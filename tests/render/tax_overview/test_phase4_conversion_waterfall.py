"""Phase-4 tests: CHF conversion + Vermögenszuwachs waterfall reconciliation.

Covers the boundary at which foreign-currency figures become CHF (rounding,
audit-trail preservation, CHF short-circuit) and the bridge ledger that
reconciles opening-to-closing portfolio value.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

import pytest

from opensteuerauszug.core.exchange_rate_provider import ExchangeRateProvider
from opensteuerauszug.render.tax_overview.conversion import (
    CHF,
    MoneyCHF,
    sum_chf,
    to_chf,
)
from opensteuerauszug.render.tax_overview.waterfall import (
    DEFAULT_RECONCILIATION_TOLERANCE_CHF,
    Waterfall,
    WaterfallLine,
    build_waterfall,
)

# ---------------------------------------------------------------------------
# Test provider
# ---------------------------------------------------------------------------


class FixedRateProvider(ExchangeRateProvider):
    """Deterministic provider for isolating conversion math in unit tests."""

    def __init__(self, rates: dict[tuple[str, date], Decimal]) -> None:
        self.rates = rates
        self.calls: list[tuple[str, date]] = []

    def get_exchange_rate(
        self,
        currency: str,
        reference_date: date,
        path_prefix_for_log: Optional[str] = None,
    ) -> Decimal:
        self.calls.append((currency, reference_date))
        if currency == "CHF":
            return Decimal("1")
        return self.rates[(currency, reference_date)]


D = Decimal


# ---------------------------------------------------------------------------
# to_chf / MoneyCHF
# ---------------------------------------------------------------------------


def test_chf_input_short_circuits_and_does_not_call_provider() -> None:
    provider = FixedRateProvider({})
    result = to_chf(D("100.00"), CHF, date(2025, 6, 1), provider)
    assert result.amount == D("100.00")
    assert result.rate == D("1")
    assert result.source_currency == CHF
    assert provider.calls == []


def test_foreign_conversion_rounds_to_rappen_half_up() -> None:
    # 100 USD * 0.875 = 87.5 CHF → rounds to 87.50 (exact)
    provider = FixedRateProvider({("USD", date(2025, 3, 14)): D("0.875")})
    result = to_chf(D("100.00"), "USD", date(2025, 3, 14), provider)
    assert result.amount == D("87.50")
    # Half-up: 100 USD * 0.8755 = 87.55, stays at 87.55
    provider2 = FixedRateProvider({("USD", date(2025, 3, 14)): D("0.8755")})
    result2 = to_chf(D("100.00"), "USD", date(2025, 3, 14), provider2)
    assert result2.amount == D("87.55")
    # Tie-breaking: 10 USD * 0.875 = 8.75 → 8.75 (exact)
    # But 10 USD * 0.8755 = 8.755 → ROUND_HALF_UP gives 8.76
    provider3 = FixedRateProvider({("USD", date(2025, 3, 14)): D("0.8755")})
    result3 = to_chf(D("10.00"), "USD", date(2025, 3, 14), provider3)
    assert result3.amount == D("8.76")


def test_conversion_preserves_audit_trail() -> None:
    provider = FixedRateProvider({("EUR", date(2025, 6, 1)): D("0.95")})
    result = to_chf(D("1000.00"), "EUR", date(2025, 6, 1), provider)
    assert result.source_currency == "EUR"
    assert result.source_amount == D("1000.00")
    assert result.rate == D("0.95")
    assert result.reference_date == date(2025, 6, 1)


def test_sum_chf_totals_amounts_and_rounds() -> None:
    provider = FixedRateProvider(
        {
            ("USD", date(2025, 1, 1)): D("0.9"),
            ("EUR", date(2025, 1, 1)): D("0.95"),
        }
    )
    legs = [
        to_chf(D("100"), "USD", date(2025, 1, 1), provider),
        to_chf(D("100"), "EUR", date(2025, 1, 1), provider),
        to_chf(D("100"), "CHF", date(2025, 1, 1), provider),
    ]
    # 90.00 + 95.00 + 100.00 = 285.00
    assert sum_chf(legs) == D("285.00")


def test_moneychf_addition_marks_mixed_currency_when_sources_differ() -> None:
    a = MoneyCHF(D("10.00"), "USD", D("10"), D("1"), date(2025, 1, 1))
    b = MoneyCHF(D("5.00"), "EUR", D("5"), D("1"), date(2025, 1, 2))
    combined = a + b
    assert combined.amount == D("15.00")
    assert combined.source_currency == "MIXED"
    assert combined.reference_date == date(2025, 1, 2)


def test_moneychf_addition_preserves_currency_when_identical() -> None:
    a = MoneyCHF(D("10.00"), "USD", D("10"), D("0.9"), date(2025, 1, 1))
    b = MoneyCHF(D("5.00"), "USD", D("5"), D("0.9"), date(2025, 1, 2))
    combined = a + b
    assert combined.source_currency == "USD"
    assert combined.source_amount == D("15")


# ---------------------------------------------------------------------------
# Waterfall ledger math
# ---------------------------------------------------------------------------


def test_waterfall_derives_closing_from_opening_plus_inflows_minus_outflows() -> None:
    wf = build_waterfall(
        opening=D("100000"),
        closing=D("115000"),
        inflows=[
            WaterfallLine("Dividends", D("2500"), "inflow"),
            WaterfallLine("Interest", D("500"), "inflow"),
            WaterfallLine("Market gain", D("15000"), "inflow"),
        ],
        outflows=[
            WaterfallLine("Fees", D("1000"), "outflow"),
            WaterfallLine("Withholding tax", D("2000"), "outflow"),
        ],
    )
    # derived = 100000 + (2500 + 500 + 15000) - (1000 + 2000) = 115000
    assert wf.derived_closing == D("115000")
    assert wf.residual == D("0")
    assert wf.reconciles()


def test_waterfall_residual_within_tolerance_still_reconciles() -> None:
    # Classic rounding residual: derived is 114999.37, authoritative is 115000.00.
    wf = build_waterfall(
        opening=D("100000"),
        closing=D("115000.00"),
        inflows=[WaterfallLine("Net gain", D("14999.37"), "inflow")],
    )
    assert wf.derived_closing == D("114999.37")
    assert wf.residual == D("0.63")
    assert wf.reconciles()  # |0.63| <= 1.00


def test_waterfall_residual_beyond_tolerance_fails() -> None:
    wf = build_waterfall(
        opening=D("100000"),
        closing=D("115000"),
        inflows=[WaterfallLine("Net gain", D("14998.00"), "inflow")],
    )
    assert wf.residual == D("2")
    assert not wf.reconciles()


def test_waterfall_custom_tolerance_is_respected() -> None:
    wf = build_waterfall(
        opening=D("100000"),
        closing=D("100005"),
        inflows=[WaterfallLine("Dust", D("2"), "inflow")],
    )
    # default tolerance = 1 CHF, residual = 3 CHF → fails
    assert not wf.reconciles()
    # loosen to 5 CHF → passes
    assert wf.reconciles(tolerance=D("5"))


def test_waterfall_rejects_mismatched_line_kinds() -> None:
    bad_inflow = WaterfallLine("Wrong side", D("100"), "outflow")
    with pytest.raises(ValueError, match="has kind"):
        build_waterfall(opening=D("0"), closing=D("0"), inflows=[bad_inflow])


def test_waterfall_line_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown waterfall line kind"):
        WaterfallLine("X", D("0"), "misc")


def test_as_lines_emits_opening_inflows_outflows_closing_in_order() -> None:
    wf = build_waterfall(
        opening=D("100"),
        closing=D("120"),
        inflows=[WaterfallLine("In", D("30"), "inflow")],
        outflows=[WaterfallLine("Out", D("10"), "outflow")],
    )
    kinds = [line.kind for line in wf.as_lines()]
    assert kinds == ["opening", "inflow", "outflow", "closing"]


# ---------------------------------------------------------------------------
# End-to-end: reconcile against a synthetic eCH-0196-style closing total
# ---------------------------------------------------------------------------


def test_reconciliation_happy_path_against_simulated_ech0196_total() -> None:
    """Simulate what the pipeline will do in phase 5: use Kursliste-derived
    opening/closing values and per-transaction CHF-converted movements, then
    reconcile against the authoritative closing (as if read from the eCH-0196
    XML). Tolerance is the spec's ±CHF 1.
    """
    provider = FixedRateProvider(
        {
            ("USD", date(2025, 1, 1)): D("0.9100"),
            ("USD", date(2025, 3, 14)): D("0.8900"),
            ("USD", date(2025, 9, 21)): D("0.8700"),
            ("USD", date(2025, 12, 31)): D("0.9000"),
        }
    )

    opening = to_chf(D("100000"), "USD", date(2025, 1, 1), provider).amount
    closing_authoritative = to_chf(D("105000"), "USD", date(2025, 12, 31), provider).amount

    dividend = to_chf(D("1200"), "USD", date(2025, 3, 14), provider).amount
    realized = to_chf(D("3500"), "USD", date(2025, 9, 21), provider).amount
    fees = to_chf(D("200"), "USD", date(2025, 3, 14), provider).amount

    # Synthetic "market gain" plug so this test is closed-form: everything
    # not explained by the itemised lines must equal the plug, and the
    # residual must fall inside ±CHF 1.
    market_gain = closing_authoritative - opening - dividend - realized + fees

    wf = build_waterfall(
        opening=opening,
        closing=closing_authoritative,
        inflows=[
            WaterfallLine("Dividends", dividend, "inflow"),
            WaterfallLine("Realized gains", realized, "inflow"),
            WaterfallLine("Unrealized market gain", market_gain, "inflow"),
        ],
        outflows=[
            WaterfallLine("Fees", fees, "outflow"),
        ],
    )
    assert wf.reconciles(DEFAULT_RECONCILIATION_TOLERANCE_CHF)
    assert abs(wf.residual) <= DEFAULT_RECONCILIATION_TOLERANCE_CHF
