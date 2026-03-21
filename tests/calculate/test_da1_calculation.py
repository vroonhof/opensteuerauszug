from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.model.ech0196 import (
    ISINType,
    Security,
    SecurityTaxValue,
    SecurityStock,
    SecurityPayment,
    CurrencyId,
)
from opensteuerauszug.model.kursliste import (
    Da1Rate,
    PaymentShare,
    Share,
    SecurityGroupESTV,
)

def test_da1_calculation_with_q_sign(kursliste_manager, monkeypatch):
    """
    Test that a security with a (Q) sign payment AND actual broker withholding
    is treated as a share for DA-1 calculation.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Mock a Kursliste security with a (Q) sign payment
    kl_sec = Share(
        id=1,
        securityGroup=SecurityGroupESTV.SHARE,
        country="US",
        currency="USD",
        institutionId=123,
        institutionName="Test Bank",
        payment=[
            PaymentShare(
                id=101,
                paymentDate=date(2024, 5, 10),
                currency="USD",
                paymentValue=Decimal("10.0"),
                paymentValueCHF=Decimal("9.0"),
                exchangeRate=Decimal("0.9"),
                sign="(Q)",
            )
        ]
    )

    # Provide a DA-1 rate via a patched accessor method instead of mutating the
    # shared fixture state
    accessor = kursliste_manager.get_kurslisten_for_year(2024)
    da1_rate = Da1Rate(
        id=1,
        country="US",
        securityGroup=SecurityGroupESTV.SHARE,
        value=Decimal("15"),
        release=Decimal("15"),
        nonRecoverable=Decimal("0"),
    )

    def mock_get_da1_rate(
        self,
        country,
        security_group,
        security_type=None,
        da1_rate_type=None,
        reference_date=None,
    ):
        if country == "US" and security_group == SecurityGroupESTV.SHARE:
            return da1_rate
        return None

    monkeypatch.setattr(
        accessor,
        "get_da1_rate",
        mock_get_da1_rate.__get__(accessor, type(accessor)),
    )

    # Add broker payment WITH actual withholding to trigger DA-1
    broker_dividend_payment = SecurityPayment(
        paymentDate=date(2024, 5, 10),
        name="Dividend",
        quotationType="PIECE",
        quantity=Decimal("100"),
        amountCurrency=CurrencyId("USD"),
        amount=Decimal("1000.0"),
        nonRecoverableTaxAmountOriginal=Decimal("100.0"),  # Actual withholding by broker
    )

    sec = Security(
        country="US",
        securityName="Test Q-Sign Security",
        positionId=1,
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US0000000001"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("100"),
            balanceCurrency="USD",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2024, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("100"),
                balanceCurrency="USD",
            )
        ],
        broker_payments=[broker_dividend_payment],  # Include broker payment with withholding
    )

    calc._current_kursliste_security = kl_sec
    calc.computePayments(sec, "sec")

    assert len(sec.payment) == 1
    payment = sec.payment[0]

    assert payment.lumpSumTaxCredit is True
    assert payment.lumpSumTaxCreditPercent == Decimal("15")
    assert payment.lumpSumTaxCreditAmount == Decimal("135")  # 900 * 0.15
    assert payment.nonRecoverableTaxPercent == Decimal("0")
    assert payment.nonRecoverableTaxAmount == Decimal("0")

def test_da1_calculation_for_share(kursliste_manager, monkeypatch):
    """
    Test DA-1 calculation for a regular share.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    kl_sec = Share(
        id=2,
        securityGroup=SecurityGroupESTV.SHARE,
        country="DE",
        currency="EUR",
        institutionId=123,
        institutionName="Test Bank",
        payment=[
            PaymentShare(
                id=102,
                paymentDate=date(2024, 6, 15),
                currency="EUR",
                paymentValue=Decimal("5.0"),
                paymentValueCHF=Decimal("4.8"),
                exchangeRate=Decimal("0.96"),
            )
        ]
    )

    accessor = kursliste_manager.get_kurslisten_for_year(2024)
    da1_rate = Da1Rate(
        id=2,
        country="DE",
        securityGroup=SecurityGroupESTV.SHARE,
        value=Decimal("26.375"),
        release=Decimal("15"),
        nonRecoverable=Decimal("11.375"),
    )

    def mock_get_da1_rate(
        self,
        country,
        security_group,
        security_type=None,
        da1_rate_type=None,
        reference_date=None,
    ):
        if country == "DE" and security_group == SecurityGroupESTV.SHARE:
            return da1_rate
        return None

    monkeypatch.setattr(
        accessor,
        "get_da1_rate",
        mock_get_da1_rate.__get__(accessor, type(accessor)),
    )

    sec = Security(
        country="DE",
        securityName="Test Share Security",
        positionId=2,
        currency="EUR",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("DE0000000001"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("200"),
            balanceCurrency="EUR",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2024, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("200"),
                balanceCurrency="EUR",
            )
        ],
    )

    calc._current_kursliste_security = kl_sec
    calc.computePayments(sec, "sec")

    assert len(sec.payment) == 1
    payment = sec.payment[0]

    assert payment.lumpSumTaxCredit is True
    assert payment.lumpSumTaxCreditPercent == Decimal("26.375")
    assert payment.lumpSumTaxCreditAmount == Decimal("253.2")  # 960 * 0.26375
    assert payment.nonRecoverableTaxPercent == Decimal("11.375")
    assert payment.nonRecoverableTaxAmount == Decimal("109.2")  # 960 * 0.11375

