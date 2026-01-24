
import pytest
from datetime import datetime, date
from decimal import Decimal
from lxml import etree as ET
from opensteuerauszug.model.ech0196 import TaxStatement, Institution, Client, ClientNumber, NS_MAP

def test_tax_statement_xsi_namespace_and_schema_location():
    """Test that the TaxStatement root element includes xsi namespace and schemaLocation."""

    statement = TaxStatement(
        minorVersion=22,
        id="test-id-123",
        creationDate=datetime(2023, 10, 26, 10, 30, 00),
        taxPeriod=2023,
        periodFrom=date(2023, 1, 1),
        periodTo=date(2023, 12, 31),
        canton="ZH",
        institution=Institution(name="Test Bank AG"),
        client=[
            Client(
                clientNumber=ClientNumber("C1"),
                firstName="Max",
                lastName="Muster",
                salutation="2"
            )
        ],
        totalTaxValue=Decimal("1000.50"),
        totalGrossRevenueA=Decimal("100.00"),
        totalGrossRevenueB=Decimal("50.00"),
        totalWithHoldingTaxClaim=Decimal("35.00")
    )

    xml_bytes = statement.to_xml_bytes()

    # Parse the generated XML
    root = ET.fromstring(xml_bytes)

    # Check namespaces map on the root element
    # Note: lxml nsmap keys are None for default namespace
    assert 'xsi' in root.nsmap
    assert root.nsmap['xsi'] == "http://www.w3.org/2001/XMLSchema-instance"

    # Check for schemaLocation attribute
    # The attribute key in lxml will use the expanded namespace
    xsi_ns = "http://www.w3.org/2001/XMLSchema-instance"
    schema_location_key = f"{{{xsi_ns}}}schemaLocation"

    assert schema_location_key in root.attrib

    expected_schema_location = (
        "http://www.ech.ch/xmlns/eCH-0196/2 "
        "http://www.ech.ch/xmlns/eCH-0196/2.2/eCH-0196-2-2.xsd "
        "http://www.ech.ch/xmlns/eCH-0097/4 "
        "http://www.ech.ch/xmlns/eCH-0097/4/eCH-0097-4-0.xsd"
    )

    assert root.attrib[schema_location_key] == expected_schema_location
