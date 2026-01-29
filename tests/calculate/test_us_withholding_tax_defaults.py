from decimal import Decimal
from datetime import date
from typing import Optional

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.fill_in_tax_value_calculator import FillInTaxValueCalculator
from opensteuerauszug.core.exchange_rate_provider import DummyExchangeRateProvider
from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Security,
    SecurityPayment,
    ListOfSecurities,
    Depot,
    DepotNumber
)

def test_fix_issue_78_us_security_additional_withholding_tax_usa():
    """
    Test that FillInTaxValueCalculator correctly sets additionalWithHoldingTaxUSA to 0
    for US securities when other DA1 fields are present, if it is missing, when in
    FILL mode.
    """
    provider = DummyExchangeRateProvider()
    calculator = FillInTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Create a dummy tax statement with a US security and a payment
    security = Security(
        positionId=1,
        country="US",
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        securityName="Test US Security",
        payment=[
            SecurityPayment(
                paymentDate=date(2023, 1, 1),
                quotationType="PIECE",
                quantity=Decimal("10"),
                amountCurrency="USD",
                amount=Decimal("100"),
                nonRecoverableTaxAmount=Decimal("1.00"),
                additionalWithHoldingTaxUSA=None  # Explicitly None
            )
        ]
    )

    depot = Depot(depotNumber=DepotNumber("123"), security=[security])
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(depot=[depot])
    )

    # Run calculation
    calculator.calculate(statement)

    # Assert that additionalWithHoldingTaxUSA is set to 0
    payment = statement.listOfSecurities.depot[0].security[0].payment[0]
    # This assertion is expected to fail before the fix
    assert payment.additionalWithHoldingTaxUSA is not None
    assert payment.additionalWithHoldingTaxUSA == Decimal("0")

def test_fix_issue_78_non_us_security_additional_withholding_tax_usa():
    """
    Test that FillInTaxValueCalculator does NOT set additionalWithHoldingTaxUSA
    for non-US securities if it is missing.
    """
    provider = DummyExchangeRateProvider()
    calculator = FillInTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Create a dummy tax statement with a CH security and a payment
    security = Security(
        positionId=1,
        country="CH",
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        securityName="Test CH Security",
        payment=[
            SecurityPayment(
                paymentDate=date(2023, 1, 1),
                quotationType="PIECE",
                quantity=Decimal("10"),
                amountCurrency="CHF",
                amount=Decimal("100"),
                additionalWithHoldingTaxUSA=None
            )
        ]
    )

    depot = Depot(depotNumber=DepotNumber("123"), security=[security])
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(depot=[depot])
    )

    # Run calculation
    calculator.calculate(statement)

    # Assert that additionalWithHoldingTaxUSA remains None
    payment = statement.listOfSecurities.depot[0].security[0].payment[0]
    assert payment.additionalWithHoldingTaxUSA is None
