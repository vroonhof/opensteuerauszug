

import io
from PIL import Image as PILImage
from decimal import Decimal, ROUND_HALF_UP

# --- ReportLab Imports ---
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape

# --- Configuration ---
FILENAME = "steuer_auszug_example_v8_shifted.pdf"
COMPANY_NAME = "Bank WIR"
DOC_INFO = "S. E. & O."

# --- Helper Function for Currency Formatting ---
def format_currency(value, default='0.00'):
    # (Same as v7)
    if value is None or value == '': return default
    try:
        decimal_value = Decimal(str(value)).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
        formatted = '{:,.0f}'.format(decimal_value).replace(',', "'")
        return formatted
    except: return default

# --- Header/Footer Canvas ---
class PageNumCanvas(canvas.Canvas):
    # (Same as v7 - handles landscape)
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []
        self.page_width, self.page_height = landscape(A4)
    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()
    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)
    def draw_header_footer(self, page_count):
        self.saveState()
        self.setFont('Helvetica', 9)
        header_text = "7010001 | 85506710549033 | 8391"
        self.setFillColor(colors.black)
        header_x = self.page_width - 20*mm
        header_y = self.page_height - 15*mm
        self.drawRightString(header_x, header_y, header_text)
        self.setFont('Helvetica', 9)
        self.setFillColor(colors.grey)
        footer_y = 15*mm
        self.drawString(20*mm, footer_y, COMPANY_NAME)
        self.drawCentredString(self.page_width / 2.0, footer_y, DOC_INFO)
        self.drawRightString(self.page_width - 20*mm, footer_y, f"Seite {self._pageNumber}/{page_count}")
        self.restoreState()


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

# --- Liabilities Table Function (Optional) ---
def create_liabilities_table(data, styles, usable_width):
    # (Code remains the same as v7)
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

# --- Costs Table Function (Optional) ---
def create_costs_table(data, styles, usable_width):
    # (Code remains the same as v7)
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


# --- Barcode Generation Placeholder ---
def get_barcode_image(data):
    # (Same as v7)
    try:
        from barcode.writer import ImageWriter
        from barcode import Code128
        code = Code128(str(data), writer=ImageWriter())
        pil_img = code.render(writer_options={'write_text': False, 'module_height': 10.0})
        print(f"Generated barcode for '{data}'")
        return pil_img
    except ImportError:
        print("python-barcode library not found. Using placeholder image.")
        img = PILImage.new('RGB', (800, 150), color = 'grey')
        return img
    except Exception as e:
        print(f"Error generating barcode: {e}")
        img = PILImage.new('RGB', (800, 150), color = 'red')
        return img

