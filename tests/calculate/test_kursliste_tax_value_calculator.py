from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Optional

import pytest

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from opensteuerauszug.core.flag_override_provider import FlagOverrideProvider
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.core.kursliste_accessor import KurslisteAccessor
from opensteuerauszug.model.ech0196 import (
    ISINType,
    Depot,
    DepotNumber,
    ListOfSecurities,
    Security,
    SecurityTaxValue,
    SecurityStock,
    TaxStatement,
    ValorNumber,
)
from opensteuerauszug.model.critical_warning import CriticalWarningCategory
from opensteuerauszug.model.kursliste import (
    Fund,
    Kursliste,
    Legend,
    PaymentFund,
    PaymentShare,
    PaymentTypeESTV,
    Share,
    SecurityGroupESTV,
)
from tests.utils.samples import get_sample_files

from .known_issues import _known_issue
from .conftest import get_tax_year_for_sample, ensure_kursliste_year_available


class MockFlagOverrideProvider(FlagOverrideProvider):
    def __init__(self):
        self._overrides: Dict[str, str] = {}

    def get_flag(self, isin: str) -> Optional[str]:
        return self._overrides.get(isin)

    def set_flag(self, isin: str, flag: str):
        self._overrides[isin] = flag


class TestKurslisteTaxValueCalculatorIntegration:
    @pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
    def test_run_in_verify_mode_no_errors(
        self,
        sample_file: str,
        exchange_rate_provider: KurslisteExchangeRateProvider,
        kursliste_manager,
    ):
        """
        Tests that KurslisteTaxValueCalculator runs in VERIFY mode
        without producing errors when processing real-world sample TaxStatement XML files.
        Uses the real exchange rate provider from kursliste.
        """
        # Ensure the required kursliste year is available
        required_year = get_tax_year_for_sample(sample_file)
        ensure_kursliste_year_available(kursliste_manager, required_year, sample_file)

        flag_override_provider = MockFlagOverrideProvider()
        if "Truewealth.xml" in sample_file:
            # For this specific test case, we know the sample file does not expect DA-1 calculation
            # for this ISIN, so we provide the correct flag to trigger it.
            flag_override_provider.set_flag("US9219377937", "Q")

        calculator = KurslisteTaxValueCalculator(
            mode=CalculationMode.VERIFY,
            exchange_rate_provider=exchange_rate_provider,
            flag_override_provider=flag_override_provider,
        )

        tax_statement_input = TaxStatement.from_xml_file(sample_file)

        processed_statement = calculator.calculate(tax_statement_input)

        filtered_errors = [
            e for e in calculator.errors if not _known_issue(e, tax_statement_input.institution)
        ]

        # Check if any errors were found during verification
        if filtered_errors:
            error_messages = [str(e) for e in filtered_errors]
            error_details = "\n".join(error_messages)
            pytest.fail(
                f"Unexpected validation errors for {sample_file} with {len(filtered_errors)} errors:\n{error_details}"
            )
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
    assert stv is not None
    calc._handle_SecurityTaxValue(stv, "sec.taxValue")
    assert stv.unitPrice == Decimal("255.5")
    assert stv.value == Decimal("127750")
    assert stv.exchangeRate == Decimal("1")
    assert stv.kursliste is True
    assert stv.balanceCurrency == "CHF"


def test_handle_security_tax_value_sets_undefined_when_not_in_kursliste(kursliste_manager):
    """Test that SecurityTaxValue.undefined is set to True when security is not found in Kursliste."""
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Create a security with a non-existent ISIN that won't be found in Kursliste
    sec = Security(
        country="US",
        securityName="Non-Existent Security",
        positionId=1,
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US9999999999"),  # Invalid ISIN that won't exist in Kursliste
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
    stv = sec.taxValue
    assert stv is not None

    # Call _handle_SecurityTaxValue which should set undefined=True
    # since the security was not found in Kursliste
    calc._handle_SecurityTaxValue(stv, "sec.taxValue")

    # Verify that undefined flag is set to True
    assert stv.undefined is True
    # kursliste flag should not be set since security wasn't in Kursliste
    assert stv.kursliste is not True


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
    # Reality vs spec: All three fields should be set when at least one is set
    assert payment.grossRevenueA == Decimal("0")
    assert payment.grossRevenueB == Decimal("138.400")
    assert payment.withHoldingTaxClaim == Decimal("0")


def test_compute_payments_skips_stock_split_payment():
    split_date = date(2025, 6, 18)
    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="USD",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("4"),
            )
        ],
    )
    share = Share(
        id=1,
        isin="US45841N1072",
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="Interactive Brokers Group, Inc.",
        institutionId=1,
        institutionName="Interactive Brokers Group, Inc.",
        country="US",
        currency="USD",
        nominalValue=Decimal("0.01"),
        payment=[payment],
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    security = Security(
        country="US",
        securityName="Interactive Brokers Group, Inc.",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US45841N1072"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("8"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("2"),
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("6"),
                balanceCurrency="CHF",
            ),
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("U1234567"), security=[security])]
        ),
    )

    # Expect no exception because the split is represented as a stock mutation.
    calc.calculate(statement)

    assert security.payment == []
    assert calc.errors == []


