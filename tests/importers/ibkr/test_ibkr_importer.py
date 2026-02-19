import os
import pytest
from datetime import date, timedelta
from decimal import Decimal
from typing import List
import tempfile

from opensteuerauszug.importers.ibkr.ibkr_importer import (
    IbkrImporter,
    is_summary_level,
    should_skip_pseudo_account_entry,
)
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


class DummyIbkrEntry:
    def __init__(self, account_id=None, level_of_detail=None):
        self.accountId = account_id
        self.levelOfDetail = level_of_detail


def test_invariant_summary_level_detected_case_insensitively():
    assert is_summary_level(DummyIbkrEntry(level_of_detail="summary"))


def test_invariant_non_summary_level_not_detected():
    assert not is_summary_level(DummyIbkrEntry(level_of_detail="DETAIL"))


def test_invariant_hyphen_account_entry_is_skipped():
    assert should_skip_pseudo_account_entry(
        DummyIbkrEntry(account_id="-", level_of_detail="DETAIL")
    )


def test_invariant_missing_account_summary_entry_is_skipped():
    assert should_skip_pseudo_account_entry(
        DummyIbkrEntry(account_id=None, level_of_detail="SUMMARY")
    )


def test_invariant_missing_account_detail_entry_is_not_skipped():
    assert not should_skip_pseudo_account_entry(
        DummyIbkrEntry(account_id=None, level_of_detail="DETAIL")
    )

# Define a basic sample IBKR Flex Query XML as a string
SAMPLE_IBKR_FLEX_XML_VALID = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <Trade transactionID="1001" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" issuerCountryCode="US" currency="USD" quantity="10" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="280.00" tradeMoney="2800.00" buySell="BUY" ibCommission="-1.00" ibCommissionCurrency="USD" netCash="-2801.00" />
        <Trade transactionID="1002" accountId="U1234567" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="265598" isin="US0378331005" issuerCountryCode="IE" currency="USD" quantity="-5" tradeDate="2023-06-20" settleDateTarget="2023-06-22" tradePrice="180.00" tradeMoney="-900.00" buySell="SELL" ibCommission="-0.50" ibCommissionCurrency="USD" netCash="899.50" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" issuerCountryCode="US" currency="USD" position="10" markPrice="300.00" positionValue="3000.00" reportDate="2023-12-31" />
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
        <Trade transactionID="1101" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" quantity="5" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="280.00" tradeMoney="1400.00" buySell="BUY" ibCommission="-0.50" netCash="-1400.50" ibOrderID="123456788" />
        <Trade transactionID="1102" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" quantity="5" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="281.00" tradeMoney="1405.00" buySell="BUY" ibCommission="-0.50" netCash="-1405.50" ibOrderID="123456788" />
        <Trade transactionID="1105" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" quantity="10" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="282.00" tradeMoney="2820.00" buySell="BUY" ibCommission="-0.50" netCash="-2820.50" ibOrderID="123456789" />
        <Trade transactionID="1103" accountId="U1234567" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="265598" isin="US0378331005" currency="USD" quantity="-2" tradeDate="2023-06-20" settleDateTarget="2023-06-22" tradePrice="180.00" tradeMoney="-360.00" buySell="SELL" ibCommission="-0.20" netCash="359.80" />
        <Trade transactionID="1104" accountId="U1234567" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="265598" isin="US0378331005" currency="USD" quantity="-3" tradeDate="2023-06-20" settleDateTarget="2023-06-22" tradePrice="179.50" tradeMoney="-538.50" buySell="SELL" ibCommission="-0.30" netCash="538.20" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" currency="USD" position="20" markPrice="300.00" positionValue="6000.00" reportDate="2023-12-31" />
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
        <Transfer accountId="U1234567" type="INTERNAL" direction="IN" assetCategory="STK" symbol="GME" description="GAMESTOP" conid="123456" isin="US36467W1099" currency="USD" quantity="10" date="2023-07-01" account="Other Account" />
        <Transfer accountId="U1234567" type="INTERNAL" direction="IN" assetCategory="CASH" currency="USD" cashTransfer="100" date="2023-07-01" account="Other Account" />
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
        <Transfer accountId="U1234567" type="INTERNAL" direction="OUT" assetCategory="STK" symbol="GME" description="GAMESTOP" conid="123456" isin="US36467W1099" currency="USD" quantity="10" date="2023-07-01" account="Other Account" />
      </Transfers>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

