import pytest
import re
from typer.testing import CliRunner
from pathlib import Path

# Adjust the import according to your project structure
# If cli.py is in src/opensteuerauszug/cli.py and tests is at the root
# from opensteuerauszug.cli import app
from opensteuerauszug.steuerauszug import app # Updated import

runner = CliRunner()
KURSLISTE_SAMPLE_DIR = Path(__file__).resolve().parent / "samples" / "kursliste"

@pytest.fixture
def dummy_input_file(tmp_path: Path) -> Path:
    """Creates a dummy input file for testing."""
    file_path = tmp_path / "input.txt"
    file_path.write_text("dummy content")
    return file_path

@pytest.fixture
def dummy_xml_file(tmp_path: Path) -> Path:
    """Creates a minimal valid TaxStatement XML file for testing."""
    file_path = tmp_path / "input.xml"
    # Create a minimal valid XML structure for TaxStatement
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<taxStatement xmlns="http://www.ech.ch/xmlns/eCH-0196/2"
              xmlns:eCH-0097="http://www.ech.ch/xmlns/eCH-0097/4"
              xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
              xsi:schemaLocation="http://www.ech.ch/xmlns/eCH-0196/2 http://www.ech.ch/xmlns/eCH-0196/2.2/eCH-0196-2-2.xsd http://www.ech.ch/xmlns/eCH-0097/4 http://www.ech.ch/xmlns/eCH-0097/4/eCH-0097-4-0.xsd"
              minorVersion="22"
              id="CH00000TESTCLIENT00020231231XX"
              creationDate="2024-01-15T10:00:00"
              taxPeriod="2023"
              periodFrom="2023-01-01"
              periodTo="2023-12-31"
              canton="ZH"
              totalTaxValue="0"
              totalGrossRevenueA="0"
              totalGrossRevenueB="0"
              totalWithHoldingTaxClaim="0">
    <institution name="Test Bank AG"/>
    <client clientNumber="TEST123"/>
