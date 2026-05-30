"""Sales page — list past sales, view detail, mark paid, download PDFs."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from services import sales as sales_svc
from ui.auth import get_client, is_admin, require_auth, sidebar_user_info


st.set_page_config(page_title="Sales", page_icon="💸", layout="wide")
require_auth()
sidebar_user_info()

st.title("💸 Sales")

client = get_client()
admin = is_admin()


@st.cache_data(ttl=15, show_spinner=False)
def _orders(_client, status: str | None, cache_key: str):
    return sales_svc.list_sales(_client, status_filter=status)


@st.cache_data(ttl=15, show_spinner=False)
def _detail(_client, order_id: str, cache_key: str):
    return sales_svc.get_sale_detail(_client, order_id)


cache_key = st.session_state["access_token"]


# ---- Filter bar ------------------------------------------------------
fc1, fc2 = st.columns([2, 6])
with fc1:
    status_label = st.selectbox(
        "Status",
        options=["All", "Unpaid (invoiced)", "Paid", "Void"],
        label_visibility="collapsed",
    )

status_map = {
    "All": None,
    "Unpaid (invoiced)": "invoiced",
    "Paid": "paid",
    "Void": "void",
}
orders = _orders(client, status_map[status_label], cache_key)

if not orders:
    st.info(
        "No sales matching that filter."
        if status_map[status_label]
        else "No sales yet. Build a basket on the New Sale page."
    )
    st.page_link("pages/3_New_Sale.py", label="🛒 New sale", icon=None)
    st.stop()

df = pd.DataFrame(orders)

# ---- Summary metrics -------------------------------------------------
total_invoiced = float(df[df["status"].isin(["invoiced", "paid"])]["total"].sum())
total_unpaid = float(df[df["status"] == "invoiced"]["total"].sum())
total_paid = float(df[df["status"] == "paid"]["total"].sum())

m1, m2, m3 = st.columns(3)
m1.metric("Total billed", f"${total_invoiced:,.2f}")
m2.metric("Outstanding (unpaid)", f"${total_unpaid:,.2f}",
          delta=f"{int((df['status'] == 'invoiced').sum())} order(s)",
          delta_color="off")
m3.metric("Collected (paid)", f"${total_paid:,.2f}")

st.divider()

# ---- Orders table ----------------------------------------------------
display_cols = ["order_number", "order_date", "customer_name", "status", "total", "paid_date"]
column_config = {
    "order_number":   st.column_config.TextColumn("Order #"),
    "order_date":     st.column_config.DateColumn("Date"),
    "customer_name":  st.column_config.TextColumn("Customer", width="medium"),
    "status":         st.column_config.TextColumn("Status"),
    "total":          st.column_config.NumberColumn("Total", format="$%.2f"),
    "paid_date":      st.column_config.DateColumn("Paid on"),
}
if admin:
    display_cols.insert(5, "subtotal_cogs")
    column_config["subtotal_cogs"] = st.column_config.NumberColumn("COGS", format="$%.2f")

st.dataframe(
    df[display_cols],
    column_config=column_config,
    use_container_width=True,
    hide_index=True,
)

# ---- Detail view -----------------------------------------------------
st.divider()
st.subheader("Order detail")

picker_options = [""] + [
    f"{o['order_number']}  ·  {o['customer_name']}  ·  ${float(o['total']):,.2f}  ·  {o['status']}"
    for o in orders
]
pick = st.selectbox("Pick an order", options=picker_options, label_visibility="collapsed")

if not pick:
    st.stop()

picked_idx = picker_options.index(pick) - 1
order_id = orders[picked_idx]["id"]

detail = _detail(client, order_id, cache_key)
if not detail:
    st.error("Order not found.")
    st.stop()

# Header
hc1, hc2, hc3, hc4 = st.columns(4)
hc1.metric("Order #", detail["order_number"])
hc2.metric("Date", str(detail["order_date"]))
hc3.metric("Status", detail["status"])
hc4.metric("Total", f"${float(detail['total']):,.2f}")

# Customer
cust = detail.get("customer") or {}
st.markdown(f"**Customer:** {cust.get('name', '—')}")
contact_bits = []
if cust.get("email"): contact_bits.append(cust["email"])
if cust.get("phone"): contact_bits.append(cust["phone"])
if cust.get("shipping_address"):
    contact_bits.append(cust["shipping_address"].replace("\n", ", "))
if contact_bits:
    st.caption(" · ".join(contact_bits))

# Lines
lines = detail.get("lines") or []
if lines:
    lines_df = pd.DataFrame(lines)
    lines_df["line_total"] = lines_df["qty"].astype(float) * lines_df["unit_price_at_sale"].astype(float)
    line_cols = ["item_name", "qty", "unit_price_at_sale", "line_total"]
    line_cfg = {
        "item_name":          st.column_config.TextColumn("Item", width="large"),
        "qty":                st.column_config.NumberColumn("Qty", format="%.0f"),
        "unit_price_at_sale": st.column_config.NumberColumn("Sale / unit", format="$%.4f"),
        "line_total":         st.column_config.NumberColumn("Line total", format="$%.2f"),
    }
    if admin:
        line_cols.append("total_cogs")
        line_cfg["total_cogs"] = st.column_config.NumberColumn("Line COGS", format="$%.2f")
    st.dataframe(lines_df[line_cols], column_config=line_cfg, use_container_width=True, hide_index=True)

# Totals strip
tc1, tc2, tc3, tc4 = st.columns(4)
tc1.caption(f"Subtotal: ${float(detail.get('subtotal_price', 0) or 0):,.2f}")
tc2.caption(f"Shipping: ${float(detail.get('shipping_charge', 0) or 0):,.2f}")
tc3.caption(f"Tax: ${float(detail.get('sales_tax', 0) or 0):,.2f}")
tc4.caption(f"**Total: ${float(detail.get('total', 0) or 0):,.2f}**")

if admin:
    cogs = float(detail.get("subtotal_cogs", 0) or 0)
    rev = float(detail.get("subtotal_price", 0) or 0)
    profit = rev - cogs
    margin = (profit / rev * 100) if rev else 0
    st.caption(f"**(Admin)** COGS ${cogs:,.2f} · Profit ${profit:,.2f} · Margin {margin:.1f}%")

# Actions
st.divider()
ac1, ac2, ac3 = st.columns(3)

with ac1:
    if detail["status"] == "invoiced":
        paid_on = st.date_input(
            "Paid on",
            value=date.today(),
            key=f"paid_date_{order_id}",
            help="Date the payment actually landed — defaults to today.",
        )
        if st.button("✅ Mark as paid", type="primary", use_container_width=True):
            sales_svc.mark_paid(client, order_id, paid_date=paid_on)
            _orders.clear()
            _detail.clear()
            st.success(f"{detail['order_number']} marked paid on {paid_on}.")
            st.rerun()
    elif detail["status"] == "paid":
        st.caption(f"Paid on {detail.get('paid_date', '—')}")

with ac2:
    if detail.get("pdf_path"):
        try:
            pdf_bytes = sales_svc.download_customer_invoice_pdf(client, detail["pdf_path"])
            st.download_button(
                "📄 Download PDF",
                data=pdf_bytes,
                file_name=f"{detail['order_number']}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.caption(f"PDF download failed: {e}")
    else:
        st.caption("No archived PDF on file.")
