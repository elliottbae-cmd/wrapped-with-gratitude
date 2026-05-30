"""Sales order commit + FIFO consumption from inventory_lots.

The supabase-py REST client can't do multi-table transactions, so commits
here are sequential inserts/updates. For a single-user MVP that's OK; if
two users were committing simultaneously, lot decrements could race. To
fix properly later: wrap commit_sale in a Postgres RPC function.

Flow:
  1. plan_fifo_consumption(item, qty) — read-only; figures out which lots
     to pull from and what the COGS is, without touching the DB.
  2. cost_basket(lines) — runs the above for every basket line.
  3. commit_sale(...) — inserts sales_order, sales_order_lines, lot_consumptions,
     then decrements each inventory_lot.qty_remaining.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from supabase import Client


_MONEY = Decimal("0.01")
_RATE  = Decimal("0.0001")


def _r(value: Decimal, q: Decimal = _MONEY) -> Decimal:
    return value.quantize(q, rounding=ROUND_HALF_UP)


# ----------------------------------------------------------------------------
# Domain types
# ----------------------------------------------------------------------------

@dataclass
class BasketLine:
    """User input — picked from the basket builder UI."""
    inventory_item_id: str
    description: str
    qty: Decimal


@dataclass
class ConsumptionPlan:
    """Planned draw against a single lot — not yet persisted."""
    lot_id: str
    qty_consumed: Decimal
    unit_cost: Decimal


@dataclass
class CostedLine:
    """A basket line ready to commit.

    - line_type='product' has inventory_item_id, FIFO consumptions, and a
      computed total_cogs from the lots.
    - line_type='service' has no inventory_item_id, no consumptions, and
      total_cogs=0 (labor has no cost basis in this MVP).
    """
    description: str
    qty: Decimal
    line_type: str = "product"           # 'product' or 'service'
    inventory_item_id: str | None = None
    total_cogs: Decimal = Decimal("0")
    consumptions: list[ConsumptionPlan] = field(default_factory=list)


class InsufficientInventory(Exception):
    """Raised when a basket line asks for more than on-hand."""
    def __init__(self, item_id: str, needed: Decimal, available: Decimal, description: str = ""):
        self.item_id = item_id
        self.needed = needed
        self.available = available
        self.description = description
        super().__init__(
            f"'{description or item_id}': need {needed}, only {available} available"
        )


# ----------------------------------------------------------------------------
# FIFO planning — read-only
# ----------------------------------------------------------------------------

def plan_fifo_consumption(
    client: Client,
    inventory_item_id: str,
    qty_needed: Decimal,
    description: str = "",
) -> tuple[list[ConsumptionPlan], Decimal]:
    """Walk open lots oldest-first, planning how to satisfy `qty_needed`.

    Returns (consumption_plans, total_cogs).
    Raises InsufficientInventory if open lots can't cover `qty_needed`.
    """
    lots = (
        client.table("inventory_lots")
        .select("id, qty_remaining, landed_unit_cost")
        .eq("inventory_item_id", inventory_item_id)
        .gt("qty_remaining", 0)
        .order("received_date")
        .order("id")
        .execute()
        .data
    )

    plans: list[ConsumptionPlan] = []
    remaining = qty_needed
    total_cogs = Decimal("0")
    available_total = Decimal("0")

    for lot in lots:
        available_total += Decimal(str(lot["qty_remaining"]))
        if remaining <= 0:
            continue
        avail = Decimal(str(lot["qty_remaining"]))
        take = avail if avail < remaining else remaining
        unit_cost = Decimal(str(lot["landed_unit_cost"]))
        plans.append(ConsumptionPlan(
            lot_id=lot["id"],
            qty_consumed=take,
            unit_cost=unit_cost,
        ))
        total_cogs += take * unit_cost
        remaining -= take

    if remaining > 0:
        raise InsufficientInventory(
            item_id=inventory_item_id,
            needed=qty_needed,
            available=available_total,
            description=description,
        )

    return plans, _r(total_cogs)


def cost_basket(
    client: Client,
    lines: list[BasketLine],
) -> list[CostedLine]:
    """Compute FIFO cost basis for every PRODUCT line. Raises at the first short line.

    Use `as_service_line(description, qty)` to wrap a free-form labor/service
    line as a CostedLine — this function is only for inventory-backed lines.
    """
    out: list[CostedLine] = []
    for line in lines:
        plans, cogs = plan_fifo_consumption(
            client, line.inventory_item_id, line.qty, line.description
        )
        out.append(CostedLine(
            line_type="product",
            inventory_item_id=line.inventory_item_id,
            description=line.description,
            qty=line.qty,
            total_cogs=cogs,
            consumptions=plans,
        ))
    return out


def as_service_line(description: str, qty: Decimal) -> CostedLine:
    """Build a service/labor CostedLine — no inventory, no COGS."""
    return CostedLine(
        line_type="service",
        inventory_item_id=None,
        description=description.strip(),
        qty=qty,
        total_cogs=Decimal("0"),
        consumptions=[],
    )


# ----------------------------------------------------------------------------
# Order number
# ----------------------------------------------------------------------------

def next_order_number(client: Client, when: date | None = None) -> str:
    """Format: WG-YYYY-NNN. NNN = count of sales_orders in `when`'s year, plus one."""
    when = when or date.today()
    year_start = date(when.year, 1, 1).isoformat()
    next_year_start = date(when.year + 1, 1, 1).isoformat()
    res = (
        client.table("sales_orders")
        .select("id", count="exact")
        .gte("order_date", year_start)
        .lt("order_date", next_year_start)
        .execute()
    )
    count = res.count or 0
    return f"WG-{when.year}-{count + 1:03d}"


