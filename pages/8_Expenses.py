"""Operating expenses — add, list, edit, delete."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from services import expenses as exp
from ui.auth import get_client, is_admin, require_auth, sidebar_user_info


st.set_page_config(page_title="Operating Expenses", page_icon="💳", layout="wide")
require_auth()

st.title("💳 Operating Expenses")
st.caption(
    "Record one-off and recurring business expenses. Flows into the P&L "
    "(net income), the balance sheet (cash), and the cash flow report."
)

client = get_client()
admin = is_admin()


@st.cache_data(ttl=20, show_spinner=False)
def _list(_client, start_iso: str | None, end_iso: str | None, category: str | None, cache_key: str):
    return exp.list_expenses(
        _client,
        start_date=date.fromisoformat(start_iso) if start_iso else None,
        end_date=date.fromisoformat(end_iso) if end_iso else None,
        category=category,
    )


cache_key = st.session_state["access_token"]

# ---- Add expense ----------------------------------------------------
with st.expander("➕ Add an expense", expanded=False):
    with st.form("new_expense", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        with f1:
            n_date = st.date_input("Date *", value=date.today())
        with f2:
            n_cat = st.selectbox("Category *", options=exp.CATEGORIES)
        with f3:
            n_amount = st.number_input("Amount ($) *", min_value=0.01, value=10.00, step=1.00, format="%.2f")

        f4, f5 = st.columns(2)
        with f4:
            n_vendor = st.text_input("Vendor", placeholder="e.g., Replicate, USPS, Etsy")
        with f5:
            n_pay = st.text_input("Payment method", placeholder="e.g., Card ending 4014, Venmo")

        n_desc = st.text_input("Description", placeholder="What was this for?")
        n_notes = st.text_area("Notes (optional)", height=70)

        submitted = st.form_submit_button("Save expense", type="primary")
        if submitted:
            exp.create_expense(
                client,
                expense_date=n_date,
                category=n_cat,
                amount=n_amount,
                vendor=n_vendor,
                description=n_desc,
                payment_method=n_pay,
                notes=n_notes,
            )
            _list.clear()
            st.success(f"Logged ${n_amount:,.2f} to {n_cat}.")
            st.rerun()

# ---- Filters --------------------------------------------------------
st.divider()
st.subheader("Expense log")

fc1, fc2, fc3, fc4 = st.columns([1.5, 1.5, 2, 2])
with fc1:
    default_start = date.today().replace(day=1) - timedelta(days=180)  # ~6 months back
    f_start = st.date_input("From", value=default_start, key="exp_from")
with fc2:
    f_end = st.date_input("To", value=date.today(), key="exp_to")
with fc3:
    f_cat = st.selectbox(
        "Category filter",
        options=["All categories"] + exp.CATEGORIES,
        key="exp_cat_filter",
    )

cat_arg = None if f_cat == "All categories" else f_cat
rows = _list(client, f_start.isoformat(), f_end.isoformat(), cat_arg, cache_key)

if not rows:
    st.info("No expenses logged for the current filters.")
    st.stop()

df = pd.DataFrame(rows)
for col in ("vendor", "description", "payment_method", "notes"):
    if col in df.columns:
        df[col] = df[col].fillna("")

# Supabase returns expense_date as an ISO string; DateColumn needs date objects
if "expense_date" in df.columns:
    df["expense_date"] = pd.to_datetime(df["expense_date"]).dt.date

# ---- Summary metrics ------------------------------------------------
total_filtered = float(df["amount"].sum())
m1, m2, m3 = st.columns(3)
m1.metric("Filtered total", f"${total_filtered:,.2f}")
m2.metric("Count", len(df))
by_cat = df.groupby("category")["amount"].sum().sort_values(ascending=False)
if len(by_cat):
    top_cat = by_cat.index[0]
    m3.metric("Largest category", f"{top_cat}", delta=f"${by_cat.iloc[0]:,.2f}", delta_color="off")

# ---- Editable table -------------------------------------------------
st.caption("Edit any field inline (except id). Click trash icon in a row to remove. Use Save below to commit.")

display_cols = ["id", "expense_date", "category", "vendor", "description", "amount", "payment_method", "notes"]
for c in display_cols:
    if c not in df.columns:
        df[c] = "" if c not in ("amount",) else 0.0

original = df[display_cols].copy()

edited = st.data_editor(
    df[display_cols],
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    column_config={
        "id":             None,
        "expense_date":   st.column_config.DateColumn("Date", required=True),
        "category":       st.column_config.SelectboxColumn("Category", options=exp.CATEGORIES, required=True),
        "vendor":         st.column_config.TextColumn("Vendor"),
        "description":    st.column_config.TextColumn("Description", width="large"),
        "amount":         st.column_config.NumberColumn("Amount", format="$%.2f", min_value=0.01, required=True),
        "payment_method": st.column_config.TextColumn("Payment"),
        "notes":          st.column_config.TextColumn("Notes"),
    },
    key="exp_editor",
)

# Detect edits and deletions — work with plain dicts to dodge pandas Series gotchas.
original_records: list[dict] = original.to_dict("records")
edited_records: list[dict] = edited.to_dict("records")


def _is_blank_id(v) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s == "" or s.lower() == "nan"


orig_by_id: dict[str, dict] = {
    str(r["id"]): r for r in original_records if not _is_blank_id(r.get("id"))
}
edited_ids: set[str] = {
    str(r["id"]) for r in edited_records if not _is_blank_id(r.get("id"))
}

original_ids = set(orig_by_id.keys())
deleted_ids = original_ids - edited_ids

edits: list[tuple[str, dict]] = []
for r in edited_records:
    if _is_blank_id(r.get("id")):
        continue
    rid = str(r["id"])
    orig = orig_by_id.get(rid)
    if orig is None:
        continue
    changed: dict = {}
    for f in ("expense_date", "category", "vendor", "description",
              "amount", "payment_method", "notes"):
        if str(orig.get(f, "")) != str(r.get(f, "")):
            changed[f] = r.get(f)
    if changed:
        edits.append((rid, changed))

if edits or deleted_ids:
    pending = []
    if edits:        pending.append(f"{len(edits)} edit(s)")
    if deleted_ids:  pending.append(f"{len(deleted_ids)} delete(s)")
    st.info(f"Unsaved: {', '.join(pending)}.")

    sv1, sv2, _ = st.columns([1, 1, 4])
    with sv1:
        save_clicked = st.button("Save changes", type="primary", use_container_width=True)
    with sv2:
        discard_clicked = st.button("Discard", use_container_width=True)

    if discard_clicked:
        st.session_state.pop("exp_editor", None)
        st.rerun()

    if save_clicked:
        with st.spinner("Saving…"):
            for rid, changes in edits:
                exp.update_expense(client, rid, **changes)
            for rid in deleted_ids:
                exp.delete_expense(client, rid)
        _list.clear()
        st.success("Saved.")
        st.rerun()

# ---- By category breakdown -----------------------------------------
st.divider()
st.subheader("By category")
cat_df = (
    df.groupby("category")["amount"]
    .agg(["sum", "count"])
    .rename(columns={"sum": "Total", "count": "Count"})
    .sort_values("Total", ascending=False)
    .reset_index()
)
st.dataframe(
    cat_df,
    column_config={
        "category": st.column_config.TextColumn("Category"),
        "Total":    st.column_config.NumberColumn("Total", format="$%.2f"),
        "Count":    st.column_config.NumberColumn("Count", format="%d"),
    },
    use_container_width=True,
    hide_index=True,
)