# Inbound position transfer with no other transactions - just Transfer + OpenPosition
SAMPLE_IBKR_FLEX_XML_TRANSFER_ONLY_WITH_OPEN_POSITION = """
<FlexQueryResponse queryName="TransferOnlyQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2025-01-01" toDate="2025-12-31" period="Year" whenGenerated="2026-01-15T10:00:00">
      <OpenPositions>
        <OpenPosition accountId="U1234567" acctAlias="" model="" currency="EUR" fxRateToBase="0.93109" assetCategory="STK" subCategory="ETF" symbol="IWDA" description="ISHARES CORE MSCI WORLD" conid="12345678" securityID="IE00B4L5Y983" securityIDType="ISIN" cusip="" isin="IE00B4L5Y983" figi="BBG000P71QK5" listingExchange="AEB" underlyingConid="" underlyingSymbol="IWDA" underlyingSecurityID="" underlyingListingExchange="" issuer="" issuerCountryCode="IE" multiplier="1" strike="" expiry="" putCall="" principalAdjustFactor="" reportDate="2025-12-31" position="13" markPrice="111.53" positionValue="1449.89" openPrice="58.33" costBasisPrice="58.33" costBasisMoney="758.19" percentOfNAV="3.49" fifoPnlUnrealized="691.7" side="Long" levelOfDetail="SUMMARY" openDateTime="" holdingPeriodDateTime="" vestingDate="" code="" originatingOrderID="" originatingTransactionID="" accruedInt="" serialNumber="" deliveryType="" commodityType="" fineness="0.0" weight="0.0" />
      </OpenPositions>
      <Transfers>
        <Transfer accountId="U1234567" acctAlias="" model="" currency="EUR" fxRateToBase="0.944" assetCategory="STK" subCategory="ETF" symbol="IWDA" description="ISHARES CORE MSCI WORLD" conid="12345678" securityID="IE00B4L5Y983" securityIDType="ISIN" cusip="" isin="IE00B4L5Y983" figi="BBG000P71QK5" listingExchange="AEB" underlyingConid="" underlyingSymbol="IWDA" underlyingSecurityID="" underlyingListingExchange="" issuer="" issuerCountryCode="IE" multiplier="1" strike="" expiry="" putCall="" principalAdjustFactor="" reportDate="2025-08-13" date="2025-08-13" dateTime="2025-08-13" settleDate="2025-08-15" type="FOP" direction="IN" company="--" account="ExternalAccount" accountName="" deliveringBroker="Multiple" quantity="13" transferPrice="0" positionAmount="1354.02" positionAmountInBase="1278.19488" pnlAmount="0" pnlAmountInBase="0" cashTransfer="0" code="" clientReference="" transactionID="TX123456" levelOfDetail="TRANSFER" positionInstructionID="" positionInstructionSetID="" serialNumber="" deliveryType="" commodityType="" fineness="0.0" weight="0.0" />
      </Transfers>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="EUR" endingCash="0" fromDate="2025-01-01" toDate="2025-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

# OpenPosition only with no mutations at all (no trades, transfers, corporate actions)
SAMPLE_IBKR_FLEX_XML_OPEN_POSITION_ONLY = """
<FlexQueryResponse queryName="OpenPositionOnlyQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2025-01-01" toDate="2025-12-31" period="Year" whenGenerated="2026-01-15T10:00:00">
      <OpenPositions>
        <OpenPosition accountId="U1234567" acctAlias="" model="" currency="EUR" fxRateToBase="0.93109" assetCategory="STK" subCategory="ETF" symbol="IWDA" description="ISHARES CORE MSCI WORLD" conid="12345678" securityID="IE00B4L5Y983" securityIDType="ISIN" cusip="" isin="IE00B4L5Y983" figi="BBG000P71QK5" listingExchange="AEB" underlyingConid="" underlyingSymbol="IWDA" underlyingSecurityID="" underlyingListingExchange="" issuer="" issuerCountryCode="IE" multiplier="1" strike="" expiry="" putCall="" principalAdjustFactor="" reportDate="2025-12-31" position="13" markPrice="111.53" positionValue="1449.89" openPrice="58.33" costBasisPrice="58.33" costBasisMoney="758.19" percentOfNAV="3.49" fifoPnlUnrealized="691.7" side="Long" levelOfDetail="SUMMARY" openDateTime="" holdingPeriodDateTime="" vestingDate="" code="" originatingOrderID="" originatingTransactionID="" accruedInt="" serialNumber="" deliveryType="" commodityType="" fineness="0.0" weight="0.0" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="EUR" endingCash="0" fromDate="2025-01-01" toDate="2025-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

SAMPLE_IBKR_FLEX_XML_STOCK_SPLIT = """
<FlexQueryResponse queryName="SplitQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2025-01-01" toDate="2025-12-31" period="Year" whenGenerated="2026-01-15T10:00:00">
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="IBKR" description="INTERACTIVE BROKERS GRO-CL A" conid="43645865" isin="US45841N1072" currency="USD" position="8" markPrice="64.31" positionValue="514.48" reportDate="2025-12-31" />
      </OpenPositions>
      <CorporateActions>
        <CorporateAction accountId="U1234567" assetCategory="STK" symbol="IBKR" description="INTERACTIVE BROKERS GRO-CL A" conid="43645865" isin="US45841N1072" currency="USD" reportDate="2025-06-18" dateTime="2025-06-17;202500" actionDescription="IBKR(US45841N1072) SPLIT 4 FOR 1 (IBKR, INTERACTIVE BROKERS GRO-CL A, US45841N1072)" quantity="6" type="FS" />
      </CorporateActions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2025-01-01" toDate="2025-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

SAMPLE_IBKR_FLEX_XML_CORPORATE_ACTION_EXCHANGE = """
<FlexQueryResponse queryName="CorporateActionExchangeQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <CorporateActions>
        <CorporateAction accountId="U1234567" assetCategory="STK" symbol="ZT0" description="VIPER ENERGY PARTNERS LP" conid="604732578" isin="US9279591062" currency="USD" reportDate="2023-08-03" dateTime="2023-08-02;202500" actionDescription="ZT0(US9279591062) EXCHANGED TO 1XJ(US64361Q1013)" quantity="-10" type="TC" />
        <CorporateAction accountId="U1234567" assetCategory="STK" symbol="1XJ" description="VIPER ENERGY INC" conid="623598601" isin="US64361Q1013" currency="USD" reportDate="2023-08-03" dateTime="2023-08-02;202500" actionDescription="1XJ(US64361Q1013) EXCHANGED FROM ZT0(US9279591062)" quantity="10" type="TC" />
      </CorporateActions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

