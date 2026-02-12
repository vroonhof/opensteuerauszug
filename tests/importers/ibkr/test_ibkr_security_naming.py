import os
import pytest
from datetime import date
from decimal import Decimal
import tempfile
from typing import List

from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.config.models import IbkrAccountSettings

# Check if ibflex is available, skip tests if not
try:
    from ibflex import parser as ibflex_parser
    IBFLEX_INSTALLED = True
except ImportError:
    IBFLEX_INSTALLED = False

pytestmark = pytest.mark.skipif(
    not IBFLEX_INSTALLED, reason="ibflex library is not installed"
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

def test_corporate_action_with_issuer(sample_ibkr_settings):
    """
    Test case where CorporateAction has a clean 'issuer' field.
    Expectation: Use 'issuer' as name.
    """
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    xml_content = """
<FlexQueryResponse queryName="IssuerTest" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <CorporateActions>
        <CorporateAction accountId="U1234567" assetCategory="STK" symbol="LONGNAME"
                         description="VERY LONG DESCRIPTION OF A SECURITY THAT SHOULD BE SHORTER (LONGNAME)"
                         conid="999999" isin="US9999999999" currency="USD"
                         reportDate="2023-06-01" dateTime="2023-06-01;120000"
                         actionDescription="SOME ACTION" quantity="0" type="TC"
                         issuer="CLEAN ISSUER NAME" />
      </CorporateActions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
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
        depot = tax_statement.listOfSecurities.depot[0]
        sec = next((s for s in depot.security if s.isin == "US9999999999"), None)
        assert sec is not None

        # Expectation: "CLEAN ISSUER NAME (LONGNAME)"
        expected_name = "CLEAN ISSUER NAME (LONGNAME)"
        print(f"Actual security name (Issuer Test): {sec.securityName}")
        assert sec.securityName == expected_name
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_corporate_action_no_issuer_long_description(sample_ibkr_settings):
    """
    Test case where CorporateAction has NO 'issuer' and a LONG description.
    Expectation: Use 'symbol' as fallback name.
    """
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    long_desc = "A" * 60  # 60 chars
    xml_content = f"""
<FlexQueryResponse queryName="LongDescTest" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <CorporateActions>
        <CorporateAction accountId="U1234567" assetCategory="STK" symbol="SYMB"
                         description="{long_desc}"
                         conid="888888" isin="US8888888888" currency="USD"
                         reportDate="2023-06-01" dateTime="2023-06-01;120000"
                         actionDescription="SOME ACTION" quantity="0" type="TC" />
      </CorporateActions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
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
        depot = tax_statement.listOfSecurities.depot[0]
        sec = next((s for s in depot.security if s.isin == "US8888888888"), None)
        assert sec is not None

        # Expectation: "SYMB (SYMB)"
        expected_name = "SYMB (SYMB)"
        print(f"Actual security name (Long Desc Test): {sec.securityName}")
        assert sec.securityName == expected_name
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)


def test_corporate_action_no_issuer_short_description(sample_ibkr_settings):
    """
    Test case where CorporateAction has NO 'issuer' and a SHORT description.
    Expectation: Use description as name.
    """
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    importer = IbkrImporter(
        period_from=period_from, period_to=period_to, account_settings_list=sample_ibkr_settings
    )

    short_desc = "SHORT DESC"
    xml_content = f"""
<FlexQueryResponse queryName="ShortDescTest" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <CorporateActions>
        <CorporateAction accountId="U1234567" assetCategory="STK" symbol="SYMB"
                         description="{short_desc}"
                         conid="777777" isin="US7777777777" currency="USD"
                         reportDate="2023-06-01" dateTime="2023-06-01;120000"
                         actionDescription="SOME ACTION" quantity="0" type="TC" />
      </CorporateActions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" endingCash="0" fromDate="2023-01-01" toDate="2023-12-31" />
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
        depot = tax_statement.listOfSecurities.depot[0]
        sec = next((s for s in depot.security if s.isin == "US7777777777"), None)
        assert sec is not None

        # Expectation: "SHORT DESC (SYMB)"
        expected_name = "SHORT DESC (SYMB)"
        print(f"Actual security name (Short Desc Test): {sec.securityName}")
        assert sec.securityName == expected_name
    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)
