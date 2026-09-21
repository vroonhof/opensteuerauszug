"""Tax-overview writer: orchestrates xlsx / html / pdf output.

Runs the broker import + calculate pipeline (via :mod:`pipeline`) to
produce a :class:`TaxOverviewData`, then hands it to the format-specific
renderers. No placeholder content — every sheet, the HTML dashboard, and
the PDF cover render from the same source of truth.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional

from .data import TaxOverviewData
from .html import render_html
from .pdf_cover import render_pdf_cover
from .pipeline import build_tax_overview_data
from .render import render_workbook

OutputFormat = Literal["xlsx", "html", "pdf"]
ALL_FORMATS: tuple[OutputFormat, ...] = ("xlsx", "html", "pdf")


@dataclass(frozen=True)
class TaxOverviewRequest:
    """Inputs for one tax-overview invocation.

    Kept intentionally small: the CLI layer resolves filesystem paths and
    importer types; this request carries only what the writer needs.
    """

    input_path: Path
    broker: str
    tax_year: int
    output_dir: Path
    formats: tuple[OutputFormat, ...]
    preparer_mode: bool
    # When set, the prior-year Flex export feeds opening values for the current
    # year (Kursliste-derived end-of-prior-year = start-of-current-year).
    prior_year_input_path: Optional[Path] = None
    # Canton code for the statement metadata (e.g. "ZH"). Overrides the
    # config's general.canton; when neither is set, the importer-derived
    # canton applies (same behaviour as the main CLI).
    canton: Optional[str] = None
    # Opt-in yfinance sector lookup for the Performance tab. Off by default:
    # no network calls unless explicitly requested.
    online_sectors: bool = False


def compute_report_hash(request: TaxOverviewRequest) -> str:
    """Deterministic hash derived from input data only.

    Stable across preparer and third-party exports: the same input file + year
    produces the same hash regardless of which output variants are requested.
    """
    h = hashlib.sha256()
    h.update(str(request.tax_year).encode("utf-8"))
    h.update(b"\x00")
    h.update(request.broker.encode("utf-8"))
    h.update(b"\x00")
    if request.input_path.is_file():
        with request.input_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    else:
        # Directory input (Schwab): hash the sorted file names and contents.
        for child in sorted(request.input_path.rglob("*")):
            if child.is_file():
                h.update(str(child.relative_to(request.input_path)).encode("utf-8"))
                h.update(b"\x00")
                with child.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                h.update(b"\x00")
    return h.hexdigest()


def write_tax_overview(request: TaxOverviewRequest) -> List[Path]:
    """Entry point. Produce the requested formats, return the generated paths."""
    request.output_dir.mkdir(parents=True, exist_ok=True)

    result = build_tax_overview_data(
        input_path=request.input_path,
        broker=request.broker,
        tax_year=request.tax_year,
        preparer_mode=request.preparer_mode,
        prior_year_input_path=request.prior_year_input_path,
        canton=request.canton,
        online_sectors=request.online_sectors,
    )
    data = result.data

    produced: List[Path] = []
    for fmt in request.formats:
        if fmt == "xlsx":
            produced.append(_write_xlsx(request, data))
        elif fmt == "html":
            produced.append(_write_html(request, data))
        elif fmt == "pdf":
            produced.append(_write_pdf(request, data))
        else:  # pragma: no cover - typer validates enum
            raise ValueError(f"unknown output format: {fmt}")
    return produced


def _output_path(request: TaxOverviewRequest, suffix: str) -> Path:
    return request.output_dir / f"tax_overview_{request.tax_year}{suffix}"


def _write_xlsx(request: TaxOverviewRequest, data: TaxOverviewData) -> Path:
    workbook = render_workbook(data)
    path = _output_path(request, ".xlsx")
    workbook.save(path)
    return path


def _write_html(request: TaxOverviewRequest, data: TaxOverviewData) -> Path:
    html = render_html(data)
    path = _output_path(request, ".html")
    path.write_text(html, encoding="utf-8")
    return path


def _write_pdf(request: TaxOverviewRequest, data: TaxOverviewData) -> Path:
    pdf_bytes = render_pdf_cover(data)
    path = _output_path(request, ".pdf")
    path.write_bytes(pdf_bytes)
    return path


def parse_formats(value: Optional[str]) -> tuple[OutputFormat, ...]:
    """Parse the --formats CLI value. None or empty means all formats."""
    if value is None or value.strip() == "":
        return ALL_FORMATS
    requested = [p.strip().lower() for p in value.split(",") if p.strip()]
    unknown = [f for f in requested if f not in ALL_FORMATS]
    if unknown:
        raise ValueError(
            f"unknown output format(s): {', '.join(unknown)}. " f"Known: {', '.join(ALL_FORMATS)}"
        )
    # Preserve canonical order.
    return tuple(f for f in ALL_FORMATS if f in requested)  # type: ignore[misc]
