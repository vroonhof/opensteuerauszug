import os
import pytest
from datetime import date
from decimal import Decimal
from typing import List
import tempfile

from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.config.models import IbkrAccountSettings
from opensteuerauszug.model.ech0196 import TaxStatement, ListOfSecurities, ListOfBankAccounts, Security, BankAccount, QuotationType, CurrencyId

# Check if ibflex is available, skip tests if not
try:
    from ibflex import parser as ibflex_parser
    IBFLEX_INSTALLED = True
except ImportError:
    IBFLEX_INSTALLED = False

pytestmark = pytest.mark.skipif(not IBFLEX_INSTALLED, reason="ibflex library is not installed, skipping IBKR importer tests")

# Define a basic sample IBKR Flex Query XML as a string
SAMPLE_IBKR_FLEX_XML_VALID = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <Trade transactionID="1001" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" quantity="10" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="280.00" tradeMoney="2800.00" buySell="BUY" ibCommission="-1.00" ibCommissionCurrency="USD" netCash="-2801.00" />
        <Trade transactionID="1002" accountId="U1234567" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="265598" isin="US0378331005" currency="USD" quantity="-5" tradeDate="2023-06-20" settleDateTarget="2023-06-22" tradePrice="180.00" tradeMoney="-900.00" buySell="SELL" ibCommission="-0.50" ibCommissionCurrency="USD" netCash="899.50" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" position="10" markPrice="300.00" positionValue="3000.00" reportDate="2023-12-31" />
      </OpenPositions>
      <CashTransactions>
        <CashTransaction accountId="U1234567" type="Deposits/Withdrawals" currency="USD" amount="5000.00" description="Initial Deposit" conid="" symbol="" dateTime="2023-01-10T09:00:00" assetCategory="" />
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="50.00" description="MSFT Dividend" conid="272120" symbol="MSFT" dateTime="2023-09-05T00:00:00" assetCategory="STK" />
      </CashTransactions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="3148.50" fromDate="2023-01-01" toDate="2023-12-31" />
        <CashReportCurrency accountId="U1234567" currency="EUR" startingCash="0" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

