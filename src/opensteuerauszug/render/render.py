import io
from math import floor
import sys
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, Union
from decimal import Decimal, ROUND_HALF_UP
import zlib
from PIL import Image as PILImage

# --- ReportLab Imports ---
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, 
    PageBreak, KeepTogether, Frame, PageTemplate, FrameActionFlowable,
    BaseDocTemplate, NextPageTemplate
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape

# --- Import TaxStatement model ---
from opensteuerauszug.model.ech0196 import TaxStatement

# --- Import OneDeeBarCode for barcode rendering ---
from opensteuerauszug.render.onedee import OneDeeBarCode

# --- Import Organisation helper functions ---
from opensteuerauszug.core.organisation import compute_org_nr

# --- Configuration ---
COMPANY_NAME = "Bank WIR"
DOC_INFO = "S. E. & O."

__all__ = [
    'render_tax_statement',
    'render_statement_info',
    'make_barcode_pages',
    'BarcodeDocTemplate'
]

# Custom document template with barcode support
class BarcodeDocTemplate(BaseDocTemplate):
    """Custom document template with support for barcode rendering."""
    
    def __init__(self, filename, **kwargs):
        """Initialize with barcode attributes."""
        super().__init__(filename, **kwargs)
        self.onedee_generator: Optional[OneDeeBarCode] = None
        self.org_nr: str = '00000'
        self.page_count: int = 1
        self.is_barcode_page: bool = False

# --- Helper Function for Currency Formatting ---
def format_currency(value, default='0.00'):
    # (Same as v7)
    if value is None or value == '': return default
    try:
        decimal_value = Decimal(str(value)).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
        formatted = '{:,.0f}'.format(decimal_value).replace(',', "'")
        return formatted
    except: return default

# --- Header/Footer Drawing Functions (for SimpleDocTemplate) ---

def draw_page_header(canvas, doc):
    """Draws the header content on each page."""
    canvas.saveState()
    page_width = doc.pagesize[0]
    page_height = doc.pagesize[1]
    canvas.setFont('Helvetica', 9)
    header_text = "7010001 | 85506710549033 | 8391" # Example header
    canvas.setFillColor(colors.black)
    header_x = page_width - doc.rightMargin
    header_y = page_height - doc.topMargin + 10*mm # Adjust position as needed
    canvas.drawRightString(header_x, header_y, header_text)
    
    # Draw the barcode if page specific data is available
    if isinstance(doc, BarcodeDocTemplate) and doc.onedee_generator:
        page_num = canvas.getPageNumber()
        # Barcode page flag is true for the dedicated barcode pages at the end
        is_barcode_page = doc.is_barcode_page and page_num > doc.page_count - 1
        barcode_widget = doc.onedee_generator.generate_barcode(
            page_number=page_num, 
            is_barcode_page=is_barcode_page,
            org_nr=doc.org_nr
        )
        if barcode_widget:
            doc.onedee_generator.draw_barcode_on_canvas(canvas, barcode_widget, doc.pagesize)
    
    canvas.restoreState()

def draw_page_footer(canvas, doc):
    """Draws the footer content and page number on each page."""
    canvas.saveState()
    page_width = doc.pagesize[0]
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(colors.grey)
    footer_y = doc.bottomMargin - 10*mm # Adjust position
    # Company Name
    canvas.drawString(doc.leftMargin, footer_y, COMPANY_NAME)
    # Doc Info
    canvas.drawCentredString(page_width / 2.0, footer_y, DOC_INFO)
    # Page Number - Standard onPageEnd handlers typically only get current page number
    page_num = canvas.getPageNumber()
    text = f"Seite {page_num}"
    canvas.drawRightString(page_width - doc.rightMargin, footer_y, text)
    canvas.restoreState()

# --- Table Creation Functions ---