def test_compute_payments_stock_split_requires_mutation():
    split_date = date(2025, 6, 18)
    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="USD",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("4"),
            )
        ],
    )
    share = Share(
        id=1,
        isin="US45841N1072",
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="Interactive Brokers Group, Inc.",
        institutionId=1,
        institutionName="Interactive Brokers Group, Inc.",
        country="US",
        currency="USD",
        nominalValue=Decimal("0.01"),
        payment=[payment],
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    security = Security(
        country="US",
        securityName="Interactive Brokers Group, Inc.",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US45841N1072"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("8"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("2"),
                balanceCurrency="CHF",
            )
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("U1234567"), security=[security])]
        ),
    )

    result = calc.calculate(statement)
    split_warnings = [
        w for w in result.critical_warnings
        if w.category == CriticalWarningCategory.STOCK_SPLIT_MISMATCH
    ]
    assert len(split_warnings) == 1
    assert "Missing stock split mutation" in split_warnings[0].message
    assert split_warnings[0].identifier == "US45841N1072"


def test_cross_isin_stock_split_succeeds_with_correct_mutations():
    """When a stock split changes the ISIN (valorNumberNew is set), the validator
    should accept a negative mutation on the old security and a positive mutation
    on the new security, matching the split ratio."""
    split_date = date(2025, 4, 16)
    old_isin = "CH0011029946"
    new_valor = 143159891
    new_isin = "CH1431598916"

    # Kursliste payment on the OLD security with a split legend referencing the new valor
    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="CHF",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("10"),
                valorNumberNew=new_valor,
            )
        ],
    )
    share = Share(
        id=1,
        isin=old_isin,
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="INFICON HOLDING AG-REG",
        institutionId=1,
        institutionName="INFICON HOLDING AG",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("5"),
        payment=[payment],
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    # Old security: held 5 shares, removed all on split date
    old_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(old_isin),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("0"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("5"),
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("-5"),
                balanceCurrency="CHF",
            ),
        ],
    )

    # New security: received 50 shares on split date
    new_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=2,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(new_isin),
        valorNumber=ValorNumber(new_valor),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("50"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("50"),
                balanceCurrency="CHF",
            ),
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("U1234567"),
                    security=[old_security, new_security],
                )
            ]
        ),
    )

    calc.calculate(statement)

    assert old_security.payment == []
    assert calc.errors == []


def test_cross_isin_stock_split_error_when_removal_mutation_missing():
    """When a cross-ISIN split occurs but the old security has no removal mutation,
    the validator should raise a descriptive error."""
    split_date = date(2025, 4, 16)
    old_isin = "CH0011029946"
    new_valor = 143159891
    new_isin = "CH1431598916"

    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="CHF",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("10"),
                valorNumberNew=new_valor,
            )
        ],
    )
    share = Share(
        id=1,
        isin=old_isin,
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="INFICON HOLDING AG-REG",
        institutionId=1,
        institutionName="INFICON HOLDING AG",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("5"),
        payment=[payment],
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    # Old security: held 5 shares, but NO removal mutation
    old_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(old_isin),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("5"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("5"),
                balanceCurrency="CHF",
            ),
        ],
    )

    # New security exists with the correct mutation
    new_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=2,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(new_isin),
        valorNumber=ValorNumber(new_valor),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("50"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("50"),
                balanceCurrency="CHF",
            ),
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("U1234567"),
                    security=[old_security, new_security],
                )
            ]
        ),
    )

    result = calc.calculate(statement)
    split_warnings = [
        w for w in result.critical_warnings
        if w.category == CriticalWarningCategory.STOCK_SPLIT_MISMATCH
    ]
    assert len(split_warnings) == 1
    assert "expected a removal mutation of -5" in split_warnings[0].message
    assert split_warnings[0].identifier == old_isin


