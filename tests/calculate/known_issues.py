from decimal import ROUND_HALF_UP, Decimal
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
        elif error.field_path.endswith("taxValue.value"):
            # UBS rounds to two places (though the spec says not to round)
            if abs(error.expected - error.actual) / error.expected < Decimal("0.005"):
                return True
    if institution.name.startswith("True Wealth"):
        # True wealth does not seem to use exchange rates from the kurstliste for the bank accounts
        # allow 0.5% deviation for exchange rates and values
        if error.field_path.startswith("listOfBankAccounts"):
            if error.field_path.endswith("exchangeRate") or error.field_path.endswith("value"):
                if abs(error.expected - error.actual) / error.expected < Decimal("0.005"):
                    return True
        elif error.field_path.startswith("listOfSecurities"):
            # Truewealth seem to calculate internally to 6 decimal places
            if (error.expected is not None and error.actual is not None and
                error.expected.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) ==
                error.actual.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)):
                return True
            # The difference in TaxValue cascades, lets be a bit lenient here
            if error.field_path.endswith("value"):
                if abs(error.expected - error.actual) / error.expected < Decimal("0.005"):
                    return True
    return False
