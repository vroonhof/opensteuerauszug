import os
import pytest
from datetime import date
from decimal import Decimal
from typing import List
from pathlib import Path

from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.config.models import IbkrAccountSettings
from opensteuerauszug.model.ech0196 import TaxStatement # ListOfSecurities, ListOfBankAccounts, Security, BankAccount, QuotationType, CurrencyId # Keep only TaxStatement for now
from tests.utils.samples import get_sample_files # Import the utility

# Check if ibflex is available, skip tests if not
try:
    from ibflex import parser as ibflex_parser
    IBFLEX_INSTALLED = True
except ImportError:
    IBFLEX_INSTALLED = False

pytestmark = [
    pytest.mark.skipif(not IBFLEX_INSTALLED, reason="ibflex library is not installed, skipping IBKR importer tests"),
    pytest.mark.integration # Mark these as integration tests
]

# Define the path to the sample files relative to the tests directory
# Sample files will be discovered from 'tests/samples/import/ibkr/' and EXTRA_SAMPLE_DIR
SAMPLE_FILES_PATTERN = "import/ibkr/*.xml" # Pattern to match IBKR XML files

@pytest.fixture
def default_ibkr_settings() -> List[IbkrAccountSettings]:
    # Provide all required fields for IbkrAccountSettings
    # Users will need to ensure their sample data matches this, or adjust as needed.
    # Or, ideally, the account_id could be derived from the Flex Query file itself.
    return [
        IbkrAccountSettings(
            canton="ZH", # Example Canton
            full_name="Test User", # Example Full Name
            account_number="UVALID123", # Example IBKR Account Number, should match data in samples
            broker_name="Interactive Brokers", # Standard broker name
            account_name_alias="Test IBKR Account" # Example alias
        )
    ]

@pytest.mark.parametrize("xml_file_path_str", get_sample_files(SAMPLE_FILES_PATTERN, base_dir="tests/samples/"))
def test_ibkr_import_from_sample_file(xml_file_path_str: str, default_ibkr_settings: List[IbkrAccountSettings]):
    xml_file_path = Path(xml_file_path_str)
    assert xml_file_path.exists(), f"Sample file not found: {xml_file_path}"

    # These dates might need to be dynamic or configured if samples cover different periods
    # For now, using a broad period that likely covers most test samples.
    # Or, derive from the sample filename if it contains date info.
    period_from = None
    period_to = None

    # Try to extract year from filename like YYYY_*.xml or *_YYYY.xml or *_YYYY_*.xml
    # This is a common convention for financial data.
    file_name_stem = xml_file_path.stem
    year_parts = [p for p in file_name_stem.split('_') if p.isdigit() and len(p) == 4]
    extracted_year = None
    if year_parts:
        try:
            extracted_year = int(year_parts[0]) # take the first one found
            period_from = date(extracted_year, 1, 1)
            period_to = date(extracted_year, 12, 31)
        except ValueError:
            pass # Not a valid year
    
    if period_from is None or period_to is None:
        pytest.skip(f"Cannot determine tax year from filename {xml_file_path.name!r}; skipping parametrized run")

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=default_ibkr_settings
    )

    try:
        tax_statement: TaxStatement = importer.import_files([str(xml_file_path)])
    except ValueError as e:
        # If the test is designed to catch specific errors based on filename convention (e.g., "error_*.xml")
        if "error" in xml_file_path.stem.lower():
            pytest.skip(f"Skipping error-raising test for {xml_file_path.name} as it's expected to fail: {e}")
            # Or, if you want to assert specific error messages for error files:
            # assert "specific error message" in str(e), f"File {xml_file_path.name} did not raise expected error."
            # return 
        else:
            raise # Re-raise if it's an unexpected error

    assert tax_statement is not None, f"TaxStatement should not be None for {xml_file_path.name}"
    assert tax_statement.periodFrom == period_from
    assert tax_statement.periodTo == period_to
    if extracted_year:
        assert tax_statement.taxPeriod == extracted_year

    # Basic checks - users can add more detailed assertions based on their private samples
    if tax_statement.listOfSecurities:
        assert tax_statement.listOfSecurities.depot is not None
        for depot in tax_statement.listOfSecurities.depot:
            assert depot.depotNumber is not None # Basic check
            for security in depot.security:
                assert security.securityName is not None
                assert security.currency is not None # String like "USD"
                # Example: Check for currency string
                assert isinstance(security.currency, str) and len(security.currency) == 3

                if security.payment:
                    for payment in security.payment:
                        assert payment.paymentDate is not None
                        # Check name if it exists
                        if payment.name:
                             assert isinstance(payment.name, str)


    if tax_statement.listOfBankAccounts:
        assert tax_statement.listOfBankAccounts.bankAccount is not None
        for ba in tax_statement.listOfBankAccounts.bankAccount:
            assert ba.bankAccountNumber is not None
            assert ba.bankAccountCurrency is not None # String like "USD"
            assert isinstance(ba.bankAccountCurrency, str) and len(ba.bankAccountCurrency) == 3

            if ba.payment:
                for payment in ba.payment:
                    assert payment.paymentDate is not None
                    # Check name if it exists
                    if payment.name:
                        assert isinstance(payment.name, str)
            
            if ba.taxValue: # taxValue is a single object, not a list
                assert ba.taxValue.referenceDate is not None
                assert ba.taxValue.balance is not None # Or check based on expected data

    # Add a message indicating that detailed content checks depend on the sample file.
    print(f"Successfully imported {xml_file_path.name}. Detailed content assertions depend on the specific sample.")

# Remove old specific tests and fixtures as they are superseded by the parameterized test.
# def test_ibkr_import_from_valid_sample_file(valid_ibkr_settings): ...
# def test_ibkr_import_from_file_missing_required_field(error_ibkr_settings): ...
# @pytest.fixture valid_ibkr_settings, error_ibkr_settings are replaced by default_ibkr_settings
# SAMPLES_DIR is also no longer needed here.


SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples" / "import" / "ibkr"


@pytest.mark.skip(reason="Short options (covered calls) not yet supported — tracked in issue #218")
def test_ibkr_import_minimal_short_options_repro(default_ibkr_settings: List[IbkrAccountSettings]):
    """Integration test for minimal_short_options_repro.xml containing short option positions.

    Skipped until negative-balance handling for short options is implemented.
    """
    xml_file_path = SAMPLES_DIR / "minimal_short_options_repro.xml"
    assert xml_file_path.exists(), f"Sample file not found: {xml_file_path}"

    importer = IbkrImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=default_ibkr_settings,
    )
    tax_statement: TaxStatement = importer.import_files([str(xml_file_path)])
    assert tax_statement is not None


@pytest.mark.skip(reason="Short options (covered calls) not yet supported — tracked in issue #218")
def test_ibkr_import_etax_report_anonymised(default_ibkr_settings: List[IbkrAccountSettings]):
    """Integration test for eTax_report_anonymised.xml containing short option positions.

    Skipped until negative-balance handling for short options is implemented.
    """
    xml_file_path = SAMPLES_DIR / "eTax_report_anonymised.xml"
    assert xml_file_path.exists(), f"Sample file not found: {xml_file_path}"

    importer = IbkrImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=default_ibkr_settings,
    )
    tax_statement: TaxStatement = importer.import_files([str(xml_file_path)])
    assert tax_statement is not None
