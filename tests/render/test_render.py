import os
import sys
import tempfile
import pytest
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal
import pypdf  # Fors checking PDF pages
from io import BytesIO
from unittest import mock # Added for mocking

from PIL import Image as PILImage # Added for dummy image

from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Institution,
    Client,
    ClientNumber,
    ListOfBankAccounts,
    BankAccount,
    BankAccountTaxValue,
    BankAccountPayment,
    BankAccountName,
    Depot,
    Security,
    ValorNumber,
    ISINType,
    ListOfSecurities
)
from opensteuerauszug.render.render import (
    render_tax_statement,
    render_statement_info,
    make_barcode_pages,
    BarcodeDocTemplate,
    create_bank_accounts_table
)
import opensteuerauszug.render.render as render
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, Spacer, SimpleDocTemplate, Table
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from opensteuerauszug.calculate.total import TotalCalculator
from opensteuerauszug.calculate.base import CalculationMode
from tests.utils.samples import get_sample_files
from opensteuerauszug.util.styles import get_custom_styles

# Helper to create a dummy PIL Image
def create_dummy_pil_image(width=100, height=30):
    img = PILImage.new('RGB', (width, height), color = 'red')
    return img

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
        svTaxValueA=Decimal("900.00"),
        svTaxValueB=Decimal("100.50"),
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
    # We should have 4 paragraphs (customer name, portfolio, period, creation date) 
    # and 1 spacer at the end (institution and tax year are now in left header)
    assert len(story) == 5
    
    # All elements except the last should be Paragraph objects
    assert all(isinstance(elem, Paragraph) for elem in story[:-1])
    
    # Check the last element is a Spacer
    assert isinstance(story[-1], Spacer)
    
    # Convert paragraphs to text for easier assertions
    paragraph_texts = [p.text for p in story[:-1]]  # Exclude the Spacer
    
    # Check that each expected piece of information is in the paragraph texts
    assert '<b>Kunde:</b> Herr Max Muster' in paragraph_texts
    assert '<b>Portfolio:</b> C1' in paragraph_texts
    assert '<b>Periode:</b> 01.01.2023 - 31.12.2023' in paragraph_texts
    assert '<b>Erstellt am:</b> 26.10.2023' in paragraph_texts
    # Institution and tax year are now in the left header, not in the story

@mock.patch('opensteuerauszug.render.render.render_to_barcodes')
def test_render_tax_statement_content(mock_render_to_barcodes, sample_tax_statement):
    """Test that a tax statement contains the expected data in the PDF."""
    mock_render_to_barcodes.return_value = [create_dummy_pil_image()]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_path = temp_file.name
    
    # Set some values for the new fields
    sample_tax_statement.steuerwert_ab = Decimal("1000.50")
    sample_tax_statement.steuerwert_a = Decimal("800.00")
    sample_tax_statement.steuerwert_b = Decimal("200.50")
    sample_tax_statement.brutto_mit_vst = Decimal("100.00")
    sample_tax_statement.brutto_ohne_vst = Decimal("50.00")
    
    try:
        # Render the tax statement to PDF
        render_tax_statement(sample_tax_statement, temp_path)
        
        # Check that the file exists and has content
        assert os.path.exists(temp_path)
        assert os.path.getsize(temp_path) > 0
        
        # Check content in the PDF
        with open(temp_path, "rb") as f:
            pdf_reader = pypdf.PdfReader(f)
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
            assert "1'001" in text  # totalTaxValue
            assert "100" in text   # totalGrossRevenueA
            assert "50" in text    # totalGrossRevenueB
            assert "35" in text    # totalWithHoldingTaxClaim
            assert "150" in text   # total
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.unlink(temp_path)

@mock.patch('opensteuerauszug.render.render.render_to_barcodes')
def test_render_tax_statement(mock_render_to_barcodes, sample_tax_statement):
    """Test that a tax statement can be rendered to PDF."""
    mock_render_to_barcodes.return_value = [create_dummy_pil_image()]
    
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