def create_summary_table(data, styles, usable_width):
    """Creates the main summary table using a 6-COLUMN STRUCTURE with shifted Totals (v8)."""
    if 'summary' not in data: return None
    summary_data = data['summary']

    # Use styles passed from generate_pdf
    header_style = styles['Header_RIGHT'] # Not bold
    val_left = styles['Val_LEFT']
    val_right = styles['Val_RIGHT']
    val_center = styles['Val_CENTER']

    # --- Data structure based on 6 columns, with Totals shifted ---
    table_data = [
        # Row 0: A/B Headers (Indices 2 & 5 blank)
        [Paragraph('Steuerwert der A- und B-Werte am 31.12.2024', header_style),
         '',         
         Paragraph('A', val_center), # 'A' in its own column (index 2)
         Paragraph('Bruttoertrag 2024 Werte mit VSt.-Abzug', header_style),
         Paragraph('B', val_center), # 'B' in its own column (index 2)
         Paragraph('Bruttoertrag 2024 Werte ohne VSt.-Abzug', header_style),
         Paragraph('Verrechnungs- steueranspruch', header_style), '',
         Paragraph('''Werte für Formular "Wertschriften- und Guthabenverzeichnis"
(inkl. Konti, ohne Werte DA-1 und USA)
(1) Davon A 10'063 und B 0''', val_left)],
        # Row 1: A/B Values (Index 2 is 'B', Index 5 blank)
        [Paragraph(format_currency(summary_data.get('steuerwert_ab')), val_right),
         Paragraph("(1)", val_left),
         '',
         Paragraph(format_currency(summary_data.get('brutto_mit_vst')), val_right),
         '',
         Paragraph(format_currency(summary_data.get('brutto_ohne_vst')), val_right),
         Paragraph(format_currency(summary_data.get('vst_anspruch')), val_right),
         ''],
        # Row 2: Spacer row (6 columns)
        ['', '', '', '', '', ''],
         # Row 3: DA-1 Headers (Indices 1 & 2 blank)
        [Paragraph('Steuerwert der DA-1 und USA- Werte am 31.12.2024', header_style),
         '', '', '', '',
         Paragraph('Bruttoertrag 2024 DA-1 und USA-Werte', header_style), # Starts in Col 4
         Paragraph('Pauschale Steueranrechnung (DA-1)', header_style), 
         Paragraph('Steuerrückbehalt USA', header_style),
         Paragraph('''Werte für zusätzliches Formular "DA-1 Antrag auf Anrechnung
ausländischer Quellensteuer und zusätzlichen Steuerrückbehalt
USA"''', val_left)], #
         # Row 4: DA-1 Values (Indices 1 & 2 blank)
        [Paragraph(format_currency(summary_data.get('steuerwert_da1_usa')), val_right),
         '', '', '', '',
         Paragraph(format_currency(summary_data.get('brutto_da1_usa')), val_right), # Starts in Col 3
         Paragraph(format_currency(summary_data.get('pauschale_da1')), val_right), # Col 4
         Paragraph(format_currency(summary_data.get('rueckbehalt_usa')), val_right),
         '',
], # Col 5
        # Row 5: Spacer row (6 columns)
        ['', '', '', '', '', ''],
        # Row 6: Total Headers (** SHIFTED RIGHT **, Indices 1, 2, 5 blank)
        [Paragraph('Total Steuerwert der A,B,DA-1 und USA-Werte', header_style), # Col 0
         '',
         '', 
         Paragraph('Total Bruttoertrag 2024 A-Werte mit VSt.-Abzug', header_style), # Col 3 << SHIFTED
         '', 
         Paragraph('Total Bruttoertrag 2024 B,DA-1 und USA-Werte ohne VSt.-Abzug', header_style), # Col 4 << SHIFTED
         Paragraph('Total Bruttoertrag 2024 A.B.DA-1 und USA-Werte', header_style),
         "",
                  Paragraph('''Falls keine Anrechnung ausländischer Quellensteuern (DA-1)
geltend gemacht wird, sind diese Totalwerte im
Wertschriftenverzeichnis einzusetzen.''', val_left)], # Col 5 << SHIFTED
         # Row 7: Total Values (** SHIFTED RIGHT **, Indices 1, 2, 5 blank)
        [Paragraph(format_currency(summary_data.get('total_steuerwert')), val_right), # Col 0
         '',
         '', 
         Paragraph(format_currency(summary_data.get('total_brutto_mit_vst')), val_right), # Col 3 << SHIFTED
         '', 
         Paragraph(format_currency(summary_data.get('total_brutto_ohne_vst')), val_right),# Col 4 << SHIFTED
         Paragraph(format_currency(summary_data.get('total_brutto_gesamt')), val_right)],   # Col 5 << SHIFTED
    ]

    usable_width = usable_width - 2.5*8 - 8 - 16
    base_col_width = usable_width / 7
    col_widths = [base_col_width, # Col 0: Steuerwert
                  2.5*8, # Col 1: Footnotes
                  8, # Col 2: 'A' / Blank
                  base_col_width, # Col 3: Brutto mit VSt (Header only) / Blank
                  16, # Col 4: 'B' / Blank
                  base_col_width, # Col 5: Brutto ohne VSt / Brutto DA-1 / Total mit VSt << Needs width
                  base_col_width, # Col 6: Verrechnungsst / Pauschale / Total ohne VSt << Needs width
                  base_col_width, # Col 7: Blank / Steuerrueckbehalt / Total Gesamt << Needs width
                  2*base_col_width, # Col 8: Description / Istrunctions
                  ] 

    row_heights = [15*mm, 6*mm, 2*mm, 15*mm, 6*mm, 2*mm, 15*mm, 6*mm]
    summary_table = Table(table_data, colWidths=col_widths, rowHeights=row_heights)

    # --- Table Style ---

    # --- Define common styles ---
    common_padding = [
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        # footnote colunn
        ('LEFTPADDING', (1, 0), (1, -1), 1),
    ]
    common_valign = ('VALIGN', (0, 0), (-1, -1), 'BOTTOM')
    line_style = (0.7, colors.black)
    no_line_style = (0, colors.white) # Or use (0.5, colors.white) if background isn't white

    # --- Define spacer row styles ---
    spacer_row_2_style = [
        ('TOPPADDING', (0, 2), (-1, 2), 0), ('BOTTOMPADDING', (0, 2), (-1, 2), 0),
    ]
    spacer_row_5_style = [
        ('TOPPADDING', (0, 5), (-1, 5), 0), ('BOTTOMPADDING', (0, 5), (-1, 5), 0),
    ]

    # --- Define line styles ---
    # Apply lines generally first, then remove where needed
    line_commands = [
        # Row 0 Headers (A/B) 
        ('LINEBELOW', (0, 0), (-1, 0), *line_style), # Apply to whole row
        ('LINEBELOW', (1, 0), (2, 0), *no_line_style), 
        ('LINEBELOW', (3, 0), (3, 0), *no_line_style),
        # Add more ('LINEBELOW', (col_index, 0), (col_index, 0), *no_line_style) for other cols if needed

        # Row 3 Headers (DA-1) 
        ('LINEBELOW', (0, 3), (-1, 3), *line_style), # Apply to whole row
        ('LINEBELOW', (1, 3), (3, 3), *no_line_style), # Remove from col 1

        # Row 6 Headers (Totals) - Apply line above all, then below specific cols
        ('LINEABOVE', (0, 6), (-1, 6), *line_style), # Line above all total headers
        ('LINEBELOW', (0, 6), (-1, 6), *line_style), # Apply below all initially
        ('LINEBELOW', (1, 6), (2, 6), *no_line_style), # Remove from cols 1, 2
        ('LINEBELOW', (3, 6), (4, 6), *no_line_style), # Remove from col 3
        # Footnotes column 
        ('LINEBELOW', (1, 0), (1, -1), *no_line_style),
        # A column 
        ('LINEBELOW', (2, 0), (2, -1), *no_line_style),
        # B column 
        ('LINEBELOW', (4, 0), (4, -1), *no_line_style),
        # Description column 
        ('LINEBELOW', (8, 0), (8, -1), *no_line_style),
    ]

    # --- Combine all styles ---
    style_commands = [
        common_valign,
        *common_padding,
        *spacer_row_2_style,
        *spacer_row_5_style,
        *line_commands,
        # ('GRID', (0,0), (-1,-1), 0.2, colors.lightgrey) # Debug grid
    ]

    # --- Apply the combined style ---
    summary_table.setStyle(TableStyle(style_commands))

    # --- Explanation ---
    # How it works:
    # 1. We define styles for padding, alignment, spacers, and lines separately for clarity.
    # 2. For rows where you want lines under *most* columns (like rows 0, 3, 6):
    #    - We first apply 'LINEBELOW' to the entire row using `(0, row_index), (-1, row_index)`.
    #    - Then, for specific columns where you *don't* want the line, we add another
    #      'LINEBELOW' command targeting just that cell (or range of cells) but set the
    #      line width to 0 or the color to match the background (e.g., colors.white).
    #      This effectively "erases" the line drawn by the previous command for that cell.
    # 3. This makes adding/removing columns easier:
    #    - If you add a column and want a line below it in row 0, you don't need to do anything
    #      if it's not column 2 (as the general rule covers it).
    #    - If you remove column 3, you just need to adjust the ranges in the "remove" commands
    #      if necessary (e.g., if column 4 becomes the new column 3).
    #    - You primarily manage the exceptions (where lines are removed) rather than adding
    #      individual lines for most columns.

    # Footnote
    footnote_text = "(1) Davon A {} und B {}".format(
        format_currency(summary_data.get('steuerwert_a', '')),
        format_currency(summary_data.get('steuerwert_b', ''))
    )
    footnote = Paragraph(footnote_text, val_left)
    return KeepTogether([summary_table, Spacer(1, 2*mm), footnote])