def test_cross_isin_stock_split_resolves_new_security_by_kursliste_isin_when_valor_not_enriched_yet():
    """Cross-ISIN validation should resolve the target security via Kursliste ISIN
    if the statement security exists but has not had its valorNumber enriched yet."""
    split_date = date(2025, 4, 16)
    old_isin = "CH0011029946"
    new_valor = 143159891
    new_isin = "CH1431598916"

    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="CHF",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("10"),
                valorNumberNew=new_valor,
            )
        ],
    )
    old_share = Share(
        id=1,
        isin=old_isin,
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="INFICON HOLDING AG-REG",
        institutionId=1,
        institutionName="INFICON HOLDING AG",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("5"),
        payment=[payment],
    )
    new_share = Share(
        id=2,
        isin=new_isin,
        valorNumber=new_valor,
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="INFICON HOLDING AG-REG",
        institutionId=1,
        institutionName="INFICON HOLDING AG",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("5"),
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[old_share, new_share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    old_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(old_isin),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("0"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("5"),
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("-5"),
                balanceCurrency="CHF",
            ),
        ],
    )

    # New security exists but does not have valorNumber yet (would be enriched later).
    new_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=2,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(new_isin),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("50"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("50"),
                balanceCurrency="CHF",
            ),
        ],
    )

    # Order old security first, new security second to reproduce enrichment-order issue.
    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("U1234567"),
                    security=[old_security, new_security],
                )
            ]
        ),
    )

    calc.calculate(statement)

    assert old_security.payment == []
    assert calc.errors == []


def test_cross_isin_stock_split_error_when_new_security_missing():
    """When a cross-ISIN split references a valorNumberNew that does not
    correspond to any security in the statement, the validator should raise."""
    split_date = date(2025, 4, 16)
    old_isin = "CH0011029946"
    new_valor = 143159891

    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="CHF",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("10"),
                valorNumberNew=new_valor,
            )
        ],
    )
    share = Share(
        id=1,
        isin=old_isin,
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="INFICON HOLDING AG-REG",
        institutionId=1,
        institutionName="INFICON HOLDING AG",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("5"),
        payment=[payment],
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    # Old security: correctly has removal mutation
    old_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(old_isin),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("0"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("5"),
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("-5"),
                balanceCurrency="CHF",
            ),
        ],
    )

    # No new security at all in the statement!
    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("U1234567"),
                    security=[old_security],
                )
            ]
        ),
    )

    result = calc.calculate(statement)
    split_warnings = [
        w for w in result.critical_warnings
        if w.category == CriticalWarningCategory.STOCK_SPLIT_MISMATCH
    ]
    assert len(split_warnings) == 1
    assert "no security with that valor number was found" in split_warnings[0].message
    assert split_warnings[0].identifier == old_isin


def test_cross_isin_stock_split_error_when_new_security_addition_wrong():
    """When a cross-ISIN split's new security has a mutation but with the wrong
    quantity, the validator should raise with a descriptive message."""
    split_date = date(2025, 4, 16)
    old_isin = "CH0011029946"
    new_valor = 143159891
    new_isin = "CH1431598916"

    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="CHF",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("10"),
                valorNumberNew=new_valor,
            )
        ],
    )
    share = Share(
        id=1,
        isin=old_isin,
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="INFICON HOLDING AG-REG",
        institutionId=1,
        institutionName="INFICON HOLDING AG",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("5"),
        payment=[payment],
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    # Old security: correct removal
    old_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(old_isin),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("0"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("5"),
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("-5"),
                balanceCurrency="CHF",
            ),
        ],
    )

    # New security: wrong addition quantity (40 instead of 50)
    new_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=2,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(new_isin),
        valorNumber=ValorNumber(new_valor),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("40"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("40"),
                balanceCurrency="CHF",
            ),
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("U1234567"),
                    security=[old_security, new_security],
                )
            ]
        ),
    )

    result = calc.calculate(statement)
    split_warnings = [
        w for w in result.critical_warnings
        if w.category == CriticalWarningCategory.STOCK_SPLIT_MISMATCH
    ]
    assert len(split_warnings) == 1
    assert "expected an addition of 50" in split_warnings[0].message
    assert split_warnings[0].identifier == old_isin


