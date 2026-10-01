"""Tax-overview mode: tax-authority-friendly dashboard for Swiss tax filings."""

from .cli import tax_overview_command
from .conversion import CHF, CHF_QUANTUM, MoneyCHF, sum_chf, to_chf
from .data import (
    DA1Claim,
    FeeEvent,
    FXRateUsed,
    IncomeEvent,
    KS36Criterion,
    KS36Evidence,
    PositionSummary,
    TaxOverviewData,
    VerzeichnisLine,
)
from .fifo import FifoError, FifoResult, Lot, LotClose, apply_orders
from .html import format_chf, format_date, format_number, format_percent, render_html
from .orders import DEFAULT_TIME_CLUSTER_WINDOW, Fill, Order, reconstruct_orders
from .pdf_cover import render_pdf_cover
from .render import render_workbook
from .waterfall import (
    DEFAULT_RECONCILIATION_TOLERANCE_CHF,
    Waterfall,
    WaterfallLine,
    build_waterfall,
)
from .writer import (
    ALL_FORMATS,
    OutputFormat,
    TaxOverviewRequest,
    compute_report_hash,
    parse_formats,
    write_tax_overview,
)

__all__ = [
    "ALL_FORMATS",
    "CHF",
    "CHF_QUANTUM",
    "DEFAULT_RECONCILIATION_TOLERANCE_CHF",
    "DEFAULT_TIME_CLUSTER_WINDOW",
    "DA1Claim",
    "FeeEvent",
    "FXRateUsed",
    "FifoError",
    "FifoResult",
    "Fill",
    "IncomeEvent",
    "KS36Criterion",
    "KS36Evidence",
    "Lot",
    "LotClose",
    "MoneyCHF",
    "Order",
    "OutputFormat",
    "PositionSummary",
    "TaxOverviewData",
    "TaxOverviewRequest",
    "VerzeichnisLine",
    "Waterfall",
    "WaterfallLine",
    "apply_orders",
    "build_waterfall",
    "compute_report_hash",
    "format_chf",
    "format_date",
    "format_number",
    "format_percent",
    "parse_formats",
    "reconstruct_orders",
    "render_html",
    "render_pdf_cover",
    "render_workbook",
    "sum_chf",
    "tax_overview_command",
    "to_chf",
    "write_tax_overview",
]
