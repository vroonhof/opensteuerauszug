"""Tests for known_issues utility functions."""
import pytest
from decimal import Decimal

from opensteuerauszug.calculate.base import CalculationError
from opensteuerauszug.model.ech0196 import Institution
from opensteuerauszug.util.known_issues import is_known_issue


def test_is_known_issue_handles_none_expected():
    """Verify that is_known_issue handles None expected value without crashing."""
    error = CalculationError(
        field_path="listOfSecurities[US0378331005].payment[0].amountPerUnit",
        expected=None,
        actual=Decimal("10.5")
    )
    institution = Institution(name="True Wealth AG")
    
    # Should not crash and should return False (not a known issue)
    result = is_known_issue(error, institution)
    assert result is False


def test_is_known_issue_handles_none_actual():
    """Verify that is_known_issue handles None actual value without crashing.
    
    Note: For TrueWealth, None actual values in payment fields are considered known issues.
    """
    error = CalculationError(
        field_path="listOfSecurities[US0378331005].payment[0].amountPerUnit",
        expected=Decimal("10.5"),
        actual=None
    )
    institution = Institution(name="True Wealth AG")
    
    # Should not crash - TrueWealth has specific logic for None actual in payment fields
    result = is_known_issue(error, institution)
    assert result is True  # This is a known issue for TrueWealth


def test_is_known_issue_handles_both_none():
    """Verify that is_known_issue handles both values being None without crashing.
    
    Note: For TrueWealth, None actual values in payment fields are considered known issues.
    """
    error = CalculationError(
        field_path="listOfSecurities[US0378331005].payment[0].amountPerUnit",
        expected=None,
        actual=None
    )
    institution = Institution(name="True Wealth AG")
    
    # Should not crash - TrueWealth has specific logic for None actual in payment fields
    result = is_known_issue(error, institution)
    assert result is True  # This is a known issue for TrueWealth (actual is None in payment field)


def test_is_known_issue_ubs_with_none_values():
    """Verify that is_known_issue handles None values for UBS institution."""
    error = CalculationError(
        field_path="listOfSecurities[US0378331005].taxValue.value",
        expected=Decimal("100.5"),
        actual=None
    )
    institution = Institution(name="UBS Switzerland AG")
    
    # Should not crash and should return False (not a known issue)
    result = is_known_issue(error, institution)
    assert result is False


def test_is_known_issue_truewealth_with_none_on_division():
    """Verify that is_known_issue handles None values that would cause division errors."""
    # Test case where error.expected is None and we would divide by it
    error = CalculationError(
        field_path="listOfSecurities[US0378331005].value",
        expected=None,
        actual=Decimal("100.0")
    )
    institution = Institution(name="True Wealth AG")
    
    # Should not crash
    result = is_known_issue(error, institution)
    assert result is False


def test_is_known_issue_truewealth_bankaccount_with_none():
    """Verify that is_known_issue handles None values for True Wealth bank accounts."""
    error = CalculationError(
        field_path="listOfBankAccounts[0].exchangeRate",
        expected=None,
        actual=Decimal("1.05")
    )
    institution = Institution(name="True Wealth AG")
    
    # Should not crash
    result = is_known_issue(error, institution)
    assert result is False


def test_is_known_issue_with_valid_decimal_values():
    """Verify that is_known_issue still works correctly with valid Decimal values."""
    # Test a case that should be recognized as a known issue (UBS rounding)
    error = CalculationError(
        field_path="listOfSecurities[US0378331005].taxValue.value",
        expected=Decimal("100.123"),
        actual=Decimal("100.125")
    )
    institution = Institution(name="UBS Switzerland AG")
    
    # This should be recognized as a known issue (difference < 0.005)
    result = is_known_issue(error, institution)
    assert result is True
