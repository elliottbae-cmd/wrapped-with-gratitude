"""Streamlit auth gate with branded login card.

Session lives in `st.session_state` and is dropped on browser refresh.
"""
from __future__ import annotations

import streamlit as st

from db.client import anon_client, authed_client
from ui.style import apply_style, wordmark


_SESSION_KEYS = ("access_token", "refresh_token", "user_id", "user_email", "role")


def is_authenticated() -> bool:
    return "access_token" in st.session_state


@st.cache_resource(show_spinner=False)
def _build_authed_client(access_token: str, refresh_token: str):
    """Cached by (access_token, refresh_token) — saves rebuilding the client
    object on every Streamlit rerun. New sign-ins produce a new cache key."""
    return authed_client(access_token, refresh_token)


def get_client():
    if not is_authenticated():
        return None
    return _build_authed_client(
        st.session_state["access_token"],
        st.session_state["refresh_token"],
    )


def get_user_role() -> str:
    if "role" in st.session_state:
        return st.session_state["role"]
    client = get_client()
    if client is None:
        return "anon"
    res = (
        client.table("profiles")
        .select("role")
        .eq("id", st.session_state["user_id"])
        .limit(1)
        .execute()
    )
    role = res.data[0]["role"] if res.data else "staff"
    st.session_state["role"] = role
    return role


def is_admin() -> bool:
    return get_user_role() == "admin"


def login_form() -> None:
    """Branded, centered login card."""
    apply_style()

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        wordmark()
        with st.container(border=True):
            st.markdown(
                '<p class="wg-caption" style="margin-bottom:1.25rem;">'
                'Sign in to continue'
                '</p>',
                unsafe_allow_html=True,
            )
            with st.form("login_form", clear_on_submit=False):
                email = st.text_input("Email", placeholder="you@example.com")
                password = st.text_input("Password", type="password", placeholder="••••••••")
                submit = st.form_submit_button(
                    "Sign in", type="primary", use_container_width=True
                )

    if submit:
        if not email or not password:
            st.error("Email and password are required.")
            return
        try:
            client = anon_client()
            res = client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            st.session_state["access_token"] = res.session.access_token
            st.session_state["refresh_token"] = res.session.refresh_token
            st.session_state["user_id"] = res.user.id
            st.session_state["user_email"] = res.user.email
            st.rerun()
        except Exception as e:
            st.error(f"Sign in failed: {e}")


def require_auth() -> None:
    """Top-of-page gate. Renders styling and login form if needed."""
    apply_style()
    if not is_authenticated():
        login_form()
        st.stop()


def require_admin() -> None:
    require_auth()
    if not is_admin():
        st.error("Admin access required.")
        st.stop()


def logout() -> None:
    for k in _SESSION_KEYS:
        st.session_state.pop(k, None)
    _build_authed_client.clear()  # drop the cached client too
    st.rerun()


def sidebar_user_info() -> None:
    if not is_authenticated():
        return
    with st.sidebar:
        st.markdown(
            '<div style="font-family:\'Cormorant Garamond\',serif; '
            'font-size:1.5rem; padding:0.5rem 0 0.25rem;">'
            'Wrapped with Gratitude</div>',
            unsafe_allow_html=True,
        )
        st.divider()
        st.caption(f"**{st.session_state['user_email']}**")
        st.caption(f"Role: `{get_user_role()}`")
        if st.button("Sign out", use_container_width=True):
            logout()