def test_cross_isin_stock_split_error_when_new_security_has_no_mutations():
    """When a cross-ISIN split's new security exists but has no mutations on the
    split date, the validator should raise."""
    split_date = date(2025, 4, 16)
    old_isin = "CH0011029946"
    new_valor = 143159891
    new_isin = "CH1431598916"

    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="CHF",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("10"),
                valorNumberNew=new_valor,
            )
        ],
    )
    share = Share(
        id=1,
        isin=old_isin,
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="INFICON HOLDING AG-REG",
        institutionId=1,
        institutionName="INFICON HOLDING AG",
        country="CH",
        currency="CHF",
        nominalValue=Decimal("5"),
        payment=[payment],
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    # Old security: correct removal
    old_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(old_isin),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("0"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("5"),
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("-5"),
                balanceCurrency="CHF",
            ),
        ],
    )

    # New security exists but has NO mutations on the split date
    new_security = Security(
        country="CH",
        securityName="INFICON HOLDING AG-REG",
        positionId=2,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(new_isin),
        valorNumber=ValorNumber(new_valor),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("50"),
            balanceCurrency="CHF",
        ),
        stock=[],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("U1234567"),
                    security=[old_security, new_security],
                )
            ]
        ),
    )

    result = calc.calculate(statement)
    split_warnings = [
        w for w in result.critical_warnings
        if w.category == CriticalWarningCategory.STOCK_SPLIT_MISMATCH
    ]
    assert len(split_warnings) == 1
    assert "has no mutations on the split date" in split_warnings[0].message
    assert split_warnings[0].identifier == old_isin


def test_same_isin_stock_split_error_message_is_descriptive():
    """Verify that the same-ISIN split error messages include quantities and ratios."""
    split_date = date(2025, 6, 18)
    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="USD",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("4"),
            )
        ],
    )
    share = Share(
        id=1,
        isin="US45841N1072",
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="Interactive Brokers Group, Inc.",
        institutionId=1,
        institutionName="Interactive Brokers Group, Inc.",
        country="US",
        currency="USD",
        nominalValue=Decimal("0.01"),
        payment=[payment],
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    security = Security(
        country="US",
        securityName="Interactive Brokers Group, Inc.",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US45841N1072"),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("8"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("2"),
                balanceCurrency="CHF",
            ),
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=Decimal("3"),  # Wrong: should be 6
                balanceCurrency="CHF",
            ),
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("U1234567"), security=[security])]
        ),
    )

    result = calc.calculate(statement)
    split_warnings = [
        w for w in result.critical_warnings
        if w.category == CriticalWarningCategory.STOCK_SPLIT_MISMATCH
    ]
    assert len(split_warnings) == 1
    assert "Stock split ratio mismatch" in split_warnings[0].message
    assert "expected a mutation of 6" in split_warnings[0].message
    assert "split ratio 4:1" in split_warnings[0].message
    assert "pre-split position 2" in split_warnings[0].message
    assert split_warnings[0].identifier == "US45841N1072"


