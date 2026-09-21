"""Typer subcommand for the tax-overview mode.

Registered by ``opensteuerauszug.steuerauszug`` via ``app.command(...)`` so the
tax_overview package stays importable without the main CLI.

The writer stack (openpyxl, jinja2, reportlab) is imported lazily inside the
command body: the main CLI imports this module on every invocation, and eager
imports here would tax the startup of unrelated subcommands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer


def tax_overview_command(
    input_path: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        file_okay=True,
        dir_okay=True,
        readable=True,
        help="Broker statement: IBKR Flex XML file, or Schwab statement directory.",
    ),
    broker: str = typer.Option(
        ...,
        "--broker",
        help="Broker name: 'ibkr' or 'schwab'. Must match the statement format.",
    ),
    tax_year: int = typer.Option(..., "--year", help="Steuerperiode (e.g. 2025)."),
    output_dir: Path = typer.Option(
        Path("./out"),
        "--output-dir",
        "-o",
        file_okay=False,
        dir_okay=True,
        help="Directory where tax_overview_<year>.{xlsx,html,pdf} are written.",
    ),
    formats: Optional[str] = typer.Option(
        None, "--formats", help="Comma-separated list of output formats. Default: xlsx,html,pdf."
    ),
    preparer_mode: bool = typer.Option(
        False,
        "--preparer-mode",
        help="Include hidden KS36 self-check sheets. NEVER share this workbook "
        "with third parties. Omit for a clean third-party export.",
    ),
    prior_year_input: Optional[Path] = typer.Option(
        None,
        "--prior-year-input",
        exists=True,
        file_okay=True,
        dir_okay=True,
        readable=True,
        help="Prior-year broker statement; its Kursliste-derived closing "
        "values become the current-year opening (2023 Schluss = 2024 Eröffnung).",
    ),
    canton: Optional[str] = typer.Option(
        None,
        "--canton",
        help="Your canton code (e.g. ZH, BE, SG) for the statement metadata. "
        "Overrides the config's general.canton; when neither is set, the "
        "canton from the importer data applies.",
    ),
    online_sectors: bool = typer.Option(
        False,
        "--online-sectors",
        help="Look up missing sector classifications via yfinance (sends "
        "ticker symbols to Yahoo Finance; results cached in "
        "data/cache/sector_lookup.json). Off by default — without it, "
        "uncached sectors show as 'Unbekannt'.",
    ),
) -> None:
    """Generate a tax-authority-friendly overview (xlsx, HTML, PDF) from a broker statement."""
    from .writer import TaxOverviewRequest, parse_formats, write_tax_overview

    try:
        parsed_formats = parse_formats(formats)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--formats") from exc

    broker_norm = broker.strip().lower()
    if broker_norm not in {"ibkr", "schwab"}:
        raise typer.BadParameter(
            f"unknown broker '{broker}'. Expected 'ibkr' or 'schwab'.",
            param_hint="--broker",
        )

    request = TaxOverviewRequest(
        input_path=input_path,
        broker=broker_norm,
        tax_year=tax_year,
        output_dir=output_dir,
        formats=parsed_formats,
        preparer_mode=preparer_mode,
        prior_year_input_path=prior_year_input,
        canton=canton.strip().upper() if canton else None,
        online_sectors=online_sectors,
    )
    produced = write_tax_overview(request)
    for path in produced:
        typer.echo(f"wrote {path}")
