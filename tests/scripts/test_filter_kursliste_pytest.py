from decimal import Decimal
import tempfile
import os
import sys
from pathlib import Path
from subprocess import run, PIPE

import pytest
import lxml.etree as ET
from pydantic import ValidationError
from opensteuerauszug.model.kursliste import Kursliste as KurslisteModel

# Add the script's directory to sys.path to allow direct import
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent))  # Add project root to import opensteuerauszug

# Path to the script to be tested
FILTER_KURSLISTE_SCRIPT = SCRIPTS_DIR / "filter_kursliste.py"


@pytest.fixture
def sample_files_dir():
    """Return the path to the test data directory."""
    return Path(__file__).parent / "test_data"


@pytest.fixture
def sample_kursliste_xml(sample_files_dir):
    """Return the path to the sample kursliste XML file."""
    path = sample_files_dir / "sample_kursliste_for_filtering.xml"
    if not path.exists():
        pytest.skip(f"Sample kursliste file not found: {path}")
    return path


@pytest.fixture
def sample_ech0196_statement1_xml(sample_files_dir):
    """Return the path to the first sample eCH-0196 statement XML file."""
    path = sample_files_dir / "sample_ech0196_statement1.xml"
    if not path.exists():
        pytest.skip(f"Sample statement file not found: {path}")
    return path


@pytest.fixture
def sample_ech0196_statement2_xml(sample_files_dir):
    """Return the path to the second sample eCH-0196 statement XML file."""
    path = sample_files_dir / "sample_ech0196_statement2.xml"
    if not path.exists():
        pytest.skip(f"Sample statement file not found: {path}")
    return path


@pytest.fixture
def malformed_kursliste_xml(sample_files_dir):
    """Return the path to the malformed kursliste XML file."""
    path = sample_files_dir / "malformed_kursliste.xml"
    if not path.exists():
        pytest.skip(f"Malformed kursliste file not found: {path}")
    return path


@pytest.fixture
def malformed_ech0196_statement_xml(sample_files_dir):
    """Return the path to the malformed eCH-0196 statement XML file."""
    path = sample_files_dir / "malformed_ech0196_statement.xml"
    if not path.exists():
        pytest.skip(f"Malformed statement file not found: {path}")
    return path


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


def run_script(temp_dir, args_list):
    """
    Run the filter_kursliste.py script with given arguments.
    Returns the path to the output file, stdout, stderr, and return code.
    """
    output_xml_path = temp_dir / "output_kursliste.xml"
    
    common_args = [
        sys.executable,  # Python interpreter
        str(FILTER_KURSLISTE_SCRIPT),
        "--output-file", str(output_xml_path),
    ]
    
    cmd = common_args + args_list
    
    print(f"Running command: {' '.join(cmd)}")  # For debugging tests
    
    result = run(cmd, capture_output=True, text=True, encoding='utf-8')

    print(f"Command completed with return code {result.returncode}")
    print(f"Stdout:\n{result.stdout}")
    print(f"Stderr:\n{result.stderr}")
    
    return output_xml_path, result.stdout, result.stderr, result.returncode


def parse_output_xml(output_xml_path):
    """Parse the output XML file into a KurslisteModel object."""
    if not output_xml_path.exists() or output_xml_path.stat().st_size == 0:
        print(f"Output XML file {output_xml_path} does not exist or is empty.")
        return None
    try:
        # Pass denylist=None as we expect the filtered output to be loadable in its entirety
        parsed_model = KurslisteModel.from_xml_file(str(output_xml_path), denylist=None)
        print(f"Successfully parsed output XML: {output_xml_path}")
        return parsed_model
    except FileNotFoundError:
        print(f"Output XML file {output_xml_path} not found during parsing attempt.")
        pytest.fail(f"Output XML file {output_xml_path} not found during parsing attempt.")
    except Exception as e:
        print(f"Failed to parse output XML file {output_xml_path} due to {type(e).__name__}: {e}")
        # For debugging, print the content of the file that failed to parse
        try:
            with open(output_xml_path, 'r', encoding='utf-8') as f_debug:
                print(f"Content of {output_xml_path} that failed parsing:\n{f_debug.read()}")
        except Exception as e_read:
            print(f"Could not read content of {output_xml_path} for debugging: {e_read}")
        pytest.fail(f"Failed to parse output XML file {output_xml_path}: {type(e).__name__} - {e}")
    return None  # Should not be reached if pytest.fail is called


