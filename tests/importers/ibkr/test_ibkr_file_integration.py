import os
import pytest
from datetime import date
from decimal import Decimal
from typing import List
from pathlib import Path

from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.config.models import IbkrAccountSettings
from opensteuerauszug.model.ech0196 import TaxStatement, ListOfSecurities, ListOfBankAccounts, Security, BankAccount, QuotationType, CurrencyId

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
# Assuming the tests are run from the project root or similar context where 'tests/...' is valid
SAMPLES_DIR = Path("tests/samples/import/ibkr/")

@pytest.fixture
def valid_ibkr_settings() -> List[IbkrAccountSettings]:
    return [IbkrAccountSettings(account_id="UVALID123", name="Test IBKR Valid Account")]

@pytest.fixture
def error_ibkr_settings() -> List[IbkrAccountSettings]:
    return [IbkrAccountSettings(account_id="UERROR456", name="Test IBKR Error Account")]


def test_ibkr_import_from_valid_sample_file(valid_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)
    xml_file_path = SAMPLES_DIR / "sample_1_simple_trade_cash.xml"

    assert xml_file_path.exists(), f"Sample file not found: {xml_file_path}"

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=valid_ibkr_settings
    )

    tax_statement = importer.import_files([str(xml_file_path)])
    assert tax_statement is not None
    assert tax_statement.periodFrom == period_from
    assert tax_statement.periodTo == period_to
    assert tax_statement.taxPeriod == 2023

    # --- Check Securities ---
    assert tax_statement.listOfSecurities is not None
    assert len(tax_statement.listOfSecurities.depot) == 1
    depot = tax_statement.listOfSecurities.depot[0]
    assert depot.depotNumber == "UVALID123"
    assert len(depot.security) == 2 # IBM and TSLA

    # IBM Security
    ibm_sec = next((s for s in depot.security if s.securityName == "INTL BUSINESS MACHINES CORP (IBM)"), None)
    assert ibm_sec is not None
    assert ibm_sec.isin == "US4592001014"
    assert ibm_sec.currency == CurrencyId.USD
    assert len(ibm_sec.stock) == 2 # 1 trade (mutation) + 1 open position (balance)
    assert ibm_sec.stock[0].mutation is True # Trade
    assert ibm_sec.stock[0].quantity == Decimal("20")
    assert ibm_sec.stock[1].mutation is False # Open Position Balance
    assert ibm_sec.stock[1].quantity == Decimal("20")
    assert ibm_sec.stock[1].referenceDate == date(2023,12,31)

    assert len(ibm_sec.payment) == 1 # 1 for the BUY trade (Dividend goes to BankAccount)
    buy_payment_ibm = next((p for p in ibm_sec.payment if "Trade:" in p.name and "IBM" in p.name), None)
    assert buy_payment_ibm is not None
    assert buy_payment_ibm.amount == Decimal("-2801.50") # netCash for BUY

    # TSLA Security
    tsla_sec = next((s for s in depot.security if s.securityName == "TESLA INC (TSLA)"), None)
    assert tsla_sec is not None
    assert tsla_sec.isin == "US88160R1014"
    assert len(tsla_sec.stock) == 1 # 1 trade (mutation)
    assert tsla_sec.stock[0].quantity == Decimal("-10") # SELL
    assert len(tsla_sec.payment) == 1
    assert tsla_sec.payment[0].amount == Decimal("2499.00") # netCash for SELL

    # --- Check Bank Accounts ---
    assert tax_statement.listOfBankAccounts is not None
    assert len(tax_statement.listOfBankAccounts.bankAccount) == 1

    usd_account = next((ba for ba in tax_statement.listOfBankAccounts.bankAccount if ba.bankAccountCurrency == CurrencyId.USD), None)
    assert usd_account is not None
    assert usd_account.bankAccountNumber == "UVALID123-USD"

    assert len(usd_account.payment) == 2 # Funding + IBM Dividend
    funding_payment = next((p for p in usd_account.payment if p.name == "Funding"), None)
    assert funding_payment is not None
    assert funding_payment.amount == Decimal("10000.00")

    ibm_dividend_payment = next((p for p in usd_account.payment if p.name == "IBM Dividend"), None)
    assert ibm_dividend_payment is not None
    assert ibm_dividend_payment.amount == Decimal("30.00")

    assert usd_account.taxValue is not None
    assert len(usd_account.taxValue) == 1
    assert usd_account.taxValue[0].balance == Decimal("9727.50")
    assert usd_account.taxValue[0].referenceDate == date(2023,12,31)


def test_ibkr_import_from_file_missing_required_field(error_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)
    xml_file_path = SAMPLES_DIR / "sample_2_error_missing_field.xml"

    assert xml_file_path.exists(), f"Sample file not found: {xml_file_path}"

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=error_ibkr_settings
    )

    with pytest.raises(ValueError) as excinfo:
        importer.import_files([str(xml_file_path)])

    assert "Missing required field 'tradePrice'" in str(excinfo.value)
    assert "Trade (Symbol: AMZN)" in str(excinfo.value)