# --- Liabilities Table Function ---
def create_liabilities_table(data, styles, usable_width):
    """Creates a table displaying liabilities information.
    
    Args:
        data: Dictionary containing the liabilities data
        styles: Dictionary of styles for text formatting
        usable_width: Available width for the table
        
    Returns:
        A Table object containing the liabilities data or None if no data
    """
    if not data.get('liabilities'): return None
    header_style = styles['Header_CENTER']
    val_left = styles['Val_LEFT']
    val_right = styles['Val_RIGHT']
    val_center = styles['Val_CENTER']
    bold_left = styles['Bold_LEFT']
    bold_right = styles['Bold_RIGHT']
    table_data = [ [Paragraph('Datum', header_style), Paragraph('Bezeichnung<br/>Schulden<br/>Zinsen', header_style), Paragraph('Währung', header_style), Paragraph('Schulden', header_style), Paragraph('Kurs', header_style), Paragraph('Schulden<br/>31.12.2024<br/>in CHF', header_style), Paragraph('Schuldzinsen<br/>2024<br/>in CHF', header_style)] ]
    total_debt = Decimal(0); total_interest = Decimal(0)
    for item in data['liabilities']:
        if 'transactions' in item:
             for trans in item['transactions']: table_data.append([ Paragraph(trans.get('date', ''), val_left), Paragraph(trans.get('description', ''), val_left), Paragraph(item.get('currency', 'CHF'), val_center), Paragraph(format_currency(trans.get('amount')), val_right), '', '', Paragraph(format_currency(trans.get('amount')), val_right) ])
        table_data.append([ Paragraph(item.get('date', '31.12.2024'), val_left), Paragraph(item.get('description', '').replace('\n', '<br/>'), val_left), Paragraph(item.get('currency', 'CHF'), val_center), Paragraph(format_currency(item.get('amount')), val_right), Paragraph(item.get('rate', ''), val_right), Paragraph(format_currency(item.get('value_chf')), val_right), Paragraph(format_currency(item.get('total_interest')), val_right) ])
        total_debt += Decimal(str(item.get('value_chf', 0))); total_interest += Decimal(str(item.get('total_interest', 0)))
    table_data.append([ '', Paragraph('Total Schulden', bold_left), '', '', '', Paragraph(format_currency(total_debt), bold_right), Paragraph(format_currency(total_interest), bold_right) ])
    col_widths = [30*mm, 100*mm, 20*mm, 27*mm, 20*mm, 30*mm, 30*mm]
    liabilities_table = Table(table_data, colWidths=col_widths)
    liabilities_table.setStyle(TableStyle([ ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 1), ('RIGHTPADDING', (0, 0), (-1, -1), 1), ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1), ('LINEBELOW', (0, 0), (-1, 0), 1, colors.black), ('BOTTOMPADDING', (0, 0), (-1, 0), 3*mm), ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black), ('TOPPADDING', (0, -1), (-1, -1), 3*mm), ]))
    return liabilities_table

