import os
import sys
import tempfile
import pytest
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal
import PyPDF2  # For checking PDF pages
from io import BytesIO

from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Institution,
    Client,
    ClientNumber
)
from opensteuerauszug.render.render import (
    render_tax_statement,
    render_statement_info,
    make_barcode_pages,
    BarcodeDocTemplate
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, Spacer, SimpleDocTemplate
from reportlab.lib.enums import TA_LEFT

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

def test_render_statement_info(sample_tax_statement):
    """Test that the statement info is correctly rendered to story elements without rendering a PDF."""
    # Create a story list and style
    story = []
    styles = getSampleStyleSheet()
    client_info_style = ParagraphStyle(name='ClientInfo', parent=styles['Normal'], fontSize=9)
    
    # Call the function
    render_statement_info(sample_tax_statement, story, client_info_style)
    
    # Check that the expected elements were added to the story
    # We should have 6 paragraphs (customer name, portfolio, institution, year, period, creation date) 
    # and 1 spacer at the end
    assert len(story) == 7
    
    # All elements except the last should be Paragraph objects
    assert all(isinstance(elem, Paragraph) for elem in story[:-1])
    
    # Check the last element is a Spacer
    assert isinstance(story[-1], Spacer)
    
    # Convert paragraphs to text for easier assertions
    paragraph_texts = [p.text for p in story[:-1]]  # Exclude the Spacer
    
    # Check that each expected piece of information is in the paragraph texts
    assert '<b>Kunde:</b> Herr Max Muster' in paragraph_texts
    assert '<b>Portfolio:</b> C1' in paragraph_texts
    assert '<b>Institution:</b> Test Bank AG' in paragraph_texts
    assert '<b>Steuerjahr:</b> 2023' in paragraph_texts
    assert '<b>Periode:</b> 01.01.2023 - 31.12.2023' in paragraph_texts
    assert '<b>Erstellt am:</b> 26.10.2023' in paragraph_texts

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
            # The PDF should now have exactly two pages
            assert len(pdf_reader.pages) == 2
            
            # Check page content for validation
            text = pdf_reader.pages[0].extract_text()
            assert "Steuerauszug" in text
            assert "Zusammenfassung" in text
            # Standard page templates usually only show current page number
            assert "Seite 1" in text
            
            # Check the barcode page
            text2 = pdf_reader.pages[1].extract_text()
            assert "Barcode Pages - For Scanning" in text2
    finally:
        # Cleanup temporary file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

def test_barcode_rendering(sample_tax_statement):
    """Test that barcodes are rendered correctly on all pages including a dedicated barcode page."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        # Render the tax statement (now always includes a barcode page)
        render_tax_statement(sample_tax_statement, tmp_path)
        
        # Check that the file exists
        assert os.path.exists(tmp_path)
        
        # Check the number of pages using PyPDF2
        with open(tmp_path, "rb") as f:
            pdf_reader = PyPDF2.PdfReader(f)
            # Should have 2 pages (content + barcode page)
            assert len(pdf_reader.pages) == 2
            
            # Check content in the regular page
            text1 = pdf_reader.pages[0].extract_text()
            assert "Steuerauszug" in text1
            assert "Zusammenfassung" in text1
            
            # Check content in the barcode page
            text2 = pdf_reader.pages[1].extract_text()
            assert "Barcode Page 1 of" in text2
    finally:
        # Cleanup temporary file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

def test_make_barcode_pages(sample_tax_statement, monkeypatch):
    """Test that make_barcode_pages correctly configures the document and story."""
    # Create a mock story and document
    story = []
    buffer = BytesIO()
    doc = BarcodeDocTemplate(buffer, pagesize=(800, 600))
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(name='SectionTitle', parent=styles['h2'], fontSize=10)
    
    # Mock the render_to_barcodes function to return a list of mock images
    def mock_render_to_barcodes(tax_statement):
        from PIL import Image
        # Create a simple 100x100 black image
        img = Image.new('RGB', (100, 100), color='black')
        # Return a list with one image
        return [img]
    
    # Apply the monkeypatch
    monkeypatch.setattr('opensteuerauszug.render.render.render_to_barcodes', mock_render_to_barcodes)
    
    # Call the function
    make_barcode_pages(doc, story, sample_tax_statement, title_style)
    
    # Verify document configuration
    assert doc.is_barcode_page is True
    
    # Verify core story elements - should include at minimum:
    # 1. NextPageTemplate
    # 2. PageBreak
    # 3. Title paragraph
    # 4. Spacer after title
    # 5. Table for barcode layout
    assert len(story) >= 5
    
    # Find the title paragraph
    title_found = False
    for item in story:
        if isinstance(item, Paragraph) and "Barcode Page" in item.text:
            title_found = True
            break
    
    assert title_found, "No barcode page title found"
    
    # Find a spacer
    spacer_found = False
    for item in story:
        if isinstance(item, Spacer):
            spacer_found = True
            break
    
    assert spacer_found, "No spacer found"
    
    # Find a table
    table_found = False
    for item in story:
        if item.__class__.__name__ == 'Table':
            table_found = True
            break
    
    assert table_found, "No table found for barcode layout"