SAMPLE_IBKR_FLEX_XML_WITH_MISSING_ACCOUNT_ENTRIES = """
<FlexQueryResponse queryName="MissingAccountEntryQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <CorporateActions>
        <CorporateAction assetCategory="STK" symbol="DUP" description="DUPLICATE CO" conid="111111" isin="US1111111111" currency="USD" reportDate="2023-08-03" dateTime="2023-08-02;202500" actionDescription="DUP(US1111111111) EXAMPLE" quantity="5" type="TC" levelOfDetail="DETAIL" />
        <CorporateAction accountId="U1234567" assetCategory="STK" symbol="REAL" description="REAL CO" conid="222222" isin="US2222222222" currency="USD" reportDate="2023-08-03" dateTime="2023-08-02;202500" actionDescription="REAL(US2222222222) EXAMPLE" quantity="5" type="TC" />
      </CorporateActions>
      <CashTransactions>
        <CashTransaction type="Broker Interest Received" currency="USD" amount="99.99" description="Pseudo Interest" conid="" symbol="" dateTime="2023-08-15T00:00:00" assetCategory="" levelOfDetail="DETAIL" />
        <CashTransaction accountId="U1234567" type="Broker Interest Received" currency="USD" amount="25.50" description="Interest on Cash" conid="" symbol="" dateTime="2023-08-15T00:00:00" assetCategory="" />
      </CashTransactions>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="REAL" description="REAL CO" conid="222222" isin="US2222222222" currency="USD" position="5" markPrice="10.00" positionValue="50.00" reportDate="2023-12-31" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency currency="USD" endingCash="123.45" fromDate="2023-01-01" toDate="2023-12-31" levelOfDetail="DETAIL" />
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

SAMPLE_IBKR_FLEX_XML_WITH_HYPHEN_ACCOUNT_ENTRIES = """
<FlexQueryResponse queryName="HyphenAccountEntryQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <CorporateActions>
        <CorporateAction accountId="-" assetCategory="STK" symbol="DUP" description="DUPLICATE CO" conid="111111" isin="US1111111111" currency="USD" reportDate="2023-08-03" dateTime="2023-08-02;202500" actionDescription="DUP(US1111111111) EXAMPLE" quantity="5" type="TC" levelOfDetail="SUMMARY" />
        <CorporateAction accountId="U1234567" assetCategory="STK" symbol="REAL" description="REAL CO" conid="222222" isin="US2222222222" currency="USD" reportDate="2023-08-03" dateTime="2023-08-02;202500" actionDescription="REAL(US2222222222) EXAMPLE" quantity="5" type="TC" />
      </CorporateActions>
      <CashTransactions>
        <CashTransaction accountId="-" type="Broker Interest Received" currency="USD" amount="99.99" description="Pseudo Interest" conid="" symbol="" dateTime="2023-08-15T00:00:00" assetCategory="" levelOfDetail="SUMMARY" />
        <CashTransaction accountId="U1234567" type="Broker Interest Received" currency="USD" amount="25.50" description="Interest on Cash" conid="" symbol="" dateTime="2023-08-15T00:00:00" assetCategory="" />
      </CashTransactions>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="REAL" description="REAL CO" conid="222222" isin="US2222222222" currency="USD" position="5" markPrice="10.00" positionValue="50.00" reportDate="2023-12-31" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency accountId="-" currency="USD" endingCash="123.45" fromDate="2023-01-01" toDate="2023-12-31" levelOfDetail="SUMMARY" />
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
        assert msft_sec.country == "US"
        assert len(msft_sec.stock) == 2
        # No peroid start stock entry needed because initial position is zero
        assert msft_sec.stock[0].mutation is True  # Trade
        assert msft_sec.stock[0].quantity == Decimal("10")
        assert msft_sec.stock[1].mutation is False
        assert msft_sec.stock[1].referenceDate == date(2024, 1, 1)
        assert msft_sec.stock[1].quantity == Decimal("10")
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
        assert aapl_sec.country == "IE"
        assert len(aapl_sec.stock) == 3
        # Peroid start stock entry needed because initial position is not zero
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


