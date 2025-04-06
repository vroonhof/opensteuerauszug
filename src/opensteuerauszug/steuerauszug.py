import typer
from enum import Enum
from pathlib import Path
from typing import List, Optional

# Use the generated eCH-0196 model
from .model.ech0196 import TaxStatement
# Import the rendering functionality
from .render.render import render_tax_statement

# Keep Portfolio for now, maybe it becomes an alias or wrapper for TaxStatement?
# Or perhaps TaxStatement becomes the internal representation?
# For now, assume TaxStatement IS the model passed around.
# from .model.portfolio import Portfolio
Portfolio = TaxStatement # Use TaxStatement as the main model type

app = typer.Typer()

class Phase(str, Enum):
    IMPORT = "import"
    VALIDATE = "validate"
    CALCULATE = "calculate"
    RENDER = "render"

default_phases = [Phase.IMPORT, Phase.VALIDATE, Phase.CALCULATE, Phase.RENDER]

@app.command()
def main(
    input_file: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True, help="Input file (specific format depends on importer, or XML for raw)"),
    output_file: Path = typer.Option(None, "--output", "-o", help="Output PDF file path."),
    run_phases_input: List[Phase] = typer.Option(None, "--phases", "-p", help="Phases to run (default: all). Specify multiple times or comma-separated."),
    debug_dump_path: Optional[Path] = typer.Option(None, "--debug-dump", help="Directory to dump intermediate model state after each phase (as XML)."),
    raw_import: bool = typer.Option(False, "--raw-import", help="Import directly from XML model dump instead of using an importer."),
    # Add importer-specific options here later
    # Add calculation-specific options here later
    # Add render-specific options here later
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
            portfolio = Portfolio(minorVersion=2)
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
            # TODO: Implement calculation logic
            # calculate_tax_values(portfolio, ...)
            print(f"Calculation successful (placeholder)." )
            dump_debug_model(current_phase.value, portfolio)

        if Phase.RENDER in run_phases:
            current_phase = Phase.RENDER
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run render phase.")
            if not output_file:
                 raise ValueError("Output file path must be specified for the render phase.")
            
            # Use the render_tax_statement function to generate the PDF
            rendered_path = render_tax_statement(portfolio, output_file)
            print(f"Rendering successful to {rendered_path}")
            # No debug dump after render

        print("Processing finished successfully.")

    except Exception as e:
        print(f"Error during phase {current_phase.value if current_phase else 'startup'}: {e}")
        if portfolio and debug_dump_path:
            error_phase_str = f"{current_phase.value}_error" if current_phase else "startup_error"
            try:
                dump_debug_model(error_phase_str, portfolio)
            except Exception as dump_e:
                print(f"Failed to dump debug model after error: {dump_e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app() 