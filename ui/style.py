"""Global CSS + brand elements.

Imports Google Fonts for the wordmark (Cormorant Garamond serif) and body
(Inter sans-serif), hides Streamlit's default chrome, and themes buttons +
form fields to match the blush palette.
"""
from __future__ import annotations

import streamlit as st


_HEAD = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
"""

_CSS = """
<style>
/* Body + UI text */
html, body, [data-testid="stAppViewContainer"],
.stMarkdown, .stTextInput input, .stNumberInput input,
.stSelectbox, .stDateInput input, .stTextArea textarea {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* Headings — elegant serif */
h1, h2, h3, h4, h5 {
    font-family: 'Cormorant Garamond', Georgia, serif !important;
    font-weight: 500 !important;
    color: #2C2826;
    letter-spacing: 0.005em;
}
h1 { font-size: 2.5rem !important; line-height: 1.15 !important; }
h2 { font-size: 1.875rem !important; }
h3 { font-size: 1.375rem !important; }

/* Hide default Streamlit chrome */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
[data-testid="stStatusWidget"] { visibility: hidden; }

/* Buttons — refined */
.stButton > button {
    border-radius: 4px;
    font-family: 'Inter', sans-serif;
    font-weight: 500;
    letter-spacing: 0.03em;
    transition: all 0.15s ease;
    padding: 0.5rem 1.25rem;
}
.stButton > button[kind="primary"] {
    background-color: #C18A82;
    border-color: #C18A82;
}
.stButton > button[kind="primary"]:hover {
    background-color: #A87268;
    border-color: #A87268;
}

/* Form-submit primary button matches */
.stFormSubmitButton > button[kind="primary"] {
    background-color: #C18A82;
    border-color: #C18A82;
}
.stFormSubmitButton > button[kind="primary"]:hover {
    background-color: #A87268;
    border-color: #A87268;
}

/* Brand wordmark */
.wg-wordmark {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 2.25rem;
    font-weight: 500;
    color: #2C2826;
    letter-spacing: 0.02em;
    text-align: center;
    margin: 1.5rem 0 0.5rem;
    line-height: 1.1;
}
.wg-wordmark-sub {
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem;
    font-weight: 500;
    color: #8B7E78;
    letter-spacing: 0.32em;
    text-align: center;
    text-transform: uppercase;
    margin-bottom: 2.5rem;
}

/* Section captions used inline */
.wg-caption {
    color: #8B7E78;
    font-size: 0.875rem;
    text-align: center;
}

/* Bordered container — subtle shadow over the default border */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 6px !important;
    background: #FFFFFF !important;
}
</style>
"""


def apply_style() -> None:
    """Inject global CSS. Safe to call once per page."""
    st.markdown(_HEAD + _CSS, unsafe_allow_html=True)


def wordmark(tagline: str = "Inventory · Sales · Care") -> None:
    """Render the brand wordmark + tagline."""
    st.markdown(
        f'<div class="wg-wordmark">Wrapped with Gratitude</div>'
        f'<div class="wg-wordmark-sub">{tagline}</div>',
        unsafe_allow_html=True,
    )
