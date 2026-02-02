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
    BaseDocTemplate, DocAssign
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
import logging

# --- Import TaxStatement model ---
from opensteuerauszug.model.ech0196 import TaxStatement, get_expense_description

# --- Import OneDeeBarCode for barcode rendering ---
from opensteuerauszug.render.onedee import OneDeeBarCode

# --- Import Organisation helper functions ---
from opensteuerauszug.core.organisation import compute_org_nr

# --- Import Security type utilities ---
from opensteuerauszug.core.security import determine_security_type, SecurityType

# --- Import styles utility ---
from opensteuerauszug.util.styles import get_custom_styles
from opensteuerauszug.util import round_accounting
from opensteuerauszug.render.markdown_renderer import markdown_to_platypus

logger = logging.getLogger(__name__)

# --- Configuration ---
DOC_INFO = "TODO: Place some compact info here"

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
        self.is_barcode_page: bool = False
        self.company_name: Optional[str] = None
        self.section_name: str = 'SECTION NAME'
        # Client information for the header box
        self.client_info: Dict[str, str] = {}
        self.summary_table_last_col_width: float = 0.0
        self.tax_statement: Optional[TaxStatement] = None

# --- Helper Function for Currency Formatting ---
def format_currency_rounded(value: Decimal, default='0.00'):
    """Format currency with 0 decimals, for summary table only."""
    if value is None or value == '': return default
    try:
        decimal_value = Decimal(str(value)).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
        formatted = '{:,.0f}'.format(decimal_value).replace(',', "'")
        return formatted
    except: return default

def format_currency_2dp(value: Decimal, default='0.00'):
    """Format currency with 2 decimals, for detail tables."""
    if value is None or value == '': return default
    try:
        decimal_value = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        formatted = '{:,.2f}'.format(decimal_value).replace(',', "'")
        return formatted
    except: return default

# For most values we use 2 decimals, or leave blank it None or zero
def format_currency(value: Optional[Decimal], default=''):
    """Format currency, trimming trailing zeros for better alignment."""
    if value is None or value == Decimal(0):
        return default

    try:
        decimal_value = round_accounting(value)

        two_dec = decimal_value.quantize(Decimal("0.01"))
        three_dec = decimal_value.quantize(Decimal("0.001"))

        if two_dec == three_dec:
            formatted = "{:,.2f}".format(two_dec)
        else:
            formatted = "{:,.3f}".format(three_dec)

        return formatted.replace(',', "'")
    except Exception:
        return default

# For exchange rates we limit to 6 decimals, don't show if 1
def format_exchange_rate(value: Decimal, default=''):
    """Format exchange rate with 6 decimals, for detail tables."""
    if value is None or value == Decimal(1): return default
    try:
        decimal_value = Decimal(str(value)).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
        formatted = '{:,.6f}'.format(decimal_value).replace(',', "'")
        return formatted
    except: return default

# For Stock quantities quantize to a shared template, if argument mutation is true
# then always render a sign in front of the number
def format_stock_quantity(value: Decimal, mutation: bool = False, template: Decimal = Decimal('0.0000'), default=''):
    """Format stock quantity with 4 decimals, if mutation is true, render a sign in front of the number."""
    if value is None or value == Decimal(0): return default
    decimal_value = Decimal(str(value)).quantize(template, rounding=ROUND_HALF_UP)
    if mutation:
        return f"{decimal_value:+,}".replace(',', "'")
    else:
        return f"{decimal_value:,}".replace(',', "'")
    
# Find the minimal number of decimals required to represent the value
def find_minimal_decimals(value: Optional[Decimal]):
    """Find the minimal number of decimals required to represent the value."""
    if value is None or value == Decimal(0): return 0
    exponent = value.normalize().as_tuple().exponent
    if isinstance(exponent, int): return max(0, -exponent)
    return 4

def extract_client_info(tax_statement: TaxStatement) -> Dict[str, str]:
    """Extract client information from tax statement for header display.
    
    Args:
        tax_statement: The TaxStatement model containing client data
        
    Returns:
        Dictionary with formatted client information
    """
    client_info = {}
    
    # Handle multiple clients (joint accounts)
    if tax_statement.client and len(tax_statement.client) > 0:
        client_names = []
        portfolio_numbers = []
        
        for client in tax_statement.client:
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
            
            if name_parts:
                client_names.append(" ".join(name_parts))
            
            # Collect portfolio/client numbers
            if hasattr(client, 'clientNumber'):
                portfolio_numbers.append(str(client.clientNumber))
        
        # Store multiple client names
        if client_names:
            client_info['names'] = client_names  # Changed from 'name' to 'names' (list)
        
        # Store portfolio numbers
        if portfolio_numbers:
            client_info['portfolio'] = ", ".join(portfolio_numbers) if len(portfolio_numbers) > 1 else portfolio_numbers[0]
    
    # Add canton information
    if hasattr(tax_statement, 'canton') and tax_statement.canton:
        client_info['canton'] = tax_statement.canton
    
    # Period information
    period_from = tax_statement.periodFrom.strftime("%d.%m.%Y") if tax_statement.periodFrom else ""
    period_to = tax_statement.periodTo.strftime("%d.%m.%Y") if tax_statement.periodTo else ""
    if period_from and period_to:
        client_info['period'] = f"{period_from} - {period_to}"
    
    # Creation date
    if hasattr(tax_statement, 'creationDate') and tax_statement.creationDate:
        client_info['created'] = tax_statement.creationDate.strftime("%d.%m.%Y")
    
    return client_info