@mock.patch('opensteuerauszug.render.render.render_to_barcodes')
def test_pdf_page_count(mock_render_to_barcodes, sample_tax_statement):
    """Test that the PDF has the correct number of pages."""
    mock_render_to_barcodes.return_value = [create_dummy_pil_image()]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        # Render the tax statement to PDF
        render_tax_statement(sample_tax_statement, tmp_path)
        
        # Check that the file exists
        assert os.path.exists(tmp_path)
        
        # Check the number of pages using PyPDF2
        with open(tmp_path, "rb") as f:
            pdf_reader = pypdf.PdfReader(f)
            # The PDF should now have four pages (content, two info pages, barcode)
            assert len(pdf_reader.pages) == 4
            
            # Check page content for validation
            text = pdf_reader.pages[0].extract_text()
            assert "Steuerauszug" in text
            assert "Zusammenfassung" in text
            # Standard page templates usually only show current page number
            assert "Seite 1" in text
            
            # Check the barcode page
            text2 = pdf_reader.pages[3].extract_text()
            assert "Barcode Seite" in text2
    finally:
        # Cleanup temporary file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@mock.patch('opensteuerauszug.render.render.render_to_barcodes')
def test_render_tax_statement_minimal_placeholder(mock_render_to_barcodes, sample_tax_statement):
    """Ensure minimal mode renders placeholder instead of summary."""
    mock_render_to_barcodes.return_value = [create_dummy_pil_image()]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_path = temp_file.name

    try:
        render_tax_statement(sample_tax_statement, temp_path, minimal_frontpage_placeholder=True)

        with open(temp_path, "rb") as f:
            pdf_reader = pypdf.PdfReader(f)
            text = pdf_reader.pages[0].extract_text()
            assert "Minimaldokument" in text
            assert "1'001" not in text
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

@mock.patch('opensteuerauszug.render.render.render_to_barcodes')
def test_pdf_title_metadata(mock_render_to_barcodes, sample_tax_statement):
    """Verify that the rendered PDF sets a descriptive title."""
    mock_render_to_barcodes.return_value = [create_dummy_pil_image()]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        render_tax_statement(sample_tax_statement, tmp_path)

        with open(tmp_path, "rb") as f:
            pdf_reader = pypdf.PdfReader(f)
            assert (
                pdf_reader.metadata.title
                == "Steuerauszug Test Bank AG 2023"
            )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

@mock.patch('opensteuerauszug.render.render.render_to_barcodes')
def test_barcode_rendering(mock_render_to_barcodes, sample_tax_statement):
    """Test that barcodes are rendered correctly on all pages including a dedicated barcode page."""
    mock_render_to_barcodes.return_value = [create_dummy_pil_image()]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        # Render the tax statement (now always includes a barcode page)
        render_tax_statement(sample_tax_statement, tmp_path)
        
        # Check that the file exists
        assert os.path.exists(tmp_path)
        
        # Check the number of pages using PyPDF2
        with open(tmp_path, "rb") as f:
            pdf_reader = pypdf.PdfReader(f)
            # Should have 4 pages (content, two info pages, barcode page)
            assert len(pdf_reader.pages) == 4
            
            # Check content in the regular page
            text1 = pdf_reader.pages[0].extract_text()
            assert "Steuerauszug" in text1
            assert "Zusammenfassung" in text1
            
            # Check content in the barcode page
            text2 = pdf_reader.pages[3].extract_text()
            assert "Barcode Seite" in text2
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
        # Create a simple 100x100 black image
        img = PILImage.new('RGB', (100, 100), color='black')
        # Return a list with one image
        return [img]
    
    # Apply the monkeypatch
    monkeypatch.setattr('opensteuerauszug.render.render.render_to_barcodes', mock_render_to_barcodes)
    
    # Call the function
    make_barcode_pages(doc, story, sample_tax_statement, title_style)
    
    # Check that the story has been populated with elements
    assert len(story) > 0
    
    # Check for presence of key elements without making assumptions about specific implementation
    # Look for a paragraph that contains barcode text
    barcode_paragraph_found = any(
        isinstance(item, Paragraph) and "Barcode" in item.text 
        for item in story
    )
    assert barcode_paragraph_found, "No barcode-related paragraph found"
    
    # Check that at least one spacer is present (common in ReportLab layouts)
    spacer_found = any(isinstance(item, Spacer) for item in story)
    assert spacer_found, "No spacer found in the story"

@pytest.mark.integration
@pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
@mock.patch('opensteuerauszug.render.render.render_to_barcodes') # Mock at the source
def test_integration_render_all_samples(mock_render_to_barcodes, sample_file):
    """Integration test: run total calculator in FILL mode and render all sample imports to PDF."""
    mock_render_to_barcodes.return_value = [create_dummy_pil_image()] # Return a list with one dummy image

    # Load the tax statement from XML
    tax_statement = TaxStatement.from_xml_file(sample_file)
    # Run the total calculator in FILL mode
    calc = TotalCalculator(mode=CalculationMode.FILL)
    calc.calculate(tax_statement)
    # Render to PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        render_tax_statement(tax_statement, tmp_path)
        assert os.path.exists(tmp_path)
        assert os.path.getsize(tmp_path) > 0
    finally:
        if os.path.exists(tmp_path): # ensure it exists before trying to remove
            os.remove(tmp_path)

