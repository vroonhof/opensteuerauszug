import typer
from enum import Enum
from pathlib import Path
from typing import List, Optional
from datetime import date, datetime

from opensteuerauszug.config.models import SchwabAccountSettings, IbkrAccountSettings # Added IbkrAccountSettings
import os # For path construction
from .core.identifier_loader import SecurityIdentifierMapLoader

# Use the generated eCH-0196 model
from .model.ech0196 import TaxStatement
# Import the rendering functionality
from .render.render import render_tax_statement
# Import calculation framework
from .calculate.base import CalculationMode
from .calculate.total import TotalCalculator
from .calculate.cleanup import CleanupCalculator
from .calculate.minimal_tax_value import MinimalTaxValueCalculator
from .calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from .calculate.fill_in_tax_value_calculator import FillInTaxValueCalculator
from .importers.schwab.schwab_importer import SchwabImporter
from .importers.ibkr.ibkr_importer import IbkrImporter # Added IbkrImporter
from .core.exchange_rate_provider import ExchangeRateProvider
from .core.kursliste_manager import KurslisteManager
from .core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from .config import ConfigManager, ConcreteAccountSettings

Portfolio = TaxStatement

app = typer.Typer()

class Phase(str, Enum):
    IMPORT = "import"
    VALIDATE = "validate"
    VERIFY = "verify"
    CALCULATE = "calculate"
    RENDER = "render"

class ImporterType(str, Enum):
    SCHWAB = "schwab"
    IBKR = "ibkr" # Added IBKR
    NONE = "none"

class TaxCalculationLevel(str, Enum):
    NONE = "None"
    MINIMAL = "Minimal"
    KURSLISTE = "Kursliste"
    FILL_IN = "Fill-In"

default_phases = [Phase.IMPORT, Phase.VALIDATE, Phase.CALCULATE, Phase.RENDER]

