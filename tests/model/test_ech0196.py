import os
import sys
import glob
import pytest
from datetime import date, datetime
from decimal import Decimal
from lxml import etree as ET  # Use lxml.etree explicitly
from pathlib import Path
import re

# Adjust import path based on your project structure if necessary
# This assumes 'tests' is at the same level as 'src'
from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Institution,
    Client,
    ClientNumber,
    BankAccount,
    NS_MAP,
    ns_tag
)

# --- Test Data ---

@pytest.fixture
def sample_tax_statement_data():
    """Provides a basic, valid TaxStatement instance for testing."""
    return TaxStatement(
        minorVersion=2,
        id="test-id-123",
        creationDate=datetime(2023, 10, 26, 10, 30, 00), # Use fixed datetime
        taxPeriod=2023,
        periodFrom=date(2023, 1, 1),
        periodTo=date(2023, 12, 31),
        canton="ZH",
        institution=Institution(name="Test Bank AG"),
        client=[
            Client(
                clientNumber=ClientNumber("C1"), # Keep explicit cast for static type checker
                firstName="Max",
                lastName="Muster",
                salutation="2"
            )
        ],
        totalTaxValue=Decimal("1000.50"),
        totalGrossRevenueA=Decimal("100.00"),
        totalGrossRevenueB=Decimal("50.00"),
        totalWithHoldingTaxClaim=Decimal("35.00")
        # Add other required fields from the XSD or base type as needed
        # Ensure all fields marked as required in the Pydantic model or its base
        # (like those with `...` or without Optional/default) are provided.
        # Example: Assuming these were marked required in TaxStatementExtension:
        # totalTaxValue=Decimal("1000.50"),
        # totalGrossRevenueA=Decimal("100.00"),
        # totalGrossRevenueB=Decimal("50.00"),
        # totalWithHoldingTaxClaim=Decimal("35.00"),
    )

sample_tax_xml_files = [
    os.path.expanduser(os.path.expandvars(p)) for p in [
        "~/src/steuerausweiss/samples/WIR.xml",
        "~/src/steuerausweiss/samples/Truewealth.xml",
        "~/src/steuerausweiss/samples/UBS_fixed.xml"]
]

# --- Helper functions ---

def normalize_xml(xml_bytes: bytes, remove_xmlns: bool = False) -> str:
    """Normalize XML string by parsing and re-serializing it.
    
    Args:
        xml_bytes: The XML content as bytes
        remove_xmlns: If True, remove xmlns declarations and schema locations for more robust comparison
    """
    # First normalize without pretty print to get consistent attribute order
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.fromstring(xml_bytes, parser=parser)
    normalized_bytes = ET.tostring(tree, method='c14n') # type: ignore
    
    # Re-parse and pretty print
    tree = ET.fromstring(normalized_bytes, parser=parser) 
    normalized = ET.tostring(tree, pretty_print=True).decode().replace('=".', '="0.') # type: ignore
    if remove_xmlns:
        import re
        # Remove xmlns declarations
        normalized = re.sub(r'\s+xmlns(?::[^=]*)?="[^"]*"', '', normalized)
        # Remove schemaLocation and noNamespaceSchemaLocation attributes
        normalized = re.sub(r'\s+(?:xsi:)?schemaLocation="[^"]*"', '', normalized)
        normalized = re.sub(r'\s+(?:xsi:)?noNamespaceSchemaLocation="[^"]*"', '', normalized)
        
    return normalized

# --- Tests ---

def test_tax_statement_creation(sample_tax_statement_data):
    """Tests basic instantiation of the TaxStatement model."""
    statement = sample_tax_statement_data
    assert statement.minorVersion == 2
    assert statement.id == "test-id-123"
    assert statement.canton == "ZH"
    assert statement.institution is not None
    assert statement.institution.name == "Test Bank AG"
    assert len(statement.client) == 1
    assert statement.client[0].lastName == "Muster"
    assert statement.totalTaxValue == Decimal("1000.50")

