"""
Tests for gratis stock dividend handling (GRATIS payment type).

This module tests that:
1. No DA-1 withholding tax is calculated for GRATIS (stock dividend) payments
2. Stock dividend mutations are validated on the payment date, not ex-date
3. Warning messages correctly identify events as "stock dividend" not "stock split"
"""

from datetime import date, datetime
from decimal import Decimal

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
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider, render_language='en'
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

    # GRATIS payments have taxable revenue but no withholding claim or DA-1
    assert payment_result.grossRevenueA == Decimal("0")
    assert payment_result.grossRevenueB == Decimal("231.0")  # 2310 * 0.1
    assert payment_result.withHoldingTaxClaim == Decimal("0")
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
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider, render_language='en'
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
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider, render_language='en'
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


def _make_calc_with_gratis_payment(ex_date, payment_date):
    """Helper: return (calc, share) for a GRATIS stock-dividend payment."""
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
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider, render_language='en'
    )
    return calc, share


def _make_security_with_mutation_on(mutation_date, quantity=Decimal("2310")):
    """Return a Security whose only mutation is on *mutation_date*."""
    delta = quantity * Decimal("0.05")  # 5% gratis stock dividend
    return Security(
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
            quantity=quantity + delta,
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=quantity,
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=mutation_date,
                mutation=True,
                quotationType="PIECE",
                quantity=delta,
                balanceCurrency="CHF",
            ),
        ],
    )


def test_gratis_stock_dividend_mutation_on_exdate_fallback_accepted():
    """Mutation on ex-date is accepted as a fallback for gratis stock dividends.

    The Kursliste primary date for gratis events is paymentDate.  When the broker
    records the mutation on the ex-date instead, the validator should silently
    accept it (no warning) provided no other tax event falls between the two dates.
    """
    ex_date = date(2025, 7, 11)      # Friday
    payment_date = date(2025, 7, 18)  # Following Friday

    calc, _ = _make_calc_with_gratis_payment(ex_date, payment_date)
    # Mutation is on ex_date, not payment_date
    security = _make_security_with_mutation_on(ex_date)

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

    # Fallback should have been used silently — no warnings
    assert calc._stock_split_warnings == []


def test_stock_split_mutation_on_next_business_day_fallback_accepted():
    """Mutation on next business day is accepted as a fallback for stock splits.

    Some brokers post corporate actions one business day after the Kursliste
    effective date.  The validator should silently accept that date.
    """
    ex_date = date(2025, 3, 14)   # Friday — the Kursliste effectiveDate
    payment_date = date(2025, 3, 17)  # Monday
    next_bday = date(2025, 3, 17)     # Monday = next business day after Friday

    payment = PaymentShare(
        id=1,
        paymentDate=payment_date,
        currency="USD",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=ex_date,
        gratis=False,
        legend=[
            Legend(
                id=1,
                effectiveDate=ex_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("2"),
            )
        ],
    )
    share = Share(
        id=1,
        isin="US45841N1072",
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="Test Split Security",
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
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider, render_language='en'
    )

    quantity = Decimal("100")
    # Mutation is on the next business day (Monday), not ex_date (Friday)
    security = Security(
        country="US",
        securityName="Test Split Security",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US45841N1072"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=quantity * 2,
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=quantity,
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=next_bday,  # Monday, not ex_date
                mutation=True,
                quotationType="PIECE",
                quantity=quantity,  # 2:1 split delta = +100
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

    # Fallback to next business day should have been used silently — no warnings
    assert calc._stock_split_warnings == []


def test_fallback_blocked_by_intervening_tax_event():
    """Fallback date matching is skipped when another tax event falls between dates.

    When a second tax event occurs between the primary date and the candidate
    fallback date, the fallback must not be used (to avoid ambiguity).  The
    validator should issue a warning in this case.
    """
    ex_date = date(2025, 7, 11)       # Friday — effectiveDate for split
    payment_date = date(2025, 7, 18)  # Following Friday

    # An *intervening* dividend payment lands on 2025-07-15 (Tuesday), which
    # falls strictly between ex_date and payment_date.
    intervening_dividend = PaymentShare(
        id=2,
        paymentDate=date(2025, 7, 15),
        currency="CHF",
        paymentValue=Decimal("1"),
        exchangeRate=Decimal("1"),
        paymentValueCHF=Decimal("1"),
        paymentType=PaymentTypeESTV.STANDARD,
        taxEvent=True,
        exDate=date(2025, 7, 15),
    )
    split_payment = PaymentShare(
        id=1,
        paymentDate=payment_date,
        currency="CHF",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
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
        securityName="Test Security",
        institutionId=1,
        institutionName="Test Company",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("1"),
        payment=[split_payment, intervening_dividend],
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
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider, render_language='en'
    )

    quantity = Decimal("2310")
    # Put the mutation on ex_date — but the fallback to ex_date should be blocked
    # by the intervening dividend on 2025-07-15.
    security = _make_security_with_mutation_on(ex_date, quantity=quantity)

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

    # The ex_date fallback is blocked; should have a stock-dividend warning.
    assert len(calc._stock_split_warnings) == 1
    assert "stock dividend" in calc._stock_split_warnings[0]["message"].lower()
