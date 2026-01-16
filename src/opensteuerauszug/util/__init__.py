from decimal import Decimal, ROUND_HALF_UP
from .date_coverage import DateRangeCoverage
from .known_issues import is_known_issue

QUANTIZE_3_PLACES = Decimal("0.001")
QUANTIZE_2_PLACES = Decimal("0.01")


def round_accounting(value: Decimal | float | int) -> Decimal:
    """
    Rundet einen Betrag gemäss eCH-0196 Spezifikation.

    Spezifikation:
    Gerundet wird nur nach der Summenbildung. Beträge kleiner 100 sind mit 3
    Nachkommastellen darzustellen, Beträge grösser gleich 100 mit 2
    Nachkommastellen. Bei sämtlichen zu rundenden Beträgen muss nach DIN-Norm
    1333 vorgegangen werden: Ist die Zahl an der ersten wegfallenden
    Dezimalstelle eine:
    0,1,2,3 oder 4 wird abgerundet
    5,6,7,8 oder 9 wird aufgerundet
    Einzelpositionen (Steuerwerte, Erträge) sind in den Originalwerten ohne
    Rundung zu übernehmen.

    Args:
        value: Der zu rundende Betrag.

    Returns:
        Der gerundete Betrag als Decimal.
    """
    val_decimal = Decimal(str(value)) # Ensure Decimal for precision

    if abs(val_decimal) < 100:
        # Round to 3 decimal places
        return val_decimal.quantize(QUANTIZE_3_PLACES, rounding=ROUND_HALF_UP)
    else:
        # Round to 2 decimal places
        return val_decimal.quantize(QUANTIZE_2_PLACES, rounding=ROUND_HALF_UP)
