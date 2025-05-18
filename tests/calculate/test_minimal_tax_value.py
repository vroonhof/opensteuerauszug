import pytest
from opensteuerauszug.calculate.minimal_tax_value import MinimalTaxValueCalculator
from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.model.ech0196 import TaxStatement
from opensteuerauszug.core.exchange_rate_provider import DummyExchangeRateProvider, ExchangeRateProvider
from datetime import datetime
from tests.utils.samples import get_sample_files

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
    def test_run_in_verify_mode_no_errors(self, sample_file: str):
        """
        Tests that MinimalTaxValueCalculator runs in VERIFY mode
        without producing errors when processing real-world sample TaxStatement XML files.
        """
        provider: ExchangeRateProvider = DummyExchangeRateProvider()
        calculator = MinimalTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=provider)
        
        # Load TaxStatement from the sample XML file
        tax_statement_input = TaxStatement.from_xml_file(sample_file)

        # Process the statement.
        processed_statement = calculator.calculate(tax_statement_input)

        # Check if any errors were found during verification
        if calculator.errors:
            error_messages = [str(e) for e in calculator.errors]
            error_details = "\n".join(error_messages)
            pytest.fail(f"MinimalTaxValueCalculator produced errors for {sample_file} with {len(calculator.errors)} errors:\n{error_details}")
        
        # Assert that the statement itself is returned
        assert processed_statement is tax_statement_input
