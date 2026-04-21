from datetime import date
from decimal import Decimal

from opensteuerauszug.importers.common import (
    apply_withholding_tax_fields,
    build_security_payment,
)
from opensteuerauszug.core.constants import UNINITIALIZED_QUANTITY
from opensteuerauszug.model.ech0196 import SecurityPayment


def _blank_payment() -> SecurityPayment:
    return SecurityPayment(
        paymentDate=date(2024, 1, 1),
        name="Div",
        amountCurrency="USD",
        amount=Decimal("10"),
        quotationType="PIECE",
        quantity=UNINITIALIZED_QUANTITY,
    )


def test_apply_withholding_negative_chf_sets_claim():
    p = _blank_payment()
    apply_withholding_tax_fields(p, Decimal("-5"), "CHF")
    assert p.withHoldingTaxClaim == Decimal("5")
    assert p.nonRecoverableTaxAmountOriginal is None


def test_apply_withholding_negative_foreign_sets_non_recoverable():
    p = _blank_payment()
    apply_withholding_tax_fields(p, Decimal("-5"), "USD")
    assert p.nonRecoverableTaxAmountOriginal == Decimal("5")
    assert p.withHoldingTaxClaim is None


def test_apply_withholding_positive_records_reversal():
    p = _blank_payment()
    apply_withholding_tax_fields(p, Decimal("5"), "USD")
    assert p.nonRecoverableTaxAmountOriginal == Decimal("-5")


def test_build_security_payment_basic():
    p = build_security_payment(
        payment_date=date(2024, 3, 1),
        description="Dividend AAPL",
        currency="USD",
        amount=Decimal("42"),
        broker_label="DIV",
    )
    assert p.paymentDate == date(2024, 3, 1)
    assert p.name == "Dividend AAPL"
    assert p.amount == Decimal("42")
    assert p.broker_label_original == "DIV"
    assert p.securitiesLending is None or p.securitiesLending is False
    assert p.withHoldingTaxClaim is None


def test_build_security_payment_securities_lending_and_withholding():
    p = build_security_payment(
        payment_date=date(2024, 3, 1),
        description="wht",
        currency="USD",
        amount=Decimal("-3"),
        broker_label="WHTAX",
        is_securities_lending=True,
        is_withholding=True,
    )
    assert p.securitiesLending is True
    assert p.nonRecoverableTaxAmountOriginal == Decimal("3")
