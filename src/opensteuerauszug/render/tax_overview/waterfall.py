"""Vermögenszuwachs waterfall: bridges opening to closing portfolio value.

The dashboard should show the tax office *why* the portfolio value changed
during the year. This module builds the ledger of opening
value + inflows − outflows = closing value and reports the residual against
an authoritative closing (typically the eCH-0196 XML's reported total).

**Value basis.** Opening and closing *market* values should come from the
ESTV Kursliste ``Steuerwert`` (annual official tax values per ISIN) where
available, not broker mark-to-market: the Kursliste tax value is the value
the tax authority will use, so our waterfall must reconcile against that
same reference to avoid a spurious residual. Callers are responsible for
feeding Kursliste-derived figures in; this module is agnostic about the
source.

Reconciliation tolerance is ±CHF 1 per spec: the rounding noise from
per-transaction CHF conversion should not push the residual beyond that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Sequence

DEFAULT_RECONCILIATION_TOLERANCE_CHF = Decimal("1.00")


@dataclass(frozen=True)
class WaterfallLine:
    """One labelled component of the Vermögenszuwachs bridge."""

    label: str
    amount_chf: Decimal
    kind: str  # "opening" | "inflow" | "outflow" | "closing"

    def __post_init__(self) -> None:
        if self.kind not in {"opening", "inflow", "outflow", "closing"}:
            raise ValueError(f"unknown waterfall line kind: {self.kind!r}")


@dataclass
class Waterfall:
    """Opening value + inflows − outflows = closing value (with residual)."""

    opening: Decimal
    inflows: List[WaterfallLine] = field(default_factory=list)
    outflows: List[WaterfallLine] = field(default_factory=list)
    closing: Decimal = Decimal("0")

    @property
    def total_inflow(self) -> Decimal:
        return sum((line.amount_chf for line in self.inflows), Decimal(0))

    @property
    def total_outflow(self) -> Decimal:
        return sum((line.amount_chf for line in self.outflows), Decimal(0))

    @property
    def derived_closing(self) -> Decimal:
        """Closing value implied by opening + inflows − outflows."""
        return self.opening + self.total_inflow - self.total_outflow

    @property
    def residual(self) -> Decimal:
        """Difference between the authoritative closing and the derived one.

        Positive residual means the authoritative (eCH-0196) closing exceeds
        what our ledger can explain — i.e. we are missing an inflow or have
        overstated an outflow.
        """
        return self.closing - self.derived_closing

    def reconciles(self, tolerance: Decimal = DEFAULT_RECONCILIATION_TOLERANCE_CHF) -> bool:
        return abs(self.residual) <= tolerance

    def as_lines(self) -> List[WaterfallLine]:
        """Flatten opening + inflows + outflows + closing into a single list.

        Convenient for the workbook writer which emits one row per line.
        """
        lines: List[WaterfallLine] = [WaterfallLine("Opening value", self.opening, "opening")]
        lines.extend(self.inflows)
        lines.extend(self.outflows)
        lines.append(WaterfallLine("Closing value", self.closing, "closing"))
        return lines


def build_waterfall(
    opening: Decimal,
    closing: Decimal,
    *,
    inflows: Sequence[WaterfallLine] = (),
    outflows: Sequence[WaterfallLine] = (),
) -> Waterfall:
    """Construct a :class:`Waterfall`, validating each line's kind."""
    for line in inflows:
        if line.kind != "inflow":
            raise ValueError(f"inflow line {line.label!r} has kind {line.kind!r}")
    for line in outflows:
        if line.kind != "outflow":
            raise ValueError(f"outflow line {line.label!r} has kind {line.kind!r}")
    return Waterfall(
        opening=opening,
        inflows=list(inflows),
        outflows=list(outflows),
        closing=closing,
    )
