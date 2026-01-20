import os
import pytest
from datetime import date
from typing import List
import tempfile
from decimal import Decimal

from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.config.models import IbkrAccountSettings

# Check if ibflex is available, skip tests if not
try:
    from ibflex import parser as ibflex_parser
    IBFLEX_INSTALLED = True
except ImportError:
    IBFLEX_INSTALLED = False

pytestmark = pytest.mark.skipif(
    not IBFLEX_INSTALLED, reason="ibflex library is not installed, skipping IBKR importer tests"
)

SAMPLE_IBKR_MULTI_ACCOUNT_XML = """
<FlexQueryResponse queryName="MultiAccountQuery" type="AF">
  <FlexStatements count="2">
    <FlexStatement accountId="U111111" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <Trade transactionID="1001" accountId="U111111" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" quantity="10" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="280.00" tradeMoney="2800.00" buySell="BUY" ibCommission="-1.00" ibCommissionCurrency="USD" netCash="-2801.00" />
      </Trades>
      <CashReport>
        <CashReportCurrency accountId="U111111" currency="USD" startingCash="0" endingCash="100.00" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
    <FlexStatement accountId="U222222" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <Trade transactionID="2001" accountId="U222222" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="265598" isin="US0378331005" currency="USD" quantity="20" tradeDate="2023-04-20" settleDateTarget="2023-04-22" tradePrice="180.00" tradeMoney="3600.00" buySell="BUY" ibCommission="-1.00" ibCommissionCurrency="USD" netCash="-3601.00" />
      </Trades>
      <CashReport>
        <CashReportCurrency accountId="U222222" currency="USD" startingCash="0" endingCash="200.00" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

def test_ibkr_filter_single_account():
    """Test that only the configured account is imported when settings are provided."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    # Configure only for U111111
    settings = [
        IbkrAccountSettings(
            account_number="U111111",
            broker_name="Interactive Brokers",
            account_name_alias="Account 1",
            canton="ZH",
            full_name="User 1",
        )
    ]

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_MULTI_ACCOUNT_XML)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None

        # Check Securities
        assert tax_statement.listOfSecurities is not None
        # Should only have 1 depot for U111111
        assert len(tax_statement.listOfSecurities.depot) == 1
        depot = tax_statement.listOfSecurities.depot[0]
        assert depot.depotNumber == "U111111"
        assert len(depot.security) == 1
        assert depot.security[0].securityName == "MICROSOFT CORP (MSFT)"

        # Check Bank Accounts
        assert tax_statement.listOfBankAccounts is not None
        # Should only have account for U111111
        assert len(tax_statement.listOfBankAccounts.bankAccount) == 1
        bank_account = tax_statement.listOfBankAccounts.bankAccount[0]
        assert "U111111" in bank_account.bankAccountNumber

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)

def test_ibkr_no_filter_empty_settings():
    """Test that all accounts are imported when no settings are provided."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    # No settings
    settings = []

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_MULTI_ACCOUNT_XML)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None

        # Check Securities
        assert tax_statement.listOfSecurities is not None
        # Should have depots for both
        assert len(tax_statement.listOfSecurities.depot) == 2
        depot_ids = sorted([d.depotNumber for d in tax_statement.listOfSecurities.depot])
        assert depot_ids == ["U111111", "U222222"]

        # Check Bank Accounts
        assert tax_statement.listOfBankAccounts is not None
        assert len(tax_statement.listOfBankAccounts.bankAccount) == 2
        account_ids = sorted([ba.bankAccountNumber for ba in tax_statement.listOfBankAccounts.bankAccount])
        assert "U111111" in account_ids[0]
        assert "U222222" in account_ids[1]

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)
