"""Claude vision invoice parser.

Sends a PDF or image to Claude and forces a tool call that returns structured
invoice data. Tool use guarantees a valid JSON shape (vs. asking for free-text
JSON and hoping). System prompt + tool definition are cached so repeated
uploads in the same session don't re-pay for those tokens.
"""
from __future__ import annotations

import base64
from typing import Any


MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are an invoice data extractor for a small gift-making business.

Your job: read the vendor invoice in the attached file and call the
`extract_invoice` tool with the structured data.

Rules:
- Use the invoice's stated totals (subtotal, shipping, tax, total) verbatim
  — do NOT recompute them. If they don't add up, report the discrepancy in
  the `notes` field but still pass the stated numbers through.
- Line items: one row per distinct product line. If the same SKU appears
  twice on the invoice, keep them as two separate lines (we preserve invoice
  fidelity here; deduping happens later).
- `qty` and `unit_price` must come from the invoice. If only a line total
  is shown, set unit_price = line_total / qty.
- `category`: infer a sensible product category from the product title
  (e.g. "Skincare", "Bath & Body", "Kitchen", "Stationery", "Candles",
  "Stickers", "Apparel", "Pet", "Home Decor", "Jewelry", "Toys", "Food").
  Use the most specific term that's still general enough to reuse across
  similar items. Default to "Other" only if the title gives no clue.
- IMPORTANT — pack size vs order quantity: extract them as TWO separate
  fields. `pack_size` is how many individual units come in one pack/set,
  detected from the product title:
    "Eccliy 30 Pack 12x12x6 Tote Bag" → pack_size=30
    "Summer Fridays Mini Skin Set (4 Count)" → pack_size=4
    "Pack of 2 Geometry Towels" → pack_size=2
    "Set of 6 Mugs" → pack_size=6
    "12 ct Tea Bags" → pack_size=12
    "Single Bottle Cleanser" → pack_size=1
  `qty` is the number of PACKS the customer ordered (almost always 1 on
  Amazon orders unless a numeric badge clearly shows more). `unit_price` is
  the price per PACK as printed.
- Self-check: qty × unit_price must equal the line total shown on the
  invoice. If a single "30 Pack" line shows $66.99, the correct extraction
  is qty=1, unit_price=66.99, pack_size=30 (NOT qty=30 with unit_price=2.23).
- If a numeric badge on the product image conflicts with pack-size language
  in the title (e.g. badge "2" + title "Pack of 4"), trust the title and
  default qty=1 — flag the conflict in `notes` for human review.
- Dates: always YYYY-MM-DD. If only a partial date is visible, do your best
  and mention the ambiguity in `notes`.
- Empty strings (not null) for optional text fields that aren't present.
- Zero (not null) for optional numeric fields that aren't present.
- `notes` is for the human reviewer — flag anything ambiguous, unclear, or
  worth double-checking before posting. Quantity ambiguity is the most
  common parser failure mode, so always note it when uncertain.
"""

EXTRACT_TOOL: dict[str, Any] = {
    "name": "extract_invoice",
    "description": "Submit structured data extracted from a vendor invoice.",
    "input_schema": {
        "type": "object",
        "properties": {
            "vendor_name":    {"type": "string", "description": "Vendor / seller name"},
            "vendor_email":   {"type": "string", "description": "Vendor email if visible, else empty string"},
            "vendor_phone":   {"type": "string", "description": "Vendor phone if visible, else empty string"},
            "invoice_number": {"type": "string", "description": "Invoice number or ID; empty string if absent"},
            "invoice_date":   {"type": "string", "description": "Invoice date as YYYY-MM-DD"},
            "subtotal":       {"type": "number", "description": "Subtotal before shipping/tax/other"},
            "shipping":       {"type": "number", "description": "Shipping/freight charges; 0 if none"},
            "tax":            {"type": "number", "description": "Sales tax; 0 if none"},
            "other_charges":  {"type": "number", "description": "Other fees not in subtotal/shipping/tax; 0 if none"},
            "total":          {"type": "number", "description": "Grand total"},
            "line_items": {
                "type": "array",
                "description": "Individual product lines from the invoice.",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "description": "Product description as printed"},
                        "sku":         {"type": "string", "description": "Vendor SKU / item number if shown, else empty string"},
                        "category":    {"type": "string", "description": "Best-guess category inferred from product title — e.g. 'Skincare', 'Kitchen', 'Stationery', 'Candles', 'Stickers', 'Apparel', 'Pet', 'Home Decor'. Use 'Other' if unclear. Never leave empty."},
                        "pack_size":   {"type": "integer", "description": "Number of individual sellable units bundled in each pack/set as indicated by the product title — e.g. '30 Pack' → 30, 'Pack of 4' → 4, 'Set of 2' → 2, '12 Count' → 12, '6 ct' → 6. Default to 1 if the title gives no pack indicator. This is per-pack, NOT order quantity."},
                        "qty":         {"type": "number", "description": "Quantity of PACKS ordered (not individual units). For a single '30 Pack' bought once, qty=1."},
                        "unit_price":  {"type": "number", "description": "Price per PACK (not per individual unit). For one '30 Pack' costing $66.99, unit_price=66.99."},
                    },
                    "required": ["description", "qty", "unit_price", "category", "pack_size"],
                },
            },
            "notes": {
                "type": "string",
                "description": "Anything ambiguous or worth human review; empty string if all clear",
            },
        },
        "required": [
            "vendor_name", "invoice_date", "subtotal", "shipping", "tax",
            "total", "line_items",
        ],
    },
}


def _file_block(file_bytes: bytes, mime_type: str) -> dict[str, Any]:
    """Wrap the uploaded file as a vision content block."""
    b64 = base64.standard_b64encode(file_bytes).decode("ascii")
    if mime_type == "application/pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": mime_type, "data": b64},
        }
    if mime_type in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": mime_type, "data": b64},
        }
    raise ValueError(f"Unsupported file type: {mime_type}")


def parse_invoice(
    file_bytes: bytes,
    mime_type: str,
    anthropic_api_key: str,
) -> dict[str, Any]:
    """Parse an invoice file. Returns the tool input dict (already validated by the API).

    Raises ValueError on unsupported MIME types or if the model didn't return a tool call.
    """
    # Lazy-import so the Upload Invoice page doesn't pay the anthropic SDK
    # import cost just from navigating to it.
    from anthropic import Anthropic

    client = Anthropic(api_key=anthropic_api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_invoice"},
        messages=[{
            "role": "user",
            "content": [
                _file_block(file_bytes, mime_type),
                {"type": "text", "text": "Extract this invoice's data and call the tool."},
            ],
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_invoice":
            return block.input  # already validated against the schema

    raise ValueError(
        "Claude did not return a tool call. "
        f"Stop reason: {response.stop_reason}. "
        f"Content: {response.content!r}"
    )
