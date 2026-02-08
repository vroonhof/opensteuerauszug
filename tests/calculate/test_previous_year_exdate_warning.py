"""Tests for critical warnings when a payment has an exDate in the previous year."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from opensteuerauszug.calculate.cleanup import CleanupCalculator
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


def _make_statement_with_payment(
    ex_date,
    payment_date=None,
    period_from=None,
    period_to=None,
    security_name="Test Security",
):
    """Create a minimal TaxStatement with one security that has a payment."""
    if payment_date is None:
        payment_date = date(2024, 1, 15)
    if period_from is None:
        period_from = date(2024, 1, 1)
    if period_to is None:
        period_to = date(2024, 12, 31)

    payment = SecurityPayment(
        paymentDate=payment_date,
        exDate=ex_date,
        name="Dividend",
        quotationType="PIECE",
        quantity=Decimal("10"),
        amountCurrency="USD",
        amount=Decimal("50"),
    )
    security = Security(
        positionId=1,
        isin=ISINType("US0378331005"),
        securityName=security_name,
        securityCategory="SHARE",
        country="US",
        currency="USD",
        quotationType="PIECE",
        payment=[payment],
        stock=[
            SecurityStock(
                referenceDate=period_from,
                mutation=False,
                quantity=Decimal("10"),
                balanceCurrency="USD",
                quotationType="PIECE",
            ),
        ],
        taxValue=SecurityTaxValue(
            referenceDate=period_to,
            quotationType="PIECE",
            quantity=Decimal("10"),
            balanceCurrency="USD",
        ),
    )
    return TaxStatement(
        minorVersion=2,
        id="test-exdate-warnings",
        creationDate=datetime(2024, 6, 1),
        taxPeriod=period_to.year,
        periodFrom=period_from,
        periodTo=period_to,
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


def test_previous_year_exdate_generates_critical_warning():
    """A payment with exDate before period_from produces a critical warning."""
    statement = _make_statement_with_payment(
        ex_date=date(2023, 12, 20),
        payment_date=date(2024, 1, 15),
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
    )
    calculator = CleanupCalculator(
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        importer_name="test",
    )
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 1
    assert "ex-date" in warnings[0].message
    assert "2023-12-20" in warnings[0].message
    assert warnings[0].source == "CleanupCalculator"
    assert warnings[0].identifier == "US0378331005"


def test_current_year_exdate_generates_no_warning():
    """A payment with exDate within the period does not produce a warning."""
    statement = _make_statement_with_payment(
        ex_date=date(2024, 3, 15),
        payment_date=date(2024, 4, 1),
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
    )
    calculator = CleanupCalculator(
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        importer_name="test",
    )
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 0


def test_no_exdate_generates_no_warning():
    """A payment without an exDate does not produce a warning."""
    statement = _make_statement_with_payment(
        ex_date=None,
        payment_date=date(2024, 4, 1),
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
    )
    calculator = CleanupCalculator(
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        importer_name="test",
    )
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 0


def test_exdate_on_period_start_generates_no_warning():
    """A payment with exDate exactly on period_from does not produce a warning."""
    statement = _make_statement_with_payment(
        ex_date=date(2024, 1, 1),
        payment_date=date(2024, 1, 15),
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
    )
    calculator = CleanupCalculator(
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        importer_name="test",
    )
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 0


def test_multiple_payments_one_previous_year_exdate():
    """Only payments with previous-year exDate trigger warnings, not all."""
    period_from = date(2024, 1, 1)
    period_to = date(2024, 12, 31)

    payment_prev_year = SecurityPayment(
        paymentDate=date(2024, 1, 10),
        exDate=date(2023, 12, 28),
        name="Dividend Q4",
        quotationType="PIECE",
        quantity=Decimal("10"),
        amountCurrency="USD",
        amount=Decimal("25"),
    )
    payment_current_year = SecurityPayment(
        paymentDate=date(2024, 6, 15),
        exDate=date(2024, 6, 10),
        name="Dividend Q2",
        quotationType="PIECE",
        quantity=Decimal("10"),
        amountCurrency="USD",
        amount=Decimal("25"),
    )
    security = Security(
        positionId=1,
        isin=ISINType("US0378331005"),
        securityName="Apple Inc",
        securityCategory="SHARE",
        country="US",
        currency="USD",
        quotationType="PIECE",
        payment=[payment_prev_year, payment_current_year],
        stock=[
            SecurityStock(
                referenceDate=period_from,
                mutation=False,
                quantity=Decimal("10"),
                balanceCurrency="USD",
                quotationType="PIECE",
            ),
        ],
        taxValue=SecurityTaxValue(
            referenceDate=period_to,
            quotationType="PIECE",
            quantity=Decimal("10"),
            balanceCurrency="USD",
        ),
    )
    statement = TaxStatement(
        minorVersion=2,
        id="test-multi-exdate",
        creationDate=datetime(2024, 6, 1),
        taxPeriod=2024,
        periodFrom=period_from,
        periodTo=period_to,
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

    calculator = CleanupCalculator(
        period_from=period_from,
        period_to=period_to,
        importer_name="test",
    )
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 1
    assert "2023-12-28" in warnings[0].message
    assert "Dividend Q4" in warnings[0].message


def test_warning_message_contains_key_information():
    """The warning message includes the payment name, exDate, and security identifier."""
    statement = _make_statement_with_payment(
        ex_date=date(2023, 12, 15),
        payment_date=date(2024, 1, 5),
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        security_name="Apple Inc",
    )
    calculator = CleanupCalculator(
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        importer_name="test",
    )
    result = calculator.calculate(statement)

    warnings = [
        w
        for w in result.critical_warnings
        if w.category == CriticalWarningCategory.PREVIOUS_YEAR_EXDATE
    ]
    assert len(warnings) == 1
    msg = warnings[0].message
    assert "Dividend" in msg
    assert "2023-12-15" in msg
    assert "2024-01-05" in msg
    assert "opening position" in msg
    assert "double-check" in msg
