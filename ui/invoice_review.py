"""Editable review table for a parsed invoice.

Flow:
  1. Show parsed header (vendor, date, totals) — editable.
  2. Show parsed lines in a data_editor — qty, unit_price, description editable.
  3. On "Commit": each line's description is looked up in inventory_items by
     name (case-insensitive). New descriptions create new SKUs automatically.
     Then run the allocator and insert invoice + lines + lots.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import streamlit as st
from supabase import Client

from services.invoice_allocator import LineInput, allocate
from services.inventory import (
    CommitLine,
    commit_invoice,
    find_existing_invoice,
    find_or_create_inventory_item,
    find_or_create_vendor,
    upload_invoice_pdf,
)


def render(
    parsed: dict[str, Any],
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
    client: Client,
) -> None:
    """Render the review form. Calls commit_invoice on submission."""
    # Lazy-import pandas so just navigating to the Upload page doesn't pay
    # the pandas import cost.
    import pandas as pd

    st.subheader("Review parsed invoice")
    if parsed.get("notes"):
        st.warning(f"Parser notes: {parsed['notes']}")

    # ---- Header ----
    c1, c2, c3 = st.columns(3)
    with c1:
        vendor_name = st.text_input("Vendor", value=parsed.get("vendor_name", ""))
    with c2:
        invoice_number = st.text_input("Invoice #", value=parsed.get("invoice_number", ""))
    with c3:
        try:
            inv_date = date.fromisoformat(parsed.get("invoice_date") or date.today().isoformat())
        except (ValueError, TypeError):
            inv_date = date.today()
        invoice_date = st.date_input("Invoice date", value=inv_date)

    c4, c5, c6, c7 = st.columns(4)
    with c4:
        subtotal = st.number_input(
            "Subtotal", value=float(parsed.get("subtotal", 0) or 0), step=0.01, format="%.2f"
        )
    with c5:
        shipping = st.number_input(
            "Shipping", value=float(parsed.get("shipping", 0) or 0), step=0.01, format="%.2f"
        )
    with c6:
        tax = st.number_input(
            "Tax", value=float(parsed.get("tax", 0) or 0), step=0.01, format="%.2f"
        )
    with c7:
        other_charges = st.number_input(
            "Other", value=float(parsed.get("other_charges", 0) or 0), step=0.01, format="%.2f"
        )

    total = st.number_input(
        "Total (from invoice)",
        value=float(parsed.get("total", 0) or 0),
        step=0.01,
        format="%.2f",
        help="Used for audit. The allocator works off subtotal + shipping + tax + other.",
    )

    # ---- Lines ----
    st.markdown(
        "**Line items** — edit qty / unit price / description as needed. "
        "New descriptions will be auto-created as inventory items; matching "
        "names will reuse existing SKUs."
    )

    raw_lines = parsed.get("line_items", []) or []
    df = pd.DataFrame(
        [
            {
                "description": ln.get("description", ""),
                "sku_hint":    ln.get("sku", ""),
                "category":    ln.get("category", ""),
                "pack_size":   int(ln.get("pack_size", 1) or 1),
                "qty":         float(ln.get("qty", 0) or 0),
                "unit_price":  float(ln.get("unit_price", 0) or 0),
            }
            for ln in raw_lines
        ]
    )

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "description": st.column_config.TextColumn("Description", required=True, width="large"),
            "sku_hint":    st.column_config.TextColumn("Vendor SKU", help="Optional, from the invoice"),
            "category":    st.column_config.TextColumn("Category", help="Claude's guess — edit if you want a different label"),
            "pack_size":   st.column_config.NumberColumn(
                "Pack size",
                min_value=1,
                step=1,
                format="%d",
                help="Individual units per pack (e.g. '30 Pack' → 30). Inventory qty = qty × pack size.",
                required=True,
            ),
            "qty":         st.column_config.NumberColumn("Qty (packs)", min_value=0.001, step=1, format="%.3f", required=True),
            "unit_price":  st.column_config.NumberColumn("Unit price (per pack)", min_value=0.0, step=0.01, format="%.4f", required=True),
        },
        key="invoice_lines_editor",
    )

    # Line items totals
    if not edited.empty:
        valid = edited.dropna(subset=["description"])
        valid = valid[valid["description"].astype(str).str.strip() != ""]
        n_lines = len(valid)
        total_packs = float(valid["qty"].fillna(0).sum())
        total_line_sum = float((valid["qty"].fillna(0) * valid["unit_price"].fillna(0)).sum())
        total_inventory_units = float(
            (valid["qty"].fillna(0) * valid["pack_size"].fillna(1)).sum()
        )
        any_pack_expansion = (valid["pack_size"].fillna(1) > 1).any()

        match_text = (
            f" _(matches invoice subtotal ${subtotal:,.2f})_"
            if abs(total_line_sum - subtotal) <= 0.02
            else f" _(Δ ${total_line_sum - subtotal:+,.2f} vs invoice subtotal ${subtotal:,.2f})_"
        )

        if any_pack_expansion:
            st.caption(
                f"**{n_lines}** line(s) · "
                f"**{total_packs:,.0f}** pack(s) ordered → "
                f"**{total_inventory_units:,.0f}** individual unit(s) to inventory · "
                f"line subtotal sum **${total_line_sum:,.2f}**" + match_text
            )
        else:
            st.caption(
                f"**{n_lines}** line(s) · "
                f"**{total_packs:,.0f}** unit(s) · "
                f"line subtotal sum **${total_line_sum:,.2f}**" + match_text
            )

    # Live preview of allocations — expand packs so the preview shows what
    # actually lands in inventory (individual units, not packs ordered).
    if not edited.empty and (subtotal + shipping + tax + other_charges) > 0:
        try:
            preview_lines = []
            for _, row in edited.iterrows():
                pack = int(row.get("pack_size") or 1)
                expanded_qty = Decimal(str(row["qty"])) * pack
                per_unit_price = (
                    Decimal(str(row["unit_price"])) / Decimal(pack)
                    if pack > 1
                    else Decimal(str(row["unit_price"]))
                )
                preview_lines.append(
                    LineInput(
                        description=row["description"],
                        qty=expanded_qty,
                        unit_price=per_unit_price,
                    )
                )
            alloc = allocate(
                preview_lines,
                Decimal(str(shipping)),
                Decimal(str(tax)),
                Decimal(str(other_charges)),
            )
            preview_rows = [
                {
                    "Description":     a.description,
                    "Qty":             float(a.qty),
                    "Line subtotal":   float(a.line_subtotal),
                    "+Ship":           float(a.allocated_shipping),
                    "+Tax":            float(a.allocated_tax),
                    "+Other":          float(a.allocated_other),
                    "Landed/unit":     float(a.landed_unit_cost),
                    "Total landed":    float(a.qty) * float(a.landed_unit_cost),
                }
                for a in alloc
            ]
            # Append a TOTAL row
            total_qty_p     = sum(r["Qty"]           for r in preview_rows)
            total_sub_p     = sum(r["Line subtotal"] for r in preview_rows)
            total_ship_p    = sum(r["+Ship"]         for r in preview_rows)
            total_tax_p     = sum(r["+Tax"]          for r in preview_rows)
            total_other_p   = sum(r["+Other"]        for r in preview_rows)
            total_landed_p  = sum(r["Total landed"]  for r in preview_rows)
            wac_p = (total_landed_p / total_qty_p) if total_qty_p else 0.0
            preview_rows.append({
                "Description":   "TOTAL",
                "Qty":           total_qty_p,
                "Line subtotal": total_sub_p,
                "+Ship":         total_ship_p,
                "+Tax":          total_tax_p,
                "+Other":        total_other_p,
                "Landed/unit":   wac_p,    # weighted avg across this invoice
                "Total landed":  total_landed_p,
            })
            preview = pd.DataFrame(preview_rows)
            st.caption("Landed cost preview (with allocated shipping/tax):")
            st.dataframe(
                preview,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Qty":           st.column_config.NumberColumn(format="%.3f"),
                    "Line subtotal": st.column_config.NumberColumn(format="$%.2f"),
                    "+Ship":         st.column_config.NumberColumn(format="$%.2f"),
                    "+Tax":          st.column_config.NumberColumn(format="$%.2f"),
                    "+Other":        st.column_config.NumberColumn(format="$%.2f"),
                    "Landed/unit":   st.column_config.NumberColumn(format="$%.4f"),
                    "Total landed":  st.column_config.NumberColumn(format="$%.2f"),
                },
            )
        except Exception as e:
            st.info(f"Allocation preview unavailable: {e}")

    # ---- Validation ----
    st.divider()

    # Hard blockers (data missing / invalid) — commit always blocked
    blockers: list[str] = []
    # Math discrepancies — overridable via checkbox; persisted to DB if overridden
    math_issues: list[str] = []
    # Parser advisories — informational only, never gate the commit
    parser_advisories: list[str] = []

    if not vendor_name.strip():
        blockers.append("Vendor name is required.")

    if edited.empty:
        blockers.append("At least one line item is required.")
    else:
        if (edited["qty"].fillna(0) <= 0).any():
            blockers.append("Every line must have qty > 0.")
        if (edited["unit_price"].fillna(0) < 0).any():
            blockers.append("Unit price cannot be negative on any line.")
        if edited["description"].fillna("").str.strip().eq("").any():
            blockers.append("Every line needs a description.")

    # Math tie-outs (overridable warnings)
    line_sum = 0.0
    subtotal_delta = 0.0
    if not edited.empty:
        line_sum = float(
            (edited["qty"].fillna(0) * edited["unit_price"].fillna(0)).sum()
        )
        subtotal_delta = round(line_sum - subtotal, 2)
        if abs(subtotal_delta) > 0.02:
            math_issues.append(
                f"Line subtotals sum to **${line_sum:,.2f}** but invoice subtotal is "
                f"**${subtotal:,.2f}** (Δ ${subtotal_delta:+,.2f})."
            )

    header_sum = round(subtotal + shipping + tax + other_charges, 2)
    total_delta = round(header_sum - total, 2)
    if abs(total_delta) > 0.02:
        math_issues.append(
            f"Subtotal + shipping + tax + other = **${header_sum:,.2f}** but stated total is "
            f"**${total:,.2f}** (Δ ${total_delta:+,.2f})."
        )

    # Parser advisories are informational only — do NOT gate the commit button
    if parsed.get("notes"):
        parser_advisories.append(
            "Parser flagged ambiguity — see the parser notes at the top of the form. "
            "Math may still tie out; this is just a reminder to double-check."
        )

    for b in blockers:
        st.error(b)
    for w in math_issues:
        st.warning(w)
    for a in parser_advisories:
        st.info(a)

    if not blockers and not math_issues:
        st.success("All math ties out. Ready to post.")

    # Override checkbox shown only when math has actually failed
    override_math = False
    if math_issues and not blockers:
        override_math = st.checkbox(
            "I've reviewed the discrepancies — commit anyway",
            help="The invoice + lots will be posted exactly as shown. It will be flagged "
                 "as having a math discrepancy and surfaced on the home page for follow-up.",
        )

    can_commit = not blockers and (not math_issues or override_math)

    # Build the discrepancy detail string we'll persist with the invoice (if overridden)
    discrepancy_detail: str | None = None
    if math_issues and override_math:
        detail_lines = []
        if abs(subtotal_delta) > 0.02:
            detail_lines.append(
                f"Line subtotals sum: ${line_sum:,.2f}; invoice subtotal: ${subtotal:,.2f}; "
                f"Δ ${subtotal_delta:+,.2f}"
            )
        if abs(total_delta) > 0.02:
            detail_lines.append(
                f"Header sum (sub+ship+tax+other): ${header_sum:,.2f}; "
                f"stated total: ${total:,.2f}; Δ ${total_delta:+,.2f}"
            )
        discrepancy_detail = " | ".join(detail_lines)

    # ---- Commit ----
    commit_clicked = st.button(
        "Commit to inventory",
        type="primary",
        use_container_width=True,
        disabled=not can_commit,
    )

    if not commit_clicked:
        return

    with st.spinner("Committing..."):
        # 1. Vendor — track new vs existing for the summary
        before_vendors = client.table("vendors").select("id", count="exact").execute().count or 0
        vendor_id = find_or_create_vendor(client, vendor_name)
        after_vendors = client.table("vendors").select("id", count="exact").execute().count or 0
        vendor_was_new = after_vendors > before_vendors

        # 2. Duplicate-invoice check
        existing_inv = find_existing_invoice(client, vendor_id, invoice_number or None)
        if existing_inv:
            st.warning(
                f"Invoice #{invoice_number} from this vendor was already posted on "
                f"{existing_inv['invoice_date']}. Not re-importing."
            )
            return

        # 3. Resolve each line's inventory_item_id, tracking which were newly created.
        # Pack-expand: feed the allocator individual-unit qty + per-unit price so
        # the resulting landed_unit_cost is per individual inventory unit.
        commit_lines_input: list[LineInput] = []
        item_ids: list[str] = []
        pack_sizes: list[int] = []
        new_item_descriptions: list[str] = []
        for _, row in edited.iterrows():
            # Snapshot count to detect if find_or_create created a new item
            before_items = client.table("inventory_items").select("id", count="exact").execute().count or 0
            item_id = find_or_create_inventory_item(
                client,
                name=row["description"],
                sku=row.get("sku_hint") or None,
                category=row.get("category") or None,
            )
            after_items = client.table("inventory_items").select("id", count="exact").execute().count or 0
            if after_items > before_items:
                new_item_descriptions.append(row["description"])
            item_ids.append(item_id)

            pack = int(row.get("pack_size") or 1)
            pack_sizes.append(pack)
            expanded_qty = Decimal(str(row["qty"])) * pack
            per_unit_price = (
                Decimal(str(row["unit_price"])) / Decimal(pack)
                if pack > 1
                else Decimal(str(row["unit_price"]))
            )
            commit_lines_input.append(
                LineInput(
                    description=row["description"],
                    qty=expanded_qty,
                    unit_price=per_unit_price,
                )
            )

        # 4. Allocate landed cost
        allocated = allocate(
            commit_lines_input,
            Decimal(str(shipping)),
            Decimal(str(tax)),
            Decimal(str(other_charges)),
        )

        commit_lines = [
            CommitLine(
                inventory_item_id=item_ids[i],
                description=a.description,
                qty=a.qty,
                unit_price=a.unit_price,
                line_subtotal=a.line_subtotal,
                allocated_shipping=a.allocated_shipping,
                allocated_tax=a.allocated_tax,
                allocated_other=a.allocated_other,
                landed_unit_cost=a.landed_unit_cost,
                pack_size=pack_sizes[i],
            )
            for i, a in enumerate(allocated)
        ]

        # 5. Upload the original file to Storage
        try:
            pdf_path = upload_invoice_pdf(client, file_bytes, file_name, mime_type)
        except Exception as e:
            st.warning(f"Storage upload failed ({e}); proceeding without archived PDF.")
            pdf_path = None

        # 6. Insert invoice + lines + lots
        invoice_id = commit_invoice(
            client=client,
            vendor_id=vendor_id,
            invoice_number=invoice_number or None,
            invoice_date=invoice_date.isoformat(),
            subtotal=Decimal(str(subtotal)),
            shipping=Decimal(str(shipping)),
            tax=Decimal(str(tax)),
            other_charges=Decimal(str(other_charges)),
            total=Decimal(str(total)),
            lines=commit_lines,
            pdf_path=pdf_path,
            raw_extracted_json=parsed,
            has_math_discrepancy=bool(discrepancy_detail),
            discrepancy_detail=discrepancy_detail,
        )

    # ---- Post-commit summary ----
    if discrepancy_detail:
        st.warning(
            f"Invoice posted to inventory **with math discrepancy flagged for review** — "
            f"{discrepancy_detail}"
        )
    else:
        st.success("Invoice posted to inventory")
    st.balloons()

    total_cost_basis = float(sum(
        l.line_subtotal + l.allocated_shipping + l.allocated_tax + l.allocated_other
        for l in commit_lines
    ))
    total_units = float(sum(l.qty for l in commit_lines))

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Vendor", vendor_name, "new" if vendor_was_new else "existing")
    sc2.metric("Line items / lots", len(commit_lines))
    sc3.metric("Units received", f"{total_units:,.0f}")
    sc4.metric("Cost basis added", f"${total_cost_basis:,.2f}")

    if new_item_descriptions:
        with st.expander(f"New SKUs created ({len(new_item_descriptions)})", expanded=True):
            for desc in new_item_descriptions:
                st.markdown(f"- {desc}")

    matched_count = len(commit_lines) - len(new_item_descriptions)
    if matched_count > 0:
        st.caption(f"{matched_count} line(s) matched existing SKUs.")

    st.caption(f"Invoice ID: `{invoice_id}`")
    if pdf_path:
        st.caption(f"PDF archived to Storage: `invoices/{pdf_path}`")

    st.page_link("pages/2_Inventory.py", label="View inventory →")

    # Clear the parsed result so the page can accept a new upload
    st.session_state.pop("parsed_invoice", None)
    st.session_state.pop("uploaded_file_meta", None)
    # Invalidate cached inventory queries so the Inventory page reflects the new lots immediately
    st.cache_data.clear()
