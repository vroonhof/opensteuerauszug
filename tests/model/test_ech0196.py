import os
import sys
import pytest
from datetime import date, datetime
from decimal import Decimal
from lxml import etree as ET  # Use lxml.etree explicitly
from pathlib import Path
import re
from pydantic import Field

# Import the centralized test utilities
from tests.utils import normalize_xml, get_sample_files

# Adjust import path based on your project structure if necessary
# This assumes 'tests' is at the same level as 'src'
from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Institution,
    Client,
    ClientNumber,
    BankAccount,
    BankAccountName,
    BankAccountNumber,
    BaseXmlModel,
    NS_MAP,
    ns_tag,
    Security, # Added Security import
    SecurityPayment,
    SecurityStock
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
    )

# Use the centralized helper function
def get_sample_tax_xml_files():
    return get_sample_files("*.xml")


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

    # Deserialize in strict mode to ensure XML matches schema exactly
    try:
        bank_account = BankAccount._from_xml_element(element, strict=True)
    except Exception as e:
        pytest.fail(f"Failed to deserialize BankAccountType from XML: {e}")

    print("bank_account: ", bank_account)

    # Using strict mode means we should have no unknown attributes or elements
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

    # Deserialize in strict mode
    try:
        institution = Institution._from_xml_element(element, strict=True)
    except Exception as e:
        pytest.fail(f"Failed to deserialize InsitutionType from XML: {e}")

    # Using strict mode means we should have no unknown attributes or elements
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


# Integration tests
# Use the centralized helper function
@pytest.mark.parametrize("xml_file", get_sample_tax_xml_files())
def test_xml_round_trip_files(xml_file: str, tmp_path: Path):
    """Test round-trip XML processing (read and write) of real XML files."""
    if not xml_file:
        pytest.skip("No XML files provided for testing")

    # First attempt with strict mode - might fail for some files
    statement = TaxStatement.from_xml_file(xml_file, strict=True)

    output_xml = statement.to_xml_bytes()

    with open(xml_file, 'rb') as f:
        original_xml = normalize_xml(f.read(), remove_xmlns=True)
    output_xml = normalize_xml(output_xml, remove_xmlns=True)

    assert output_xml == original_xml

def test_strict_mode_unknown_attribute():
    """Test that strict mode raises an exception for unknown attributes."""
    # XML with an unknown attribute
    xml_input = '''
    <bankAccount xmlns="http://www.ech.ch/xmlns/eCH-0196/2"
                 iban="CH1234567890123456789"
                 unknownAttr="value">
    </bankAccount>
    '''
    parser = ET.XMLParser(remove_blank_text=True)
    element = ET.fromstring(xml_input, parser=parser)

    # Create a strict version of BankAccount for testing
    class StrictBankAccount(BankAccount):
        model_config = {
            "arbitrary_types_allowed": True,
            "strict_parsing": True
        }

    # Should raise an exception in strict mode
    with pytest.raises(ValueError, match="Unknown attribute: .*unknownAttr.*"):
        StrictBankAccount._from_xml_element(element)
    
    # Should not raise an exception in normal mode
    bank_account = BankAccount._from_xml_element(element)
    assert 'unknownAttr' in bank_account.unknown_attrs
    assert bank_account.unknown_attrs['unknownAttr'] == 'value'

def test_strict_mode_unknown_element():
    """Test that strict mode raises an exception for unknown elements."""
    # XML with an unknown element
    xml_input = '''
    <bankAccount xmlns="http://www.ech.ch/xmlns/eCH-0196/2"
                 iban="CH1234567890123456789">
        <unknownElement>Some content</unknownElement>
    </bankAccount>
    '''
    parser = ET.XMLParser(remove_blank_text=True)
    element = ET.fromstring(xml_input, parser=parser)

    # Create a strict version of BankAccount for testing
    class StrictBankAccount(BankAccount):
        model_config = {
            "arbitrary_types_allowed": True,
            "strict_parsing": True
        }

    # Should raise an exception in strict mode
    with pytest.raises(ValueError, match="Unknown element.*unknownElement.*"):
        StrictBankAccount._from_xml_element(element)
    
    # Should not raise an exception in normal mode
    bank_account = BankAccount._from_xml_element(element)
    assert len(bank_account.unknown_elements) == 1
    assert bank_account.unknown_elements[0].tag.endswith('unknownElement')