def create_client_info_table(tax_statement: TaxStatement, styles, box_width: float):
    """Create a client information table for header display.
    
    Args:
        tax_statement: The TaxStatement model containing client data
        styles: Dictionary of text styles
        box_width: Width of the client info table
        
    Returns:
        A Table object containing the client information or None if no client data
    """
    client_info = extract_client_info(tax_statement)
    if not client_info:
        return None
    
    # Use smaller font for the info box - removed bold, reduced line spacing
    info_style = ParagraphStyle(
        name='ClientInfoStyle', 
        parent=styles['Normal'], 
        fontSize=8, 
        fontName='Helvetica',  # Changed from Helvetica-Bold
        leading=9,  # Reduced from 10 to save vertical space
        leftIndent=0,
        rightIndent=0
    )
    
    # Prepare table data - removed <b> tags
    table_data = []
    
    # Handle multiple clients - create separate lines for each
    if 'names' in client_info:
        for name in client_info['names']:
            table_data.append([Paragraph(f"Kunde: {name}", info_style)])
    
    if 'portfolio' in client_info:
        table_data.append([Paragraph(f"Portfolio: {client_info['portfolio']}", info_style)])
    
    if 'canton' in client_info:
        table_data.append([Paragraph(f"Kanton: {client_info['canton']}", info_style)])
    
    if 'period' in client_info:
        table_data.append([Paragraph(f"Periode: {client_info['period']}", info_style)])
    
    if 'created' in client_info:
        table_data.append([Paragraph(f"Daten von: {client_info['created']}", info_style)])
    
    if not table_data:
        return None
    
    # Create table with single column
    client_table = Table(table_data, colWidths=[box_width])
    
    # Style the table to look like the info box - reduced padding to save space
    client_table.setStyle(TableStyle([
        # Removed background color
        ('LINEABOVE', (0, 0), (-1, 0), 0.5, colors.black),  # Top border only
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.black),  # Bottom border only
        # Removed left and right borders
        ('LEFTPADDING', (0, 0), (-1, -1), 2*mm),  # Reduced from 3mm
        ('RIGHTPADDING', (0, 0), (-1, -1), 2*mm),  # Reduced from 3mm
        ('TOPPADDING', (0, 0), (-1, -1), 1*mm),   # Reduced from 2mm
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm), # Reduced from 2mm
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    return client_table

# --- Header/Footer Drawing Functions (for SimpleDocTemplate) ---

def draw_page_header(canvas, doc, is_barcode_page: bool = False):
    """Draws the header content on each page, including both regular content pages and barcode pages."""
    canvas.saveState()
    page_width = doc.pagesize[0]
    page_height = doc.pagesize[1]
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(colors.black)
    header_x = page_width - doc.rightMargin
    
    # Draw left header text on all pages
    if hasattr(doc, 'tax_statement') and doc.tax_statement:
        # Get custom styles for header text
        styles = get_custom_styles()
        
        # Institution name in big font
        institution_name = ""
        if hasattr(doc.tax_statement, 'institution') and doc.tax_statement.institution:
            institution_name = doc.tax_statement.institution.name if hasattr(doc.tax_statement.institution, 'name') else ""
        
        if institution_name:
            institution_style = styles['HeaderInstitution']
            canvas.setFont(institution_style.fontName, institution_style.fontSize)
            canvas.drawString(doc.leftMargin, page_height - 15*mm, institution_name)
        
        # "erstellt mit" line
        created_with_style = styles['HeaderCreatedWith']
        canvas.setFont(created_with_style.fontName, created_with_style.fontSize)
        canvas.drawString(doc.leftMargin, page_height - 20*mm, 
                         "erstellt mit OpenSteuerauszug (https://github.com/vroonhof/opensteuerauszug)")
        
        # Tax statement title aligned with bottom of client info box - now big and bold
        period_end_date = doc.tax_statement.periodTo.strftime("%d.%m.%Y") if doc.tax_statement.periodTo else "31.12"
        tax_year = str(doc.tax_statement.taxPeriod) if doc.tax_statement.taxPeriod else ""
        canton = doc.tax_statement.canton if hasattr(doc.tax_statement, 'canton') and doc.tax_statement.canton else "CH"
        
        title_style = styles['HeaderTitle']
        canvas.setFont(title_style.fontName, title_style.fontSize)
        canvas.drawString(doc.leftMargin, page_height - doc.topMargin + 5*mm, 
                         f"Steuerauszug {tax_year} {canton} {period_end_date}")
    
    # Draw client information table on all pages
    if hasattr(doc, 'tax_statement') and doc.tax_statement:
        box_width = getattr(doc, 'summary_table_last_col_width', 60*mm)  # Default fallback
        client_table = create_client_info_table(doc.tax_statement, get_custom_styles(), box_width)
        if client_table:
            # Position the table in the header area
            table_x = page_width - doc.rightMargin - box_width
            table_y = page_height - 15*mm
            
            # Wrap the table to get its dimensions
            table_width, table_height = client_table.wrapOn(canvas, box_width, 50*mm)
            # Draw the table at the calculated position
            client_table.drawOn(canvas, table_x, table_y - table_height)
    
    # Draw the barcode if page specific data is available
    if isinstance(doc, BarcodeDocTemplate) and doc.onedee_generator:
        page_num = canvas.getPageNumber()
        # Barcode page flag is true for the dedicated barcode pages at the end
        barcode_widget = doc.onedee_generator.generate_barcode(
            page_number=page_num, 
            is_barcode_page=is_barcode_page,
            org_nr=doc.org_nr
        )
        if barcode_widget:
            doc.onedee_generator.draw_barcode_on_canvas(canvas, barcode_widget, doc.pagesize)
    
    canvas.restoreState()

def draw_page_header_barcode(canvas, doc):
    """Draws the header and barcode on the barcode pages."""
    draw_page_header(canvas, doc, is_barcode_page=True)

def draw_page_footer(canvas, doc):
    """Draws the footer content and page number on each page."""
    canvas.saveState()
    page_width = doc.pagesize[0]
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(colors.grey)
    footer_y = doc.bottomMargin - 10*mm # Adjust position
    # Company Name
    if doc.company_name:
        canvas.drawString(doc.leftMargin, footer_y, f"{doc.company_name} convertiert mit OpenSteuerauszug")
    # Doc Info
    # canvas.drawCentredString(page_width / 2.0, footer_y, DOC_INFO)
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

    steuerwert_a = format_currency_rounded(summary_data.get('steuerwert_a'))
    steuerwert_b = format_currency_rounded(summary_data.get('steuerwert_b'))
    # Footnote
    footnote_text = "(1) Davon A {} und B {}".format(
        format_currency_rounded(summary_data.get('steuerwert_a', '')),
        format_currency_rounded(summary_data.get('steuerwert_b', ''))
    )

    # --- Data structure based on 6 columns, with Totals shifted ---
    table_data = [
        # Row 0: A/B Headers (Indices 2 & 5 blank)
        [Paragraph(f'Steuerwert der A- und B-Werte am {summary_data.get("period_end_date", "31.12")}', header_style),
         '',         
         Paragraph('A', val_center), # 'A' in its own column (index 2)
         Paragraph(f'Bruttoertrag {summary_data.get("tax_period", "")} Werte mit VSt.-Abzug', header_style),
         Paragraph('B', val_center), # 'B' in its own column (index 2)
         Paragraph(f'Bruttoertrag {summary_data.get("tax_period", "")} Werte ohne VSt.-Abzug', header_style),
         Paragraph('Verrechnungs- steueranspruch', header_style),
         Paragraph('Gebühren', header_style),
         Paragraph(f'''Werte für Formular "Wertschriften- und Guthabenverzeichnis"
(inkl. Konti, ohne Werte DA-1 und USA)''', val_left)],
        # Row 1: A/B Values (Index 2 is 'B', Index 5 blank)
        [Paragraph(format_currency_rounded(summary_data.get('steuerwert_ab')), val_right),
         Paragraph("(1)", val_left),
         '',
         Paragraph(format_currency_rounded(summary_data.get('brutto_mit_vst')), val_right),
         '',
         Paragraph(format_currency_rounded(summary_data.get('brutto_ohne_vst')), val_right),
         Paragraph(format_currency_2dp(summary_data.get('vst_anspruch')), val_right),
         Paragraph(format_currency_2dp(summary_data.get('total_gebuehren')), val_right),
         Paragraph(footnote_text, val_left)],
        # Row 2: Spacer row (6 columns)
        ['', '', '', '', '', ''],
         # Row 3: DA-1 Headers (Indices 1 & 2 blank)
        [Paragraph(f'Steuerwert der DA-1 und USA- Werte am {summary_data.get("period_end_date", "31.12")}', header_style),
         '', '', '', '',
         Paragraph(f'Bruttoertrag {summary_data.get("tax_period", "")} DA-1 und USA-Werte', header_style), # Starts in Col 4
         Paragraph('Pauschale Steueranrechnung (DA-1)', header_style), 
         Paragraph('Steuerrückbehalt USA', header_style),
         Paragraph('''Werte für zusätzliches Formular "DA-1 Antrag auf Anrechnung
ausländischer Quellensteuer und zusätzlichen Steuerrückbehalt
USA"''', val_left)], #
         # Row 4: DA-1 Values (Indices 1 & 2 blank)
        [Paragraph(format_currency_rounded(summary_data.get('steuerwert_da1_usa')), val_right),
         '', '', '', '',
         Paragraph(format_currency_rounded(summary_data.get('brutto_da1_usa')), val_right), # Starts in Col 3
         Paragraph(format_currency_rounded(summary_data.get('pauschale_da1')), val_right), # Col 4
         Paragraph(format_currency_rounded(summary_data.get('rueckbehalt_usa')), val_right),
         '',
], # Col 5
        # Row 5: Spacer row (6 columns)
        ['', '', '', '', '', ''],
        # Row 6: Total Headers (** SHIFTED RIGHT **, Indices 1, 2, 5 blank)
        [Paragraph('Total Steuerwert der A,B,DA-1 und USA-Werte', header_style), # Col 0
         '',
         '', 
         Paragraph(f'Total Bruttoertrag {summary_data.get("tax_period", "")} A-Werte mit VSt.-Abzug', header_style), # Col 3 << SHIFTED
         '', 
         Paragraph(f'Total Bruttoertrag {summary_data.get("tax_period", "")} B,DA-1 und USA-Werte ohne VSt.-Abzug', header_style), # Col 4 << SHIFTED
         Paragraph(f'Total Bruttoertrag {summary_data.get("tax_period", "")} A.B.DA-1 und USA-Werte', header_style),
         "",
                  Paragraph('''Falls keine Anrechnung ausländischer Quellensteuern (DA-1)
geltend gemacht wird, sind diese Totalwerte im
Wertschriftenverzeichnis einzusetzen.''', val_left)], # Col 5 << SHIFTED
         # Row 7: Total Values (** SHIFTED RIGHT **, Indices 1, 2, 5 blank)
        [Paragraph(format_currency_rounded(summary_data.get('total_steuerwert')), val_right), # Col 0
         '',
         '', 
         Paragraph(format_currency_rounded(summary_data.get('total_brutto_mit_vst')), val_right), # Col 3 << SHIFTED
         '', 
         Paragraph(format_currency_rounded(summary_data.get('total_brutto_ohne_vst')), val_right),# Col 4 << SHIFTED
         Paragraph(format_currency_rounded(summary_data.get('total_brutto_gesamt')), val_right)],   # Col 5 << SHIFTED
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
                  2*base_col_width, # Col 8: Description / Instructions
                  ] 

    row_heights = [15*mm, 6*mm, 2*mm, 15*mm, 6*mm, 2*mm, 20*mm, 6*mm]
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
    no_line_style = (0, colors.black) # Or use (0.5, colors.white) if background isn't white

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
        # First row of values
        ('LINEABOVE', (0, 1), (0, 1), *line_style),
        ('LINEBELOW', (0, 1), (0, 1), *line_style),
        ('LINEABOVE', (2, 1), (3, 1), *line_style),
        ('LINEBELOW', (2, 1), (3, 1), *line_style),
        ('LINEABOVE', (5, 1), (6, 1), *line_style),
        ('LINEBELOW', (5, 1), (6, 1), *line_style),
        ('LINEABOVE', (7, 1), (7, 1), *line_style),
        ('LINEBELOW', (7, 1), (7, 1), *line_style),
        # 2nd row of values
        ('LINEABOVE', (0, 4), (0, 4), *line_style),
        ('LINEBELOW', (0, 4), (0, 4), *line_style),
        # No A values for DA-1
        ('LINEABOVE', (5, 4), (6, 4), *line_style),
        ('LINEBELOW', (5, 4), (6, 4), *line_style),
        ('LINEABOVE', (7, 4), (7, 4), *line_style),
        ('LINEBELOW', (7, 4), (7, 4), *line_style),
        # Totals
        ('LINEABOVE', (0, 7), (0, 7), *line_style),
        ('LINEBELOW', (0, 7), (0, 7), *line_style),
        ('LINEABOVE', (2, 7), (3, 7), *line_style),
        ('LINEBELOW', (2, 7), (3, 7), *line_style),
        ('LINEABOVE', (5, 7), (6, 7), *line_style),
        ('LINEBELOW', (5, 7), (6, 7), *line_style),
    ]

    # --- Combine all styles ---
    style_commands = [
        common_valign,
        *common_padding,
        *spacer_row_2_style,
        *spacer_row_5_style,
        *line_commands,
        ('BACKGROUND', (0, 0), (-1, 5), colors.HexColor('#e0e0e0')),

        # ('GRID', (0,0), (-1,-1), 0.2, colors.lightgrey) # Debug grid
    ]

    # --- Apply the combined style ---
    summary_table.setStyle(TableStyle(style_commands))

    return KeepTogether([summary_table, Spacer(1, 2*mm)])

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
    period_end_date = data.get('summary', {}).get('period_end_date', '31.12')
    tax_period = data.get('summary', {}).get('tax_period', '')
    table_data = [ [Paragraph('Datum', header_style), Paragraph('Bezeichnung<br/>Schulden<br/>Zinsen', header_style), Paragraph('Währung', header_style), Paragraph('Schulden', header_style), Paragraph('Kurs', header_style), Paragraph(f'Schulden<br/>{period_end_date}<br/>in CHF', header_style), Paragraph(f'Schuldzinsen<br/>{tax_period}<br/>in CHF', header_style)] ]
    total_debt = Decimal(0); total_interest = Decimal(0)
    for item in data['liabilities']:
        if 'transactions' in item:
            for trans in item['transactions']:
                table_data.append([
                    Paragraph(trans.get('date', ''), val_left),
                    Paragraph(trans.get('description', ''), val_left),
                    Paragraph(item.get('currency', 'CHF'), val_center),
                    Paragraph(format_currency_2dp(trans.get('amount')), val_right),
                    Paragraph('', val_right),
                    Paragraph('', val_right),
                    Paragraph(format_currency_2dp(trans.get('amount')), val_right)
                ])
        table_data.append([
            Paragraph(item.get('date', period_end_date), val_left),
            Paragraph(item.get('description', '').replace('\n', '<br/>'), val_left),
            Paragraph(item.get('currency', 'CHF'), val_center),
            Paragraph(format_currency_2dp(item.get('amount')), val_right),
            Paragraph(item.get('rate', ''), val_right),
            Paragraph(format_currency_2dp(item.get('value_chf')), val_right),
            Paragraph(format_currency_2dp(item.get('total_interest')), val_right)
        ])
        total_debt += Decimal(str(item.get('value_chf', 0))); total_interest += Decimal(str(item.get('total_interest', 0)))
    table_data.append([
        Paragraph('', val_left),
        Paragraph('Total Schulden', bold_left),
        Paragraph('', val_left),
        Paragraph('', val_right),
        Paragraph('', val_right),
        Paragraph(format_currency_2dp(total_debt), bold_right),
        Paragraph(format_currency_2dp(total_interest), bold_right)
    ])
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
    period_end_date = data.get('summary', {}).get('period_end_date', '31.12')
    table_data = [ [Paragraph('Bezeichnung', header_left_style), Paragraph('Spesentyp', header_left_style), Paragraph(f'Wert<br/>{period_end_date}<br/>in CHF', header_right_style)] ]
    total_costs = Decimal(0)
    for item in data['costs']: table_data.append([ Paragraph(item.get('description', ''), val_left), Paragraph(item.get('type', ''), val_left), Paragraph(format_currency_2dp(item.get('value_chf')), val_right) ]); total_costs += Decimal(str(item.get('value_chf', 0)))
    table_data.append([ Paragraph('Total bezahlte Bankspesen', bold_left), Paragraph('', val_left), Paragraph(format_currency_2dp(total_costs), bold_right) ])
    col_widths = [110*mm, 97*mm, 50*mm]
    costs_table = Table(table_data, colWidths=col_widths)
    costs_table.setStyle(TableStyle([ ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 1), ('RIGHTPADDING', (0, 0), (-1, -1), 1), ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1), ('LINEBELOW', (0, 0), (-1, 0), 1, colors.black), ('BOTTOMPADDING', (0, 0), (-1, 0), 3*mm), ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black), ('TOPPADDING', (0, -1), (-1, -1), 3*mm), ]))
    footnote_text = '(2) Über die Abzugsfähigkeit der Spesen entscheidet die zuständige Veranlagungsbehörde.'
    return KeepTogether([costs_table, Spacer(1, 2*mm), Paragraph(footnote_text, val_left)])


