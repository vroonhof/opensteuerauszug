import os
import pytest
from datetime import date
from decimal import Decimal
from typing import List
import tempfile

from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.config.models import IbkrAccountSettings
from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    ListOfSecurities,
    ListOfBankAccounts,
    Security,
    BankAccount,
    QuotationType,
    CurrencyId,
    Client,
)

# Check if ibflex is available, skip tests if not
try:
    from ibflex import parser as ibflex_parser

    IBFLEX_INSTALLED = True
except ImportError:
    IBFLEX_INSTALLED = False

pytestmark = pytest.mark.skipif(
    not IBFLEX_INSTALLED, reason="ibflex library is not installed, skipping IBKR importer tests"
)

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

SAMPLE_IBKR_FLEX_XML_INTEREST_WITH_SECURITY = """
<FlexQueryResponse queryName="InterestSecurity" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <CashTransactions>
        <CashTransaction accountId="U1234567" type="Broker Interest Paid" currency="USD" amount="5.00" description="Interest on MSFT" conid="272120" symbol="MSFT" dateTime="2023-01-05T00:00:00" assetCategory="STK" />
      </CashTransactions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="5.00" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


@pytest.fixture
def sample_ibkr_settings() -> List[IbkrAccountSettings]:
    return [
        IbkrAccountSettings(
            account_number="U1234567",
            broker_name="Interactive Brokers",
            account_name_alias="Test IBKR Account",
            canton="ZH",  # Placeholder
            full_name="Test User",  # Placeholder
        )
    ]


@pytest.fixture
def sample_ibkr_settings_other_account() -> List[IbkrAccountSettings]:
    return [
        IbkrAccountSettings(
            account_number="U7654321",
            broker_name="Interactive Brokers",
            account_name_alias="Test IBKR Account Missing",
            canton="ZH",  # Placeholder
            full_name="Test User Missing",  # Placeholder
        )
    ]


def test_ibkr_import_valid_xml(sample_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
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
        assert len(depot.security) == 2  # MSFT and AAPL

        # MSFT Security
        msft_sec = next(
            (s for s in depot.security if s.securityName == "MICROSOFT CORP (MSFT)"), None
        )
        assert msft_sec is not None
        assert msft_sec.isin == "US5949181045"
        assert msft_sec.currency == "USD"
        assert len(msft_sec.stock) == 3
        assert msft_sec.stock[0].mutation is False
        assert msft_sec.stock[0].referenceDate == date(2023, 1, 1)
        assert msft_sec.stock[0].quantity == Decimal("0")
        assert msft_sec.stock[1].mutation is True  # Trade
        assert msft_sec.stock[1].quantity == Decimal("10")
        assert msft_sec.stock[2].mutation is False
        assert msft_sec.stock[2].referenceDate == date(2024, 1, 1)
        assert msft_sec.stock[2].quantity == Decimal("10")
        assert all(s.referenceDate != date(2023, 12, 31) for s in msft_sec.stock)

        # Trades should not create SecurityPayment entries
        assert len(msft_sec.payment) == 0

        # AAPL Security
        aapl_sec = next((s for s in depot.security if s.securityName == "APPLE INC (AAPL)"), None)
        assert aapl_sec is not None
        assert aapl_sec.isin == "US0378331005"
        assert len(aapl_sec.stock) == 3
        assert aapl_sec.stock[0].mutation is False
        assert aapl_sec.stock[0].quantity == Decimal("5")
        assert aapl_sec.stock[0].referenceDate == date(2023, 1, 1)
        assert aapl_sec.stock[1].mutation is True
        assert aapl_sec.stock[1].quantity == Decimal("-5")  # SELL
        assert aapl_sec.stock[2].mutation is False
        assert aapl_sec.stock[2].quantity == Decimal("0")
        assert aapl_sec.stock[2].referenceDate == date(2024, 1, 1)
        assert all(s.referenceDate != date(2023, 12, 31) for s in aapl_sec.stock)
        assert len(aapl_sec.payment) == 0

        # --- Check Bank Accounts ---
        assert tax_statement.listOfBankAccounts is not None
        assert (
            len(tax_statement.listOfBankAccounts.bankAccount) == 1
        )  # Only USD account has transactions + balance

        usd_account = next(
            (
                ba
                for ba in tax_statement.listOfBankAccounts.bankAccount
                if ba.bankAccountCurrency == "USD"
            ),
            None,
        )
        assert usd_account is not None
        assert usd_account.bankAccountNumber == "U1234567-USD"

        assert len(usd_account.payment) == 1  # Only deposit remains
        deposit_payment = next(
            (p for p in usd_account.payment if p.name == "Initial Deposit"), None
        )
        assert deposit_payment is not None
        assert deposit_payment.amount == Decimal("5000.00")

        assert usd_account.taxValue is not None
        assert usd_account.taxValue.balance == Decimal("3148.50")
        assert usd_account.taxValue.referenceDate == date(2023, 12, 31)

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_import_missing_required_field(sample_ibkr_settings_other_account):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings_other_account,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_MISSING_FIELD)
        xml_file_path = tmp_file.name

    try:
        with pytest.raises(ValueError) as excinfo:
            importer.import_files([xml_file_path])
        assert "Missing required field 'tradeDate'" in str(excinfo.value)
        assert "Trade (Symbol: GOOG)" in str(excinfo.value)  # Check context in error
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_open_position_balance_date_is_day_after_period_end(sample_ibkr_settings):
    """Ensure balances from OpenPositions use period end + 1 as reference date."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_VALID)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])

        msft_sec = next(
            (
                s
                for s in tax_statement.listOfSecurities.depot[0].security
                if s.securityName == "MICROSOFT CORP (MSFT)"
            ),
            None,
        )
        assert msft_sec is not None

        # The last stock entry should be the balance from OpenPositions at day after period end
        closing_stock = msft_sec.stock[-1]
        assert closing_stock.referenceDate == date(2024, 1, 1)
        assert closing_stock.mutation is False
        assert closing_stock.quantity == Decimal("10")

        # Ensure no stock entry exists on the period end itself
        assert all(s.referenceDate != date(2023, 12, 31) for s in msft_sec.stock)
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_cash_transaction_security_interest_assert(sample_ibkr_settings):
    """CashTransaction with security ID and interest type should raise AssertionError."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_INTEREST_WITH_SECURITY)
        xml_file_path = tmp_file.name

    try:
        with pytest.raises(AssertionError):
            importer.import_files([xml_file_path])
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

# Parameterized test data for client information
CLIENT_INFO_TEST_CASES = [
    # Scenario 1: name provided
    {
        "account_info_xml": """
          <AccountInformation accountId="U9876543" acctAlias="Test Alias" name="John Doe" />""",
        "expected_client_number": "U9876543",
        "expected_first_name": None,
        "expected_last_name": "John Doe",
        "description": "name present in AccountInformation",
    },
    # Scenario 2: Different name
    {
        "account_info_xml": """
          <AccountInformation accountId="U9876544" acctAlias="Another Alias" name="Jane Smith" />""",
        "expected_client_number": "U9876544",
        "expected_first_name": None,
        "expected_last_name": "Jane Smith",
        "description": "different name present in AccountInformation",
    },
    # Scenario 3: No name provided, client should not be created
    {
        "account_info_xml": """
          <AccountInformation accountId="U9876545" acctAlias="Third Alias" />""",
        "expected_client_number": None,  # client object should not be created
        "expected_first_name": None,
        "expected_last_name": None,
        "description": "No name field present, client should be None",
    },
    # Scenario 4: Empty name provided, client should not be created
    {
        "account_info_xml": """
          <AccountInformation accountId="U9876546" acctAlias="Fourth Alias" name="" />""",
        "expected_client_number": None,  # client object should not be created due to empty name
        "expected_first_name": None,
        "expected_last_name": None,
        "description": "Empty name field present, client should be None",
    },
    # Scenario 5: Whitespace-only name provided, client should not be created
    {
        "account_info_xml": """
          <AccountInformation accountId="U9876547" acctAlias="Fifth Alias" name="   " />""",
        "expected_client_number": None,  # client object should not be created due to whitespace-only name
        "expected_first_name": None,
        "expected_last_name": None,
        "description": "Whitespace-only name field present, client should be None",
    },
    # Scenario 6: Other attributes present but no name
    {
        "account_info_xml": """
          <AccountInformation accountId="U9876548" acctAlias="Sixth Alias" street="123 Main St" city="New York" />""",
        "expected_client_number": None,  # client object should not be created
        "expected_first_name": None,
        "expected_last_name": None,
        "description": "Other attributes present but no name field, client should be None",
    },
]


@pytest.mark.parametrize("client_data", CLIENT_INFO_TEST_CASES)
def test_import_files_with_client_information(client_data, sample_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    # Use the accountId from the test case for settings, or a default if not applicable
    account_id_for_settings = client_data["expected_client_number"] or "U0000000"
    settings = [
        IbkrAccountSettings(
            account_number=account_id_for_settings,  # This is not directly used by client creation from XML accountId
            broker_name="Interactive Brokers",
            account_name_alias="Client Test Account",
            canton="ZH",
            full_name="Test User",
        )
    ]

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=settings,  # Use the dynamic settings
    )

    # Construct a minimal valid FlexQueryResponse with the specific AccountInformation
    # Basic structure that includes Trades to avoid "No Flex statements" warning if no trades are present
    # and to ensure `all_flex_statements` is populated.
    xml_content = f"""