def test_strict_mode_parsing_error():
    """Test that strict mode raises an exception when attribute parsing fails."""
    # XML with an attribute that will fail to parse
    xml_input = '''
    <bankAccount xmlns="http://www.ech.ch/xmlns/eCH-0196/2"
                 iban="CH1234567890123456789"
                 balanceCurrency="123">
    </bankAccount>
    '''
    parser = ET.XMLParser(remove_blank_text=True)
    element = ET.fromstring(xml_input, parser=parser)

    # Create a modified version of BankAccount for testing
    class StrictBankAccount(BankAccount):
        model_config = {
            "arbitrary_types_allowed": True,
            "strict_parsing": True
        }
        
        balanceCurrency: date = Field(..., json_schema_extra={'is_attribute': True})  # Invalid type on purpose

    # Should raise an exception in strict mode
    with pytest.raises(ValueError, match="Could not parse attribute.*balanceCurrency.*"):
        StrictBankAccount._from_xml_element(element)

def test_use_strict_parameter():
    """Test that the strict parameter overrides the Config setting."""
    xml_input = '''
    <bankAccount xmlns="http://www.ech.ch/xmlns/eCH-0196/2"
                 iban="CH1234567890123456789"
                 unknownAttr="value">
    </bankAccount>
    '''
    parser = ET.XMLParser(remove_blank_text=True)
    element = ET.fromstring(xml_input, parser=parser)

    # Non-strict class, but use strict parameter
    with pytest.raises(ValueError, match="Unknown attribute: .*unknownAttr.*"):
        BankAccount._from_xml_element(element, strict=True)
    
    # Create a strict class, but override with strict=False
    class StrictBankAccount(BankAccount):
        model_config = {
            "arbitrary_types_allowed": True,
            "strict_parsing": True
        }
    
    # This should not raise, despite the class being strict
    bank_account = StrictBankAccount._from_xml_element(element, strict=False)
    assert 'unknownAttr' in bank_account.unknown_attrs
    assert bank_account.unknown_attrs['unknownAttr'] == 'value'

def test_security_symbol_not_serialized_to_xml():
    """Tests that the 'symbol' field in Security model is not serialized to XML."""
    # Minimal required fields for Security instantiation
    sec = Security(
        positionId=1,
        country="US",
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        securityName="Test Security Name",
        symbol="TESTSYM"  # This field should be excluded from XML
    )

    # Serialize to an lxml element
    # The _build_xml_element method needs a parent if it's not the root,
    # or can be called with None if it's meant to be a root (depends on its implementation).
    # For a fragment, creating a dummy parent is safer.
    # However, Security is typically a child of Depot.
    # Let's assume _build_xml_element can create its own root for this test,
    # or we can construct a minimal parent.
    # Based on BaseXmlModel, _build_xml_element(None) should work if tag_name is in model_config or class name is used.
    # Security model has 'tag_name': 'security' in its model_config.

    xml_element = sec._build_xml_element(parent_element=None) # Builds the <security> element

    # Convert the element to an XML string
    xml_string = ET.tostring(xml_element, pretty_print=True)

    # Assert that "symbol" attribute is not present
    # ET.tostring will output bytes, so compare with bytes
    assert b'symbol="TESTSYM"' not in xml_string, "Symbol attribute should not be serialized"

    # Also assert that "symbol" as an element is not present
    assert b"<symbol>TESTSYM</symbol>" not in xml_string, "Symbol element should not be serialized"
    assert b"<symbol>" not in xml_string, "Symbol element tag should not be serialized"

    # More robust check: parse the XML and inspect the element
    parsed_element = ET.fromstring(xml_string)
    assert parsed_element.get("symbol") is None, "Parsed XML should not have 'symbol' attribute"

    # Check for child elements named 'symbol'
    # ns_tag('eCH-0196', 'symbol') would be for namespaced elements.
    # Since 'symbol' is exclude=True, it shouldn't be a namespaced or non-namespaced element.
    found_symbol_element = parsed_element.find("symbol") # Non-namespaced check
    assert found_symbol_element is None, "Parsed XML should not have a child element named 'symbol'"

    found_namespaced_symbol_element = parsed_element.find(ns_tag('eCH-0196', 'symbol')) # Namespaced check
    assert found_namespaced_symbol_element is None, "Parsed XML should not have a namespaced child element named 'symbol'"

