import pytest
from typer.testing import CliRunner
from pathlib import Path
from unittest.mock import patch, MagicMock
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from opensteuerauszug.steuerauszug import app

runner = CliRunner()

def create_dummy_pdf(path: Path, pages: int = 1):
    c = canvas.Canvas(str(path))
    for i in range(pages):
        c.drawString(100, 100, f"Page {i+1}")
        c.showPage()
    c.save()

def create_dummy_xml(path: Path):
    path.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<eCH-0196:taxStatement xmlns:eCH-0196="http://www.ech.ch/xmlns/eCH-0196/2" minorVersion="2">
    <eCH-0196:institution>
        <eCH-0196:name>Test Bank</eCH-0196:name>
        <eCH-0196:address>
            <eCH-0196:name>Test Bank</eCH-0196:name>
            <eCH-0196:street>Street</eCH-0196:street>
            <eCH-0196:zip>8000</eCH-0196:zip>
            <eCH-0196:city>Zurich</eCH-0196:city>
        </eCH-0196:address>
    </eCH-0196:institution>
    <eCH-0196:client>
        <eCH-0196:clientNumber>12345</eCH-0196:clientNumber>
        <eCH-0196:person>
            <eCH-0196:firstName>John</eCH-0196:firstName>
            <eCH-0196:lastName>Doe</eCH-0196:lastName>
        </eCH-0196:person>
    </eCH-0196:client>
    <eCH-0196:taxPeriod>2023</eCH-0196:taxPeriod>
    <eCH-0196:periodFrom>2023-01-01</eCH-0196:periodFrom>
    <eCH-0196:periodTo>2023-12-31</eCH-0196:periodTo>
</eCH-0196:taxStatement>
""")

@pytest.fixture
def dummy_xml(tmp_path):
    xml_path = tmp_path / "input.xml"
    create_dummy_xml(xml_path)
    return xml_path

@pytest.fixture
def pre_amble_pdf(tmp_path):
    pdf_path = tmp_path / "pre.pdf"
    create_dummy_pdf(pdf_path, pages=1)
    return pdf_path

@pytest.fixture
def post_amble_pdf(tmp_path):
    pdf_path = tmp_path / "post.pdf"
    create_dummy_pdf(pdf_path, pages=2)
    return pdf_path

def test_cli_concatenation(tmp_path, dummy_xml, pre_amble_pdf, post_amble_pdf):
    output_pdf = tmp_path / "output.pdf"

    # Mock render_tax_statement to produce a dummy PDF
    with patch("opensteuerauszug.steuerauszug.render_tax_statement") as mock_render:
        def side_effect(statement, output_path, **kwargs):
            # output_path should be the temp path
            create_dummy_pdf(Path(output_path), pages=3)
            return Path(output_path)

        mock_render.side_effect = side_effect

        # Mock ConfigManager and TotalCalculator
        with patch("opensteuerauszug.steuerauszug.ConfigManager") as MockConfigManager, \
             patch("opensteuerauszug.steuerauszug.TotalCalculator") as MockTotalCalculator:

             MockConfigManager.return_value.general_settings = None
             MockConfigManager.return_value.calculate_settings = MagicMock()
             MockConfigManager.return_value.calculate_settings.keep_existing_payments = False

             MockTotalCalculator.return_value.calculate.side_effect = lambda x: x

             result = runner.invoke(app, [
                 str(dummy_xml),
                 "--output", str(output_pdf),
                 "--raw-import",
                 "--phases", "render",
                 "--pre-amble", str(pre_amble_pdf),
                 "--post-amble", str(post_amble_pdf),
                 "--tax-year", "2023",
                 "--period-from", "2023-01-01",
                 "--period-to", "2023-12-31",
                 "--tax-calculation-level", "none"
             ])

    print(result.stdout)
    assert result.exit_code == 0
    assert output_pdf.exists()

    reader = PdfReader(output_pdf)
    # 1 page pre + 3 pages main + 2 pages post = 6 pages
    assert len(reader.pages) == 6

def test_cli_concatenation_failure_cleanup(tmp_path, dummy_xml, pre_amble_pdf):
    output_pdf = tmp_path / "output_fail.pdf"

    with patch("opensteuerauszug.steuerauszug.render_tax_statement") as mock_render, \
         patch("opensteuerauszug.steuerauszug.PdfWriter") as MockPdfWriter:

        def side_effect(statement, output_path, **kwargs):
            create_dummy_pdf(Path(output_path), pages=1)
            return Path(output_path)
        mock_render.side_effect = side_effect

        # Simulate failure during merge
        MockPdfWriter.return_value.append.side_effect = Exception("Merge failed")

        with patch("opensteuerauszug.steuerauszug.ConfigManager") as MockConfigManager, \
             patch("opensteuerauszug.steuerauszug.TotalCalculator") as MockTotalCalculator:

             MockConfigManager.return_value.general_settings = None
             MockConfigManager.return_value.calculate_settings = MagicMock()
             MockTotalCalculator.return_value.calculate.side_effect = lambda x: x

             result = runner.invoke(app, [
                 str(dummy_xml),
                 "--output", str(output_pdf),
                 "--raw-import",
                 "--phases", "render",
                 "--pre-amble", str(pre_amble_pdf),
                 "--tax-year", "2023",
                 "--period-from", "2023-01-01",
                 "--period-to", "2023-12-31",
                 "--tax-calculation-level", "none"
             ])

    assert result.exit_code == 1
    assert "Error during PDF concatenation: Merge failed" in result.stdout

    # Check that temp file is cleaned up
    temp_file = output_pdf.with_suffix(".tmp_main.pdf")
    assert not temp_file.exists()