def test_create_bank_accounts_table_none():
    styles = getSampleStyleSheet()
    tax_statement = TaxStatement(minorVersion=2)
    result = create_bank_accounts_table(tax_statement, styles, 500)
    assert result is None

def test_create_bank_accounts_table_single_minimal():
    styles = get_custom_styles()
    tax_statement = TaxStatement(
        minorVersion=2,
        periodTo=date(2023, 12, 31),
        taxPeriod=2023,
        listOfBankAccounts=ListOfBankAccounts(
            bankAccount=[
                BankAccount(
                    bankAccountName=BankAccountName("Testkonto"),
                    iban="CH123",
                    taxValue=BankAccountTaxValue(
                        referenceDate=date(2023, 12, 31),
                        balanceCurrency="CHF",
                        balance=Decimal("100.00"),
                        exchangeRate=Decimal("1.0"),
                        value=Decimal("100.00")
                    ),
                    payment=[],
                    totalTaxValue=Decimal("100.00"),
                    totalGrossRevenueA=Decimal("10.00"),
                    totalGrossRevenueB=Decimal("5.00")
                )
            ],
            totalTaxValue=Decimal("100.00"),
            totalGrossRevenueA=Decimal("10.00"),
            totalGrossRevenueB=Decimal("5.00")
        )
    )
    table = create_bank_accounts_table(tax_statement, styles, 500)
    assert isinstance(table, Table)
    # Should have at least header + 2 rows (label, value)
    assert len(table._cellvalues) >= 3  # type: ignore[attr-defined]
    # Header row should contain expected text
    header_texts = [cell.text for cell in table._cellvalues[0] if isinstance(cell, Paragraph)]  # type: ignore[attr-defined]
    assert any("Datum" in t for t in header_texts)
    assert any("Bezeichnung" in t for t in header_texts)
    assert any("Bruttoertrag" in t for t in header_texts)

def test_create_bank_accounts_table_multiple_accounts_with_payments():
    styles = get_custom_styles()
    tax_statement = TaxStatement(
        minorVersion=2,
        periodTo=date(2023, 12, 31),
        taxPeriod=2023,
        listOfBankAccounts=ListOfBankAccounts(
            bankAccount=[
                BankAccount(
                    bankAccountName=BankAccountName("Konto1"),
                    iban="CH111",
                    taxValue=BankAccountTaxValue(
                        referenceDate=date(2023, 12, 31),
                        balanceCurrency="CHF",
                        balance=Decimal("200.00"),
                        exchangeRate=Decimal("1.0"),
                        value=Decimal("200.00")
                    ),
                    payment=[
                        BankAccountPayment(
                            paymentDate=date(2023, 6, 30),
                            name="Zinszahlung",
                            amountCurrency="CHF",
                            amount=Decimal("2.50"),
                            exchangeRate=Decimal("1.0"),
                            grossRevenueA=Decimal("2.50"),
                            grossRevenueB=Decimal("0.00")
                        )
                    ],
                    totalTaxValue=Decimal("200.00"),
                    totalGrossRevenueA=Decimal("2.50"),
                    totalGrossRevenueB=Decimal("0.00")
                ),
                BankAccount(
                    bankAccountName=BankAccountName("Konto2"),
                    iban="CH222",
                    taxValue=BankAccountTaxValue(
                        referenceDate=date(2023, 12, 31),
                        balanceCurrency="EUR",
                        balance=Decimal("300.00"),
                        exchangeRate=Decimal("0.95"),
                        value=Decimal("285.00")
                    ),
                    payment=[],
                    totalTaxValue=Decimal("285.00"),
                    totalGrossRevenueA=Decimal("0.00"),
                    totalGrossRevenueB=Decimal("0.00")
                )
            ],
            totalTaxValue=Decimal("485.00"),
            totalGrossRevenueA=Decimal("2.50"),
            totalGrossRevenueB=Decimal("0.00")
        )
    )
    table = create_bank_accounts_table(tax_statement, styles, 500)
    assert isinstance(table, Table)
    # Should have header + rows for each account and payment
    assert len(table._cellvalues) > 4  # type: ignore[attr-defined]
    # Check that both account names appear in the table
    all_text = " ".join(cell.text for row in table._cellvalues for cell in row if isinstance(cell, Paragraph))  # type: ignore[attr-defined]
    assert "Konto1" in all_text
    assert "Konto2" in all_text
    assert "Zinszahlung" in all_text


