"""Tests for prior-period position verification."""

from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.model.ech0196 import (
    Depot,
    ListOfSecurities,
    Security,
    SecurityStock,
    SecurityTaxValue,
    TaxStatement,
)
from opensteuerauszug.core.prior_period_verifier import (
    MissingSecurity,
    PositionMismatch,
    PriorPeriodVerificationResult,
    verify_prior_period_positions,
    _get_ending_positions,
    _get_opening_positions,
    _security_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_security(
    position_id: int,
    name: str,
    isin: str = None,
    valor: int = None,
    tax_value_qty: Decimal = None,
    opening_stock_qty: Decimal = None,
    currency: str = "USD",
) -> Security:
    """Build a minimal Security for testing."""
    tax_value = None
    if tax_value_qty is not None:
        tax_value = SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=tax_value_qty,
            balanceCurrency=currency,
        )

    stocks = []
    if opening_stock_qty is not None:
        stocks.append(
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=opening_stock_qty,
                balanceCurrency=currency,
            )
        )

    return Security(
        positionId=position_id,
        country="US",
        currency=currency,
        quotationType="PIECE",
        securityCategory="SHARE",
        securityName=name,
        isin=isin,
        valorNumber=valor,
        taxValue=tax_value,
        stock=stocks,
    )


def _make_statement(securities: list, period_year: int = 2024) -> TaxStatement:
    """Wrap a list of securities into a TaxStatement."""
    depot = Depot(security=securities, depotNumber="D001")
    return TaxStatement(
        minorVersion=2,
        taxPeriod=period_year,
        periodFrom=date(period_year, 1, 1),
        periodTo=date(period_year, 12, 31),
        listOfSecurities=ListOfSecurities(depot=[depot]),
    )


# ---------------------------------------------------------------------------
# _security_key
# ---------------------------------------------------------------------------


class TestSecurityKey:
    def test_key_prefers_isin_over_valor(self):
        sec = _make_security(1, "TestCo", isin="US0378331005", valor=12345)
        assert _security_key(sec) == "isin:US0378331005"

    def test_key_falls_back_to_valor(self):
        sec = _make_security(1, "TestCo", valor=12345)
        assert _security_key(sec) == "valor:12345"

    def test_key_returns_none_when_no_identifiers(self):
        sec = _make_security(1, "TestCo")
        assert _security_key(sec) is None


# ---------------------------------------------------------------------------
# _get_ending_positions
# ---------------------------------------------------------------------------


class TestGetEndingPositions:
    def test_extracts_quantity_from_tax_value(self):
        sec = _make_security(1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("100"))
        stmt = _make_statement([sec])
        positions = _get_ending_positions(stmt)
        assert "isin:US0378331005" in positions
        qty, _, _ = positions["isin:US0378331005"]
        assert qty == Decimal("100")

    def test_skips_security_without_tax_value(self):
        sec = _make_security(1, "AAPL", isin="US0378331005")
        stmt = _make_statement([sec])
        positions = _get_ending_positions(stmt)
        assert len(positions) == 0

    def test_skips_security_without_identifiers(self):
        sec = _make_security(1, "Mystery")
        sec = _make_security(1, "Mystery", tax_value_qty=Decimal("50"))
        stmt = _make_statement([sec])
        positions = _get_ending_positions(stmt)
        assert len(positions) == 0

    def test_empty_list_of_securities(self):
        stmt = TaxStatement(minorVersion=2)
        positions = _get_ending_positions(stmt)
        assert len(positions) == 0

    def test_includes_zero_quantity_positions(self):
        sec = _make_security(1, "SOLD", isin="US1234567890", tax_value_qty=Decimal("0"))
        stmt = _make_statement([sec])
        positions = _get_ending_positions(stmt)
        assert "isin:US1234567890" in positions
        qty, _, _ = positions["isin:US1234567890"]
        assert qty == Decimal("0")


# ---------------------------------------------------------------------------
# _get_opening_positions
# ---------------------------------------------------------------------------


class TestGetOpeningPositions:
    def test_extracts_quantity_from_first_balance_stock(self):
        sec = _make_security(1, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("200"))
        stmt = _make_statement([sec], period_year=2025)
        positions = _get_opening_positions(stmt)
        assert "isin:US0378331005" in positions
        qty, _, _ = positions["isin:US0378331005"]
        assert qty == Decimal("200")

    def test_ignores_mutation_stock_entries(self):
        sec = _make_security(1, "AAPL", isin="US0378331005")
        # Add only a mutation stock entry
        sec.stock = [
            SecurityStock(
                referenceDate=date(2025, 1, 15),
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("10"),
                balanceCurrency="USD",
            )
        ]
        stmt = _make_statement([sec], period_year=2025)
        positions = _get_opening_positions(stmt)
        assert len(positions) == 0

    def test_picks_earliest_balance(self):
        sec = _make_security(1, "AAPL", isin="US0378331005")
        sec.stock = [
            SecurityStock(
                referenceDate=date(2025, 6, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("999"),
                balanceCurrency="USD",
            ),
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("100"),
                balanceCurrency="USD",
            ),
        ]
        stmt = _make_statement([sec], period_year=2025)
        positions = _get_opening_positions(stmt)
        qty, _, _ = positions["isin:US0378331005"]
        assert qty == Decimal("100")


# ---------------------------------------------------------------------------
# verify_prior_period_positions
# ---------------------------------------------------------------------------


