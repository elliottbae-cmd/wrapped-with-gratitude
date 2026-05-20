"""Supabase client factory.

The app always uses the anon key plus the user's session JWT — never the
service role key. RLS enforces what each user can do.
"""
from __future__ import annotations

from supabase import create_client, Client

from config import load


def anon_client() -> Client:
    """A fresh client with no session attached. Use for the login call itself."""
    cfg = load()
    return create_client(cfg.supabase_url, cfg.supabase_anon_key)


def authed_client(access_token: str, refresh_token: str) -> Client:
    """A client bound to a user's session — RLS policies see auth.uid()."""
    client = anon_client()
    client.auth.set_session(access_token, refresh_token)
    return client
