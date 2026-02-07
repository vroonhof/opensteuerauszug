"""Tests for the CriticalWarning model."""

from opensteuerauszug.model.critical_warning import (
    CriticalWarning,
    CriticalWarningCategory,
)


def test_critical_warning_creation():
    """A CriticalWarning can be created with all fields."""
    warning = CriticalWarning(
        category=CriticalWarningCategory.MISSING_KURSLISTE,
        message="Missing entry for AAPL",
        source="KurslisteTaxValueCalculator",
        identifier="US0378331005",
    )
    assert warning.category == CriticalWarningCategory.MISSING_KURSLISTE
    assert warning.message == "Missing entry for AAPL"
    assert warning.source == "KurslisteTaxValueCalculator"
    assert warning.identifier == "US0378331005"


def test_critical_warning_without_identifier():
    """identifier is optional and defaults to None."""
    warning = CriticalWarning(
        category=CriticalWarningCategory.OTHER,
        message="Something went wrong",
        source="test",
    )
    assert warning.identifier is None


def test_critical_warning_categories():
    """All expected categories exist."""
    assert CriticalWarningCategory.MISSING_KURSLISTE == "missing_kursliste"
    assert CriticalWarningCategory.UNMAPPED_SYMBOL == "unmapped_symbol"
    assert CriticalWarningCategory.OTHER == "other"
