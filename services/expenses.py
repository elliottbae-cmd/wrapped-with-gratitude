"""Operating expenses CRUD + period aggregates.

These feed the P&L (operating expenses line + net income), the BS (cash
position), and the cash flow report.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from supabase import Client


# Curated category list. Free-form would create messy duplicates ("Software"
# vs "software" vs "subscriptions"); this keeps the categorization tight.
CATEGORIES: list[str] = [
    "Software & Subscriptions",
    "Packaging & Materials",
    "Shipping & Postage",
    "Marketing & Advertising",
    "Office & Supplies",
    "Bank & Payment Fees",
    "Professional Services",
    "Other",
]


def list_expenses(
    client: Client,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    q = (
        client.table("operating_expenses")
        .select("*")
        .order("expense_date", desc=True)
        .order("created_at", desc=True)
    )
    if start_date:
        q = q.gte("expense_date", start_date.isoformat())
    if end_date:
        q = q.lte("expense_date", end_date.isoformat())
    if category:
        q = q.eq("category", category)
    return q.execute().data or []


def create_expense(
    client: Client,
    expense_date: date,
    category: str,
    amount: float,
    vendor: str | None = None,
    description: str | None = None,
    payment_method: str | None = None,
    notes: str | None = None,
) -> str:
    row = {
        "expense_date":   expense_date.isoformat(),
        "category":       category,
        "amount":         float(amount),
        "vendor":         (vendor or "").strip() or None,
        "description":    (description or "").strip() or None,
        "payment_method": (payment_method or "").strip() or None,
        "notes":          (notes or "").strip() or None,
    }
    res = client.table("operating_expenses").insert(row).execute()
    return res.data[0]["id"]


def update_expense(client: Client, expense_id: str, **fields) -> None:
    updates: dict[str, Any] = {}
    for k in ("expense_date", "category", "vendor", "description",
              "amount", "payment_method", "notes"):
        if k in fields and fields[k] is not None:
            v = fields[k]
            if k == "expense_date" and isinstance(v, date):
                updates[k] = v.isoformat()
            elif isinstance(v, str):
                updates[k] = v.strip() or None
            else:
                updates[k] = v
    if updates:
        client.table("operating_expenses").update(updates).eq("id", expense_id).execute()


def delete_expense(client: Client, expense_id: str) -> None:
    client.table("operating_expenses").delete().eq("id", expense_id).execute()


def sum_in_period(
    client: Client,
    start_date: date,
    end_date: date,
) -> float:
    rows = (
        client.table("operating_expenses")
        .select("amount")
        .gte("expense_date", start_date.isoformat())
        .lte("expense_date", end_date.isoformat())
        .execute()
        .data
        or []
    )
    return float(sum(float(r["amount"]) for r in rows))


def sum_to_date(client: Client, as_of: date) -> float:
    rows = (
        client.table("operating_expenses")
        .select("amount")
        .lte("expense_date", as_of.isoformat())
        .execute()
        .data
        or []
    )
    return float(sum(float(r["amount"]) for r in rows))


def by_category_in_period(
    client: Client,
    start_date: date,
    end_date: date,
) -> dict[str, float]:
    rows = (
        client.table("operating_expenses")
        .select("category, amount")
        .gte("expense_date", start_date.isoformat())
        .lte("expense_date", end_date.isoformat())
        .execute()
        .data
        or []
    )
    out: dict[str, float] = {}
    for r in rows:
        cat = r.get("category") or "Other"
        out[cat] = out.get(cat, 0.0) + float(r["amount"])
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))