def test_filter_by_cmd_line_valors_only(temp_dir, sample_kursliste_xml):
    """Test filtering kursliste by command line valor numbers only."""
    args = [
        "--input-file", str(sample_kursliste_xml),
        "--valor-numbers", "12345",  # Test Share CHF
        "--target-currency", "CHF",
        "--log-level", "DEBUG"  # Use DEBUG for more verbose output during tests
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode == 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}"
    assert output_xml_path.exists(), "Output XML file was not created."

    output_kursliste = parse_output_xml(output_xml_path)
    assert output_kursliste is not None, "Failed to parse output XML."

    # Verify securities
    assert output_kursliste.shares is not None, "Shares section is missing."
    assert len(output_kursliste.shares) == 1, "Incorrect number of shares found."
    assert output_kursliste.shares[0].valorNumber == 12345
    assert output_kursliste.shares[0].currency == "CHF"
    
    assert not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty."
    assert not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty."

    # Verify DefinitionCurrency
    # Expect CHF (from security) and target_currency (CHF)
    assert output_kursliste.currencies is not None, "DefinitionCurrencies are missing."
    found_currencies = {c.currency for c in output_kursliste.currencies}
    assert "CHF" in found_currencies, "CHF definition currency missing."
    # Only CHF should be present as no other currency is referenced by kept securities or target
    assert len(found_currencies) == 1, f"Expected only CHF definition currency, found: {found_currencies}"

    # Verify Exchange Rates (target CHF, security CHF -> effectively no explicit rates needed beyond definition)
    # For CHF target, rates to CHF are 1.0 and usually implicit or not listed as separate entries unless it's a cross-rate.
    # The script keeps ExchangeRate* entries if their currency symbol is in relevant_currencies.
    # Since only CHF is relevant here, and Kursliste has no CHF-to-CHF rates, these lists should be empty/None.
    assert not output_kursliste.exchangeRates or len(output_kursliste.exchangeRates) == 0, \
        f"Daily exchange rates should be empty for CHF->CHF. Found: {len(output_kursliste.exchangeRates) if output_kursliste.exchangeRates else 0}"
    assert not output_kursliste.exchangeRatesMonthly or len(output_kursliste.exchangeRatesMonthly) == 0, \
        f"Monthly exchange rates should be empty for CHF->CHF. Found: {len(output_kursliste.exchangeRatesMonthly) if output_kursliste.exchangeRatesMonthly else 0}"
    assert not output_kursliste.exchangeRatesYearEnd or len(output_kursliste.exchangeRatesYearEnd) == 0, \
        f"Year-end exchange rates should be empty for CHF->CHF. Found: {len(output_kursliste.exchangeRatesYearEnd) if output_kursliste.exchangeRatesYearEnd else 0}"

