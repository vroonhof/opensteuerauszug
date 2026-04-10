"""Tests for critical warnings when a Kursliste payment has an exDate in the previous year."""

import datetime as dt
from datetime import date, datetime
from decimal import Decimal

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from opensteuerauszug.calculate.payment_reconciliation_calculator import (
    PaymentReconciliationCalculator,
)
from opensteuerauszug.core.kursliste_accessor import KurslisteAccessor
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.model.critical_warning import CriticalWarningCategory
from opensteuerauszug.model.ech0196 import (
    Depot,
    DepotNumber,
    ISINType,
    ListOfSecurities,
    Security,
    SecurityPayment,
    SecurityStock,
    SecurityTaxValue,
    TaxStatement,
)
from opensteuerauszug.model.kursliste import (
    ExchangeRateYearEnd,
    Kursliste,
    PaymentShare,
    Share,
)


def _make_statement(isin="US0000000000", name="Test Security", tax_year=2024):
    """Create a minimal TaxStatement with one security (no payments)."""
    security = Security(
        positionId=1,
        isin=ISINType(isin),
        securityName=name,
        securityCategory="SHARE",
        country="US",
        currency="USD",
        quotationType="PIECE",
        stock=[
            SecurityStock(
                referenceDate=date(tax_year, 1, 1),
                mutation=False,
                quantity=Decimal("10"),
                balanceCurrency="USD",
                quotationType="PIECE",
            ),
        ],
        taxValue=SecurityTaxValue(
            referenceDate=date(tax_year, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("10"),
            balanceCurrency="USD",
        ),
    )
    return TaxStatement(
        minorVersion=2,
        id="test-exdate-warnings",
        creationDate=datetime(tax_year, 6, 1),
        taxPeriod=tax_year,
        periodFrom=date(tax_year, 1, 1),
        periodTo=date(tax_year, 12, 31),
        country="CH",
        canton="ZH",
        totalTaxValue=Decimal("0"),
        totalGrossRevenueA=Decimal("0"),
        totalGrossRevenueB=Decimal("0"),
        totalWithHoldingTaxClaim=Decimal("0"),
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("D1"), security=[security])]
        ),
    )


def _make_kursliste(shares, tax_year=2024):
    """Create a Kursliste with a USD exchange rate and given shares."""
    return Kursliste(
        version="2.2.0.0",
        creationDate=dt.datetime(tax_year, 12, 31),
        year=tax_year,
        shares=shares,
        exchangeRatesYearEnd=[
            ExchangeRateYearEnd(currency="USD", year=tax_year, value=Decimal("0.85")),
        ],
    )


def _make_provider(kursliste, tax_year=2024):
    """Wrap a Kursliste into a KurslisteExchangeRateProvider."""
    manager = KurslisteManager()
    manager.kurslisten[tax_year] = KurslisteAccessor(
        data_source=[kursliste], tax_year=tax_year
    )
    return KurslisteExchangeRateProvider(manager)


def _make_share_with_payment(isin, name, ex_date, payment_date, tax_year=2024):
    """Create a Share with a single PaymentShare."""
    payment = PaymentShare(
        id=1,
        paymentDate=payment_date,
        exDate=ex_date,
        currency="USD",
        paymentValue=Decimal("1.00"),
        paymentValueCHF=Decimal("0.85"),
        exchangeRate=Decimal("0.85"),
        withHoldingTax=True,
    )
    return Share(
        id=1,
        institutionId=1,
        institutionName="Test Institution",
        valorNumber=12345,
        isin=isin,
        securityName=name,
        country="US",
        currency="USD",
        securityGroup="SHARE",
        payment=[payment],
    )


def test_previous_year_exdate_generates_critical_warning():
    """A Kursliste payment with exDate before the tax year produces a warning."""
    share = _make_share_with_payment(
        isin="US0000000000",
        name="Test Security",
        ex_date=date(2023, 12, 20),
        payment_date=date(2024, 1, 15),
    )
    provider = _make_provider(_make_kursliste(shares=[share]))
    calculator = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE,
        exchange_rate_provider=provider,
    )
    statement = _make_statement()
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 1
    assert "ex-date" in warnings[0].message
    assert "2023-12-20" in warnings[0].message
    assert warnings[0].source == "KurslisteTaxValueCalculator"
    assert warnings[0].identifier == "US0000000000"