def test_ibkr_import_keeps_entries_with_missing_account_id(sample_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_WITH_MISSING_ACCOUNT_ENTRIES)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement.listOfSecurities is not None
        assert len(tax_statement.listOfSecurities.depot) == 1

        depot = tax_statement.listOfSecurities.depot[0]
        assert depot.depotNumber == "U1234567"
        assert len(depot.security) == 2
        security_names = {security.securityName for security in depot.security}
        assert security_names == {"DUPLICATE CO (DUP)", "REAL CO (REAL)"}

        assert tax_statement.listOfBankAccounts is not None
        assert len(tax_statement.listOfBankAccounts.bankAccount) == 1
        bank_account = tax_statement.listOfBankAccounts.bankAccount[0]
        assert bank_account.bankAccountNumber == "U1234567-USD"
        assert bank_account.taxValue is not None
        assert bank_account.taxValue.balance == Decimal("0")
        assert len(bank_account.payment) == 2
        payment_amounts = {payment.amount for payment in bank_account.payment}
        assert payment_amounts == {Decimal("99.99"), Decimal("25.50")}
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_import_skips_hyphen_account_entries(sample_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_WITH_HYPHEN_ACCOUNT_ENTRIES)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement.listOfSecurities is not None
        assert len(tax_statement.listOfSecurities.depot) == 1

        depot = tax_statement.listOfSecurities.depot[0]
        assert depot.depotNumber == "U1234567"
        assert len(depot.security) == 1
        assert depot.security[0].securityName == "REAL CO (REAL)"

        assert tax_statement.listOfBankAccounts is not None
        assert len(tax_statement.listOfBankAccounts.bankAccount) == 1
        bank_account = tax_statement.listOfBankAccounts.bankAccount[0]
        assert bank_account.bankAccountNumber == "U1234567-USD"
        assert bank_account.taxValue is not None
        assert bank_account.taxValue.balance == Decimal("0")
        assert len(bank_account.payment) == 1
        assert bank_account.payment[0].amount == Decimal("25.50")
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
                assert payment.nonRecoverableTax is None
                assert payment.nonRecoverableTaxAmountOriginal == Decimal("1.85")
                assert payment.broker_label_original == "Withholding Tax"
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


def test_transfer_with_open_position_no_trades(sample_ibkr_settings):
    """
    Test inbound position transfer with no other transactions.
    
    When there is only an inbound transfer (FOP) with an OpenPosition at year-end
    but no other trades, the position should be correctly tracked with:
    - Opening balance of 0 at period start
    - A mutation entry for the transfer
    - Closing balance matching the OpenPosition at period end + 1
    """
    period_from = date(2025, 1, 1)
    period_to = date(2025, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_TRANSFER_ONLY_WITH_OPEN_POSITION)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])

        # Verify securities were created
        assert tax_statement.listOfSecurities is not None
        assert len(tax_statement.listOfSecurities.depot) == 1
        
        depot = tax_statement.listOfSecurities.depot[0]
        assert depot.depotNumber == "U1234567"
        
        # Find the IWDA security
        iwda_sec = next(
            (s for s in depot.security if s.isin == "IE00B4L5Y983"),
            None,
        )
        assert iwda_sec is not None, "IWDA security should be present"
        assert iwda_sec.currency == "EUR"
        assert iwda_sec.country == "IE"
        
        # Check stock entries: should have a transfer mutation and a closing balance (no opening balance at period start)
        assert len(iwda_sec.stock) == 2, f"Expected 2 stock entries (transfer, closing), got {len(iwda_sec.stock)}"
        
        # Transfer mutation should exist
        transfer_mutations = [s for s in iwda_sec.stock if s.mutation]
        assert len(transfer_mutations) == 1, "Should have exactly one transfer mutation"
        transfer = transfer_mutations[0]
        assert transfer.quantity == Decimal("13"), f"Transfer quantity should be 13, got {transfer.quantity}"
        assert transfer.referenceDate == date(2025, 8, 13), "Transfer date should be 2025-08-13"
        assert "FOP" in transfer.name, f"Transfer name should contain 'FOP', got {transfer.name}"
        
        # Closing balance at period end + 1 should be 13
        end_plus_one = period_to + timedelta(days=1)
        closing_balance = next(
            (s for s in iwda_sec.stock if not s.mutation and s.referenceDate == end_plus_one),
            None,
        )
        assert closing_balance is not None, "Closing balance entry should exist"
        assert closing_balance.quantity == Decimal("13"), f"Closing balance should be 13, got {closing_balance.quantity}"
        
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_open_position_only_no_mutations(sample_ibkr_settings):
    """
    Test OpenPosition only with no mutations.
    
    When there is only an OpenPosition at year-end but no trades, transfers or
    corporate actions (e.g., position was transferred in a previous year),
    the position should be correctly tracked with:
    - Opening balance matching closing balance at period start
    - Closing balance matching the OpenPosition at period end + 1
    """
    period_from = date(2025, 1, 1)
    period_to = date(2025, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_OPEN_POSITION_ONLY)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])

        # Verify securities were created
        assert tax_statement.listOfSecurities is not None
        assert len(tax_statement.listOfSecurities.depot) == 1
        
        depot = tax_statement.listOfSecurities.depot[0]
        
        # Find the IWDA security
        iwda_sec = next(
            (s for s in depot.security if s.isin == "IE00B4L5Y983"),
            None,
        )
        assert iwda_sec is not None, "IWDA security should be present"
        
        # Check stock entries: should have opening balance and closing balance only
        # No mutations since there were no trades/transfers/corporate actions
        mutations = [s for s in iwda_sec.stock if s.mutation]
        assert len(mutations) == 0, "Should have no mutations"
        
        balances = [s for s in iwda_sec.stock if not s.mutation]
        assert len(balances) == 2, f"Should have 2 balance entries (opening and closing), got {len(balances)}"
        
        # Opening balance at period start should be 13 (same as closing, no changes)
        opening_balance = next(
            (s for s in iwda_sec.stock if not s.mutation and s.referenceDate == period_from),
            None,
        )
        assert opening_balance is not None, "Opening balance entry should exist"
        assert opening_balance.quantity == Decimal("13"), f"Opening balance should be 13, got {opening_balance.quantity}"
        
        # Closing balance at period end + 1 should be 13
        end_plus_one = period_to + timedelta(days=1)
        closing_balance = next(
            (s for s in iwda_sec.stock if not s.mutation and s.referenceDate == end_plus_one),
            None,
        )
        assert closing_balance is not None, "Closing balance entry should exist"
        assert closing_balance.quantity == Decimal("13"), f"Closing balance should be 13, got {closing_balance.quantity}"
        
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
        # Should aggregate into a single trade entry per security and ibOrderID if present
        assert len(msft_sec.stock) == 3
        assert msft_sec.stock[0].quantity == Decimal("10")
        assert msft_sec.stock[0].unitPrice == Decimal("280.50")
        assert msft_sec.stock[1].quantity == Decimal("10")
        assert msft_sec.stock[1].unitPrice == Decimal("282.0")
        assert len(aapl_sec.stock) == 3
        assert aapl_sec.stock[1].quantity == Decimal("-5")
        assert aapl_sec.stock[1].unitPrice == Decimal("179.70")
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
            self.dateOpened = None
            self.dateClosed = None
            self.stateResidentialAddress = None

    class DummyFlexStatement:
        def __init__(self) -> None:
            self.accountId = "U1111111"
            self.fromDate = period_from
            self.toDate = period_to
            self.AccountInformation = DummyAccountInfo()
            self.Trades = []
            self.OpenPositions = []
            self.Transfers = []
            self.CorporateActions = []
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


