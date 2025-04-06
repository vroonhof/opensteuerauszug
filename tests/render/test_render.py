import os
import sys
import tempfile
import pytest
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal
import PyPDF2  # For checking PDF pages

from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Institution,
    Client,
    ClientNumber
)
from opensteuerauszug.render.render import (
    render_tax_statement
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
                salutation="2"  # "2" is code for "Mr"
            )
        ],
        totalTaxValue=Decimal("1000.50"),
        totalGrossRevenueA=Decimal("100.00"),
        totalGrossRevenueB=Decimal("50.00"),
        totalWithHoldingTaxClaim=Decimal("35.00")
    )

def test_render_tax_statement_content(sample_tax_statement):
    """Test that a tax statement contains the expected data in the PDF."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_path = temp_file.name
    
    try:
        # Render the tax statement to PDF
        render_tax_statement(sample_tax_statement, temp_path)
        
        # Check that the file exists and has content
        assert os.path.exists(temp_path)
        assert os.path.getsize(temp_path) > 0
        
        # Check content in the PDF
        with open(temp_path, "rb") as f:
            pdf_reader = PyPDF2.PdfReader(f)
            text = pdf_reader.pages[0].extract_text()
            
            # Verify client information appears in the PDF
            assert "Max" in text
            assert "Muster" in text
            assert "Herr" in text
            
            # Verify institution information
            assert "Test Bank AG" in text
            
            # Verify period information
            assert "2023" in text
            assert "01.01.2023" in text 
            assert "31.12.2023" in text
            
            # Verify summary data (we're checking for the values, not exact format)
            # Because the PDF might format these numbers differently
            assert "1000" in text  # totalTaxValue
            assert "100" in text   # totalGrossRevenueA
            assert "50" in text    # totalGrossRevenueB
            assert "35" in text    # totalWithHoldingTaxClaim
            assert "150" in text   # total
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def test_render_tax_statement(sample_tax_statement):
    """Test that a tax statement can be rendered to PDF."""
    # Create a temporary file for the output
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_path = temp_file.name
    
    try:
        # Render the tax statement to PDF
        render_tax_statement(sample_tax_statement, temp_path)
        
        # Check that the file exists and has content
        assert os.path.exists(temp_path)
        assert os.path.getsize(temp_path) > 0
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def test_pdf_page_count(sample_tax_statement):
    """Test that the PDF has the correct number of pages."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        # Render the tax statement to PDF
        render_tax_statement(sample_tax_statement, tmp_path)
        
        # Check that the file exists
        assert os.path.exists(tmp_path)
        
        # Check the number of pages using PyPDF2
        with open(tmp_path, "rb") as f:
            pdf_reader = PyPDF2.PdfReader(f)
            # The PDF should now have exactly one page
            assert len(pdf_reader.pages) == 1
            
            # Check page content for validation
            text = pdf_reader.pages[0].extract_text()
            assert "Steuerauszug" in text
            assert "Zusammenfassung" in text
            # Standard page templates usually only show current page number
            assert "Seite 1" in text  
            assert "Seite 1/1" not in text # Ensure the old format is gone
    finally:
        # Cleanup temporary file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
