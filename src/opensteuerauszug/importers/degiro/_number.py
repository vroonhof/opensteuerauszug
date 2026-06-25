"""Number-parsing helpers for the Degiro importer.

Degiro CSV exports use the locale-specific number formatting of the user's
account language: English exports use ``1234.56`` while German/Italian/French
exports use ``1.234,56`` (or quoted ``"3487,66"``).  These helpers normalise
both styles to a plain ``Decimal``-compatible string before parsing.
"""

from decimal import Decimal

from opensteuerauszug.importers.common.parsing import to_decimal


def normalize_number(s: str) -> str:
    """Strip thousands separators and convert decimal commas to dots.

    Handles:
      * Swiss/Italian style with apostrophe thousands: ``1'000.50``
      * English/US style with comma thousands: ``1,000.50``
      * German/French style with dot thousands and comma decimal: ``1.000,50``
      * Plain European decimal comma: ``3487,66``
    """
    if "," in s and "." in s:
        if s.rindex(",") > s.rindex("."):
            return s.replace(".", "").replace(",", ".")
        return s.replace(",", "")
    if "," in s:
        return s.replace(",", ".")
    return s.replace("'", "")


def to_decimal_localized(value: str, field_name: str, context: str) -> Decimal:
    """Like ``to_decimal`` but tolerant of European number formats."""
    return to_decimal(normalize_number(value), field_name, context)