def test_corporate_action_stock_split_creates_mutation(sample_ibkr_settings):
    period_from = date(2025, 1, 1)
    period_to = date(2025, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_STOCK_SPLIT)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement.listOfSecurities is not None
        depot = tax_statement.listOfSecurities.depot[0]
        ibkr_sec = next(
            (s for s in depot.security if s.securityName == "INTERACTIVE BROKERS GRO-CL A (IBKR)"),
            None,
        )
        assert ibkr_sec is not None

        split_mutation = next(
            (s for s in ibkr_sec.stock if s.mutation and s.referenceDate == date(2025, 6, 18)),
            None,
        )
        assert split_mutation is not None
        assert split_mutation.quantity == Decimal("6")
        assert "SPLIT 4 FOR 1" in split_mutation.name

        opening_balance = next(
            (s for s in ibkr_sec.stock if not s.mutation and s.referenceDate == period_from),
            None,
        )
        assert opening_balance is not None
        assert opening_balance.quantity == Decimal("2")
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_corporate_action_exchange_creates_mutations(sample_ibkr_settings):
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_IBKR_FLEX_XML_CORPORATE_ACTION_EXCHANGE)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement.listOfSecurities is not None
        depot = tax_statement.listOfSecurities.depot[0]

        for isin in ("US9279591062", "US64361Q1013"):
            security = next((s for s in depot.security if s.isin == isin), None)
            assert security is not None
            mutation = next((s for s in security.stock if s.mutation), None)
            assert mutation is not None
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