def test_same_valor_number_new_treated_as_same_isin_split():
    """When valorNumberNew in the Kursliste split legend equals the current
    security's valor number (no actual ISIN change), the split must be
    validated as a same-ISIN split accepting a single net-quantity mutation.

    This covers IBKR's net-quantity format where a 4-for-1 forward split on
    2.7932 shares is reported as a single corporate action with quantity=8.3796
    (the net increase) rather than separate removal and addition entries."""
    split_date = date(2025, 6, 18)
    valor = 2812198
    isin = "US45841N1072"

    payment = PaymentShare(
        id=1,
        paymentDate=split_date,
        currency="USD",
        paymentValue=Decimal("0"),
        paymentValueCHF=Decimal("0"),
        paymentType=PaymentTypeESTV.OTHER_BENEFIT,
        taxEvent=True,
        exDate=split_date,
        legend=[
            Legend(
                id=1,
                effectiveDate=split_date,
                exchangeRatioPresent=Decimal("1"),
                exchangeRatioNew=Decimal("4"),
                valorNumberNew=valor,  # same valor as the security itself
            )
        ],
    )
    share = Share(
        id=1,
        isin=isin,
        securityGroup=SecurityGroupESTV.SHARE,
        securityName="Interactive Brokers Group, Inc.",
        institutionId=1,
        institutionName="Interactive Brokers Group, Inc.",
        country="US",
        currency="USD",
        nominalValue=Decimal("0.01"),
        payment=[payment],
    )
    kursliste = Kursliste(
        version="2.2.0.0",
        creationDate=datetime(2025, 1, 1),
        year=2025,
        shares=[share],
    )
    kursliste_manager = KurslisteManager()
    kursliste_manager.kurslisten[2025] = KurslisteAccessor([kursliste], 2025)

    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )

    pre_split_qty = Decimal("2.7932")
    net_increase = pre_split_qty * Decimal("3")  # (4-1)/1 * pre_split_qty = 8.3796

    security = Security(
        country="US",
        securityName="Interactive Brokers Group, Inc.",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType(isin),
        valorNumber=ValorNumber(valor),
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=pre_split_qty * Decimal("4"),
            balanceCurrency="CHF",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=pre_split_qty,
                balanceCurrency="CHF",
            ),
            # IBKR reports the net increase only (not a removal + addition pair)
            SecurityStock(
                referenceDate=split_date,
                mutation=True,
                quotationType="PIECE",
                quantity=net_increase,
                balanceCurrency="CHF",
            ),
        ],
    )

    statement = TaxStatement(
        minorVersion=2,
        taxPeriod=2025,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("U1234567"), security=[security])]
        ),
    )

    # Should succeed without errors: same valorNumberNew is treated as same-ISIN split
    calc.calculate(statement)
    assert calc.errors == []


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
    # Reality vs spec: All three fields should be set when at least one is set
    assert first.grossRevenueA == Decimal("0")
    assert first.grossRevenueB == Decimal("82.45900")
    assert first.withHoldingTaxClaim == Decimal("0")


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
    # Use sign "(I)" which means "taxable earnings not yet determined" - appropriate for undefined payments
    kl_sec = Share(
        id=1,
        securityGroup=SecurityGroupESTV.SHARE,
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
                sign="(I)",
                gratis=True,
                paymentType=PaymentTypeESTV.GRATIS,
            )
        ],
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
    assert payment.sign == "(I)"
    assert payment.gratis is True