def test_create_bank_accounts_table_with_opening_date():
    """Test that openingDate is rendered as 'Eröffnung DD.MM.YYYY' below the IBAN."""
    styles = get_custom_styles()
    tax_statement = TaxStatement(
        minorVersion=2,
        periodTo=date(2023, 12, 31),
        taxPeriod=2023,
        listOfBankAccounts=ListOfBankAccounts(
            bankAccount=[
                BankAccount(
                    bankAccountName=BankAccountName("Testkonto"),
                    iban="CH123",
                    openingDate=date(2023, 5, 29),
                    taxValue=BankAccountTaxValue(
                        referenceDate=date(2023, 12, 31),
                        balanceCurrency="CHF",
                        balance=Decimal("100.00"),
                    ),
                    payment=[],
                    totalTaxValue=Decimal("100.00"),
                    totalGrossRevenueA=Decimal("0"),
                    totalGrossRevenueB=Decimal("0"),
                )
            ],
            totalTaxValue=Decimal("100.00"),
            totalGrossRevenueA=Decimal("0"),
            totalGrossRevenueB=Decimal("0"),
        ),
    )
    table = create_bank_accounts_table(tax_statement, styles, 500)
    assert isinstance(table, Table)
    # Find the account description cell and check for opening date text
    all_text = " ".join(
        cell.text for row in table._cellvalues for cell in row if isinstance(cell, Paragraph)
    )
    assert "Eröffnung 29.05.2023" in all_text


def test_create_bank_accounts_table_with_closing_date():
    """Test that closingDate is rendered as 'Saldierung DD.MM.YYYY' below the IBAN."""
    styles = get_custom_styles()
    tax_statement = TaxStatement(
        minorVersion=2,
        periodTo=date(2023, 12, 31),
        taxPeriod=2023,
        listOfBankAccounts=ListOfBankAccounts(
            bankAccount=[
                BankAccount(
                    bankAccountName=BankAccountName("Testkonto"),
                    iban="CH456",
                    closingDate=date(2023, 9, 15),
                    taxValue=BankAccountTaxValue(
                        referenceDate=date(2023, 12, 31),
                        balanceCurrency="CHF",
                        balance=Decimal("0.00"),
                    ),
                    payment=[],
                    totalTaxValue=Decimal("0"),
                    totalGrossRevenueA=Decimal("0"),
                    totalGrossRevenueB=Decimal("0"),
                )
            ],
            totalTaxValue=Decimal("0"),
            totalGrossRevenueA=Decimal("0"),
            totalGrossRevenueB=Decimal("0"),
        ),
    )
    table = create_bank_accounts_table(tax_statement, styles, 500)
    assert isinstance(table, Table)
    all_text = " ".join(
        cell.text for row in table._cellvalues for cell in row if isinstance(cell, Paragraph)
    )
    assert "Saldierung 15.09.2023" in all_text


def test_create_bank_accounts_table_with_both_dates():
    """Test that both openingDate and closingDate are rendered when set."""
    styles = get_custom_styles()
    tax_statement = TaxStatement(
        minorVersion=2,
        periodTo=date(2023, 12, 31),
        taxPeriod=2023,
        listOfBankAccounts=ListOfBankAccounts(
            bankAccount=[
                BankAccount(
                    bankAccountName=BankAccountName("Testkonto"),
                    iban="CH789",
                    openingDate=date(2023, 3, 1),
                    closingDate=date(2023, 11, 30),
                    taxValue=BankAccountTaxValue(
                        referenceDate=date(2023, 12, 31),
                        balanceCurrency="CHF",
                        balance=Decimal("0.00"),
                    ),
                    payment=[],
                    totalTaxValue=Decimal("0"),
                    totalGrossRevenueA=Decimal("0"),
                    totalGrossRevenueB=Decimal("0"),
                )
            ],
            totalTaxValue=Decimal("0"),
            totalGrossRevenueA=Decimal("0"),
            totalGrossRevenueB=Decimal("0"),
        ),
    )
    table = create_bank_accounts_table(tax_statement, styles, 500)
    assert isinstance(table, Table)
    all_text = " ".join(
        cell.text for row in table._cellvalues for cell in row if isinstance(cell, Paragraph)
    )
    assert "Eröffnung 01.03.2023" in all_text
    assert "Saldierung 30.11.2023" in all_text