def test_tax_statement_to_xml(sample_tax_statement_data):
    """Tests serialization to XML bytes and checks basic structure."""
    statement = sample_tax_statement_data
    xml_bytes = statement.to_xml_bytes(pretty_print=False)

    assert xml_bytes.startswith(b'<?xml')
    # Parse and check key elements/attributes
    try:
        root = ET.fromstring(xml_bytes, parser=None)
        # Check root tag
        assert root.tag == ns_tag('eCH-0196', 'taxStatement')
        # Check some attributes
        assert root.get('minorVersion') == "2"
        assert root.get('id') == "test-id-123"
        assert root.get('canton') == "ZH"
        assert root.get('totalTaxValue') == "1000.50"
        # Check institution element existence and name attribute
        institution_el = root.find(ns_tag('eCH-0196', 'institution'), namespaces=NS_MAP)
        assert institution_el is not None
        assert institution_el.get('name') == "Test Bank AG"
        # Check client element existence and lastName attribute
        client_el = root.find(ns_tag('eCH-0196', 'client'), namespaces=NS_MAP)
        assert client_el is not None
        assert client_el.get('lastName') == "Muster"

    except ET.XMLSyntaxError as e:
        pytest.fail(f"Generated XML is not well-formed:\n{xml_bytes.decode()}\\nError: {e}")

@pytest.mark.skip(reason="Test is currently failing due to ValidationError during deserialization")
def test_tax_statement_from_xml(sample_tax_statement_data):
    """Tests deserialization from an XML string by parsing it first."""
    statement_orig = sample_tax_statement_data
    xml_bytes = statement_orig.to_xml_bytes(pretty_print=False)

    # Test the public from_xml_file logic by simulating file content
    # This requires writing to a temp file or using io.BytesIO if
    # from_xml_file is adapted to handle file-like objects.
    # For simplicity here, we re-parse and use _from_xml_element,
    # assuming from_xml_file primarily handles file reading and root validation.

    try:
        root = ET.fromstring(xml_bytes, parser=None)
         # Basic check for root element name and namespace before deeper parsing
        expected_tag = ns_tag('eCH-0196', 'taxStatement')
        if root.tag != expected_tag:
             pytest.fail(f"Expected root element '{expected_tag}' but found '{root.tag}'")

        # Use the internal _from_xml_element method for testing deserialization core logic
        loaded_statement = TaxStatement._from_xml_element(root)

    except ET.XMLSyntaxError as e:
         pytest.fail(f"Input XML for deserialization is not well-formed:\n{xml_bytes.decode()}\\nError: {e}")
    except ValueError as e:
         pytest.fail(f"ValueError during deserialization: {e}")
    except Exception as e:
         pytest.fail(f"Unexpected error during deserialization: {e}")


    # Compare key fields
    assert loaded_statement.minorVersion == statement_orig.minorVersion
    assert loaded_statement.id == statement_orig.id
    assert loaded_statement.creationDate == statement_orig.creationDate
    assert loaded_statement.taxPeriod == statement_orig.taxPeriod
    assert loaded_statement.periodFrom == statement_orig.periodFrom
    assert loaded_statement.periodTo == statement_orig.periodTo
    assert loaded_statement.canton == statement_orig.canton
    assert loaded_statement.totalTaxValue == statement_orig.totalTaxValue
    # Compare nested models (basic check)
    assert loaded_statement.institution is not None
    assert loaded_statement.institution.name == statement_orig.institution.name
    assert len(loaded_statement.client) == 1
    assert loaded_statement.client[0].lastName == statement_orig.client[0].lastName
    assert loaded_statement.client[0].clientNumber == statement_orig.client[0].clientNumber