# --- Info Box Helpers ---
def create_minimal_placeholder(styles):
    """Create a placeholder paragraph for minimal tax statements."""
    text = (
        "Dies ist kein echter Steuerauszug. Dieses Minimaldokument dient nur dazu, "
        "die Bankdaten über Barcodes zu importieren. Das die Totale nicht ermittelt werden wird auf eine Zusammenfassung verzichtet."
    )
    return Paragraph(text, styles['Normal'])


def create_dual_info_boxes(styles, usable_width, minimal: bool = False):
    """Create two side-by-side information boxes for the first page."""
    templates_path = Path(__file__).parent / 'templates'

    if minimal:
        left_file = 'tax_office_minimal.de.md'
        right_file = 'tax_payer_minimal.en.md'
    else:
        left_file = 'tax_office.de.md'
        right_file = 'tax_payer.en.md'

    with open(templates_path / left_file, 'r', encoding='utf-8') as f:
        left_markdown = f.read()

    with open(templates_path / right_file, 'r', encoding='utf-8') as f:
        right_markdown = f.read()

    left_flowables = markdown_to_platypus(left_markdown, styles=styles, section='short-version')
    right_flowables = markdown_to_platypus(right_markdown, styles=styles, section='short-version')

    table = Table(
        [[left_flowables, right_flowables]],
        colWidths=[usable_width / 2, usable_width / 2],
    )
    table.setStyle(
        TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOX', (0, 0), (0, 0), 0.5, colors.black),
            ('BOX', (1, 0), (1, 0), 0.5, colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ])
    )
    return table


