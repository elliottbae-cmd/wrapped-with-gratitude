"""Marketing — Photo Studio + future email campaigns.

Tab 1: Photo Studio
  Upload phone photo → Replicate removes the background → composite on a
  branded gradient backdrop → optionally Claude drafts 3 caption variants.
  Save to the marketing-photos bucket and the marketing_photos table.

Tab 2: Gallery
  Browse / re-download past creations.

Tab 3: Email Campaigns (placeholder for Phase 4a).
"""
from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path

import streamlit as st
from PIL import Image

from config import load
from services import photo_studio as ps
from services.caption_generator import generate_captions
from ui.auth import get_client, require_auth, sidebar_user_info


cfg = load()
st.set_page_config(page_title="Marketing", page_icon="📣", layout="wide")
require_auth()

st.title("📣 Marketing")
st.caption(
    "Polish phone photos, draft captions, and (soon) run email campaigns. "
    "She continues posting to her personal Instagram — this just makes the content easier."
)

client = get_client()


@st.cache_data(ttl=20, show_spinner=False)
def _gallery(_client, cache_key: str):
    return ps.list_marketing_photos(_client)


cache_key = st.session_state["access_token"]

tab_studio, tab_gallery, tab_email = st.tabs(["📸 Photo Studio", "🖼 Gallery", "✉️ Email (soon)"])


# =====================================================================
# Tab 1: Photo Studio
# =====================================================================
with tab_studio:
    # Session-state pieces for the studio workflow
    if "studio_enhanced_bytes" not in st.session_state:
        st.session_state.studio_enhanced_bytes = None
    if "studio_original_bytes" not in st.session_state:
        st.session_state.studio_original_bytes = None
    if "studio_palette" not in st.session_state:
        st.session_state.studio_palette = "cream"
    if "studio_captions" not in st.session_state:
        st.session_state.studio_captions = None
    if "studio_saved_id" not in st.session_state:
        st.session_state.studio_saved_id = None

    # --- 1. Upload ----------------------------------------------------
    st.subheader("1. Upload a photo")
    uploaded = st.file_uploader(
        "Pick a photo of a gift basket / product",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=False,
        key="studio_upload",
    )

    if uploaded is not None:
        new_sig = (uploaded.name, uploaded.size)
        if st.session_state.get("studio_upload_sig") != new_sig:
            # Fresh upload — reset downstream state
            st.session_state.studio_upload_sig = new_sig
            st.session_state.studio_original_bytes = uploaded.getvalue()
            st.session_state.studio_original_name = uploaded.name
            st.session_state.studio_original_mime = uploaded.type
            st.session_state.studio_enhanced_bytes = None
            st.session_state.studio_captions = None
            st.session_state.studio_saved_id = None

    # --- 2. Enhance ---------------------------------------------------
    if st.session_state.studio_original_bytes:
        st.markdown("&nbsp;")
        st.subheader("2. Polish it")

        pc1, pc2 = st.columns([2, 1])
        with pc1:
            palette = st.selectbox(
                "Backdrop",
                options=list(ps.BACKDROP_PALETTES.keys()),
                index=list(ps.BACKDROP_PALETTES.keys()).index(st.session_state.studio_palette),
                key="studio_palette_picker",
                help="Choose the backdrop color/feel. Generated on the fly — no asset files.",
            )
            st.session_state.studio_palette = palette
        with pc2:
            enhance_clicked = st.button(
                "✨ Enhance",
                type="primary",
                use_container_width=True,
                disabled=not cfg.replicate_api_token,
                help=("Replicate API token required — set REPLICATE_API_TOKEN."
                      if not cfg.replicate_api_token else None),
            )

        if not cfg.replicate_api_token:
            st.warning(
                "Set `REPLICATE_API_TOKEN` in your `.env` (and Streamlit Cloud Secrets) "
                "and restart to enable enhancement."
            )

        if enhance_clicked:
            with st.spinner("Removing background and compositing on the backdrop…"):
                try:
                    enhanced = ps.enhance_photo(
                        image_bytes=st.session_state.studio_original_bytes,
                        mime_type=st.session_state.studio_original_mime,
                        api_token=cfg.replicate_api_token,
                        palette=palette,
                    )
                    st.session_state.studio_enhanced_bytes = enhanced
                    # Clear captions if backdrop changed — re-generate from final image
                    st.session_state.studio_captions = None
                    st.session_state.studio_saved_id = None
                except Exception as e:
                    st.error(f"Enhancement failed: {e}")

        # Side-by-side preview
        if st.session_state.studio_enhanced_bytes:
            pv1, pv2 = st.columns(2)
            with pv1:
                st.caption("Original")
                st.image(st.session_state.studio_original_bytes, use_container_width=True)
            with pv2:
                st.caption("Enhanced")
                st.image(st.session_state.studio_enhanced_bytes, use_container_width=True)

            ac1, ac2 = st.columns(2)
            with ac1:
                st.download_button(
                    "⬇ Download enhanced PNG",
                    data=st.session_state.studio_enhanced_bytes,
                    file_name=f"wwg-enhanced-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png",
                    mime="image/png",
                    type="primary",
                    use_container_width=True,
                )
            with ac2:
                if not st.session_state.studio_saved_id:
                    save_now = st.button("💾 Save to gallery", use_container_width=True)
                    if save_now:
                        with st.spinner("Saving to Storage + gallery…"):
                            try:
                                orig_path = ps.upload_photo_to_storage(
                                    client,
                                    st.session_state.studio_original_bytes,
                                    "original",
                                    content_type=(st.session_state.studio_original_mime or "image/jpeg"),
                                )
                            except Exception as e:
                                st.warning(f"Original upload failed ({e}); proceeding without it.")
                                orig_path = None

                            enh_path = ps.upload_photo_to_storage(
                                client,
                                st.session_state.studio_enhanced_bytes,
                                "enhanced",
                                content_type="image/png",
                            )
                            photo_id = ps.save_marketing_photo(
                                client,
                                original_path=orig_path,
                                enhanced_path=enh_path,
                                backdrop=st.session_state.studio_palette,
                            )
                            st.session_state.studio_saved_id = photo_id
                            _gallery.clear()
                            st.success("Saved to your gallery.")
                            st.rerun()
                else:
                    st.success(f"Saved (id: `{st.session_state.studio_saved_id[:8]}…`)")

        # --- 3. Caption ------------------------------------------------
        if st.session_state.studio_enhanced_bytes:
            st.markdown("&nbsp;")
            st.subheader("3. Draft a caption")

            cc1, cc2, cc3 = st.columns([1, 1, 1])
            with cc1:
                tone = st.selectbox(
                    "Tone",
                    options=["warm", "casual", "professional"],
                    key="studio_tone",
                )
            with cc2:
                occasion = st.text_input(
                    "Occasion / context",
                    placeholder="e.g., Mother's Day, hostess gift, just because",
                    key="studio_occasion",
                )
            with cc3:
                audience = st.text_input(
                    "Audience (optional)",
                    placeholder="e.g., new moms, brides, teachers",
                    key="studio_audience",
                )

            items_in_basket = st.text_input(
                "Items in this basket (optional)",
                placeholder="e.g., Summer Fridays Jet Lag mask, hand-poured candle, linen napkins",
                help="Helps Claude reference specifics. Leave blank if you want a more general caption.",
                key="studio_items",
            )

            extra_notes = st.text_input(
                "Anything else to weave in? (optional)",
                placeholder="e.g., 20% off this weekend, made for a friend's birthday",
                key="studio_extra",
            )

            gen_clicked = st.button(
                "✨ Generate 3 caption variants",
                type="primary",
                use_container_width=True,
            )

            if gen_clicked:
                with st.spinner("Claude is drafting…"):
                    try:
                        variants = generate_captions(
                            image_bytes=st.session_state.studio_enhanced_bytes,
                            mime_type="image/png",
                            anthropic_api_key=cfg.anthropic_api_key,
                            tone=tone,
                            items_in_basket=items_in_basket,
                            occasion=occasion,
                            audience=audience,
                            extra_notes=extra_notes,
                        )
                        st.session_state.studio_captions = variants
                    except Exception as e:
                        st.error(f"Caption generation failed: {e}")

            if st.session_state.studio_captions:
                st.markdown("**Pick your favorite (or edit any of them):**")
                for i, v in enumerate(st.session_state.studio_captions):
                    with st.container(border=True):
                        st.markdown(f"**Variant {i+1}** · _{v['angle']}_")
                        edited = st.text_area(
                            f"Caption {i+1}",
                            value=v["caption"],
                            height=180,
                            key=f"studio_caption_text_{i}",
                            label_visibility="collapsed",
                        )
                        st.session_state.studio_captions[i]["caption"] = edited

                        sub_c1, sub_c2 = st.columns([1, 1])
                        with sub_c1:
                            st.download_button(
                                "⬇ Download caption (.txt)",
                                data=edited,
                                file_name=f"caption-variant-{i+1}.txt",
                                mime="text/plain",
                                key=f"studio_dl_caption_{i}",
                                use_container_width=True,
                            )
                        with sub_c2:
                            if st.session_state.studio_saved_id:
                                use_btn = st.button(
                                    "Use this one (save to gallery)",
                                    key=f"studio_use_caption_{i}",
                                    type="primary",
                                    use_container_width=True,
                                )
                                if use_btn:
                                    ps.update_caption(
                                        client,
                                        st.session_state.studio_saved_id,
                                        edited,
                                        caption_tone=tone,
                                    )
                                    _gallery.clear()
                                    st.success("Caption saved to gallery.")
                            else:
                                st.caption("Save the photo to gallery first to attach a caption.")