# --- Costs Table Function ---
def create_costs_table(data, styles, usable_width):
    """Creates a table displaying bank costs information.
    
    Args:
        data: Dictionary containing the costs data
        styles: Dictionary of styles for text formatting
        usable_width: Available width for the table
        
    Returns:
        A KeepTogether object containing the costs table and footnote or None if no data
    """
    if not data.get('costs'): return None
    header_left_style = styles['Header_LEFT']
    header_right_style = styles['Header_RIGHT']
    val_left = styles['Val_LEFT']
    val_right = styles['Val_RIGHT']
    bold_left = styles['Bold_LEFT']
    bold_right = styles['Bold_RIGHT']
    table_data = [ [Paragraph('Bezeichnung', header_left_style), Paragraph('Spesentyp', header_left_style), Paragraph('Wert<br/>31.12.2024<br/>in CHF', header_right_style)] ]
    total_costs = Decimal(0)
    for item in data['costs']: table_data.append([ Paragraph(item.get('description', ''), val_left), Paragraph(item.get('type', ''), val_left), Paragraph(format_currency(item.get('value_chf')), val_right) ]); total_costs += Decimal(str(item.get('value_chf', 0)))
    table_data.append([ Paragraph('Total bezahlte Bankspesen', bold_left), '', Paragraph(format_currency(total_costs), bold_right) ])
    col_widths = [110*mm, 97*mm, 50*mm]
    costs_table = Table(table_data, colWidths=col_widths)
    costs_table.setStyle(TableStyle([ ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 1), ('RIGHTPADDING', (0, 0), (-1, -1), 1), ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1), ('LINEBELOW', (0, 0), (-1, 0), 1, colors.black), ('BOTTOMPADDING', (0, 0), (-1, 0), 3*mm), ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black), ('TOPPADDING', (0, -1), (-1, -1), 3*mm), ]))
    footnote_text = '(2) Über die Abzugsfähigkeit der Spesen entscheidet die zuständige Veranlagungsbehörde.'
    return KeepTogether([costs_table, Spacer(1, 2*mm), Paragraph(footnote_text, val_left)])