def create_single_info_page(markdown_text, styles, section=None):
    """Create simple text content for a dedicated information page."""
    return markdown_to_platypus(markdown_text, section=section)



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
    
    # Period information with safe date handling
    period_from = tax_statement.periodFrom.strftime("%d.%m.%Y") if tax_statement.periodFrom else ""
    period_to = tax_statement.periodTo.strftime("%d.%m.%Y") if tax_statement.periodTo else ""
    
    # Period text with mandatory fields
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
    from pdf417gen import encode_macro, render_image # Changed back to encode_macro
    
    # Use the real XML data for proper macro PDF417 generation
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

    # Use encode_macro for proper macro PDF417 generation
    codes = encode_macro(
        data,
        file_id=[1],
        columns=NUM_COLUMNS,
        force_rows=NUM_ROWS,
        security_level=4,
        segment_size=SEGMENT_SIZE,
        force_binary=True,
    )
    
    # encode_macro returns a list of barcodes (for multi-segment data)
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
        
    
    # Get styles
    styles = get_custom_styles()
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
        story.append(PageBreak('barcode'))

        story.append(DocAssign("section_name", f"'Barcode Seite {page_num + 1} von {barcode_pages}'"))
        story.append(Paragraph(f"Barcode Seite {page_num + 1} von {barcode_pages}", title_style))
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
  