def test_decimal_serialization_avoids_scientific_notation():
    """Test that Decimal values are serialized as plain strings, not scientific notation."""
    # A very small decimal value that might be serialized to scientific notation
    small_decimal = Decimal('0.0000000001') # 1e-10
    
    # Create a simple model instance with this decimal value
    # We can use BankAccount and set one of its Decimal attributes
    bank_account = BankAccount(
        iban="CH1234567890123456789",
        bankAccountNumber=BankAccountNumber("ACC123"),
        bankAccountName=BankAccountName("Test Account"),
        totalTaxValue=small_decimal
    )
    
    # Serialize to an lxml element
    # The _build_xml_element method needs a parent if it's not the root
    temp_parent = ET.Element("temp", nsmap={None: 'http://www.ech.ch/xmlns/eCH-0196/2'})
    xml_element = bank_account._build_xml_element(temp_parent)
    
    # Get the serialized value of the 'totalTaxValue' attribute
    serialized_value = xml_element.get("totalTaxValue")
    
    # Assert that the serialized value is a plain string, not in scientific notation
    assert serialized_value is not None, "totalTaxValue attribute should be serialized"
    assert "E" not in serialized_value.upper(), f"Scientific notation found in serialized decimal: {serialized_value}"
    assert serialized_value == "0.0000000001", f"Serialized decimal has incorrect format: {serialized_value}"

def test_optional_boolean_serialization():
    """
    Tests that optional boolean attributes are serialized correctly.
    - True should be serialized to "1".
    - False should be omitted from the XML.
    """
    # Test with gratis=True
    payment_true = SecurityPayment(
        paymentDate="2023-01-01",
        quotationType="PIECE",
        quantity=1,
        amountCurrency="CHF",
        gratis=True
    )
    xml_element_true = payment_true._build_xml_element(parent_element=None)
    assert xml_element_true.get("gratis") == "1"

    # Test with gratis=False
    payment_false = SecurityPayment(
        paymentDate="2023-01-01",
        quotationType="PIECE",
        quantity=1,
        amountCurrency="CHF",
        gratis=False
    )
    xml_element_false = payment_false._build_xml_element(parent_element=None)
    assert "gratis" not in xml_element_false.attrib

def test_required_boolean_serialization():
    """
    Tests that required boolean attributes are serialized correctly.
    - True should be serialized to "1".
    - False should be serialized to "0".
    """
    # Test with mutation=True
    stock_true = SecurityStock(
        referenceDate="2023-01-01",
        mutation=True,
        quotationType="PIECE",
        quantity=1,
        balanceCurrency="CHF"
    )
    xml_element_true = stock_true._build_xml_element(parent_element=None)
    assert xml_element_true.get("mutation") == "1"

    # Test with mutation=False
    stock_false = SecurityStock(
        referenceDate="2023-01-01",
        mutation=False,
        quotationType="PIECE",
        quantity=1,
        balanceCurrency="CHF"
    )
    xml_element_false = stock_false._build_xml_element(parent_element=None)
    assert xml_element_false.get("mutation") == "0"