def test_filter_by_tax_statement_valors_only(temp_dir, sample_kursliste_xml, sample_ech0196_statement1_xml):
    """Test filtering kursliste by tax statement valor numbers only."""
    args = [
        "--input-file", str(sample_kursliste_xml),
        "--tax-statement-files", str(sample_ech0196_statement1_xml),
        "--target-currency", "CHF",  # Important for exchange rate selection
        "--log-level", "DEBUG"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode == 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}"
    assert output_xml_path.exists(), "Output XML file was not created."
    
    output_kursliste = parse_output_xml(output_xml_path)
    assert output_kursliste is not None, "Failed to parse output XML."

    # Expected valors from statement1.xml: 12345 (Share CHF), 54321 (not in Kursliste)
    # Expected currencies from statement1.xml: CHF (from sec 12345), USD (from sec 54321), EUR (from bank account)
    # Target currency is CHF.

    # Verify securities
    assert output_kursliste.shares is not None, "Shares section is missing."
    found_share_valors = {s.valorNumber for s in output_kursliste.shares}
    assert 12345 in found_share_valors, "Share 12345 should be present."
    assert 54321 not in found_share_valors, "Share 54321 should not be present as it's not in Kursliste."
    assert len(output_kursliste.shares) == 1, "Incorrect number of shares found."
    
    assert not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty."
    assert not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty."

    # Verify DefinitionCurrency (CHF from sec 12345, USD from sec 54321 in tax statement, EUR from bank account in tax statement)
    # All these should be included because they are found in tax statements or target.
    assert output_kursliste.currencies is not None, "DefinitionCurrencies are missing."
    found_def_currencies = {c.currency for c in output_kursliste.currencies}
    expected_def_currencies = {"CHF", "USD", "EUR"}  # CHF (target/security), USD (tax statement sec), EUR (tax statement bank acc)
    assert found_def_currencies == expected_def_currencies, \
        f"Expected definition currencies {expected_def_currencies}, found: {found_def_currencies}"

    # Verify Exchange Rates (target CHF)
    # Expected currencies needing rates to CHF: USD, EUR (from tax statement)
    assert output_kursliste.exchangeRatesYearEnd is not None, "Year-end exchange rates missing."
    found_ye_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesYearEnd}
    assert "USD" in found_ye_rates_currencies, "USD year-end exchange rate to CHF missing."
    assert "EUR" in found_ye_rates_currencies, "EUR year-end exchange rate to CHF missing."
    # JPY was in sample Kursliste but not referenced by tax statement or target.
    assert "JPY" not in found_ye_rates_currencies, "JPY year-end exchange rate should not be present."

    # Check one USD rate value
    usd_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "USD"), None)
    assert usd_ye_rate is not None
    assert usd_ye_rate.value == Decimal('0.90')  # From sample_kursliste_for_filtering.xml

    # Check monthly rates (EUR is relevant from tax statement bank account)
    assert output_kursliste.exchangeRatesMonthly is not None
    found_m_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesMonthly}
    assert "EUR" in found_m_rates_currencies, "EUR monthly exchange rate should be present."
    # USD was in sample Kursliste monthly, but not specifically referenced for a monthly context by tax data.
    # The logic is: if 'EUR' is a relevant_currency, all 'EUR' rates are pulled.
    assert "USD" in found_m_rates_currencies, "USD monthly exchange rate should be present as USD is relevant."

    # Check daily rates (USD is relevant from tax statement security)
    assert output_kursliste.exchangeRates is not None
    found_d_rates_currencies = {er.currency for er in output_kursliste.exchangeRates}
    assert "USD" in found_d_rates_currencies, "USD daily exchange rate should be present."