def create_bank_accounts_table(tax_statement, styles, usable_width):
    """Creates a table displaying bank accounts information as per user specification."""
    if not tax_statement.listOfBankAccounts or not tax_statement.listOfBankAccounts.bankAccount:
        return None
    bank_accounts = tax_statement.listOfBankAccounts.bankAccount
    period_end_date = tax_statement.periodTo.strftime("%d.%m.%Y") if tax_statement.periodTo else "31.12"
    year = str(tax_statement.taxPeriod) if tax_statement.taxPeriod else ""

    header_style = styles['Header_RIGHT']
    header_left = styles['Header_LEFT']
    val_left = styles['Val_LEFT']
    val_right = styles['Val_RIGHT']
    val_center = styles['Val_CENTER']
    bold_left = styles['Bold_LEFT']
    bold_right = styles['Bold_RIGHT']

    # Table header as specified
    table_data = [
        [
            Paragraph('Datum', header_left),
            Paragraph('Bezeichnung<br/>Bankkonto<br/>Zinsen', header_left),
            Paragraph('Währung', header_style),
            Paragraph(f'Steuerwert/Ertag<br/>{period_end_date}<br/>in CHF', header_style),
            Paragraph('Kurs', header_style),
            Paragraph('<strong>Steuerwert</strong>', header_style),
            '',
            Paragraph('<strong>A</strong>', header_style),
            Paragraph(f'<strong>Bruttoertrag</strong><br/>{year}<br/>mit VSt.', header_style),
            '',
            Paragraph('<strong>B</strong>', header_style),
            Paragraph(f'<strong>Bruttoertrag</strong><br/>{year}<br/>ohne VSt.', header_style),
        ]
    ]

    intermediate_total_rows = []
    current_row = 1  # Start after header

    for account in bank_accounts:
        table_data.append([
            '',
            Paragraph(f"<strong>{account.bankAccountName}</strong><br/> {account.iban or account.bankAccountNumber or ''}", val_left),
            '',
            '',
            '',
            '',
            '', '', '', '', '', '',
        ])
        current_row += 1
        # Payment rows
        for payment in account.payment:
            table_data.append([
                Paragraph(payment.paymentDate.strftime("%d.%m.%Y"), val_left) if payment.paymentDate else Paragraph('', val_left),
                Paragraph(payment.name or '', val_left),
                Paragraph(payment.amountCurrency or account.bankAccountCurrency or '', val_center),
                Paragraph(format_currency_2dp(payment.amount), val_right),
                Paragraph(format_exchange_rate(payment.exchangeRate), val_right),
                '', 
                '',
                '',
                Paragraph(format_currency(payment.grossRevenueA), val_right),
                '',
                '',
                Paragraph(format_currency(payment.grossRevenueB), val_right),
            ])
            current_row += 1
        if account.closingDate:
            date_str = account.closingDate.strftime("%d.%m.%Y")
        elif ( account.taxValue and account.taxValue.referenceDate):
            date_str = account.taxValue.referenceDate.strftime("%d.%m.%Y")
        else:
            date_str = ""
        if account.taxValue:
            balance_str = format_currency_2dp(account.taxValue.balance)
            exchange_rate_str = format_exchange_rate(account.taxValue.exchangeRate)
            currency_str = account.taxValue.balanceCurrency or account.bankAccountCurrency or ''
        else:
            balance_str = ''
            exchange_rate_str = ''
            currency_str = ''
        table_data.append([
            Paragraph(date_str, val_left),
            Paragraph('Auflösung / Ertrag' if account.closingDate else 'Steuerwert / Ertrag', bold_left),
            Paragraph(currency_str, val_center),
            Paragraph(balance_str, val_right),
            Paragraph(exchange_rate_str, val_right),
            Paragraph(format_currency_2dp(account.totalTaxValue), bold_right),
            '', '', Paragraph(format_currency(account.totalGrossRevenueA), bold_right),
            '', '', Paragraph(format_currency(account.totalGrossRevenueB), bold_right),
        ])
        intermediate_total_rows.append(current_row)
        current_row += 1
        # Seperator row after each account
        table_data.append([])
        current_row += 1

    # add a final with totals for the list of bank accounts
    table_data.append([
        "",
        Paragraph("Total Bankkonten ", val_left),
        '',
        '',
        '',
        Paragraph(format_currency_2dp(tax_statement.listOfBankAccounts.totalTaxValue), bold_right),
        '', '', Paragraph(format_currency(tax_statement.listOfBankAccounts.totalGrossRevenueA), bold_right),
        '', '', Paragraph(format_currency(tax_statement.listOfBankAccounts.totalGrossRevenueB), bold_right),
    ])

    # Column widths (adjust as needed for layout)
    col_widths = [20*mm, 65*mm, 18*mm, 28*mm, 18*mm, 28*mm, 5*mm, 8, 23*mm, 5*mm,  8 , 23*mm]
    bank_table = Table(table_data, colWidths=col_widths)
    # --- Table style for header and intermediate totals ---
    table_style = [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        # First content row
        ('TOPPADDING', (0, 1), (-1, 1), 3*mm),
        # Last content row
        # For now handled by the extra seperator row
        # ('BOTTOMPADDING', (0, -2), (-1, -2), 3*mm),
        # Header row background (light grey)
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
        # Finla totals 
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e0e0e0')),
    ]
    # Add even lighter grey background to each intermediate total row (after each account)
    for idx in intermediate_total_rows:
        table_style.append(('BACKGROUND', (0, idx), (-1, idx), colors.HexColor('#f5f5f5')))
    bank_table.setStyle(TableStyle(table_style))
    return bank_table