def test_da1_calculation_v_sign_raises_error(kursliste_manager):
    """
    Test that a (V) sign payment raises NotImplementedError.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    kl_sec = Share(
        id=3,
        securityGroup=SecurityGroupESTV.SHARE,
        country="US",
        currency="USD",
        institutionId=123,
        institutionName="Test Bank",
        payment=[
            PaymentShare(
                id=103,
                paymentDate=date(2024, 7, 20),
                currency="USD",
                paymentValue=Decimal("1.0"),
                paymentValueCHF=Decimal("0.9"),
                exchangeRate=Decimal("0.9"),
                sign="(V)",
            )
        ]
    )

    sec = Security(
        country="US",
        securityName="Test V-Sign Security",
        positionId=3,
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US0000000002"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("50"),
            balanceCurrency="USD",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2024, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("50"),
                balanceCurrency="USD",
            )
        ],
    )

    calc._current_kursliste_security = kl_sec
    with pytest.raises(NotImplementedError):
        calc.computePayments(sec, "sec")


def test_q_flag_without_broker_withholding_not_classified_as_da1(kursliste_manager, monkeypatch):
    """
    Test that a security with (Q) flag but no actual broker withholding is NOT classified as DA-1.

    This tests the fix for issue #295: Position with non-foreign-withholding tax deduction
    wrongly classified as DA-1.

    When Kursliste has (Q) flag (indicating foreign withholding tax applies) but the broker
    didn't actually withhold any tax, the security should NOT be classified as DA-1 and
    should NOT have DA-1 fields set.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Mock a Kursliste security with a (Q) sign payment
    kl_sec = Share(
        id=4,
        securityGroup=SecurityGroupESTV.SHARE,
        country="US",
        currency="USD",
        institutionId=123,
        institutionName="Test Bank",
        payment=[
            PaymentShare(
                id=104,
                paymentDate=date(2024, 5, 6),
                currency="USD",
                paymentValue=Decimal("0.350808"),
                paymentValueCHF=Decimal("0.315727"),  # assuming ~0.9 exchange rate
                exchangeRate=Decimal("0.9"),
                sign="(Q)",  # Indicates foreign withholding tax
            )
        ]
    )

    # Provide a DA-1 rate
    accessor = kursliste_manager.get_kurslisten_for_year(2024)
    da1_rate = Da1Rate(
        id=3,
        country="US",
        securityGroup=SecurityGroupESTV.SHARE,
        value=Decimal("15"),
        release=Decimal("15"),
        nonRecoverable=Decimal("0"),
    )

    def mock_get_da1_rate(
        self,
        country,
        security_group,
        security_type=None,
        da1_rate_type=None,
        reference_date=None,
    ):
        if country == "US" and security_group == SecurityGroupESTV.SHARE:
            return da1_rate
        return None

    monkeypatch.setattr(
        accessor,
        "get_da1_rate",
        mock_get_da1_rate.__get__(accessor, type(accessor)),
    )

    # Create a security with broker payment (dividend) but NO withholding tax
    # This simulates the IBKR case where there's a dividend payment but no withholding tax transaction
    broker_dividend_payment = SecurityPayment(
        paymentDate=date(2024, 5, 6),
        name="Dividend",
        quotationType="PIECE",
        quantity=Decimal("700"),
        amountCurrency=CurrencyId("USD"),
        amount=Decimal("245.57"),  # 700 * 0.350808
        # NOTE: No nonRecoverableTaxAmountOriginal set - no withholding by broker!
    )

    sec = Security(
        country="US",
        securityName="BANCOLOMBIA S.A.-SPONS ADR",
        positionId=4,
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US05968L1026"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("700"),
            balanceCurrency="USD",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2024, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("0"),
                balanceCurrency="USD",
            ),
            SecurityStock(
                referenceDate=date(2024, 4, 7),  # Settlement date of purchase
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("700"),
                balanceCurrency="USD",
            ),
        ],
        broker_payments=[broker_dividend_payment],  # Broker payment with NO withholding
    )

    calc._current_kursliste_security = kl_sec
    calc.computePayments(sec, "sec")

    assert len(sec.payment) == 1
    payment = sec.payment[0]

    # The payment should NOT have DA-1 fields set because there was no actual withholding by broker
    assert payment.lumpSumTaxCredit is None or payment.lumpSumTaxCredit is False
    assert payment.lumpSumTaxCreditPercent is None
    assert payment.lumpSumTaxCreditAmount is None
    assert payment.nonRecoverableTaxPercent is None
    assert payment.nonRecoverableTaxAmount is None
    assert payment.additionalWithHoldingTaxUSA is None

    # The payment should still have the regular dividend fields
    assert payment.grossRevenueB is not None  # Foreign dividend without withholding tax claim
    assert payment.grossRevenueB > Decimal("0")
