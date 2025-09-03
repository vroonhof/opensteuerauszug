import pytest
from typing import Dict, Optional

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.fill_in_tax_value_calculator import FillInTaxValueCalculator
from opensteuerauszug.core.exchange_rate_provider import (
    DummyExchangeRateProvider,
    ExchangeRateProvider,
)
from opensteuerauszug.core.flag_override_provider import FlagOverrideProvider
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.model.ech0196 import TaxStatement
from tests.utils.samples import get_sample_files

from .known_issues import _known_issue


class MockFlagOverrideProvider(FlagOverrideProvider):
    def __init__(self):
        self._overrides: Dict[str, str] = {}

    def get_flag(self, isin: str) -> Optional[str]:
        return self._overrides.get(isin)

    def set_flag(self, isin: str, flag: str):
        self._overrides[isin] = flag


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
        flag_override_provider = MockFlagOverrideProvider()
        if "Truewealth.xml" in sample_file:
            # For this specific test case, we know the sample file does not expect DA-1 calculation
            # for this ISIN, so we provide the correct flag to trigger it.
            flag_override_provider.set_flag("US9219377937", "Q")

        calculator = FillInTaxValueCalculator(
            mode=CalculationMode.VERIFY,
            exchange_rate_provider=exchange_rate_provider,
            flag_override_provider=flag_override_provider,
        )

        tax_statement_input = TaxStatement.from_xml_file(sample_file)

        processed_statement = calculator.calculate(tax_statement_input)

        filtered_errors = [
            e for e in calculator.errors if not _known_issue(e, tax_statement_input.institution)
        ]

        assert filtered_errors == [], "Unexpected verification errors"
        assert processed_statement is tax_statement_input
