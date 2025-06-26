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
)
from opensteuerauszug.model.kursliste import (
    Da1Rate,
    PaymentShare,
    Share,
    SecurityGroupESTV,
)

@pytest.mark.skip("Currupts the shared state of the kursliste_manager fixture")
def test_da1_calculation_with_q_sign(kursliste_manager):
    """
    Test that a security with a (Q) sign payment is treated as a share for DA-1 calculation.
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

    # Mock the DA-1 rate for US shares
    accessor = kursliste_manager.get_kurslisten_for_year(2024)
    accessor.data_source[0].da1Rates = []
    accessor.data_source[0].da1Rates.append(
        Da1Rate(
            id=1,
            country="US",
            securityGroup=SecurityGroupESTV.SHARE,
            value=Decimal("15"),
            release=Decimal("15"),
            nonRecoverable=Decimal("0"),
        )
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

@pytest.mark.skip("Currupts the shared state of the kursliste_manager fixture")
def test_da1_calculation_for_share(kursliste_manager):
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
    accessor.data_source[0].da1Rates = []
    accessor.data_source[0].da1Rates.append(
        Da1Rate(
            id=2,
            country="DE",
            securityGroup=SecurityGroupESTV.SHARE,
            value=Decimal("26.375"),
            release=Decimal("15"),
            nonRecoverable=Decimal("11.375"),
        )
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
