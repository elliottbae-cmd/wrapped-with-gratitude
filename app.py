"""Streamlit entry — page config, auth gate, sidebar navigation with groups.

Sidebar layout:
  WIG Dashboard        ← default home page
  Operations           (collapsible)
    · Upload Invoice
    · Inventory
    · New Sale
    · Sales
    · Customers
  Accounting           (collapsible)
    · Reports
    · Expenses
  Marketing            (collapsible)
    · Marketing
"""
from __future__ import annotations

import streamlit as st

from config import load
from ui.auth import require_auth, sidebar_user_info


cfg = load()

st.set_page_config(
    page_title=cfg.business_name,
    page_icon="🎁",
    layout="centered",
    initial_sidebar_state="auto",
)

# Auth gate runs once at the navigation entry — pages don't need to repeat it.
require_auth()

# Page tree — dict keys become section headers. The empty string "" group
# renders without a header so the home page sits at the top of the sidebar.
pages = {
    "": [
        st.Page("home_page.py", title="WIG Dashboard", icon="🎁", default=True),
    ],
    "Operations": [
        st.Page("pages/1_Upload_Invoice.py", title="Upload Invoice", icon="📥"),
        st.Page("pages/2_Inventory.py",      title="Inventory",      icon="📦"),
        st.Page("pages/3_New_Sale.py",       title="New Sale",       icon="🛒"),
        st.Page("pages/4_Sales.py",          title="Sales",          icon="💸"),
        st.Page("pages/5_Customers.py",      title="Customers",      icon="👥"),
    ],
    "Accounting": [
        st.Page("pages/6_Reports.py",  title="Reports",  icon="📊"),
        st.Page("pages/8_Expenses.py", title="Expenses", icon="💳"),
    ],
    "Marketing": [
        st.Page("pages/7_Marketing.py", title="Marketing", icon="📣"),
    ],
}

pg = st.navigation(pages, position="sidebar", expanded=True)

# Add the user info + sign-out below the nav — runs once per rerun.
sidebar_user_info()

pg.run()