# --- Securities/Depots Table Function ---
def create_securities_table(tax_statement, styles, usable_width, security_type: SecurityType):
    """
    Creates a table displaying securities information filtered by security type.
    
    Args:
        tax_statement: The tax statement containing securities data
        styles: Dictionary of text styles
        usable_width: Available width for the table
        security_type: Type of securities to include ("A", "B", or "DA1")
        
    Returns:
        A Table object with the filtered securities or None if no matching securities
    """
    if not tax_statement.listOfSecurities or not tax_statement.listOfSecurities.depot:
        return None
    depots = tax_statement.listOfSecurities.depot
    period_end_date = tax_statement.periodTo.strftime("%d.%m.%Y") if tax_statement.periodTo else "31.12.2024"
    year = str(tax_statement.taxPeriod) if tax_statement.taxPeriod else "2024"

    header_style = styles['Header_RIGHT']
    header_left = styles['Header_LEFT']
    val_left = styles['Val_LEFT']
    val_right = styles['Val_RIGHT']
    val_center = styles['Val_CENTER']
    bold_left = styles['Bold_LEFT']
    bold_right = styles['Bold_RIGHT']

    # Table header with security type in the title
    type_label = {"A": "mit VSt.-Abzug", "B": "ohne VSt.-Abzug", "DA1": "DA-1 und USA-Werte"}
    
    table_header = [
        Paragraph('Valoren-Nr<br/>Datum', header_left),
        Paragraph('Depot-Nr<br/>Bezeichnung<br/>ISIN', header_left),
        Paragraph('Anzahl<br/>Nominal', header_style),
        Paragraph('Währung<br/>Land', header_style),
        Paragraph('Stückpreis<br/>Ertrag', header_style),
        Paragraph('ExDatum', header_style),
        Paragraph('Kurs', header_style),
        Paragraph(f'Steuerwert {period_end_date}<br/>in CHF', header_style),
        Paragraph('A', header_style),
        Paragraph(f'Bruttoertrag {year}<br/>mit VSt.in CHF', header_style),
        Paragraph('B', header_style),
        Paragraph(f'Bruttoertrag {year}<br/>ohne VSt.in CHF', header_style),
        Paragraph('Anrechenbare ausl. Quellensteuer<br/> in CHF', header_style),
        Paragraph('Steuerrückbehalt USA<br/> in CHF', header_style),
    ]
    
    col_widths = [18*mm, 50*mm, 20*mm, 18*mm, 18*mm, 14*mm, 18*mm, 22*mm, 8, 22*mm, 8, 22*mm, 25*mm, 25*mm]
    col_widths = [1.0*w for w in col_widths]
    assert len(col_widths) == len(table_header)
    # Hide columns not used in this table
    hidden_columns = []
    if security_type != "DA1":
        col_widths[-1] = 0
        col_widths[-2] = 0
        hidden_columns.extend([len(col_widths) - 1, len(col_widths) - 2])
    else:
        col_widths[-4] = 0 # A
        col_widths[-5] = 0  # Ertrag mit VSt.
        col_widths[-6] = 0  # B
        hidden_columns.extend([len(col_widths) - 4, len(col_widths) - 5, len(col_widths) - 6])
    assert sum(col_widths) < usable_width
    
    # Collect securities of the specified type
    filtered_securities = []
    for depot in depots:
        for security in depot.security:
            if determine_security_type(security) == security_type:
                filtered_securities.append((depot, security))
    
    # Return None if no matching securities
    if not filtered_securities:
        return None

    table_data = []
    intermediate_total_rows = []
    current_row = 1  # Start after header

    
    for depot, security in filtered_securities:
        # Description/header row for the security
        if security.country != "CH" and security.country != None:
            cur_country = f"{security.currency or ''}<br/>{security.country}"
        else:
            cur_country = security.currency
        table_data.append([
            Paragraph(f"{security.valorNumber or ''}", bold_left),
            Paragraph(f"<strong>{security.securityName or ''}</strong><br/>{security.isin or ''}", val_left),
            Paragraph('', val_right),
            Paragraph(cur_country, val_right),
            Paragraph('', val_right),
            Paragraph('', val_right),
            Paragraph('', val_left),
            Paragraph('', val_right),
            Paragraph('', val_right),
            Paragraph('', val_right),
            Paragraph('', val_right),
            Paragraph('', val_right),
        ])
        current_row += 1
        # Collect all payments and stock entries, sort by date
        entries = []
        precision = find_minimal_decimals(security.nominalValue)
        if getattr(security, 'payment', None):
            for payment in security.payment:
                entries.append(('payment', payment.paymentDate, payment))
                precision = max(precision, find_minimal_decimals(payment.quantity))
        if getattr(security, 'stock', None):
            for stock in security.stock:
                entries.append(('stock', stock.referenceDate, stock))
                precision = max(precision, find_minimal_decimals(stock.quantity))
        if precision > 0:
            stock_quantity_template = Decimal('0.' + '0' * precision)
        else:
            stock_quantity_template = Decimal('0')
        entries.sort(key=lambda x: x[1] or '')
        
        # Render each entry
        for entry_type, entry_date, entry in entries:
            if entry_type == 'payment':
                name = entry.name or ''
                if entry.sign:
                    name = f"{name} {entry.sign}"
                table_data.append([
                    Paragraph(entry.paymentDate.strftime("%d.%m.%Y") if entry.paymentDate else '', val_left),
                    Paragraph(name, val_left),
                    Paragraph(format_stock_quantity(entry.quantity, False, stock_quantity_template), val_right),
                    Paragraph(entry.amountCurrency or '', val_right),
                    Paragraph(format_currency(entry.amount) if getattr(entry, 'amount', None) else '', val_right),
                    Paragraph(entry.exDate.strftime("%d.%m") if getattr(entry, 'exDate', None) else '', val_right),
                    Paragraph(format_exchange_rate(entry.exchangeRate) if getattr(entry, 'exchangeRate', None) else '', val_right),
                    Paragraph('', val_right),
                    '',
                    Paragraph(format_currency_2dp(entry.grossRevenueA) if getattr(entry, 'grossRevenueA', None) else '', val_right),
                    '',
                    Paragraph(format_currency_2dp(entry.grossRevenueB) if getattr(entry, 'grossRevenueB', None) else '', val_right),
                    Paragraph(format_currency_2dp(entry.nonRecoverableTaxAmount), val_right),
                    Paragraph(format_currency_2dp(entry.additionalWithHoldingTaxUSA), val_right),
                ])
            elif entry_type == 'stock':
                if entry.quotationType != 'PIECE':
                    raise NotImplementedError("Cannot render stock type")
                if entry.mutation:
                    name = entry.name
                else:
                    name = "Bestand"
                table_data.append([
                    Paragraph(entry.referenceDate.strftime("%d.%m.%Y") if entry.referenceDate else '', val_left),
                    Paragraph(name, val_left),
                    Paragraph(format_stock_quantity(entry.quantity, entry.mutation, stock_quantity_template), val_right),
                    Paragraph(entry.balanceCurrency if entry.unitPrice else '', val_right),
                    # TODO: What should the resolution of unit price be? UK stocks can have fractions of a penny
                    Paragraph(format_currency(entry.unitPrice) if getattr(entry, 'unitPrice', None) else '', val_right),
                    Paragraph('', val_left),
                    Paragraph(format_exchange_rate(entry.exchangeRate) if getattr(entry, 'exchangeRate', None) else '', val_right),
                    Paragraph(format_currency_2dp(entry.value) if getattr(entry, 'value', None) else '', val_right),
                    Paragraph('', val_right),
                    Paragraph('', val_right),
                    Paragraph('', val_right),
                    Paragraph('', val_right),
                    '',
                    ''
                ])
            current_row += 1
            
        # Subtotal row for the security
        tax_value = security.taxValue
        if tax_value and tax_value.referenceDate:
            date_str = tax_value.referenceDate.strftime("%d.%m.%Y")
        else:
            date_str = ""
        table_data.append([
            Paragraph(date_str, bold_left),
            Paragraph('Bestand / Steuerwert / Ertrag', bold_left),
            Paragraph(format_stock_quantity(tax_value.quantity, False, stock_quantity_template) if tax_value else '', val_right),
            Paragraph(tax_value.balanceCurrency or '' if tax_value else '', val_right),
            Paragraph(format_currency(tax_value.unitPrice) if tax_value and getattr(tax_value, 'unitPrice', None) else '', val_right),
            Paragraph('', val_left),
            Paragraph('', val_right),
            Paragraph(format_currency_2dp(tax_value.value) if tax_value and getattr(tax_value, 'value', None) else '', bold_right),
            '',
            Paragraph(format_currency(security.totalGrossRevenueA), bold_right),
            '',
            Paragraph(format_currency(security.totalGrossRevenueB), bold_right),
            Paragraph(format_currency(security.totalNonRecoverableTax), val_right),
            Paragraph(format_currency(security.totalAdditionalWithHoldingTaxUSA), val_right),
        ])
        intermediate_total_rows.append(current_row)
        current_row += 1
        # Separator row
        table_data.append([Paragraph('')]*len(table_header))
        current_row += 1

    # TOOD read pre-submmed totals from the model
    if security_type == "A":
        total_tax_value = tax_statement.svTaxValueA
        total_gross_revenueA = tax_statement.svGrossRevenueA
        total_gross_revenueB = None
    elif security_type == "B":
        total_tax_value = tax_statement.svTaxValueB
        total_gross_revenueA = None
        total_gross_revenueB = tax_statement.svGrossRevenueB
    elif security_type == "DA1":
        total_tax_value = tax_statement.da1TaxValue
        total_gross_revenueA = None
        total_gross_revenueB = tax_statement.da_GrossRevenue
    # Add a total row
    table_data.append([
        Paragraph('', val_left),
        Paragraph(f'Total {security_type}-Werte', bold_left),
        Paragraph('', val_right),
        Paragraph('', val_center),
        Paragraph('', val_right),
        Paragraph('', val_left),
        Paragraph('', val_right),
        Paragraph(format_currency_2dp(total_tax_value), bold_right),
        '',
        Paragraph(format_currency(total_gross_revenueA), bold_right),
        '',
        Paragraph(format_currency(total_gross_revenueB), bold_right),
        Paragraph(format_currency(tax_statement.listOfSecurities.totalNonRecoverableTax), bold_right),
        Paragraph(format_currency(tax_statement.listOfSecurities.totalAdditionalWithHoldingTaxUSA), bold_right),
    ])
    intermediate_total_rows.append(current_row)
    current_row += 1

    # Table style
    table_style = [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, -2), (-1, -2), 3*mm),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
    ]
    # Set padding to 0 for hidden columns to avoid negative availWidth
    for col in hidden_columns:
        table_style.append(('LEFTPADDING', (col, 0), (col, -1), 0))
        table_style.append(('RIGHTPADDING', (col, 0), (col, -1), 0))
        table_style.append(('TOPPADDING', (col, 0), (col, -1), 0))
        table_style.append(('BOTTOMPADDING', (col, 0), (col, -1), 0))
    for idx in intermediate_total_rows:
        table_style.append(('BACKGROUND', (0, idx), (-1, idx), colors.HexColor('#f5f5f5')))
    securities_table = Table([table_header] + table_data, colWidths=col_widths, repeatRows=1, splitByRow=1)
    securities_table.setStyle(TableStyle(table_style))
    return securities_table

