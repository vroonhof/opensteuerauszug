import logging
import typer
import sys
from enum import Enum
from pathlib import Path
from typing import List, Optional
from datetime import date, datetime
from pypdf import PdfReader, PdfWriter

from opensteuerauszug.config.models import SchwabAccountSettings, IbkrAccountSettings, GeneralSettings # Added GeneralSettings
import os # For path construction
from .core.identifier_loader import SecurityIdentifierMapLoader

# Use the generated eCH-0196 model
from .model.ech0196 import TaxStatement, Client, ClientNumber, Institution
# Import the rendering functionality
from .render.render import render_tax_statement
# Import calculation framework
from .calculate.base import CalculationMode
from .calculate.total import TotalCalculator
from .calculate.cleanup import CleanupCalculator
from .calculate.minimal_tax_value import MinimalTaxValueCalculator
from .calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from .calculate.fill_in_tax_value_calculator import FillInTaxValueCalculator
from .calculate.payment_reconciliation_calculator import PaymentReconciliationCalculator
from .util.known_issues import is_known_issue
from .importers.schwab.schwab_importer import SchwabImporter
from .importers.ibkr.ibkr_importer import IbkrImporter # Added IbkrImporter
from .core.exchange_rate_provider import ExchangeRateProvider
from .core.kursliste_manager import KurslisteManager
from .core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from .config import ConfigManager, ConcreteAccountSettings

logger = logging.getLogger(__name__)

app = typer.Typer()

class Phase(str, Enum):
    IMPORT = "import"
    VALIDATE = "validate"
    VERIFY = "verify"
    CALCULATE = "calculate"
    RECONCILE_PAYMENTS = "reconcile-payments"
    RENDER = "render"

class ImporterType(str, Enum):
    SCHWAB = "schwab"
    IBKR = "ibkr" # Added IBKR
    NONE = "none"

class TaxCalculationLevel(str, Enum):
    NONE = "none"
    MINIMAL = "minimal"
    KURSLISTE = "kursliste"
    FILL_IN = "fillin"

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

default_phases = [Phase.IMPORT, Phase.VALIDATE, Phase.CALCULATE, Phase.RECONCILE_PAYMENTS, Phase.RENDER]

