# Import necessary ReportLab components
from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.pdfgen import canvas
# Import landscape and A4 page size
from reportlab.lib.pagesizes import A4, landscape
# Import Tuple for type hinting from the correct module
from typing import Tuple
import logging
# Import standard colors
from reportlab.lib import colors

PRINT_SCALE_CORRECTION = 1/0.97 # Allow for printer scaling (97% reduction)

logger = logging.getLogger(__name__)
    
class OneDeeBarCode:
    """
    Generates and draws 1D CODE128 barcode objects for ReportLab,
    according to eCH-0196 V2.2 specification.

    Generates the barcode widget and provides a method to draw it
    in a specific rotated layout (approx 10mm top, text baseline 5mm left,
    -90deg rotation) onto a given canvas. Manually draws the
    human-readable text with correct positioning and increased spacing.
    Barcode width increased. Quiet zone disabled on widget.

    Based on: BEIL2_d_DEF_2022-06-07_eCH-0196_V2.0.0_Barcode Generierung -
              Technische Wegleitung.pdf
    """
    FORMULAR_NR = '196' # eCH-0196
    VERSION_NR = '22'   # Assuming v2.2
    AUSRICHTUNG_POS_ID = '02' # Reading order 2 (left/right, top-to-bottom)

    def generate_barcode(self, page_number: int, is_barcode_page: bool, org_nr: str = '00000') -> code128.Code128 | None:
        """
        Generates a ReportLab Code128 barcode widget object (without text or quiet zone).

        Args:
            page_number: The page number for the document.
            is_barcode_page: True if this page contains the 2D barcode sheet,
                             False otherwise.
            org_nr: The 5-digit numeric Organisation Number (e.g., Clearing Nr.).
                    Defaults to '00000'.

        Returns:
            A configured reportlab.graphics.barcode.code128.Code128 object
            (with humanReadable=False, quiet=False), or None if an error occurred.
        """
        # --- Input Validation ---
        if not isinstance(page_number, int) or page_number < 1:
            logger.error("page_number must be a positive integer.")
            return None
        if not isinstance(org_nr, str) or not org_nr.isdigit() or len(org_nr) != 5:
            logger.error("org_nr '%s' must be a 5-digit string.", org_nr)
            return None
        if not isinstance(is_barcode_page, bool):
            logger.error("is_barcode_page must be a boolean (True or False).")
            return None

        # --- Assemble Barcode Data ---
        page_str = f"{page_number:03d}" # Format to 3 digits with leading zeros
        barcode_flag = '1' if is_barcode_page else '0'

        barcode_data = (
            self.FORMULAR_NR +
            self.VERSION_NR +
            org_nr +
            page_str +
            barcode_flag +
            self.AUSRICHTUNG_POS_ID
        ) # Total 16 digits

        if len(barcode_data) != 16:
            logger.error("Internal logic error, generated data length is not 16: %s", barcode_data)
            return None

        # --- Create ReportLab Barcode Widget ---
        try:
            # Document specifies >= 7mm height
            min_height = 7 * mm * PRINT_SCALE_CORRECTION
            # Keep increased barWidth for >= 38mm total width
            bar_width_points = 0.3 * mm * PRINT_SCALE_CORRECTION

            barcode_widget = code128.Code128(
                barcode_data,
                barHeight=min_height,
                barWidth=bar_width_points,
                humanReadable=False, # Disable built-in text rendering
                quiet=False          # Disable built-in quiet zone
            )

            # print(f"Generated ReportLab barcode widget (no text/quiet) for page {page_number} (Data: {barcode_data})")
            # Print calculated width to check against >= 38mm requirement
            # print(f"  Widget width: {barcode_widget.width*PRINT_SCALE_CORRECTION/mm:.1f}mm") # Note: width might not account for quiet zone if quiet=True
            return barcode_widget

        except Exception as e:
            logger.error("Error generating barcode widget for page %s: %s", page_number, e)
            raise e
            return None

    def draw_barcode_on_canvas(self,
                               canvas: canvas.Canvas,
                               barcode_widget: code128.Code128,
                               pagesize: Tuple[float, float]):
        """
        Draws the provided barcode widget onto the canvas, rotated -90 degrees.
        Positions the drawing so the text baseline is 5mm from the left edge,
        and the top of the rotated barcode is approx 10mm from the top edge.
        Manually draws the human-readable text to the left of the bars (relative
        to rotation) with a gap and approx 3mm height.

        Assumes the canvas uses the provided pagesize.

        Args:
            canvas: The ReportLab canvas object to draw on.
            barcode_widget: The generated Code128 widget to draw.
            pagesize: A tuple (width, height) representing the page dimensions
                      (e.g., landscape(A4)).
        """

        page_width, page_height = pagesize

        # Target position: Text baseline 5mm from left, Top of rotated barcode ~10mm from top.
        margin_top = 10 * mm
        # Apply print scale correction to ensure proper margin at 97% printing
        margin_left = 5 * mm * PRINT_SCALE_CORRECTION

        # Dimensions of the barcode widget *before* rotation
        bw = barcode_widget.width
        bh = barcode_widget.barHeight # Use barHeight as it's the relevant dimension

        # --- Manual Text Settings ---
        # Gap between bars edge (y=0 in rotated coords) and text baseline
        font_size_points = 9 # 3mm is about 8.5pt, but 9pt is a common size
        font_name = "Helvetica"

        # Calculate text baseline position relative to the rotated origin (0,0)
        # This is the position along the rotated Y-axis (points left)
        text_y_relative = 5 * mm * PRINT_SCALE_CORRECTION # 5mm for text and spacing, adjusted for printing scale

        # Calculate the required translation point (final_bl_x, final_bl_y)
        # such that the text baseline lands at margin_left from the page edge.
        # Final page X = final_bl_x + y_rotated. We want X = margin_left when y_rotated = text_y_relative.
        # So, final_bl_x + text_y_relative = margin_left
        final_bl_x = margin_left + text_y_relative

        # final_bl_y determines the vertical position (bottom of rotated barcode)
        final_bl_y = page_height - margin_top  # Bottom edge of rotated barcode's bounding box

        canvas.saveState() # Save the current canvas state
        try:
            # Translate origin to the calculated final bottom-left corner
            canvas.translate(final_bl_x, final_bl_y)
            # Rotate -90 degrees around the new origin
            canvas.rotate(-90)

            # --- Draw Barcode Bars ---
            # Draw the barcode widget at the new origin (0,0).
            barcode_widget.drawOn(canvas, 0, 0)

            # --- Draw Manual Text ---
            # Calculate text position relative to the *new* rotated origin (0,0)
            text_x = bw / 2.0 # Center vertically along the bars (along rotated X-axis)
            # Use the relative y position calculated earlier for the baseline
            text_y = -text_y_relative

            # Set font, color, then draw the string centered at text_x
            canvas.setFont(font_name, font_size_points)
            canvas.setFillColor(colors.black)
            # Use drawCentredString to center the text horizontally at text_x
            canvas.drawCentredString(text_x, text_y, barcode_widget.value)

            # Debug lines for visual inspection during development
            # canvas.setStrokeColor(colors.red)
            # canvas.setLineWidth(0.5)
            # canvas.line(text_x - 10, text_y, text_x + 10, text_y) # Horizontal line at text baseline
            # canvas.line(text_x - 10, -5 * mm * PRINT_SCALE_CORRECTION, text_x + 10, -5 * mm * PRINT_SCALE_CORRECTION) 

        finally:
            canvas.restoreState() # Restore the canvas state (translation, rotation)

        # print(f"Drew rotated barcode and manual text on canvas.")
        # print(f"  Target Text Baseline X: {margin_left/mm:.1f}mm which gives ")
        # print(f"  Calculated BL corner X: {final_bl_x/mm:.1f}mm, Y: {final_bl_y/mm:.1f}mm")
        # print(f"  Text drawn relative to BL at ({text_x/mm:.1f}mm, {text_y/mm:.1f}mm) in rotated coords (using drawCentredString)")


