from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from ..calculate.base import CalculationError
from ..model.ech0196 import Institution, SecurityPayment


def is_known_issue(error: Exception, institution: Optional[Institution]) -> bool:
    """Return True if ``error`` is considered a known issue for ``institution``."""
    if not isinstance(error, CalculationError):
        return False
    if not institution or not getattr(institution, "name", None):
        return False

    # All the example we have do not set the kurliste field
    if error.field_path.endswith(".kursliste") and error.actual is None:
        return True

    # Ignore name differences (perhaps we should not even check these?)
    if error.field_path.endswith("name") and 'payment' in error.field_path:
        return True

    # Allow omitting unknown payments
    if 'payment' in error.field_path and error.actual is None:
        if type(error.expected) is SecurityPayment:
            if error.expected.undefined:
                return True
    
    if institution.name.startswith("UBS"):
        if error.field_path.endswith("exchangeRate"):
            if error.expected == Decimal("1") and error.actual == Decimal("0"):
                return True
        elif error.field_path.endswith("taxValue.value") or error.field_path.endswith("amount"):
            # UBS rounds to two places (though the spec says not to round)
            if abs(error.expected - error.actual) < Decimal("0.005"):
                return True
    if institution.name.startswith("True Wealth"):
        # True wealth does not seem to use exchange rates from the kurstliste for the bank accounts
        # allow 2% deviation for exchange rates and values  
        if error.field_path.startswith("listOfBankAccounts"):
            if error.field_path.endswith("exchangeRate") or error.field_path.endswith("value"):
                if abs(error.expected - error.actual) / error.expected < Decimal("0.02"):
                    return True
        elif error.field_path.startswith("listOfSecurities"):
            if 'payment' in error.field_path:
                # Truewealth does not propegate sign it seems (at least not the ones in files we saw.
                if error.field_path.endswith("sign") and error.actual is None:
                    return True
                
            if error.field_path.endswith("unitPrice"):
            # Reported rounded to three places (though the spec says not to round)
                if abs(error.expected - error.actual) < Decimal("0.0005"):
                    return True
            if (
                error.expected is not None
                and error.actual is not None
                and type(error.expected) is Decimal
                and type(error.actual) is Decimal
                and error.expected.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                == error.actual.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            ):
                return True
            # The difference in TaxValue cascades, lets be a bit lenient here
            if error.field_path.endswith("value"):
                if abs(error.expected - error.actual) / error.expected < Decimal("0.005"):
                    return True
    return False