# ----------------------------------------------------------------------------
# Commit
# ----------------------------------------------------------------------------

def commit_sale(
    client: Client,
    customer_id: str,
    costed_lines: list[CostedLine],
    line_unit_prices: list[Decimal],  # customer-facing per-unit prices
    markup_pct: Decimal,
    shipping_charge: Decimal,
    sales_tax: Decimal,
    order_date: date | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Insert sales_order + lines + lot_consumptions; decrement inventory_lots.

    Returns: {order_id, order_number, subtotal_cogs, subtotal_price, total}
    """
    if len(line_unit_prices) != len(costed_lines):
        raise ValueError("line_unit_prices must match costed_lines length")

    order_date = order_date or date.today()
    order_number = next_order_number(client, order_date)

    subtotal_cogs = _r(sum((cl.total_cogs for cl in costed_lines), Decimal("0")))
    subtotal_price = _r(sum(
        (line_unit_prices[i] * cl.qty for i, cl in enumerate(costed_lines)),
        Decimal("0"),
    ))
    total = _r(subtotal_price + shipping_charge + sales_tax)

    # 1. Header
    order_row = {
        "order_number": order_number,
        "customer_id": customer_id,
        "order_date": order_date.isoformat(),
        "subtotal_cogs": float(subtotal_cogs),
        "markup_pct": float(markup_pct),
        "subtotal_price": float(subtotal_price),
        "shipping_charge": float(shipping_charge),
        "sales_tax": float(sales_tax),
        "total": float(total),
        "status": "invoiced",
        "payment_method": "venmo",
        "notes": notes,
    }
    order_res = client.table("sales_orders").insert(order_row).execute()
    order_id = order_res.data[0]["id"]

    # 2. Lines — product lines reference inventory_item_id; service lines store
    # their free-form description and have a NULL inventory_item_id.
    line_rows = [
        {
            "sales_order_id": order_id,
            "inventory_item_id": cl.inventory_item_id,
            "line_no": i + 1,
            "line_type": cl.line_type,
            "description": cl.description if cl.line_type == "service" else None,
            "qty": float(cl.qty),
            "unit_price_at_sale": float(line_unit_prices[i]),
            "total_cogs": float(cl.total_cogs),
        }
        for i, cl in enumerate(costed_lines)
    ]
    line_res = client.table("sales_order_lines").insert(line_rows).execute()

    # 3. lot_consumptions — only product lines have consumptions
    consumption_rows = []
    for i, cl in enumerate(costed_lines):
        if cl.line_type != "product":
            continue
        sol_id = line_res.data[i]["id"]
        for plan in cl.consumptions:
            consumption_rows.append({
                "sales_order_line_id": sol_id,
                "inventory_lot_id": plan.lot_id,
                "qty_consumed": float(plan.qty_consumed),
                "unit_cost": float(plan.unit_cost),
            })
    if consumption_rows:
        client.table("lot_consumptions").insert(consumption_rows).execute()

    # 4. Decrement inventory_lots — products only
    lot_draws: dict[str, Decimal] = {}
    for cl in costed_lines:
        if cl.line_type != "product":
            continue
        for plan in cl.consumptions:
            lot_draws[plan.lot_id] = lot_draws.get(plan.lot_id, Decimal("0")) + plan.qty_consumed

    for lot_id, draw in lot_draws.items():
        current = (
            client.table("inventory_lots")
            .select("qty_remaining")
            .eq("id", lot_id)
            .limit(1)
            .execute()
            .data
        )
        if not current:
            continue
        new_remaining = Decimal(str(current[0]["qty_remaining"])) - draw
        if new_remaining < 0:
            new_remaining = Decimal("0")
        client.table("inventory_lots").update(
            {"qty_remaining": float(new_remaining)}
        ).eq("id", lot_id).execute()

    return {
        "order_id": order_id,
        "order_number": order_number,
        "subtotal_cogs": subtotal_cogs,
        "subtotal_price": subtotal_price,
        "total": total,
    }


def attach_pdf_path(client: Client, order_id: str, pdf_path: str) -> None:
    client.table("sales_orders").update({"pdf_path": pdf_path}).eq("id", order_id).execute()


def upload_customer_invoice_pdf(
    client: Client,
    file_bytes: bytes,
    order_number: str,
) -> str:
    """Upload generated PDF to the `customer-invoices` Storage bucket."""
    import uuid
    object_path = f"{order_number}-{uuid.uuid4().hex[:8]}.pdf"
    client.storage.from_("customer-invoices").upload(
        path=object_path,
        file=file_bytes,
        file_options={"content-type": "application/pdf", "upsert": "false"},
    )
    return object_path


def download_customer_invoice_pdf(client: Client, pdf_path: str) -> bytes:
    return client.storage.from_("customer-invoices").download(pdf_path)


# ----------------------------------------------------------------------------
# Read paths
# ----------------------------------------------------------------------------

def list_sales(client: Client, status_filter: str | None = None) -> list[dict[str, Any]]:
    """Sales orders newest-first, with customer name hydrated."""
    q = (
        client.table("sales_orders")
        .select(
            "id, order_number, customer_id, order_date, subtotal_cogs, "
            "subtotal_price, shipping_charge, sales_tax, total, status, "
            "paid_date, pdf_path, created_at"
        )
        .order("order_date", desc=True)
        .order("created_at", desc=True)
    )
    if status_filter:
        q = q.eq("status", status_filter)
    orders = q.execute().data
    if not orders:
        return []

    cids = list({o["customer_id"] for o in orders})
    customers = (
        client.table("customers")
        .select("id, name, email")
        .in_("id", cids)
        .execute()
        .data
    )
    by_cid = {c["id"]: c for c in customers}
    for o in orders:
        c = by_cid.get(o["customer_id"], {})
        o["customer_name"] = c.get("name", "—")
        o["customer_email"] = c.get("email")
    return orders


def get_sale_detail(client: Client, order_id: str) -> dict[str, Any] | None:
    res = (
        client.table("sales_orders")
        .select("*")
        .eq("id", order_id)
        .limit(1)
        .execute()
        .data
    )
    if not res:
        return None
    order = res[0]

    customer = (
        client.table("customers")
        .select("*")
        .eq("id", order["customer_id"])
        .limit(1)
        .execute()
        .data
    )
    order["customer"] = customer[0] if customer else None

    lines = (
        client.table("sales_order_lines")
        .select("*")
        .eq("sales_order_id", order_id)
        .order("line_no")
        .execute()
        .data
    )
    if lines:
        # Only join inventory_items for product lines
        iids = list({l["inventory_item_id"] for l in lines if l.get("inventory_item_id")})
        items = (
            client.table("inventory_items")
            .select("id, name, sku, unit_of_measure")
            .in_("id", iids)
            .execute()
            .data
        ) if iids else []
        by_iid = {i["id"]: i for i in items}
        for l in lines:
            if l.get("line_type", "product") == "service":
                l["item_name"]       = l.get("description") or "Service"
                l["sku"]             = None
                l["unit_of_measure"] = "ea"
            else:
                item = by_iid.get(l["inventory_item_id"], {})
                l["item_name"]       = item.get("name", "—")
                l["sku"]             = item.get("sku")
                l["unit_of_measure"] = item.get("unit_of_measure", "each")
    order["lines"] = lines
    return order


def mark_paid(client: Client, order_id: str, paid_date: date | None = None) -> None:
    paid_date = paid_date or date.today()
    client.table("sales_orders").update({
        "status": "paid",
        "paid_date": paid_date.isoformat(),
    }).eq("id", order_id).execute()


def count_unpaid(client: Client) -> int:
    res = (
        client.table("sales_orders")
        .select("id", count="exact")
        .eq("status", "invoiced")
        .execute()
    )
    return res.count or 0


def sum_unpaid(client: Client) -> float:
    rows = (
        client.table("sales_orders")
        .select("total")
        .eq("status", "invoiced")
        .execute()
        .data
    )
    return float(sum((float(r["total"]) for r in rows), 0.0))
