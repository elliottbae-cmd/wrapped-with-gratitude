"""New Sale page — basket builder → markup → customer PDF invoice."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from config import load
from services import customers as customers_svc
from services import sales as sales_svc
from services.customer_invoice_pdf import generate_invoice_pdf
from services.inventory import list_inventory_summary
from ui.auth import get_client, is_admin, require_auth, sidebar_user_info


cfg = load()
st.set_page_config(page_title="New Sale", page_icon="🛒", layout="wide")
require_auth()
sidebar_user_info()

st.title("🛒 New Sale")
st.caption(
    "Build a basket from inventory, choose a markup, and generate a "
    "Venmo-ready PDF invoice for your customer."
)

client = get_client()
admin = is_admin()


# ---- Session state init ----------------------------------------------
if "basket" not in st.session_state:
    st.session_state.basket = []   # product lines: {item_id, name, sku, category, on_hand, qty}
if "service_basket" not in st.session_state:
    st.session_state.service_basket = []   # service lines: {description, qty, unit_price}
if "basket_customer_id" not in st.session_state:
    st.session_state.basket_customer_id = None
if "last_sale_result" not in st.session_state:
    st.session_state.last_sale_result = None


@st.cache_data(ttl=30, show_spinner=False)
def _inventory(_client, cache_key: str):
    return list_inventory_summary(_client)


@st.cache_data(ttl=30, show_spinner=False)
def _customers(_client, cache_key: str):
    return customers_svc.list_customers(_client)


cache_key = st.session_state["access_token"]

# ====================================================================
# 1. Customer
# ====================================================================
st.subheader("1. Customer")

all_customers = _customers(client, cache_key)
options = ["— Select a customer —"] + [c["name"] for c in all_customers]
current_idx = 0
if st.session_state.basket_customer_id:
    for i, c in enumerate(all_customers):
        if c["id"] == st.session_state.basket_customer_id:
            current_idx = i + 1
            break

picked = st.selectbox(
    "Pick existing customer",
    options=options,
    index=current_idx,
    label_visibility="collapsed",
)

if picked != "— Select a customer —":
    customer_row = next(c for c in all_customers if c["name"] == picked)
    st.session_state.basket_customer_id = customer_row["id"]
    bits = []
    if customer_row.get("email"): bits.append(customer_row["email"])
    if customer_row.get("phone"): bits.append(customer_row["phone"])
    if customer_row.get("shipping_address"):
        bits.append(customer_row["shipping_address"].replace("\n", ", "))
    st.caption(" · ".join(bits) if bits else "No contact details on file.")
else:
    st.session_state.basket_customer_id = None

with st.expander("➕ Or add a new customer"):
    with st.form("inline_new_customer", clear_on_submit=True):
        a, b = st.columns(2)
        with a:
            nn_name = st.text_input("Name *")
            nn_email = st.text_input("Email")
            nn_phone = st.text_input("Phone")
        with b:
            nn_ig = st.text_input("Instagram handle (no @)")
            nn_ship = st.text_area("Shipping address", height=80)
        if st.form_submit_button("Create and select", type="primary"):
            if not nn_name.strip():
                st.error("Name required.")
            else:
                cid = customers_svc.find_or_create_customer(
                    client,
                    name=nn_name, email=nn_email, phone=nn_phone,
                    instagram_handle=nn_ig, shipping_address=nn_ship,
                )
                st.session_state.basket_customer_id = cid
                _customers.clear()
                st.success(f"Added {nn_name}. They're now selected.")
                st.rerun()

# Sale date — defaults to today; can backdate when entering past sales
dc1, _ = st.columns([1, 3])
with dc1:
    order_date = st.date_input(
        "Sale date",
        value=date.today(),
        help=(
            "Date the sale actually happened. Affects which year the order "
            "number is sequenced under (e.g., WG-2026-001 vs WG-2025-001) "
            "and which period it lands in for P&L reporting."
        ),
        key="sale_order_date",
    )

st.divider()

# ====================================================================
# 2. Items
# ====================================================================
st.subheader("2. Items")

inventory = _inventory(client, cache_key)
in_stock = [i for i in inventory if i["on_hand"] > 0]
in_stock_by_id = {i["id"]: i for i in in_stock}

if not in_stock:
    st.warning("Nothing in stock. Upload an invoice first.")
    st.page_link("pages/1_Upload_Invoice.py", label="📥 Upload an invoice", icon=None)
    st.stop()

# --- Add items: search + category filter + clickable list ---
in_basket_ids = {b["item_id"] for b in st.session_state.basket}
candidates_all = [i for i in in_stock if i["id"] not in in_basket_ids]

if not candidates_all:
    st.caption(
        "Every in-stock item is already in the basket — edit qty below or remove a line."
    )
else:
    with st.container(border=True):
        st.markdown("**Add items**")
        sc1, sc2 = st.columns([3, 1])
        with sc1:
            search = st.text_input(
                "Search items",
                placeholder="Search by name, SKU, or category…",
                label_visibility="collapsed",
                key="basket_search",
            )
        with sc2:
            cats = sorted({
                c.get("category", "") for c in candidates_all if c.get("category")
            })
            cat_options = ["All categories"] + cats
            cat_filter = st.selectbox(
                "Filter by category",
                options=cat_options,
                label_visibility="collapsed",
                key="basket_cat_filter",
            )

        candidates = candidates_all
        if search:
            s = search.lower().strip()
            candidates = [
                c for c in candidates
                if s in c["name"].lower()
                or s in (c.get("sku") or "").lower()
                or s in (c.get("category") or "").lower()
            ]
        if cat_filter != "All categories":
            candidates = [c for c in candidates if c.get("category") == cat_filter]

        if not candidates:
            st.caption("No items match the current filters.")
        else:
            shown_limit = 15
            shown = candidates[:shown_limit]

            for item in shown:
                with st.container():
                    cols = st.columns([4, 1.2, 1])
                    with cols[0]:
                        st.markdown(f"**{item['name']}**")
                        bits = []
                        if item.get("category"):
                            bits.append(item["category"])
                        if item.get("sku"):
                            bits.append(f"SKU: {item['sku']}")
                        bits.append(f"{item['on_hand']:.0f} on hand")
                        st.caption(" · ".join(bits))
                    with cols[1]:
                        qty = st.number_input(
                            "Qty",
                            min_value=1.0,
                            max_value=float(item["on_hand"]),
                            value=1.0,
                            step=1.0,
                            key=f"add_qty_{item['id']}",
                            label_visibility="collapsed",
                        )
                    with cols[2]:
                        if st.button(
                            "Add",
                            key=f"add_btn_{item['id']}",
                            type="primary",
                            use_container_width=True,
                        ):
                            st.session_state.basket.append({
                                "item_id": item["id"],
                                "name": item["name"],
                                "sku": item.get("sku") or "",
                                "category": item.get("category") or "",
                                "on_hand": float(item["on_hand"]),
                                "qty": float(qty),
                            })
                            st.rerun()

            if len(candidates) > shown_limit:
                st.caption(
                    f"Showing {shown_limit} of {len(candidates)} matches — "
                    f"refine your search or pick a category to narrow."
                )
            else:
                st.caption(f"{len(candidates)} item(s).")

# ---- Add a service (labor / embroidery / monogram) -------------------
st.markdown("&nbsp;")
with st.container(border=True):
    st.markdown("**Add a service**")
    st.caption("Labor lines like embroidery, monogramming, custom design. Not inventory-tracked.")
    with st.form("add_service", clear_on_submit=True):
        ss1, ss2, ss3, ss4 = st.columns([3, 1, 1, 1])
        with ss1:
            svc_desc = st.text_input(
                "Description",
                placeholder="e.g., Custom embroidery",
                label_visibility="collapsed",
            )
        with ss2:
            svc_qty = st.number_input(
                "Qty",
                min_value=1.0,
                value=1.0,
                step=1.0,
                label_visibility="collapsed",
            )
        with ss3:
            svc_price = st.number_input(
                "Unit price ($)",
                min_value=0.0,
                value=0.0,
                step=1.0,
                format="%.2f",
                label_visibility="collapsed",
            )
        with ss4:
            svc_add = st.form_submit_button("Add", type="primary", use_container_width=True)

        if svc_add:
            if not svc_desc.strip():
                st.error("Description required.")
            elif svc_price <= 0:
                st.error("Unit price must be greater than 0.")
            else:
                st.session_state.service_basket.append({
                    "description": svc_desc.strip(),
                    "qty": float(svc_qty),
                    "unit_price": float(svc_price),
                })
                st.rerun()

# --- Basket rows ---
if not st.session_state.basket and not st.session_state.service_basket:
    st.info("Basket is empty. Add an item or service above.")
    st.stop()

st.markdown("**Basket**")
remove_prod_idx = None
remove_svc_idx = None

# Product lines
for i, item in enumerate(st.session_state.basket):
    # Refresh on_hand in case inventory changed between reruns
    fresh = in_stock_by_id.get(item["item_id"])
    if fresh:
        item["on_hand"] = float(fresh["on_hand"])

    cols = st.columns([5, 1.4, 1.4, 1])
    with cols[0]:
        st.markdown(f"**{item['name']}**")
        sub_bits = ["📦 Product"]
        if item["sku"]:      sub_bits.append(f"SKU: {item['sku']}")
        if item["category"]: sub_bits.append(item["category"])
        sub_bits.append(f"{item['on_hand']:.0f} on hand")
        st.caption(" · ".join(sub_bits))
    with cols[1]:
        new_q = st.number_input(
            "Qty",
            min_value=1.0,
            max_value=max(1.0, item["on_hand"]),
            value=min(float(item["qty"]), float(item["on_hand"])),
            step=1.0,
            key=f"basket_qty_{i}_{item['item_id']}",
            label_visibility="collapsed",
        )
        item["qty"] = float(new_q)
    with cols[2]:
        if item["qty"] > item["on_hand"]:
            st.markdown(":red[Over stock]")
        else:
            st.caption("✓")
    with cols[3]:
        if st.button("Remove", key=f"basket_rm_{i}_{item['item_id']}", use_container_width=True):
            remove_prod_idx = i

# Service lines
for i, svc in enumerate(st.session_state.service_basket):
    cols = st.columns([3, 1.4, 1.4, 1.4, 1])
    with cols[0]:
        st.markdown(f"**{svc['description']}**")
        st.caption("🛠 Service (no inventory)")
    with cols[1]:
        new_q = st.number_input(
            "Qty",
            min_value=1.0,
            value=float(svc["qty"]),
            step=1.0,
            key=f"svc_qty_{i}_{svc['description'][:20]}",
            label_visibility="collapsed",
        )
        svc["qty"] = float(new_q)
    with cols[2]:
        new_p = st.number_input(
            "Unit price",
            min_value=0.0,
            value=float(svc["unit_price"]),
            step=1.0,
            format="%.2f",
            key=f"svc_price_{i}_{svc['description'][:20]}",
            label_visibility="collapsed",
        )
        svc["unit_price"] = float(new_p)
    with cols[3]:
        line_total = svc["qty"] * svc["unit_price"]
        st.caption(f"= **${line_total:,.2f}**")
    with cols[4]:
        if st.button("Remove", key=f"svc_rm_{i}_{svc['description'][:20]}", use_container_width=True):
            remove_svc_idx = i

if remove_prod_idx is not None:
    st.session_state.basket.pop(remove_prod_idx)
    st.rerun()
if remove_svc_idx is not None:
    st.session_state.service_basket.pop(remove_svc_idx)
    st.rerun()

# Pull FIFO cost for product lines; build service lines without FIFO.
try:
    product_basket_lines = [
        sales_svc.BasketLine(
            inventory_item_id=b["item_id"],
            description=b["name"],
            qty=Decimal(str(b["qty"])),
        )
        for b in st.session_state.basket
    ]
    costed_products = sales_svc.cost_basket(client, product_basket_lines) if product_basket_lines else []
except sales_svc.InsufficientInventory as e:
    st.error(f"Not enough inventory for {e.description or e.item_id}: need {e.needed}, only {e.available} available.")
    st.stop()
except Exception as e:
    st.error(f"Could not cost the basket: {e}")
    st.stop()

costed_services = [
    sales_svc.as_service_line(s["description"], Decimal(str(s["qty"])))
    for s in st.session_state.service_basket
]

# Unified list — order: products then services (matches how they're displayed)
costed = costed_products + costed_services
total_cogs = sum((c.total_cogs for c in costed), Decimal("0"))

st.divider()

# ====================================================================
# 3. Pricing
# ====================================================================
st.subheader("3. Pricing")
pc1, pc2, pc3 = st.columns(3)
with pc1:
    markup_pct = st.number_input(
        "Markup %",
        min_value=0.0, max_value=1000.0, value=100.0, step=5.0,
        help="100% means double the cost. 50% means 1.5× cost.",
    )
with pc2:
    shipping = st.number_input("Shipping charge ($)", min_value=0.0, value=0.0, step=0.50, format="%.2f")
with pc3:
    tax = st.number_input("Sales tax ($)", min_value=0.0, value=0.0, step=0.50, format="%.2f")

notes = st.text_area(
    "Notes for the customer (optional)",
    placeholder="Anything that should appear on the customer's invoice",
    height=70,
)

markup_dec = Decimal(str(markup_pct)) / Decimal("100")
ship_dec = Decimal(str(shipping))
tax_dec = Decimal(str(tax))

# Per-line sale prices:
#   - product lines: cost-per-unit × (1 + markup %)
#   - service lines: the customer-entered unit price (no markup applied)
line_unit_prices: list[Decimal] = []
for c in costed_products:
    cost_per_unit = c.total_cogs / c.qty if c.qty > 0 else Decimal("0")
    sale_per_unit = (cost_per_unit * (Decimal("1") + markup_dec)).quantize(Decimal("0.01"))
    line_unit_prices.append(sale_per_unit)
for s in st.session_state.service_basket:
    line_unit_prices.append(Decimal(str(s["unit_price"])).quantize(Decimal("0.01")))

subtotal_price = sum(
    (line_unit_prices[i] * c.qty for i, c in enumerate(costed)),
    Decimal("0"),
).quantize(Decimal("0.01"))
total = (subtotal_price + ship_dec + tax_dec).quantize(Decimal("0.01"))
profit = subtotal_price - total_cogs
margin_pct = (profit / subtotal_price * 100) if subtotal_price > 0 else Decimal("0")

st.divider()

# ====================================================================
# 4. Review
# ====================================================================
st.subheader("4. Review")

mt1, mt2, mt3, mt4 = st.columns(4)
mt1.metric("Items", len(costed))
mt2.metric("Total cost basis", f"${float(total_cogs):,.2f}")
mt3.metric("Customer subtotal", f"${float(subtotal_price):,.2f}")
mt4.metric("Customer total", f"${float(total):,.2f}")

if admin:
    am1, am2 = st.columns(2)
    am1.metric("Gross profit", f"${float(profit):,.2f}")
    am2.metric("Gross margin", f"{float(margin_pct):.1f}%")

breakdown_rows = []
for i, c in enumerate(costed):
    cost_per_unit = (c.total_cogs / c.qty) if c.qty > 0 else Decimal("0")
    sale_per_unit = line_unit_prices[i]
    breakdown_rows.append({
        "Item":          c.description,
        "Qty":           float(c.qty),
        "Cost / unit":   float(cost_per_unit),
        "Sale / unit":   float(sale_per_unit),
        "Line total":    float(sale_per_unit * c.qty),
    })
breakdown_rows.append({
    "Item":        "Subtotal",
    "Qty":         float(sum((c.qty for c in costed), Decimal("0"))),
    "Cost / unit": None,
    "Sale / unit": None,
    "Line total":  float(subtotal_price),
})

breakdown_df = pd.DataFrame(breakdown_rows)
breakdown_cfg = {
    "Item":        st.column_config.TextColumn("Item", width="large"),
    "Qty":         st.column_config.NumberColumn("Qty", format="%.0f"),
    "Cost / unit": st.column_config.NumberColumn("Cost / unit", format="$%.2f"),
    "Sale / unit": st.column_config.NumberColumn("Sale / unit", format="$%.2f"),
    "Line total":  st.column_config.NumberColumn("Line total", format="$%.2f"),
}
if not admin:
    # Hide cost columns from staff
    breakdown_df = breakdown_df.drop(columns=["Cost / unit"])
    breakdown_cfg.pop("Cost / unit", None)
st.dataframe(breakdown_df, column_config=breakdown_cfg, use_container_width=True, hide_index=True)

st.caption(
    f"Subtotal **${float(subtotal_price):,.2f}** · "
    f"+ Shipping ${shipping:,.2f} · + Tax ${tax:,.2f} · "
    f"= **Total ${float(total):,.2f}**"
)

st.divider()

# ====================================================================
# 5. Commit
# ====================================================================
st.subheader("5. Generate invoice & post sale")

blockers: list[str] = []
if not st.session_state.basket_customer_id:
    blockers.append("Pick or add a customer above.")
if not costed:
    blockers.append("Add at least one item to the basket.")
if cfg.business_venmo_handle == "":
    blockers.append("Set BUSINESS_VENMO_HANDLE in your config — the invoice can't show payment instructions without it.")

for b in blockers:
    st.error(b)

commit_clicked = st.button(
    "Generate invoice & post sale",
    type="primary",
    use_container_width=True,
    disabled=bool(blockers),
)

if commit_clicked:
    with st.spinner("Posting sale, decrementing lots, generating PDF…"):
        try:
            result = sales_svc.commit_sale(
                client,
                customer_id=st.session_state.basket_customer_id,
                costed_lines=costed,
                line_unit_prices=line_unit_prices,
                markup_pct=markup_dec,
                shipping_charge=ship_dec,
                sales_tax=tax_dec,
                order_date=order_date,
                notes=notes or None,
            )
        except Exception as e:
            st.error(f"Commit failed: {e}")
            st.stop()

        # Generate PDF
        customer = customers_svc.get_customer(client, st.session_state.basket_customer_id) or {}
        pdf_lines = [
            {
                "description": c.description,
                "qty":         c.qty,
                "unit_price":  line_unit_prices[i],
                "line_total":  line_unit_prices[i] * c.qty,
            }
            for i, c in enumerate(costed)
        ]
        try:
            pdf_bytes = generate_invoice_pdf(
                business_name=cfg.business_name,
                business_email=cfg.business_email,
                business_phone=cfg.business_phone,
                business_venmo=cfg.business_venmo_handle,
                order_number=result["order_number"],
                order_date=order_date,
                customer_name=customer.get("name", "Customer"),
                customer_email=customer.get("email"),
                customer_phone=customer.get("phone"),
                shipping_address=customer.get("shipping_address"),
                lines=pdf_lines,
                subtotal=result["subtotal_price"],
                shipping=ship_dec,
                tax=tax_dec,
                total=result["total"],
                notes=notes or None,
            )
        except Exception as e:
            st.error(f"PDF generation failed: {e}")
            pdf_bytes = None

        # Upload PDF
        pdf_path = None
        if pdf_bytes:
            try:
                pdf_path = sales_svc.upload_customer_invoice_pdf(
                    client, pdf_bytes, result["order_number"]
                )
                sales_svc.attach_pdf_path(client, result["order_id"], pdf_path)
            except Exception as e:
                st.warning(f"PDF storage upload failed ({e}); proceeding without archived copy.")

    # Post-commit summary
    st.success(f"✅ Sale posted as **{result['order_number']}**")
    st.balloons()

    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("Order #", result["order_number"])
    sc2.metric("Customer total", f"${float(result['total']):,.2f}")
    sc3.metric("COGS (booked)", f"${float(result['subtotal_cogs']):,.2f}")

    if pdf_bytes:
        st.download_button(
            "📄 Download invoice PDF",
            data=pdf_bytes,
            file_name=f"{result['order_number']}.pdf",
            mime="application/pdf",
            type="primary",
        )

    st.page_link("pages/4_Sales.py", label="View all sales →")

    # Clear basket + services for the next sale
    st.session_state.basket = []
    st.session_state.service_basket = []
    st.session_state.basket_customer_id = None
    st.session_state.last_sale_result = result
    _inventory.clear()
    _customers.clear()