def test_ibkr_import_canton_extraction(sample_ibkr_settings):
    """Test that canton is extracted from IBKR stateResidentialAddress."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)
    
    # Create XML with AccountInformation containing stateResidentialAddress
    xml_with_canton = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <AccountInformation accountId="U1234567" name="John Doe" stateResidentialAddress="CH-ZH" />
      <Trades>
        <Trade transactionID="1001" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" issuerCountryCode="US" currency="USD" quantity="10" tradeDate="2023-03-15" settleDateTarget="2023-03-17" tradePrice="280.00" tradeMoney="2800.00" buySell="BUY" ibCommission="-1.00" ibCommissionCurrency="USD" netCash="-2801.00" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" issuerCountryCode="US" currency="USD" position="10" markPrice="300.00" positionValue="3000.00" reportDate="2023-12-31" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="1000.00" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""
    
    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_with_canton)
        xml_file_path = tmp_file.name
    
    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        
        # Verify canton was extracted and set
        assert tax_statement.canton == "ZH"
        
        # Verify client was created (from name field)
        assert tax_statement.client is not None
        assert len(tax_statement.client) == 1
        assert tax_statement.client[0].lastName == "Doe"
        
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_import_canton_extraction_different_cantons(sample_ibkr_settings):
    """Test canton extraction works with different Swiss cantons."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)
    
    test_cantons = ["ZH", "BE", "GE", "VD", "ZG", "TI"]
    
    for canton in test_cantons:
        xml_content = f"""
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <AccountInformation accountId="U1234567" name="Jane Smith" stateResidentialAddress="CH-{canton}" />
      <Trades />
      <OpenPositions />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""
        
        importer = IbkrImporter(
            period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
        )
        
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
            tmp_file.write(xml_content)
            xml_file_path = tmp_file.name
        
        try:
            tax_statement = importer.import_files([xml_file_path])
            assert tax_statement is not None
            assert tax_statement.canton == canton, f"Expected canton {canton}, got {tax_statement.canton}"
        finally:
            if os.path.exists(xml_file_path):
                os.remove(xml_file_path)


def test_ibkr_import_canton_extraction_invalid_format(sample_ibkr_settings):
    """Test that invalid canton formats are handled gracefully."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)
    
    # Test with non-CH country code
    xml_with_invalid_country = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <AccountInformation accountId="U1234567" name="John Doe" stateResidentialAddress="US-NY" />
      <Trades />
      <OpenPositions />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""
    
    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_with_invalid_country)
        xml_file_path = tmp_file.name
    
    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        # Canton should not be set for non-CH address
        assert tax_statement.canton is None
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_import_canton_extraction_invalid_swiss_canton(sample_ibkr_settings):
    """Test that invalid Swiss canton codes are handled gracefully."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)
    
    # Test with invalid Swiss canton code
    xml_with_invalid_canton = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <AccountInformation accountId="U1234567" name="John Doe" stateResidentialAddress="CH-XX" />
      <Trades />
      <OpenPositions />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""
    
    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_with_invalid_canton)
        xml_file_path = tmp_file.name
    
    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        # Canton should not be set for invalid canton code
        assert tax_statement.canton is None
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_import_account_dates_set_on_bank_accounts(sample_ibkr_settings):
    """Test that dateOpened and dateClosed from AccountInformation are set on bank accounts."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    xml_with_dates = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <AccountInformation accountId="U1234567" name="John Doe" dateOpened="2023-05-29" dateClosed="" />
      <Trades>
        <Trade transactionID="1001" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" issuerCountryCode="US" currency="USD" quantity="10" tradeDate="2023-06-15" settleDateTarget="2023-06-17" tradePrice="280.00" tradeMoney="2800.00" buySell="BUY" ibCommission="-1.00" ibCommissionCurrency="USD" netCash="-2801.00" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" issuerCountryCode="US" currency="USD" position="10" markPrice="300.00" positionValue="3000.00" reportDate="2023-12-31" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="1000.00" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_with_dates)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None

        # Verify bank accounts have the opening date set
        assert tax_statement.listOfBankAccounts is not None
        for ba in tax_statement.listOfBankAccounts.bankAccount:
            assert ba.openingDate == date(2023, 5, 29), (
                f"Expected openingDate 2023-05-29 on account {ba.bankAccountNumber}, got {ba.openingDate}"
            )
            # dateClosed was empty, so should be None
            assert ba.closingDate is None, (
                f"Expected closingDate None on account {ba.bankAccountNumber}, got {ba.closingDate}"
            )
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_import_account_dates_both_set(sample_ibkr_settings):
    """Test that both dateOpened and dateClosed are set when provided."""
    period_from = date(2024, 1, 1)
    period_to = date(2024, 12, 31)

    xml_with_both_dates = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2024-01-01" toDate="2024-12-31" period="Year" whenGenerated="2025-01-15T10:00:00">
      <AccountInformation accountId="U1234567" name="John Doe" dateOpened="2024-03-01" dateClosed="2024-09-15" />
      <Trades />
      <OpenPositions />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="0" fromDate="2024-01-01" toDate="2024-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_with_both_dates)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        assert tax_statement.listOfBankAccounts is not None
        for ba in tax_statement.listOfBankAccounts.bankAccount:
            assert ba.openingDate == date(2024, 3, 1)
            assert ba.closingDate == date(2024, 9, 15)
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_import_account_dates_scoped_to_own_statement(sample_ibkr_settings):
    """Test that dates from one flex statement do not leak to bank accounts of another."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    # Two flex statements in a single response: first account has dates, second does not
    xml_two_accounts = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="2">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <AccountInformation accountId="U1234567" name="John Doe" dateOpened="2023-05-29" />
      <Trades />
      <OpenPositions />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="500.00" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
    <FlexStatement accountId="U7777777" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <AccountInformation accountId="U7777777" name="Jane Smith" />
      <Trades />
      <OpenPositions />
      <CashReport>
        <CashReportCurrency accountId="U7777777" currency="EUR" startingCash="0" endingCash="100.00" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

    settings = [
        IbkrAccountSettings(
            account_number="U1234567",
            broker_name="Interactive Brokers",
            account_name_alias="Acct 1",
            canton="ZH",
            full_name="John Doe",
        ),
        IbkrAccountSettings(
            account_number="U7777777",
            broker_name="Interactive Brokers",
            account_name_alias="Acct 2",
            canton="ZH",
            full_name="Jane Smith",
        ),
    ]

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_two_accounts)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        assert tax_statement.listOfBankAccounts is not None
        assert len(tax_statement.listOfBankAccounts.bankAccount) == 2

        acct1_ba = next(
            (ba for ba in tax_statement.listOfBankAccounts.bankAccount if ba.bankAccountCurrency == "USD"),
            None,
        )
        acct2_ba = next(
            (ba for ba in tax_statement.listOfBankAccounts.bankAccount if ba.bankAccountCurrency == "EUR"),
            None,
        )
        assert acct1_ba is not None
        assert acct2_ba is not None

        # U1234567 has dateOpened -> should be set on its bank accounts
        assert acct1_ba.openingDate == date(2023, 5, 29)
        assert acct1_ba.closingDate is None

        # U7777777 has no dates -> should NOT inherit U1234567's dates
        assert acct2_ba.openingDate is None, (
            f"U7777777 bank account should have openingDate=None but got {acct2_ba.openingDate}"
        )
        assert acct2_ba.closingDate is None
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_import_account_dates_not_set_when_absent(sample_ibkr_settings):
    """Test that openingDate/closingDate are None when AccountInformation has no dates."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    xml_no_dates = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <AccountInformation accountId="U1234567" name="John Doe" />
      <Trades />
      <OpenPositions />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="100.00" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_no_dates)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        assert tax_statement.listOfBankAccounts is not None
        for ba in tax_statement.listOfBankAccounts.bankAccount:
            assert ba.openingDate is None
            assert ba.closingDate is None
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_ibkr_import_canton_extraction_no_account_info(sample_ibkr_settings):
    """Test that missing AccountInformation doesn't cause errors."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)
    
    xml_without_account_info = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades />
      <OpenPositions />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""
    
    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_without_account_info)
        xml_file_path = tmp_file.name
    
    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        # Canton should not be set without AccountInformation
        assert tax_statement.canton is None
        # Client should also not be created
        assert len(tax_statement.client) == 0
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


# ---------------------------------------------------------------------------
# Unknown-attribute tolerance tests
#
# The production driver (steuerauszug.py) calls
# ibflex.enable_unknown_attribute_tolerance() before importing IBKR data so
# that new fields added by Interactive Brokers don't break parsing.  Tests
# keep the default *strict* mode to catch regressions; the tests below
# explicitly toggle tolerance to verify the feature works.
# See: https://github.com/vroonhof/opensteuerauszug/issues/48
# ---------------------------------------------------------------------------

# XML fragment with fabricated unknown attributes on known element types.
_XML_WITH_UNKNOWN_ATTRS = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <Trade transactionID="3001" accountId="U1234567" assetCategory="STK"
               symbol="MSFT" description="MICROSOFT CORP" conid="272120"
               isin="US5949181045" currency="USD" quantity="10"
               tradeDate="2023-03-15" settleDateTarget="2023-03-17"
               tradePrice="280.00" tradeMoney="2800.00" buySell="BUY"
               ibCommission="-1.00" ibCommissionCurrency="USD" netCash="-2801.00"
               futureField="some_value" newMetric="42" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="MSFT"
                      description="MICROSOFT CORP" conid="272120"
                      isin="US5949181045" currency="USD" position="10"
                      markPrice="300.00" positionValue="3000.00"
                      reportDate="2023-12-31" extraInfo="hello" />
      </OpenPositions>
      <CashTransactions>
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD"
                         amount="50.00" description="MSFT Dividend"
                         conid="272120" symbol="MSFT"
                         dateTime="2023-09-05T00:00:00" assetCategory="STK"
                         unknownFlag="Y" />
      </CashTransactions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD"
                            startingCash="0" endingCash="3148.50"
                            fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

# XML fragment with an entirely unknown element type inside FlexStatement.
_XML_WITH_UNKNOWN_ELEMENT = """
<FlexQueryResponse queryName="TestQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <Trade transactionID="4001" accountId="U1234567" assetCategory="STK"
               symbol="AAPL" description="APPLE INC" conid="265598"
               isin="US0378331005" currency="USD" quantity="5"
               tradeDate="2023-06-20" settleDateTarget="2023-06-22"
               tradePrice="180.00" tradeMoney="900.00" buySell="BUY"
               ibCommission="-0.50" ibCommissionCurrency="USD" netCash="-900.50" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="AAPL"
                      description="APPLE INC" conid="265598"
                      isin="US0378331005" currency="USD" position="5"
                      markPrice="190.00" positionValue="950.00"
                      reportDate="2023-12-31" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD"
                            startingCash="0" endingCash="0"
                            fromDate="2023-01-01" toDate="2023-12-31" />
      </CashReport>
      <HypotheticalNewSection>
        <HypotheticalNewEntry accountId="U1234567" someField="value" anotherField="123" />
      </HypotheticalNewSection>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


