"""Home dashboard."""
from __future__ import annotations

import streamlit as st

from config import load
from services.inventory import count_flagged_invoices, list_flagged_invoices
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

# ---- Flagged invoices banner ----
client = get_client()


@st.cache_data(ttl=30, show_spinner=False)
def _flagged(_client, cache_key: str):
    return list_flagged_invoices(_client)


flagged = _flagged(client, st.session_state["access_token"])
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

c1, c2 = st.columns(2, gap="medium")

with c1:
    with st.container(border=True):
        st.markdown("### Upload an invoice")
        st.caption(
            "Drop a vendor PDF or photo. Claude reads the line items and "
            "lands the cost across your inventory."
        )
        st.page_link("pages/1_Upload_Invoice.py", label="Open uploader →")

with c2:
    with st.container(border=True):
        st.markdown("### View inventory")
        st.caption(
            "Browse on-hand quantities, lot history, and landed cost — "
            "FIFO across receipts."
        )
        st.page_link("pages/2_Inventory.py", label="Open inventory →")

st.markdown("&nbsp;")

# Coming-soon panel
with st.container(border=True):
    st.markdown("##### Coming next")
    st.caption(
        "• Sales basket builder with markup and PDF customer invoices  \n"
        "• Balance sheet & P&L reports (admin)  \n"
        "• Customer email campaigns  \n"
        "• Instagram integration"
    )