def test_filter_by_union_valors_and_currencies(temp_dir, sample_kursliste_xml, sample_ech0196_statement1_xml, sample_ech0196_statement2_xml):
    """Test filtering kursliste by union of command line valor numbers and tax statement valor numbers."""
    args = [
        "--input-file", str(sample_kursliste_xml),
        "--valor-numbers", "11223",  # Fund EUR from Kursliste
        "--tax-statement-files", str(sample_ech0196_statement1_xml), str(sample_ech0196_statement2_xml),
        "--target-currency", "CHF",
        "--log-level", "DEBUG"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode == 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}"
    assert output_xml_path.exists(), "Output XML file was not created."
    
    output_kursliste = parse_output_xml(output_xml_path)
    assert output_kursliste is not None, "Failed to parse output XML."

    # Expected valor numbers:
    # From cmd-line: 11223 (Fund EUR)
    # From statement1: 12345 (Share CHF), 54321 (not in KL)
    # From statement2: 67890 (Share USD)
    # Consolidated unique in KL: 11223, 12345, 67890

    # Expected currencies for definitions and rates:
    # Target: CHF
    # From cmd-line (via valor 11223 -> Fund EUR): EUR
    # From statement1: CHF (sec 12345), USD (sec 54321), EUR (bank acc)
    # From statement2: USD (sec 67890), JPY (bank acc)
    # Consolidated unique: CHF, EUR, USD, JPY

    # Verify shares
    assert output_kursliste.shares is not None, "Shares section is missing."
    found_share_valors = {s.valorNumber for s in output_kursliste.shares}
    assert 12345 in found_share_valors, "Share 12345 (from statement1) should be present."
    assert 67890 in found_share_valors, "Share 67890 (from statement2) should be present."
    assert len(output_kursliste.shares) == 2, "Incorrect number of shares found."

    # Verify funds
    assert output_kursliste.funds is not None, "Funds section is missing."
    found_fund_valors = {f.valorNumber for f in output_kursliste.funds}
    assert 11223 in found_fund_valors, "Fund 11223 (from cmd-line) should be present."
    assert len(output_kursliste.funds) == 1, "Incorrect number of funds found."

    assert not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty."

    # Verify DefinitionCurrency
    assert output_kursliste.currencies is not None, "DefinitionCurrencies are missing."
    found_def_currencies = {c.currency for c in output_kursliste.currencies}
    expected_def_currencies = {"CHF", "EUR", "USD", "JPY"}
    assert found_def_currencies == expected_def_currencies, \
        f"Expected definition currencies {expected_def_currencies}, found: {found_def_currencies}"

 
    # Verify Exchange Rates (target CHF)
    # Expected currencies needing rates to CHF: EUR, USD, JPY
    assert output_kursliste.exchangeRatesYearEnd is not None, "Year-end exchange rates missing."
    found_ye_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesYearEnd}
    assert "USD" in found_ye_rates_currencies
    assert "EUR" in found_ye_rates_currencies
    assert "JPY" in found_ye_rates_currencies
    
    # Check specific rate values from sample Kursliste
    usd_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "USD"), None)
    assert usd_ye_rate is not None
    assert usd_ye_rate.value == Decimal('0.90')
    eur_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "EUR"), None)
    assert eur_ye_rate is not None
    assert eur_ye_rate.value == Decimal('0.95')
    jpy_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "JPY"), None)
    assert jpy_ye_rate is not None
    assert jpy_ye_rate.value == Decimal('0.007')

    # Check monthly rates (EUR, USD are relevant)
    assert output_kursliste.exchangeRatesMonthly is not None
    found_m_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesMonthly}
    assert "EUR" in found_m_rates_currencies  # EUR from Fund 11223 & stmt1 bank acc
    assert "USD" in found_m_rates_currencies  # USD from Share 67890 & stmt1 sec 54321
    
    # Check daily rates (USD, EUR are relevant)
    assert output_kursliste.exchangeRates is not None
    found_d_rates_currencies = {er.currency for er in output_kursliste.exchangeRates}
    assert "USD" in found_d_rates_currencies  # From Share 67890 -> payment date 2023-07-20
    assert "EUR" in found_d_rates_currencies  # From Fund 11223 -> payment date 2023-03-10 (no daily rate for this in sample, but EUR is relevant)
                                             # The sample daily rates are USD@2023-07-20, EUR@2023-06-15
                                             # Since EUR is relevant, the EUR daily rate from sample KL should be pulled.


@pytest.mark.skip("Bonds currently filtered out in parser")
def test_include_bonds(temp_dir, sample_kursliste_xml):
    """Test filtering kursliste with the include bonds option."""
    args = [
        "--input-file", str(sample_kursliste_xml),
        "--valor-numbers", "33445",  # Test Bond CHF
        "--include-bonds",
        "--target-currency", "CHF",
        "--log-level", "DEBUG"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode == 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}"
    assert output_xml_path.exists(), "Output XML file was not created."
    
    output_kursliste = parse_output_xml(output_xml_path)
    assert output_kursliste is not None, "Failed to parse output XML."

    # Verify securities
    assert output_kursliste.bonds is not None, "Bonds section is missing."
    assert len(output_kursliste.bonds) == 1, "Incorrect number of bonds found."
    assert output_kursliste.bonds[0].valorNumber == 33445
    assert output_kursliste.bonds[0].currency == "CHF"
    
    assert not output_kursliste.shares or len(output_kursliste.shares) == 0, "Shares should be empty."
    assert not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty."

    # Verify DefinitionCurrency (CHF from bond and target)
    assert output_kursliste.currencies is not None, "DefinitionCurrencies are missing."
    found_currencies = {c.currency for c in output_kursliste.currencies}
    assert "CHF" in found_currencies, "CHF definition currency missing."
    assert len(found_currencies) == 1, "Expected only CHF definition currency."

    # Verify Country definitions (CH from bond 33445)
    assert output_kursliste.countries is not None, "Country definitions are missing."
    found_countries_iso = {c.country for c in output_kursliste.countries}
    assert "CH" in found_countries_iso, "CH country definition missing."
    
    # Verify Institution (inst1 from bond 33445)
    assert output_kursliste.institutions is not None
    assert any(inst.id == "inst1" for inst in output_kursliste.institutions)

    # Exchange rates should be empty for CHF target and CHF security
    assert not output_kursliste.exchangeRates or len(output_kursliste.exchangeRates) == 0
    assert not output_kursliste.exchangeRatesMonthly or len(output_kursliste.exchangeRatesMonthly) == 0
    assert not output_kursliste.exchangeRatesYearEnd or len(output_kursliste.exchangeRatesYearEnd) == 0