# =====================================================================
# Tab 2: Gallery
# =====================================================================
with tab_gallery:
    st.subheader("Your gallery")
    photos = _gallery(client, cache_key)

    if not photos:
        st.info("No saved photos yet. Polish one in the Photo Studio tab and click 'Save to gallery'.")
    else:
        # Render as a 3-column grid
        cols_per_row = 3
        for row_start in range(0, len(photos), cols_per_row):
            row_photos = photos[row_start:row_start + cols_per_row]
            cols = st.columns(cols_per_row)
            for col, p in zip(cols, row_photos):
                with col:
                    with st.container(border=True):
                        try:
                            enh_bytes = ps.download_photo(client, p["enhanced_path"])
                            st.image(enh_bytes, use_container_width=True)
                        except Exception as e:
                            st.caption(f"⚠ image load failed: {e}")
                            enh_bytes = None

                        st.caption(
                            f"_{p.get('backdrop', '—')}_ · "
                            f"{p.get('created_at', '')[:10]}"
                        )
                        if p.get("caption_text"):
                            with st.expander("Caption"):
                                st.write(p["caption_text"])
                        if enh_bytes:
                            st.download_button(
                                "⬇ Download",
                                data=enh_bytes,
                                file_name=f"wwg-{p['id'][:8]}.png",
                                mime="image/png",
                                key=f"gallery_dl_{p['id']}",
                                use_container_width=True,
                            )


# =====================================================================
# Tab 3: Email (placeholder)
# =====================================================================
with tab_email:
    st.subheader("Email Campaigns")
    st.caption(
        "Coming next: compose an email, pick a customer segment, send via SendGrid, "
        "track opens/clicks. Sign up at sendgrid.com when you're ready and we'll wire it in."
    )
    st.info("Not yet built — Phase 4a is on the roadmap.")
