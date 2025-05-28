import unittest
import tempfile
import os
import sys
from pathlib import Path
from subprocess import run, PIPE

# Add the script's directory to sys.path to allow direct import
# This assumes the test script is run from the repository root or a similar context
# where 'scripts' is a sibling directory or accessible.
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent)) # Add project root to import opensteuerauszug

from opensteuerauszug.model.kursliste import Kursliste as KurslisteModel
from pydantic_xml import from_xml

# Path to the script to be tested
FILTER_KURSLISTE_SCRIPT = SCRIPTS_DIR / "filter_kursliste.py"

class TestFilterKursliste(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir_path = Path(self.temp_dir.name)

        # Define paths to sample input files (now in tests/scripts/test_data relative to project root)
        self.sample_files_dir = Path(__file__).parent / "test_data" # Corrected base path for test data
        self.sample_kursliste_xml = self.sample_files_dir / "sample_kursliste_for_filtering.xml"
        self.sample_ech0196_statement1_xml = self.sample_files_dir / "sample_ech0196_statement1.xml"
        self.sample_ech0196_statement2_xml = self.sample_files_dir / "sample_ech0196_statement2.xml"
        self.malformed_kursliste_xml = self.sample_files_dir / "malformed_kursliste.xml"
        self.malformed_ech0196_statement_xml = self.sample_files_dir / "malformed_ech0196_statement.xml"

        # Ensure sample files exist
        for f_path in [
            self.sample_kursliste_xml, self.sample_ech0196_statement1_xml, 
            self.sample_ech0196_statement2_xml, self.malformed_kursliste_xml,
            self.malformed_ech0196_statement_xml
        ]:
            if not f_path.exists():
                raise FileNotFoundError(f"Test setup error: Sample file not found at {f_path}")


    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_script(self, args_list: list[str]) -> tuple[Path, str, str, int]:
        """
        Runs the filter_kursliste.py script with given arguments.
        Returns the path to the output file, stdout, stderr, and return code.
        """
        output_xml_path = self.temp_dir_path / "output_kursliste.xml"
        
        common_args = [
            sys.executable, # Python interpreter
            str(FILTER_KURSLISTE_SCRIPT),
            "--output-file", str(output_xml_path),
        ]
        
        cmd = common_args + args_list
        
        print(f"Running command: {' '.join(cmd)}") # For debugging tests
        
        result = run(cmd, capture_output=True, text=True, encoding='utf-8')
        
        return output_xml_path, result.stdout, result.stderr, result.returncode

    def _parse_output_xml(self, output_xml_path: Path) -> KurslisteModel | None:
        """Parses the output XML file into a KurslisteModel object."""
        if not output_xml_path.exists() or output_xml_path.stat().st_size == 0:
            return None
        try:
            return KurslisteModel.from_xml_file(str(output_xml_path))
        except Exception as e:
            print(f"Error parsing output XML {output_xml_path}: {e}")
            # Optionally, print file content for debugging
            # with open(output_xml_path, 'r', encoding='utf-8') as f:
            #     print(f.read())
            raise # Re-raise the exception to fail the test if parsing is crucial

    # Test cases will be added here
    def test_filter_by_cmd_line_valors_only(self):
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            "--valor-numbers", "12345", # Test Share CHF
            "--target-currency", "CHF",
            "--log-level", "DEBUG" # Use DEBUG for more verbose output during tests
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertEqual(returncode, 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}")
        self.assertTrue(output_xml_path.exists(), "Output XML file was not created.")
        
        output_kursliste = self._parse_output_xml(output_xml_path)
        self.assertIsNotNone(output_kursliste, "Failed to parse output XML.")

        # Verify securities
        self.assertIsNotNone(output_kursliste.shares, "Shares section is missing.")
        self.assertEqual(len(output_kursliste.shares), 1, "Incorrect number of shares found.")
        self.assertEqual(output_kursliste.shares[0].valorNumber, 12345)
        self.assertEqual(output_kursliste.shares[0].currency, "CHF")
        
        self.assertTrue(not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty.")
        self.assertTrue(not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty.")

        # Verify DefinitionCurrency
        # Expect CHF (from security) and target_currency (CHF)
        self.assertIsNotNone(output_kursliste.currencies, "DefinitionCurrencies are missing.")
        found_currencies = {c.currency for c in output_kursliste.currencies}
        self.assertIn("CHF", found_currencies, "CHF definition currency missing.")
        # Only CHF should be present as no other currency is referenced by kept securities or target
        self.assertEqual(len(found_currencies), 1, f"Expected only CHF definition currency, found: {found_currencies}")

        # Verify Country definitions
        # Expect CH (from security 12345)
        self.assertIsNotNone(output_kursliste.countries, "Country definitions are missing.")
        found_countries_iso = {c.country for c in output_kursliste.countries}
        self.assertIn("CH", found_countries_iso, "CH country definition missing.")
        # Check if institution 'inst1' (country CH) is kept, which it should be.
        self.assertIsNotNone(output_kursliste.institutions)
        self.assertTrue(any(inst.id == "inst1" for inst in output_kursliste.institutions))


        # Verify Exchange Rates (target CHF, security CHF -> effectively no explicit rates needed beyond definition)
        # For CHF target, rates to CHF are 1.0 and usually implicit or not listed as separate entries unless it's a cross-rate.
        # The script keeps ExchangeRate* entries if their currency symbol is in relevant_currencies.
        # Since only CHF is relevant here, and Kursliste has no CHF-to-CHF rates, these lists should be empty/None.
        self.assertTrue(not output_kursliste.exchangeRates or len(output_kursliste.exchangeRates) == 0, 
                        f"Daily exchange rates should be empty for CHF->CHF. Found: {len(output_kursliste.exchangeRates) if output_kursliste.exchangeRates else 0}")
        self.assertTrue(not output_kursliste.exchangeRatesMonthly or len(output_kursliste.exchangeRatesMonthly) == 0,
                        f"Monthly exchange rates should be empty for CHF->CHF. Found: {len(output_kursliste.exchangeRatesMonthly) if output_kursliste.exchangeRatesMonthly else 0}")
        self.assertTrue(not output_kursliste.exchangeRatesYearEnd or len(output_kursliste.exchangeRatesYearEnd) == 0,
                        f"Year-end exchange rates should be empty for CHF->CHF. Found: {len(output_kursliste.exchangeRatesYearEnd) if output_kursliste.exchangeRatesYearEnd else 0}")

        # Check pretty printing (basic check for newlines)
        with open(output_xml_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("\n", content, "Output XML is not pretty-printed (missing newlines).")
        self.assertTrue(content.count("\n") > 5, "Output XML seems not pretty-printed (too few newlines).")

    def test_filter_by_tax_statement_valors_only(self):
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            "--tax-statement-files", str(self.sample_ech0196_statement1_xml),
            "--target-currency", "CHF", # Important for exchange rate selection
            "--log-level", "DEBUG"
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertEqual(returncode, 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}")
        self.assertTrue(output_xml_path.exists(), "Output XML file was not created.")
        
        output_kursliste = self._parse_output_xml(output_xml_path)
        self.assertIsNotNone(output_kursliste, "Failed to parse output XML.")

        # Expected valors from statement1.xml: 12345 (Share CHF), 54321 (not in Kursliste)
        # Expected currencies from statement1.xml: CHF (from sec 12345), USD (from sec 54321), EUR (from bank account)
        # Target currency is CHF.

        # Verify securities
        self.assertIsNotNone(output_kursliste.shares, "Shares section is missing.")
        found_share_valors = {s.valorNumber for s in output_kursliste.shares}
        self.assertIn(12345, found_share_valors, "Share 12345 should be present.")
        self.assertNotIn(54321, found_share_valors, "Share 54321 should not be present as it's not in Kursliste.")
        self.assertEqual(len(output_kursliste.shares), 1, "Incorrect number of shares found.")
        
        self.assertTrue(not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty.")
        self.assertTrue(not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty.")

        # Verify DefinitionCurrency (CHF from sec 12345, USD from sec 54321 in tax statement, EUR from bank account in tax statement)
        # All these should be included because they are found in tax statements or target.
        self.assertIsNotNone(output_kursliste.currencies, "DefinitionCurrencies are missing.")
        found_def_currencies = {c.currency for c in output_kursliste.currencies}
        expected_def_currencies = {"CHF", "USD", "EUR"} # CHF (target/security), USD (tax statement sec), EUR (tax statement bank acc)
        self.assertEqual(found_def_currencies, expected_def_currencies, 
                         f"Expected definition currencies {expected_def_currencies}, found: {found_def_currencies}")

        # Verify Country definitions
        # CH from Share 12345. US from statement security 54321 (not in KL, so its country def might not be pulled unless institution is).
        # Institution 'inst1' (country CH) for Share 12345.
        self.assertIsNotNone(output_kursliste.countries, "Country definitions are missing.")
        found_countries_iso = {c.country for c in output_kursliste.countries}
        self.assertIn("CH", found_countries_iso, "CH country definition missing (from Share 12345).")
        # The script logic: relevant_country_codes.add(sec.country) for *filtered* securities.
        # Inst countries are added from *filtered* institutions.
        # Security 54321 is not in Kursliste, so it won't be a filtered security. Its country 'US' won't be added from it directly.
        # It depends if any other mechanism (like an institution related to 54321 if it were in KL) would pull 'US'.
        # In this specific case, only CH from the kept Share 12345 and its institution inst1 (CH) are expected.
        self.assertEqual(len(found_countries_iso), 1, f"Expected only CH country, found {found_countries_iso}")


        # Verify Exchange Rates (target CHF)
        # Expected currencies needing rates to CHF: USD, EUR (from tax statement)
        self.assertIsNotNone(output_kursliste.exchangeRatesYearEnd, "Year-end exchange rates missing.")
        found_ye_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesYearEnd}
        self.assertIn("USD", found_ye_rates_currencies, "USD year-end exchange rate to CHF missing.")
        self.assertIn("EUR", found_ye_rates_currencies, "EUR year-end exchange rate to CHF missing.")
        # JPY was in sample Kursliste but not referenced by tax statement or target.
        self.assertNotIn("JPY", found_ye_rates_currencies, "JPY year-end exchange rate should not be present.")

        # Check one USD rate value
        usd_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "USD"), None)
        self.assertIsNotNone(usd_ye_rate)
        self.assertEqual(usd_ye_rate.value, 0.90) # From sample_kursliste_for_filtering.xml

        # Check monthly rates (EUR is relevant from tax statement bank account)
        self.assertIsNotNone(output_kursliste.exchangeRatesMonthly)
        found_m_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesMonthly}
        self.assertIn("EUR", found_m_rates_currencies, "EUR monthly exchange rate should be present.")
        # USD was in sample Kursliste monthly, but not specifically referenced for a monthly context by tax data.
        # The logic is: if 'EUR' is a relevant_currency, all 'EUR' rates are pulled.
        self.assertIn("USD", found_m_rates_currencies, "USD monthly exchange rate should be present as USD is relevant.")

        # Check daily rates (USD is relevant from tax statement security)
        self.assertIsNotNone(output_kursliste.exchangeRates)
        found_d_rates_currencies = {er.currency for er in output_kursliste.exchangeRates}
        self.assertIn("USD", found_d_rates_currencies, "USD daily exchange rate should be present.")

    def test_filter_by_union_valors_and_currencies(self):
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            "--valor-numbers", "11223", # Fund EUR from Kursliste
            "--tax-statement-files", str(self.sample_ech0196_statement1_xml), str(self.sample_ech0196_statement2_xml),
            "--target-currency", "CHF",
            "--log-level", "DEBUG"
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertEqual(returncode, 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}")
        self.assertTrue(output_xml_path.exists(), "Output XML file was not created.")
        
        output_kursliste = self._parse_output_xml(output_xml_path)
        self.assertIsNotNone(output_kursliste, "Failed to parse output XML.")

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
        self.assertIsNotNone(output_kursliste.shares, "Shares section is missing.")
        found_share_valors = {s.valorNumber for s in output_kursliste.shares}
        self.assertIn(12345, found_share_valors, "Share 12345 (from statement1) should be present.")
        self.assertIn(67890, found_share_valors, "Share 67890 (from statement2) should be present.")
        self.assertEqual(len(output_kursliste.shares), 2, "Incorrect number of shares found.")

        # Verify funds
        self.assertIsNotNone(output_kursliste.funds, "Funds section is missing.")
        found_fund_valors = {f.valorNumber for f in output_kursliste.funds}
        self.assertIn(11223, found_fund_valors, "Fund 11223 (from cmd-line) should be present.")
        self.assertEqual(len(output_kursliste.funds), 1, "Incorrect number of funds found.")

        self.assertTrue(not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty.")

        # Verify DefinitionCurrency
        self.assertIsNotNone(output_kursliste.currencies, "DefinitionCurrencies are missing.")
        found_def_currencies = {c.currency for c in output_kursliste.currencies}
        expected_def_currencies = {"CHF", "EUR", "USD", "JPY"}
        self.assertEqual(found_def_currencies, expected_def_currencies,
                         f"Expected definition currencies {expected_def_currencies}, found: {found_def_currencies}")

        # Verify Country definitions
        # Share 12345 (CH, inst1 CH), Share 67890 (US, inst2 US), Fund 11223 (LU, inst2 US)
        # Expected countries: CH, US, LU
        self.assertIsNotNone(output_kursliste.countries, "Country definitions are missing.")
        found_countries_iso = {c.country for c in output_kursliste.countries}
        expected_countries_iso = {"CH", "US", "LU"}
        self.assertEqual(found_countries_iso, expected_countries_iso,
                         f"Expected countries {expected_countries_iso}, found: {found_countries_iso}")
        
        # Verify Institutions
        # inst1 (from Share 12345), inst2 (from Share 67890 and Fund 11223)
        self.assertIsNotNone(output_kursliste.institutions)
        found_institution_ids = {inst.id for inst in output_kursliste.institutions}
        expected_institution_ids = {"inst1", "inst2"}
        self.assertEqual(found_institution_ids, expected_institution_ids)


        # Verify Exchange Rates (target CHF)
        # Expected currencies needing rates to CHF: EUR, USD, JPY
        self.assertIsNotNone(output_kursliste.exchangeRatesYearEnd, "Year-end exchange rates missing.")
        found_ye_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesYearEnd}
        self.assertIn("USD", found_ye_rates_currencies)
        self.assertIn("EUR", found_ye_rates_currencies)
        self.assertIn("JPY", found_ye_rates_currencies) 
        
        # Check specific rate values from sample Kursliste
        usd_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "USD"), None)
        self.assertEqual(usd_ye_rate.value, 0.90)
        eur_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "EUR"), None)
        self.assertEqual(eur_ye_rate.value, 0.95)
        jpy_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "JPY"), None)
        self.assertEqual(jpy_ye_rate.value, 0.007)

        # Check monthly rates (EUR, USD are relevant)
        self.assertIsNotNone(output_kursliste.exchangeRatesMonthly)
        found_m_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesMonthly}
        self.assertIn("EUR", found_m_rates_currencies) # EUR from Fund 11223 & stmt1 bank acc
        self.assertIn("USD", found_m_rates_currencies) # USD from Share 67890 & stmt1 sec 54321
        
        # Check daily rates (USD, EUR are relevant)
        self.assertIsNotNone(output_kursliste.exchangeRates)
        found_d_rates_currencies = {er.currency for er in output_kursliste.exchangeRates}
        self.assertIn("USD", found_d_rates_currencies) # From Share 67890 -> payment date 2023-07-20
        self.assertIn("EUR", found_d_rates_currencies) # From Fund 11223 -> payment date 2023-03-10 (no daily rate for this in sample, but EUR is relevant)
                                                      # The sample daily rates are USD@2023-07-20, EUR@2023-06-15
                                                      # Since EUR is relevant, the EUR daily rate from sample KL should be pulled.

    def test_include_bonds(self):
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            "--valor-numbers", "33445", # Test Bond CHF
            "--include-bonds",
            "--target-currency", "CHF",
            "--log-level", "DEBUG"
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertEqual(returncode, 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}")
        self.assertTrue(output_xml_path.exists(), "Output XML file was not created.")
        
        output_kursliste = self._parse_output_xml(output_xml_path)
        self.assertIsNotNone(output_kursliste, "Failed to parse output XML.")

        # Verify securities
        self.assertIsNotNone(output_kursliste.bonds, "Bonds section is missing.")
        self.assertEqual(len(output_kursliste.bonds), 1, "Incorrect number of bonds found.")
        self.assertEqual(output_kursliste.bonds[0].valorNumber, 33445)
        self.assertEqual(output_kursliste.bonds[0].currency, "CHF")
        
        self.assertTrue(not output_kursliste.shares or len(output_kursliste.shares) == 0, "Shares should be empty.")
        self.assertTrue(not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty.")

        # Verify DefinitionCurrency (CHF from bond and target)
        self.assertIsNotNone(output_kursliste.currencies, "DefinitionCurrencies are missing.")
        found_currencies = {c.currency for c in output_kursliste.currencies}
        self.assertIn("CHF", found_currencies, "CHF definition currency missing.")
        self.assertEqual(len(found_currencies), 1, "Expected only CHF definition currency.")

        # Verify Country definitions (CH from bond 33445)
        self.assertIsNotNone(output_kursliste.countries, "Country definitions are missing.")
        found_countries_iso = {c.country for c in output_kursliste.countries}
        self.assertIn("CH", found_countries_iso, "CH country definition missing.")
        
        # Verify Institution (inst1 from bond 33445)
        self.assertIsNotNone(output_kursliste.institutions)
        self.assertTrue(any(inst.id == "inst1" for inst in output_kursliste.institutions))

        # Exchange rates should be empty for CHF target and CHF security
        self.assertTrue(not output_kursliste.exchangeRates or len(output_kursliste.exchangeRates) == 0)
        self.assertTrue(not output_kursliste.exchangeRatesMonthly or len(output_kursliste.exchangeRatesMonthly) == 0)
        self.assertTrue(not output_kursliste.exchangeRatesYearEnd or len(output_kursliste.exchangeRatesYearEnd) == 0)

    def test_exclude_bonds_by_default(self):
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            "--valor-numbers", "33445", # Test Bond CHF
            # --include-bonds is NOT specified
            "--target-currency", "CHF",
            "--log-level", "DEBUG"
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertEqual(returncode, 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}")
        self.assertTrue(output_xml_path.exists(), "Output XML file was not created.")
        
        output_kursliste = self._parse_output_xml(output_xml_path)
        self.assertIsNotNone(output_kursliste, "Failed to parse output XML.")

        # Verify securities - bonds should be empty
        self.assertTrue(not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty as --include-bonds was not used.")
        self.assertTrue(not output_kursliste.shares or len(output_kursliste.shares) == 0, "Shares should be empty.")
        self.assertTrue(not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty.")
        
        # DefinitionCurrency should still contain CHF (target currency)
        self.assertIsNotNone(output_kursliste.currencies)
        found_currencies = {c.currency for c in output_kursliste.currencies}
        self.assertIn("CHF", found_currencies, "CHF definition currency (target) should be present.")
        # No other currencies should be pulled in as no securities are kept.
        self.assertEqual(len(found_currencies), 1, "Only CHF (target) definition should be present.")

    def test_no_matching_valors(self):
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            "--valor-numbers", "99999,88888", # Valors not in sample Kursliste
            "--target-currency", "EUR", # Use a different target to check its definition
            "--log-level", "DEBUG"
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertEqual(returncode, 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}")
        self.assertTrue(output_xml_path.exists(), "Output XML file was not created.")
        
        output_kursliste = self._parse_output_xml(output_xml_path)
        self.assertIsNotNone(output_kursliste, "Failed to parse output XML.")

        # Verify no securities are present
        self.assertTrue(not output_kursliste.shares or len(output_kursliste.shares) == 0, "Shares should be empty.")
        self.assertTrue(not output_kursliste.funds or len(output_kursliste.funds) == 0, "Funds should be empty.")
        self.assertTrue(not output_kursliste.bonds or len(output_kursliste.bonds) == 0, "Bonds should be empty.")

        # Verify DefinitionCurrency (only target currency EUR should be present)
        self.assertIsNotNone(output_kursliste.currencies, "DefinitionCurrencies are missing.")
        found_currencies = {c.currency for c in output_kursliste.currencies}
        self.assertIn("EUR", found_currencies, "EUR definition currency (target) should be present.")
        self.assertEqual(len(found_currencies), 1, "Only EUR (target) definition should be present.")

        # Verify Exchange Rates (only for EUR, the target currency)
        self.assertIsNotNone(output_kursliste.exchangeRatesYearEnd, "Year-end exchange rates missing.")
        found_ye_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesYearEnd}
        self.assertIn("EUR", found_ye_rates_currencies, "EUR year-end exchange rate to CHF should be present.")
        self.assertEqual(len(found_ye_rates_currencies), 1, "Only EUR year-end rates should be present.")
        eur_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "EUR"), None)
        self.assertEqual(eur_ye_rate.value, 0.95) # From sample_kursliste_for_filtering.xml

        self.assertIsNotNone(output_kursliste.exchangeRatesMonthly)
        found_m_rates_currencies = {er.currency for er in output_kursliste.exchangeRatesMonthly}
        self.assertIn("EUR", found_m_rates_currencies, "EUR monthly exchange rate should be present.")
        self.assertEqual(len(found_m_rates_currencies), 1, "Only EUR monthly rates should be present.")
        
        self.assertIsNotNone(output_kursliste.exchangeRates)
        found_d_rates_currencies = {er.currency for er in output_kursliste.exchangeRates}
        self.assertIn("EUR", found_d_rates_currencies, "EUR daily exchange rate should be present.")
        self.assertEqual(len(found_d_rates_currencies), 1, "Only EUR daily rates should be present.")
        
        # Country and Institution lists should be empty as no securities are kept
        self.assertTrue(not output_kursliste.countries or len(output_kursliste.countries) == 0)
        self.assertTrue(not output_kursliste.institutions or len(output_kursliste.institutions) == 0)
        
        # Check that other definitional elements (e.g., cantons) are still copied
        self.assertIsNotNone(output_kursliste.cantons)
        self.assertTrue(len(output_kursliste.cantons) > 0, "Cantons should be copied from source.")

    def test_error_no_input_source(self):
        # Test without --valor-numbers and without --tax-statement-files
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            # No --valor-numbers
            # No --tax-statement-files
            "--target-currency", "CHF",
            "--log-level", "ERROR" # Keep log clean for error checking
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertNotEqual(returncode, 0, "Script should exit with a non-zero return code when no input source is provided.")
        # The script logs to stderr for this specific error, check for the message.
        # The script also prints "Parsed arguments" to stdout, then the error to stderr.
        # The main script's error message is: "Error: Either --valor-numbers or --tax-statement-files must be provided."
        # This message goes to logging, which by default for ERROR level goes to stderr.
        self.assertIn("Error: Either --valor-numbers or --tax-statement-files must be provided.", stderr, 
                      f"Expected error message not found in stderr. Stderr:\n{stderr}")
        self.assertFalse(output_xml_path.exists(), "Output XML file should not be created when no input source is provided.")

    def test_input_file_not_found(self):
        args = [
            "--input-file", "non_existent_kursliste.xml",
            "--valor-numbers", "12345",
            "--target-currency", "CHF",
            "--log-level", "ERROR"
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)
        
        self.assertNotEqual(returncode, 0, "Script should exit with a non-zero return code for non-existent input file.")
        # The script logs "Error: Input file not found at..." to stderr.
        self.assertIn("Error: Input file not found at non_existent_kursliste.xml", stderr,
                      f"Expected file not found message in stderr. Stderr:\n{stderr}")
        self.assertFalse(output_xml_path.exists(), "Output XML file should not be created.")

    def test_invalid_kursliste_xml(self):
        args = [
            "--input-file", str(self.malformed_kursliste_xml),
            "--valor-numbers", "12345", # Valor numbers are provided
            "--target-currency", "CHF",
            "--log-level", "ERROR"
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertNotEqual(returncode, 0, "Script should exit with a non-zero return code for malformed Kursliste XML.")
        # The script should log an error related to XML parsing.
        # pydantic-xml might raise various exceptions; checking for a generic parsing error message.
        # The main script's error handling logs: "An unexpected error occurred: {e}"
        self.assertIn("An unexpected error occurred", stderr,
                      f"Expected XML parsing error message not found in stderr. Stderr:\n{stderr}")
        self.assertFalse(output_xml_path.exists(), "Output XML file should not be created for malformed input Kursliste.")

    def test_invalid_tax_statement_xml(self):
        # Test with one valid and one malformed tax statement.
        # The script should process the valid one and skip the malformed one.
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            "--tax-statement-files", str(self.sample_ech0196_statement1_xml), str(self.malformed_ech0196_statement_xml),
            "--target-currency", "CHF",
            "--log-level", "DEBUG" # DEBUG to see all processing logs
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertEqual(returncode, 0, f"Script should complete successfully even with a malformed tax statement, by skipping it. Stderr:\n{stderr}\nStdout:\n{stdout}")
        
        # Check stderr for the error message about the malformed tax statement
        expected_error_msg = f"Error parsing tax statement file {self.malformed_ech0196_statement_xml}"
        self.assertIn(expected_error_msg, stderr, 
                      f"Expected error message for malformed tax statement not found in stderr. Stderr:\n{stderr}")

        # Verify that the output XML was created and contains data from the valid tax statement
        self.assertTrue(output_xml_path.exists(), "Output XML file was not created.")
        output_kursliste = self._parse_output_xml(output_xml_path)
        self.assertIsNotNone(output_kursliste, "Failed to parse output XML.")

        # Check for security from the valid statement (sample_ech0196_statement1.xml -> valor 12345)
        self.assertIsNotNone(output_kursliste.shares, "Shares section is missing.")
        found_share_valors = {s.valorNumber for s in output_kursliste.shares}
        self.assertIn(12345, found_share_valors, "Share 12345 from valid tax statement should be present.")
        
        # Check that no valor from the malformed statement (77777) is present, assuming it wouldn't be processed.
        self.assertNotIn(77777, found_share_valors, "Share from malformed tax statement should not be present.")

    def test_invalid_valor_number_format(self):
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            "--valor-numbers", "12345,abc,67890", # Contains an invalid valor 'abc'
            "--target-currency", "CHF",
            "--log-level", "ERROR" 
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)

        self.assertNotEqual(returncode, 0, "Script should exit with a non-zero return code for invalid valor number format.")
        # The script logs "Invalid valor number format from command line: 'abc'. Must be an integer."
        # And "Errors encountered while parsing command-line valor numbers. Exiting."
        self.assertIn("Invalid valor number format from command line: 'abc'", stderr,
                      f"Expected invalid valor format message not found in stderr. Stderr:\n{stderr}")
        self.assertIn("Errors encountered while parsing command-line valor numbers. Exiting.", stderr,
                      f"Expected exiting message not found in stderr. Stderr:\n{stderr}")
        self.assertFalse(output_xml_path.exists(), "Output XML file should not be created with invalid valor number format.")

    def test_target_currency_behavior(self):
        # Test with a target currency that requires specific exchange rates
        args = [
            "--input-file", str(self.sample_kursliste_xml),
            "--valor-numbers", "67890", # Share USD
            "--target-currency", "USD", # Target is USD
            "--log-level", "DEBUG"
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)
        self.assertEqual(returncode, 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}")
        
        output_kursliste = self._parse_output_xml(output_xml_path)
        self.assertIsNotNone(output_kursliste, "Failed to parse output XML.")

        # Security 67890 (USD) should be present
        self.assertIsNotNone(output_kursliste.shares)
        self.assertEqual(len(output_kursliste.shares), 1)
        self.assertEqual(output_kursliste.shares[0].valorNumber, 67890)
        self.assertEqual(output_kursliste.shares[0].currency, "USD")

        # Definition Currencies: USD (from security and target)
        self.assertIsNotNone(output_kursliste.currencies)
        found_def_currencies = {c.currency for c in output_kursliste.currencies}
        self.assertEqual(found_def_currencies, {"USD"})

        # Exchange Rates: Since target is USD, and security is in USD,
        # no explicit exchange rates to USD are typically needed or listed if they are 1.0.
        # The sample Kursliste has rates to CHF.
        # If USD is target, all USD rates from Kursliste (which are to CHF usually) are still pulled if USD is in relevant_currencies.
        # This test checks if the script correctly identifies USD as relevant and pulls its rates.
        self.assertIsNotNone(output_kursliste.exchangeRatesYearEnd)
        usd_ye_rate = next((r for r in output_kursliste.exchangeRatesYearEnd if r.currency == "USD"), None)
        self.assertIsNotNone(usd_ye_rate, "USD Year End rate should be present as USD is relevant.")
        self.assertEqual(usd_ye_rate.value, 0.90) # This is the USD to CHF rate from sample

    def test_empty_input_kursliste(self):
        # Create an empty but valid Kursliste XML
        empty_kursliste_content = """<?xml version="1.0" encoding="UTF-8"?>
<kursliste xmlns="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste" version="2.0.0.0" creationDate="2023-01-01T12:00:00" datum="2023-12-31">
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
        empty_kursliste_path = self.temp_dir_path / "empty_kursliste.xml"
        with open(empty_kursliste_path, "w", encoding="utf-8") as f:
            f.write(empty_kursliste_content)

        args = [
            "--input-file", str(empty_kursliste_path),
            "--valor-numbers", "12345", # Valor won't be found
            "--target-currency", "CHF",
            "--log-level", "DEBUG"
        ]
        output_xml_path, stdout, stderr, returncode = self._run_script(args)
        self.assertEqual(returncode, 0, f"Script failed with stderr:\n{stderr}\nstdout:\n{stdout}")
        
        output_kursliste = self._parse_output_xml(output_xml_path)
        self.assertIsNotNone(output_kursliste, "Failed to parse output XML from empty input.")

        # Expect empty securities lists
        self.assertTrue(not output_kursliste.shares or len(output_kursliste.shares) == 0)
        self.assertTrue(not output_kursliste.funds or len(output_kursliste.funds) == 0)
        self.assertTrue(not output_kursliste.bonds or len(output_kursliste.bonds) == 0)

        # Expect definitions from the empty input to be copied (like cantons, CHF currency def)
        self.assertIsNotNone(output_kursliste.cantons)
        self.assertEqual(len(output_kursliste.cantons), 1)
        self.assertIsNotNone(output_kursliste.currencies)
        found_def_currencies = {c.currency for c in output_kursliste.currencies}
        self.assertEqual(found_def_currencies, {"CHF"}) # CHF from input and target

        # Exchange rates should be empty as the input has none
        self.assertTrue(not output_kursliste.exchangeRatesYearEnd or len(output_kursliste.exchangeRatesYearEnd) == 0)


if __name__ == "__main__":
    unittest.main()