def test_current_year_exdate_generates_no_warning():
    """A Kursliste payment with exDate within the tax year produces no warning."""
    share = _make_share_with_payment(
        isin="US0000000000",
        name="Test Security",
        ex_date=date(2024, 3, 15),
        payment_date=date(2024, 4, 1),
    )
    provider = _make_provider(_make_kursliste(shares=[share]))
    calculator = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE,
        exchange_rate_provider=provider,
    )
    statement = _make_statement()
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 0


def test_no_exdate_generates_no_warning():
    """A Kursliste payment without an exDate produces no warning."""
    share = _make_share_with_payment(
        isin="US0000000000",
        name="Test Security",
        ex_date=None,
        payment_date=date(2024, 4, 1),
    )
    provider = _make_provider(_make_kursliste(shares=[share]))
    calculator = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE,
        exchange_rate_provider=provider,
    )
    statement = _make_statement()
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 0


def test_warning_message_contains_key_information():
    """The warning message includes exDate, security identifier, and guidance."""
    share = _make_share_with_payment(
        isin="US0000000000",
        name="Test Security",
        ex_date=date(2023, 12, 15),
        payment_date=date(2024, 1, 5),
    )
    provider = _make_provider(_make_kursliste(shares=[share]))
    calculator = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE,
        exchange_rate_provider=provider,
    )
    statement = _make_statement()
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 1
    msg = warnings[0].message
    assert "2023-12-15" in msg
    assert "opening position" in msg
    assert "double-check" in msg


def test_previous_year_exdate_warning_dismissed_when_reconciliation_matches():
    """Warning is removed when payment reconciliation confirms the amount is correct."""
    isin = "US0000000000"
    name = "Test Security"
    payment_date = date(2024, 1, 15)

    payment = PaymentShare(
        id=1,
        paymentDate=payment_date,
        exDate=date(2023, 12, 20),
        currency="USD",
        paymentValue=Decimal("1.00"),
        paymentValueCHF=Decimal("0.85"),
        exchangeRate=Decimal("0.85"),
        withHoldingTax=False,
    )
    share = Share(
        id=1, institutionId=1, institutionName="Test",
        valorNumber=12345, isin=isin, securityName=name,
        country="US", currency="USD", securityGroup="SHARE",
        payment=[payment],
    )
    provider = _make_provider(_make_kursliste(shares=[share]))
    calculator = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE,
        exchange_rate_provider=provider,
    )
    statement = _make_statement(isin=isin, name=name)
    result = calculator.calculate(statement)

    assert any(
        w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
        for w in result.critical_warnings
    )

    # Add matching broker payment (grossRevenueB=8.50 CHF → 10 USD at 0.85 rate)
    security = result.listOfSecurities.depot[0].security[0]
    security.broker_payments = [
        SecurityPayment(
            paymentDate=payment_date,
            quotationType="PIECE",
            quantity=Decimal("-1"),
            amountCurrency="USD",
            amount=Decimal("10"),
            name="Dividend",
        ),
    ]

    result = PaymentReconciliationCalculator().calculate(result)

    report = result.payment_reconciliation_report
    assert any(
        r.identifier == isin and r.payment_date == payment_date and r.matched
        for r in report.rows
    )

    warnings_after = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings_after) == 0


def test_previous_year_exdate_warning_kept_when_reconciliation_mismatches():
    """Warning is kept when payment reconciliation shows a mismatch."""
    isin = "US0000000000"
    name = "Test Security"
    payment_date = date(2024, 1, 15)

    share = _make_share_with_payment(
        isin=isin,
        name=name,
        ex_date=date(2023, 12, 20),
        payment_date=payment_date,
    )
    provider = _make_provider(_make_kursliste(shares=[share]))
    calculator = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE,
        exchange_rate_provider=provider,
    )
    statement = _make_statement(isin=isin, name=name)
    result = calculator.calculate(statement)

    # Add wildly mismatching broker payments so reconciliation fails
    security = result.listOfSecurities.depot[0].security[0]
    security.broker_payments = [
        SecurityPayment(
            paymentDate=payment_date,
            quotationType="PIECE",
            quantity=Decimal("-1"),
            amountCurrency="USD",
            amount=Decimal("99999"),
            name="Dividend",
        ),
    ]

    reconciliation_calculator = PaymentReconciliationCalculator()
    result = reconciliation_calculator.calculate(result)

    warnings_after = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings_after) == 1