def test_create_bank_accounts_table_without_dates():
    """Test that no date lines appear when openingDate/closingDate are None."""
    styles = get_custom_styles()
    tax_statement = TaxStatement(
        minorVersion=2,
        periodTo=date(2023, 12, 31),
        taxPeriod=2023,
        listOfBankAccounts=ListOfBankAccounts(
            bankAccount=[
                BankAccount(
                    bankAccountName=BankAccountName("Testkonto"),
                    iban="CH000",
                    openingDate=None,
                    closingDate=None,
                    taxValue=BankAccountTaxValue(
                        referenceDate=date(2023, 12, 31),
                        balanceCurrency="CHF",
                        balance=Decimal("100.00"),
                    ),
                    payment=[],
                    totalTaxValue=Decimal("100.00"),
                    totalGrossRevenueA=Decimal("0"),
                    totalGrossRevenueB=Decimal("0"),
                )
            ],
            totalTaxValue=Decimal("100.00"),
            totalGrossRevenueA=Decimal("0"),
            totalGrossRevenueB=Decimal("0"),
        ),
    )
    table = create_bank_accounts_table(tax_statement, styles, 500)
    assert isinstance(table, Table)
    all_text = " ".join(
        cell.text for row in table._cellvalues for cell in row if isinstance(cell, Paragraph)
    )
    assert "Eröffnung" not in all_text
    assert "Saldierung" not in all_text


def test_format_currency_trailing_zero():
    value_two_dec = Decimal("50.00")
    value_three_dec = Decimal("50.005")

    assert render.format_currency(value_two_dec) == "50.00"
    assert render.format_currency(value_three_dec) == "50.005"


def test_format_exchange_rate():
    """Test exchange rate formatting with 6 decimal digits."""
    # Test normal exchange rate with 6 decimals
    assert render.format_exchange_rate(Decimal("1.234567")) == "1.234567"
    
    # Test exchange rate with fewer decimals - should pad with zeros
    assert render.format_exchange_rate(Decimal("1.23")) == "1.230000"
    
    # Test exchange rate that needs rounding
    assert render.format_exchange_rate(Decimal("1.2345678")) == "1.234568"
    
    # Test exchange rate of 1 should return default (empty string)
    assert render.format_exchange_rate(Decimal("1")) == ""
    assert render.format_exchange_rate(Decimal("1.0")) == ""
    
    # Test None should return default
    assert render.format_exchange_rate(None) == ""
    
    # Test typical ESTV exchange rates (6 decimals)
    assert render.format_exchange_rate(Decimal("0.952381")) == "0.952381"
    assert render.format_exchange_rate(Decimal("1.095890")) == "1.095890"


def test_escape_html_for_paragraph():
    """Test HTML escaping for ReportLab Paragraph rendering."""
    # Test ampersand escaping
    assert render.escape_html_for_paragraph("S&P 500") == "S&amp;P 500"
    assert render.escape_html_for_paragraph("ISHARES CORE S&P 500") == "ISHARES CORE S&amp;P 500"
    
    # Test other HTML special characters
    assert render.escape_html_for_paragraph("<TEST>") == "&lt;TEST&gt;"
    assert render.escape_html_for_paragraph('"QUOTED"') == "&quot;QUOTED&quot;"
    assert render.escape_html_for_paragraph("A & B") == "A &amp; B"
    
    # Test combination of special characters
    assert render.escape_html_for_paragraph('TEST <FUND> "GROWTH" & \'VALUE\'') == 'TEST &lt;FUND&gt; &quot;GROWTH&quot; &amp; &#x27;VALUE&#x27;'
    
    # Test plain text (no escaping needed)
    assert render.escape_html_for_paragraph("Plain text") == "Plain text"
    assert render.escape_html_for_paragraph("TEST123") == "TEST123"
    
    # Test empty string
    assert render.escape_html_for_paragraph("") == ""


