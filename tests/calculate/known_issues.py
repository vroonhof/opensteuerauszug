from decimal import Decimal
from typing import Optional
from opensteuerauszug.calculate.base import CalculationError
from opensteuerauszug.model.ech0196 import Institution

def _known_issue(error: Exception, institution: Optional[Institution]) -> bool:
    """
    Determine if an error is a known issue that should be ignored.
    
    Args:
        error: The error to check
        institution: The institution associated with the tax statement
        
    Returns:
        bool: True if the error is a known issue, False otherwise
    """
    if not isinstance(error, CalculationError):
        return False
    if not institution or not institution.name:
        return False
    if institution.name.startswith("UBS"):
        if error.field_path.endswith("exchangeRate"):
            # UBS has a known issue with broken exchange rates on CHF payments
            if error.expected == Decimal("1") and error.actual == Decimal("0"):
                return True
    if institution.name.startswith("True Wealth"):
        # True wealth does not seem to use exchange rates from the kurstliste for the bank accounts
        # allow 0.5% deviation for exchange rates and values
        if error.field_path.endswith("exchangeRate") or error.field_path.endswith("value"):
            if abs(error.expected - error.actual) / error.expected < Decimal("0.005"):
                return True

    return False
