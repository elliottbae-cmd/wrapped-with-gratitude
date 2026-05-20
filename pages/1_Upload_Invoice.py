"""Upload Invoice page — file upload → Claude vision parse → editable review → commit."""
from __future__ import annotations

import streamlit as st

from config import load
from services.invoice_parser import parse_invoice
from ui.auth import get_client, require_auth, sidebar_user_info
from ui.invoice_review import render as render_review


cfg = load()

st.set_page_config(page_title="Upload Invoice", page_icon="📥", layout="wide")
require_auth()
sidebar_user_info()

st.title("📥 Upload Invoice")
st.caption(
    "Upload a vendor invoice as PDF or image. Claude will parse it; you review "
    "and edit before it hits inventory."
)

client = get_client()

# Step 1 — file upload
uploaded = st.file_uploader(
    "Invoice file",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=False,
)

# Persist the last parse in session so re-renders during editing don't re-call the API
if uploaded is not None:
    new_signature = (uploaded.name, uploaded.size)
    if st.session_state.get("uploaded_file_meta") != new_signature:
        # Fresh upload — clear the previous parse
        st.session_state.pop("parsed_invoice", None)
        st.session_state["uploaded_file_meta"] = new_signature
        st.session_state["uploaded_file_bytes"] = uploaded.getvalue()
        st.session_state["uploaded_file_name"] = uploaded.name
        st.session_state["uploaded_file_mime"] = uploaded.type

# Step 2 — parse
if "uploaded_file_meta" in st.session_state and "parsed_invoice" not in st.session_state:
    if st.button("Parse invoice with Claude", type="primary"):
        with st.spinner("Parsing invoice — usually 5–15 seconds..."):
            try:
                parsed = parse_invoice(
                    file_bytes=st.session_state["uploaded_file_bytes"],
                    mime_type=st.session_state["uploaded_file_mime"],
                    anthropic_api_key=cfg.anthropic_api_key,
                )
                st.session_state["parsed_invoice"] = parsed
                st.rerun()
            except Exception as e:
                st.error(f"Parse failed: {e}")

# Step 3 — review + commit
if "parsed_invoice" in st.session_state:
    render_review(
        parsed=st.session_state["parsed_invoice"],
        file_bytes=st.session_state["uploaded_file_bytes"],
        file_name=st.session_state["uploaded_file_name"],
        mime_type=st.session_state["uploaded_file_mime"],
        client=client,
    )
