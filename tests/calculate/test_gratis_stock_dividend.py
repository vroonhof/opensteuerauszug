"""
Tests for gratis stock dividend handling (GRATIS payment type).

This module tests that:
1. No DA-1 withholding tax is calculated for GRATIS (stock dividend) payments
2. Stock dividend mutations are validated on the payment date, not ex-date
3. Warning messages correctly identify events as "stock dividend" not "stock split"
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.core.kursliste_accessor import KurslisteAccessor
from opensteuerauszug.model.ech0196 import (
    ISINType,
    Depot,
    DepotNumber,
    ListOfSecurities,
    Security,
    SecurityTaxValue,
    SecurityStock,
    TaxStatement,
)
from opensteuerauszug.model.critical_warning import CriticalWarningCategory
from opensteuerauszug.model.kursliste import (
    Kursliste,
    Legend,
    PaymentShare,
    PaymentTypeESTV,
    Share,
    SecurityGroupESTV,
)


def test_gratis_stock_dividend_has_no_da1_withholding():
    """Test that GRATIS payment type does not generate DA-1 withholding tax claims.

    Stock dividends (gratis=True, paymentType=GRATIS) don't involve cash withholding,
    so no DA-1 reclaim should be calculated.
    """
    ex_date = date(2025, 7, 11)
    payment_date = date(2025, 7, 18)

    # Create a gratis stock dividend payment as shown in the issue
    payment = PaymentShare(
        id=7309735,
        paymentIdSIX="612299403",
        paymentDate=payment_date,
        currency="CHF",  # Use CHF to avoid exchange rate lookup
        paymentValue=Decimal("0.1"),  # Nominal value per share
        exchangeRate=Decimal("1"),
        paymentValueCHF=Decimal("0.1"),
        paymentType=PaymentTypeESTV.GRATIS,  # This is the key: GRATIS not STANDARD
        taxEvent=True,
        exDate=ex_date,
        gratis=True,
        withHoldingTax=False,  # No withholding for stock dividends
        legend=[
            Legend(
                id=1264980,
                eventIdSIX="612299403",
                effectiveDate=ex_date,
                exchangeRatioAvailable=Decimal("1"),
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("1.05"),
            )
        ],
    )

    share = Share(
        id=1,
        isin="CH0147853092",  # Use CH country code to match CHF
        valorNumber=1234567,
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="Test Stock Dividend Security",
        institutionId=1,
        institutionName="Test Company",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("1"),
        payment=[payment],
    )

    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )

    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    # Create a security with stock mutation on payment date (not ex-date)
    security = Security(
        country="CH",
        securityName="Test Stock Dividend Security",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("CH0147853092"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("2425.5"),  # After stock dividend
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("2310"),  # Pre-dividend position
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=payment_date,  # Mutation on payment date, not ex-date!
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("115.5"),  # 5% stock dividend: 2310 * 0.05
                balanceCurrency="CHF",
            ),
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("U1234567"), security=[security])]
        ),
    )

    calc.calculate(statement)

    # Should have one payment generated
    assert len(security.payment) == 1
    payment_result = security.payment[0]

    # Verify payment has correct metadata
    assert payment_result.name == "Stock Dividend"
    assert payment_result.gratis is True
    assert payment_result.paymentDate == payment_date
    assert payment_result.exDate == ex_date

    # CRITICAL: No DA-1 withholding should be calculated for GRATIS payments
    assert payment_result.withHoldingTaxClaim is None or payment_result.withHoldingTaxClaim == Decimal("0")
    assert payment_result.lumpSumTaxCreditAmount is None
    assert payment_result.lumpSumTaxCreditPercent is None
    assert payment_result.nonRecoverableTaxAmount is None
    assert payment_result.nonRecoverableTaxPercent is None
    assert payment_result.lumpSumTaxCredit is not True

    # Should have no warnings since mutation is on correct date (payment_date)
    assert calc.errors == []
    split_warnings = [
        w for w in calc._stock_split_warnings
    ]
    assert len(split_warnings) == 0


def test_gratis_stock_dividend_warning_uses_correct_date():
    """Test that stock dividend validation looks for mutations on payment date, not ex-date.

    For gratis stock dividends, the mutation typically occurs on the payment date,
    not the ex-date (effective date). The warning should also mention "stock dividend"
    not "stock split".
    """
    ex_date = date(2025, 7, 11)
    payment_date = date(2025, 7, 18)

    payment = PaymentShare(
        id=7309735,
        paymentDate=payment_date,
        currency="CHF",
        paymentValue=Decimal("0.1"),
        exchangeRate=Decimal("1"),
        paymentValueCHF=Decimal("0.1"),
        paymentType=PaymentTypeESTV.GRATIS,
        taxEvent=True,
        exDate=ex_date,
        gratis=True,
        withHoldingTax=False,
        legend=[
            Legend(
                id=1,
                effectiveDate=ex_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("1.05"),
            )
        ],
    )

    share = Share(
        id=1,
        isin="CH0147853092",
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="Test Stock Dividend Security",
        institutionId=1,
        institutionName="Test Company",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("1"),
        payment=[payment],
    )

    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )

    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    # Create a security WITHOUT the mutation - should trigger warning
    security = Security(
        country="CH",
        securityName="Test Stock Dividend Security",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("CH0147853092"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("2310"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("2310"),
                balanceCurrency="CHF",
            ),
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("U1234567"), security=[security])]
        ),
    )

    calc.calculate(statement)

    # Should have warning about missing mutation
    warnings = calc._stock_split_warnings
    assert len(warnings) == 1
    warning_msg = warnings[0]["message"]

    # CRITICAL: Should mention "stock dividend" not "stock split"
    assert "stock dividend" in warning_msg.lower()
    assert "stock split" not in warning_msg.lower()

    # CRITICAL: Should reference the payment date, not ex-date
    assert str(payment_date) in warning_msg
    assert "115.5" in warning_msg  # Expected delta: 2310 * (1.05 - 1) = 115.5
    assert warnings[0]["identifier"] == "CH0147853092"


def test_regular_stock_split_still_uses_split_terminology():
    """Test that regular stock splits (non-gratis) still use 'stock split' terminology.

    This ensures we didn't break the existing behavior for normal stock splits.
    """
    split_date = date(2025, 6, 18)

    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="USD",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,  # Not GRATIS
        taxEvent=True,
        exDate=split_date,
        gratis=False,  # Not a gratis payment
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("4"),
            )
        ],
    )

    share = Share(
        id=1,
        isin="US45841N1072",
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="Test Company",
        institutionId=1,
        institutionName="Test Company",
        country="US",
        currency="USD",
        nominalValue=Decimal("0.01"),
        payment=[payment],
    )

    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )

    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    # Create security without mutation to trigger warning
    security = Security(
        country="US",
        securityName="Test Company",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US45841N1072"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("2"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("2"),
                balanceCurrency="CHF",
            ),
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("U1234567"), security=[security])]
        ),
    )

    calc.calculate(statement)

    # Should have warning about missing mutation
    warnings = calc._stock_split_warnings
    assert len(warnings) == 1
    warning_msg = warnings[0]["message"]

    # Should use "stock split" terminology for non-gratis splits
    assert "stock split" in warning_msg.lower()
    assert "stock dividend" not in warning_msg.lower()
