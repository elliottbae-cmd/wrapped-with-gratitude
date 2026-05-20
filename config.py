"""Environment-backed configuration. Single source of truth for env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required env var: {name}. "
            f"Copy .env.example to .env and fill in real values."
        )
    return val


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_anon_key: str
    anthropic_api_key: str
    business_name: str
    business_venmo_handle: str
    business_email: str
    business_phone: str
    sendgrid_api_key: str
    sendgrid_from_email: str
    instagram_access_token: str
    instagram_business_account_id: str


def load() -> Config:
    return Config(
        supabase_url=_required("SUPABASE_URL"),
        supabase_anon_key=_required("SUPABASE_ANON_KEY"),
        anthropic_api_key=_required("ANTHROPIC_API_KEY"),
        business_name=os.environ.get("BUSINESS_NAME", "Wrapped with Gratitude"),
        business_venmo_handle=os.environ.get("BUSINESS_VENMO_HANDLE", ""),
        business_email=os.environ.get("BUSINESS_EMAIL", ""),
        business_phone=os.environ.get("BUSINESS_PHONE", ""),
        sendgrid_api_key=os.environ.get("SENDGRID_API_KEY", ""),
        sendgrid_from_email=os.environ.get("SENDGRID_FROM_EMAIL", ""),
        instagram_access_token=os.environ.get("INSTAGRAM_ACCESS_TOKEN", ""),
        instagram_business_account_id=os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", ""),
    )