class TestVerifyPriorPeriodPositions:
    def test_matching_positions_reports_no_errors(self):
        prior_sec = _make_security(
            1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("500")
        )
        current_sec = _make_security(
            1, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("500")
        )

        prior = _make_statement([prior_sec], period_year=2024)
        current = _make_statement([current_sec], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok
        assert result.matched_count == 1
        assert result.error_count == 0

    def test_quantity_mismatch_is_detected(self):
        prior_sec = _make_security(
            1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("500")
        )
        current_sec = _make_security(
            1, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("400")
        )

        prior = _make_statement([prior_sec], period_year=2024)
        current = _make_statement([current_sec], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert not result.is_ok
        assert len(result.mismatches) == 1
        assert result.mismatches[0].prior_quantity == Decimal("500")
        assert result.mismatches[0].current_quantity == Decimal("400")
        assert result.mismatches[0].difference == Decimal("-100")

    def test_security_in_prior_only_with_nonzero_qty_is_flagged(self):
        prior_sec = _make_security(
            1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("100")
        )
        prior = _make_statement([prior_sec], period_year=2024)
        current = _make_statement([], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert not result.is_ok
        assert len(result.missing_in_current) == 1
        assert result.missing_in_current[0].isin == "US0378331005"

    def test_security_in_prior_only_with_zero_qty_is_ok(self):
        prior_sec = _make_security(
            1, "SOLD", isin="US1234567890", tax_value_qty=Decimal("0")
        )
        prior = _make_statement([prior_sec], period_year=2024)
        current = _make_statement([], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok
        assert result.matched_count == 1

    def test_security_in_current_only_with_nonzero_qty_is_flagged(self):
        current_sec = _make_security(
            1, "NEW", isin="US9999999999", opening_stock_qty=Decimal("50")
        )
        prior = _make_statement([], period_year=2024)
        current = _make_statement([current_sec], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert not result.is_ok
        assert len(result.missing_in_prior) == 1

    def test_security_in_current_only_with_zero_qty_is_ok(self):
        current_sec = _make_security(
            1, "NEW_ZERO", isin="US9999999999", opening_stock_qty=Decimal("0")
        )
        prior = _make_statement([], period_year=2024)
        current = _make_statement([current_sec], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok

    def test_multiple_securities_mixed_results(self):
        """Test with multiple securities: one match, one mismatch, one missing."""
        prior_secs = [
            _make_security(1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("100")),
            _make_security(2, "MSFT", isin="US5949181045", tax_value_qty=Decimal("200")),
            _make_security(3, "GOOG", isin="US0231351067", tax_value_qty=Decimal("50")),
        ]
        current_secs = [
            _make_security(1, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("100")),
            _make_security(2, "MSFT", isin="US5949181045", opening_stock_qty=Decimal("180")),
            # GOOG not present in current (sold)
        ]

        prior = _make_statement(prior_secs, period_year=2024)
        current = _make_statement(current_secs, period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert not result.is_ok
        assert result.matched_count == 1  # AAPL matches
        assert len(result.mismatches) == 1  # MSFT mismatch
        assert len(result.missing_in_current) == 1  # GOOG missing

    def test_matching_by_valor_number(self):
        prior_sec = _make_security(
            1, "Roche", valor=1203204, tax_value_qty=Decimal("300")
        )
        current_sec = _make_security(
            1, "Roche", valor=1203204, opening_stock_qty=Decimal("300")
        )

        prior = _make_statement([prior_sec], period_year=2024)
        current = _make_statement([current_sec], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok
        assert result.matched_count == 1

    def test_empty_statements_is_ok(self):
        prior = _make_statement([], period_year=2024)
        current = _make_statement([], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok
        assert result.matched_count == 0

    def test_no_list_of_securities_is_ok(self):
        prior = TaxStatement(minorVersion=2)
        current = TaxStatement(minorVersion=2)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok


# ---------------------------------------------------------------------------
# Result dataclass helpers
# ---------------------------------------------------------------------------


class TestPositionMismatchStr:
    def test_str_with_isin(self):
        m = PositionMismatch(
            security_name="Apple",
            isin="US0378331005",
            valor=None,
            prior_quantity=Decimal("100"),
            current_quantity=Decimal("90"),
            depot="D001",
        )
        text = str(m)
        assert "US0378331005" in text
        assert "depot=D001" in text
        assert "difference=-10" in text

    def test_str_without_isin_uses_valor(self):
        m = PositionMismatch(
            security_name="Roche",
            isin=None,
            valor=1203204,
            prior_quantity=Decimal("100"),
            current_quantity=Decimal("100"),
        )
        text = str(m)
        assert "valor=1203204" in text

    def test_str_without_identifiers_uses_name(self):
        m = PositionMismatch(
            security_name="Mystery Corp",
            isin=None,
            valor=None,
            prior_quantity=Decimal("10"),
            current_quantity=Decimal("20"),
        )
        text = str(m)
        assert "Mystery Corp" in text


class TestPriorPeriodVerificationResult:
    def test_is_ok_when_empty(self):
        result = PriorPeriodVerificationResult()
        assert result.is_ok

    def test_is_not_ok_with_mismatches(self):
        result = PriorPeriodVerificationResult(
            mismatches=[
                PositionMismatch("X", None, None, Decimal(1), Decimal(2))
            ]
        )
        assert not result.is_ok

    def test_error_count(self):
        result = PriorPeriodVerificationResult(
            mismatches=[
                PositionMismatch("A", None, None, Decimal(1), Decimal(2))
            ],
            missing_in_current=[MissingSecurity("B", None, None, Decimal(3))],
            missing_in_prior=[MissingSecurity("C", None, None, Decimal(4))],
        )
        assert result.error_count == 3
