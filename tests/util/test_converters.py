"""Tests for the converter utilities."""
from datetime import date, timedelta
from decimal import Decimal
from opensteuerauszug.model.ech0196 import SecurityTaxValue
from opensteuerauszug.util.converters import security_tax_value_to_stock


def test_security_tax_value_to_stock():
    """Verify that SecurityTaxValue is correctly converted to SecurityStock."""
    tax_value = SecurityTaxValue(
        referenceDate=date(2024, 12, 31),
        quotationType="PIECE",
        quantity=Decimal("100"),
        balanceCurrency="CHF",
        name="Test Security",
        unitPrice=Decimal("12.34"),
        balance=Decimal("1234.00"),
        exchangeRate=Decimal("1.0"),
        value=Decimal("1234.00"),
        blocked=True,
        blockingTo=date(2025, 6, 30),
    )

    stock = security_tax_value_to_stock(tax_value)

    assert stock.referenceDate == tax_value.referenceDate + timedelta(days=1)
    assert stock.mutation is False
    assert stock.quotationType == tax_value.quotationType
    assert stock.quantity == tax_value.quantity
    assert stock.balanceCurrency == tax_value.balanceCurrency
    assert stock.name == tax_value.name
    assert stock.unitPrice == tax_value.unitPrice
    assert stock.balance == tax_value.balance
    assert stock.exchangeRate == tax_value.exchangeRate
    assert stock.value == tax_value.value
    assert stock.blocked == tax_value.blocked
    assert stock.blockingTo == tax_value.blockingTo
