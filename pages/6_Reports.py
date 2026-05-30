"""Reports — admin only.

Sections:
  1. P&L for a period (accrual or cash basis)
  2. Balance Sheet as-of date
  3. Cash flow for a period
  4. Top items by revenue (period)
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from config import load
from services import reports
from ui.auth import get_client, require_admin, sidebar_user_info


cfg = load()
st.set_page_config(page_title="Reports", page_icon="📊", layout="wide")
require_admin()
sidebar_user_info()

st.title("📊 Reports")
st.caption("Admin-only views of revenue, costs, cash, and balance sheet.")

client = get_client()


@st.cache_data(ttl=30, show_spinner=False)
def _pl(_client, start_iso: str, end_iso: str, basis: str, _key: str):
    return reports.pl_for_period(_client, date.fromisoformat(start_iso), date.fromisoformat(end_iso), basis=basis)


@st.cache_data(ttl=30, show_spinner=False)
def _bs(_client, as_of_iso: str, _key: str):
    return reports.bs_as_of(_client, date.fromisoformat(as_of_iso))


@st.cache_data(ttl=30, show_spinner=False)
def _cf(_client, start_iso: str, end_iso: str, _key: str):
    return reports.cash_flow_for_period(_client, date.fromisoformat(start_iso), date.fromisoformat(end_iso))


@st.cache_data(ttl=30, show_spinner=False)
def _top(_client, start_iso: str, end_iso: str, _key: str):
    return reports.top_items_by_revenue(
        _client, date.fromisoformat(start_iso), date.fromisoformat(end_iso), limit=10
    )


cache_key = st.session_state["access_token"]


# =====================================================================
# Period selector (shared across P&L, cash flow, top items)
# =====================================================================
st.subheader("Reporting period")

presets = ["This month", "Last month", "Quarter to date", "Year to date", "All time", "Custom"]
pc1, pc2, pc3, pc4 = st.columns([2, 1, 1, 1])
with pc1:
    preset = st.selectbox("Preset", options=presets, index=0, label_visibility="collapsed")
with pc2:
    if preset != "Custom":
        start_default, end_default = reports.period_preset(preset)
    else:
        start_default = date.today().replace(day=1)
        end_default = date.today()
    start_d = st.date_input("Start", value=start_default, key="rpt_start", disabled=(preset != "Custom"))
with pc3:
    end_d = st.date_input("End", value=end_default, key="rpt_end", disabled=(preset != "Custom"))
with pc4:
    basis = st.selectbox(
        "Basis",
        options=["accrual", "cash"],
        index=0,
        help=(
            "Accrual: revenue counted on the order date, regardless of payment. "
            "Cash: revenue counted only when payment is received."
        ),
    )

start_iso = start_d.isoformat()
end_iso = end_d.isoformat()

st.divider()

# =====================================================================
# 1. P&L
# =====================================================================
st.subheader("Profit & Loss")
st.caption(
    f"{start_d.strftime('%b %d, %Y')} → {end_d.strftime('%b %d, %Y')}  ·  "
    f"{basis.title()} basis"
)

pl = _pl(client, start_iso, end_iso, basis, cache_key)

pm1, pm2, pm3, pm4 = st.columns(4)
pm1.metric("Revenue", f"${pl.revenue:,.2f}")
pm2.metric("COGS", f"${pl.cogs:,.2f}")
pm3.metric("Gross profit", f"${pl.gross_profit:,.2f}")
pm4.metric("Gross margin", f"{pl.gross_margin_pct:.1f}%")

pm5, pm6, pm7, pm8 = st.columns(4)
pm5.metric("Orders", pl.order_count)
pm6.metric("Avg order value", f"${pl.avg_order_value:,.2f}")
pm7.metric("Shipping collected", f"${pl.shipping_collected:,.2f}",
           help="Pass-through, not P&L revenue.")
pm8.metric("Sales tax collected", f"${pl.tax_collected:,.2f}",
           help="Owed to the state, not revenue.")

st.caption(
    "Note: this MVP has no operating expense module yet — gross profit equals net income."
)

st.divider()

# =====================================================================
# 2. Top items in the period
# =====================================================================
st.subheader("Top items by revenue")
top = _top(client, start_iso, end_iso, cache_key)
if top:
    top_df = pd.DataFrame(top)
    st.dataframe(
        top_df,
        column_config={
            "item":       st.column_config.TextColumn("Item", width="large"),
            "qty":        st.column_config.NumberColumn("Units sold", format="%.0f"),
            "revenue":    st.column_config.NumberColumn("Revenue", format="$%.2f"),
            "cogs":       st.column_config.NumberColumn("COGS",    format="$%.2f"),
            "profit":     st.column_config.NumberColumn("Profit",  format="$%.2f"),
            "margin_pct": st.column_config.NumberColumn("Margin %", format="%.1f%%"),
        },
        use_container_width=True,
        hide_index=True,
    )
else:
    st.caption("No sales in the selected period.")

st.divider()

# =====================================================================
# 3. Cash flow (for the same period)
# =====================================================================
st.subheader("Cash flow")
cf = _cf(client, start_iso, end_iso, cache_key)

cm1, cm2, cm3 = st.columns(3)
cm1.metric("Payments collected", f"${cf.cash_in:,.2f}", delta=f"{cf.payment_count} payments", delta_color="off")
cm2.metric("Inventory purchases", f"${cf.cash_out:,.2f}", delta=f"{cf.purchase_count} invoices", delta_color="off")
cm3.metric(
    "Net cash change",
    f"${cf.net_change:,.2f}",
    delta="positive" if cf.net_change >= 0 else "negative",
    delta_color="normal" if cf.net_change >= 0 else "inverse",
)

st.caption(
    "Assumes you paid each vendor invoice at receipt. "
    "Once we track vendor AP (Phase 3.5 maybe), this becomes the true cash picture."
)

st.divider()

# =====================================================================
# 4. Balance Sheet
# =====================================================================
st.subheader("Balance sheet")

bs_col1, _ = st.columns([1, 3])
with bs_col1:
    as_of = st.date_input("As of", value=end_d, key="bs_as_of")

bs = _bs(client, as_of.isoformat(), cache_key)

owner = cfg.business_owner_name or "Owner"

# Two-column BS layout: Assets | Liabilities + Equity
ac1, ac2 = st.columns(2)

with ac1:
    st.markdown("##### Assets")
    with st.container(border=True):
        st.markdown(
            f"**Inventory at cost** &nbsp;&nbsp; "
            f"<span style='float:right'>${bs.inventory_at_cost:,.2f}</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"{bs.inventory_unit_count:,.0f} units across {bs.open_lot_count} open lots")
    with st.container(border=True):
        st.markdown(
            f"**Accounts receivable** &nbsp;&nbsp; "
            f"<span style='float:right'>${bs.accounts_receivable:,.2f}</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"{bs.ar_order_count} unpaid order(s) as of {as_of.strftime('%b %d, %Y')}")
    with st.container(border=True):
        st.markdown(
            f"**Cash** &nbsp;&nbsp; "
            f"<span style='float:right'>${bs.cash:,.2f}</span>",
            unsafe_allow_html=True,
        )
        st.caption("Customer payments collected to date")
    st.metric("Total assets", f"${bs.total_assets:,.2f}")

with ac2:
    st.markdown("##### Liabilities + Equity")
    with st.container(border=True):
        st.markdown(
            f"**Accounts payable** &nbsp;&nbsp; "
            f"<span style='float:right'>$0.00</span>",
            unsafe_allow_html=True,
        )
        st.caption("Vendor AP not yet tracked — assumed paid at receipt.")
    with st.container(border=True):
        st.markdown(
            f"**Capital contribution — {owner}** &nbsp;&nbsp; "
            f"<span style='float:right'>${bs.capital_contribution:,.2f}</span>",
            unsafe_allow_html=True,
        )
        st.caption("Owner-funded inventory purchases to date")
    with st.container(border=True):
        st.markdown(
            f"**Retained earnings** &nbsp;&nbsp; "
            f"<span style='float:right'>${bs.retained_earnings:,.2f}</span>",
            unsafe_allow_html=True,
        )
        st.caption("Cumulative profit on closed sales (= Total Assets − Capital)")
    st.metric("Total liab + equity", f"${bs.total_equity:,.2f}")

# Sanity-check the balance
delta = round(bs.total_assets - bs.total_equity, 2)
if abs(delta) < 0.01:
    st.caption(f"✓ Balance sheet balances: ${bs.total_assets:,.2f} = ${bs.total_equity:,.2f}")
else:
    st.caption(f"⚠ Off by ${delta:+,.2f} — would indicate a bug in the accounting math.")

st.divider()

st.caption(
    "📝 **Accounting notes** — Revenue excludes shipping pass-through and sales tax "
    "(both shown for reconciliation, not as P&L items). COGS is FIFO from the "
    "inventory_lots that fed each sale. Balance sheet is a snapshot; date-aware "
    "lot history isn't tracked, so the BS shows current inventory state regardless of as-of date."
)
