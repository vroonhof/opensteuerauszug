import pytest
from typer.testing import CliRunner
from pathlib import Path
from opensteuerauszug.steuerauszug import app
import lxml.etree as ET

runner = CliRunner()

class _LocalXsdResolver(ET.Resolver):
    def __init__(self, specs_dir: Path) -> None:
        super().__init__()
        self._specs_dir = specs_dir

    def resolve(self, url, pubid, context):
        if not url:
            return None
        basename = url.rsplit("/", 1)[-1]
        candidate = self._specs_dir / basename
        if candidate.exists():
            return self.resolve_filename(str(candidate), context)
        return None

def test_integration_ibkr_vt_and_chill_2025(tmp_path: Path):
    """
    End-to-end integration test for IBKR 2025 import and processing.
    Uses VT and Chill sample data and a mini Kursliste.
    """
    # Define paths
    project_root = Path(__file__).resolve().parent.parent
    input_file = project_root / "tests" / "samples" / "import" / "ibkr" / "vtandchill_2025.xml"
    kursliste_dir = project_root / "tests" / "samples" / "kursliste"
    output_pdf = tmp_path / "vtandchill_2025.pdf"
    output_xml = tmp_path / "vtandchill_2025.xml"
    
    # Run the CLI
    result = runner.invoke(
        app,
        [
            str(input_file),
            "--importer", "ibkr",
            "--tax-year", "2025",
            "--kursliste-dir", str(kursliste_dir),
            "--output", str(output_pdf),
            "--xml-output", str(output_xml),
            "--log-level", "DEBUG",
        ],
    )
    
    # Check execution success
    assert result.exit_code == 0, f"CLI execution failed with stdout:\n{result.stdout}"
    
    # Verify processing milestones in output
    assert "IBKR import complete." in result.stdout
    assert "CleanupCalculator finished." in result.stdout
    assert "KurslisteTaxValueCalculator finished." in result.stdout
    assert "TotalCalculator finished." in result.stdout
    assert f"Rendering successful to {output_pdf}" in result.stdout
    assert f"Final XML written to {output_xml}" in result.stdout
    assert "Processing finished successfully." in result.stdout
    
    # Verify output files exist
    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 0
    assert output_xml.exists()

    # Validate against eCH-0196-2-2 XSD
    specs_dir = project_root / "specs"
    xsd_path = specs_dir / "eCH-0196-2-2.xsd"
    xsd_parser = ET.XMLParser()
    xsd_parser.resolvers.add(_LocalXsdResolver(specs_dir))
    schema_doc = ET.parse(str(xsd_path), parser=xsd_parser)
    schema = ET.XMLSchema(schema_doc)
    xml_doc = ET.parse(str(output_xml))
    assert schema.validate(xml_doc), f"XSD validation failed:\n{schema.error_log}"

    # Smoketest XML content
    xml_content = output_xml.read_text()
    # Check for the expected ISIN from vtandchill_2025.xml
    assert "US9220427424" in xml_content
    # Check for institution name which should be in the statement
    assert "Interactive Brokers" in xml_content
    # Check for client name
    assert "Muster" in xml_content
    # Check for currency
    assert "CHF" in xml_content
    # Check for some calculated values (tax values or revenues)
    # The input had 200 shares of VT. kursliste_mini_2025.xml has VT with tax value.
    assert "VANGUARD TOT WORLD STK ETF (VT)" in xml_content
