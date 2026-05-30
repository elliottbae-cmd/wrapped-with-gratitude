"""Customer CRUD — used by the basket builder + Customers page."""
from __future__ import annotations

from typing import Any

from supabase import Client


def list_customers(client: Client) -> list[dict[str, Any]]:
    """All customers, alphabetical."""
    return (
        client.table("customers")
        .select(
            "id, name, email, phone, instagram_handle, "
            "shipping_address, billing_address, notes, created_at"
        )
        .order("name")
        .execute()
        .data
    )


def get_customer(client: Client, customer_id: str) -> dict[str, Any] | None:
    res = (
        client.table("customers")
        .select("*")
        .eq("id", customer_id)
        .limit(1)
        .execute()
        .data
    )
    return res[0] if res else None


def find_or_create_customer(
    client: Client,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    instagram_handle: str | None = None,
    shipping_address: str | None = None,
    billing_address: str | None = None,
) -> str:
    """Match by email first (most reliable), then by name. Create if no match.

    Backfills missing fields on the matched record so re-using a customer
    name with new info (e.g., an address she didn't have before) sticks.
    """
    name = name.strip()
    if not name:
        raise ValueError("Customer name is required")
    email = (email or "").strip() or None
    phone = (phone or "").strip() or None
    instagram_handle = (instagram_handle or "").strip() or None
    shipping_address = (shipping_address or "").strip() or None
    billing_address = (billing_address or "").strip() or None

    def _backfill(row: dict[str, Any]) -> str:
        updates: dict[str, Any] = {}
        if email and not (row.get("email") or "").strip():
            updates["email"] = email
        if phone and not (row.get("phone") or "").strip():
            updates["phone"] = phone
        if instagram_handle and not (row.get("instagram_handle") or "").strip():
            updates["instagram_handle"] = instagram_handle
        if shipping_address and not (row.get("shipping_address") or "").strip():
            updates["shipping_address"] = shipping_address
        if billing_address and not (row.get("billing_address") or "").strip():
            updates["billing_address"] = billing_address
        if updates:
            client.table("customers").update(updates).eq("id", row["id"]).execute()
        return row["id"]

    if email:
        match = (
            client.table("customers")
            .select("id, email, phone, instagram_handle, shipping_address, billing_address")
            .ilike("email", email)
            .limit(1)
            .execute()
        )
        if match.data:
            return _backfill(match.data[0])

    match = (
        client.table("customers")
        .select("id, email, phone, instagram_handle, shipping_address, billing_address")
        .ilike("name", name)
        .limit(1)
        .execute()
    )
    if match.data:
        return _backfill(match.data[0])

    payload: dict[str, Any] = {"name": name}
    if email: payload["email"] = email
    if phone: payload["phone"] = phone
    if instagram_handle: payload["instagram_handle"] = instagram_handle
    if shipping_address: payload["shipping_address"] = shipping_address
    if billing_address: payload["billing_address"] = billing_address
    created = client.table("customers").insert(payload).execute()
    return created.data[0]["id"]


def update_customer(
    client: Client,
    customer_id: str,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    instagram_handle: str | None = None,
    shipping_address: str | None = None,
    billing_address: str | None = None,
    notes: str | None = None,
) -> None:
    """Patch fields. Only explicitly passed fields get updated."""
    updates: dict[str, Any] = {}
    if name is not None:             updates["name"] = name.strip()
    if email is not None:            updates["email"] = email.strip() or None
    if phone is not None:            updates["phone"] = phone.strip() or None
    if instagram_handle is not None: updates["instagram_handle"] = instagram_handle.strip() or None
    if shipping_address is not None: updates["shipping_address"] = shipping_address.strip() or None
    if billing_address is not None:  updates["billing_address"] = billing_address.strip() or None
    if notes is not None:            updates["notes"] = notes.strip() or None
    if not updates:
        return
    client.table("customers").update(updates).eq("id", customer_id).execute()


def list_customer_order_summary(client: Client) -> list[dict[str, Any]]:
    """Customer directory enriched with order count + lifetime spend."""
    customers = list_customers(client)
    if not customers:
        return []
    orders = (
        client.table("sales_orders")
        .select("customer_id, total, status")
        .execute()
        .data
    )
    by_cid: dict[str, dict[str, Any]] = {}
    for o in orders:
        cid = o["customer_id"]
        b = by_cid.setdefault(cid, {"order_count": 0, "lifetime_spend": 0.0, "unpaid_count": 0})
        b["order_count"] += 1
        b["lifetime_spend"] += float(o["total"])
        if o["status"] == "invoiced":
            b["unpaid_count"] += 1
    for c in customers:
        agg = by_cid.get(c["id"], {})
        c["order_count"] = agg.get("order_count", 0)
        c["lifetime_spend"] = agg.get("lifetime_spend", 0.0)
        c["unpaid_count"] = agg.get("unpaid_count", 0)
    return customers
