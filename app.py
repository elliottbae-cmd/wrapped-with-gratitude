"""Home dashboard."""
from __future__ import annotations

import streamlit as st

from config import load
from services.inventory import list_flagged_invoices
from services.sales import count_unpaid, sum_unpaid
from ui.auth import get_client, is_admin, require_auth, sidebar_user_info
from ui.style import wordmark


cfg = load()

st.set_page_config(
    page_title=cfg.business_name,
    page_icon="🎁",
    layout="centered",
    initial_sidebar_state="auto",
)

require_auth()
sidebar_user_info()

wordmark()

st.markdown(
    f'<p class="wg-caption" style="margin-top:-1.5rem; margin-bottom:2.5rem;">'
    f'Welcome back, {st.session_state["user_email"].split("@")[0]}'
    f'</p>',
    unsafe_allow_html=True,
)

client = get_client()
admin = is_admin()


# ---- Quick metrics ----
@st.cache_data(ttl=30, show_spinner=False)
def _metrics(_client, cache_key: str):
    return {
        "unpaid_count": count_unpaid(_client),
        "unpaid_amount": sum_unpaid(_client),
    }


@st.cache_data(ttl=30, show_spinner=False)
def _flagged(_client, cache_key: str):
    return list_flagged_invoices(_client)


cache_key = st.session_state["access_token"]
metrics = _metrics(client, cache_key)

if metrics["unpaid_count"] > 0:
    with st.container(border=True):
        m1, m2 = st.columns([1, 1])
        m1.metric("Outstanding invoices", metrics["unpaid_count"])
        m2.metric("Amount owed to you", f"${metrics['unpaid_amount']:,.2f}")
        st.page_link("pages/4_Sales.py", label="Review unpaid orders →")
    st.markdown("&nbsp;")


# ---- Flagged invoices banner ----
flagged = _flagged(client, cache_key)
if flagged:
    with st.container(border=True):
        st.markdown(
            f"##### ⚠ {len(flagged)} invoice(s) posted with math discrepancies"
        )
        st.caption(
            "These were committed via the override checkbox — review and reconcile when you have time."
        )
        for inv in flagged[:5]:
            inv_num = inv.get("invoice_number") or "(no #)"
            st.markdown(
                f"- **{inv['vendor_name']}** · {inv_num} · "
                f"{inv['invoice_date']} · ${float(inv['total']):,.2f}  \n"
                f"  &nbsp;&nbsp;_{inv.get('discrepancy_detail') or 'no detail recorded'}_"
            )
        if len(flagged) > 5:
            st.caption(f"…and {len(flagged) - 5} more.")
    st.markdown("&nbsp;")


# ---- Primary nav (2x2 grid) ----
r1c1, r1c2 = st.columns(2, gap="medium")

with r1c1:
    with st.container(border=True):
        st.markdown("### Upload an invoice")
        st.caption(
            "Drop a vendor PDF or photo. Claude reads the line items and "
            "lands the cost across your inventory."
        )
        st.page_link("pages/1_Upload_Invoice.py", label="Open uploader →")

with r1c2:
    with st.container(border=True):
        st.markdown("### New sale")
        st.caption(
            "Build a basket from inventory, set a markup, and generate a "
            "Venmo-ready PDF invoice."
        )
        st.page_link("pages/3_New_Sale.py", label="Start a sale →")

r2c1, r2c2 = st.columns(2, gap="medium")

with r2c1:
    with st.container(border=True):
        st.markdown("### Inventory")
        st.caption(
            "Browse on-hand qty, lot history, and landed cost — FIFO across receipts."
        )
        st.page_link("pages/2_Inventory.py", label="Open inventory →")

with r2c2:
    with st.container(border=True):
        st.markdown("### Sales & customers")
        st.caption(
            "Past sales, mark-paid, customer directory and order history."
        )
        st.page_link("pages/4_Sales.py", label="View sales →")
        st.page_link("pages/5_Customers.py", label="Customer directory →")

st.markdown("&nbsp;")

# Coming-soon panel
with st.container(border=True):
    st.markdown("##### Coming next")
    st.caption(
        "• Balance sheet & P&L reports (admin)  \n"
        "• Customer email campaigns (SendGrid)  \n"
        "• Instagram integration (DMs + auto captions)"
    )
