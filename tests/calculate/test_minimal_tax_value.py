from decimal import Decimal
import pytest
from opensteuerauszug.calculate.minimal_tax_value import MinimalTaxValueCalculator
from opensteuerauszug.calculate.base import CalculationError, CalculationMode
from opensteuerauszug.model.ech0196 import (
    TaxStatement, BankAccount, BankAccountTaxValue, BankAccountPayment,
    LiabilityAccountTaxValue, LiabilityAccountPayment, Security, SecurityTaxValue,
    SecurityPayment, Institution
)
from opensteuerauszug.core.exchange_rate_provider import DummyExchangeRateProvider, ExchangeRateProvider
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from datetime import date, datetime
from typing import Optional
from tests.utils.samples import get_sample_files
from .known_issues import _known_issue

@pytest.fixture
def minimal_tax_value_calculator_overwrite() -> MinimalTaxValueCalculator:
    """Returns a MinimalTaxValueCalculator in OVERWRITE mode."""
    provider: ExchangeRateProvider = DummyExchangeRateProvider()
    return MinimalTaxValueCalculator(mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider)

@pytest.fixture
def minimal_tax_value_calculator_verify() -> MinimalTaxValueCalculator:
    """Returns a MinimalTaxValueCalculator in VERIFY mode."""
    provider: ExchangeRateProvider = DummyExchangeRateProvider()
    return MinimalTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=provider)

@pytest.fixture
def minimal_tax_value_calculator_fill() -> MinimalTaxValueCalculator:
    """Returns a MinimalTaxValueCalculator in FILL mode."""
    provider: ExchangeRateProvider = DummyExchangeRateProvider()
    return MinimalTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

@pytest.fixture
def empty_tax_statement() -> TaxStatement:
    """Returns a minimally valid empty TaxStatement."""
    statement = TaxStatement(minorVersion=2)
    return statement

def test_minimal_tax_value_calculator_initialization(minimal_tax_value_calculator_overwrite):
    """Test that the calculator initializes correctly."""
    assert minimal_tax_value_calculator_overwrite.mode == CalculationMode.OVERWRITE
    assert len(minimal_tax_value_calculator_overwrite.errors) == 0
    assert len(minimal_tax_value_calculator_overwrite.modified_fields) == 0

def test_minimal_tax_value_calculator_calculate_empty_statement_overwrite(
    minimal_tax_value_calculator_overwrite: MinimalTaxValueCalculator,
    empty_tax_statement: TaxStatement
):
    """Test the calculate method with an empty statement in OVERWRITE mode."""
    # Since it's a stub, we mainly check that it runs without error
    # and doesn't unexpectedly modify or error out.
    result_statement = minimal_tax_value_calculator_overwrite.calculate(empty_tax_statement)
    assert result_statement is empty_tax_statement # It should return the same object
    assert len(minimal_tax_value_calculator_overwrite.errors) == 0
    # In a real scenario, modified_fields might change. For a stub, it might be 0.
    # assert len(minimal_tax_value_calculator_overwrite.modified_fields) == 0 # Or check for expected modifications

def test_minimal_tax_value_calculator_calculate_empty_statement_verify(
    minimal_tax_value_calculator_verify: MinimalTaxValueCalculator,
    empty_tax_statement: TaxStatement
):
    """Test the calculate method with an empty statement in VERIFY mode."""
    result_statement = minimal_tax_value_calculator_verify.calculate(empty_tax_statement)
    assert result_statement is empty_tax_statement
    assert len(minimal_tax_value_calculator_verify.errors) == 0
    assert len(minimal_tax_value_calculator_verify.modified_fields) == 0 # Verify mode should not modify


class TestMinimalTaxValueCalculatorIntegration:
    @pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
    def test_run_in_verify_mode_no_errors(self, sample_file: str, exchange_rate_provider: KurslisteExchangeRateProvider):
        """
        Tests that MinimalTaxValueCalculator runs in VERIFY mode
        without producing errors when processing real-world sample TaxStatement XML files.
        Uses the real exchange rate provider from kursliste.
        """
        calculator = MinimalTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=exchange_rate_provider)
        
        # Load TaxStatement from the sample XML file
        tax_statement_input = TaxStatement.from_xml_file(sample_file)

        # Process the statement.
        processed_statement = calculator.calculate(tax_statement_input)

        filtered_errors = [e for e in calculator.errors if not _known_issue(e, tax_statement_input.institution)]

        # Check if any errors were found during verification
        if filtered_errors:
            error_messages = [str(e) for e in filtered_errors]
            error_details = "\n".join(error_messages)
            pytest.fail(f"MinimalTaxValueCalculator produced errors for {sample_file} with {len(filtered_errors)} errors:\n{error_details}")
        
        # Assert that the statement itself is returned
        assert processed_statement is tax_statement_input


