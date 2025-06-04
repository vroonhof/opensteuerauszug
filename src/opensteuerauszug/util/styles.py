from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT


def get_custom_styles():
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
    
    # Header text styles for page headers
    styles.add(ParagraphStyle(name='HeaderInstitution', parent=base_style, fontSize=14, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='HeaderCreatedWith', parent=base_style, fontSize=9, fontName='Helvetica'))
    styles.add(ParagraphStyle(name='HeaderTitle', parent=base_style, fontSize=14, fontName='Helvetica-Bold'))
    
    return styles 