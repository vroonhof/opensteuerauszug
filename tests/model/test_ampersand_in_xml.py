"""Test that ampersands in security names are properly handled in XML output."""

import pytest
from decimal import Decimal
from opensteuerauszug.model.ech0196 import Security, ISINType, ValorNumber


def test_ampersand_in_security_name_xml_serialization():
    """Test that lxml properly escapes ampersands in XML output."""
    # Create a security with an ampersand in the name
    security = Security(
        positionId=1,
        country="US",
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        securityName="ISHARES CORE S&P 500",
        isin=ISINType("US4642874576"),
        valorNumber=ValorNumber(12345678)
    )
    
    # Build XML element
    xml_element = security._build_xml_element(parent_element=None)
    
    # Check that the securityName attribute contains an escaped ampersand
    security_name_attr = xml_element.get('securityName')
    assert security_name_attr == "ISHARES CORE S&P 500", "Security name should be unescaped in the element attribute"
    
    # When serialized to XML string, lxml should automatically escape it
    import lxml.etree as ET
    xml_string = ET.tostring(xml_element, encoding='unicode')
    
    # The XML string should contain &amp; not &
    assert 'securityName="ISHARES CORE S&amp;P 500"' in xml_string, "XML should have escaped ampersand"
    # Make sure we don't have an unescaped ampersand in the attribute
    assert 'securityName="ISHARES CORE S&P 500"' not in xml_string, "XML should not have unescaped ampersand"


def test_multiple_special_chars_in_xml():
    """Test that other HTML/XML special characters are handled properly."""
    # Create a security with multiple special characters
    security = Security(
        positionId=1,
        country="US",
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        securityName='TEST <FUND> "GROWTH" & \'VALUE\'',
        isin=ISINType("US1234567890"),
        valorNumber=ValorNumber(12345679)
    )
    
    # Build XML element
    xml_element = security._build_xml_element(parent_element=None)
    
    # When serialized to XML string, lxml should automatically escape all special chars
    import lxml.etree as ET
    xml_string = ET.tostring(xml_element, encoding='unicode')
    
    # Check that special characters are properly escaped in XML
    assert '&amp;' in xml_string, "Ampersand should be escaped"
    assert '&lt;' in xml_string or '&gt;' in xml_string, "Angle brackets should be escaped"
    assert '&quot;' in xml_string, "Quotes should be escaped"
    
    # Make sure we don't have unescaped versions that would break XML
    # Note: The attribute value will have quotes around it, so checking the pattern
    assert 'securityName="TEST <FUND>' not in xml_string, "Should not have unescaped angle brackets"
