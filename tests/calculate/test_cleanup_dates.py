import pytest
from datetime import date
from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.model.ech0196 import TaxStatement, CantonAbbreviation

@pytest.fixture
def base_statement():
    """Create a minimal TaxStatement for testing."""
    return TaxStatement(
        minorVersion=1,
        periodFrom=date(2023, 1, 1),
        periodTo=date(2023, 12, 31),
        taxPeriod=2023,
        canton="ZH",
        listOfSecurities=None,
        listOfBankAccounts=None
    )

def test_cleanup_respects_valid_dates(base_statement):
    """Test that valid dates within the requested window are preserved."""
    requested_from = date(2023, 1, 1)
    requested_to = date(2023, 12, 31)

    # Statement has a partial period (e.g. account opened in June)
    stmt_from = date(2023, 6, 1)
    stmt_to = date(2023, 12, 31)

    base_statement.periodFrom = stmt_from
    base_statement.periodTo = stmt_to

    calculator = CleanupCalculator(
        period_from=requested_from,
        period_to=requested_to,
        importer_name="TestImporter",
        config_settings=None
    )

    result = calculator.calculate(base_statement)

    # Dates should be preserved
    assert result.periodFrom == stmt_from
    assert result.periodTo == stmt_to

def test_cleanup_resets_dates_outside_start(base_statement):
    """Test that periodFrom is reset if it is before the requested start date."""
    requested_from = date(2023, 1, 1)
    requested_to = date(2023, 12, 31)

    # Statement starts in previous year (e.g. 2022)
    stmt_from = date(2022, 12, 31)
    stmt_to = date(2023, 12, 31)

    base_statement.periodFrom = stmt_from
    base_statement.periodTo = stmt_to

    calculator = CleanupCalculator(
        period_from=requested_from,
        period_to=requested_to,
        importer_name="TestImporter",
        config_settings=None
    )

    result = calculator.calculate(base_statement)

    # Start date should be reset to requested start date
    assert result.periodFrom == requested_from
    # End date should be preserved
    assert result.periodTo == stmt_to

def test_cleanup_resets_dates_outside_end(base_statement):
    """Test that periodTo is reset if it is after the requested end date."""
    requested_from = date(2023, 1, 1)
    requested_to = date(2023, 12, 31)

    # Statement ends in next year (e.g. 2024)
    stmt_from = date(2023, 1, 1)
    stmt_to = date(2024, 1, 1)

    base_statement.periodFrom = stmt_from
    base_statement.periodTo = stmt_to

    calculator = CleanupCalculator(
        period_from=requested_from,
        period_to=requested_to,
        importer_name="TestImporter",
        config_settings=None
    )

    result = calculator.calculate(base_statement)

    # Start date should be preserved
    assert result.periodFrom == stmt_from
    # End date should be reset to requested end date
    assert result.periodTo == requested_to

def test_cleanup_sets_dates_if_missing(base_statement):
    """Test that dates are set from config if missing in statement."""
    requested_from = date(2023, 1, 1)
    requested_to = date(2023, 12, 31)

    # Statement has no dates (simulated, though usually mandatory in model but optional in some contexts)
    # Actually TaxStatement model fields are mandatory but can be None if optional (check model definition)
    # The Pydantic model might enforce it, but let's assume it can be None initially
    base_statement.periodFrom = None
    base_statement.periodTo = None

    calculator = CleanupCalculator(
        period_from=requested_from,
        period_to=requested_to,
        importer_name="TestImporter",
        config_settings=None
    )

    result = calculator.calculate(base_statement)

    assert result.periodFrom == requested_from
    assert result.periodTo == requested_to
