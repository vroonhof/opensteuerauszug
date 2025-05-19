import pytest
from opensteuerauszug.calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.model.ech0196 import TaxStatement
from opensteuerauszug.core.exchange_rate_provider import DummyExchangeRateProvider, ExchangeRateProvider
from tests.utils.samples import get_sample_files
from .known_issues import _known_issue

class TestKurslisteTaxValueCalculatorIntegration:
    @pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
    def test_run_in_verify_mode_no_errors(self, sample_file: str):
        """
        Tests that KurslisteTaxValueCalculator runs in VERIFY mode
        without producing errors when processing real-world sample TaxStatement XML files.
        """
        provider: ExchangeRateProvider = DummyExchangeRateProvider()
        calculator = KurslisteTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=provider)
        
        tax_statement_input = TaxStatement.from_xml_file(sample_file)

        processed_statement = calculator.calculate(tax_statement_input)

        filtered_errors = [e for e in calculator.errors if not _known_issue(e, tax_statement_input.institution)]

        if filtered_errors:
            error_messages = [str(e) for e in filtered_errors]
            error_details = "\n".join(error_messages)
            pytest.fail(f"KurslisteTaxValueCalculator produced errors for {sample_file} with {len(filtered_errors)} errors:\n{error_details}")
        
        assert processed_statement is tax_statement_input