@pytest.fixture()
def _enable_unknown_attribute_tolerance():
    """Temporarily enable ibflex unknown-attribute tolerance for a single test."""
    import ibflex
    ibflex.enable_unknown_attribute_tolerance()
    yield
    ibflex.disable_unknown_attribute_tolerance()


def test_strict_mode_rejects_unknown_xml_attributes(sample_ibkr_settings):
    """In strict mode (the default for tests), unknown attributes must raise an error."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(_XML_WITH_UNKNOWN_ATTRS)
        xml_file_path = tmp_file.name

    try:
        with pytest.raises((ValueError, RuntimeError)):
            importer.import_files([xml_file_path])
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


@pytest.mark.usefixtures("_enable_unknown_attribute_tolerance")
def test_unknown_xml_attributes_are_silently_ignored(sample_ibkr_settings):
    """With tolerance enabled, unknown attributes must not break parsing.

    The production driver enables this mode before importing IBKR data so
    that new fields added by Interactive Brokers are silently ignored.
    """
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(_XML_WITH_UNKNOWN_ATTRS)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        assert tax_statement.listOfSecurities is not None
        assert len(tax_statement.listOfSecurities.depot) == 1
        depot = tax_statement.listOfSecurities.depot[0]
        assert len(depot.security) == 1
        assert "MICROSOFT" in depot.security[0].securityName
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


@pytest.mark.usefixtures("_enable_unknown_attribute_tolerance")
def test_unknown_xml_element_types_are_silently_ignored(sample_ibkr_settings):
    """With tolerance enabled, unknown element types must not break parsing.

    IB may add entirely new XML element types (e.g. a hypothetical
    <NewReportSection>).  The tolerance mode must skip these gracefully.
    """
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=sample_ibkr_settings,
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(_XML_WITH_UNKNOWN_ELEMENT)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement is not None
        assert tax_statement.listOfSecurities is not None
        assert len(tax_statement.listOfSecurities.depot) == 1
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_withholding_tax_cash_transactions_are_mapped_to_security_tax_fields(sample_ibkr_settings):
    period_from = date(2025, 1, 1)
    period_to = date(2025, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    xml_content = f"""