# --- Barcode Generation ---
def get_barcode_image(data):
    """Generate a barcode image from the given data using Code128.
    
    Args:
        data: The data to encode in the barcode
        
    Returns:
        A PIL Image object containing the barcode
    """
    try:
        from barcode.writer import ImageWriter
        from barcode import Code128
        code = Code128(str(data), writer=ImageWriter())
        pil_img = code.render(writer_options={'write_text': False, 'module_height': 10.0})
        return pil_img
    except ImportError:
        # Fallback to a placeholder if barcode library isn't available
        img = PILImage.new('RGB', (800, 150), color='grey')
        return img
    except Exception as e:
        # Return a red placeholder in case of errors
        img = PILImage.new('RGB', (800, 150), color='red')
        return img

def render_statement_info(tax_statement: TaxStatement, story: list, client_info_style: ParagraphStyle) -> None:
    """Add client, institution, period, and creation date information to the PDF story.
    
    Args:
        tax_statement: The TaxStatement model containing the information
        story: The reportlab story list to append elements to
        client_info_style: The paragraph style to use for the info elements
    """
    # Extract client data
    client_name = ""
    client_address = ""
    portfolio = ""
    
    if tax_statement.client and len(tax_statement.client) > 0:
        client = tax_statement.client[0]
        
        # Prepare client name with salutation
        salutation = ""
        if hasattr(client, 'salutation') and client.salutation:
            salutation_codes = {"1": "", "2": "Herr", "3": "Frau"}
            salutation = salutation_codes.get(client.salutation, "")
        
        name_parts = []
        if salutation:
            name_parts.append(salutation)
        if hasattr(client, 'firstName') and client.firstName:
            name_parts.append(client.firstName)
        if hasattr(client, 'lastName') and client.lastName:
            name_parts.append(client.lastName)
        
        client_name = " ".join(name_parts)
        
        # Set portfolio if available
        if hasattr(client, 'clientNumber'):
            portfolio = str(client.clientNumber)
    
    # Add client info to the PDF
    if client_name:
        story.append(Paragraph(f"<b>Kunde:</b> {client_name}", client_info_style))
    if client_address:
        story.append(Paragraph(f"<b>Adresse:</b> {client_address}", client_info_style))
    if portfolio:
        story.append(Paragraph(f"<b>Portfolio:</b> {portfolio}", client_info_style))
    
    # Add institution information
    if hasattr(tax_statement, 'institution') and tax_statement.institution:
        institution_name = tax_statement.institution.name if hasattr(tax_statement.institution, 'name') else ""
        if institution_name:
            story.append(Paragraph(f"<b>Institution:</b> {institution_name}", client_info_style))
    
    # Period information
    period_from = ""
    period_to = ""
    
    if hasattr(tax_statement, 'taxPeriod'):
        story.append(Paragraph(f"<b>Steuerjahr:</b> {tax_statement.taxPeriod}", client_info_style))
    
    if hasattr(tax_statement, 'periodFrom') and tax_statement.periodFrom:
        period_from = tax_statement.periodFrom.strftime("%d.%m.%Y")
    
    if hasattr(tax_statement, 'periodTo') and tax_statement.periodTo:
        period_to = tax_statement.periodTo.strftime("%d.%m.%Y")
    
    if period_from and period_to:
        period_text = f"{period_from} - {period_to}"
        story.append(Paragraph(f"<b>Periode:</b> {period_text}", client_info_style))
    
    # Creation date
    if hasattr(tax_statement, 'creationDate') and tax_statement.creationDate:
        created_date = tax_statement.creationDate.strftime("%d.%m.%Y")
        story.append(Paragraph(f"<b>Erstellt am:</b> {created_date}", client_info_style))
    
    story.append(Spacer(1, 0.5*cm))