def test_exclude_bonds_by_default(temp_dir, sample_kursliste_xml):
    """Test that bonds are excluded by default."""
    args = [
        "--input-file", str(sample_kursliste_xml),
        "--valor-numbers", "33445",  # Test Bond CHF
        # --include-bonds is NOT specified
        "--target-currency", "CHF",
        "--log-level", "DEBUG"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode == 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}"
    assert output_xml_path.exists(), "Output XML file was not created."
    
    output_kursliste = parse_output_xml(output_xml_path)
    assert output_kursliste is not None, "Failed to parse output XML."

    # Verify securities - bonds should be empty
    assert not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty as --include-bonds was not used."
    assert not output_kursliste.shares or len(output_kursliste.shares) == 0, "Shares should be empty."
    assert not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty."
    
    # DefinitionCurrency should still contain CHF (target currency)
    assert output_kursliste.currencies is not None
    found_currencies = {c.currency for c in output_kursliste.currencies}
    assert "CHF" in found_currencies, "CHF definition currency (target) should be present."
    # No other currencies should be pulled in as no securities are kept.
    assert len(found_currencies) == 1, "Only CHF (target) definition should be present."


def test_no_matching_valors(temp_dir, sample_kursliste_xml):
    """Test filtering kursliste with no matching valor numbers."""
    args = [
        "--input-file", str(sample_kursliste_xml),
        "--valor-numbers", "99999,88888",  # Valors not in sample Kursliste
        "--target-currency", "EUR",  # Use a different target to check its definition
        "--log-level", "DEBUG"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode == 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}"
    assert output_xml_path.exists(), "Output XML file was not created."
    
    output_kursliste = parse_output_xml(output_xml_path)
    assert output_kursliste is not None, "Failed to parse output XML."

    # Verify no securities are present
    assert not output_kursliste.shares or len(output_kursliste.shares) == 0, "Shares should be empty."
    assert not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty."
    assert not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty."

    # Verify DefinitionCurrency (only target currency EUR should be present)
    assert output_kursliste.currencies is not None, "DefinitionCurrencies are missing."
    found_currencies = {c.currency for c in output_kursliste.currencies}
    assert "EUR" in found_currencies, "EUR definition currency (target) should be present."
    assert len(found_currencies) == 1, "Only EUR (target) definition should be present."

    # Verify Exchange Rates (only for EUR, the target currency)
    assert output_kursliste.exchangeRatesYearEnd is not None, "Year-end exchange rates missing."
    found_ye_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesYearEnd}
    assert "EUR" in found_ye_rates_currencies, "EUR year-end exchange rate to CHF should be present."
    assert len(found_ye_rates_currencies) == 1, "Only EUR year-end rates should be present."
    eur_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "EUR"), None)
    assert eur_ye_rate.value == Decimal('0.95')  # From sample_kursliste_for_filtering.xml

    assert output_kursliste.exchangeRatesMonthly is not None
    found_m_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesMonthly}
    assert "EUR" in found_m_rates_currencies, "EUR monthly exchange rate should be present."
    assert len(found_m_rates_currencies) == 1, "Only EUR monthly rates should be present."
    
    assert output_kursliste.exchangeRates is not None
    found_d_rates_currencies = {er.currency for er in output_kursliste.exchangeRates}
    assert "EUR" in found_d_rates_currencies, "EUR daily exchange rate should be present."
    assert len(found_d_rates_currencies) == 1, "Only EUR daily rates should be present."
    
    # Country and Institution lists should be empty as no securities are kept
    assert not output_kursliste.countries or len(output_kursliste.countries) == 0
    assert not output_kursliste.institutions or len(output_kursliste.institutions) == 0
    

