"""Prorata allocation of shipping / tax / other charges across invoice lines.

Allocation is by line subtotal (qty * unit_price). The per-unit landed cost
is then (line_subtotal + allocated_shipping + allocated_tax + allocated_other) / qty.

All math is in Decimal to avoid floating-point drift on money. Rounding
happens at the end so allocations sum back to the invoice totals exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


# Quantization helpers
_MONEY = Decimal("0.01")           # 2 dp for stored money columns
_RATE  = Decimal("0.0001")         # 4 dp for unit prices / landed costs


def _r(value: Decimal, q: Decimal) -> Decimal:
    return value.quantize(q, rounding=ROUND_HALF_UP)


@dataclass
class LineInput:
    description: str
    qty: Decimal
    unit_price: Decimal


@dataclass
class AllocatedLine:
    description: str
    qty: Decimal
    unit_price: Decimal
    line_subtotal: Decimal
    allocated_shipping: Decimal
    allocated_tax: Decimal
    allocated_other: Decimal
    landed_unit_cost: Decimal


def allocate(
    lines: list[LineInput],
    shipping: Decimal,
    tax: Decimal,
    other_charges: Decimal = Decimal("0"),
) -> list[AllocatedLine]:
    """Allocate shipping/tax/other to lines pro-rata by line subtotal.

    Residual rounding pennies (from quantizing each share independently) are
    pushed onto the largest line so the allocated totals sum exactly to the
    invoice charges.
    """
    if not lines:
        return []

    subtotals = [(li.qty * li.unit_price) for li in lines]
    total_subtotal = sum(subtotals, Decimal("0"))

    if total_subtotal == 0:
        # Nothing to allocate against — landed cost equals unit price.
        return [
            AllocatedLine(
                description=li.description,
                qty=li.qty,
                unit_price=li.unit_price,
                line_subtotal=Decimal("0"),
                allocated_shipping=Decimal("0"),
                allocated_tax=Decimal("0"),
                allocated_other=Decimal("0"),
                landed_unit_cost=_r(li.unit_price, _RATE),
            )
            for li in lines
        ]

    raw_alloc = []
    for li, sub in zip(lines, subtotals):
        share = sub / total_subtotal
        raw_alloc.append({
            "shipping": shipping * share,
            "tax": tax * share,
            "other": other_charges * share,
        })

    # Distribute the pennies residual onto the line with the largest subtotal
    # so the allocated charges sum to the input charges exactly.
    largest_idx = max(range(len(subtotals)), key=lambda i: subtotals[i])

    for key, total in (("shipping", shipping), ("tax", tax), ("other", other_charges)):
        rounded = [_r(a[key], _MONEY) for a in raw_alloc]
        residual = total - sum(rounded, Decimal("0"))
        rounded[largest_idx] += residual
        for a, r in zip(raw_alloc, rounded):
            a[key] = r

    out: list[AllocatedLine] = []
    for li, sub, alloc in zip(lines, subtotals, raw_alloc):
        landed_total = sub + alloc["shipping"] + alloc["tax"] + alloc["other"]
        landed_unit = landed_total / li.qty
        out.append(
            AllocatedLine(
                description=li.description,
                qty=li.qty,
                unit_price=li.unit_price,
                line_subtotal=_r(sub, _MONEY),
                allocated_shipping=alloc["shipping"],
                allocated_tax=alloc["tax"],
                allocated_other=alloc["other"],
                landed_unit_cost=_r(landed_unit, _RATE),
            )
        )
    return out
