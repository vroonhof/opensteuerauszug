"""Tests for prior-period position verification."""

from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.model.ech0196 import (
    Depot,
    DepotNumber,
    ISINType,
    ListOfSecurities,
    Security,
    SecurityStock,
    SecurityTaxValue,
    TaxStatement,
    ValorNumber,
)
from opensteuerauszug.core.prior_period_verifier import (
    MissingSecurity,
    PositionKey,
    PositionMismatch,
    PriorPeriodVerificationResult,
    PriorPeriodXmlLoadError,
    SecurityId,
    load_prior_period_statement,
    verify_prior_period_positions,
    _get_ending_positions,
    _get_opening_positions,
    _position_key,
    _security_identifier,
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
        isin=ISINType(isin) if isin else None,
        valorNumber=ValorNumber(valor) if valor else None,
        taxValue=tax_value,
        stock=stocks,
    )


def _make_statement(
    depots: list = None,
    securities: list = None,
    period_year: int = 2024,
    depot_number: str = "D001",
) -> TaxStatement:
    """Wrap securities into a TaxStatement.

    Either pass a list of pre-built ``Depot`` objects via *depots*, or a flat
    list of securities which will be placed in a single depot.
    """
    if depots is None:
        secs = securities if securities is not None else []
        depots = [Depot(security=secs, depotNumber=DepotNumber(depot_number))]
    return TaxStatement(
        minorVersion=2,
        taxPeriod=period_year,
        periodFrom=date(period_year, 1, 1),
        periodTo=date(period_year, 12, 31),
        listOfSecurities=ListOfSecurities(depot=depots),
    )


# ---------------------------------------------------------------------------
# _security_identifier  /  _position_key
# ---------------------------------------------------------------------------


class TestSecurityIdentifier:
    def test_prefers_isin_over_valor(self):
        sec = _make_security(1, "TestCo", isin="US0378331005", valor=12345)
        assert _security_identifier(sec) == ("isin", "US0378331005")

    def test_falls_back_to_valor(self):
        sec = _make_security(1, "TestCo", valor=12345)
        assert _security_identifier(sec) == ("valor", 12345)

    def test_returns_none_when_no_identifiers(self):
        sec = _make_security(1, "TestCo")
        assert _security_identifier(sec) is None


class TestPositionKey:
    def test_includes_depot_and_isin(self):
        sec = _make_security(1, "X", isin="US0378331005")
        assert _position_key("D001", sec) == ("D001", ("isin", "US0378331005"))

    def test_includes_depot_and_valor(self):
        sec = _make_security(1, "X", valor=12345)
        assert _position_key("D002", sec) == ("D002", ("valor", 12345))

    def test_none_depot(self):
        sec = _make_security(1, "X", isin="US0378331005")
        assert _position_key(None, sec) == (None, ("isin", "US0378331005"))

    def test_returns_none_when_no_security_id(self):
        sec = _make_security(1, "X")
        assert _position_key("D001", sec) is None


# ---------------------------------------------------------------------------
# _get_ending_positions
# ---------------------------------------------------------------------------