# --- Main API function to be called from steuerauszug.py ---
def render_tax_statement(
    tax_statement: TaxStatement,
    output_path: Union[str, Path],
    override_org_nr: Optional[str] = None,
    minimal_frontpage_placeholder: bool = False,
) -> Path:
    """Render a tax statement to PDF.
    
    Args:
        tax_statement: The TaxStatement model to render
        output_path: Path where to save the generated PDF
        override_org_nr: Optional override for organization number (5 digits)
        minimal_frontpage_placeholder: If True, replace the summary on the first
            page with a placeholder suitable for minimal tax statements
        
    Returns:
        Path to the generated PDF file
    """
    # Convert to string path if it's a Path object
    output_path = str(output_path) if isinstance(output_path, Path) else output_path
    
    buffer = io.BytesIO()
    page_width, page_height = landscape(A4)
    left_margin = 20*mm # This leaves enough space for the barcode
    right_margin = 20*mm
    top_margin = 40*mm  # Increased from 45*mm to accommodate header text + client info box height + buffer
    bottom_margin = 15*mm
    usable_width = page_width - left_margin - right_margin

    # Define frame for the main content area
    frame = Frame(left_margin, bottom_margin, usable_width, page_height - top_margin - bottom_margin,
                  id='normal')

    # Create the page template with header/footer functions
    main_page_template = PageTemplate(id='main', frames=[frame],
                                 onPage=draw_page_header, 
                                 onPageEnd=draw_page_footer)
    barcode_page_template = PageTemplate(id='barcode', frames=[frame],
                                 onPage=draw_page_header_barcode, 
                                 onPageEnd=draw_page_footer)

    # Use BarcodeDocTemplate for barcode support
    doc = BarcodeDocTemplate(buffer,
                             pagesize=landscape(A4),
                             pageTemplates=[main_page_template, barcode_page_template],
                             leftMargin=left_margin,
                             rightMargin=right_margin,
                             topMargin=top_margin,
                             bottomMargin=bottom_margin)
    
    # Set up barcode generator
    doc.onedee_generator = OneDeeBarCode()
    
    # Compute the organization number
    doc.org_nr = compute_org_nr(tax_statement, override_org_nr)
    doc.company_name = tax_statement.institution.name if tax_statement.institution else ""

    # Store tax statement for header access
    doc.tax_statement = tax_statement

    # Set the PDF title using institution name and tax year
    company_name = tax_statement.institution.name if tax_statement.institution else ""
    tax_year = str(tax_statement.taxPeriod) if tax_statement.taxPeriod else ""
    title_parts = ["Steuerauszug", company_name, tax_year]
    doc.title = " ".join(part for part in title_parts if part)
    
    # Extract and store client information for header display (backward compatibility)
    doc.client_info = extract_client_info(tax_statement)
    
    # Calculate the summary table's last column width to match the client info box
    # From create_summary_table: 2*base_col_width for column 8 (the instructions column)
    usable_table_width = usable_width - 2.5*8 - 8 - 16  # Adjustments from create_summary_table
    base_col_width = usable_table_width / 7
    doc.summary_table_last_col_width = 2 * base_col_width  # Column 8 width
    
    # --- Define styles centrally (same as before) ---
    styles = get_custom_styles()


    
    story = []

    # --- Sections ---
    title_style = ParagraphStyle(name='SectionTitle', parent=styles['h2'], alignment=TA_LEFT, fontSize=10, spaceAfter=4*mm)
    # Would love to use this, but following text then overlaps.
    # title_style = styles['HeaderTitle']

    use_minimal_frontpage = minimal_frontpage_placeholder

    # 1. Summary Section or placeholder
    story.append(Paragraph("Steuerauszug | Zusammenfassung", title_style))

    if use_minimal_frontpage:
        story.append(create_minimal_placeholder(styles))
        story.append(Spacer(1, 0.5*cm))
        story.append(create_dual_info_boxes(styles, usable_width, minimal=True))
    else:
        # Extract tax period and period end date - both are mandatory in the model
        tax_period = str(tax_statement.taxPeriod)

        # Format period end date - periodTo is mandatory in the model
        if tax_statement.periodTo:
            period_end_date = tax_statement.periodTo.strftime("%d.%m.%Y")
        else:
            raise ValueError("PeriodTo is mandatory in the model")

        # Calculate total gross revenue if not already set
        if tax_statement.total_brutto_gesamt is None:
            total_gross_revenue_a = tax_statement.totalGrossRevenueA or Decimal('0')
            total_gross_revenue_b = tax_statement.totalGrossRevenueB or Decimal('0')
            tax_statement.total_brutto_gesamt = total_gross_revenue_a + total_gross_revenue_b

        # Ensure the model fields are populated
        if tax_statement.svGrossRevenueA is None:
            tax_statement.svGrossRevenueA = tax_statement.totalGrossRevenueA or Decimal('0')

        if tax_statement.svGrossRevenueB is None:
            tax_statement.svGrossRevenueB = tax_statement.totalGrossRevenueB or Decimal('0')

        # Create summary data dictionary from model fields
        summary_data = {
            "steuerwert_ab": ((tax_statement.svTaxValueA or Decimal('0'))
                              + (tax_statement.svTaxValueB or Decimal('0'))),
            "steuerwert_a": tax_statement.svTaxValueA or Decimal('0'),
            "steuerwert_b": tax_statement.svTaxValueB or Decimal('0'),
            "brutto_mit_vst": tax_statement.svGrossRevenueA,
            "brutto_ohne_vst": tax_statement.svGrossRevenueB,
            "vst_anspruch": tax_statement.totalWithHoldingTaxClaim,
            "steuerwert_da1_usa": tax_statement.da1TaxValue,
            "brutto_da1_usa": tax_statement.da_GrossRevenue,
            "pauschale_da1": tax_statement.listOfSecurities.totalNonRecoverableTax if tax_statement.listOfSecurities else Decimal('0'),
            "rueckbehalt_usa": tax_statement.listOfSecurities.totalAdditionalWithHoldingTaxUSA if tax_statement.listOfSecurities else Decimal('0'),
            "total_steuerwert": tax_statement.totalTaxValue,
            "total_gebuehren": tax_statement.listOfExpenses.totalExpenses if tax_statement.listOfExpenses else Decimal('0'),
            "total_brutto_mit_vst": tax_statement.totalGrossRevenueA,
            "total_brutto_ohne_vst": tax_statement.totalGrossRevenueB,
            "total_brutto_gesamt": tax_statement.total_brutto_gesamt,
            "tax_period": tax_period,
            "period_end_date": period_end_date
        }

        # Create summary table with direct data
        summary_table_data = create_summary_table({"summary": summary_data}, styles, usable_width)
        if summary_table_data:
            story.append(summary_table_data)

        story.append(Spacer(1, 0.5*cm))

        # Info boxes below the summary table
        story.append(create_dual_info_boxes(styles, usable_width))

    # --- Bank Accounts Section ---
    bank_table = create_bank_accounts_table(tax_statement, styles, usable_width)
    if bank_table:
        story.append(PageBreak())
        story.append(Paragraph("Bankkonten", title_style))
        story.append(bank_table)
        story.append(Spacer(1, 0.5*cm))

    # --- Securities/Depots Section for Type A ---
    securities_table_a = create_securities_table(tax_statement, styles, usable_width, "A")
    if securities_table_a:
        story.append(PageBreak())
        story.append(Paragraph("Wertschriften A-Werte (mit VSt.-Abzug)", title_style))
        story.append(securities_table_a)
        story.append(Spacer(1, 0.5*cm))
    
    # --- Securities/Depots Section for Type B ---
    securities_table_b = create_securities_table(tax_statement, styles, usable_width, "B")
    if securities_table_b:
        story.append(PageBreak())
        story.append(Paragraph("Wertschriften B-Werte (ohne VSt.-Abzug)", title_style))
        story.append(securities_table_b)
        story.append(Spacer(1, 0.5*cm))
    
    # --- Securities/Depots Section for Type DA1 ---
    securities_table_da1 = create_securities_table(tax_statement, styles, usable_width, "DA1")
    if securities_table_da1:
        story.append(PageBreak())
        story.append(Paragraph("Wertschriften DA-1 und USA-Werte", title_style))
        story.append(securities_table_da1)
        story.append(Spacer(1, 0.5*cm))

    if tax_statement.listOfExpenses:
        costs_data = {
            "summary": {
                "tax_period": tax_period,
                "period_end_date": period_end_date
            },
            "costs": [{'description': expense.name, 'type': get_expense_description(expense.expenseType), 'value_chf': expense.expenses} for expense in tax_statement.listOfExpenses.expense]}

        costs_table = create_costs_table(costs_data, styles, usable_width)
        if costs_table:
            story.append(PageBreak())
            story.append(Paragraph("Gebühren", title_style))
            story.append(costs_table)
            story.append(Spacer(1, 0.5*cm))

    # Info pages before the barcode
    templates_path = Path(__file__).parent / 'templates'
    if use_minimal_frontpage:
        tax_office_file = 'tax_office_minimal.de.md'
        tax_payer_file = 'tax_payer_minimal.en.md'
    else:
        tax_office_file = 'tax_office.de.md'
        tax_payer_file = 'tax_payer.en.md'
    with open(templates_path / tax_office_file, 'r', encoding='utf-8') as f:
        tax_office_markdown = f.read()
    with open(templates_path / tax_payer_file, 'r', encoding='utf-8') as f:
        tax_payer_markdown = f.read()

    story.append(PageBreak())
    story.extend(create_single_info_page(tax_office_markdown, styles, section='long-version'))
    story.append(PageBreak())
    story.extend(create_single_info_page(tax_payer_markdown, styles, section='long-version'))

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
                logger.error("Invalid --org-nr '%s': Must be a 5-digit string.", args.org_nr)
                return 1
        
        # Render to PDF
        output_path = render_tax_statement(tax_statement, args.output, override_org_nr=args.org_nr)
        
        logger.info("Tax statement successfully rendered to: %s", output_path)
        return 0
    except Exception as e:
        logger.error("Error rendering tax statement: %s", e)
        return 1

if __name__ == "__main__":
    sys.exit(main())