def render_to_barcodes(tax_statement: TaxStatement) -> list[PILImage.Image]:
    """Render the tax statement to a list of barcode images.
    
    Args:
        tax_statement: The TaxStatement model to render
        
    Returns:
        A list of PIL Image objects containing the barcode images
    """ 
    from pdf417gen import encode_macro, render_image
    
    xml = tax_statement.to_xml_bytes()
    data = zlib.compress(xml)

    # Follow Guidance in "Beilage zu eCH-0196 V2.2.0 – Barcode Generierung – Technische Wegleitung"
    # our library foes not allow setting the row_count, so guess by making the segments roughly
    # right
    # Overhead:
    #    1  start word
    #    1 + 2 + 1 macro pdf fields with 1 word file ID
    #    4 for segment count
    #    1 for possible last code marker
    #    32 error correction at level 4
    #    1 for specifying byte encoding
    # gives 43 words of overhead
    FIXED_OVERHEAD = 43
    # Given in the guidance
    NUM_COLUMNS = 13
    NUM_ROWS = 35
    CAPACTITY = NUM_COLUMNS * NUM_ROWS - FIXED_OVERHEAD
    # Byte encodinge efficency is 6 bytes per 5 codewords
    SEGMENT_SIZE = floor((CAPACTITY / 5) * 6)

    # We want to have 13 columns, so calculate the data length per column
    codes = encode_macro(
        data,
        file_id=[1],
        columns=NUM_COLUMNS,
        force_rows=NUM_ROWS,
        security_level=4,
        segment_size=SEGMENT_SIZE,
        force_binary=True,
    )
    images = []
    for i, barcode in enumerate(codes):
        image = render_image(
            barcode,
            # generate 1 pixel for unit, we will scale later
            scale=1,
            # per guidance
            ratio=2,
            padding=0,
        )
        images.append(image)
    
    return images
    
