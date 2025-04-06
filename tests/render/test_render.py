import os
import sys
import tempfile
import pytest
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal

from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Institution,
    Client,
    ClientNumber
)
from opensteuerauszug.render.render import (
    render_tax_statement,
    map_tax_statement_to_pdf_data
)

@pytest.fixture
def sample_tax_statement():
    """Provides a basic tax statement for testing the renderer."""
    return TaxStatement(
        minorVersion=2,
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

def test_map_tax_statement_to_pdf_data(sample_tax_statement):
    """Test that a tax statement can be correctly mapped to PDF data."""
    pdf_data = map_tax_statement_to_pdf_data(sample_tax_statement)
    
    # Check basic structure
    assert isinstance(pdf_data, dict)
    assert "customer" in pdf_data
    assert "institution" in pdf_data
    assert "period" in pdf_data
    assert "summary" in pdf_data
    
    # Check customer data
    assert pdf_data["customer"]["firstName"] == "Max"
    assert pdf_data["customer"]["lastName"] == "Muster"
    assert pdf_data["customer"]["salutation"] == "Herr"
    
    # Check institution data
    assert pdf_data["institution"]["name"] == "Test Bank AG"
    
    # Check period data
    assert pdf_data["period"]["year"] == 2023
    assert pdf_data["period"]["from"] == "2023-01-01"
    assert pdf_data["period"]["to"] == "2023-12-31"
    
    # Check summary data
    assert pdf_data["summary"]["steuerwert_ab"] == Decimal("1000.50")
    assert pdf_data["summary"]["brutto_mit_vst"] == Decimal("100.00")
    assert pdf_data["summary"]["brutto_ohne_vst"] == Decimal("50.00")
    assert pdf_data["summary"]["vst_anspruch"] == Decimal("35.00")
    assert pdf_data["summary"]["total_brutto_gesamt"] == Decimal("150.00")

def test_render_tax_statement(sample_tax_statement):
    """Test that a tax statement can be rendered to PDF."""
    # Create a temporary file for the output
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_path = temp_file.name
    
    try:
        # Render the tax statement to PDF
        output_path = render_tax_statement(sample_tax_statement, temp_path)
        
        # Check that the file exists and has content
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0
        
        # We're not checking the content of the PDF since that would be complex
        # Just verify that it's generated correctly
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.unlink(temp_path)
