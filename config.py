"""Environment-backed configuration. Single source of truth for env vars.

Lookup order for each key:
  1. Streamlit secrets (st.secrets) — used on Streamlit Cloud
  2. .env file via python-dotenv — used in local development
  3. OS environment variables — used in tests / CI

Lets the same code run locally and on Cloud without changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _from_secrets(name: str) -> str | None:
    """Try Streamlit's secrets store. Returns None if not available or key missing."""
    try:
        import streamlit as st
        # st.secrets is a Mapping; .get() avoids KeyError on missing keys.
        # If there's no secrets.toml at all, accessing st.secrets raises — hence the try.
        val = st.secrets.get(name) if hasattr(st, "secrets") else None
        return val if val else None
    except Exception:
        return None


def _read(name: str, default: str = "") -> str:
    """Read a config value from st.secrets → .env / environ → default."""
    return _from_secrets(name) or os.environ.get(name) or default


def _required(name: str) -> str:
    val = _read(name)
    if not val:
        raise RuntimeError(
            f"Missing required config key: {name}. "
            f"Set it in your local .env file, or in Streamlit Cloud's Secrets manager."
        )
    return val


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_anon_key: str
    anthropic_api_key: str
    business_name: str
    business_owner_name: str
    business_venmo_handle: str
    business_email: str
    business_phone: str
    sendgrid_api_key: str
    sendgrid_from_email: str
    instagram_access_token: str
    instagram_business_account_id: str
    replicate_api_token: str


def load() -> Config:
    return Config(
        supabase_url=_required("SUPABASE_URL"),
        supabase_anon_key=_required("SUPABASE_ANON_KEY"),
        anthropic_api_key=_required("ANTHROPIC_API_KEY"),
        business_name=_read("BUSINESS_NAME", "Wrapped with Gratitude"),
        business_owner_name=_read("BUSINESS_OWNER_NAME", "Owner"),
        business_venmo_handle=_read("BUSINESS_VENMO_HANDLE"),
        business_email=_read("BUSINESS_EMAIL"),
        business_phone=_read("BUSINESS_PHONE"),
        sendgrid_api_key=_read("SENDGRID_API_KEY"),
        sendgrid_from_email=_read("SENDGRID_FROM_EMAIL"),
        instagram_access_token=_read("INSTAGRAM_ACCESS_TOKEN"),
        instagram_business_account_id=_read("INSTAGRAM_BUSINESS_ACCOUNT_ID"),
        replicate_api_token=_read("REPLICATE_API_TOKEN"),
    )
