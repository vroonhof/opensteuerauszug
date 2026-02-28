import typer
from pathlib import Path
from typing import List, Optional
from opensteuerauszug.kursliste.__main__ import app as kursliste_app
from opensteuerauszug.steuerauszug import run_pipeline, Phase, ImporterType, TaxCalculationLevel, LogLevel

app = typer.Typer()

from dataclasses import dataclass

@dataclass
class GlobalOptions:
    log_level: LogLevel
    config_file: Optional[Path]
    override_configs: Optional[List[str]]

app.add_typer(kursliste_app, name="kursliste", help="Manage Kursliste files.")

@app.callback()
def main_callback(
    ctx: typer.Context,
    log_level: LogLevel = typer.Option(LogLevel.INFO, "--log-level", help="Set the log level for console output."),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to the configuration TOML file. Defaults to config.toml in CWD or XDG config home."),
    override_configs: List[str] = typer.Option(None, "--set", help="Override configuration settings using path.to.key=value format. Can be used multiple times."),
):
    """OpenSteuerauszug CLI"""
    ctx.obj = GlobalOptions(log_level=log_level, config_file=config_file, override_configs=override_configs)

@app.command()
def generate(
    ctx: typer.Context,
    input_file: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=True, readable=True, help="Input file (specific format depends on importer, or XML for raw) or directory (for Schwab importer)."),
    output_file: Path = typer.Option(None, "--output", "-o", help="Output PDF file path."),
    run_phases_input: List[Phase] = typer.Option(None, "--phases", "-p", help="Phases to run (default: all). Specify multiple times or comma-separated."),
    debug_dump_path: Optional[Path] = typer.Option(None, "--debug-dump", help="Directory to dump intermediate model state after each phase (as XML)."),
    final_xml_path: Optional[Path] = typer.Option(None, "--xml-output", help="Write the final tax statement XML to this file."),
    raw_import: bool = typer.Option(False, "--raw", help="Import directly from XML model dump instead of using an importer."),
    importer_type: ImporterType = typer.Option(ImporterType.NONE, "--importer", help="Specify the importer to use."),
    period_from_str: Optional[str] = typer.Option(None, "--period-from", help="Start date of the tax period (YYYY-MM-DD), required for some importers like Schwab."),
    period_to_str: Optional[str] = typer.Option(None, "--period-to", help="End date of the tax period (YYYY-MM-DD), required for some importers like Schwab."),
    tax_year: Optional[int] = typer.Option(None, "--tax-year", help="Specify the tax year (e.g., 2023)."),
    identifiers_csv_path_opt: Optional[str] = typer.Option(None, "--identifiers-csv-path", help="Path to the security identifiers CSV file."),
    strict_consistency_flag: bool = typer.Option(True, "--strict-consistency/--no-strict-consistency", help="Enable/disable strict consistency checks in importers."),
    filter_to_period_flag: bool = typer.Option(True, "--filter-to-period/--no-filter-to-period", help="Filter transactions and stock events to the tax period."),
    tax_calculation_level: TaxCalculationLevel = typer.Option(TaxCalculationLevel.KURSLISTE, "--tax-calculation-level", help="Specify the level of detail for tax value calculations."),
    broker_name: Optional[str] = typer.Option(None, "--broker", help="Broker name from config.toml to use for this run."),
    kursliste_dir: Optional[Path] = typer.Option(None, "--kursliste-dir", help="Directory containing Kursliste XML files."),
    org_nr: Optional[str] = typer.Option(None, "--org-nr", help="Override the organization number used in barcodes."),
    payment_reconciliation: bool = typer.Option(True, "--payment-reconciliation/--no-payment-reconciliation", help="Run optional payment reconciliation between Kursliste and broker evidence."),
    pre_amble: Optional[List[Path]] = typer.Option(None, "--pre-amble", help="List of PDF documents to add before the main steuerauszug."),
    post_amble: Optional[List[Path]] = typer.Option(None, "--post-amble", help="List of PDF documents to add after the main steuerauszug."),
):
    """Generates a Steuerauszug from broker data or raw XML."""
    global_opts: GlobalOptions = ctx.obj
    run_pipeline(
        input_file=input_file,
        output_file=output_file,
        run_phases_input=run_phases_input,
        debug_dump_path=debug_dump_path,
        final_xml_path=final_xml_path,
        raw_import=raw_import,
        importer_type=importer_type,
        period_from_str=period_from_str,
        period_to_str=period_to_str,
        tax_year=tax_year,
        identifiers_csv_path_opt=identifiers_csv_path_opt,
        strict_consistency_flag=strict_consistency_flag,
        filter_to_period_flag=filter_to_period_flag,
        tax_calculation_level=tax_calculation_level,
        log_level=global_opts.log_level,
        config_file=global_opts.config_file,
        broker_name=broker_name,
        override_configs=global_opts.override_configs,
        kursliste_dir=kursliste_dir,
        org_nr=org_nr,
        payment_reconciliation=payment_reconciliation,
        pre_amble=pre_amble,
        post_amble=post_amble,
    )

@app.command()
def verify(
    ctx: typer.Context,
    input_file: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True, help="Input XML file to verify."),
    tax_year: Optional[int] = typer.Option(None, "--tax-year", help="Specify the tax year (e.g., 2023)."),
):
    """Verifies an existing Steuerauszug XML file."""
    global_opts: GlobalOptions = ctx.obj
    run_pipeline(
        input_file=input_file,
        output_file=None,
        run_phases_input=[Phase.VERIFY],
        debug_dump_path=None,
        final_xml_path=None,
        raw_import=True,
        importer_type=ImporterType.NONE,
        period_from_str=None,
        period_to_str=None,
        tax_year=tax_year,
        identifiers_csv_path_opt=None,
        strict_consistency_flag=True,
        filter_to_period_flag=False,
        tax_calculation_level=TaxCalculationLevel.NONE,
        log_level=global_opts.log_level,
        config_file=global_opts.config_file,
        broker_name=None,
        override_configs=global_opts.override_configs,
        kursliste_dir=None,
        org_nr=None,
        payment_reconciliation=False,
        pre_amble=None,
        post_amble=None,
    )

if __name__ == "__main__":
    app()
