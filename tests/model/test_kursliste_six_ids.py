import pytest
from opensteuerauszug.model.kursliste import Payment, Legend, PaymentShare, Kursliste
from pydantic_xml import element, attr
import lxml.etree as ET

def test_payment_six_id_roundtrip():
    """Test that paymentIdSIX can be parsed and round-tripped on a Payment object."""
    # Using PaymentShare which inherits Payment
    xml_share = """
    <payment xmlns="http://xmlns.estv.admin.ch/ictax/2.2.0/kursliste"
             id="1"
             currency="CHF"
             paymentIdSIX="SIX12345"
             >
    </payment>
    """

    root = ET.fromstring(xml_share)
    payment = PaymentShare.from_xml_tree(root)

    assert payment.paymentIdSIX == "SIX12345"

    # Verify round trip (serialize back to XML)
    # pydantic-xml to_xml() returns bytes by default
    output_xml = payment.to_xml()

    if isinstance(output_xml, bytes):
        xml_str = output_xml.decode('utf-8')
    else:
        # If it returns an Element
        xml_str = ET.tostring(output_xml, encoding='unicode')

    assert 'paymentIdSIX="SIX12345"' in xml_str


def test_legend_six_id_roundtrip():
    """Test that eventIdSIX can be parsed and round-tripped on a Legend object."""
    xml = """
    <legend xmlns="http://xmlns.estv.admin.ch/ictax/2.2.0/kursliste"
            id="100"
            eventIdSIX="EVT67890">
    </legend>
    """

    root = ET.fromstring(xml)
    legend = Legend.from_xml_tree(root)

    assert legend.eventIdSIX == "EVT67890"

    # Verify round trip
    output_xml = legend.to_xml()

    if isinstance(output_xml, bytes):
        xml_str = output_xml.decode('utf-8')
    else:
        xml_str = ET.tostring(output_xml, encoding='unicode')

    assert 'eventIdSIX="EVT67890"' in xml_str

def test_payment_six_id_optional():
    """Test that paymentIdSIX is optional."""
    xml = """
    <payment xmlns="http://xmlns.estv.admin.ch/ictax/2.2.0/kursliste"
             id="2"
             currency="USD"
             >
    </payment>
    """
    root = ET.fromstring(xml)
    payment = PaymentShare.from_xml_tree(root)

    assert payment.paymentIdSIX is None

def test_legend_six_id_optional():
    """Test that eventIdSIX is optional."""
    xml = """
    <legend xmlns="http://xmlns.estv.admin.ch/ictax/2.2.0/kursliste"
            id="200">
    </legend>
    """
    root = ET.fromstring(xml)
    legend = Legend.from_xml_tree(root)

    assert legend.eventIdSIX is None
