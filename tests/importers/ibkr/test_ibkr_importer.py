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
from opensteuerauszug.core.constants import UNINITIALIZED_QUANTITY

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
        <CashTransaction accountId="U1234567" type="Broker Interest Received" currency="USD" amount="25.50" description="Interest on Cash" conid="" symbol="" dateTime="2023-08-15T00:00:00" assetCategory="" />
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

SAMPLE_IBKR_FLEX_XML_AGGREGATE = """
<FlexQueryResponse queryName="AggQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <Trade transactionID="1101" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" quantity="5" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="280.00" tradeMoney="1400.00" buySell="BUY" ibCommission="-0.50" netCash="-1400.50" />
        <Trade transactionID="1102" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" quantity="5" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="281.00" tradeMoney="1405.00" buySell="BUY" ibCommission="-0.50" netCash="-1405.50" />
        <Trade transactionID="1103" accountId="U1234567" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="265598" isin="US0378331005" currency="USD" quantity="-2" tradeDate="2023-06-20" settleDateTarget="2023-06-22" tradePrice="180.00" tradeMoney="-360.00" buySell="SELL" ibCommission="-0.20" netCash="359.80" />
        <Trade transactionID="1104" accountId="U1234567" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="265598" isin="US0378331005" currency="USD" quantity="-3" tradeDate="2023-06-20" settleDateTarget="2023-06-22" tradePrice="179.50" tradeMoney="-538.50" buySell="SELL" ibCommission="-0.30" netCash="538.20" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" position="10" markPrice="300.00" positionValue="3000.00" reportDate="2023-12-31" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
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

SAMPLE_IBKR_FLEX_XML_TRANSFER = """
<FlexQueryResponse queryName="TransferQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Transfers>
        <Transfer type="INTERNAL" direction="IN" assetCategory="STK" symbol="GME" description="GAMESTOP" conid="123456" isin="US36467W1099" currency="USD" quantity="10" date="2023-07-01" account="Other Account" />
        <Transfer type="INTERNAL" direction="IN" assetCategory="CASH" currency="USD" cashTransfer="100" date="2023-07-01" account="Other Account" />
      </Transfers>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

SAMPLE_IBKR_FLEX_XML_TRANSFER_WRONG_SIGN = """
<FlexQueryResponse queryName="TransferQueryWrong" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Transfers>
        <Transfer type="INTERNAL" direction="OUT" assetCategory="STK" symbol="GME" description="GAMESTOP" conid="123456" isin="US36467W1099" currency="USD" quantity="10" date="2023-07-01" account="Other Account" />
      </Transfers>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
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

        # Divdend fom cash transaction should be mapped to SecurityPayment
        assert len(msft_sec.payment) == 1
        assert msft_sec.payment[0].name == "MSFT Dividend"
        assert msft_sec.payment[0].amount == Decimal("50.00")
        assert msft_sec.payment[0].paymentDate == date(2023, 9, 5)

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
            len(tax_statement.listOfBankAccounts.bankAccount) == 2
        )  # USD account has transactions + balance, EUR account has only balance

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

        assert len(usd_account.payment) == 1  # Only interest payment (deposits filtered out)
        interest_payment = next(
            (p for p in usd_account.payment if p.name == "Interest on Cash"), None
        )
        assert interest_payment is not None
        assert interest_payment.amount == Decimal("25.50")

        assert usd_account.taxValue is not None
        assert usd_account.taxValue.balance == Decimal("3148.50")
        assert usd_account.taxValue.referenceDate == date(2023, 12, 31)

        # Check EUR account (should have 0 balance, no payments)
        eur_account = next(
            (
                ba
                for ba in tax_statement.listOfBankAccounts.bankAccount
                if ba.bankAccountCurrency == "EUR"
            ),
            None,
        )
        assert eur_account is not None
        assert eur_account.bankAccountNumber == "U1234567-EUR"
        assert len(eur_account.payment) == 0  # No transactions
        assert eur_account.taxValue is not None
        assert eur_account.taxValue.balance == Decimal("0")
        assert eur_account.taxValue.referenceDate == date(2023, 12, 31)

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_security_payment_quantity_is_minus_one(sample_ibkr_settings):
    """Test that SecurityPayment.quantity is set to -1 for payments derived from CashTransactions."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    xml_content_security_payment = f"""