SAMPLE_IBKR_FLEX_XML_MISSING_FIELD = """
<FlexQueryResponse queryName="TestQueryMissing" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U7654321" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <!-- Missing tradeDate -->
        <Trade transactionID="2001" accountId="U7654321" assetCategory="STK" symbol="GOOG" description="ALPHABET INC" conid="20881" currency="USD" quantity="5" settleDateTarget="2023-04-03" tradePrice="100.00" tradeMoney="500.00" buySell="BUY" ibCommission="-0.70" ibCommissionCurrency="USD" netCash="-500.70" />
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

@pytest.fixture
def sample_ibkr_settings() -> List[IbkrAccountSettings]:
    return [IbkrAccountSettings(
        account_number="U1234567",
        broker_name="Interactive Brokers",
        account_name_alias="Test IBKR Account",
        canton="ZH",  # Placeholder
        full_name="Test User"  # Placeholder
    )]

@pytest.fixture
def sample_ibkr_settings_other_account() -> List[IbkrAccountSettings]:
    return [IbkrAccountSettings(
        account_number="U7654321",
        broker_name="Interactive Brokers",
        account_name_alias="Test IBKR Account Missing",
        canton="ZH",  # Placeholder
        full_name="Test User Missing"  # Placeholder
    )]


def test_ibkr_import_valid_xml(sample_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_VALID)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        assert tax_statement.periodFrom == period_from
        assert tax_statement.periodTo == period_to
        assert tax_statement.taxPeriod == 2023

        # --- Check Securities ---
        assert tax_statement.listOfSecurities is not None
        assert len(tax_statement.listOfSecurities.depot) == 1
        depot = tax_statement.listOfSecurities.depot[0]
        assert depot.depotNumber == "U1234567"
        assert len(depot.security) == 2 # MSFT and AAPL

        # MSFT Security
        msft_sec = next((s for s in depot.security if s.securityName == "MICROSOFT CORP (MSFT)"), None)
        assert msft_sec is not None
        assert msft_sec.isin == "US5949181045"
        assert msft_sec.currency == "USD"
        assert len(msft_sec.stock) == 2 # 1 trade (mutation) + 1 open position (balance)
        assert msft_sec.stock[0].mutation is True # Trade
        assert msft_sec.stock[0].quantity == Decimal("10")
        assert msft_sec.stock[1].mutation is False # Open Position Balance
        assert msft_sec.stock[1].quantity == Decimal("10")
        assert msft_sec.stock[1].referenceDate == date(2023,12,31)

        assert len(msft_sec.payment) == 1 # Only 1 for the BUY trade. Dividend is in BankAccountPayment
        buy_payment = next((p for p in msft_sec.payment if p.name and "Trade:" in p.name and "MSFT" in p.name), None)
        assert buy_payment is not None
        assert buy_payment.amount == Decimal("-2801.00") # netCash for BUY

        # AAPL Security
        aapl_sec = next((s for s in depot.security if s.securityName == "APPLE INC (AAPL)"), None)
        assert aapl_sec is not None
        assert aapl_sec.isin == "US0378331005"
        assert len(aapl_sec.stock) == 1 # 1 trade (mutation)
        assert aapl_sec.stock[0].quantity == Decimal("-5") # SELL
        assert len(aapl_sec.payment) == 1
        assert aapl_sec.payment[0].amount == Decimal("899.50") # netCash for SELL

        # --- Check Bank Accounts ---
        assert tax_statement.listOfBankAccounts is not None
        assert len(tax_statement.listOfBankAccounts.bankAccount) == 1 # Only USD account has transactions + balance

        usd_account = next((ba for ba in tax_statement.listOfBankAccounts.bankAccount if ba.bankAccountCurrency == "USD"), None)
        assert usd_account is not None
        assert usd_account.bankAccountNumber == "U1234567-USD"

        assert len(usd_account.payment) == 2 # Deposit + MSFT Dividend (as per current CashTransaction mapping)
        deposit_payment = next((p for p in usd_account.payment if p.name == "Initial Deposit"), None)
        assert deposit_payment is not None
        assert deposit_payment.amount == Decimal("5000.00")

        msft_dividend_bank_payment = next((p for p in usd_account.payment if p.name == "MSFT Dividend"), None)
        assert msft_dividend_bank_payment is not None
        assert msft_dividend_bank_payment.amount == Decimal("50.00")


        assert usd_account.taxValue is not None
        assert usd_account.taxValue.balance == Decimal("3148.50")
        assert usd_account.taxValue.referenceDate == date(2023,12,31)

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)

def test_ibkr_import_missing_required_field(sample_ibkr_settings_other_account):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings_other_account
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_MISSING_FIELD)
        xml_file_path = tmp_file.name

    try:
        with pytest.raises(ValueError) as excinfo:
            importer.import_files([xml_file_path])
        assert "Missing required field 'tradeDate'" in str(excinfo.value)
        assert "Trade (Symbol: GOOG)" in str(excinfo.value) # Check context in error
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)

# TODO: Add more test cases:
# - XML with multiple accounts (and settings to filter/select one)
# - Different asset types (options, bonds, funds if supported by mapping)
# - More complex scenarios (corporate actions - though these are hard to map without detailed XML spec)
# - FX rates if applicable (though IBKR Flex often provides data in base currency or has fxRateToBase)
# - Empty Trades, OpenPositions, CashTransactions sections
# - File not found, invalid XML format (not ibflex parseable)
# - Test for dividend mapping to SecurityPayment if that logic changes in importer.
#   Currently, the MSFT dividend is expected in BankAccountPayment.
#   If MSFT dividend were to be mapped to SecurityPayment for MSFT security:
#   assert len(msft_sec.payment) == 2
#   dividend_payment = next((p for p in msft_sec.payment if "Dividend" in p.name), None)
#   assert dividend_payment is not None
#   assert dividend_payment.amount == Decimal("50.00")
#   And then assert only 1 payment (Initial Deposit) in the BankAccount.
#   assert len(usd_account.payment) == 1