@app.command()
def main(
    input_file: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=True, readable=True, help="Input file (specific format depends on importer, or XML for raw) or directory (for Schwab importer)."),
    output_file: Path = typer.Option(None, "--output", "-o", help="Output PDF file path."),
    run_phases_input: List[Phase] = typer.Option(None, "--phases", "-p", help="Phases to run (default: all). Specify multiple times or comma-separated."),
    debug_dump_path: Optional[Path] = typer.Option(None, "--debug-dump", help="Directory to dump intermediate model state after each phase (as XML)."),
    final_xml_path: Optional[Path] = typer.Option(None, "--xml-output", help="Write the final tax statement XML to this file."),
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
    tax_calculation_level: TaxCalculationLevel = typer.Option(TaxCalculationLevel.KURSLISTE, "--tax-calculation-level", help="Specify the level of detail for tax value calculations."),
    log_level: LogLevel = typer.Option(LogLevel.INFO, "--log-level", help="Set the log level for console output."),
    config_file: Path = typer.Option("config.toml", "--config", "-c", help="Path to the configuration TOML file."),
    broker_name: Optional[str] = typer.Option(None, "--broker", help="Broker name (e.g., 'schwab') from config.toml to use for this run."),
    override_configs: List[str] = typer.Option(None, "--set", help="Override configuration settings using path.to.key=value format. Can be used multiple times."),
    kursliste_dir: Path = typer.Option(Path("data/kursliste"), "--kursliste-dir", help="Directory containing Kursliste XML files for exchange rate information. Defaults to 'data/kursliste'."),
    org_nr: Optional[str] = typer.Option(None, "--org-nr", help="Override the organization number used in barcodes (5-digit number)"),
    payment_reconciliation: bool = typer.Option(True, "--payment-reconciliation/--no-payment-reconciliation", help="Run optional payment reconciliation between Kursliste and broker evidence."),
    pre_amble: Optional[List[Path]] = typer.Option(None, "--pre-amble", help="List of PDF documents to add before the main steuerauszug."),
    post_amble: Optional[List[Path]] = typer.Option(None, "--post-amble", help="List of PDF documents to add after the main steuerauszug."),
):
    """Processes financial data to generate a Swiss tax statement (Steuerauszug)."""
    logging.basicConfig(level=log_level.value)
    # Suppress pypdf warnings to avoid cluttering output with benign warnings
    # about rotated text and other PDF layout issues
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    sys.stdout.reconfigure(line_buffering=True)  # Ensure stdout is line-buffered for mixing with logging
    
    phases_specified_by_user = run_phases_input is not None
    run_phases = run_phases_input if phases_specified_by_user else default_phases[:]

    if payment_reconciliation and Phase.RECONCILE_PAYMENTS not in run_phases:
        render_idx = run_phases.index(Phase.RENDER) if Phase.RENDER in run_phases else len(run_phases)
        run_phases.insert(render_idx, Phase.RECONCILE_PAYMENTS)
    elif not payment_reconciliation and Phase.RECONCILE_PAYMENTS in run_phases:
        run_phases.remove(Phase.RECONCILE_PAYMENTS)

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
            logger.debug(f"Using explicit --period-from: {parsed_period_from}")
        else:
            parsed_period_from = year_start_date
            logger.debug(f"Defaulting --period-from to start of tax year: {parsed_period_from}")

        if temp_period_to:
            if temp_period_to.year != tax_year:
                raise typer.BadParameter(f"--period-to date '{temp_period_to}' is not within the specified --tax-year '{tax_year}'.")
            parsed_period_to = temp_period_to
            logger.debug(f"Using explicit --period-to: {parsed_period_to}")
        else:
            parsed_period_to = year_end_date
            logger.debug(f"Defaulting --period-to to end of tax year: {parsed_period_to}")
    else:
        parsed_period_from = temp_period_from
        parsed_period_to = temp_period_to
        if parsed_period_from:
            logger.debug(f"Using explicit --period-from: {parsed_period_from}")
        if parsed_period_to:
            logger.debug(f"Using explicit --period-to: {parsed_period_to}")

    if parsed_period_from and parsed_period_to and parsed_period_from > parsed_period_to:
        raise typer.BadParameter(f"--period-from '{parsed_period_from}' cannot be after --period-to '{parsed_period_to}'.")

    if parsed_period_from and parsed_period_to:
        print(f"Tax period: {parsed_period_from} to {parsed_period_to}")
    # ... (rest of date printing)

    # --- Configuration Loading ---
    all_schwab_account_settings_models: List[SchwabAccountSettings] = []
    all_ibkr_account_settings_models: List[IbkrAccountSettings] = [] # New list for IBKR
    config_manager = ConfigManager(config_file_path=str(config_file))
    
    # Extract general configuration settings for CleanupCalculator
    general_config_settings: Optional[GeneralSettings] = None
    try:
        if config_manager.general_settings:
            # Create GeneralSettings instance from the loaded configuration
            temp_general_settings = dict(config_manager.general_settings)
            
            # Apply CLI overrides to general settings if any
            if override_configs:
                # Create a temporary dict to apply overrides to general settings
                temp_config = {"general": config_manager.general_settings.copy()}
                config_manager._apply_cli_overrides(temp_config, override_configs)
                temp_general_settings = temp_config.get("general", {})
            
            # Create the GeneralSettings Pydantic model
            general_config_settings = GeneralSettings(**temp_general_settings)
            
            print(f"Loaded general configuration settings: canton={general_config_settings.canton}, full_name={general_config_settings.full_name}")
        else:
            print("No general configuration settings found.")
    except Exception as e:
        print(f"Warning: Error loading general configuration settings: {e}")
        general_config_settings = None

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
            logger.debug(f"Loading all account configurations for broker kind '{target_broker_kind_for_config_loading}' from '{config_file}'...")
            if override_configs:
                logger.debug(f"Applying CLI overrides: {override_configs}")

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
                logger.debug(f"Warning: No valid IBKR account configurations loaded for broker 'ibkr', though other configurations might exist.")

            if all_schwab_account_settings_models:
                print(f"Successfully loaded {len(all_schwab_account_settings_models)} Schwab account(s).")
            if all_ibkr_account_settings_models:
                print(f"Successfully loaded {len(all_ibkr_account_settings_models)} IBKR account(s).")

        except ValueError as e:
            print(f"Error loading configuration: {e}")
            raise typer.Exit(code=1)
    else:
        print("No specific broker targeted by --importer or --broker for detailed configuration loading. Proceeding with general setup.")


    # This variable is used later for Schwab Importer instantiation
    account_settings: Optional[ConcreteAccountSettings] = None # Retain for now, as Schwab Importer instantiation still uses it.
                                                              # This will be addressed in the next step.
                                                              # For this step, we focus on populating all_schwab_account_settings_models.
                                                              # If Schwab importer is used, the old account_settings will be effectively ignored
                                                              # as all_schwab_account_settings_models takes precedence in logic flow.

    statement: Optional[TaxStatement] = None # Now refers to TaxStatement

    def dump_debug_model(current_phase_str: str, model: TaxStatement):
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
            statement = TaxStatement.from_xml_file(str(input_file))
            print("Raw import complete.")
            dump_debug_model("raw_import", statement)
        except Exception as e:
            print(f"Error during raw XML import from {input_file}: {e}")
            raise typer.Exit(code=1)

        if not phases_specified_by_user:
            run_phases = []

        if not any(p in run_phases for p in [Phase.VALIDATE, Phase.CALCULATE, Phase.VERIFY, Phase.RECONCILE_PAYMENTS, Phase.RENDER]):
             print("No further phases selected after raw import. Exiting.")
             return
        
        if not parsed_period_from:
            parsed_period_from = statement.periodFrom
        if not parsed_period_to:
            parsed_period_to = statement.periodTo
        if not tax_year:
            tax_year = statement.taxPeriod


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
                statement = schwab_importer.import_dir(str(input_file))
                print(f"Schwab import complete.")

            elif importer_type == ImporterType.IBKR:
                if not parsed_period_from or not parsed_period_to:
                    raise typer.BadParameter("--period-from and --period-to are required for the IBKR importer.")
                if not input_file.is_file():
                    raise typer.BadParameter(f"Input for IBKR importer must be an XML file, but got: {input_file}")

                if not all_ibkr_account_settings_models:
                    print("No specific IBKR account settings found/loaded from config. Using empty list for importer settings.")

                # Enable tolerance for unknown XML attributes so that new
                # fields added by Interactive Brokers don't break parsing.
                # This is only available in the forked ibflex
                # (vroonhof/ibflex).  We enable it here (production path)
                # rather than at module level so that tests remain strict by
                # default.  See: https://github.com/vroonhof/opensteuerauszug/issues/48
                import ibflex
                ibflex.enable_unknown_attribute_tolerance()

                print(f"Initializing IbkrImporter with {len(all_ibkr_account_settings_models)} IBKR account configuration(s) (if any).")
                ibkr_importer = IbkrImporter(
                    period_from=parsed_period_from,
                    period_to=parsed_period_to,
                    account_settings_list=all_ibkr_account_settings_models
                )
                statement = ibkr_importer.import_files([str(input_file)])
                print(f"IBKR import complete.")

            elif importer_type == ImporterType.NONE and not raw_import:
                print("No specific importer selected, creating an empty TaxStatement for further processing.")
                # Create a minimal valid statement with required elements per eCH-0196 XSD
                statement = TaxStatement(
                    minorVersion=22,
                    institution=Institution(name=""),
                    client=[Client(clientNumber=ClientNumber(""))]
                )
            else:
                # This case implies an importer was specified but isn't handled yet,
                # or raw_import is true (which is handled before this block).
                # If more importers are added, they need to be handled here.
                print(f"Importer '{importer_type.value}' not yet implemented or not applicable. Creating empty TaxStatement.")
                # Create a minimal valid statement with required elements per eCH-0196 XSD
                statement = TaxStatement(
                    minorVersion=22,
                    institution=Institution(name=""),
                    client=[Client(clientNumber=ClientNumber(""))]
                )

            print(f"Import successful." )
            dump_debug_model(current_phase.value, statement)

        if Phase.CALCULATE in run_phases:
            current_phase = Phase.CALCULATE
            print(f"Phase: {current_phase.value}")
            if not statement:
                 raise ValueError("TaxStatement model not loaded. Cannot run calculate phase.")
            
            if not parsed_period_from or not parsed_period_to:
                raise ValueError("Both --period-from and --period-to must be specified for the calculate phase.")
            
            effective_identifiers_csv_path: str
            if identifiers_csv_path_opt is None:
                cli_py_file_path = os.path.abspath(__file__)
                src_opensteuerauszug_dir = os.path.dirname(cli_py_file_path)
                src_dir = os.path.dirname(src_opensteuerauszug_dir)
                project_root_dir = os.path.dirname(src_dir)
                effective_identifiers_csv_path = os.path.join(project_root_dir, "data", "security_identifiers.csv")
                logger.debug(f"Using default security identifiers CSV path: {effective_identifiers_csv_path}")
            else:
                effective_identifiers_csv_path = identifiers_csv_path_opt
                logger.debug(f"Using user-provided security identifiers CSV path: {effective_identifiers_csv_path}")

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
                importer_name=importer_type.value,
                config_settings=general_config_settings
            )
            statement = cleanup_calculator.calculate(statement)
            print(f"CleanupCalculator finished. Summary: Modified fields count: {len(cleanup_calculator.modified_fields)}")
            dump_debug_model(current_phase.value + "_after_cleanup", statement) # Optional intermediate dump

            exchange_rate_provider: ExchangeRateProvider
            print(f"Using KurslisteExchangeRateProvider with directory: {kursliste_dir}")
            try:
                if not kursliste_dir.exists():
                    print(f"Warning: Kursliste directory {kursliste_dir} does not exist")
                kursliste_manager = KurslisteManager()
                kursliste_manager.load_directory(kursliste_dir)
                
                # Verify that Kursliste data exists for the required tax year
                required_tax_year = parsed_period_to.year
                kursliste_manager.ensure_year_available(required_tax_year, kursliste_dir)
                
                exchange_rate_provider = KurslisteExchangeRateProvider(kursliste_manager)
            except Exception as e:
                raise ValueError(f"Failed to initialize KurslisteExchangeRateProvider with directory {kursliste_dir}: {e}")
            
            tax_value_calculator: Optional[MinimalTaxValueCalculator] = None
            calculator_name = ""

            if tax_calculation_level == TaxCalculationLevel.MINIMAL:
                print("Running MinimalTaxValueCalculator...")
                calculator_name = "MinimalTaxValueCalculator"
                tax_value_calculator = MinimalTaxValueCalculator(mode=CalculationMode.OVERWRITE, exchange_rate_provider=exchange_rate_provider, keep_existing_payments=config_manager.calculate_settings.keep_existing_payments)
            elif tax_calculation_level == TaxCalculationLevel.KURSLISTE:
                print("Running KurslisteTaxValueCalculator...")
                calculator_name = "KurslisteTaxValueCalculator"
                tax_value_calculator = KurslisteTaxValueCalculator(mode=CalculationMode.OVERWRITE, exchange_rate_provider=exchange_rate_provider, keep_existing_payments=config_manager.calculate_settings.keep_existing_payments)
            elif tax_calculation_level == TaxCalculationLevel.FILL_IN:
                print("Running FillInTaxValueCalculator...")
                calculator_name = "FillInTaxValueCalculator"
                tax_value_calculator = FillInTaxValueCalculator(mode=CalculationMode.OVERWRITE, exchange_rate_provider=exchange_rate_provider, keep_existing_payments=config_manager.calculate_settings.keep_existing_payments)
            
            if tax_value_calculator and calculator_name:
                statement = tax_value_calculator.calculate(statement)
                print(f"{calculator_name} finished. Modified fields: {len(tax_value_calculator.modified_fields) if tax_value_calculator.modified_fields else '0'}, Errors: {len(tax_value_calculator.errors)}")
                dump_debug_model(current_phase.value + f"_after_{calculator_name.lower()}", statement)
            elif tax_calculation_level != TaxCalculationLevel.NONE:
                print(f"Warning: Tax calculation level '{tax_calculation_level.value}' was specified but no corresponding calculator was run.")
            else:
                print(f"Tax calculation level set to '{tax_calculation_level.value}', skipping detailed tax value calculation step.")

            # --- 3. Run TotalCalculator (or other main calculators) ---
            # Ensure statement is not None after cleanup, though cleanup should always return it
            if not statement:
                raise ValueError("TaxStatement became None after cleanup phase. This should not happen.")
            calculator = TotalCalculator(mode=CalculationMode.OVERWRITE)
            
            # Apply calculations
            statement = calculator.calculate(statement)
            print(f"TotalCalculator finished. Modified fields: {len(calculator.modified_fields) if calculator.modified_fields else '0'}")
            dump_debug_model(current_phase.value, statement)

        if Phase.VERIFY in run_phases:
            current_phase = Phase.VERIFY
            print(f"Phase: {current_phase.value}")
            if not statement:
                 raise ValueError("TaxStatement model not loaded. Cannot run calculate phase.")
            
            print(f"Verifying with tax calculation level: {tax_calculation_level.value}...")
            exchange_rate_provider_verify: ExchangeRateProvider
            print(f"Using KurslisteExchangeRateProvider with directory: {kursliste_dir} for verification")
            try:
                if not kursliste_dir.exists():
                    print(f"Warning: Kursliste directory {kursliste_dir} does not exist for verification.")
                    kursliste_dir.mkdir(parents=True, exist_ok=True)
                kursliste_manager_verify = KurslisteManager()
                kursliste_manager_verify.load_directory(kursliste_dir)
                
                # Verify that Kursliste data exists for the required tax year
                required_tax_year_verify = statement.taxPeriod if statement.taxPeriod else parsed_period_to.year
                kursliste_manager_verify.ensure_year_available(required_tax_year_verify, kursliste_dir)
                
                exchange_rate_provider_verify = KurslisteExchangeRateProvider(kursliste_manager_verify)
            except Exception as e:
                raise ValueError(f"Failed to initialize KurslisteExchangeRateProvider for verification with directory {kursliste_dir}: {e}")
            
            tax_value_verifier: Optional[MinimalTaxValueCalculator] = None
            verifier_name = ""

            if tax_calculation_level == TaxCalculationLevel.MINIMAL:
                verifier_name = "MinimalTaxValueCalculator"
                tax_value_verifier = MinimalTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=exchange_rate_provider_verify, keep_existing_payments=config_manager.calculate_settings.keep_existing_payments)
            elif tax_calculation_level == TaxCalculationLevel.KURSLISTE:
                verifier_name = "KurslisteTaxValueCalculator"
                tax_value_verifier = KurslisteTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=exchange_rate_provider_verify, keep_existing_payments=config_manager.calculate_settings.keep_existing_payments)
            elif tax_calculation_level == TaxCalculationLevel.FILL_IN:
                verifier_name = "FillInTaxValueCalculator"
                tax_value_verifier = FillInTaxValueCalculator(mode=CalculationMode.VERIFY, exchange_rate_provider=exchange_rate_provider_verify, keep_existing_payments=config_manager.calculate_settings.keep_existing_payments)

            if tax_value_verifier and verifier_name:
                print(f"Running {verifier_name} (Verify Mode)...")
                tax_value_verifier.calculate(statement)  # Does not modify statement in verify mode
                if tax_value_verifier.errors:
                    print(
                        f"{verifier_name} (Verify Mode) encountered {len(tax_value_verifier.errors)} errors:"
                    )
                    for error in tax_value_verifier.errors:
                        prefix = "Known" if is_known_issue(error, statement.institution) else "Error"
                        print(f"  {prefix}: {error}")
                else:
                    print(f"{verifier_name} (Verify Mode) found no errors.")
            elif tax_calculation_level != TaxCalculationLevel.NONE:
                print(f"Warning: Tax calculation level '{tax_calculation_level.value}' was specified but no corresponding verifier was run.")
            else:
                print(f"Tax calculation level set to '{tax_calculation_level.value}', skipping detailed tax value verification step.")

            calculator = TotalCalculator(mode=CalculationMode.VERIFY)
            calculator.calculate(statement)
            
            if calculator.errors:
                print(f"Encountered {len(calculator.errors)} fields during calculation")
                for error in calculator.errors:
                    prefix = "Known" if is_known_issue(error, statement.institution) else "Error"
                    print(f"{prefix}: {error}")
            else:
                print("No errors calculation")

        if Phase.RECONCILE_PAYMENTS in run_phases:
            current_phase = Phase.RECONCILE_PAYMENTS
            print(f"Phase: {current_phase.value}")
            if not statement:
                raise ValueError("TaxStatement model not loaded. Cannot run payment reconciliation phase.")

            reconciliation_calculator = PaymentReconciliationCalculator()
            statement = reconciliation_calculator.calculate(statement)
            report = statement.payment_reconciliation_report
            if report:
                print(
                    "Payment reconciliation complete: "
                    f"matches={report.match_count}, "
                    f"expected-missing={report.expected_missing_count}, "
                    f"mismatches={report.mismatch_count}"
                )
                for row in report.rows:
                    if row.status == "mismatch":
                        div_diff_chf = None
                        wht_diff_chf = None
                        div_diff_orig = None
                        wht_diff_orig = None
                        if row.exchange_rate is not None and row.exchange_rate != 0:
                            if row.broker_dividend_amount is not None:
                                broker_div_chf = row.broker_dividend_amount * row.exchange_rate
                                div_diff_chf = broker_div_chf - row.kursliste_dividend_chf
                                div_diff_orig = row.broker_dividend_amount - (row.kursliste_dividend_chf / row.exchange_rate)
                            if row.broker_withholding_amount is not None:
                                broker_wht_chf = row.broker_withholding_amount * row.exchange_rate
                                wht_diff_chf = broker_wht_chf - row.kursliste_withholding_chf
                                wht_diff_orig = row.broker_withholding_amount - (row.kursliste_withholding_chf / row.exchange_rate)

                        print(
                            f"  MISMATCH {row.country} {row.security} {row.payment_date}: "
                            f"KL div {row.kursliste_dividend_chf} CHF / KL wht {row.kursliste_withholding_chf} CHF vs "
                            f"Broker div {row.broker_dividend_amount} {row.broker_dividend_currency} / "
                            f"Broker wht {row.broker_withholding_amount} {row.broker_withholding_currency}; "
                            f"dCHF(div={div_diff_chf}, wht={wht_diff_chf}); "
                            f"dORIG(div={div_diff_orig} {row.broker_dividend_currency}, "
                            f"wht={wht_diff_orig} {row.broker_withholding_currency})"
                        )

            dump_debug_model(current_phase.value, statement)

        if Phase.VALIDATE in run_phases:
            current_phase = Phase.VALIDATE
            print(f"Phase: {current_phase.value}")
            if not statement:
                 raise ValueError("TaxStatement model not loaded. Cannot run validate phase.")
            statement.validate_model()
            print(f"Validation successful.")
            dump_debug_model(current_phase.value, statement)

        if Phase.RENDER in run_phases:
            current_phase = Phase.RENDER
            print(f"Phase: {current_phase.value}")
            if not statement:
                 raise ValueError("TaxStatement model not loaded. Cannot run render phase.")
            if not output_file:
                 raise ValueError("Output file path must be specified for the render phase.")

            # Fill in missing fields to make rendering possible
            calculator = TotalCalculator(mode=CalculationMode.FILL)
            statement = calculator.calculate(statement)
            print(f"Calculation successful.")
            dump_debug_model(current_phase.value, statement)
            
            if org_nr is not None:
                if not isinstance(org_nr, str) or not org_nr.isdigit() or len(org_nr) != 5:
                    raise ValueError(f"Invalid --org-nr '{org_nr}': Must be a 5-digit string.")
            
            # Determine the path for the main tax statement PDF
            # If we are merging, render to a temp file first
            main_pdf_path = output_file
            if pre_amble or post_amble:
                main_pdf_path = output_file.with_suffix(".tmp_main.pdf")

            # Use the render_tax_statement function to generate the PDF
            rendered_path = render_tax_statement(
                statement,
                main_pdf_path,
                override_org_nr=org_nr,
                minimal_frontpage_placeholder=(
                    (tax_calculation_level == TaxCalculationLevel.MINIMAL)
                    and (
                        general_config_settings.minimal_uses_placeholder_frontpage
                        if general_config_settings
                        else True
                    )
                ),
            )
            print(f"Rendering successful to {rendered_path}")

            if pre_amble or post_amble:
                # Validate all pre/post amble files before starting the merge
                all_amble_files = list(pre_amble or []) + list(post_amble or [])
                for path in all_amble_files:
                    if not path.exists():
                        print(f"Error: PDF file not found: {path}")
                        raise typer.Exit(code=1)
                    try:
                        PdfReader(path)
                    except Exception:
                        print(f"Error: File is not a valid PDF: {path}")
                        raise typer.Exit(code=1)

                try:
                    merger = PdfWriter()

                    if pre_amble:
                        print(f"Prepending {len(pre_amble)} document(s)...")
                        for path in pre_amble:
                            merger.append(path)

                    merger.append(rendered_path)

                    if post_amble:
                        print(f"Appending {len(post_amble)} document(s)...")
                        for path in post_amble:
                            merger.append(path)

                    # Write the final merged PDF directly to the output file
                    merger.write(output_file)
                    merger.close()
                    print(f"Successfully merged pre/post-ambles into {output_file}")

                except Exception as e:
                    print(f"Error during PDF concatenation: {e}")
                    raise typer.Exit(code=1)
                finally:
                    # Cleanup the temporary main PDF
                    if rendered_path.exists():
                        try:
                            rendered_path.unlink()
                        except Exception as e:
                            print(f"Warning: Failed to delete temporary file {rendered_path}: {e}")

        if final_xml_path:
            try:
                statement.to_xml_file(str(final_xml_path))
                print(f"Final XML written to {final_xml_path}")
            except Exception as e:
                print(f"Failed to write final XML to {final_xml_path}: {e}")
                raise typer.Exit(code=1)

        print("Processing finished successfully.")

    except Exception as e:
        print(f"Error during phase {current_phase.value if current_phase else 'startup'}: {e}")
        print("Stack trace:")
        import traceback
        traceback.print_exc(limit=20)
        if statement and debug_dump_path:
            error_phase_str = f"{current_phase.value}_error" if current_phase else "startup_error"
            try:
                dump_debug_model(error_phase_str, statement)
            except Exception as dump_e:
                print(f"Failed to dump debug model after error: {dump_e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
