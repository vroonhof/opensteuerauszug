# pyright: reportOperatorIssue=false
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from ..calculate.base import CalculationError
from ..model.ech0196 import Institution, SecurityPayment


# With our current structure we cannot auto detect.
TRUEWEALTH_USES_CHF = [
    "IE0005042456",
    "IE0009YEDMC6",
    "IE00B3B8PX14",
    "IE00B4K6B022",
    "IE00B4WPHX27",
    "IE00B7452L46",
    "IE00BK6NC407",
    "IE00BMFJGP26",
    "LU1109942653",
]


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

    # We currently assume foreign brokers and set additionalWithHoldingTaxUSA to 0.
    # Swiss brokers might have non-zero values.
    # TODO: Support Swiss brokers properly with a config setting.
    if error.field_path.endswith("additionalWithHoldingTaxUSA"):
        if error.expected == Decimal("0"):
            return True

    if institution.name.startswith("UBS"):
        if error.field_path.endswith("exchangeRate"):
            if error.expected == Decimal("1") and error.actual == Decimal("0"):
                return True
        elif error.field_path.endswith("taxValue.value") or error.field_path.endswith("amount"):
            # UBS rounds to two places (though the spec says not to round)
            if error.expected is not None and error.actual is not None:
                if abs(error.expected - error.actual) < Decimal("0.005"):
                    return True
        if type(error.expected) is Decimal and type(error.actual) is Decimal:
            if 'payment' in error.field_path:
                # UBS sometimes rounds more sometimes uses more accurate values than kursliste
                # add some tolerance for these
                if abs(error.expected - error.actual) <= Decimal("0.01"):
                    return True
    if institution.name.startswith("True Wealth"):
        # True wealth does not seem to use exchange rates from the kurstliste for the bank accounts
        # allow 2% deviation for exchange rates and values  
        if error.field_path.startswith("listOfBankAccounts"):
            if error.field_path.endswith("exchangeRate") or error.field_path.endswith("value"):
                if error.expected is not None and error.actual is not None and error.expected != Decimal("0"):
                    if abs(error.expected - error.actual) / error.expected < Decimal("0.02"):
                        return True
        elif error.field_path.startswith("listOfSecurities"):
            if 'payment' in error.field_path:
                # Truewealth does not propegate sign it seems (at least not the ones in files we saw.
                if error.field_path.endswith("sign") and error.actual is None:
                    return True
                TRUEWALTH_UNSET_FIELDS = ['.amount', '.exchangeRate']
                if error.actual is None and any(f in error.field_path for f in TRUEWALTH_UNSET_FIELDS):
                    return True
                if any(isin in error.field_path for isin in TRUEWEALTH_USES_CHF):
                    # For these securities, True Wealth uses CHF as currency, so the native currency values are wrong
                    if 'amountPer' in error.field_path or 'amountCurrency' in error.field_path:
                        return True
                if error.field_path.endswith("amountPerUnit"):
                    # Truewealth seems to recompute this backward from rounding and gets way more
                    # digits than in the actual kursliste.
                    if error.expected is not None and error.actual is not None:
                        if abs(error.expected - error.actual) < Decimal("0.005"):
                            return True
                # TODO(recompute against kursliste site):  
                if error.field_path.endswith("grossRevenueA") or error.field_path.endswith("grossRevenueB"):
                    # allow small tolerance for rounding differences. unclear who is correct
                    if error.expected is not None and error.actual is not None:
                        if abs(error.expected - error.actual) < Decimal("0.01"):
                            return True

            if error.field_path.endswith("unitPrice"):
            # Reported rounded to three places (though the spec says not to round)
                if error.expected is not None and error.actual is not None:
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
                if error.expected is not None and error.actual is not None and error.expected != Decimal("0"):
                    if abs(error.expected - error.actual) / error.expected < Decimal("0.005"):
                        return True
    else:
        # Ignore common implementation issues for unknown institutions
        if "Revenue" in error.field_path:
            if type(error.expected) is Decimal and type(error.actual) is Decimal:
                if abs(error.expected - error.actual) < Decimal("0.01"):
                    return True
            if error.expected == Decimal("0") and error.actual is None:
                return True
    return False
