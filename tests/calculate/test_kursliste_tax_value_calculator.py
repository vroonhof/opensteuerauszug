from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.model.ech0196 import ISINType, Security, SecurityTaxValue, TaxStatement
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

        assert filtered_errors, "Expected verification errors when comparing against Kursliste"
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
    )
    calc._handle_Security(sec, "sec")
    stv = sec.taxValue
    calc._handle_SecurityTaxValue(stv, "sec.taxValue")
    assert stv.unitPrice == Decimal("255.5")
    assert stv.value == Decimal("127750")
    assert stv.exchangeRate == Decimal("1")
    assert stv.kursliste is True