class TestGetEndingPositions:
    def test_extracts_quantity_from_tax_value(self):
        sec = _make_security(1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("100"))
        stmt = _make_statement(securities=[sec])
        positions = _get_ending_positions(stmt)
        key = ("D001", ("isin", "US0378331005"))
        assert key in positions
        qty, _, _ = positions[key]
        assert qty == Decimal("100")

    def test_skips_security_without_tax_value(self):
        sec = _make_security(1, "AAPL", isin="US0378331005")
        stmt = _make_statement(securities=[sec])
        positions = _get_ending_positions(stmt)
        assert len(positions) == 0

    def test_skips_security_without_identifiers(self):
        sec = _make_security(1, "Mystery", tax_value_qty=Decimal("50"))
        stmt = _make_statement(securities=[sec])
        positions = _get_ending_positions(stmt)
        assert len(positions) == 0

    def test_empty_list_of_securities(self):
        stmt = TaxStatement(minorVersion=2)
        positions = _get_ending_positions(stmt)
        assert len(positions) == 0

    def test_includes_zero_quantity_positions(self):
        sec = _make_security(1, "SOLD", isin="US1234567890", tax_value_qty=Decimal("0"))
        stmt = _make_statement(securities=[sec])
        positions = _get_ending_positions(stmt)
        key = ("D001", ("isin", "US1234567890"))
        assert key in positions
        qty, _, _ = positions[key]
        assert qty == Decimal("0")

    def test_same_security_in_two_depots_tracked_separately(self):
        sec_a = _make_security(1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("100"))
        sec_b = _make_security(2, "AAPL", isin="US0378331005", tax_value_qty=Decimal("50"))
        depot_a = Depot(security=[sec_a], depotNumber=DepotNumber("DA"))
        depot_b = Depot(security=[sec_b], depotNumber=DepotNumber("DB"))
        stmt = _make_statement(depots=[depot_a, depot_b])
        positions = _get_ending_positions(stmt)

        isin_id = ("isin", "US0378331005")
        assert (DepotNumber("DA"), isin_id) in positions
        assert (DepotNumber("DB"), isin_id) in positions
        assert positions[(DepotNumber("DA"), isin_id)][0] == Decimal("100")
        assert positions[(DepotNumber("DB"), isin_id)][0] == Decimal("50")


# ---------------------------------------------------------------------------
# _get_opening_positions
# ---------------------------------------------------------------------------