def test_error_no_input_source(temp_dir, sample_kursliste_xml):
    """Test error when no input source is provided."""
    # Test without --valor-numbers and without --tax-statement-files
    args = [
        "--input-file", str(sample_kursliste_xml),
        # No --valor-numbers
        # No --tax-statement-files
        "--target-currency", "CHF",
        "--log-level", "ERROR"  # Keep log clean for error checking
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode != 0, "Script should exit with a non-zero return code when no input source is provided."
    # The script logs to stderr for this specific error, check for the message.
    # The script also prints "Parsed arguments" to stdout, then the error to stderr.
    # The main script's error message is: "Error: Either --valor-numbers or --tax-statement-files must be provided."
    # This message goes to logging, which by default for ERROR level goes to stderr.
    assert "Error: Either --valor-numbers or --tax-statement-files must be provided." in stderr, \
        f"Expected error message not found in stderr. Stderr:\n{stderr}"
    assert not output_xml_path.exists(), "Output XML file should not be created when no input source is provided."


def test_input_file_not_found(temp_dir):
    """Test error when input file is not found."""
    args = [
        "--input-file", "non_existent_kursliste.xml",
        "--valor-numbers", "12345",
        "--target-currency", "CHF",
        "--log-level", "ERROR"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)
    
    assert returncode != 0, "Script should exit with a non-zero return code for non-existent input file."
    assert not output_xml_path.exists(), "Output XML file should not be created."


def test_invalid_kursliste_xml(temp_dir, malformed_kursliste_xml):
    """Test error when kursliste XML is invalid."""
    args = [
        "--input-file", str(malformed_kursliste_xml),
        "--valor-numbers", "12345",  # Valor numbers are provided
        "--target-currency", "CHF",
        "--log-level", "ERROR"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode != 0, "Script should exit with a non-zero return code for malformed Kursliste XML."
    # The script should log an error related to XML parsing.
    # pydantic-xml might raise various exceptions; checking for a generic parsing error message.
    # The main script's error handling logs: "An unexpected error occurred: {e}"
    assert "An unexpected error occurred" in stderr, \
        f"Expected XML parsing error message not found in stderr. Stderr:\n{stderr}"
    assert not output_xml_path.exists(), "Output XML file should not be created for malformed input Kursliste."


def test_invalid_tax_statement_xml(temp_dir, sample_kursliste_xml, sample_ech0196_statement1_xml, malformed_ech0196_statement_xml):
    """Test error handling with valid and invalid tax statement XML files."""
    # Test with one valid and one malformed tax statement.
    # The script should process the valid one and skip the malformed one.
    args = [
        "--input-file", str(sample_kursliste_xml),
        "--tax-statement-files", str(sample_ech0196_statement1_xml), str(malformed_ech0196_statement_xml),
        "--target-currency", "CHF",
        "--log-level", "DEBUG"  # DEBUG to see all processing logs
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode == 0, f"Script should complete successfully even with a malformed tax statement, by skipping it. Stderr:\n{stderr}\nStdout:\n{stdout}"
    
    # Check stderr for the error message about the malformed tax statement
    expected_error_msg = f"Error parsing tax statement file {malformed_ech0196_statement_xml}"
    assert expected_error_msg in stderr, \
        f"Expected error message for malformed tax statement not found in stderr. Stderr:\n{stderr}"

    # Verify that the output XML was created and contains data from the valid tax statement
    assert output_xml_path.exists(), "Output XML file was not created."
    output_kursliste = parse_output_xml(output_xml_path)
    assert output_kursliste is not None, "Failed to parse output XML."

    # Check for security from the valid statement (sample_ech0196_statement1.xml -> valor 12345)
    assert output_kursliste.shares is not None, "Shares section is missing."
    found_share_valors = {s.valorNumber for s in output_kursliste.shares}
    assert 12345 in found_share_valors, "Share 12345 from valid tax statement should be present."
    
    # Check that no valor from the malformed statement (77777) is present, assuming it wouldn't be processed.
    assert 77777 not in found_share_valors, "Share from malformed tax statement should not be present."


def test_invalid_valor_number_format(temp_dir, sample_kursliste_xml):
    """Test error when an invalid valor number format is provided."""
    args = [
        "--input-file", str(sample_kursliste_xml),
        "--valor-numbers", "12345,abc,67890",  # Contains an invalid valor 'abc'
        "--target-currency", "CHF",
        "--log-level", "ERROR"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)

    assert returncode != 0, "Script should exit with a non-zero return code for invalid valor number format."
    # The script logs "Invalid valor number format from command line: 'abc'. Must be an integer."
    # And "Errors encountered while parsing command-line valor numbers. Exiting."
    assert "Invalid valor number format from command line: 'abc'" in stderr, \
        f"Expected invalid valor format message not found in stderr. Stderr:\n{stderr}"
    assert "Errors encountered while parsing command-line valor numbers. Exiting." in stderr, \
        f"Expected exiting message not found in stderr. Stderr:\n{stderr}"
    assert not output_xml_path.exists(), "Output XML file should not be created with invalid valor number format."


def test_target_currency_behavior(temp_dir, sample_kursliste_xml):
    """Test behavior with a target currency that requires specific exchange rates."""
    args = [
        "--input-file", str(sample_kursliste_xml),
        "--valor-numbers", "67890",  # Share USD
        "--target-currency", "USD",  # Target is USD
        "--log-level", "DEBUG"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)
    assert returncode == 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}"
    
    output_kursliste = parse_output_xml(output_xml_path)
    assert output_kursliste is not None, "Failed to parse output XML."

    # Security 67890 (USD) should be present
    assert output_kursliste.shares is not None
    assert len(output_kursliste.shares) == 1
    assert output_kursliste.shares[0].valorNumber == 67890
    assert output_kursliste.shares[0].currency == "USD"

    # Definition Currencies: USD (from security and target)
    assert output_kursliste.currencies is not None
    found_def_currencies = {c.currency for c in output_kursliste.currencies}
    assert found_def_currencies == {"USD"}

    # Exchange Rates: Since target is USD, and security is in USD,
    # no explicit exchange rates to USD are typically needed or listed if they are 1.0.
    # The sample Kursliste has rates to CHF.
    # If USD is target, all USD rates from Kursliste (which are to CHF usually) are still pulled if USD is in relevant_currencies.
    # This test checks if the script correctly identifies USD as relevant and pulls its rates.
    assert output_kursliste.exchangeRatesYearEnd is not None
    usd_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "USD"), None)
    assert usd_ye_rate is not None, "USD Year End rate should be present as USD is relevant."
    assert usd_ye_rate.value == Decimal('0.90')  # This is the USD to CHF rate from sample