@mock.patch('opensteuerauszug.render.render.render_to_barcodes')
def test_security_name_with_ampersand_renders_correctly(mock_render_to_barcodes):
    """Test that ampersands in security names don't cause PDF rendering errors."""
    mock_render_to_barcodes.return_value = [create_dummy_pil_image()]
    
    # Create a tax statement with a security containing an ampersand
    tax_statement = TaxStatement(
        minorVersion=2,
        id="test-id-amp",
        creationDate=datetime(2023, 10, 26, 10, 30, 00),
        taxPeriod=2023,
        periodFrom=date(2023, 1, 1),
        periodTo=date(2023, 12, 31),
        canton="ZH",
        institution=Institution(name="Test Bank & Co AG"),
        client=[
            Client(
                clientNumber=ClientNumber("C1"),
                firstName="Max",
                lastName="Muster & Co",
                salutation="2"
            )
        ],
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="ISHARES CORE S&P 500",
                            isin=ISINType("US4642874576"),
                            valorNumber=ValorNumber(12345678),
                            totalTaxValue=Decimal("950.00"),
                            totalGrossRevenueA=Decimal("0"),
                            totalGrossRevenueB=Decimal("0")
                        )
                    ]
                )
            ],
            totalTaxValue=Decimal("950.00"),
            totalGrossRevenueA=Decimal("0"),
            totalGrossRevenueB=Decimal("0"),
            totalWithHoldingTaxClaim=Decimal("0"),
            totalLumpSumTaxCredit=Decimal("0"),
            totalNonRecoverableTax=Decimal("0"),
            totalAdditionalWithHoldingTaxUSA=Decimal("0"),
            totalGrossRevenueIUP=Decimal("0"),
            totalGrossRevenueConversion=Decimal("0")
        ),
        totalTaxValue=Decimal("950.00"),
        svTaxValueA=Decimal("950.00"),
        svTaxValueB=Decimal("0"),
        totalGrossRevenueA=Decimal("0"),
        totalGrossRevenueB=Decimal("0"),
        totalWithHoldingTaxClaim=Decimal("0")
    )
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_path = temp_file.name
    
    try:
        # Main test: Render the tax statement to PDF should not crash
        render_tax_statement(tax_statement, temp_path)
        
        # Check that the file exists and has content
        assert os.path.exists(temp_path)
        assert os.path.getsize(temp_path) > 0
        
        # Check content in the PDF - verify client name with ampersand renders correctly
        with open(temp_path, "rb") as f:
            pdf_reader = pypdf.PdfReader(f)
            all_text = ""
            for page in pdf_reader.pages:
                all_text += page.extract_text()
            
            # Client name should appear without spurious semicolons
            assert "Muster & Co" in all_text or "Muster &amp; Co" in all_text or "Muster" in all_text
            # Make sure there's no spurious semicolon from incorrect HTML entity parsing
            assert "Muster &amp; ; Co" not in all_text
            assert "Muster &; Co" not in all_text
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@mock.patch('opensteuerauszug.render.render.render_to_barcodes')
def test_security_name_with_html_special_chars_renders_correctly(mock_render_to_barcodes):
    """Test that HTML special characters in security names don't crash PDF rendering."""
    mock_render_to_barcodes.return_value = [create_dummy_pil_image()]
    
    # Create a tax statement with securities containing various HTML special characters
    tax_statement = TaxStatement(
        minorVersion=2,
        id="test-id-html",
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
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName='TEST <FUND> "GROWTH" & \'VALUE\'',
                            isin=ISINType("US1234567890"),
                            valorNumber=ValorNumber(12345679),
                            totalTaxValue=Decimal("237.50"),
                            totalGrossRevenueA=Decimal("0"),
                            totalGrossRevenueB=Decimal("0")
                        )
                    ]
                )
            ],
            totalTaxValue=Decimal("237.50"),
            totalGrossRevenueA=Decimal("0"),
            totalGrossRevenueB=Decimal("0"),
            totalWithHoldingTaxClaim=Decimal("0"),
            totalLumpSumTaxCredit=Decimal("0"),
            totalNonRecoverableTax=Decimal("0"),
            totalAdditionalWithHoldingTaxUSA=Decimal("0"),
            totalGrossRevenueIUP=Decimal("0"),
            totalGrossRevenueConversion=Decimal("0")
        ),
        totalTaxValue=Decimal("237.50"),
        svTaxValueA=Decimal("237.50"),
        svTaxValueB=Decimal("0"),
        totalGrossRevenueA=Decimal("0"),
        totalGrossRevenueB=Decimal("0"),
        totalWithHoldingTaxClaim=Decimal("0")
    )
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_path = temp_file.name
    
    try:
        # Main test: Render the tax statement to PDF should not crash
        # even with special characters in security names
        render_tax_statement(tax_statement, temp_path)
        
        # Check that the file exists and has content
        assert os.path.exists(temp_path)
        assert os.path.getsize(temp_path) > 0
        
        # The PDF was created successfully - that's the main test
        # (actual security rendering may require more complete data structure)
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.unlink(temp_path)