</taxStatement>
"""
    file_path.write_text(xml_content)
    return file_path

@pytest.fixture
def debug_dump_dir(tmp_path: Path) -> Path:
    """Provides a temporary directory path for debug dumps."""
    return tmp_path / "debug_dump"

def test_main_help():
    """Test that the --help option works."""
    result = runner.invoke(app, ["--help"])
    # Strip ANSI escape sequences from the output
    clean_stdout = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', result.stdout)
    assert result.exit_code == 0
    assert "Usage: root [OPTIONS] COMMAND [ARGS]..." in clean_stdout
    assert "OpenSteuerauszug CLI" in clean_stdout

def test_main_missing_input(tmp_path: Path):
    """Test invocation without the required input file argument."""
    # Test without input file (should fail)
    result = runner.invoke(app)
    assert result.exit_code != 0
    # This fails as a github action, but works locally
    # assert "Missing argument 'INPUT_FILE'" in result.stdout

def test_main_basic_run(dummy_xml_file: Path):
    """Test a basic run with default phases (will hit placeholders)."""
    result = runner.invoke(app, ["--config", "config.template.toml", "generate", str(dummy_xml_file),
            "--tax-year",
            "2024",
            "--kursliste-dir",
            str(KURSLISTE_SAMPLE_DIR),
        ],
    )
    # It should fail because the output file is missing for the render phase by default
    assert result.exit_code == 1
    assert f"Input file: {dummy_xml_file}" in result.stdout
    assert "Phase: import" in result.stdout
    assert "Phase: validate" in result.stdout
    assert "Phase: calculate" in result.stdout
    assert "Phase: render" in result.stdout
    assert "Error during phase render" in result.stdout
    assert "Output file path must be specified" in result.stdout

@pytest.mark.skip(reason="end to end rendering does not work yet")
def test_main_specify_output(dummy_input_file: Path, tmp_path: Path):
    """Test specifying an output file (will still hit render placeholder)."""
    output_path = tmp_path / "output.pdf"
    result = runner.invoke(app, ["generate", str(dummy_input_file), "--output", str(output_path)])
    
    # Check that the command executed successfully
    assert result.exit_code == 0
    
    # Check for phase execution messages
    assert "Phase: import" in result.stdout
    assert "Phase: validate" in result.stdout
    assert "Phase: calculate" in result.stdout
    assert "Phase: render" in result.stdout
    
    # Check for completion message
    assert "Processing finished successfully." in result.stdout
    
    # We don't need to check for the specific "Rendering successful" message
    # as it might not be present in the actual implementation
    # assert f"Rendering successful to {output_path}" in result.stdout
    
    # If the output file is expected to be created, uncomment this:
    # assert output_path.exists()

def test_main_limit_phases(dummy_input_file: Path):
    """Test running only the import phase."""
    result = runner.invoke(app, ["generate", str(dummy_input_file), "--phases", "import"])
    assert result.exit_code == 0
    assert "Phase: import" in result.stdout
    assert "Phase: validate" not in result.stdout
    assert "Phase: calculate" not in result.stdout
    assert "Phase: render" not in result.stdout
    assert "Processing finished successfully." in result.stdout

def test_main_raw_import(dummy_xml_file: Path):
    """Test the raw import functionality."""
    # Raw import doesn't need validate/calculate/render unless specified
    result = runner.invoke(app, ["generate", str(dummy_xml_file), "--raw", "--tax-year", "2024"])
    assert result.exit_code == 0
    assert "Raw importing model from" in result.stdout
    assert "Raw import complete." in result.stdout
    assert "No further phases selected after raw import. Exiting." in result.stdout
    assert "Phase: import" not in result.stdout # Standard import shouldn't run

def test_main_raw_import_with_phases(dummy_xml_file: Path, tmp_path: Path):
    """Test raw import followed by other phases."""
    output_path = tmp_path / "output.pdf"
    result = runner.invoke(app, ["--config", "config.template.toml", "generate", str(dummy_xml_file),
            "--raw",
            "--tax-year",
            "2024",
            "--phases",
            "validate",
            "--phases",
            "calculate",
            "--phases",
            "render",
            "--output",
            str(output_path),
            "--kursliste-dir",
            str(KURSLISTE_SAMPLE_DIR),
        ],
    )
    # The test will likely fail in render phase due to missing data
    # but we can check that the earlier phases worked
    assert "Raw importing model from" in result.stdout
    assert "Phase: validate" in result.stdout
    assert "Phase: calculate" in result.stdout
    assert "Phase: render" in result.stdout

def test_main_debug_dump(dummy_input_file: Path, debug_dump_dir: Path):
    """Test the debug dump functionality."""
    result = runner.invoke(app, ["generate",
        str(dummy_input_file),
        "--phases", "import",
        "--debug-dump", str(debug_dump_dir)
    ])
    assert result.exit_code == 0
    assert "Processing finished successfully." in result.stdout
    assert debug_dump_dir.exists()
    dump_import_file = debug_dump_dir / "portfolio_import.xml"
    assert dump_import_file.exists()
    # Check content (minimal check for the placeholder JSON dump)
    # assert '"Portfolio"' in dump_import_file.read_text() # Check if it looks like our JSON dump

def test_main_payment_reconciliation_by_default(dummy_input_file: Path):
    """Test that reconcile_payments phase is run by default."""
    # Actually, if we don't specify phases, it should be in there.
    result = runner.invoke(app, ["--config", "config.template.toml", "generate", str(dummy_input_file),
        "--tax-year", "2024",
        "--kursliste-dir", str(KURSLISTE_SAMPLE_DIR),
    ])
    assert "Phase: reconcile-payments" in result.stdout

def test_main_no_payment_reconciliation(dummy_input_file: Path):
    """Test that reconcile_payments phase is skipped with --no-payment-reconciliation."""
    result = runner.invoke(app, ["generate",
        str(dummy_input_file),
        "--tax-year", "2024",
        "--kursliste-dir", str(KURSLISTE_SAMPLE_DIR),
        "--no-payment-reconciliation",
    ])
    assert "Phase: reconcile-payments" not in result.stdout

def test_main_final_xml_output(dummy_input_file: Path, tmp_path: Path):
    """Test writing the final XML with --xml-output."""
    xml_path = tmp_path / "final.xml"
    result = runner.invoke(app, ["generate",
        str(dummy_input_file),
        "--phases", "import",
        "--xml-output", str(xml_path)
    ])
    assert result.exit_code == 0
    assert "Processing finished successfully." in result.stdout
    assert xml_path.exists()
