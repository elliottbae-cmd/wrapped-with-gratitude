"""Photo Studio — background removal + branded backdrop composite.

Pipeline:
  1. User uploads a phone photo (JPG/PNG).
  2. remove_background()   — Replicate model strips the background, returns
     RGBA PNG with the subject on transparent.
  3. composite_on_backdrop() — Pillow generates a gradient backdrop matching
     the brand palette, drops a soft shadow under the subject, centers + scales
     for an Instagram square crop.
  4. Caller persists original + enhanced to Storage.

Replicate model is configurable (BG_REMOVAL_MODEL). Default is a current
maintained model; swap if Replicate retires it.
"""
from __future__ import annotations

import base64
import io
import uuid
from typing import Iterable

import requests
from PIL import Image, ImageDraw, ImageFilter
from supabase import Client


# --------------------------------------------------------------------------
# Replicate model — swap if this version is retired.
# --------------------------------------------------------------------------
BG_REMOVAL_MODEL = "851-labs/background-remover"


# --------------------------------------------------------------------------
# Brand backdrops (gradients generated programmatically — no asset files)
# --------------------------------------------------------------------------
BACKDROP_PALETTES: dict[str, tuple[str, str]] = {
    "cream":   ("#FBF7F4", "#F5EBE6"),  # warm cream → soft blush
    "blush":   ("#F5EBE6", "#E5C8C0"),  # soft blush → dusty rose
    "sage":    ("#EFF1EB", "#C8D0BD"),  # cool cream → sage
    "marble":  ("#FFFFFF", "#F2F2F2"),  # white → barely-grey
    "linen":   ("#F4ECDF", "#E8DCC4"),  # linen → wheat
    "charcoal":("#3A332F", "#2C2826"),  # deep, moody
}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def make_backdrop(width: int, height: int, palette: str = "cream") -> Image.Image:
    """Vertical gradient backdrop, RGB."""
    top_hex, bot_hex = BACKDROP_PALETTES.get(palette, BACKDROP_PALETTES["cream"])
    top, bot = _hex_to_rgb(top_hex), _hex_to_rgb(bot_hex)
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    denom = max(1, height - 1)
    for y in range(height):
        t = y / denom
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def add_drop_shadow(
    subject_rgba: Image.Image,
    offset: tuple[int, int] = (12, 24),
    blur_radius: int = 18,
    opacity: int = 110,
) -> Image.Image:
    """Return a new RGBA with subject + drop shadow on a transparent canvas."""
    sw, sh = subject_rgba.size
    pad = max(abs(offset[0]), abs(offset[1])) + blur_radius * 2
    canvas_w = sw + 2 * pad
    canvas_h = sh + 2 * pad
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # Shadow: take alpha, blur it, dim it, paste offset
    alpha = subject_rgba.split()[3]
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(blur_radius))
    shadow_alpha = shadow_alpha.point(lambda p: min(int(p * opacity / 255), opacity))
    shadow = Image.new("RGBA", subject_rgba.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    canvas.paste(shadow, (pad + offset[0], pad + offset[1]), shadow)

    # Subject on top
    canvas.paste(subject_rgba, (pad, pad), subject_rgba)
    return canvas


def composite_on_backdrop(
    subject_rgba: Image.Image,
    palette: str = "cream",
    canvas_size: tuple[int, int] = (1080, 1080),
    subject_scale: float = 0.72,
) -> Image.Image:
    """Place a transparent-background subject onto a branded gradient backdrop.

    canvas_size: (width, height) — defaults to 1080×1080 Instagram square.
    subject_scale: subject occupies this fraction of the smaller canvas dim.
    """
    canvas_w, canvas_h = canvas_size
    backdrop = make_backdrop(canvas_w, canvas_h, palette).convert("RGBA")

    # Fit subject inside the target area while preserving aspect ratio
    target_max = int(min(canvas_w, canvas_h) * subject_scale)
    sw, sh = subject_rgba.size
    scale = min(target_max / sw, target_max / sh, 1.0)
    new_w = max(1, int(sw * scale))
    new_h = max(1, int(sh * scale))
    subject_scaled = subject_rgba.resize((new_w, new_h), Image.LANCZOS)

    subject_with_shadow = add_drop_shadow(subject_scaled)

    sw, sh = subject_with_shadow.size
    x = (canvas_w - sw) // 2
    # Slightly above true center for a more pleasing composition
    y = (canvas_h - sh) // 2 - int(canvas_h * 0.04)

    canvas = backdrop.copy()
    canvas.paste(subject_with_shadow, (x, y), subject_with_shadow)
    return canvas.convert("RGB")


# --------------------------------------------------------------------------
# Replicate — background removal
# --------------------------------------------------------------------------

def remove_background(image_bytes: bytes, mime_type: str, api_token: str) -> bytes:
    """Strip the background. Returns RGBA PNG bytes.

    Sends the image as a base64 data URI so we don't need to upload-then-pass-URL.
    """
    if not api_token:
        raise RuntimeError("REPLICATE_API_TOKEN not configured.")

    import replicate

    client = replicate.Client(api_token=api_token)
    b64 = base64.b64encode(image_bytes).decode()
    data_uri = f"data:{mime_type};base64,{b64}"

    try:
        output = client.run(BG_REMOVAL_MODEL, input={"image": data_uri})
    except Exception as e:
        raise RuntimeError(
            f"Replicate model `{BG_REMOVAL_MODEL}` failed: {e}. "
            f"If the model was retired, update BG_REMOVAL_MODEL in services/photo_studio.py."
        ) from e

    # Replicate's `run` returns various shapes depending on the model:
    # - A FileOutput-like object with .read() (newer SDK)
    # - A URL string
    # - A list of either
    if isinstance(output, list):
        output = output[0] if output else None
    if output is None:
        raise RuntimeError("Replicate returned no output.")

    if hasattr(output, "read"):
        return output.read()
    if isinstance(output, (bytes, bytearray)):
        return bytes(output)
    if isinstance(output, str):
        # URL — fetch the bytes
        resp = requests.get(output, timeout=60)
        resp.raise_for_status()
        return resp.content

    raise RuntimeError(f"Unexpected Replicate output type: {type(output).__name__}")


# --------------------------------------------------------------------------
# Full enhance pipeline
# --------------------------------------------------------------------------

def enhance_photo(
    image_bytes: bytes,
    mime_type: str,
    api_token: str,
    palette: str = "cream",
    canvas_size: tuple[int, int] = (1080, 1080),
) -> bytes:
    """Full pipeline: BG removal → composite on backdrop. Returns PNG bytes."""
    bg_removed_png = remove_background(image_bytes, mime_type, api_token)
    subject = Image.open(io.BytesIO(bg_removed_png)).convert("RGBA")
    final = composite_on_backdrop(subject, palette=palette, canvas_size=canvas_size)

    out = io.BytesIO()
    final.save(out, format="PNG", optimize=True)
    return out.getvalue()


# --------------------------------------------------------------------------
# Storage + DB helpers
# --------------------------------------------------------------------------

def upload_photo_to_storage(
    client: Client,
    file_bytes: bytes,
    filename_prefix: str,
    content_type: str = "image/png",
) -> str:
    """Upload to the `marketing-photos` bucket. Returns the object path."""
    ext = ".png" if "png" in content_type else (".jpg" if "jpeg" in content_type else ".bin")
    object_path = f"{filename_prefix}-{uuid.uuid4().hex[:10]}{ext}"
    client.storage.from_("marketing-photos").upload(
        path=object_path,
        file=file_bytes,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return object_path


def download_photo(client: Client, object_path: str) -> bytes:
    return client.storage.from_("marketing-photos").download(object_path)


def save_marketing_photo(
    client: Client,
    original_path: str | None,
    enhanced_path: str,
    backdrop: str,
    caption_text: str | None = None,
    caption_tone: str | None = None,
    sale_order_id: str | None = None,
    notes: str | None = None,
) -> str:
    row = {
        "original_path": original_path,
        "enhanced_path": enhanced_path,
        "backdrop": backdrop,
        "caption_text": caption_text,
        "caption_tone": caption_tone,
        "sale_order_id": sale_order_id,
        "notes": notes,
    }
    res = client.table("marketing_photos").insert(row).execute()
    return res.data[0]["id"]


def list_marketing_photos(client: Client, limit: int = 50) -> list[dict]:
    return (
        client.table("marketing_photos")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def update_caption(client: Client, photo_id: str, caption_text: str, caption_tone: str | None = None) -> None:
    updates: dict = {"caption_text": caption_text}
    if caption_tone is not None:
        updates["caption_tone"] = caption_tone
    client.table("marketing_photos").update(updates).eq("id", photo_id).execute()