@pytest.mark.skip(reason="Test is currently failing due to ValidationError during deserialization")
def test_tax_statement_round_trip_file(sample_tax_statement_data, tmp_path: Path):
    """Tests writing to and reading from an XML file."""
    statement_orig = sample_tax_statement_data
    output_file = tmp_path / "test_statement.xml"

    # Write to file
    try:
        statement_orig.to_xml_file(str(output_file), pretty_print=False)
    except Exception as e:
         pytest.fail(f"Failed to write statement to file {output_file}: {e}")
    assert output_file.exists()
    assert output_file.stat().st_size > 0 # Check file is not empty

    # Read from file
    try:
        loaded_statement = TaxStatement.from_xml_file(str(output_file))
    except Exception as e:
        pytest.fail(f"Failed to load statement from file {output_file}: {e}")


    # Compare key fields (similar to test_tax_statement_from_xml)
    assert loaded_statement.minorVersion == statement_orig.minorVersion
    assert loaded_statement.id == statement_orig.id
    assert loaded_statement.creationDate == statement_orig.creationDate
    assert loaded_statement.taxPeriod == statement_orig.taxPeriod
    assert loaded_statement.canton == statement_orig.canton
    assert loaded_statement.totalTaxValue == statement_orig.totalTaxValue
    assert loaded_statement.institution is not None
    assert loaded_statement.institution.name == statement_orig.institution.name
    assert loaded_statement.client[0].lastName == statement_orig.client[0].lastName
    assert loaded_statement.client[0].clientNumber == statement_orig.client[0].clientNumber

def test_bank_account_round_trip():
    """Tests deserializing and serializing a BankAccountType element."""
    # Simplified XML snippet for a bankAccount element in human-readable format
    xml_input = '''
    <bankAccount xmlns="http://www.ech.ch/xmlns/eCH-0196/2"
                 iban="CH1234567890123456789"
                 bankAccountNumber="ACC987"
                 bankAccountName="Main Account">
      <taxValue referenceDate="2024-12-31" balanceCurrency="CHF" balance="10000" exchangeRate="1" value="10000"/>
      <payment paymentDate="2024-03-31" name="Habenzins mit Verrechnungssteuer" amountCurrency="CHF" amount="1.20" exchangeRate="1" grossRevenueA="1.20" grossRevenueB="0" withHoldingTaxClaim=".3"/>
    </bankAccount>
    '''
    parser = ET.XMLParser(remove_blank_text=True)
    element = ET.fromstring(xml_input, parser=parser)

    # Deserialize
    try:
        bank_account = BankAccount._from_xml_element(element)
    except Exception as e:
        pytest.fail(f"Failed to deserialize BankAccountType from XML: {e}")

    print("bank_account: ", bank_account)

    # Check complete parse
    assert bank_account.unknown_attrs == {}
    assert bank_account.unknown_elements == []

    # Check deserialized values
    assert bank_account.iban == "CH1234567890123456789"
    assert bank_account.bankAccountNumber == "ACC987"
    assert bank_account.bankAccountName == "Main Account"
    assert bank_account.taxValue is not None
    assert bank_account.taxValue.balanceCurrency == "CHF"
    assert bank_account.taxValue.balance == 10000
    assert bank_account.taxValue.exchangeRate == 1
    assert bank_account.taxValue.value == 10000
    assert bank_account.taxValue.referenceDate == date(2024, 12, 31)
 
    # Serialize back to XML
    # Create a temporary parent element to build the XML correctly
    temp_parent = ET.Element("temp", attrib={}, nsmap={None: 'http://www.ech.ch/xmlns/eCH-0196/2'})
    bank_account._build_xml_element(temp_parent)
    # Get the first child, which should be the serialized bankAccount
    serialized_element = temp_parent[0]

    # Compare key attributes (more robust comparisons might be needed)
    assert serialized_element.tag == ns_tag('eCH-0196', 'bankAccount')
    assert serialized_element.get('iban') == bank_account.iban
    assert serialized_element.get('bankAccountNumber') == bank_account.bankAccountNumber
    assert serialized_element.get('bankAccountName') == bank_account.bankAccountName
    serialized_tax_value =  serialized_element.find(ns_tag('eCH-0196', 'taxValue'))
    assert serialized_tax_value is not None
    print("serialized_tax_value: ", serialized_tax_value.items())
    assert serialized_tax_value.get('balanceCurrency') == "CHF"
    assert serialized_tax_value.get('balance') == '10000'
    assert serialized_tax_value.get('exchangeRate') == '1'
    assert serialized_tax_value.get('value') == '10000'
    assert serialized_tax_value.get('referenceDate') == '2024-12-31'
    # Get serialized XML as string
    serialized_xml = ET.tostring(serialized_element)
    
    # Create expected XML by removing whitespace and comments from input
    expected_xml = normalize_xml(xml_input.encode())
    actual_xml = normalize_xml(serialized_xml)
    
    assert actual_xml == expected_xml

