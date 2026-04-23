"""Small parsing helpers shared by broker importers.

These are all plain functions.  The aim is that any importer can
compose them without having to derive from a base class.
"""

from decimal import Decimal, InvalidOperation


def to_decimal(value: object | None, field_name: str, context: str) -> Decimal:
    """Convert *value* to ``Decimal`` or raise ``ValueError`` with context.

    Args:
        value: The value to convert.  Typically a ``str``, ``int`` or
            ``Decimal``; anything that ``Decimal(str(x))`` can parse.
        field_name: Logical field the value came from (for error messages).
        context: Free-form context such as ``"Trade AAPL"`` that is embedded
            in the exception to help the user locate bad input rows.

    Raises:
        ValueError: if *value* is ``None`` or cannot be parsed as Decimal.
    """
    if value is None:
        raise ValueError(
            f"Cannot convert None to Decimal for field '{field_name}' in {context}"
        )
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(
            f"Invalid value for Decimal conversion: '{value}' for field "
            f"'{field_name}' in {context}"
        )
