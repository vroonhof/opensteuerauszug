import typer
from enum import Enum
from pathlib import Path
from typing import List, Optional
from datetime import date, datetime # Modified to include datetime

# Use the generated eCH-0196 model
from .model.ech0196 import TaxStatement
# Import the rendering functionality
from .render.render import render_tax_statement
# Import calculation framework
from .calculate.base import CalculationMode
from .calculate.total import TotalCalculator
from .importers.schwab.schwab_importer import SchwabImporter # Added import

# Keep Portfolio for now, maybe it becomes an alias or wrapper for TaxStatement?
# Or perhaps TaxStatement becomes the internal representation?
# For now, assume TaxStatement IS the model passed around.
# from .model.portfolio import Portfolio
Portfolio = TaxStatement # Use TaxStatement as the main model type

app = typer.Typer()

class Phase(str, Enum):
    IMPORT = "import"
    VALIDATE = "validate"
    VERIFY = "verify"
    CALCULATE = "calculate"
    RENDER = "render"

class ImporterType(str, Enum):
    SCHWAB = "schwab"
    # Add other importer types here in the future
    NONE = "none" # For raw import or if no specific importer is needed yet

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
    strict_consistency_flag: bool = typer.Option(True, "--strict-consistency/--no-strict-consistency", help="Enable/disable strict consistency checks in importers (e.g., Schwab). Defaults to strict."),
    # Add importer-specific options here later
    # Add calculation-specific options here later
    # Add render-specific options here later
    org_nr: Optional[str] = typer.Option(None, "--org-nr", help="Override the organization number used in barcodes (5-digit number)"),
):
    """Processes financial data to generate a Swiss tax statement (Steuerauszug)."""
    # Determine effective phases
    phases_specified_by_user = run_phases_input is not None
    run_phases = run_phases_input if phases_specified_by_user else default_phases[:]

    print(f"Starting OpenSteuerauszug processing...")
    print(f"Input file: {input_file}")
    print(f"Output file: {output_file}")
    print(f"Phases to run: {[p.value for p in run_phases]}")
    print(f"Raw import: {raw_import}")
    print(f"Debug dump path: {debug_dump_path}")
    print(f"Importer type: {importer_type.value}")

    # Parse date strings and determine effective period_from and period_to
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
        # No tax_year provided, use explicit dates if available
        parsed_period_from = temp_period_from
        parsed_period_to = temp_period_to
        if parsed_period_from:
            print(f"Using explicit --period-from: {parsed_period_from}")
        if parsed_period_to:
            print(f"Using explicit --period-to: {parsed_period_to}")

    # Validate that period_from is not after period_to
    if parsed_period_from and parsed_period_to and parsed_period_from > parsed_period_to:
        raise typer.BadParameter(f"--period-from '{parsed_period_from}' cannot be after --period-to '{parsed_period_to}'.")

    if parsed_period_from and parsed_period_to:
        print(f"Tax period: {parsed_period_from} to {parsed_period_to}")
    elif parsed_period_from:
        print(f"Tax period from: {parsed_period_from}")
    elif parsed_period_to:
        print(f"Tax period to: {parsed_period_to}")

    portfolio: Optional[Portfolio] = None # Now refers to TaxStatement

    def dump_debug_model(current_phase_str: str, model: Portfolio):
        if debug_dump_path and model:
            debug_dump_path.mkdir(parents=True, exist_ok=True)
            dump_file = debug_dump_path / f"portfolio_{current_phase_str}.xml"
            try:
                # Use the model's XML dump method
                model.dump_debug_xml(str(dump_file))
                print(f"Debug model dumped to: {dump_file}")
            except Exception as e:
                print(f"Error dumping debug model to {dump_file}: {e}")
        # Removed old JSON dump logic

    # --- Raw Import Phase (Special Case) ---
    if raw_import:
        if Phase.IMPORT in run_phases:
            if phases_specified_by_user:
                 print("Warning: --phases includes 'import' but --raw-import is active. Loading directly from XML.")
            run_phases = [p for p in run_phases if p != Phase.IMPORT]

        print(f"Raw importing model from: {input_file}")
        try:
            # Use the model's XML load method
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

        if not any(p in run_phases for p in [Phase.VALIDATE, Phase.CALCULATE, Phase.RENDER]):
             print("No further phases selected after raw import. Exiting.")
             return

    # --- Standard Phase Execution ---
    current_phase = None
    try:
        if Phase.IMPORT in run_phases and not raw_import:
            current_phase = Phase.IMPORT
            print(f"Phase: {current_phase.value}")
            # TODO: Implement importer logic based on input_file type
            # portfolio = run_import(input_file, ...)
            # For now, create an empty TaxStatement if not raw importing
            if importer_type == ImporterType.SCHWAB:
                if not parsed_period_from or not parsed_period_to:
                    raise typer.BadParameter("--period-from and --period-to are required for the Schwab importer and must be valid dates.")
                if not input_file.is_dir():
                    raise typer.BadParameter(f"Input for Schwab importer must be a directory, but got: {input_file}")
                
                print(f"Using Schwab importer for directory: {input_file}")
                schwab_importer = SchwabImporter(period_from=parsed_period_from, period_to=parsed_period_to, strict_consistency=strict_consistency_flag)
                portfolio = schwab_importer.import_dir(str(input_file))
            elif importer_type == ImporterType.NONE and not raw_import:
                if not input_file.is_file():
                    # This branch currently doesn't use input_file, but help text implies it would be a file.
                    # If future development uses input_file here, this check is important.
                    # If it truly isn't used, this check could be removed or made more lenient.
                    print(f"Warning: No specific importer selected, and input '{input_file}' is a directory. Proceeding by creating an empty TaxStatement. If this input was intended for use, please specify an importer or ensure it is a file.")
                 # Default behavior if no specific importer is chosen and not raw_import
                print("No specific importer selected, creating an empty TaxStatement for further processing.")
                portfolio = Portfolio(minorVersion=2) # type: ignore
            else:
                # This case implies an importer was specified but isn't handled yet,
                # or raw_import is true (which is handled before this block).
                # If more importers are added, they need to be handled here.
                print(f"Importer '{importer_type.value}' not yet implemented or not applicable. Creating empty TaxStatement.")
                portfolio = Portfolio(minorVersion=2) # type: ignore

            print(f"Import successful (placeholder)." )
            dump_debug_model(current_phase.value, portfolio)

        if Phase.VALIDATE in run_phases:
            current_phase = Phase.VALIDATE
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run validate phase.")
            # Call the model's validate method
            portfolio.validate_model()
            print(f"Validation successful (placeholder check)." )
            dump_debug_model(current_phase.value, portfolio)

        if Phase.CALCULATE in run_phases:
            current_phase = Phase.CALCULATE
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run calculate phase.")
            
            # Create calculator with appropriate mode
            calculator = TotalCalculator(mode=CalculationMode.OVERWRITE)
            
            # Apply calculations
            portfolio = calculator.calculate(portfolio)
            
            if calculator.modified_fields:
                print(f"Modified {len(calculator.modified_fields)} fields during calculation")
            else:
                print("No fields needed modification during calculation")
            
            print(f"Calculation successful.")
            dump_debug_model(current_phase.value, portfolio)

        if Phase.VERIFY in run_phases:
            current_phase = Phase.VERIFY
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run calculate phase.")
            
            calculator = TotalCalculator(mode=CalculationMode.VERIFY)
            calculator.calculate(portfolio)
            
            if calculator.errors:
                print(f"Encountered {len(calculator.errors)} fields during calculation")
                for error in calculator.errors:
                    print(f"Error: {error}")
            else:
                print("No errors calculation")
            
            # Fill in missing fields to make rendering possible
            calulator = TotalCalculator(mode=CalculationMode.FILL)
            portfolio = calculator.calculate(portfolio)
            print(f"Calculation successful.")
            dump_debug_model(current_phase.value, portfolio)

        if Phase.RENDER in run_phases:
            current_phase = Phase.RENDER
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run render phase.")
            if not output_file:
                 raise ValueError("Output file path must be specified for the render phase.")
            
            # Validate org_nr format if provided
            if org_nr is not None:
                if not isinstance(org_nr, str) or not org_nr.isdigit() or len(org_nr) != 5:
                    raise ValueError(f"Invalid --org-nr '{org_nr}': Must be a 5-digit string.")
            
            # Use the render_tax_statement function to generate the PDF
            rendered_path = render_tax_statement(portfolio, output_file, override_org_nr=org_nr)
            print(f"Rendering successful to {rendered_path}")
            # No debug dump after render

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
