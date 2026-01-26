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
    not IBFLEX_INSTALLED, reason="ibflex library is not installed, skipping IBKR importer tests"
)

# XML content from the issue, wrapped in minimal structure
SAMPLE_RIGHTS_ISSUE_XML = """
<FlexQueryResponse queryName="RightsIssueTest" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="F2345789" fromDate="2024-01-01" toDate="2024-12-31" period="Year" whenGenerated="2025-01-15T10:00:00">
      <CorporateActions>
        <CorporateAction accountId="F2345789" acctAlias="" model="" currency="CHF" fxRateToBase="1" assetCategory="STK" subCategory="RIGHT" symbol="DRPF1" description="DRPF(CH0026465366) SUBSCRIBABLE RIGHTS ISSUE  1 FOR 1 (DRPF1, UBS PROPERTY FUND DIRECT-RTS, CH1379144913)" conid="737556172" securityID="CH1379144913" securityIDType="ISIN" cusip="" isin="CH1379144913" figi="BBG01Q0RQ299" listingExchange="EBS" underlyingConid="" underlyingSymbol="DRPF1" underlyingSecurityID="" underlyingListingExchange="" issuer="" issuerCountryCode="CH" multiplier="1" strike="" expiry="" putCall="" principalAdjustFactor="" reportDate="2024-10-24" dateTime="2024-10-23;202500" actionDescription="DRPF(CH0026465366) SUBSCRIBABLE RIGHTS ISSUE  1 FOR 1 (DRPF1, UBS PROPERTY FUND DIRECT-RTS, CH1379144913)" amount="0" proceeds="0" value="0" quantity="1208" costBasis="" fifoPnlRealized="0" mtmPnl="0" code="" type="RI" transactionID="99999795846" actionID="999998964" levelOfDetail="DETAIL" serialNumber="" deliveryType="" commodityType="" fineness="0.0" weight="0.0" />
        <CorporateAction accountId="F2345789" acctAlias="" model="" currency="CHF" fxRateToBase="1" assetCategory="STK" subCategory="RIGHT" symbol="DRPF.RTS2" description="DRPF1.OLD(CH1379144913) SUBSCRIBES TO (SUDRP2411081) 1 FOR 10 FOR CHF -1.49 PER SHARE (DRPF.RTS2, UBS PROPERTY FUND DIRECT RES - RIGHTS SUBSCRIPTION, SUDRP2411081)" conid="739043271" securityID="SUDRP2411081" securityIDType="ISIN" cusip="" isin="SUDRP2411081" figi="" listingExchange="CORPACT" underlyingConid="" underlyingSymbol="DRPF.RTS2" underlyingSecurityID="" underlyingListingExchange="" issuer="" issuerCountryCode="XX" multiplier="1" strike="" expiry="" putCall="" principalAdjustFactor="" reportDate="2024-10-31" dateTime="2024-10-31;194500" actionDescription="DRPF1.OLD(CH1379144913) SUBSCRIBES TO (SUDRP2411081) 1 FOR 10 FOR CHF -1.49 PER SHARE (DRPF.RTS2, UBS PROPERTY FUND DIRECT RES - RIGHTS SUBSCRIPTION, SUDRP2411081)" amount="0" proceeds="0" value="2363.95" quantity="120" costBasis="" fifoPnlRealized="0" mtmPnl="0" code="" type="SR" transactionID="99999255351" actionID="999999726" levelOfDetail="DETAIL" serialNumber="" deliveryType="" commodityType="" fineness="0.0" weight="0.0" />
        <CorporateAction accountId="F2345789" acctAlias="" model="" currency="CHF" fxRateToBase="1" assetCategory="STK" subCategory="RIGHT" symbol="DRPF1.OLD" description="DRPF1.OLD(CH1379144913) SUBSCRIBES TO (SUDRP2411081) 1 FOR 10 FOR CHF -1.49 PER SHARE (DRPF1.OLD, UBS PROPERTY FUND DIRECT-RTS, CH1379144913)" conid="737556172" securityID="CH1379144913" securityIDType="ISIN" cusip="" isin="CH1379144913" figi="BBG01Q0RQ299" listingExchange="VALUE" underlyingConid="" underlyingSymbol="DRPF1.OLD" underlyingSecurityID="" underlyingListingExchange="" issuer="" issuerCountryCode="CH" multiplier="1" strike="" expiry="" putCall="" principalAdjustFactor="" reportDate="2024-10-31" dateTime="2024-10-31;194500" actionDescription="DRPF1.OLD(CH1379144913) SUBSCRIBES TO (SUDRP2411081) 1 FOR 10 FOR CHF -1.49 PER SHARE (DRPF1.OLD, UBS PROPERTY FUND DIRECT-RTS, CH1379144913)" amount="1788" proceeds="-1788" value="-575.83" quantity="-1200" costBasis="" fifoPnlRealized="0" mtmPnl="0" code="" type="SR" transactionID="99999255352" actionID="999999726" levelOfDetail="DETAIL" serialNumber="" deliveryType="" commodityType="" fineness="0.0" weight="0.0" />
        <CorporateAction accountId="F2345789" acctAlias="" model="" currency="CHF" fxRateToBase="1" assetCategory="STK" subCategory="CLOSED-END FUND" symbol="DRPF" description="DRPF.RTS2(SUDRP2411081) MERGED(Voluntary Offer Allocation) WITH CH0026465366 1 FOR 1 (DRPF, UBS PROPERTY FUND DIRECT RES, CH0026465366)" conid="112129667" securityID="CH0026465366" securityIDType="ISIN" cusip="" isin="CH0026465366" figi="BBG001852ZW2" listingExchange="EBS" underlyingConid="" underlyingSymbol="DRPF" underlyingSecurityID="" underlyingListingExchange="" issuer="" issuerCountryCode="CH" multiplier="1" strike="" expiry="" putCall="" principalAdjustFactor="" reportDate="2024-11-08" dateTime="2024-11-07;202500" actionDescription="DRPF.RTS2(SUDRP2411081) MERGED(Voluntary Offer Allocation) WITH CH0026465366 1 FOR 1 (DRPF, UBS PROPERTY FUND DIRECT RES, CH0026465366)" amount="0" proceeds="0" value="2259.19" quantity="120" costBasis="" fifoPnlRealized="0" mtmPnl="0" code="" type="TC" transactionID="99999497352" actionID="999994293" levelOfDetail="DETAIL" serialNumber="" deliveryType="" commodityType="" fineness="0.0" weight="0.0" />
        <CorporateAction accountId="F2345789" acctAlias="" model="" currency="CHF" fxRateToBase="1" assetCategory="STK" subCategory="RIGHT" symbol="DRPF.RTS2" description="DRPF.RTS2(SUDRP2411081) MERGED(Voluntary Offer Allocation) WITH CH0026465366 1 FOR 1 (DRPF.RTS2, UBS PROPERTY FUND DIRECT RES - RIGHTS SUBSCRIPTION, SUDRP2411081)" conid="739043271" securityID="SUDRP2411081" securityIDType="ISIN" cusip="" isin="SUDRP2411081" figi="" listingExchange="CORPACT" underlyingConid="" underlyingSymbol="DRPF.RTS2" underlyingSecurityID="" underlyingListingExchange="" issuer="" issuerCountryCode="XX" multiplier="1" strike="" expiry="" putCall="" principalAdjustFactor="" reportDate="2024-11-08" dateTime="2024-11-07;202500" actionDescription="DRPF.RTS2(SUDRP2411081) MERGED(Voluntary Offer Allocation) WITH CH0026465366 1 FOR 1 (DRPF.RTS2, UBS PROPERTY FUND DIRECT RES - RIGHTS SUBSCRIPTION, SUDRP2411081)" amount="0" proceeds="0" value="-2363.95" quantity="-120" costBasis="" fifoPnlRealized="0" mtmPnl="-638.1" code="" type="TC" transactionID="99999497353" actionID="999994293" levelOfDetail="DETAIL" serialNumber="" deliveryType="" commodityType="" fineness="0.0" weight="0.0" />
        <CorporateAction accountId="F2345789" acctAlias="" model="" currency="CHF" fxRateToBase="1" assetCategory="STK" subCategory="RIGHT" symbol="DRPF1.OLD" description="(CH1379144913) DELISTED (DRPF1.OLD, UBS PROPERTY FUND DIRECT-RTS, CH1379144913)" conid="737556172" securityID="CH1379144913" securityIDType="ISIN" cusip="" isin="CH1379144913" figi="BBG01Q0RQ299" listingExchange="VALUE" underlyingConid="" underlyingSymbol="DRPF1.OLD" underlyingSecurityID="" underlyingListingExchange="" issuer="" issuerCountryCode="CH" multiplier="1" strike="" expiry="" putCall="" principalAdjustFactor="" reportDate="2024-11-20" dateTime="2024-11-19;202500" actionDescription="(CH1379144913) DELISTED (DRPF1.OLD, UBS PROPERTY FUND DIRECT-RTS, CH1379144913)" amount="0" proceeds="0" value="0" quantity="-8" costBasis="" fifoPnlRealized="0" mtmPnl="0" code="" type="DW" transactionID="99999092357" actionID="999997113" levelOfDetail="DETAIL" serialNumber="" deliveryType="" commodityType="" fineness="0.0" weight="0.0" />
      </CorporateActions>
      <CashReport>
        <CashReportCurrency accountId="F2345789" currency="CHF" endingCash="0" fromDate="2024-01-01" toDate="2024-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

@pytest.fixture
def ibkr_settings_factory():
    def _create(ignore_rights_issues=False):
        return [
            IbkrAccountSettings(
                account_number="F2345789",
                broker_name="Interactive Brokers",
                account_name_alias="Rights Issue Test",
                canton="ZH",
                full_name="Test User",
                ignore_rights_issues=ignore_rights_issues
            )
        ]
    return _create

def test_ibkr_rights_issues_default_behavior(ibkr_settings_factory):
    """Test that rights issues are INCLUDED by default (ignore_rights_issues=False)."""
    settings = ibkr_settings_factory(ignore_rights_issues=False)
    importer = IbkrImporter(
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        account_settings_list=settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_RIGHTS_ISSUE_XML)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement.listOfSecurities is not None
        depot = tax_statement.listOfSecurities.depot[0]

        # Check for DRPF1 (CH1379144913) which has subCategory="RIGHT"
        # It has quantity 1208 and later some negative quantity.
        # We expect it to be present.
        drpf1_sec = next((s for s in depot.security if "DRPF1" in s.securityName), None)
        assert drpf1_sec is not None, "DRPF1 security should be present by default"

        # Check if _is_rights_issue flag is set (implied requirement for next steps)
        # Note: This attribute will be added in the implementation step, so this assertion might fail until then if I were running it now.
        # But since I am writing the test plan now, I can include it and it will pass after implementation.
        # Wait, if I run this test NOW it will fail on this assertion or pass if the flag is not set (if I don't assert it).
        # But I should verify the flag is set in the implementation.

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)

def test_ibkr_rights_issues_ignored(ibkr_settings_factory):
    """Test that rights issues are OMITTED when ignore_rights_issues=True and balances are zero."""
    settings = ibkr_settings_factory(ignore_rights_issues=True)
    importer = IbkrImporter(
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        account_settings_list=settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_RIGHTS_ISSUE_XML)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])

        if tax_statement.listOfSecurities is None:
             # If all securities are filtered out
             pass
        else:
            depot = tax_statement.listOfSecurities.depot[0]
            # DRPF1 has 1208 + (-1200) + (-8) = 0 balance?
            # XML shows:
            # 1. quantity="1208" (RI)
            # 2. quantity="120" (SR) -> This is DRPF.RTS2
            # 3. quantity="-1200" (SR) -> This is DRPF1.OLD (CH1379144913)
            # 4. quantity="-8" (DW) -> This is DRPF1.OLD (CH1379144913)
            # Note: DRPF1 and DRPF1.OLD seem to share the same ISIN CH1379144913 and conid 737556172.
            # So they should be aggregated into one security position.
            # Total quantity for CH1379144913: 1208 - 1200 - 8 = 0.

            # Start balance should be 0 (inferred).
            # End balance should be 0.

            # So it should be omitted.
            drpf1_sec = next((s for s in depot.security if "CH1379144913" in (s.isin or "")), None)
            assert drpf1_sec is None, "DRPF1 (CH1379144913) should be omitted when ignore_rights_issues=True and balance is 0"

            # Check DRPF.RTS2 (SUDRP2411081)
            # 1. quantity="120" (SR)
            # 2. quantity="-120" (TC)
            # Total = 0. Should be omitted.
            drpf_rts2_sec = next((s for s in depot.security if "SUDRP2411081" in (s.isin or "")), None)
            assert drpf_rts2_sec is None, "DRPF.RTS2 should be omitted"

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)

def test_ibkr_rights_issues_flag_set(ibkr_settings_factory):
    """Test that _is_rights_issue flag is set on Security objects."""
    settings = ibkr_settings_factory(ignore_rights_issues=False)
    importer = IbkrImporter(
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        account_settings_list=settings
    )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as tmp_file:
        tmp_file.write(SAMPLE_RIGHTS_ISSUE_XML)
        xml_file_path = tmp_file.name

    try:
        tax_statement = importer.import_files([xml_file_path])
        assert tax_statement.listOfSecurities is not None
        depot = tax_statement.listOfSecurities.depot[0]

        drpf1_sec = next((s for s in depot.security if "CH1379144913" in (s.isin or "")), None)
        assert drpf1_sec is not None
        assert getattr(drpf1_sec, "_is_rights_issue", False) is True, "Security should have _is_rights_issue=True"

    finally:
        if os.path.exists(xml_file_path):
            os.remove(xml_file_path)