<FlexQueryResponse queryName="WithholdingTaxMapping" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U123456" fromDate="{period_from}" toDate="{period_to}" period="Year" whenGenerated="2026-01-15T10:00:00">
      <Trades>
        <Trade transactionID="7001" accountId="U123456" assetCategory="STK" symbol="IREN" description="INFRACORE HOLDING AG" conid="238751851" isin="CH0325094297" issuerCountryCode="CH" currency="CHF" quantity="10" tradeDate="2025-01-10" settleDateTarget="2025-01-14" tradePrice="10" tradeMoney="100" buySell="BUY" ibCommission="-1" netCash="-101" />
        <Trade transactionID="7002" accountId="U123456" assetCategory="STK" symbol="ASML" description="ASML HOLDING" conid="117589399" isin="NL0010273215" issuerCountryCode="NL" currency="EUR" quantity="1" tradeDate="2025-01-10" settleDateTarget="2025-01-14" tradePrice="700" tradeMoney="700" buySell="BUY" ibCommission="-1" netCash="-701" />
      </Trades>
      <CashTransactions>
        <CashTransaction accountId="U123456" currency="CHF" assetCategory="STK" subCategory="COMMON" symbol="IREN" description="IREN(CH0325094297) CASH DIVIDEND CHF 2.60 PER SHARE - CH TAX" conid="238751851" isin="CH0325094297" issuerCountryCode="CH" dateTime="2025-05-12;202000" amount="-1234.56" type="Withholding Tax" levelOfDetail="DETAIL" />
        <CashTransaction accountId="U123456" currency="EUR" assetCategory="STK" subCategory="COMMON" symbol="ASML" description="ASML(NL0010273215) CASH DIVIDEND EUR 1.52 PER SHARE - NL TAX" conid="117589399" isin="NL0010273215" issuerCountryCode="NL" dateTime="2025-02-19;202000" amount="-1.13" type="Withholding Tax" levelOfDetail="DETAIL" />
      </CashTransactions>
      <CashReport>
        <CashReportCurrency accountId="U123456" currency="CHF" endingCash="0"/>
        <CashReportCurrency accountId="U123456" currency="EUR" endingCash="0"/>
      </CashReport>
      <OpenPositions>
        <OpenPosition accountId="U123456" assetCategory="STK" symbol="IREN" description="INFRACORE HOLDING AG" conid="238751851" isin="CH0325094297" currency="CHF" position="10" markPrice="12" positionValue="120" reportDate="{period_to}" />
        <OpenPosition accountId="U123456" assetCategory="STK" symbol="ASML" description="ASML HOLDING" conid="117589399" isin="NL0010273215" currency="EUR" position="1" markPrice="750" positionValue="750" reportDate="{period_to}" />
      </OpenPositions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(xml_content)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])

        assert tax_statement.listOfSecurities is not None
        assert len(tax_statement.listOfSecurities.depot) == 1
        securities = tax_statement.listOfSecurities.depot[0].security

        ireen = next(security for security in securities if security.isin == "CH0325094297")
        asml = next(security for security in securities if security.isin == "NL0010273215")

        assert len(ireen.payment) == 1
        assert ireen.payment[0].name == "IREN(CH0325094297) CASH DIVIDEND CHF 2.60 PER SHARE - CH TAX"
        assert ireen.payment[0].broker_label_original == "Withholding Tax"
        assert ireen.payment[0].amount == Decimal("-1234.56")
        assert ireen.payment[0].withHoldingTaxClaim == Decimal("1234.56")
        assert ireen.payment[0].nonRecoverableTax is None
        assert ireen.payment[0].nonRecoverableTaxAmountOriginal is None

        assert len(asml.payment) == 1
        assert asml.payment[0].name == "ASML(NL0010273215) CASH DIVIDEND EUR 1.52 PER SHARE - NL TAX"
        assert asml.payment[0].broker_label_original == "Withholding Tax"
        assert asml.payment[0].amount == Decimal("-1.13")
        assert asml.payment[0].nonRecoverableTax is None
        assert asml.payment[0].nonRecoverableTaxAmountOriginal == Decimal("1.13")
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)
