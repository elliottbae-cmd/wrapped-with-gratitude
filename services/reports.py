"""Period reporting — P&L, Balance Sheet, and a simple cash flow summary.

No new schema required. Everything comes from invoices, sales_orders,
sales_order_lines, inventory_lots.

Accounting choices for MVP:
- Period P&L can be run on accrual basis (by order_date) or cash basis
  (by paid_date, paid orders only).
- BS inventory value is a CURRENT snapshot of inventory_lots.qty_remaining
  × landed_unit_cost. Strict historical valuation would need a snapshot
  table; this is good enough for monthly close at small scale.
- Cash position model: collected from customers (paid orders) minus
  vendor invoice totals (assumes she paid each invoice at receipt). We
  don't track vendor AP yet; this is a "best guess at runway" number,
  not a true cash balance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from supabase import Client


@dataclass
class PLResult:
    basis: str                  # "accrual" or "cash"
    start_date: date
    end_date: date
    order_count: int
    revenue: float              # subtotal_price (no shipping pass-through, no tax)
    shipping_collected: float   # not revenue; tracked for reconciliation
    tax_collected: float        # not revenue; sales tax pass-through
    cogs: float
    gross_profit: float
    gross_margin_pct: float
    avg_order_value: float


def pl_for_period(
    client: Client,
    start_date: date,
    end_date: date,
    basis: str = "accrual",
) -> PLResult:
    """Period P&L. `basis` = 'accrual' (by order_date, all non-void)
    or 'cash' (by paid_date, only paid orders)."""
    q = (
        client.table("sales_orders")
        .select("subtotal_price, subtotal_cogs, shipping_charge, sales_tax, status, order_date, paid_date")
    )
    if basis == "cash":
        q = q.eq("status", "paid").gte("paid_date", start_date.isoformat()).lte("paid_date", end_date.isoformat())
    else:
        q = q.neq("status", "void").gte("order_date", start_date.isoformat()).lte("order_date", end_date.isoformat())

    orders = q.execute().data or []

    revenue   = sum(float(o["subtotal_price"]) for o in orders)
    cogs      = sum(float(o["subtotal_cogs"])  for o in orders)
    shipping  = sum(float(o.get("shipping_charge") or 0) for o in orders)
    tax       = sum(float(o.get("sales_tax") or 0)       for o in orders)
    gross     = revenue - cogs
    gm        = (gross / revenue * 100) if revenue > 0 else 0.0
    aov       = (revenue / len(orders))  if orders     else 0.0

    return PLResult(
        basis=basis,
        start_date=start_date,
        end_date=end_date,
        order_count=len(orders),
        revenue=revenue,
        shipping_collected=shipping,
        tax_collected=tax,
        cogs=cogs,
        gross_profit=gross,
        gross_margin_pct=gm,
        avg_order_value=aov,
    )


@dataclass
class BSResult:
    as_of: date
    # Assets
    inventory_at_cost: float
    accounts_receivable: float       # invoiced + unpaid as of date
    cash: float                      # collected from customer payments
    total_assets: float
    # Equity (no AP tracking yet, so liabilities = $0)
    capital_contribution: float      # owner-funded; equal to inventory purchases to date
    retained_earnings: float         # = total_assets − capital_contribution (= cumulative profit)
    total_equity: float              # = capital_contribution + retained_earnings
    # Supporting context
    inventory_unit_count: float
    open_lot_count: int
    ar_order_count: int


def bs_as_of(client: Client, as_of: date) -> BSResult:
    """Balance Sheet snapshot.

    Accounting model assumed for MVP:
      - The owner personally funded every vendor invoice received to date,
        recorded as a Capital Contribution.
      - Cash on the BS = customer payments collected (since contribution
        offsets vendor purchases).
      - Retained Earnings = Total Assets − Capital Contribution
        (which works out to cumulative gross profit on closed sales).
    """
    iso = as_of.isoformat()

    # --- Inventory at landed cost (current snapshot) ----
    lots = (
        client.table("inventory_lots")
        .select("qty_remaining, landed_unit_cost")
        .gt("qty_remaining", 0)
        .execute()
        .data
        or []
    )
    inventory_value = sum(
        float(l["qty_remaining"]) * float(l["landed_unit_cost"]) for l in lots
    )
    inventory_units = sum(float(l["qty_remaining"]) for l in lots)
    open_lots = len(lots)

    # --- A/R: invoiced (not paid, not void) with order_date <= as_of ----
    ar_rows = (
        client.table("sales_orders")
        .select("total")
        .eq("status", "invoiced")
        .lte("order_date", iso)
        .execute()
        .data
        or []
    )
    ar = sum(float(r["total"]) for r in ar_rows)

    # --- Cash collected from customers up to as_of ----
    paid_rows = (
        client.table("sales_orders")
        .select("total")
        .eq("status", "paid")
        .lte("paid_date", iso)
        .execute()
        .data
        or []
    )
    cash = sum(float(r["total"]) for r in paid_rows)

    # --- Capital contribution: owner-funded inventory purchases to date ----
    purch_rows = (
        client.table("invoices")
        .select("total")
        .lte("invoice_date", iso)
        .execute()
        .data
        or []
    )
    capital = sum(float(r["total"]) for r in purch_rows)

    total_assets = inventory_value + ar + cash
    retained = total_assets - capital
    total_equity = capital + retained  # equals total_assets by construction

    return BSResult(
        as_of=as_of,
        inventory_at_cost=inventory_value,
        accounts_receivable=ar,
        cash=cash,
        total_assets=total_assets,
        capital_contribution=capital,
        retained_earnings=retained,
        total_equity=total_equity,
        inventory_unit_count=inventory_units,
        open_lot_count=open_lots,
        ar_order_count=len(ar_rows),
    )


@dataclass
class CashFlowResult:
    start_date: date
    end_date: date
    cash_in: float                   # customer payments received in period
    cash_out: float                  # vendor invoices received in period (assumed paid)
    net_change: float
    payment_count: int
    purchase_count: int


def cash_flow_for_period(
    client: Client,
    start_date: date,
    end_date: date,
) -> CashFlowResult:
    """Simple cash flow: payments collected vs. vendor invoices received."""
    start_iso, end_iso = start_date.isoformat(), end_date.isoformat()

    paid = (
        client.table("sales_orders")
        .select("total")
        .eq("status", "paid")
        .gte("paid_date", start_iso)
        .lte("paid_date", end_iso)
        .execute()
        .data
        or []
    )
    cash_in = sum(float(r["total"]) for r in paid)

    purch = (
        client.table("invoices")
        .select("total")
        .gte("invoice_date", start_iso)
        .lte("invoice_date", end_iso)
        .execute()
        .data
        or []
    )
    cash_out = sum(float(r["total"]) for r in purch)

    return CashFlowResult(
        start_date=start_date,
        end_date=end_date,
        cash_in=cash_in,
        cash_out=cash_out,
        net_change=cash_in - cash_out,
        payment_count=len(paid),
        purchase_count=len(purch),
    )


# ----------------------------------------------------------------------------
# Period presets
# ----------------------------------------------------------------------------

def quarter_start(d: date) -> date:
    q = (d.month - 1) // 3
    return date(d.year, q * 3 + 1, 1)


def period_preset(name: str, today: date | None = None) -> tuple[date, date]:
    """Return (start, end) for common preset labels. End is inclusive."""
    today = today or date.today()
    if name == "This month":
        start = today.replace(day=1)
        return start, today
    if name == "Last month":
        first_of_this = today.replace(day=1)
        # last day of previous month
        from datetime import timedelta
        last_of_last = first_of_this - timedelta(days=1)
        start = last_of_last.replace(day=1)
        return start, last_of_last
    if name == "Quarter to date":
        return quarter_start(today), today
    if name == "Year to date":
        return date(today.year, 1, 1), today
    if name == "All time":
        return date(2020, 1, 1), today
    raise ValueError(f"Unknown preset: {name}")


def top_items_by_revenue(
    client: Client,
    start_date: date,
    end_date: date,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Most-sold items in the period, by revenue (cash basis on order_date)."""
    orders = (
        client.table("sales_orders")
        .select("id")
        .neq("status", "void")
        .gte("order_date", start_date.isoformat())
        .lte("order_date", end_date.isoformat())
        .execute()
        .data
        or []
    )
    if not orders:
        return []
    order_ids = [o["id"] for o in orders]
    lines = (
        client.table("sales_order_lines")
        .select("inventory_item_id, qty, unit_price_at_sale, total_cogs")
        .in_("sales_order_id", order_ids)
        .execute()
        .data
        or []
    )
    if not lines:
        return []

    agg: dict[str, dict[str, float]] = {}
    for l in lines:
        iid = l["inventory_item_id"]
        if iid is None:
            # Service/labor line — no inventory_item to attribute to. Skip from
            # this report; service revenue still rolls up via the P&L card.
            continue
        a = agg.setdefault(iid, {"qty": 0.0, "revenue": 0.0, "cogs": 0.0})
        q = float(l["qty"])
        a["qty"]     += q
        a["revenue"] += q * float(l["unit_price_at_sale"])
        a["cogs"]    += float(l["total_cogs"])

    item_ids = list(agg.keys())
    items = (
        client.table("inventory_items")
        .select("id, name, sku")
        .in_("id", item_ids)
        .execute()
        .data
        or []
    )
    name_by_id = {i["id"]: i["name"] for i in items}

    rows = [
        {
            "item":    name_by_id.get(iid, "—"),
            "qty":     a["qty"],
            "revenue": a["revenue"],
            "cogs":    a["cogs"],
            "profit":  a["revenue"] - a["cogs"],
            "margin_pct": ((a["revenue"] - a["cogs"]) / a["revenue"] * 100) if a["revenue"] > 0 else 0.0,
        }
        for iid, a in agg.items()
    ]
    rows.sort(key=lambda r: r["revenue"], reverse=True)
    return rows[:limit]