<FlexQueryResponse queryName="ClientTestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="{client_data.get('expected_client_number', 'U0000000')}" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      {client_data["account_info_xml"]}
      <Trades>
        <Trade transactionID="3001" accountId="{client_data.get('expected_client_number', 'U0000000')}" assetCategory="STK" symbol="TEST" description="TEST STOCK" conid="00000" currency="USD" quantity="1" tradeDate="2023-01-01" settleDateTarget="2023-01-01" tradePrice="10" tradeMoney="10" buySell="BUY" ibCommission="0" netCash="-10" />
      </Trades>
      <CashReport>
        <CashReportCurrency accountId="{client_data.get('expected_client_number', 'U0000000')}" currency="USD" endingCash="0"/>
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_content)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None

        if (
            client_data["expected_client_number"] is None
            and client_data["expected_last_name"] is None
        ):
            # Scenario where no client should be created
            assert (
                not hasattr(tax_statement, "client")
                or tax_statement.client is None
                or len(tax_statement.client) == 0
            )
        else:
            assert hasattr(tax_statement, "client")
            assert tax_statement.client is not None
            assert len(tax_statement.client) == 1
            client_obj = tax_statement.client[0]
            assert isinstance(client_obj, Client)
            assert client_obj.clientNumber == client_data["expected_client_number"]
            assert client_obj.firstName == client_data["expected_first_name"]
            assert client_obj.lastName == client_data["expected_last_name"]
            # Optional: Log details for easier debugging if a test case fails
            # print(f"Test: {client_data['description']}")
            # print(f"  Expected: clientNumber={client_data['expected_client_number']}, firstName={client_data['expected_first_name']}, lastName={client_data['expected_last_name']}")
            # print(f"  Actual:   clientNumber={client_obj.clientNumber}, firstName={client_obj.firstName}, lastName={client_obj.lastName}")

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)