# --- Example Usage ---
if __name__ == '__main__':
    generator = OneDeeBarCode()

    # 1. Generate a barcode widget (bars only, no quiet zone)
    barcode_widget_1 = generator.generate_barcode(page_number=5, is_barcode_page=False, org_nr='12345')

    # 2. Create a simple PDF and draw the barcode using the class method
    if barcode_widget_1:
        output_pdf_path = "reportlab_final_barcode_example.pdf" # Final filename
        page_layout = landscape(A4) # Define page layout

        # Create canvas
        c = canvas.Canvas(output_pdf_path, pagesize=page_layout)

        logger.info("Creating example PDF: %s", output_pdf_path)

        # --- Draw Rotated Barcode and Manual Text using the class method ---
        generator.draw_barcode_on_canvas(c, barcode_widget_1, page_layout)

        # --- Add an optional label (kept in example for clarity) ---
        # Note: bh is barHeight (original height), which becomes width after rotation
        bh_rotated_width = barcode_widget_1.barHeight
        # Adjust label position slightly based on new barcode placement logic
        label_x = 5 * mm + 12 * mm + 5 * mm # Position label to the right of the rotated barcode
        label_y = page_layout[1] - 10 * mm - 10 # Position label slightly below the top of barcode
        c.drawString(label_x, label_y, f"Rotated Barcode (Page 5)")

        # Save the PDF page and file
        c.showPage()
        c.save()
        logger.info("Example PDF saved.")

    else:
        logger.error("Failed to generate the barcode widget.")
