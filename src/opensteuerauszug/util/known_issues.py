from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from ..calculate.base import CalculationError
from ..model.ech0196 import Institution


def is_known_issue(error: Exception, institution: Optional[Institution]) -> bool:
    """Return True if ``error`` is considered a known issue for ``institution``."""
    if not isinstance(error, CalculationError):
        return False
    if not institution or not getattr(institution, "name", None):
        return False

    if institution.name.startswith("UBS"):
        if error.field_path.endswith("exchangeRate"):
            if error.expected == Decimal("1") and error.actual == Decimal("0"):
                return True
        elif error.field_path.endswith("taxValue.value"):
            if abs(error.expected - error.actual) / error.expected < Decimal("0.005"):
                return True
    if institution.name.startswith("True Wealth"):
        if error.field_path.startswith("listOfBankAccounts"):
            if error.field_path.endswith("exchangeRate") or error.field_path.endswith("value"):
                if abs(error.expected - error.actual) / error.expected < Decimal("0.005"):
                    return True
        elif error.field_path.startswith("listOfSecurities"):
            if (
                error.expected is not None
                and error.actual is not None
                and error.expected.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                == error.actual.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            ):
                return True
            if error.field_path.endswith("value"):
                if abs(error.expected - error.actual) / error.expected < Decimal("0.005"):
                    return True
    return False