def test_compute_payments_withholding_tax_scenario(kursliste_manager):
    """
    Test that payments with withholding tax correctly set all three fields:
    grossRevenueA, grossRevenueB, and withHoldingTaxClaim.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Mock a Kursliste security with a payment that has withholding tax
    kl_sec = Share(
        id=1,
        securityGroup=SecurityGroupESTV.SHARE,
        country="CH",
        currency="CHF",
        institutionId=123,
        institutionName="Test Bank",
        payment=[
            PaymentShare(
                id=101,
                paymentDate=date(2024, 5, 10),
                currency="CHF",
                paymentValue=Decimal("2.50"),  # 2.50 CHF per share
                paymentValueCHF=Decimal("2.50"),  # Same in CHF
                exchangeRate=Decimal("1.0"),
                withHoldingTax=True,  # This triggers grossRevenueA and withHoldingTaxClaim
            )
        ],
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

    # Reality vs spec: All three fields should be set when withholding tax applies
    # grossRevenueA should contain the CHF amount (250.00)
    # grossRevenueB should be zero
    # withHoldingTaxClaim should be 35% of grossRevenueA (87.50)
    assert payment.grossRevenueA == Decimal("250.00")  # 100 shares * 2.50 CHF
    assert payment.grossRevenueB == Decimal("0")
    assert payment.withHoldingTaxClaim == Decimal("87.50")  # 35% of 250.00


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


def test_compute_payments_capital_gain_scenario(kursliste_manager):
    """
    Test that payments marked as capital gains are ignored.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Mock a Kursliste security with a payment that is a capital gain
    kl_sec = Fund(
        id=1,
        securityGroup=SecurityGroupESTV.FUND,
        country="CH",
        currency="CHF",
        institutionId=123,
        institutionName="Test Bank",
        nominalValue=Decimal("1"),
        payment=[
            PaymentFund(
                id=101,
                paymentDate=date(2024, 5, 10),
                currency="CHF",
                paymentValue=Decimal("2.50"),
                paymentValueCHF=Decimal("2.50"),
                exchangeRate=Decimal("1.0"),
                capitalGain=True,
            )
        ],
    )

    sec = Security(
        country="CH",
        securityName="Test Security",
        positionId=1,
        currency="CHF",
        quotationType="PIECE",
        securityCategory="FUND",
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
    assert len(sec.payment) == 0


def test_compute_payments_unknown_sign_type_raises_error(kursliste_manager):
    """
    Test that payments with unknown sign types raise a ValueError.
    This ensures we fail fast on sign types we haven't explicitly handled.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Mock a Kursliste security with a payment that has an unknown sign type
    kl_sec = Share(
        id=1,
        securityGroup=SecurityGroupESTV.SHARE,
        country="CH",
        currency="CHF",
        institutionId=123,
        institutionName="Test Bank",
        payment=[
            PaymentShare(
                id=101,
                paymentDate=date(2024, 5, 10),
                currency="CHF",
                paymentValue=Decimal("2.50"),
                paymentValueCHF=Decimal("2.50"),
                exchangeRate=Decimal("1.0"),
                sign="XXX",  # Unknown sign type
            )
        ],
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

    calc._current_kursliste_security = kl_sec

    with pytest.raises(ValueError, match="Unknown sign type 'XXX'"):
        calc.computePayments(sec, "sec")


def test_compute_payments_skips_kep_payments(kursliste_manager):
    """
    Test that payments with sign 'KEP' (return of capital contributions) are
    skipped as they are not taxable for private investors.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Mock a Kursliste security with a KEP payment
    kl_sec = Share(
        id=1,
        securityGroup=SecurityGroupESTV.SHARE,
        country="CH",
        currency="CHF",
        institutionId=123,
        institutionName="Test Bank",
        payment=[
            PaymentShare(
                id=101,
                paymentDate=date(2024, 5, 10),
                currency="CHF",
                paymentValue=Decimal("2.50"),
                paymentValueCHF=Decimal("2.50"),
                exchangeRate=Decimal("1.0"),
                sign="KEP",  # Return of capital - non-taxable
            )
        ],
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

    calc._current_kursliste_security = kl_sec

    calc.computePayments(sec, "sec")

    # KEP payments should be skipped entirely
    assert len(sec.payment) == 0


def test_compute_payments_skips_capital_gain_sign_payments(kursliste_manager):
    """
    Test that payments with sign '(KG)' (capital gain) are skipped
    as they are not taxable for private investors.
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Mock a Kursliste security with a (KG) payment
    kl_sec = Share(
        id=1,
        securityGroup=SecurityGroupESTV.SHARE,
        country="CH",
        currency="CHF",
        institutionId=123,
        institutionName="Test Bank",
        payment=[
            PaymentShare(
                id=101,
                paymentDate=date(2024, 5, 10),
                currency="CHF",
                paymentValue=Decimal("2.50"),
                paymentValueCHF=Decimal("2.50"),
                exchangeRate=Decimal("1.0"),
                sign="(KG)",  # Capital gain - non-taxable
            )
        ],
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

    calc._current_kursliste_security = kl_sec

    calc.computePayments(sec, "sec")

    # (KG) payments should be skipped entirely
    assert len(sec.payment) == 0


def test_compute_payments_sets_additional_withholding_tax_usa(kursliste_manager):
    """
    Test that for a US security in the Kursliste, the generated SecurityPayment objects
    have additionalWithHoldingTaxUSA explicitly set to Decimal("0").
    """
    provider = KurslisteExchangeRateProvider(kursliste_manager)
    calc = KurslisteTaxValueCalculator(mode=CalculationMode.FILL, exchange_rate_provider=provider)

    # Mock a US Kursliste security
    kl_sec = Share(
        id=1,
        securityGroup=SecurityGroupESTV.SHARE,
        country="US",
        currency="USD",
        institutionId=123,
        institutionName="Test US Bank",
        payment=[
            PaymentShare(
                id=101,
                paymentDate=date(2024, 5, 10),
                currency="USD",
                paymentValue=Decimal("2.50"),
                paymentValueCHF=Decimal("2.20"),
                exchangeRate=Decimal("0.88"),
                withHoldingTax=False,
            )
        ],
    )

    sec = Security(
        country="US",
        securityName="Test US Security",
        positionId=1,
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        isin=ISINType("US0000000001"),
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

    # Manually set the Kursliste security for the calculator
    calc._current_kursliste_security = kl_sec

    # Run the payment computation
    calc.computePayments(sec, "sec")

    # Assertions
    assert len(sec.payment) == 1
    payment = sec.payment[0]

    # Assert additionalWithHoldingTaxUSA is set to 0
    assert payment.additionalWithHoldingTaxUSA == Decimal("0")