class TestGetOpeningPositions:
    def test_extracts_quantity_from_first_balance_stock(self):
        sec = _make_security(1, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("200"))
        stmt = _make_statement(securities=[sec], period_year=2025)
        positions = _get_opening_positions(stmt)
        key = ("D001", ("isin", "US0378331005"))
        assert key in positions
        qty, _, _ = positions[key]
        assert qty == Decimal("200")

    def test_ignores_mutation_stock_entries(self):
        sec = _make_security(1, "AAPL", isin="US0378331005")
        sec.stock = [
            SecurityStock(
                referenceDate=date(2025, 1, 15),
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("10"),
                balanceCurrency="USD",
            )
        ]
        stmt = _make_statement(securities=[sec], period_year=2025)
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
        stmt = _make_statement(securities=[sec], period_year=2025)
        positions = _get_opening_positions(stmt)
        key = ("D001", ("isin", "US0378331005"))
        qty, _, _ = positions[key]
        assert qty == Decimal("100")

    def test_same_security_in_two_depots_tracked_separately(self):
        sec_a = _make_security(1, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("100"))
        sec_b = _make_security(2, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("40"))
        depot_a = Depot(security=[sec_a], depotNumber=DepotNumber("DA"))
        depot_b = Depot(security=[sec_b], depotNumber=DepotNumber("DB"))
        stmt = _make_statement(depots=[depot_a, depot_b], period_year=2025)
        positions = _get_opening_positions(stmt)

        isin_id = ("isin", "US0378331005")
        assert positions[(DepotNumber("DA"), isin_id)][0] == Decimal("100")
        assert positions[(DepotNumber("DB"), isin_id)][0] == Decimal("40")


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

        prior = _make_statement(securities=[prior_sec], period_year=2024)
        current = _make_statement(securities=[current_sec], period_year=2025)

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

        prior = _make_statement(securities=[prior_sec], period_year=2024)
        current = _make_statement(securities=[current_sec], period_year=2025)

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
        prior = _make_statement(securities=[prior_sec], period_year=2024)
        current = _make_statement(securities=[], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert not result.is_ok
        assert len(result.missing_in_current) == 1
        assert result.missing_in_current[0].isin == "US0378331005"

    def test_security_in_prior_only_with_zero_qty_is_ok(self):
        prior_sec = _make_security(
            1, "SOLD", isin="US1234567890", tax_value_qty=Decimal("0")
        )
        prior = _make_statement(securities=[prior_sec], period_year=2024)
        current = _make_statement(securities=[], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok
        assert result.matched_count == 1

    def test_security_in_current_only_with_nonzero_qty_is_flagged(self):
        current_sec = _make_security(
            1, "NEW", isin="US9999999999", opening_stock_qty=Decimal("50")
        )
        prior = _make_statement(securities=[], period_year=2024)
        current = _make_statement(securities=[current_sec], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert not result.is_ok
        assert len(result.missing_in_prior) == 1

    def test_security_in_current_only_with_zero_qty_is_ok(self):
        current_sec = _make_security(
            1, "NEW_ZERO", isin="US9999999999", opening_stock_qty=Decimal("0")
        )
        prior = _make_statement(securities=[], period_year=2024)
        current = _make_statement(securities=[current_sec], period_year=2025)

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

        prior = _make_statement(securities=prior_secs, period_year=2024)
        current = _make_statement(securities=current_secs, period_year=2025)

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

        prior = _make_statement(securities=[prior_sec], period_year=2024)
        current = _make_statement(securities=[current_sec], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok
        assert result.matched_count == 1

    def test_empty_statements_is_ok(self):
        prior = _make_statement(securities=[], period_year=2024)
        current = _make_statement(securities=[], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok
        assert result.matched_count == 0

    def test_no_list_of_securities_is_ok(self):
        prior = TaxStatement(minorVersion=2)
        current = TaxStatement(minorVersion=2)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok

    # --- Depot-aware matching ---

    def test_same_isin_in_different_depots_matched_independently(self):
        """Same ISIN in depot A and B should not be merged."""
        prior_a = _make_security(1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("100"))
        prior_b = _make_security(2, "AAPL", isin="US0378331005", tax_value_qty=Decimal("50"))
        current_a = _make_security(1, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("100"))
        current_b = _make_security(2, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("50"))

        prior = _make_statement(depots=[
            Depot(security=[prior_a], depotNumber=DepotNumber("DA")),
            Depot(security=[prior_b], depotNumber=DepotNumber("DB")),
        ], period_year=2024)
        current = _make_statement(depots=[
            Depot(security=[current_a], depotNumber=DepotNumber("DA")),
            Depot(security=[current_b], depotNumber=DepotNumber("DB")),
        ], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok
        assert result.matched_count == 2

    def test_same_isin_different_depots_mismatch_in_one(self):
        prior_a = _make_security(1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("100"))
        prior_b = _make_security(2, "AAPL", isin="US0378331005", tax_value_qty=Decimal("50"))
        current_a = _make_security(1, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("100"))
        current_b = _make_security(2, "AAPL", isin="US0378331005", opening_stock_qty=Decimal("30"))

        prior = _make_statement(depots=[
            Depot(security=[prior_a], depotNumber=DepotNumber("DA")),
            Depot(security=[prior_b], depotNumber=DepotNumber("DB")),
        ], period_year=2024)
        current = _make_statement(depots=[
            Depot(security=[current_a], depotNumber=DepotNumber("DA")),
            Depot(security=[current_b], depotNumber=DepotNumber("DB")),
        ], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert not result.is_ok
        assert result.matched_count == 1
        assert len(result.mismatches) == 1
        assert result.mismatches[0].depot == DepotNumber("DB")

    # --- Missing opening balance treated as zero ---

    def test_no_opening_balance_with_zero_prior_ending_is_ok(self):
        """Security has no opening stock entry and prior ended at zero → OK."""
        prior_sec = _make_security(
            1, "SOLD", isin="US1234567890", tax_value_qty=Decimal("0")
        )
        # Current security exists but without any stock entries (no opening balance)
        current_sec = _make_security(1, "SOLD", isin="US1234567890")

        prior = _make_statement(securities=[prior_sec], period_year=2024)
        current = _make_statement(securities=[current_sec], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert result.is_ok

    def test_no_opening_balance_with_nonzero_prior_ending_is_mismatch(self):
        """Security has no opening stock entry but prior ended with qty → mismatch."""
        prior_sec = _make_security(
            1, "AAPL", isin="US0378331005", tax_value_qty=Decimal("200")
        )
        # Current security exists with transactions but no opening balance stock entry
        current_sec = _make_security(1, "AAPL", isin="US0378331005")
        current_sec.stock = [
            SecurityStock(
                referenceDate=date(2025, 3, 1),
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("10"),
                balanceCurrency="USD",
            )
        ]

        prior = _make_statement(securities=[prior_sec], period_year=2024)
        current = _make_statement(securities=[current_sec], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert not result.is_ok
        assert len(result.mismatches) == 1
        assert result.mismatches[0].prior_quantity == Decimal("200")
        assert result.mismatches[0].current_quantity == Decimal("0")

    def test_no_opening_balance_security_not_in_current_at_all(self):
        """Security in prior with qty but completely absent from current → missing."""
        prior_sec = _make_security(
            1, "GONE", isin="US1111111118", tax_value_qty=Decimal("75")
        )

        prior = _make_statement(securities=[prior_sec], period_year=2024)
        current = _make_statement(securities=[], period_year=2025)

        result = verify_prior_period_positions(prior, current)
        assert not result.is_ok
        assert len(result.missing_in_current) == 1
        assert result.missing_in_current[0].quantity == Decimal("75")


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


# ---------------------------------------------------------------------------
# load_prior_period_statement  /  PriorPeriodXmlLoadError
# ---------------------------------------------------------------------------


class TestLoadPriorPeriodStatement:
    def test_file_not_found_gives_friendly_error(self, tmp_path):
        missing = str(tmp_path / "nonexistent.xml")
        with pytest.raises(PriorPeriodXmlLoadError) as exc_info:
            load_prior_period_statement(missing)
        assert "does not exist" in str(exc_info.value)
        assert missing in str(exc_info.value)

    def test_directory_instead_of_file_gives_friendly_error(self, tmp_path):
        with pytest.raises(PriorPeriodXmlLoadError) as exc_info:
            load_prior_period_statement(str(tmp_path))
        assert "not a regular file" in str(exc_info.value)

    def test_unreadable_file_gives_friendly_error(self, tmp_path):
        bad_file = tmp_path / "locked.xml"
        bad_file.write_text("<x/>")
        bad_file.chmod(0o000)
        try:
            with pytest.raises(PriorPeriodXmlLoadError) as exc_info:
                load_prior_period_statement(str(bad_file))
            assert "not readable" in str(exc_info.value)
        finally:
            bad_file.chmod(0o644)

    def test_malformed_xml_gives_friendly_error(self, tmp_path):
        bad_xml = tmp_path / "bad.xml"
        bad_xml.write_text("<<<not xml at all>>>")
        with pytest.raises(PriorPeriodXmlLoadError) as exc_info:
            load_prior_period_statement(str(bad_xml))
        assert "Could not load" in str(exc_info.value)

    def test_wrong_root_element_gives_friendly_error(self, tmp_path):
        wrong = tmp_path / "wrong.xml"
        wrong.write_text('<?xml version="1.0"?><notATaxStatement/>')
        with pytest.raises(PriorPeriodXmlLoadError) as exc_info:
            load_prior_period_statement(str(wrong))
        assert "Could not load" in str(exc_info.value)

    def test_valid_file_loads_successfully(self, tmp_path):
        xml_file = tmp_path / "prior.xml"
        xml_file.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<taxStatement xmlns="http://www.ech.ch/xmlns/eCH-0196/2"'
            ' minorVersion="2" taxPeriod="2023"'
            ' periodFrom="2023-01-01" periodTo="2023-12-31"/>'
        )
        stmt = load_prior_period_statement(str(xml_file))
        assert stmt.taxPeriod == 2023
