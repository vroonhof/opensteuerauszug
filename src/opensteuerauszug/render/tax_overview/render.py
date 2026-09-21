"""Workbook-level orchestration for the tax-overview mode.

:func:`render_workbook` is the pure "data in → openpyxl.Workbook out"
function that every format writer (xlsx, html via worksheet export, PDF
cover) builds on. Order of sheet creation matches the spec's left-to-right
tab order; the hidden KS36 sheets are appended last under the
``preparer_mode`` flag so third-party exports never ship them.
"""

from __future__ import annotations

from openpyxl import Workbook

from .data import TaxOverviewData
from .design import register_named_styles
from .sheets import (
    write_da1_sheet,
    write_dividends_sheet,
    write_fees_sheet,
    write_fx_rates_sheet,
    write_interest_sheet,
    write_ks36_criteria_sheet,
    write_ks36_evidence_sheet,
    write_orders_sheet,
    write_performance_sheet,
    write_securities_sheet,
    write_uebersicht_sheet,
    write_verzeichnis_sheet,
)


def render_workbook(data: TaxOverviewData) -> Workbook:
    """Build the workbook from a fully-prepared :class:`TaxOverviewData`.

    Visible sheet order (left-to-right): Übersicht, Wertschriften,
    SG_Verzeichnis, DA1_Hilfstabelle, Kauf_Verkauf, Dividenden, Zinsen,
    Gebühren, FX_Kurse. Hidden ``_KS36_Criteria`` and ``_KS36_Evidence``
    sheets are appended only when ``data.preparer_mode`` is true.
    """
    wb = Workbook()
    # openpyxl starts with a default "Sheet"; remove before adding ours so the
    # tab order is exactly as specified.
    default = wb.active
    if default is not None:
        wb.remove(default)

    register_named_styles(wb)

    write_uebersicht_sheet(wb, data)
    # Performance tab sits right after Übersicht — the dashboard narrative goes
    # "totals → how did we get there" before diving into raw position data.
    write_performance_sheet(wb, data)
    write_securities_sheet(wb, data)
    # SG-specific sheets go next — the tax clerk's reading order is
    # "what's the total?" → "which SG lines?" → "DA-1?" → transactional detail.
    write_verzeichnis_sheet(wb, data)
    write_da1_sheet(wb, data)
    write_orders_sheet(wb, data)
    write_dividends_sheet(wb, data)
    write_interest_sheet(wb, data)
    write_fees_sheet(wb, data)
    write_fx_rates_sheet(wb, data)

    if data.preparer_mode:
        # Hidden KS36 sheets carry preparer-only content and are created with
        # ``sheet_state = "hidden"`` by the writers themselves. Gate here so
        # third-party exports (preparer_mode=False) skip them entirely.
        write_ks36_criteria_sheet(wb, data)
        write_ks36_evidence_sheet(wb, data)

    return wb