def make_barcode_pages(doc: BarcodeDocTemplate, story: list, tax_statement: TaxStatement, title_style: ParagraphStyle) -> None:
    """
    Configure the document for barcode pages and add barcode page content to the story.
    
    Args:
        doc: The document template to configure
        story: The story to append to
        tax_statement: The tax statement model
        title_style: Style to use for page titles
    """
    # Generate the 2D PDF417 barcodes
    barcode_images = render_to_barcodes(tax_statement)
    
    # Render on page according to "Beilage zu eCH-0196 V2.2.0 – Barcode Generierung – Technische Wegleitung""
    # Calculate how many pages we need - guidance spec says 6 barcodes per page
    barcodes_per_page = 6
    barcode_pages = (len(barcode_images) + barcodes_per_page - 1) // barcodes_per_page  # Ceiling division
        
    # Force a page break for the barcode section
    story.append(NextPageTemplate('main'))
    
    # Get styles
    styles = getSampleStyleSheet()
    center_style = ParagraphStyle(name='Center', parent=styles['Normal'], alignment=TA_CENTER)
    
    # Scaling for barcodes - each module (pixel) should be 0.4 - 0,42 mm.
    scale_factor_col = 0.42 * mm
    scale_factor_row = 0.4 * mm
    
    # Calculate available width and height
    page_width, page_height = landscape(A4)
    available_width = page_width - (doc.leftMargin + doc.rightMargin)
    available_height = page_height - (doc.topMargin + doc.bottomMargin)
    
    # Process barcodes in groups
    for page_num in range(barcode_pages):
        story.append(PageBreak())
        doc.is_barcode_page = True
        story.append(Paragraph(f"Barcode Page {page_num + 1} of {barcode_pages}", title_style))
        story.append(Spacer(1, 0.5*cm))
        
        # Calculate start and end indices for this page
        start_idx = page_num * barcodes_per_page
        end_idx = min(start_idx + barcodes_per_page, len(barcode_images))
        
        # Create table for this page's barcodes
        table_data = []
        
        row = []
        for i in range(start_idx, end_idx):
            # Get the barcode image
            img = barcode_images[i]
            
            # rotate image 90 degree clockwise
            img = img.rotate(-90, expand=True)

            # Scale dimensions
            scaled_width = img.width * scale_factor_row
            scaled_height = img.height * scale_factor_col
            
            # Convert to ReportLab image
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            rl_img = Image(img_buffer, width=scaled_width, height=scaled_height)
            
            # push in front of row
            row.insert(0, rl_img)
                
        table_data.append(row)
        
        # Calculate column widths
        col_width = (available_width / barcodes_per_page)
        col_widths = [col_width] * (end_idx - start_idx)
        
        # Create table with proper alignment
        table = Table(
            table_data,
            colWidths=col_widths,
            spaceBefore=0.5*cm,
            spaceAfter=1*cm,
            hAlign='RIGHT'  # Align entire table to the right (rotated clockwise)
        )
        
        # Add styling to table
        table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),  # Left align cell contents
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # Vertically center content
            ('LEFTPADDING', (0, 0), (-1, -1), 2*cm),  # Remove left padding
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),  # Remove right padding
        ]))
        
        story.append(table)
  
