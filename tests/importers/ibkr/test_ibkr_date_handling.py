import os
import pytest
from datetime import date
from typing import List
import tempfile

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

@pytest.fixture
def sample_ibkr_settings() -> List[IbkrAccountSettings]:
    return [
        IbkrAccountSettings(
            account_number="U1234567",
            broker_name="Interactive Brokers",
            account_name_alias="Test IBKR Account",
            canton="ZH",
            full_name="Test User",
        )
    ]

def test_ibkr_importer_uses_statement_dates(sample_ibkr_settings):
    """Test that the importer uses dates from the XML file, not the ones passed to __init__."""
    # Dates passed to __init__ (requested period)
    requested_from = date(2023, 1, 1)
    requested_to = date(2023, 12, 31)

    # Dates in the XML file (actual statement period, e.g. partial year)
    xml_from = date(2023, 6, 1)
    xml_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=requested_from,
        period_to=requested_to,
        account_settings_list=sample_ibkr_settings
    )

    xml_content = f"""
<FlexQueryResponse queryName="DateTest" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="{xml_from}" toDate="{xml_to}" period="Custom" whenGenerated="2024-01-15T10:00:00">
      <Trades>
         <Trade transactionID="1001" accountId="U1234567" assetCategory="STK" symbol="MSFT" description="MICROSOFT CORP" conid="272120" isin="US5949181045" issuerCountryCode="US" currency="USD" quantity="10" tradeDate="2023-06-15" settleDateTarget="2023-06-17" tradePrice="300.00" tradeMoney="3000.00" buySell="BUY" ibCommission="-1.00" ibCommissionCurrency="USD" netCash="-3001.00" />
      </Trades>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="{xml_from}" toDate="{xml_to}" />
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

        # Verify that TaxStatement uses the dates from XML
        assert tax_statement.periodFrom == xml_from
        assert tax_statement.periodTo == xml_to

        # Verify it didn't use the requested dates
        assert tax_statement.periodFrom != requested_from

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)

def test_ibkr_importer_multiple_statements_dates(sample_ibkr_settings):
    """Test that the importer correctly determines min/max dates from multiple statements."""
    requested_from = date(2023, 1, 1)
    requested_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=requested_from,
        period_to=requested_to,
        account_settings_list=sample_ibkr_settings
    )

    # Statement 1: Jan to June
    s1_from = date(2023, 1, 1)
    s1_to = date(2023, 6, 30)

    # Statement 2: July to Dec
    s2_from = date(2023, 7, 1)
    s2_to = date(2023, 12, 31)

    xml_content = f"""
<FlexQueryResponse queryName="MultiDateTest" type="AF">
  <FlexStatements count="2">
    <FlexStatement accountId="U1234567" fromDate="{s1_from}" toDate="{s1_to}" period="Custom" whenGenerated="2024-01-15T10:00:00">
      <Trades />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" />
      </CashReport>
    </FlexStatement>
    <FlexStatement accountId="U1234567" fromDate="{s2_from}" toDate="{s2_to}" period="Custom" whenGenerated="2024-01-15T10:00:00">
      <Trades />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" />
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

        # Verify min start and max end
        assert tax_statement.periodFrom == s1_from
        assert tax_statement.periodTo == s2_to

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)
