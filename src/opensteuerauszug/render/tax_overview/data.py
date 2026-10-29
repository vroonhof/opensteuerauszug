"""Aggregated, CHF-normalised data model consumed by the sheet writers.

Every figure in :class:`TaxOverviewData` is already in CHF (or carries the
source amount alongside) — the boundary conversions happen upstream in
phases 2–4. Sheet writers are therefore pure: they format and lay out, they
never compute. That keeps visual regressions isolated from numerical bugs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional

from .fifo import LotClose
from .orders import Order
from .waterfall import Waterfall


@dataclass(frozen=True)
class PositionSummary:
    """One row in the Wertschriften (closing holdings) sheet."""

    isin: Optional[str]
    symbol: str
    description: str
    quantity_closing: Decimal
    currency: str
    price_closing_local: Decimal
    price_closing_chf: Decimal  # ESTV Kursliste Steuerwert per share when available
    market_value_chf: Decimal
    # Canonical eCH-0196 classification ("A" | "B" | "DA1") from
    # core.security.determine_security_type — keeps the Verzeichnis's
    # Form A/B split consistent with the official statement rendering.
    security_type: str = "B"


@dataclass(frozen=True)
class IncomeEvent:
    """A dividend or interest payment, already CHF-converted for display.

    Keeping dividends and interest in the same shape (with a ``category``
    discriminator) avoids a parallel type hierarchy — they differ only in
    semantic label and in which sheet they land on.
    """

    payment_date: date
    isin: Optional[str]
    symbol: str
    description: str
    category: str  # "dividend" | "interest"
    gross_local: Decimal
    currency: str
    withholding_tax_local: Decimal
    net_local: Decimal
    gross_chf: Decimal
    withholding_tax_chf: Decimal
    net_chf: Decimal


@dataclass(frozen=True)
class FeeEvent:
    """A non-commission fee (platform, data, wire, etc.). Commissions live on Order."""

    fee_date: date
    kind: str  # "platform" | "data" | "wire" | "other"
    description: str
    amount_local: Decimal
    currency: str
    amount_chf: Decimal


@dataclass(frozen=True)
class FXRateUsed:
    """One FX rate the pipeline resolved from the Kursliste (for audit)."""

    currency: str
    reference_date: date
    rate: Decimal  # CHF per 1 unit of ``currency``
    source: str = "kursliste"


@dataclass(frozen=True)
class VerzeichnisLine:
    """One row of the SG Wertschriftenverzeichnis mapping sheet.

    Consolidates everything a taxpayer needs to copy into the canton's
    securities-register form: market value at year-end, full-year gross
    income, and the two withholding-tax flavours (CH Verrechnungssteuer vs.
    foreign Quellensteuer). ``form_field`` names the SG line — kept as a
    free-form string because the exact numbering shifts year to year.
    """

    form_field: str
    investment_type: str  # "Aktie" | "Obligation" | "Fonds" | "Sonstige"
    isin: Optional[str]
    description: str
    quantity: Decimal
    market_value_chf: Decimal
    income_gross_chf: Decimal
    verrechnungssteuer_chf: Decimal
    auslaendische_quellensteuer_chf: Decimal


@dataclass(frozen=True)
class KS36Criterion:
    """One ESTV Kreisschreiben 36 criterion evaluation.

    Lives on the hidden ``_KS36_Criteria`` sheet that only preparer-mode
    exports include. The 5 ESTV criteria for gewerbsmässiger Wertschriften-
    handel are:

    - ``holding_period``   — share of positions held < 6 months
    - ``volume_ratio``     — transaction volume / opening portfolio
    - ``gains_income_ratio`` — realized capital gains / net income
    - ``leverage``         — margin debt relative to portfolio value
    - ``derivatives``      — non-hedging derivatives activity

    ``status`` is the traffic-light judgment: "green" / "amber" / "red".
    ``triggered`` is true when observed crosses threshold (i.e. "red"
    territory). The preparer reads the holistic picture — this module
    never issues a final verdict itself.
    """

    code: str
    label: str
    observed_value: Decimal
    threshold: Decimal
    unit: str  # "percent" | "ratio" | "count" | "chf"
    triggered: bool
    status: str  # "green" | "amber" | "red"
    note: Optional[str] = None


@dataclass(frozen=True)
class KS36Evidence:
    """One supporting row for the hidden ``_KS36_Evidence`` sheet."""

    criterion_code: str
    category: str  # e.g. "short_held_close" | "margin_interest" | "option_trade"
    description: str
    value_chf: Decimal
    evidence_date: Optional[date] = None


@dataclass(frozen=True)
class PerformancePosition:
    """One row in the Performance tab: per-security total return.

    ``return_pct`` is the period P&L divided by opening value (or — when
    opening was zero because the position was opened intra-year — by
    net invested capital). ``contribution_chf`` is the signed CHF P&L that
    rolls up into the portfolio total.
    """

    isin: Optional[str]
    symbol: str
    description: str
    currency: str
    sector: str
    opening_value_chf: Decimal
    closing_value_chf: Decimal
    buys_chf: Decimal
    sells_chf: Decimal
    dividends_chf: Decimal
    unrealized_pnl_chf: Decimal
    realized_pnl_chf: Decimal
    total_pnl_chf: Decimal
    return_pct: Optional[Decimal]


@dataclass(frozen=True)
class SectorAllocation:
    """Sector or currency bucket for pie-chart rendering."""

    label: str
    market_value_chf: Decimal
    pnl_chf: Decimal
    weight_pct: Decimal


@dataclass(frozen=True)
class BenchmarkComparison:
    """One benchmark row for the performance tab (hardcoded annual return)."""

    code: str  # e.g. "SPI", "SMI", "SPX", "MSCI_ACWI"
    label: str  # display name
    return_pct: Decimal  # annual return in percent (e.g. 6.24)
    note: Optional[str] = None


@dataclass(frozen=True)
class PerformanceSummary:
    """Top-of-tab KPIs for the whole portfolio."""

    # Securities-only portfolio values (excludes cash). The performance
    # numerator is built from these so the result is well-defined even when
    # opening cash is unknown (default Flex queries report ``startingCash=0``).
    opening_value_chf: Decimal
    closing_value_chf: Decimal
    # Year-end cash position; informational only — never enters the return
    # math because we typically don't know the opening cash to pair against it.
    closing_cash_chf: Decimal
    cash_known: bool
    # External cash flows into/out of the brokerage account; reported beside
    # the totals so the reviewer can sanity-check the net-deposit identity.
    net_deposits_chf: Decimal
    deposits_gross_chf: Decimal
    withdrawals_chf: Decimal
    # Net flow between cash and securities (positive = bought net of sales).
    # Used as the external-flow term in Modified Dietz on the security portfolio.
    securities_net_flow_chf: Decimal
    total_pnl_chf: Decimal
    dividends_chf: Decimal
    interest_chf: Decimal
    fees_chf: Decimal
    # Modified Dietz: P&L / (opening + weighted deposits). Weight=0.5 assumes
    # deposits arrive mid-period; good enough at a dashboard level.
    money_weighted_return_pct: Optional[Decimal]
    # Simple return without flow adjustment, for cross-check.
    simple_return_pct: Optional[Decimal]


@dataclass(frozen=True)
class PerformanceSection:
    """Aggregate performance payload consumed by HTML / xlsx / PDF renderers."""

    summary: PerformanceSummary
    positions: List[PerformancePosition] = field(default_factory=list)
    sectors: List[SectorAllocation] = field(default_factory=list)
    currencies: List[SectorAllocation] = field(default_factory=list)
    benchmarks: List[BenchmarkComparison] = field(default_factory=list)


@dataclass(frozen=True)
class DA1Claim:
    """One DA-1 reclaim line for foreign withholding tax.

    ``withholding_rate`` and ``treaty_rate_ceiling`` are decimals (0.15, not
    15). ``recoverable_chf`` is what the pipeline has already decided is
    recoverable — typically equal to ``withholding_tax_chf`` when the actual
    rate is at or below the treaty ceiling, otherwise capped. The sheet
    writer does not recompute.
    """

    isin: Optional[str]
    symbol: str
    description: str
    source_country: str  # ISO 3166-1 alpha-2, e.g. "US"
    gross_chf: Decimal
    withholding_tax_chf: Decimal
    withholding_rate: Decimal
    treaty_rate_ceiling: Optional[Decimal]
    recoverable_chf: Decimal


@dataclass
class TaxOverviewData:
    """Everything the sheet writers need, already CHF-normalised."""

    tax_year: int
    broker: str
    preparer_mode: bool
    opening_value_chf: Decimal
    closing_value_chf: Decimal
    waterfall: Waterfall
    positions: List[PositionSummary] = field(default_factory=list)
    orders: List[Order] = field(default_factory=list)
    lot_closes: List[LotClose] = field(default_factory=list)
    dividends: List[IncomeEvent] = field(default_factory=list)
    interest: List[IncomeEvent] = field(default_factory=list)
    fees: List[FeeEvent] = field(default_factory=list)
    fx_rates: List[FXRateUsed] = field(default_factory=list)
    verzeichnis_lines: List[VerzeichnisLine] = field(default_factory=list)
    da1_claims: List[DA1Claim] = field(default_factory=list)
    ks36_criteria: List[KS36Criterion] = field(default_factory=list)
    ks36_evidence: List[KS36Evidence] = field(default_factory=list)
    performance: Optional[PerformanceSection] = None

    def total_dividends_chf(self) -> Decimal:
        return sum((d.gross_chf for d in self.dividends), Decimal(0))

    def total_interest_chf(self) -> Decimal:
        return sum((i.gross_chf for i in self.interest), Decimal(0))

    def total_withholding_tax_chf(self) -> Decimal:
        return sum(
            (evt.withholding_tax_chf for evt in (*self.dividends, *self.interest)),
            Decimal(0),
        )

    def total_fees_chf(self) -> Decimal:
        fee_sum = sum((f.amount_chf for f in self.fees), Decimal(0))
        commission_sum = sum((abs(o.total_commission) for o in self.orders), Decimal(0))
        return fee_sum + commission_sum

    def total_da1_recoverable_chf(self) -> Decimal:
        return sum((c.recoverable_chf for c in self.da1_claims), Decimal(0))