# --- Main Document Generation Function ---
def generate_pdf(data):
    """Generates the complete PDF document in landscape with shifted totals (v8)."""
    buffer = io.BytesIO()
    page_width, page_height = landscape(A4)
    left_margin = 20*mm
    right_margin = 20*mm
    usable_width = page_width - left_margin - right_margin

    doc = SimpleDocTemplate(buffer,
                            pagesize=landscape(A4),
                            leftMargin=left_margin,
                            rightMargin=right_margin,
                            topMargin=25*mm,
                            bottomMargin=25*mm)

    # --- Define styles centrally ---
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
    if 'customer' in data: story.append(Paragraph(f"<b>Kunde:</b> {data['customer'].get('name', '')}", client_info_style))
    if 'customer' in data: story.append(Paragraph(f"<b>Adresse:</b> {data['customer'].get('address', '')}", client_info_style))
    if 'portfolio' in data: story.append(Paragraph(f"<b>Portfolio:</b> {data.get('portfolio', '')}", client_info_style))
    if 'period' in data: story.append(Paragraph(f"<b>Periode:</b> {data.get('period', '')}", client_info_style))
    if 'created_date' in data: story.append(Paragraph(f"<b>Erstellt am:</b> {data.get('created_date', '')}", client_info_style))
    story.append(Spacer(1, 0.5*cm))

    # --- Sections ---
    title_style = ParagraphStyle(name='SectionTitle', parent=styles['h2'], alignment=TA_LEFT, fontSize=10, spaceAfter=4*mm)

    # 1. Summary
    story.append(Paragraph("Steuerauszug 31.12.2024 | Zusammenfassung", title_style))
    summary_content = create_summary_table(data, styles, usable_width)
    if summary_content: story.append(summary_content)
    story.append(Spacer(1, 0.5*cm))

    # 2. Costs (Optional)
    costs_content = create_costs_table(data, styles, usable_width)
    if costs_content:
        story.append(PageBreak())
        story.append(Paragraph("Steuerauszug 31.12.2024 | Bezahlte Bankspesen", title_style))
        story.append(costs_content)
        story.append(Spacer(1, 0.5*cm))

    # 3. Accounts (Placeholder)
    # ...

    # 4. Liabilities (Optional)
    liabilities_table = create_liabilities_table(data, styles, usable_width)
    if liabilities_table:
        story.append(PageBreak())
        story.append(Paragraph("Steuerauszug 31.12.2024 | Schulden", title_style))
        story.append(liabilities_table)
        story.append(Spacer(1, 0.5*cm))

    # 5. Barcode (Optional)
    if data.get('barcode_data'):
        story.append(PageBreak())
        story.append(Spacer(1, 3*cm))
        try:
            barcode_pil_image = get_barcode_image(data['barcode_data'])
            img_buffer = io.BytesIO()
            barcode_pil_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            barcode_img = Image(img_buffer, width=usable_width * 0.8, height=4*cm)
            barcode_img.hAlign = 'CENTER'
            story.append(barcode_img)
        except Exception as e:
            print(f"Error adding barcode image: {e}")
            story.append(Paragraph(f"[Error adding barcode: {e}]", styles['Italic']))

    # --- Build PDF ---
    doc.build(story, canvasmaker=PageNumCanvas)

    pdf_value = buffer.getvalue()
    buffer.close()
    return pdf_value


# --- Example Data Structure ---
# (Same as v6)
example_data = {
    "customer": { "name": "Herr Johannes Vroonhof und Frau Talitha Bakker", "address": "8903 Birmensdorf ZH" },
    "portfolio": "825.829-44-00 Hauptportfolio", "period": "01.01.2024-31.12.2024", "created_date": "04.02.2025",
    "summary": {
        "steuerwert_ab": 10063, "steuerwert_a": 10063, "steuerwert_b": 0, "brutto_mit_vst": 5.52,
        "brutto_ohne_vst": 0, "vst_anspruch": 1.90, "steuerwert_da1_usa": 0, "brutto_da1_usa": 0,
        "pauschale_da1": 0, "rueckbehalt_usa": 0, "total_steuerwert": 10063, "total_brutto_mit_vst": 5.52,
        "total_brutto_ohne_vst": 0, "total_brutto_gesamt": 5.52,
    },
    "costs": [ { "description": "Verwaltungskosten Kontoführungsgebühr", "type": "Kontoführungsgebühren (...)", "value_chf": 30.00 }, ],
    "accounts": [ ],
    "liabilities": [ {
            "description": "Darlehen/Hypothek fest CHF VIAC GB Birmensdorf Nr. 4436\nCH39 0839 1825 8294 4380 0",
            "currency": "CHF", "amount": 500000.00, "rate": "", "value_chf": 500000.00, "total_interest": 11500.00, "date": "31.12.2024",
            "transactions": [ {"date": "31.03.2024", "description": "Sollzins", "amount": 2875.00}, {"date": "30.06.2024", "description": "Sollzins", "amount": 2875.00}, {"date": "30.09.2024", "description": "Sollzins", "amount": 2875.00}, {"date": "31.12.2024", "description": "Sollzins", "amount": 2875.00}, ]
        }, ],
    "barcode_data": "7010001855067105490338391"
}

# --- Generate and Save PDF ---
if __name__ == "__main__":
    print(f"Generating PDF: {FILENAME}...")
    pdf_data = generate_pdf(example_data)
    with open(FILENAME, 'wb') as f:
        f.write(pdf_data)
    print("PDF generated successfully.")