<FlexQueryResponse queryName="SecPaymentQtyTest" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="{period_from}" toDate="{period_to}" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <!-- Add a trade to define the security MSFT so it appears in listOfSecurities -->
        <Trade transactionID="5001" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" quantity="1" tradeDate="2023-02-01" settleDateTarget="2023-02-03" tradePrice="250.00" tradeMoney="250.00" buySell="BUY" ibCommission="-0.50" netCash="-250.50" />
      </Trades>
      <CashTransactions>
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="12.34" description="MSFT Corp Dividend" conid="272120" symbol="MSFT" dateTime="2023-05-10T00:00:00" assetCategory="STK" />
        <CashTransaction accountId="U1234567" type="Withholding Tax" currency="USD" amount="-1.85" description="Tax on MSFT Dividend" conid="272120" symbol="MSFT" dateTime="2023-05-10T00:00:00" assetCategory="STK" />
      </CashTransactions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0"/>
      </CashReport>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" position="1" markPrice="300.00" positionValue="300.00" reportDate="{period_to}" />
      </OpenPositions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""
    xml_file_path = "test_sec_payment_qty.xml"
    try:
        with open(xml_file_path, "w") as f:
            f.write(xml_content_security_payment)

        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        assert tax_statement.listOfSecurities is not None
        assert len(tax_statement.listOfSecurities.depot) == 1

        depot = tax_statement.listOfSecurities.depot[0]
        assert depot.depotNumber == "U1234567"

        msft_security = None
        for sec in depot.security:
            if sec.securityName == "MICROSOFT CORP (MSFT)" and sec.isin == "US5949181045":
                msft_security = sec
                break

        assert msft_security is not None, "MSFT security not found"
        assert msft_security.payment is not None, "MSFT security should have payments"
        assert len(msft_security.payment) == 2, "MSFT security should have two payments (dividend and tax)"

        for payment in msft_security.payment:
            if payment.name == "MSFT Corp Dividend":
                assert payment.quantity == UNINITIALIZED_QUANTITY, f"Dividend payment quantity for {payment.name} should be UNINITIALIZED_QUANTITY"
            elif payment.name == "Tax on MSFT Dividend":
                assert payment.quantity == UNINITIALIZED_QUANTITY, f"Tax payment quantity for {payment.name} should be UNINITIALIZED_QUANTITY"
            else:
                pytest.fail(f"Unexpected payment found: {payment.name}")

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_transfer_to_stock(sample_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_TRANSFER)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])

        depot = tax_statement.listOfSecurities.depot[0]
        gme_sec = next(
            (s for s in depot.security if s.securityName == "GAMESTOP (GME)"),
            None,
        )
        assert gme_sec is not None
        transfers = [s for s in gme_sec.stock if s.mutation]
        assert len(transfers) == 1
        transfer_stock = transfers[0]
        assert transfer_stock.quantity == Decimal("10")
        assert transfer_stock.name == "INTERNAL Other Account"
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_transfer_quantity_sign_mismatch(sample_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_TRANSFER_WRONG_SIGN)
        xml_file_path = tmp_file.name

    try:
        with pytest.raises(ValueError):
            importer.import_files([xml_file_path])
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_trade_aggregation(sample_ibkr_settings):
    """Trades on the same day should be aggregated into single entries."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_AGGREGATE)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])

        depot = tax_statement.listOfSecurities.depot[0]
        msft_sec = next(
            (s for s in depot.security if s.securityName == "MICROSOFT CORP (MSFT)"),
            None,
        )
        aapl_sec = next(
            (s for s in depot.security if s.securityName == "APPLE INC (AAPL)"),
            None,
        )
        assert msft_sec is not None and aapl_sec is not None
        # Should aggregate into a single trade entry per security
        assert len(msft_sec.stock) == 3
        assert msft_sec.stock[1].quantity == Decimal("10")
        assert len(aapl_sec.stock) == 3
        assert aapl_sec.stock[1].quantity == Decimal("-5")
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
        "expected_first_name": "John",
        "expected_last_name": "Doe",
        "description": "name present in AccountInformation",
    },
    # Scenario 2: Different name
    {
        "account_info_xml": """
          <AccountInformation accountId="U9876544" acctAlias="Another Alias" name="Jane Smith" />""",
        "expected_client_number": "U9876544",
        "expected_first_name": "Jane",
        "expected_last_name": "Smith",
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


def test_import_files_with_firstname_and_name(monkeypatch, sample_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    class DummyAccountInfo:
        def __init__(self) -> None:
            self.accountId = "U1111111"
            self.name = "Bob Builder"
            self.firstName = "Bob"
            self.lastName = None
            self.accountHolderName = None

    class DummyFlexStatement:
        def __init__(self) -> None:
            self.accountId = "U1111111"
            self.fromDate = period_from
            self.toDate = period_to
            self.AccountInformation = DummyAccountInfo()
            self.Trades = []
            self.OpenPositions = []
            self.Transfers = []
            self.CashTransactions = []
            self.CashReport = []

    class DummyResponse:
        def __init__(self) -> None:
            self.FlexStatements = [DummyFlexStatement()]

    def fake_parse(_filename):
        return DummyResponse()

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    monkeypatch.setattr(ibflex_parser, "parse", fake_parse)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write("<FlexQueryResponse></FlexQueryResponse>")
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement.client is not None
        assert len(tax_statement.client) == 1
        client_obj = tax_statement.client[0]
        assert client_obj.firstName == "Bob"
        assert client_obj.lastName == "Builder"
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_base_summary_currency_filtered_out(sample_ibkr_settings):
    """Test that BASE_SUMMARY currency entries are filtered out and not included in bank accounts."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    # Create XML with BASE_SUMMARY currency alongside real currencies
    xml_content = """
<FlexQueryResponse queryName="BaseSummaryTestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <Trade transactionID="4001" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" quantity="10" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="280.00" tradeMoney="2800.00" buySell="BUY" ibCommission="-1.00" netCash="-2801.00" />
      </Trades>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="1500.00" fromDate="2023-01-01" toDate="2023-12-31" />
        <CashReportCurrency accountId="U1234567" currency="EUR" startingCash="0" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
        <CashReportCurrency accountId="U1234567" currency="BASE_SUMMARY" startingCash="0" endingCash="189947.764908952" fromDate="2023-01-01" toDate="2023-12-31" />
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

        # Should have bank accounts for USD and EUR, but not BASE_SUMMARY
        assert tax_statement.listOfBankAccounts is not None
        bank_accounts = tax_statement.listOfBankAccounts.bankAccount
        assert len(bank_accounts) == 2  # USD and EUR only

        # Verify currencies present
        currencies = {ba.bankAccountCurrency for ba in bank_accounts}
        assert currencies == {"USD", "EUR"}

        # Verify BASE_SUMMARY is not present
        assert "BASE_SUMMARY" not in currencies

        # Verify account numbers don't contain BASE_SUMMARY
        account_numbers = {str(ba.bankAccountNumber) for ba in bank_accounts if ba.bankAccountNumber}
        base_summary_accounts = {num for num in account_numbers if "BASE_SUMMARY" in num}
        assert len(base_summary_accounts) == 0

        # Verify we can find the expected accounts
        usd_account = next((ba for ba in bank_accounts if ba.bankAccountCurrency == "USD"), None)
        eur_account = next((ba for ba in bank_accounts if ba.bankAccountCurrency == "EUR"), None)
        
        assert usd_account is not None
        assert eur_account is not None
        assert usd_account.bankAccountNumber == "U1234567-USD"
        assert eur_account.bankAccountNumber == "U1234567-EUR"

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_bank_account_names_always_set(sample_ibkr_settings):
    """Test that bank account names are always set for all currencies with closing balances."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)
    
    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    # Create XML with multiple currencies including 0 balance ones
    xml_content = f"""
<FlexQueryResponse queryName="BankAccountNamesTestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U7890123" fromDate="{period_from}" toDate="{period_to}" period="Year" whenGenerated="2024-01-15T10:00:00">
      <CashReport>
        <CashReportCurrency accountId="U7890123" currency="USD" endingCash="1500.00" />
        <CashReportCurrency accountId="U7890123" currency="EUR" endingCash="0" />
        <CashReportCurrency accountId="U7890123" currency="GBP" endingCash="250.75" />
      </CashReport>
      <CashTransactions>
        <CashTransaction accountId="U7890123" type="Broker Interest Received" currency="USD" amount="15.00" description="Interest on USD Cash" conid="" symbol="" dateTime="2023-06-15T00:00:00" assetCategory="" />
      </CashTransactions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
    """

    xml_file_path = "test_bank_account_names.xml"
    try:
        with open(xml_file_path, "w") as f:
            f.write(xml_content)

        tax_statement = importer.import_files([xml_file_path])

        # Verify that bank accounts are created for all currencies
        assert tax_statement.listOfBankAccounts is not None
        assert len(tax_statement.listOfBankAccounts.bankAccount) == 3

        # Check that all bank accounts have names set
        for bank_account in tax_statement.listOfBankAccounts.bankAccount:
            assert bank_account.bankAccountName is not None
            assert bank_account.bankAccountName != ""
            
            # Check the naming pattern: "<AccountId> <Currency> position"
            currency = bank_account.bankAccountCurrency
            expected_name = f"U7890123 {currency} position"
            assert bank_account.bankAccountName == expected_name

        # Verify specific accounts
        currencies_found = {ba.bankAccountCurrency for ba in tax_statement.listOfBankAccounts.bankAccount}
        assert currencies_found == {"USD", "EUR", "GBP"}

        # Verify USD account has interest payment
        usd_account = next(ba for ba in tax_statement.listOfBankAccounts.bankAccount if ba.bankAccountCurrency == "USD")
        assert len(usd_account.payment) == 1
        assert usd_account.payment[0].name == "Interest on USD Cash"

        # Verify EUR account has no payments but still has name
        eur_account = next(ba for ba in tax_statement.listOfBankAccounts.bankAccount if ba.bankAccountCurrency == "EUR")
        assert len(eur_account.payment) == 0
        assert eur_account.bankAccountName == "U7890123 EUR position"

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)