# --- Main API function to be called from steuerauszug.py ---
def render_tax_statement(tax_statement: TaxStatement, output_path: Union[str, Path], override_org_nr: Optional[str] = None) -> Path:
    """Render a tax statement to PDF.
    
    Args:
        tax_statement: The TaxStatement model to render
        output_path: Path where to save the generated PDF
        override_org_nr: Optional override for organization number (5 digits)
        
    Returns:
        Path to the generated PDF file
    """
    # Convert to string path if it's a Path object
    output_path = str(output_path) if isinstance(output_path, Path) else output_path
    
    buffer = io.BytesIO()
    page_width, page_height = landscape(A4)
    left_margin = 20*mm # This leaves enough space for the barcode
    right_margin = 20*mm
    top_margin = 25*mm
    bottom_margin = 25*mm
    usable_width = page_width - left_margin - right_margin

    # Define frame for the main content area
    frame = Frame(left_margin, bottom_margin, usable_width, page_height - top_margin - bottom_margin,
                  id='normal')

    # Create the page template with header/footer functions
    page_template = PageTemplate(id='main', frames=[frame],
                                 onPage=draw_page_header, 
                                 onPageEnd=draw_page_footer)

    # Use BarcodeDocTemplate for barcode support
    doc = BarcodeDocTemplate(buffer,
                             pagesize=landscape(A4),
                             pageTemplates=[page_template],
                             leftMargin=left_margin,
                             rightMargin=right_margin,
                             topMargin=top_margin,
                             bottomMargin=bottom_margin)
    
    # Set up barcode generator
    doc.onedee_generator = OneDeeBarCode()
    
    # Compute the organization number
    doc.org_nr = compute_org_nr(tax_statement, override_org_nr)
    
    # --- Define styles centrally (same as before) ---
    styles = getSampleStyleSheet()
    base_style = styles['Normal']
    base_style.fontSize = 8
    styles.add(ParagraphStyle(name='Header_LEFT', parent=base_style, alignment=TA_LEFT, fontName='Helvetica'))
    styles.add(ParagraphStyle(name='Header_CENTER', parent=base_style, alignment=TA_CENTER, fontName='Helvetica'))
    styles.add(ParagraphStyle(name='Header_RIGHT', parent=base_style, alignment=TA_RIGHT, fontName='Helvetica'))
    styles.add(ParagraphStyle(name='Val_LEFT', parent=base_style, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name='Val_RIGHT', parent=base_style, alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='Val_CENTER', parent=base_style, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='Bold_LEFT', parent=styles['Val_LEFT'], fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='Bold_RIGHT', parent=styles['Val_RIGHT'], fontName='Helvetica-Bold'))

    story = []

    # --- Add Client Header Info ---
    client_info_style = ParagraphStyle(name='ClientInfo', parent=styles['Normal'], fontSize=9, spaceAfter=3*mm)
    
    # Render statement information
    render_statement_info(tax_statement, story, client_info_style)

    # --- Sections ---
    title_style = ParagraphStyle(name='SectionTitle', parent=styles['h2'], alignment=TA_LEFT, fontSize=10, spaceAfter=4*mm)

    # 1. Summary Section
    story.append(Paragraph("Steuerauszug | Zusammenfassung", title_style))
    
    # Extract summary data directly from tax_statement
    total_gross_revenue_a = tax_statement.totalGrossRevenueA if hasattr(tax_statement, 'totalGrossRevenueA') and tax_statement.totalGrossRevenueA is not None else Decimal('0')
    total_gross_revenue_b = tax_statement.totalGrossRevenueB if hasattr(tax_statement, 'totalGrossRevenueB') and tax_statement.totalGrossRevenueB is not None else Decimal('0')
    
    summary_data = {
        "steuerwert": tax_statement.totalTaxValue if hasattr(tax_statement, 'totalTaxValue') else None,
        "steuerwert_a": total_gross_revenue_a,
        "steuerwert_b": total_gross_revenue_b,
        "brutto_mit_vst": total_gross_revenue_a,
        "brutto_ohne_vst": total_gross_revenue_b,
        "vst_anspruch": tax_statement.totalWithHoldingTaxClaim if hasattr(tax_statement, 'totalWithHoldingTaxClaim') else None,
        "steuerwert_da1_usa": Decimal('0'),
        "brutto_da1_usa": Decimal('0'),
        "pauschale_da1": Decimal('0'),
        "rueckbehalt_usa": Decimal('0'),
        "total_steuerwert": tax_statement.totalTaxValue if hasattr(tax_statement, 'totalTaxValue') else None,
        "total_brutto_mit_vst": total_gross_revenue_a,
        "total_brutto_ohne_vst": total_gross_revenue_b,
        "total_brutto_gesamt": total_gross_revenue_a + total_gross_revenue_b
    }
    
    # Create summary table with direct data
    summary_table_data = create_summary_table({"summary": summary_data}, styles, usable_width)
    if summary_table_data:
        story.append(summary_table_data)
    
    story.append(Spacer(1, 0.5*cm))
    
    # Add the barcode page
    make_barcode_pages(doc, story, tax_statement, title_style)
    
    # Build the PDF
    doc.build(story)
    
    pdf_data = buffer.getvalue()
    buffer.close()
    
    # Write to file
    with open(output_path, 'wb') as f:
        f.write(pdf_data)
    
    return Path(output_path)


# --- Main function for testing ---
def main():
    """Main function for testing the render module directly."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Render a tax statement to PDF')
    parser.add_argument('--input', type=str, default='tests/samples/fake_statement.xml',
                         help='Input XML file path (default: tests/samples/fake_statement.xml)')
    parser.add_argument('--output', type=str, default='fake_statement_output.pdf',
                         help='Output PDF file path (default: fake_statement_output.pdf)')
    parser.add_argument('--org-nr', type=str, 
                         help='Override the organization number (must be a 5-digit string)')
    
    args = parser.parse_args()
    
    try:
        # Load the tax statement from XML
        tax_statement = TaxStatement.from_xml_file(args.input)
        
        # Validate org_nr format if provided
        if args.org_nr is not None:
            if not isinstance(args.org_nr, str) or not args.org_nr.isdigit() or len(args.org_nr) != 5:
                print(f"Error: Invalid --org-nr '{args.org_nr}': Must be a 5-digit string.", file=sys.stderr)
                return 1
        
        # Render to PDF
        output_path = render_tax_statement(tax_statement, args.output, override_org_nr=args.org_nr)
        
        print(f"Tax statement successfully rendered to: {output_path}")
        return 0
    except Exception as e:
        print(f"Error rendering tax statement: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
