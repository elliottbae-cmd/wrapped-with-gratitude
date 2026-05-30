"""Inventory page — editable SKU list with lot drill-down.

Editable inline: name, SKU, category, unit_of_measure. Cost / qty columns
are read-only (derived from inventory_lots). Admins see WAC / latest cost /
on-hand value; staff don't.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.inventory import (
    list_inventory_summary,
    list_lots_for_item,
    update_inventory_item,
)
from ui.auth import get_client, is_admin, require_auth, sidebar_user_info


st.set_page_config(page_title="Inventory", page_icon="📦", layout="wide")
require_auth()

st.title("📦 Inventory")

client = get_client()
admin = is_admin()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_summary(_client, cache_key: str):
    return list_inventory_summary(_client)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_lots(_client, item_id: str, cache_key: str):
    return list_lots_for_item(_client, item_id)


cache_key = st.session_state["access_token"]
summary = _cached_summary(client, cache_key)

if not summary:
    st.info("No inventory yet. Upload an invoice to get started.")
    st.page_link("pages/1_Upload_Invoice.py", label="Upload your first invoice", icon="📥")
    st.stop()

# ---- Editable grid ----
df = pd.DataFrame(summary).copy()
df["name"] = df["name"].fillna("")
df["sku"] = df["sku"].fillna("")
df["category"] = df["category"].fillna("")
df["unit_of_measure"] = df["unit_of_measure"].fillna("each")

# Keep an immutable copy so we can detect what changed (against the FULL dataset,
# not the filtered view — filters don't affect change tracking)
original = df[["id", "name", "sku", "category", "unit_of_measure"]].copy()

# ---- Filters ----
all_categories = sorted({c for c in df["category"] if c})
uncategorized_count = int((df["category"] == "").sum())

fc1, fc2, fc3 = st.columns([3, 3, 2])
with fc1:
    selected_cats = st.multiselect(
        "Category",
        options=all_categories + (["(Uncategorized)"] if uncategorized_count else []),
        default=[],
        placeholder=f"All categories ({len(all_categories)})",
        label_visibility="collapsed",
    )
with fc2:
    search_query = st.text_input(
        "Search",
        placeholder="Search name or SKU…",
        label_visibility="collapsed",
    )
with fc3:
    hide_zero = st.toggle("Hide out-of-stock", value=False)

filtered = df.copy()
if selected_cats:
    if "(Uncategorized)" in selected_cats:
        cats_only = [c for c in selected_cats if c != "(Uncategorized)"]
        filtered = filtered[filtered["category"].isin(cats_only) | (filtered["category"] == "")]
    else:
        filtered = filtered[filtered["category"].isin(selected_cats)]
if search_query:
    q = search_query.lower().strip()
    filtered = filtered[
        filtered["name"].str.lower().str.contains(q, na=False)
        | filtered["sku"].str.lower().str.contains(q, na=False)
    ]
if hide_zero:
    filtered = filtered[filtered["on_hand"] > 0]

active_filters = bool(selected_cats) or bool(search_query) or hide_zero

if filtered.empty:
    st.info("No items match the current filters.")
    st.stop()

if active_filters:
    st.caption(f"Showing {len(filtered)} of {len(df)} items.")
else:
    st.caption(f"{len(df)} items.")

# Build column config
column_config = {
    "id":              None,  # hide
    "name":            st.column_config.TextColumn("Item", width="large", required=True),
    "sku":             st.column_config.TextColumn("SKU"),
    "category":        st.column_config.TextColumn("Category"),
    "unit_of_measure": st.column_config.TextColumn("UoM", help="e.g. each, oz, set"),
    "on_hand":         st.column_config.NumberColumn("On hand", format="%.3f", disabled=True),
    "open_lot_count":  st.column_config.NumberColumn("Open lots", format="%d", disabled=True),
}

display_cols = [
    "id", "name", "sku", "category", "unit_of_measure", "on_hand", "open_lot_count",
]

if admin:
    display_cols += ["weighted_avg_cost", "latest_landed_cost", "inventory_value"]
    column_config["weighted_avg_cost"]  = st.column_config.NumberColumn("WAC / unit",       format="$%.4f", disabled=True)
    column_config["latest_landed_cost"] = st.column_config.NumberColumn("Latest cost / unit", format="$%.4f", disabled=True)
    column_config["inventory_value"]    = st.column_config.NumberColumn("On-hand value",    format="$%.2f", disabled=True)

st.caption("Edit Item / SKU / Category / UoM inline. Cost columns are read-only (computed from lots).")

edited = st.data_editor(
    filtered[display_cols],
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",  # adding/deleting items happens through invoice upload, not here
    column_config=column_config,
    # Include filter signature in the key so the editor resets cleanly when filters change
    key=f"inventory_editor::{tuple(sorted(selected_cats))}::{search_query}::{hide_zero}",
)

# ---- Detect changes ----
edited_subset = edited[["id", "name", "sku", "category", "unit_of_measure"]].copy()
merged = original.merge(edited_subset, on="id", suffixes=("_orig", "_new"))

changed_rows = merged[
    (merged["name_orig"] != merged["name_new"])
    | (merged["sku_orig"] != merged["sku_new"])
    | (merged["category_orig"] != merged["category_new"])
    | (merged["unit_of_measure_orig"] != merged["unit_of_measure_new"])
]

if not changed_rows.empty:
    st.info(f"{len(changed_rows)} row(s) have unsaved changes.")
    col_save, col_discard, _ = st.columns([1, 1, 4])
    with col_save:
        save_clicked = st.button("Save changes", type="primary", use_container_width=True)
    with col_discard:
        discard_clicked = st.button("Discard", use_container_width=True)

    if discard_clicked:
        # Clear any inventory_editor::... keys (the editor key includes filter signature)
        for k in list(st.session_state.keys()):
            if isinstance(k, str) and k.startswith("inventory_editor"):
                st.session_state.pop(k, None)
        st.rerun()

    if save_clicked:
        with st.spinner("Saving..."):
            for _, row in changed_rows.iterrows():
                update_inventory_item(
                    client,
                    item_id=row["id"],
                    name=row["name_new"] if row["name_orig"] != row["name_new"] else None,
                    sku=row["sku_new"] if row["sku_orig"] != row["sku_new"] else None,
                    category=row["category_new"] if row["category_orig"] != row["category_new"] else None,
                    unit_of_measure=(
                        row["unit_of_measure_new"]
                        if row["unit_of_measure_orig"] != row["unit_of_measure_new"]
                        else None
                    ),
                )
        st.cache_data.clear()
        st.success(f"Saved {len(changed_rows)} row(s).")
        st.rerun()

if admin:
    total_value = float(df["inventory_value"].sum())
    if active_filters:
        filtered_value = float(filtered["inventory_value"].sum())
        mc1, mc2 = st.columns(2)
        mc1.metric("Filtered inventory value", f"${filtered_value:,.2f}")
        mc2.metric("Total inventory value", f"${total_value:,.2f}")
    else:
        st.metric("Total inventory value (at landed cost)", f"${total_value:,.2f}")

# ---- Lot drill-down ----
st.divider()
st.subheader("Lot detail")

item_options = {
    f'{row["name"]}' + (f' [{row["sku"]}]' if row["sku"] else ""): row["id"]
    for _, row in edited.iterrows()
}
choice = st.selectbox("Pick an item to see its lots", options=[""] + list(item_options.keys()))

if choice:
    item_id = item_options[choice]
    lots = _cached_lots(client, item_id, cache_key)
    if not lots:
        st.info("No lots recorded for this item.")
    else:
        lot_df = pd.DataFrame(lots)
        lot_df["consumed"] = lot_df["qty_received"].astype(float) - lot_df["qty_remaining"].astype(float)
        lot_cols = ["received_date", "qty_received", "consumed", "qty_remaining"]
        lcfg = {
            "received_date": st.column_config.DateColumn("Received"),
            "qty_received":  st.column_config.NumberColumn("Received", format="%.3f"),
            "consumed":      st.column_config.NumberColumn("Consumed", format="%.3f"),
            "qty_remaining": st.column_config.NumberColumn("Remaining", format="%.3f"),
        }
        if admin:
            lot_cols.append("landed_unit_cost")
            lcfg["landed_unit_cost"] = st.column_config.NumberColumn("Landed / unit", format="$%.4f")
        st.dataframe(lot_df[lot_cols], use_container_width=True, hide_index=True, column_config=lcfg)
        st.caption("Lots are listed in FIFO order — top row is consumed first on the next sale.")
