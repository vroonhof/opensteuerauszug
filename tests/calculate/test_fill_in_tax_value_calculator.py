import pytest

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.fill_in_tax_value_calculator import FillInTaxValueCalculator
from opensteuerauszug.core.exchange_rate_provider import (
    DummyExchangeRateProvider,
    ExchangeRateProvider,
)
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.model.ech0196 import TaxStatement
from tests.utils.samples import get_sample_files

from .known_issues import _known_issue


class TestFillInTaxValueCalculatorIntegration:
    @pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
    def test_run_in_verify_mode_no_errors(
        self, sample_file: str, exchange_rate_provider: KurslisteExchangeRateProvider
    ):
        """
        Tests that FillInTaxValueCalculator runs in VERIFY mode
        without producing errors when processing real-world sample TaxStatement XML files.
        Uses the real exchange rate provider from kursliste.
        """
        calculator = FillInTaxValueCalculator(
            mode=CalculationMode.VERIFY, exchange_rate_provider=exchange_rate_provider
        )

        tax_statement_input = TaxStatement.from_xml_file(sample_file)

        processed_statement = calculator.calculate(tax_statement_input)

        filtered_errors = [
            e for e in calculator.errors if not _known_issue(e, tax_statement_input.institution)
        ]

        assert filtered_errors == [], "Unexpected verification errors"
        assert processed_statement is tax_statement_input