def test_institution_round_trip():
    """Tests deserializing and serializing an InstitutionType element.
    
        This has sub elements that are in a different namespace.
    """
    # Simplified XML snippet for a bankAccount element in human-readable format
    xml_input = '''
      <institution 
        xmlns="http://www.ech.ch/xmlns/eCH-0196/2"
        xmlns:eCH-0097="http://www.ech.ch/xmlns/eCH-0097/4"
        lei="IDENTIFIER1234567A01" name="Test Bank">
        <uid>
          <eCH-0097:uidOrganisationIdCategorie>CHE</eCH-0097:uidOrganisationIdCategorie>
          <eCH-0097:uidOrganisationId>123456789</eCH-0097:uidOrganisationId>
        </uid>
      </institution>
    '''
    parser = ET.XMLParser(remove_blank_text=True)
    element = ET.fromstring(xml_input, parser=parser)

    # Deserialize
    try:
        institution = Institution._from_xml_element(element)
    except Exception as e:
        pytest.fail(f"Failed to deserialize InsitutionType from XML: {e}")

    assert institution.unknown_attrs == {}
    assert institution.unknown_elements == []

    # Check deserialized values
    assert institution.name == "Test Bank"
    assert institution.lei == "IDENTIFIER1234567A01"
    assert institution.uid is not None
    assert institution.uid.uidOrganisationIdCategorie == "CHE"
    assert institution.uid.uidOrganisationId == 123456789
    assert institution.uid.uidSuffix is None
    # Serialize back to XML
    # Create a temporary parent element to build the XML correctly
    local_ns_map = {None: 'http://www.ech.ch/xmlns/eCH-0196/2',
                    'eCH-0097': 'http://www.ech.ch/xmlns/eCH-0097/4'}
    temp_parent = ET.Element("temp", attrib={}, nsmap=local_ns_map)
    institution._build_xml_element(temp_parent)
    # Get the first child, which should be the serialized bankAccount
    serialized_element = temp_parent[0]

    # Compare key attributes (more robust comparisons might be needed)
    assert serialized_element.tag == ns_tag('eCH-0196', 'institution')
    assert serialized_element.get('lei') == institution.lei
    assert serialized_element.get('name') == institution.name
    assert serialized_element.find(ns_tag('eCH-0196','uid')) is not None
    # Get serialized XML as string
    serialized_xml = ET.tostring(serialized_element)
    
    # Create expected XML by removing whitespace and comments from input
    expected_xml = normalize_xml(xml_input.encode())
    actual_xml = normalize_xml(serialized_xml)
    
    assert actual_xml == expected_xml


@pytest.mark.parametrize("xml_file", sample_tax_xml_files)
def test_xml_round_trip_files(xml_file: str, tmp_path: Path):
    """Test round-trip XML processing (read and write) of real XML files."""
    if not xml_file:
        pytest.skip("No XML files provided for testing")

    # Read original file
    try:
        statement = TaxStatement.from_xml_file(xml_file)
    except Exception as e:
        pytest.fail(f"Failed to read XML file {xml_file}: {e}")

    output_xml = statement.to_xml_bytes()

    with open(xml_file, 'rb') as f:
        original_xml = normalize_xml(f.read(), remove_xmlns=True)
    output_xml = normalize_xml(output_xml, remove_xmlns=True)

    # Compare normalized XML
    assert output_xml == original_xml, f"Round-trip XML differs for file {xml_file}"
 