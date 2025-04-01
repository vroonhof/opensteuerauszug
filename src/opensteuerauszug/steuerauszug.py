import typer
from enum import Enum
from pathlib import Path
from typing import List, Optional

from .model.portfolio import Portfolio

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

    portfolio: Optional[Portfolio] = None

    def dump_debug_model(current_phase_str: str, model: Portfolio):
        if debug_dump_path and model:
            debug_dump_path.mkdir(parents=True, exist_ok=True)
            dump_file = debug_dump_path / f"portfolio_{current_phase_str}.xml"
            # TODO: Implement XML serialization for Portfolio model
            with open(dump_file, "w") as f:
                # Replace with actual XML writing logic
                f.write(f"<!-- Debug dump after {current_phase_str} phase -->\n")
                f.write(model.model_dump_json(indent=2)) # Temporary JSON dump
            print(f"Debug model dumped to: {dump_file}")

    # --- Raw Import Phase (Special Case) ---
    if raw_import:
        if Phase.IMPORT in run_phases:
            if phases_specified_by_user:
                 print("Warning: --phases includes 'import' but --raw-import is active. Loading directly from XML.")
            run_phases = [p for p in run_phases if p != Phase.IMPORT] # Remove standard import phase if present

        print(f"Raw importing model from: {input_file}")
        # TODO: Implement XML deserialization for Portfolio model
        # portfolio = Portfolio.from_xml(input_file)
        portfolio = Portfolio() # Placeholder
        print("Raw import complete.")
        dump_debug_model("raw_import", portfolio)

        # If user specified --raw-import but *did not* specify any --phases,
        # assume they *only* want the raw import and no subsequent steps.
        if not phases_specified_by_user:
            run_phases = [] # Clear subsequent phases

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
            portfolio = Portfolio() # Placeholder
            print(f"Import successful.")
            dump_debug_model(current_phase.value, portfolio)

        if Phase.VALIDATE in run_phases:
            current_phase = Phase.VALIDATE
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run validate phase.")
            # TODO: Implement validation logic
            # validate_portfolio(portfolio, ...)
            print(f"Validation successful.")
            dump_debug_model(current_phase.value, portfolio)

        if Phase.CALCULATE in run_phases:
            current_phase = Phase.CALCULATE
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run calculate phase.")
            # TODO: Implement calculation logic
            # calculate_tax_values(portfolio, ...)
            print(f"Calculation successful.")
            dump_debug_model(current_phase.value, portfolio)

        if Phase.RENDER in run_phases:
            current_phase = Phase.RENDER
            print(f"Phase: {current_phase.value}")
            if not portfolio:
                 raise ValueError("Portfolio model not loaded. Cannot run render phase.")
            if not output_file:
                 raise ValueError("Output file path must be specified for the render phase.")
            # TODO: Implement rendering logic
            # render_pdf(portfolio, output_file, ...)
            print(f"Rendering successful to {output_file}.")
            # No debug dump after render, as it's the final output

        print("Processing finished successfully.")

    except Exception as e:
        print(f"Error during phase {current_phase.value if current_phase else 'startup'}: {e}")
        # Potentially dump model even on error if it exists
        if portfolio and debug_dump_path:
            error_phase_str = f"{current_phase.value}_error" if current_phase else "startup_error"
            try:
                dump_debug_model(error_phase_str, portfolio)
            except Exception as dump_e:
                print(f"Failed to dump debug model after error: {dump_e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app() 