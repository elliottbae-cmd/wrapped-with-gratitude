"""Instagram caption generation for product photos.

Claude reads the (enhanced or original) photo + user-provided context, and
returns three caption variants via tool use so the structure is guaranteed.
"""
from __future__ import annotations

import base64
from typing import Any


MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You write Instagram captions for **Wrapped with Gratitude**,
a small gift-making business run by Alex Elliott. Alex curates and assembles
gift baskets — thoughtfully chosen products arranged with care.

Brand voice:
- Warm, personal, casual but elevated. Like a thoughtful friend, not a brand.
- Sells through feeling and story, never pushy or salesy.
- Gratitude and care are core themes — the name is the ethos.
- Emoji are fine in moderation, never as crutches. Vary by tone.
- Specific > generic. Reference the actual items in the basket if you can see them.

For each caption variant, follow this structure:
  1. Hook — a question, sensory detail, observation, or moment-in-time.
  2. Substance — what's in the basket, what makes it special, what it evokes.
  3. Soft CTA — e.g., "DMs are open for custom orders" or "link in bio".
     Vary the phrasing; don't repeat the same CTA every time.
  4. Hashtags — 6–10, mix of niche (small business, handmade gifts, curated
     baskets) and broader (gifting, self-care, hostess gift, etc.). Place at
     the very end on a new line.

Return THREE distinct variants. Each variant should approach the post from
a meaningfully different angle (e.g., recipient-focused, occasion-focused,
sensory-focused, story-focused) so the user has real choices."""


_TOOL: dict[str, Any] = {
    "name": "write_captions",
    "description": "Submit three Instagram caption variants for the user to pick from.",
    "input_schema": {
        "type": "object",
        "properties": {
            "variants": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "angle": {
                            "type": "string",
                            "description": "Short label for what this variant emphasizes (e.g., 'recipient-focused', 'sensory hook', 'gratitude theme').",
                        },
                        "caption": {
                            "type": "string",
                            "description": "Full caption including the body text and hashtag block, ready to paste into Instagram.",
                        },
                    },
                    "required": ["angle", "caption"],
                },
            },
        },
        "required": ["variants"],
    },
}


_TONE_GUIDANCE = {
    "warm":         "Lead with feeling. Cozy, intimate, slower pacing. Light emoji, all soft (🤍 🌿 ✨).",
    "casual":       "Conversational, playful, modern. More emoji, contractions, faster rhythm.",
    "professional": "Polished and restrained. Minimal emoji. Brand-forward, almost editorial.",
}


def _img_block(image_bytes: bytes, mime_type: str) -> dict[str, Any]:
    if mime_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        raise ValueError(f"Unsupported image type for caption generation: {mime_type}")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": base64.standard_b64encode(image_bytes).decode("ascii"),
        },
    }


def generate_captions(
    image_bytes: bytes,
    mime_type: str,
    anthropic_api_key: str,
    *,
    tone: str = "warm",
    items_in_basket: str = "",
    occasion: str = "",
    audience: str = "",
    extra_notes: str = "",
) -> list[dict[str, str]]:
    """Call Claude vision; return a list of {angle, caption} dicts (always 3)."""
    from anthropic import Anthropic

    client = Anthropic(api_key=anthropic_api_key)

    tone = tone if tone in _TONE_GUIDANCE else "warm"
    user_context_parts: list[str] = [
        f"Tone for this post: **{tone}**. {_TONE_GUIDANCE[tone]}",
    ]
    if items_in_basket.strip():
        user_context_parts.append(f"Items in this basket: {items_in_basket.strip()}")
    if occasion.strip():
        user_context_parts.append(f"Occasion / context: {occasion.strip()}")
    if audience.strip():
        user_context_parts.append(f"Intended audience: {audience.strip()}")
    if extra_notes.strip():
        user_context_parts.append(f"Extra notes: {extra_notes.strip()}")

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "write_captions"},
        messages=[{
            "role": "user",
            "content": [
                _img_block(image_bytes, mime_type),
                {
                    "type": "text",
                    "text": (
                        "Write three Instagram caption variants for this gift basket "
                        "photo.\n\n" + "\n".join(user_context_parts)
                    ),
                },
            ],
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "write_captions":
            variants = block.input.get("variants", [])
            return [{"angle": v.get("angle", ""), "caption": v.get("caption", "")} for v in variants]

    raise RuntimeError(
        f"Claude did not return caption variants. stop_reason={response.stop_reason!r}"
    )
