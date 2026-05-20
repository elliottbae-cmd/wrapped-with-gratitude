"""Inventory write paths + summary reads.

Phase 1 scope: vendor/item upsert, invoice commit (header + lines + lots),
and the inventory summary used by the Inventory page.

Transactions: the supabase-py client doesn't expose multi-table transactions
over the REST API. Commits here are sequential inserts. If a mid-flight error
leaves a partial invoice, re-uploading is safe — the (vendor_id, invoice_number)
unique constraint blocks duplicates and the user can manually clean up the
partial row in Table Editor. If this becomes a real problem we'll wrap the
whole thing in a Postgres RPC function.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from supabase import Client


# ----------------------------------------------------------------------------
# Vendor + inventory item upsert
# ----------------------------------------------------------------------------

def find_or_create_vendor(client: Client, name: str) -> str:
    """Return the vendor id, creating the row if the name (case-insensitive) is new."""
    name = name.strip()
    if not name:
        raise ValueError("Vendor name is required")

    existing = (
        client.table("vendors")
        .select("id")
        .ilike("name", name)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]

    created = client.table("vendors").insert({"name": name}).execute()
    return created.data[0]["id"]


def find_or_create_inventory_item(
    client: Client,
    name: str,
    sku: str | None = None,
    category: str | None = None,
) -> str:
    """Match by SKU first, then by case-insensitive name. Create if no match.

    On match, backfills missing SKU/category on the existing record (never
    overwrites non-empty values — so the user's hand edits stick).
    """
    name = name.strip()
    sku = (sku or "").strip() or None
    category = (category or "").strip() or None

    def _backfill(item: dict[str, Any]) -> None:
        updates: dict[str, Any] = {}
        if sku and not (item.get("sku") or "").strip():
            updates["sku"] = sku
        if category and not (item.get("category") or "").strip():
            updates["category"] = category
        if updates:
            client.table("inventory_items").update(updates).eq("id", item["id"]).execute()

    if sku:
        match = (
            client.table("inventory_items")
            .select("id, sku, category")
            .eq("sku", sku)
            .limit(1)
            .execute()
        )
        if match.data:
            _backfill(match.data[0])
            return match.data[0]["id"]

    match = (
        client.table("inventory_items")
        .select("id, sku, category")
        .ilike("name", name)
        .limit(1)
        .execute()
    )
    if match.data:
        _backfill(match.data[0])
        return match.data[0]["id"]

    payload: dict[str, Any] = {"name": name}
    if sku:
        payload["sku"] = sku
    if category:
        payload["category"] = category
    created = client.table("inventory_items").insert(payload).execute()
    return created.data[0]["id"]


# ----------------------------------------------------------------------------
# Idempotency check
# ----------------------------------------------------------------------------

def find_existing_invoice(
    client: Client,
    vendor_id: str,
    invoice_number: str | None,
) -> dict[str, Any] | None:
    """Return the existing invoice row if (vendor, invoice_number) is already on file."""
    if not invoice_number:
        return None
    res = (
        client.table("invoices")
        .select("*")
        .eq("vendor_id", vendor_id)
        .eq("invoice_number", invoice_number)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ----------------------------------------------------------------------------
# Invoice commit
# ----------------------------------------------------------------------------

@dataclass
class CommitLine:
    """A line ready to post to invoice_line_items + inventory_lots.

    `qty` and `unit_price` here are already EXPANDED — i.e. they describe
    individual inventory units, not packs. The original `pack_size` is kept
    for the audit trail on invoice_line_items.
    """
    inventory_item_id: str
    description: str
    qty: Decimal              # expanded: number of individual inventory units
    unit_price: Decimal       # per individual unit
    line_subtotal: Decimal    # qty × unit_price
    allocated_shipping: Decimal
    allocated_tax: Decimal
    allocated_other: Decimal
    landed_unit_cost: Decimal # per individual unit
    pack_size: int = 1        # for audit (1 means "no pack expansion")


def _to_float(d: Decimal) -> float:
    """Supabase JSON columns expect floats, not Decimals."""
    return float(d)


def commit_invoice(
    client: Client,
    vendor_id: str,
    invoice_number: str | None,
    invoice_date: str,            # YYYY-MM-DD
    subtotal: Decimal,
    shipping: Decimal,
    tax: Decimal,
    other_charges: Decimal,
    total: Decimal,
    lines: list[CommitLine],
    pdf_path: str | None,
    raw_extracted_json: dict[str, Any] | None,
    notes: str | None = None,
    has_math_discrepancy: bool = False,
    discrepancy_detail: str | None = None,
) -> str:
    """Insert invoice + invoice_line_items + inventory_lots. Returns the invoice id.

    Status is set to 'posted' immediately — the review/edit step happens in the
    UI before this function is called, so by the time we're here the data is
    intended to be live inventory.
    """
    invoice_row = {
        "vendor_id": vendor_id,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "subtotal": _to_float(subtotal),
        "shipping": _to_float(shipping),
        "tax": _to_float(tax),
        "other_charges": _to_float(other_charges),
        "total": _to_float(total),
        "pdf_path": pdf_path,
        "raw_extracted_json": raw_extracted_json,
        "status": "posted",
        "notes": notes,
        "has_math_discrepancy": has_math_discrepancy,
        "discrepancy_detail": discrepancy_detail,
    }
    inv_res = client.table("invoices").insert(invoice_row).execute()
    invoice_id = inv_res.data[0]["id"]

    line_rows = [
        {
            "invoice_id": invoice_id,
            "inventory_item_id": line.inventory_item_id,
            "line_no": i + 1,
            "description": line.description,
            "qty": _to_float(line.qty),
            "unit_price": _to_float(line.unit_price),
            "line_subtotal": _to_float(line.line_subtotal),
            "allocated_shipping": _to_float(line.allocated_shipping),
            "allocated_tax": _to_float(line.allocated_tax),
            "allocated_other": _to_float(line.allocated_other),
            "landed_unit_cost": _to_float(line.landed_unit_cost),
            "pack_size": line.pack_size,
        }
        for i, line in enumerate(lines)
    ]
    line_res = client.table("invoice_line_items").insert(line_rows).execute()

    lot_rows = [
        {
            "inventory_item_id": line.inventory_item_id,
            "invoice_line_item_id": line_res.data[i]["id"],
            "received_date": invoice_date,
            "qty_received": _to_float(line.qty),
            "qty_remaining": _to_float(line.qty),
            "landed_unit_cost": _to_float(line.landed_unit_cost),
        }
        for i, line in enumerate(lines)
    ]
    client.table("inventory_lots").insert(lot_rows).execute()

    return invoice_id


# ----------------------------------------------------------------------------
# Storage upload
# ----------------------------------------------------------------------------

def upload_invoice_pdf(
    client: Client,
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
) -> str:
    """Upload the original invoice file to the `invoices` Storage bucket.

    Returns the object path (relative to the bucket). Caller stores this on
    `invoices.pdf_path` so the PDF can be retrieved later.
    """
    import uuid
    from pathlib import Path

    ext = Path(file_name).suffix or ".bin"
    object_path = f"{uuid.uuid4().hex}{ext}"

    client.storage.from_("invoices").upload(
        path=object_path,
        file=file_bytes,
        file_options={"content-type": mime_type, "upsert": "false"},
    )
    return object_path


# ----------------------------------------------------------------------------
# Read paths for the Inventory page
# ----------------------------------------------------------------------------

def list_inventory_summary(client: Client) -> list[dict[str, Any]]:
    """One row per inventory_item with on-hand qty + weighted-avg cost.

    Weighted average is over *open* lots only (qty_remaining > 0), so it
    reflects the cost of inventory currently on the shelf — not historical sales.
    """
    items = (
        client.table("inventory_items")
        .select("id, sku, name, category, unit_of_measure")
        .order("name")
        .execute()
        .data
    )
    if not items:
        return []

    lots = (
        client.table("inventory_lots")
        .select("inventory_item_id, qty_remaining, landed_unit_cost, received_date")
        .gt("qty_remaining", 0)
        .execute()
        .data
    )

    by_item: dict[str, list[dict[str, Any]]] = {}
    for lot in lots:
        by_item.setdefault(lot["inventory_item_id"], []).append(lot)

    out: list[dict[str, Any]] = []
    for item in items:
        item_lots = by_item.get(item["id"], [])
        on_hand = sum(float(l["qty_remaining"]) for l in item_lots)
        total_value = sum(
            float(l["qty_remaining"]) * float(l["landed_unit_cost"])
            for l in item_lots
        )
        wac = (total_value / on_hand) if on_hand > 0 else 0.0
        latest = max(
            (l for l in item_lots),
            key=lambda l: l["received_date"],
            default=None,
        )
        latest_cost = float(latest["landed_unit_cost"]) if latest else 0.0

        out.append({
            **item,
            "on_hand": on_hand,
            "open_lot_count": len(item_lots),
            "weighted_avg_cost": wac,
            "latest_landed_cost": latest_cost,
            "inventory_value": total_value,
        })
    return out


def update_inventory_item(
    client: Client,
    item_id: str,
    name: str | None = None,
    sku: str | None = None,
    category: str | None = None,
    unit_of_measure: str | None = None,
) -> None:
    """Patch an inventory_items row. Only fields explicitly passed get updated."""
    updates: dict[str, Any] = {}
    if name is not None:
        updates["name"] = name.strip()
    if sku is not None:
        updates["sku"] = sku.strip() or None
    if category is not None:
        updates["category"] = category.strip() or None
    if unit_of_measure is not None:
        updates["unit_of_measure"] = unit_of_measure.strip() or "each"
    if not updates:
        return
    client.table("inventory_items").update(updates).eq("id", item_id).execute()


def list_flagged_invoices(client: Client) -> list[dict[str, Any]]:
    """Invoices that were committed despite math discrepancies — newest first."""
    res = (
        client.table("invoices")
        .select("id, invoice_number, invoice_date, vendor_id, total, "
                "discrepancy_detail, notes, created_at")
        .eq("has_math_discrepancy", True)
        .order("invoice_date", desc=True)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return []
    # Hydrate vendor names in one query
    vendor_ids = list({r["vendor_id"] for r in rows})
    vendors = (
        client.table("vendors")
        .select("id, name")
        .in_("id", vendor_ids)
        .execute()
        .data
    )
    by_vid = {v["id"]: v["name"] for v in vendors}
    for r in rows:
        r["vendor_name"] = by_vid.get(r["vendor_id"], "—")
    return rows


def count_flagged_invoices(client: Client) -> int:
    res = (
        client.table("invoices")
        .select("id", count="exact")
        .eq("has_math_discrepancy", True)
        .execute()
    )
    return res.count or 0


def list_lots_for_item(client: Client, inventory_item_id: str) -> list[dict[str, Any]]:
    """All lots for an item, oldest first — matches FIFO consumption order."""
    return (
        client.table("inventory_lots")
        .select(
            "id, received_date, qty_received, qty_remaining, landed_unit_cost, "
            "invoice_line_item_id"
        )
        .eq("inventory_item_id", inventory_item_id)
        .order("received_date")
        .order("id")
        .execute()
        .data
    )
