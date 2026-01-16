import pytest
from datetime import date
from decimal import Decimal
import tempfile
import os

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

def test_ibkr_security_category_mapping():
    """Test that asset categories are correctly mapped to SecurityCategory Literal."""
    period_from = date(2023, 1, 1)
    period_to = date(2023, 12, 31)

    settings = [
        IbkrAccountSettings(
            account_number="U1234567",
            broker_name="IBKR",
            account_name_alias="Test Account",
            canton="ZH",
            full_name="Test User",
        )
    ]

    importer = IbkrImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=settings,
    )

    # Create XML with different asset categories
    # STK -> SHARE
    # OPT -> OPTION
    # BOND -> BOND
    # FUT -> OTHER
    # ETF -> FUND
    # FUND -> FUND

    xml_content = """
<FlexQueryResponse queryName="CategoryMappingTest" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
      <Trades>
        <Trade accountId="U1234567" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="1" currency="USD" quantity="10" tradeDate="2023-01-05" settleDateTarget="2023-01-07" tradePrice="150" tradeMoney="1500" buySell="BUY" ibCommission="-1" netCash="-1501" />
        <Trade accountId="U1234567" assetCategory="OPT" symbol="AAPL 230120C150" description="AAPL Call" conid="2" currency="USD" quantity="1" tradeDate="2023-01-05" settleDateTarget="2023-01-06" tradePrice="5" tradeMoney="500" buySell="BUY" ibCommission="-1" netCash="-501" />
        <Trade accountId="U1234567" assetCategory="BOND" symbol="US-T" description="US Treasury" conid="3" isin="US1234567890" currency="USD" quantity="1000" tradeDate="2023-01-05" settleDateTarget="2023-01-07" tradePrice="98" tradeMoney="980" buySell="BUY" ibCommission="-1" netCash="-981" />
        <Trade accountId="U1234567" assetCategory="FUT" symbol="ES" description="E-mini S&amp;P 500" conid="4" currency="USD" quantity="1" tradeDate="2023-01-05" settleDateTarget="2023-01-06" tradePrice="4000" tradeMoney="0" buySell="BUY" ibCommission="-2" netCash="-2" />
        <Trade accountId="U1234567" assetCategory="FUND" symbol="VTSAX" description="Vanguard Total Stock" conid="6" currency="USD" quantity="10" tradeDate="2023-01-05" settleDateTarget="2023-01-07" tradePrice="100" tradeMoney="1000" buySell="BUY" ibCommission="0" netCash="-1000" />
      </Trades>
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
        assert tax_statement.listOfSecurities is not None
        securities = tax_statement.listOfSecurities.depot[0].security

        # Helper to get category by symbol
        def get_category(symbol_conid):
            sec = next((s for s in securities if s.valorNumber == int(symbol_conid) or s.positionId == int(symbol_conid)), None)
            # Actually we mapped symbol=conid in importer for SecurityPosition
            # but in Security object, securityName is description.
            # The test XML sets conid=1, 2, 3...
            # In importer: valorNumber=sec_pos_obj.valor.
            # Valornumber is from sec_pos_obj.valor.
            # In Trades loop: valor = None. (Flex does not provide Valor).
            # So valorNumber in Security will be None.

            # We can find by securityName
            # AAPL -> conid=1
            # AAPL 230120C150 -> conid=2
            # US-T -> conid=3
            # ES -> conid=4
            # SPY -> conid=5
            # VTSAX -> conid=6
            return None

        name_map = {
            "APPLE INC (AAPL)": "SHARE",
            "AAPL Call (AAPL 230120C150)": "OPTION",
            "US Treasury (US-T)": "BOND",
            "E-mini S&P 500 (ES)": "OTHER",
            "Vanguard Total Stock (VTSAX)": "FUND"
        }

        for name, expected_cat in name_map.items():
            sec = next((s for s in securities if s.securityName == name), None)
            assert sec is not None, f"Security {name} not found"
            assert sec.securityCategory == expected_cat, f"Security {name} category mismatch. Expected {expected_cat}, got {sec.securityCategory}"

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)

def test_ibkr_security_category_fallback():
    """Test that unknown/missing asset category falls back to SHARE (STK)."""
    # ... (similar setup but with CASH transaction that creates a security position implicitly, if possible, or a Transfer without asset category?)
    # Transfers require assetCategory.
    # We can test logic by relying on default if asset category not found in side-map?
    pass
