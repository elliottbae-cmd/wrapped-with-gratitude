"""Customers directory — list, add, edit inline."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services import customers
from ui.auth import get_client, require_auth, sidebar_user_info


st.set_page_config(page_title="Customers", page_icon="👥", layout="wide")
require_auth()
sidebar_user_info()

st.title("👥 Customers")

client = get_client()


@st.cache_data(ttl=30, show_spinner=False)
def _summary(_client, cache_key: str):
    return customers.list_customer_order_summary(_client)


cache_key = st.session_state["access_token"]

# ---- Add new ---------------------------------------------------------
with st.expander("➕ Add a new customer"):
    with st.form("new_customer", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            n_name = st.text_input("Name *")
            n_email = st.text_input("Email")
            n_phone = st.text_input("Phone")
        with c2:
            n_ig = st.text_input("Instagram handle (without @)")
            n_ship = st.text_area("Shipping address", height=80)
            n_bill = st.text_area("Billing address (if different)", height=80)
        submitted = st.form_submit_button("Create customer", type="primary")
        if submitted:
            if not n_name.strip():
                st.error("Name is required.")
            else:
                customers.find_or_create_customer(
                    client,
                    name=n_name,
                    email=n_email,
                    phone=n_phone,
                    instagram_handle=n_ig,
                    shipping_address=n_ship,
                    billing_address=n_bill,
                )
                _summary.clear()
                st.success(f"Added {n_name}.")
                st.rerun()

# ---- Directory -------------------------------------------------------
data = _summary(client, cache_key)
if not data:
    st.info("No customers yet. Add one above or create from the New Sale page.")
    st.stop()

df = pd.DataFrame(data)
for col in ("name", "email", "phone", "instagram_handle", "shipping_address", "billing_address", "notes"):
    if col not in df.columns:
        df[col] = ""
    df[col] = df[col].fillna("")

original = df[[
    "id", "name", "email", "phone", "instagram_handle",
    "shipping_address", "billing_address", "notes",
]].copy()

display_cols = [
    "id", "name", "email", "phone", "instagram_handle",
    "shipping_address", "billing_address", "notes",
    "order_count", "lifetime_spend", "unpaid_count",
]
column_config = {
    "id":                None,  # hide
    "name":              st.column_config.TextColumn("Name", width="medium", required=True),
    "email":             st.column_config.TextColumn("Email"),
    "phone":             st.column_config.TextColumn("Phone"),
    "instagram_handle":  st.column_config.TextColumn("IG"),
    "shipping_address":  st.column_config.TextColumn("Shipping address", width="large"),
    "billing_address":   st.column_config.TextColumn("Billing address"),
    "notes":             st.column_config.TextColumn("Notes"),
    "order_count":       st.column_config.NumberColumn("Orders", format="%d", disabled=True),
    "lifetime_spend":    st.column_config.NumberColumn("Lifetime $", format="$%.2f", disabled=True),
    "unpaid_count":      st.column_config.NumberColumn("Unpaid", format="%d", disabled=True),
}

st.caption("Edit any field inline. Order count / spend / unpaid are read-only.")

edited = st.data_editor(
    df[display_cols],
    column_config=column_config,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    key="customers_editor",
)

# ---- Detect + save changes ------------------------------------------
edited_subset = edited[[
    "id", "name", "email", "phone", "instagram_handle",
    "shipping_address", "billing_address", "notes",
]].copy()
merged = original.merge(edited_subset, on="id", suffixes=("_orig", "_new"))

editable_fields = ["name", "email", "phone", "instagram_handle",
                   "shipping_address", "billing_address", "notes"]
changed_mask = False
for f in editable_fields:
    diff = merged[f"{f}_orig"] != merged[f"{f}_new"]
    changed_mask = diff if changed_mask is False else (changed_mask | diff)
changed = merged[changed_mask] if changed_mask is not False else merged.iloc[0:0]

if not changed.empty:
    st.info(f"{len(changed)} customer(s) have unsaved changes.")
    col_save, col_discard, _ = st.columns([1, 1, 4])
    with col_save:
        save_click = st.button("Save changes", type="primary", use_container_width=True)
    with col_discard:
        discard_click = st.button("Discard", use_container_width=True)

    if discard_click:
        st.session_state.pop("customers_editor", None)
        st.rerun()

    if save_click:
        with st.spinner("Saving..."):
            for _, row in changed.iterrows():
                kwargs = {}
                for f in editable_fields:
                    if row[f"{f}_orig"] != row[f"{f}_new"]:
                        kwargs[f] = row[f"{f}_new"]
                customers.update_customer(client, row["id"], **kwargs)
        _summary.clear()
        st.success(f"Saved {len(changed)} customer(s).")
        st.rerun()

# ---- Roll-up metrics -------------------------------------------------
st.divider()
m1, m2, m3 = st.columns(3)
m1.metric("Total customers", len(df))
m2.metric("Total lifetime sales", f"${float(df['lifetime_spend'].sum()):,.2f}")
m3.metric("Outstanding (unpaid) orders", int(df["unpaid_count"].sum()))
