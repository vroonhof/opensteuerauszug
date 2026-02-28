from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

FONT_REGULAR = 'Helvetica'
FONT_BOLD = 'Helvetica-Bold'

def get_custom_styles():
    styles = getSampleStyleSheet()
    base_style = styles['Normal']
    base_style.fontSize = 8
    leading = 9.4 # Tight line spacing - reduced from default 9.6 (1.2 * 8)
    base_style.leading = leading
    styles.add(ParagraphStyle(name='Header_LEFT', parent=base_style, alignment=TA_LEFT, fontName=FONT_REGULAR, leading=leading))
    styles.add(ParagraphStyle(name='Header_CENTER', parent=base_style, alignment=TA_CENTER, fontName=FONT_REGULAR, leading=leading))
    styles.add(ParagraphStyle(name='Header_RIGHT', parent=base_style, alignment=TA_RIGHT, fontName=FONT_REGULAR, leading=leading))
    styles.add(ParagraphStyle(name='Val_LEFT', parent=base_style, alignment=TA_LEFT, leading=leading))
    styles.add(ParagraphStyle(name='Val_RIGHT', parent=base_style, alignment=TA_RIGHT, leading=leading))
    styles.add(ParagraphStyle(name='Val_CENTER', parent=base_style, alignment=TA_CENTER, leading=leading))
    styles.add(ParagraphStyle(name='Bold_LEFT', parent=styles['Val_LEFT'], fontName=FONT_BOLD, leading=leading))
    styles.add(ParagraphStyle(name='Bold_RIGHT', parent=styles['Val_RIGHT'], fontName=FONT_BOLD, leading=leading))

    # Header text styles for page headers
    styles.add(ParagraphStyle(name='HeaderInstitution', parent=base_style, fontSize=24, fontName=FONT_BOLD))
    styles.add(ParagraphStyle(name='HeaderCreatedWith', parent=base_style, fontSize=9, fontName=FONT_REGULAR))
    styles.add(ParagraphStyle(name='HeaderTitle', parent=base_style, fontSize=16, fontName=FONT_BOLD))

    return styles