def test_empty_input_kursliste(temp_dir):
    """Test behavior with an empty but valid Kursliste XML file."""
    # Create an empty but valid Kursliste XML
    empty_kursliste_content = """<?xml version="1.0" encoding="UTF-8"?>
<kursliste xmlns="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste" version="2.0.0.0" creationDate="2023-01-01T12:00:00" year="2023">
    <cantons>
        <canton id="1"><cantonShortcut>ZH</cantonShortcut><cantonName lang="de" name="Zürich"/></canton>
    </cantons>
    <currencies>
        <currency id="c1"><currencyName lang="de" name="Schweizer Franken"/><currency>CHF</currency></currency>
    </currencies>
    <countries/>
    <institutions/>
    <shares/>
    <funds/>
    <bonds/>
    <exchangeRatesYearEnd/>
    <exchangeRatesMonthly/>
    <exchangeRates/>
</kursliste>
"""
    empty_kursliste_path = temp_dir / "empty_kursliste.xml"
    with open(empty_kursliste_path, "w", encoding="utf-8") as f:
        f.write(empty_kursliste_content)

    args = [
        "--input-file", str(empty_kursliste_path),
        "--valor-numbers", "12345",  # Valor won't be found
        "--target-currency", "CHF",
        "--log-level", "DEBUG"
    ]
    output_xml_path, stdout, stderr, returncode = run_script(temp_dir, args)
    assert returncode == 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}"
    
    output_kursliste = parse_output_xml(output_xml_path)
    assert output_kursliste is not None, "Failed to parse output XML from empty input."

    # Expect empty securities lists
    assert not output_kursliste.shares or len(output_kursliste.shares) == 0
    assert not output_kursliste.funds or len(output_kursliste.funds) == 0
    assert not output_kursliste.bonds or len(output_kursliste.bonds) == 0

    # kursliste reader currently hard filters some elements for speed.
    # Expect definitions from the empty input to be copied (like cantons, CHF currency def)
    # assert output_kursliste.cantons is not None
    # assert len(output_kursliste.cantons) == 1
    # assert output_kursliste.currencies is not None
    # found_def_currencies = {c.currency for c in output_kursliste.currencies}
    # assert found_def_currencies == {"CHF"}  # CHF from input and target

    # Exchange rates should be empty as the input has none
    assert not output_kursliste.exchangeRatesYearEnd or len(output_kursliste.exchangeRatesYearEnd) == 0