@app.command()
def main(
    input_file: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=True, readable=True, help="Input file (specific format depends on importer, or XML for raw) or directory (for Schwab importer)."),
    output_file: Path = typer.Option(None, "--output", "-o", help="Output PDF file path."),
    run_phases_input: List[Phase] = typer.Option(None, "--phases", "-p", help="Phases to run (default: all). Specify multiple times or comma-separated."),
    debug_dump_path: Optional[Path] = typer.Option(None, "--debug-dump", help="Directory to dump intermediate model state after each phase (as XML)."),
    raw_import: bool = typer.Option(False, "--raw-import", help="Import directly from XML model dump instead of using an importer."),
    importer_type: ImporterType = typer.Option(ImporterType.NONE, "--importer", help="Specify the importer to use."),
    period_from_str: Optional[str] = typer.Option(None, "--period-from", help="Start date of the tax period (YYYY-MM-DD), required for some importers like Schwab."),
    period_to_str: Optional[str] = typer.Option(None, "--period-to", help="End date of the tax period (YYYY-MM-DD), required for some importers like Schwab."),
    tax_year: Optional[int] = typer.Option(None, "--tax-year", help="Specify the tax year (e.g., 2023). If provided, period-from and period-to will default to the start/end of this year unless explicitly set. If period-from/to are set, they must fall within this tax year."),
    identifiers_csv_path_opt: Optional[str] = typer.Option(
        None,
        "--identifiers-csv-path",
        help="Path to the security identifiers CSV file (e.g., data/my_identifiers.csv). If not provided, defaults to 'data/security_identifiers.csv' relative to the project root."
    ),
    strict_consistency_flag: bool = typer.Option(True, "--strict-consistency/--no-strict-consistency", help="Enable/disable strict consistency checks in importers (e.g., Schwab). Defaults to strict."),
    filter_to_period_flag: bool = typer.Option(True, "--filter-to-period/--no-filter-to-period", help="Filter transactions and stock events to the tax period (with closing balances). Defaults to enabled."),
    tax_calculation_level: TaxCalculationLevel = typer.Option(TaxCalculationLevel.FILL_IN, "--tax-calculation-level", help="Specify the level of detail for tax value calculations."),
    config_file: Path = typer.Option("config.toml", "--config", "-c", help="Path to the configuration TOML file."),
    broker_name: Optional[str] = typer.Option(None, "--broker", help="Broker name (e.g., 'schwab') from config.toml to use for this run."),
    override_configs: List[str] = typer.Option(None, "--set", help="Override configuration settings using path.to.key=value format. Can be used multiple times."),
    kursliste_dir: Path = typer.Option(Path("data/kursliste"), "--kursliste-dir", help="Directory containing Kursliste XML files for exchange rate information. Defaults to 'data/kursliste'."),
    org_nr: Optional[str] = typer.Option(None, "--org-nr", help="Override the organization number used in barcodes (5-digit number)"),
):
    """Processes financial data to generate a Swiss tax statement (Steuerauszug)."""
    phases_specified_by_user = run_phases_input is not None
    run_phases = run_phases_input if phases_specified_by_user else default_phases[:]

    print(f"Starting OpenSteuerauszug processing...")
    print(f"Input file: {input_file}")
    # ... (rest of initial print statements and date parsing logic remains the same) ...
    parsed_period_from: Optional[date] = None
    parsed_period_to: Optional[date] = None

    temp_period_from: Optional[date] = None
    if period_from_str:
        try:
            temp_period_from = datetime.strptime(period_from_str, "%Y-%m-%d").date()
        except ValueError:
            raise typer.BadParameter(f"Invalid date format for --period-from: '{period_from_str}'. Expected YYYY-MM-DD.")

    temp_period_to: Optional[date] = None
    if period_to_str:
        try:
            temp_period_to = datetime.strptime(period_to_str, "%Y-%m-%d").date()
        except ValueError:
            raise typer.BadParameter(f"Invalid date format for --period-to: '{period_to_str}'. Expected YYYY-MM-DD.")

    if tax_year:
        print(f"Tax year specified: {tax_year}")
        year_start_date = date(tax_year, 1, 1)
        year_end_date = date(tax_year, 12, 31)

        if temp_period_from:
            if temp_period_from.year != tax_year:
                raise typer.BadParameter(f"--period-from date '{temp_period_from}' is not within the specified --tax-year '{tax_year}'.")
            parsed_period_from = temp_period_from
            print(f"Using explicit --period-from: {parsed_period_from}")
        else:
            parsed_period_from = year_start_date
            print(f"Defaulting --period-from to start of tax year: {parsed_period_from}")

        if temp_period_to:
            if temp_period_to.year != tax_year:
                raise typer.BadParameter(f"--period-to date '{temp_period_to}' is not within the specified --tax-year '{tax_year}'.")
            parsed_period_to = temp_period_to
            print(f"Using explicit --period-to: {parsed_period_to}")
        else:
            parsed_period_to = year_end_date
            print(f"Defaulting --period-to to end of tax year: {parsed_period_to}")
    else:
        parsed_period_from = temp_period_from
        parsed_period_to = temp_period_to
        if parsed_period_from:
            print(f"Using explicit --period-from: {parsed_period_from}")
        if parsed_period_to:
            print(f"Using explicit --period-to: {parsed_period_to}")

    if parsed_period_from and parsed_period_to and parsed_period_from > parsed_period_to:
        raise typer.BadParameter(f"--period-from '{parsed_period_from}' cannot be after --period-to '{parsed_period_to}'.")

    if parsed_period_from and parsed_period_to:
        print(f"Tax period: {parsed_period_from} to {parsed_period_to}")
    # ... (rest of date printing)

    # --- Configuration Loading ---
    all_schwab_account_settings_models: List[SchwabAccountSettings] = []
    all_ibkr_account_settings_models: List[IbkrAccountSettings] = [] # New list for IBKR
    config_manager = ConfigManager(config_file_path=str(config_file))

    target_broker_kind_for_config_loading = None
    if importer_type == ImporterType.SCHWAB:
        target_broker_kind_for_config_loading = "schwab"
    elif importer_type == ImporterType.IBKR:
        target_broker_kind_for_config_loading = "ibkr"
    elif broker_name:
        target_broker_kind_for_config_loading = broker_name.lower()
        print(f"Warning: --broker '{broker_name}' used with importer '{importer_type.value}'. Account settings will be loaded for '{target_broker_kind_for_config_loading}', ensure this is intended.")

    if target_broker_kind_for_config_loading:
        try:
            print(f"Loading all account configurations for broker kind '{target_broker_kind_for_config_loading}' from '{config_file}'...")
            if override_configs:
                print(f"Applying CLI overrides: {override_configs}")

            concrete_accounts_list = config_manager.get_all_account_settings_for_broker(
                target_broker_kind_for_config_loading,
                overrides=override_configs
            )
            
            if not concrete_accounts_list:
                print(f"No accounts configured for broker kind '{target_broker_kind_for_config_loading}' in {config_file}. Importer will proceed with defaults if possible.")

            for acc_settings in concrete_accounts_list:
                if acc_settings.kind == "schwab":
                    all_schwab_account_settings_models.append(acc_settings.settings)
                elif acc_settings.kind == "ibkr":
                    all_ibkr_account_settings_models.append(acc_settings.settings)
                else:
                    print(f"Warning: Received unhandled account configuration kind '{acc_settings.kind}' for broker '{target_broker_kind_for_config_loading}'. Skipping.")
            
            if target_broker_kind_for_config_loading == "schwab" and not all_schwab_account_settings_models and concrete_accounts_list:
                raise ValueError(f"No valid Schwab account configurations found for broker 'schwab', though other configurations might exist.")
            if target_broker_kind_for_config_loading == "ibkr" and not all_ibkr_account_settings_models and concrete_accounts_list:
                print(f"Warning: No valid IBKR account configurations loaded for broker 'ibkr', though other configurations might exist.")

            if all_schwab_account_settings_models:
                print(f"Successfully loaded {len(all_schwab_account_settings_models)} Schwab account(s).")
            if all_ibkr_account_settings_models:
                print(f"Successfully loaded {len(all_ibkr_account_settings_models)} IBKR account(s).")

        except ValueError as e:
            print(f"Error loading configuration: {e}")
            raise typer.Exit(code=1)
    else:
        print("No specific broker targeted by --importer or --broker for detailed configuration loading. Proceeding with general setup.")

    portfolio: Optional[Portfolio] = None

    def dump_debug_model(current_phase_str: str, model: Portfolio):
        if debug_dump_path and model:
            debug_dump_path.mkdir(parents=True, exist_ok=True)
            dump_file = debug_dump_path / f"portfolio_{current_phase_str}.xml"
            try:
                model.dump_debug_xml(str(dump_file))
                print(f"Debug model dumped to: {dump_file}")
            except Exception as e:
                print(f"Error dumping debug model to {dump_file}: {e}")

    if raw_import:
        # ... (raw_import logic remains the same) ...
        if Phase.IMPORT in run_phases:
            if phases_specified_by_user:
                 print("Warning: --phases includes 'import' but --raw-import is active. Loading directly from XML.")
            run_phases = [p for p in run_phases if p != Phase.IMPORT]

        print(f"Raw importing model from: {input_file}")
        try:
            if not input_file.is_file():
                raise typer.BadParameter(f"Raw import requires a file, but got a directory: {input_file}")
            portfolio = Portfolio.from_xml_file(str(input_file))
            print("Raw import complete.")
            dump_debug_model("raw_import", portfolio)
        except Exception as e:
            print(f"Error during raw XML import from {input_file}: {e}")
            raise typer.Exit(code=1)

        if not phases_specified_by_user:
            run_phases = []

        if not any(p in run_phases for p in [Phase.VALIDATE, Phase.CALCULATE, Phase.VERIFY, Phase.RENDER]):
             print("No further phases selected after raw import. Exiting.")
             return


    current_phase = None
    try:
        if Phase.IMPORT in run_phases and not raw_import:
            current_phase = Phase.IMPORT
            print(f"Phase: {current_phase.value}")

            if importer_type == ImporterType.SCHWAB:
                if not parsed_period_from or not parsed_period_to:
                    raise typer.BadParameter("--period-from and --period-to are required for the Schwab importer.")
                if not input_file.is_dir():
                    raise typer.BadParameter(f"Input for Schwab importer must be a directory, but got: {input_file}")
                if not all_schwab_account_settings_models:
                    print(f"Error: No valid Schwab account configurations loaded/found for broker 'schwab'. Check config.toml or provide --broker schwab if settings are under a different name.")
                    raise typer.Exit(code=1)
                print(f"Initializing SchwabImporter with {len(all_schwab_account_settings_models)} Schwab account configuration(s).")
                schwab_importer = SchwabImporter(
                    period_from=parsed_period_from,
                    period_to=parsed_period_to,
                    account_settings_list=all_schwab_account_settings_models,
                    strict_consistency=strict_consistency_flag
                )
                portfolio = schwab_importer.import_dir(str(input_file))
                print(f"Schwab import complete.")

            elif importer_type == ImporterType.IBKR:
                if not parsed_period_from or not parsed_period_to:
                    raise typer.BadParameter("--period-from and --period-to are required for the IBKR importer.")
                if not input_file.is_file():
                    raise typer.BadParameter(f"Input for IBKR importer must be an XML file, but got: {input_file}")

                if not all_ibkr_account_settings_models:
                    print("No specific IBKR account settings found/loaded from config. Using empty list for importer settings.")

                print(f"Initializing IbkrImporter with {len(all_ibkr_account_settings_models)} IBKR account configuration(s) (if any).")
                ibkr_importer = IbkrImporter(
                    period_from=parsed_period_from,
                    period_to=parsed_period_to,
                    account_settings_list=all_ibkr_account_settings_models
                )
                portfolio = ibkr_importer.import_files([str(input_file)])
                print(f"IBKR import complete.")

            elif importer_type == ImporterType.NONE and not raw_import:
                print("No specific importer selected, creating an empty TaxStatement for further processing.")
                portfolio = Portfolio(minorVersion=1) # Use minorVersion 1
            else:
                print(f"Importer '{importer_type.value}' not implemented or raw_import active. Creating empty TaxStatement.")
                portfolio = Portfolio(minorVersion=1) # Use minorVersion 1

            dump_debug_model(current_phase.value, portfolio)

        # ... (rest of the phases: VALIDATE, CALCULATE, VERIFY, RENDER remain the same) ...
        if Phase.VALIDATE in run_phases:
            current_phase = Phase.VALIDATE
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run validate phase.")
            portfolio.validate_model()
            print(f"Validation successful (placeholder check)." )
            dump_debug_model(current_phase.value, portfolio)

        if Phase.CALCULATE in run_phases:
            current_phase = Phase.CALCULATE
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run calculate phase.")
            
            effective_identifiers_csv_path: str
            if identifiers_csv_path_opt is None:
                cli_py_file_path = os.path.abspath(__file__)
                src_opensteuerauszug_dir = os.path.dirname(cli_py_file_path)
                src_dir = os.path.dirname(src_opensteuerauszug_dir)
                project_root_dir = os.path.dirname(src_dir)
                effective_identifiers_csv_path = os.path.join(project_root_dir, "data", "security_identifiers.csv")
                print(f"Using default security identifiers CSV path: {effective_identifiers_csv_path}")
            else:
                effective_identifiers_csv_path = identifiers_csv_path_opt
                print(f"Using user-provided security identifiers CSV path: {effective_identifiers_csv_path}")

            print(f"Attempting to load security identifiers from: {effective_identifiers_csv_path}")
            identifier_loader = SecurityIdentifierMapLoader(effective_identifiers_csv_path)
            security_identifier_map = identifier_loader.load_map()

            if security_identifier_map:
                print(f"Successfully loaded {len(security_identifier_map)} security identifiers.")
            else:
                print("Security identifier map not loaded or empty. Enrichment will be skipped.")
            
            print("Running CleanupCalculator...")
            cleanup_calculator = CleanupCalculator(
                period_from=parsed_period_from,
                period_to=parsed_period_to,
                identifier_map=security_identifier_map,
                enable_filtering=filter_to_period_flag,
                print_log=True,
                importer_name=importer_type.value
            )
            portfolio = cleanup_calculator.calculate(portfolio)
            print(f"CleanupCalculator finished. Summary: Modified fields count: {len(cleanup_calculator.modified_fields)}")
            dump_debug_model(current_phase.value + "_after_cleanup", portfolio)

            exchange_rate_provider: ExchangeRateProvider
            print(f"Using KurslisteExchangeRateProvider with directory: {kursliste_dir}")
            try:
                if not kursliste_dir.exists():
                    print(f"Warning: Kursliste directory {kursliste_dir} does not exist")
                kursliste_manager = KurslisteManager()
                kursliste_manager.load_directory(kursliste_dir)
                exchange_rate_provider = KurslisteExchangeRateProvider(kursliste_manager)
            except Exception as e:
                raise ValueError(f"Failed to initialize KurslisteExchangeRateProvider with directory {kursliste_dir}: {e}")
            
            tax_value_calculator: Optional[MinimalTaxValueCalculator] = None
            calculator_name = ""

            if tax_calculation_level == TaxCalculationLevel.MINIMAL:
                print("Running MinimalTaxValueCalculator...")
                calculator_name = "MinimalTaxValueCalculator"
                tax_value_calculator = MinimalTaxValueCalculator(mode=CalculationMode.OVERWRITE, exchange_rate_provider=exchange_rate_provider)
            elif tax_calculation_level == TaxCalculationLevel.KURSLISTE:
                print("Running KurslisteTaxValueCalculator...")
                calculator_name = "KurslisteTaxValueCalculator"
                tax_value_calculator = KurslisteTaxValueCalculator(mode=CalculationMode.OVERWRITE, exchange_rate_provider=exchange_rate_provider)
            elif tax_calculation_level == TaxCalculationLevel.FILL_IN:
                print("Running FillInTaxValueCalculator...")
                calculator_name = "FillInTaxValueCalculator"
                tax_value_calculator = FillInTaxValueCalculator(mode=CalculationMode.OVERWRITE, exchange_rate_provider=exchange_rate_provider)
            
            if tax_value_calculator and calculator_name:
                portfolio = tax_value_calculator.calculate(portfolio)
                print(f"{calculator_name} finished. Modified fields: {len(tax_value_calculator.modified_fields) if tax_value_calculator.modified_fields else '0'}, Errors: {len(tax_value_calculator.errors)}")
                dump_debug_model(current_phase.value + f"_after_{calculator_name.lower()}", portfolio)
            elif tax_calculation_level != TaxCalculationLevel.NONE:
                print(f"Warning: Tax calculation level '{tax_calculation_level.value}' was specified but no corresponding calculator was run.")
            else:
                print(f"Tax calculation level set to '{tax_calculation_level.value}', skipping detailed tax value calculation step.")

            if not portfolio:
                raise ValueError("Portfolio became None after cleanup phase. This should not happen.")
            calculator = TotalCalculator(mode=CalculationMode.OVERWRITE)
            portfolio = calculator.calculate(portfolio)
            print(f"TotalCalculator finished. Modified fields: {len(calculator.modified_fields) if calculator.modified_fields else '0'}")
            dump_debug_model(current_phase.value, portfolio)

        if Phase.VERIFY in run_phases:
            current_phase = Phase.VERIFY
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run calculate phase.")
            
            print(f"Verifying with tax calculation level: {tax_calculation_level.value}...")
            exchange_rate_provider_verify: ExchangeRateProvider
            print(f"Using KurslisteExchangeRateProvider with directory: {kursliste_dir} for verification")
            try:
                if not kursliste_dir.exists():
                    print(f"Warning: Kursliste directory {kursliste_dir} does not exist for verification.")
                    kursliste_dir.mkdir(parents=True, exist_ok=True)
                kursliste_manager_verify = KurslisteManager()
                kursliste_manager_verify.load_directory(kursliste_dir)
                exchange_rate_provider_verify = KurslisteExchangeRateProvider(kursliste_manager_verify)
            except Exception as e:
                raise ValueError(f"Failed to initialize KurslisteExchangeRateProvider for verification with directory {kursliste_dir}: {e}")
            
            tax_value_verifier: Optional[MinimalTaxValueCalculator] = None
            verifier_name = ""

            if tax_calculation_level == TaxCalculationLevel.MINIMAL:
                verifier_name = "MinimalTaxValueCalculator"
                tax_value_verifier = MinimalTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=exchange_rate_provider_verify)
            elif tax_calculation_level == TaxCalculationLevel.KURSLISTE:
                verifier_name = "KurslisteTaxValueCalculator"
                tax_value_verifier = KurslisteTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=exchange_rate_provider_verify)
            elif tax_calculation_level == TaxCalculationLevel.FILL_IN:
                verifier_name = "FillInTaxValueCalculator"
                tax_value_verifier = FillInTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=exchange_rate_provider_verify)

            if tax_value_verifier and verifier_name:
                print(f"Running {verifier_name} (Verify Mode)...")
                tax_value_verifier.calculate(portfolio)
                if tax_value_verifier.errors:
                    print(f"{verifier_name} (Verify Mode) encountered {len(tax_value_verifier.errors)} errors:")
                    for error in tax_value_verifier.errors:
                        print(f"  Error: {error}")
                else:
                    print(f"{verifier_name} (Verify Mode) found no errors.")
            elif tax_calculation_level != TaxCalculationLevel.NONE:
                print(f"Warning: Tax calculation level '{tax_calculation_level.value}' was specified but no corresponding verifier was run.")
            else:
                print(f"Tax calculation level set to '{tax_calculation_level.value}', skipping detailed tax value verification step.")

            calculator = TotalCalculator(mode=CalculationMode.VERIFY)
            calculator.calculate(portfolio)
            
            if calculator.errors:
                print(f"Encountered {len(calculator.errors)} fields during calculation")
                for error in calculator.errors:
                    print(f"Error: {error}")
            else:
                print("No errors calculation")
            
            calulator = TotalCalculator(mode=CalculationMode.FILL) # Renamed variable to avoid conflict
            portfolio = calulator.calculate(portfolio) # Use renamed variable
            print(f"Calculation successful.")
            dump_debug_model(current_phase.value, portfolio)

        if Phase.RENDER in run_phases:
            current_phase = Phase.RENDER
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run render phase.")
            if not output_file:
                 raise ValueError("Output file path must be specified for the render phase.")
            
            if org_nr is not None:
                if not isinstance(org_nr, str) or not org_nr.isdigit() or len(org_nr) != 5:
                    raise ValueError(f"Invalid --org-nr '{org_nr}': Must be a 5-digit string.")
            
            rendered_path = render_tax_statement(portfolio, output_file, override_org_nr=org_nr)
            print(f"Rendering successful to {rendered_path}")

        print("Processing finished successfully.")

    except Exception as e:
        print(f"Error during phase {current_phase.value if current_phase else 'startup'}: {e}")
        print("Stack trace:")
        import traceback
        traceback.print_exc(limit=3)
        if portfolio and debug_dump_path:
            error_phase_str = f"{current_phase.value}_error" if current_phase else "startup_error"
            try:
                dump_debug_model(error_phase_str, portfolio)
            except Exception as dump_e:
                print(f"Failed to dump debug model after error: {dump_e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
