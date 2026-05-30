"""Customer-facing invoice PDF generator.

Uses reportlab's platypus flowables to build a single-page invoice that
matches the app's blush/charcoal/ivory palette.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# Palette — matches ui/style.py
_BLUSH      = colors.HexColor("#C18A82")
_CHARCOAL   = colors.HexColor("#2C2826")
_TAUPE      = colors.HexColor("#8B7E78")
_SOFT_BLUSH = colors.HexColor("#F5EBE6")
_CREAM      = colors.HexColor("#FBF7F4")


def generate_invoice_pdf(
    *,
    business_name: str,
    business_email: str,
    business_phone: str,
    business_venmo: str,
    order_number: str,
    order_date: date,
    customer_name: str,
    customer_email: str | None,
    customer_phone: str | None,
    shipping_address: str | None,
    lines: list[dict],     # each: description, qty, unit_price, line_total
    subtotal: Decimal,
    shipping: Decimal,
    tax: Decimal,
    total: Decimal,
    notes: str | None = None,
) -> bytes:
    """Render a customer invoice PDF. Returns the bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"Invoice {order_number} — {business_name}",
    )

    # --- Styles ----------------------------------------------------------
    base = getSampleStyleSheet()

    s_title = ParagraphStyle(
        "BizName",
        parent=base["Title"],
        fontName="Times-Roman",
        fontSize=30,
        leading=34,
        textColor=_CHARCOAL,
        alignment=TA_LEFT,
        spaceAfter=2,
    )
    s_tag = ParagraphStyle(
        "InvoiceLabel",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=_TAUPE,
        spaceAfter=20,
    )
    s_body = ParagraphStyle(
        "Body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=_CHARCOAL,
    )
    s_label = ParagraphStyle(
        "Label",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=_TAUPE,
        spaceAfter=3,
    )
    s_thanks = ParagraphStyle(
        "Thanks",
        parent=base["Normal"],
        fontName="Times-Italic",
        fontSize=11,
        textColor=_TAUPE,
        alignment=TA_CENTER,
        spaceBefore=8,
    )

    story = []

    # --- Header ----------------------------------------------------------
    story.append(Paragraph(business_name, s_title))
    story.append(Paragraph("INVOICE · WRAPPED WITH GRATITUDE", s_tag))

    biz_lines = [x for x in (business_email, business_phone) if x]
    biz_text = "<br/>".join(biz_lines) or "&nbsp;"

    meta_text = (
        f"<b>Invoice #</b> &nbsp; {order_number}<br/>"
        f"<b>Date</b> &nbsp; {order_date.strftime('%B %d, %Y')}"
    )

    header_table = Table(
        [[Paragraph(biz_text, s_body), Paragraph(meta_text, s_body)]],
        colWidths=[3.5 * inch, 3.5 * inch],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.3 * inch))

    # --- Bill To ---------------------------------------------------------
    story.append(Paragraph("BILL TO", s_label))
    bill_lines = [customer_name]
    if customer_email:    bill_lines.append(customer_email)
    if customer_phone:    bill_lines.append(customer_phone)
    if shipping_address:
        # honor manual line breaks in the address
        for piece in shipping_address.splitlines():
            if piece.strip():
                bill_lines.append(piece.strip())
    story.append(Paragraph("<br/>".join(bill_lines), s_body))
    story.append(Spacer(1, 0.3 * inch))

    # --- Line items ------------------------------------------------------
    # Wrap descriptions in Paragraphs so long product names word-wrap to the
    # column width instead of overflowing into Qty / Price.
    s_cell_desc = ParagraphStyle(
        "CellDesc",
        parent=s_body,
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        spaceBefore=0,
        spaceAfter=0,
    )

    def _esc(s: str) -> str:
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    table_data = [["Description", "Qty", "Unit price", "Total"]]
    for line in lines:
        table_data.append([
            Paragraph(_esc(line["description"]), s_cell_desc),
            f"{float(line['qty']):,.0f}",
            f"${float(line['unit_price']):,.2f}",
            f"${float(line['line_total']):,.2f}",
        ])

    items_table = Table(
        table_data,
        colWidths=[4.0 * inch, 0.7 * inch, 1.15 * inch, 1.15 * inch],
        repeatRows=1,
    )
    items_table.setStyle(TableStyle([
        # Header
        ("BACKGROUND",  (0, 0), (-1, 0), _SOFT_BLUSH),
        ("TEXTCOLOR",   (0, 0), (-1, 0), _CHARCOAL),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING",    (0, 0), (-1, 0), 10),
        # Body
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 1), (-1, -1), 10),
        ("TEXTCOLOR",   (0, 1), (-1, -1), _CHARCOAL),
        ("ALIGN",       (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN",       (0, 0), (0, -1), "LEFT"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("TOPPADDING",    (0, 1), (-1, -1), 8),
        ("LINEBELOW",   (0, 0), (-1, -2), 0.5, colors.lightgrey),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 0.2 * inch))

    # --- Totals ----------------------------------------------------------
    totals_rows = [["", "Subtotal", f"${float(subtotal):,.2f}"]]
    if float(shipping) > 0:
        totals_rows.append(["", "Shipping", f"${float(shipping):,.2f}"])
    if float(tax) > 0:
        totals_rows.append(["", "Tax", f"${float(tax):,.2f}"])
    totals_rows.append(["", "Total", f"${float(total):,.2f}"])

    totals_table = Table(
        totals_rows,
        colWidths=[4.0 * inch, 1.85 * inch, 1.15 * inch],
    )
    totals_table.setStyle(TableStyle([
        ("ALIGN",       (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME",    (1, 0), (-1, -2), "Helvetica"),
        ("FONTNAME",    (1, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE",    (1, 0), (-1, -2), 10),
        ("FONTSIZE",    (1, -1), (-1, -1), 12),
        ("TEXTCOLOR",   (1, 0), (-1, -2), _TAUPE),
        ("TEXTCOLOR",   (1, -1), (-1, -1), _CHARCOAL),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE",   (1, -1), (-1, -1), 1, _CHARCOAL),
        ("TOPPADDING",  (1, -1), (-1, -1), 6),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 0.4 * inch))

    # --- Payment ---------------------------------------------------------
    story.append(Paragraph("PAYMENT", s_label))
    if business_venmo:
        handle = business_venmo if business_venmo.startswith("@") else f"@{business_venmo}"
        pay_html = (
            f"Please send payment via Venmo to <b>{handle}</b>.<br/>"
            f"Include invoice <b>{order_number}</b> in the note."
        )
    else:
        pay_html = "Payment instructions to follow."
    story.append(Paragraph(pay_html, s_body))

    if notes:
        story.append(Spacer(1, 0.3 * inch))
        story.append(Paragraph("NOTES", s_label))
        # Escape any stray HTML & preserve line breaks
        safe = (
            notes.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace("\n", "<br/>")
        )
        story.append(Paragraph(safe, s_body))

    # --- Footer ----------------------------------------------------------
    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph(
        "Thank you for your order — wrapped with gratitude.",
        s_thanks,
    ))

    doc.build(story)
    return buf.getvalue()