class TestMinimalTaxValueCalculatorHandlers:
    def test_handle_bank_account_ch(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        ba = BankAccount(bankAccountCountry="CH")
        calculator._handle_BankAccount(ba, "ba")
        assert calculator._current_account_is_type_A is True

    def test_handle_bank_account_foreign(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        ba = BankAccount(bankAccountCountry="DE")
        calculator._handle_BankAccount(ba, "ba")
        assert calculator._current_account_is_type_A is False

    def test_handle_bank_account_unknown(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        ba = BankAccount(bankAccountCountry=None) # No country
        calculator._handle_BankAccount(ba, "ba")
        assert calculator._current_account_is_type_A is None

    def test_handle_bank_account_tax_value_conversion(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        batv = BankAccountTaxValue(
            balance=Decimal("1000"), 
            balanceCurrency="USD", 
            referenceDate=date(2023, 12, 31)
        )
        calculator._handle_BankAccountTaxValue(batv, "batv")
        assert batv.exchangeRate == Decimal("0.5") # Dummy provider rate
        assert batv.value == Decimal("500") # 1000 * 0.5

    def test_handle_bank_account_tax_value_chf(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        batv = BankAccountTaxValue(
            balance=Decimal("1000"), 
            balanceCurrency="CHF", 
            referenceDate=date(2023, 12, 31)
        )
        calculator._handle_BankAccountTaxValue(batv, "batv")
        assert batv.exchangeRate == Decimal("1")
        assert batv.value == Decimal("1000")

    def test_handle_bank_account_payment_type_a(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        calculator._current_account_is_type_A = True
        bap = BankAccountPayment(
            amount=Decimal("200"), 
            amountCurrency="CHF", 
            paymentDate=date(2023, 6, 30)
        )
        calculator._handle_BankAccountPayment(bap, "bap")
        assert bap.exchangeRate == Decimal("1") # Dummy rate
        assert bap.grossRevenueA == Decimal("200") # 200
        assert bap.withHoldingTaxClaim == Decimal("70") # 200 * 0.35
        assert not bap.grossRevenueB or bap.grossRevenueB == Decimal("0") # No gross revenue B for type A

    def test_handle_bank_account_payment_type_b(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        calculator._current_account_is_type_A = False
        bap = BankAccountPayment(
            amount=Decimal("200"), 
            amountCurrency="USD", 
            paymentDate=date(2023, 6, 30)
        )
        calculator._handle_BankAccountPayment(bap, "bap")
        assert bap.exchangeRate == Decimal("0.5")
        assert bap.grossRevenueB == Decimal("100")
        # TODO Check if we should just set 0 (field is mandatory)
        assert bap.grossRevenueA is None or bap.grossRevenueA == Decimal("0") # Type A not applicable
        assert bap.withHoldingTaxClaim is None or bap.withHoldingTaxClaim == Decimal("0") # Type B not applicable

    def test_handle_bank_account_payment_type_unknown_error(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        calculator._current_account_is_type_A = None
        bap = BankAccountPayment(amount=Decimal("100"), amountCurrency="USD", paymentDate=date(2023,1,1))
        with pytest.raises(ValueError) as excinfo:
            calculator._handle_BankAccountPayment(bap, "bap")
        assert "parent BankAccount has no country specified" in str(excinfo.value)

    def test_handle_liability_account_tax_value(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        latv = LiabilityAccountTaxValue(
            balance=Decimal("5000"), 
            balanceCurrency="EUR", 
            referenceDate=date(2023,12,31)
        )
        calculator._handle_LiabilityAccountTaxValue(latv, "latv")
        assert latv.exchangeRate == Decimal("0.5")
        assert latv.value == Decimal("2500")

    def test_handle_liability_account_payment(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        lap = LiabilityAccountPayment(
            amount=Decimal("100"), 
            amountCurrency="GBP", 
            paymentDate=date(2023, 5, 5)
        )
        calculator._handle_LiabilityAccountPayment(lap, "lap")
        assert lap.exchangeRate == Decimal("0.5")
        assert lap.grossRevenueB == Decimal("50") # 100 * 0.5
        assert not hasattr(lap, "grossRevenueA")

    def test_handle_security_ch(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        sec = Security(country="CH", securityName="dummy", positionId=1, currency="CHF", quotationType="PIECE", securityCategory="SHARE")
        calculator._handle_Security(sec, "sec")
        assert calculator._current_security_is_type_A is True

    def test_handle_security_foreign(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        sec = Security(country="US", securityName="dummy", positionId=1, currency="CHF", quotationType="PIECE", securityCategory="SHARE")
        calculator._handle_Security(sec, "sec")
        assert calculator._current_security_is_type_A is False

    def test_handle_security_tax_value_conversion(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        stv = SecurityTaxValue(
            balance=Decimal("2000"), 
            balanceCurrency="JPY", 
            referenceDate=date(2023,12,31),
            quotationType="PIECE",
            quantity=Decimal("10")
        )
        calculator._handle_SecurityTaxValue(stv, "stv")
        assert stv.exchangeRate == Decimal("0.5")
        assert stv.value == Decimal("1000")

    def test_handle_security_tax_value_no_value_sets_rate(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        stv = SecurityTaxValue(
            value=None, 
            balanceCurrency="EUR", 
            referenceDate=date(2023,12,31),
            quotationType="PIECE",
            quantity=Decimal("10")
        )
        calculator._handle_SecurityTaxValue(stv, "stv")
        assert stv.exchangeRate == Decimal("0.5")
        assert stv.value is None # Value remains None

    def test_handle_security_payment_no_op(self, minimal_tax_value_calculator_fill: MinimalTaxValueCalculator):
        calculator = minimal_tax_value_calculator_fill
        sp = SecurityPayment(amount=Decimal("50"), amountCurrency="USD", paymentDate=date(2023,1,1), quotationType="PIECE", quantity=Decimal("5"))
        # Call the handler - it should do nothing as per current implementation
        calculator._handle_SecurityPayment(sp, "sp")
        # Assert that fields are not set by this minimal calculator
        # assert not hasattr(sp, "exchangeRate")
        # assert not hasattr(sp, "grossRevenueA")
        # assert not hasattr(sp, "grossRevenueB")
