"""Utility functions for converting between different model types."""
from datetime import timedelta
from opensteuerauszug.model.ech0196 import SecurityTaxValue, SecurityStock


def security_tax_value_to_stock(tax_value: SecurityTaxValue) -> SecurityStock:
    """Converts a SecurityTaxValue to a SecurityStock for the next day.

    Args:
        tax_value: The SecurityTaxValue to convert.

    Returns:
        A new SecurityStock instance representing the stock on the day after
        the tax value's reference date.
    """
    return SecurityStock(
        referenceDate=tax_value.referenceDate + timedelta(days=1),
        mutation=False,
        quotationType=tax_value.quotationType,
        quantity=tax_value.quantity,
        balanceCurrency=tax_value.balanceCurrency,
        name=tax_value.name,
        unitPrice=tax_value.unitPrice,
        balance=tax_value.balance,
        exchangeRate=tax_value.exchangeRate,
        value=tax_value.value,
        blocked=tax_value.blocked,
        blockingTo=tax_value.blockingTo,
    )
