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
    TaxStatement,
)
from opensteuerauszug.model.kursliste import (
    PaymentShare,
    PaymentTypeESTV,
    Share,
)
from tests.utils.samples import get_sample_files

from .known_issues import _known_issue


class TestKurslisteTaxValueCalculatorIntegration:
    @pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
    def test_run_in_verify_mode_no_errors(
        self, sample_file: str, exchange_rate_provider: KurslisteExchangeRateProvider
    ):
        """
        Tests that KurslisteTaxValueCalculator runs in VERIFY mode
        without producing errors when processing real-world sample TaxStatement XML files.
        Uses the real exchange rate provider from kursliste.
        """
        calculator = KurslisteTaxValueCalculator(
            mode=CalculationMode.VERIFY, exchange_rate_provider=exchange_rate_provider
        )

        tax_statement_input = TaxStatement.from_xml_file(sample_file)

        processed_statement = calculator.calculate(tax_statement_input)

        filtered_errors = [
            e for e in calculator.errors if not _known_issue(e, tax_statement_input.institution)
        ]

        assert filtered_errors == [], "Unexpected verification errors"
        assert processed_statement is tax_statement_input


def test_handle_security_sets_valor_number(kursliste_manager):
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)
    sec = Security(
        country="CH",
        securityName="Roche",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("CH0012032048"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("500"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2024, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("500"),
                balanceCurrency="CHF",
            )
        ],
    )
    assert sec.valorNumber is None
    calc._handle_Security(sec, "sec")
    assert sec.valorNumber == 1203204


def test_handle_security_tax_value_from_kursliste(kursliste_manager):
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)
    sec = Security(
        country="CH",
        securityName="Roche",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("CH0012032048"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("500"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2024, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("500"),
                balanceCurrency="CHF",
            )
        ],
    )
    calc._handle_Security(sec, "sec")
    stv = sec.taxValue
    calc._handle_SecurityTaxValue(stv, "sec.taxValue")
    assert stv is not None
    assert stv.unitPrice == Decimal("255.5")
    assert stv.value == Decimal("127750")
    assert stv.exchangeRate == Decimal("1")
    assert stv.kursliste is True


def test_compute_payments_from_kursliste_missing_ex_date(kursliste_manager):
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    sec = Security(
        country="IE",
        securityName="iShares Core S&P 500 UCITS ETF USD (Acc)",
        positionId=1,
        currency="USD",
        quotationType="PIECE",
        securityCategory="FUND",
        isin=ISINType("IE00B3B8PX14"),
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

    # The Kursliste for this security has a payment with no exDate
    calc._handle_Security(sec, "sec")
    assert len(sec.payment) == 1
    payment = sec.payment[0]
    assert payment.paymentDate == date(2024, 6, 30)
    assert payment.exDate is None
    assert payment.amountCurrency == "USD"
    assert payment.amountPerUnit == Decimal("1.5312762338")
    assert payment.amount == Decimal("153.12762338")
    assert payment.exchangeRate == Decimal("0.90405")
    assert payment.grossRevenueB == Decimal("138.400")


def test_compute_payments_from_kursliste(kursliste_manager):
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    sec = Security(
        country="US",
        securityName="Vanguard Total Stock Market ETF",
        positionId=1,
        currency="USD",
        quotationType="PIECE",
        securityCategory="FUND",
        isin=ISINType("US9229087690"),
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

    calc._handle_Security(sec, "sec")
    assert len(sec.payment) == 4
    first = sec.payment[0]
    assert first.paymentDate == date(2024, 3, 27)
    assert first.amountCurrency == "USD"
    assert first.amountPerUnit == Decimal("0.9105")
    assert first.amount == Decimal("91.05")
    assert first.exchangeRate == Decimal("0.90565")
    assert first.grossRevenueB == Decimal("82.45900")


def test_compute_payments_with_tax_value_as_stock(kursliste_manager):
    """
    Test that computePayments uses the closing stock from the tax value
    if no other stock information is available.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    sec = Security(
        country="US",
        securityName="Vanguard Total Stock Market ETF",
        positionId=1,
        currency="USD",
        quotationType="PIECE",
        securityCategory="FUND",
        isin=ISINType("US9229087690"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("200"),  # Different quantity
            balanceCurrency="USD",
        ),
        stock=[],  # No initial stock
    )

    calc._handle_Security(sec, "sec")
    assert len(sec.payment) == 4
    first = sec.payment[0]
    assert first.paymentDate == date(2024, 3, 27)
    assert first.quantity == Decimal("200")
    assert first.amount == Decimal("182.10")


def test_propagate_payment_fields(kursliste_manager):
    """
    Test that `undefined`, `sign`, `gratis`, and `paymentType` fields are
    correctly propagated from a Kursliste payment to a SecurityPayment.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Mock a Kursliste security with a special payment
    kl_sec = Share(
        id=1,
        securityGroup="SHARE",
        country="CH",
        currency="CHF",
        institutionId=123,
        institutionName="Test Bank",
        payment=[
            PaymentShare(
                id=101,
                paymentDate=date(2024, 5, 10),
                currency="CHF",
                undefined=True,
                sign="XYZ",
                gratis=True,
                paymentType=PaymentTypeESTV.GRATIS,
            )
        ]
    )

    sec = Security(
        country="CH",
        securityName="Test Security",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("CH0000000001"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("100"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2024, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("100"),
                balanceCurrency="CHF",
            )
        ],
    )

    # Manually set the Kursliste security for the calculator
    calc._current_kursliste_security = kl_sec

    # Run the payment computation
    calc.computePayments(sec, "sec")

    # Assertions
    assert len(sec.payment) == 1
    payment = sec.payment[0]

    assert payment.undefined is True
    assert payment.sign == "XYZ"
    assert payment.gratis is True


def test_compute_payments_skip_zero_quantity(kursliste_manager):
    """
    Test that payments are not generated when the quantity of outstanding
    securities is zero on the payment date.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Create a security with stock that goes to zero before the payment date
    sec = Security(
        country="US",
        securityName="Vanguard Total Stock Market ETF",
        positionId=1,
        currency="USD",
        quotationType="PIECE",
        securityCategory="FUND",
        isin=ISINType("US9229087690"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2024, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("0"),  # Final quantity is zero
            balanceCurrency="USD",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2024, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("100"),
                balanceCurrency="USD",
            ),
            SecurityStock(
                referenceDate=date(2024, 3, 1),  # Before the first payment date (2024-03-27)
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("-100"),  # Sell all shares
                balanceCurrency="USD",
            ),
        ],
    )

    calc._handle_Security(sec, "sec")
    # Should not generate any payments since quantity is zero on payment dates
    assert len(sec.payment) == 0
