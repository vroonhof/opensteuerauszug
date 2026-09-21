"""Reportlab chart helpers for the performance pages of the PDF report.

Mirrors the inline SVG charts rendered in the HTML dashboard so the PDF
carries the same visual narrative: sector / currency pies, top-contribution
bar chart, and portfolio-vs-benchmark comparison. Uses ``canvas`` primitives
only (wedges, rectangles, text) — no reportlab.graphics dependency — which
keeps the binary surface small and styling identical to the rest of the
cover.

The colour rotation is shared with the SVG renderer via
:mod:`charts._color_for`: the first six slices pull from the locked design
palette, then a deterministic golden-ratio HSL ramp picks up from there.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

from .charts import _color_for, _format_pct, _format_signed_chf
from .data import (
    BenchmarkComparison,
    PerformancePosition,
    PerformanceSection,
    SectorAllocation,
)
from .design import PALETTE

_FONT_BODY = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


# ---------------------------------------------------------------------------
# Pie chart (donut) with side legend
# ---------------------------------------------------------------------------


def draw_pie(
    c: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    allocations: Sequence[SectorAllocation],
) -> None:
    """Draw a titled donut pie with a side legend inside the given box.

    (x, y) is the bottom-left corner of the card; width/height the drawable
    extent. Empty allocations render as just the title so the card keeps its
    slot in the grid.
    """
    _draw_card_title(c, x=x, y=y + height, title=title, width=width)

    rows = [a for a in allocations if a.weight_pct > 0]
    if not rows:
        _draw_empty(c, x=x, y=y, width=width, height=height - 18)
        return

    total_pct = sum((a.weight_pct for a in rows), Decimal("0"))
    if total_pct <= 0:
        return

    pie_size = min(width * 0.45, height - 22)
    pie_x0 = x
    pie_y0 = y + (height - 22 - pie_size) / 2
    cx = pie_x0 + pie_size / 2
    cy = pie_y0 + pie_size / 2
    radius = pie_size / 2 - 4

    start_angle = 90.0  # start at 12 o'clock
    for idx, alloc in enumerate(rows):
        extent = -float(alloc.weight_pct / total_pct * Decimal(360))
        c.setFillColor(HexColor(_color_for(idx)))
        c.setStrokeColor(HexColor(PALETTE["paper"]))
        c.setLineWidth(1)
        c.wedge(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            start_angle,
            extent,
            stroke=1,
            fill=1,
        )
        start_angle += extent

    # Donut hole — paints over the inner disc in paper colour for a ring.
    c.setFillColor(HexColor(PALETTE["paper"]))
    c.setStrokeColor(HexColor(PALETTE["paper"]))
    c.circle(cx, cy, radius * 0.55, stroke=0, fill=1)

    # Legend on the right side of the card.
    legend_x = pie_x0 + pie_size + 10
    legend_top = y + height - 22 - 4
    row_h = 12
    for idx, alloc in enumerate(rows):
        ly = legend_top - (idx + 1) * row_h
        if ly < y + 4:
            break  # legend overflow — truncate rather than overlap next card
        c.setFillColor(HexColor(_color_for(idx)))
        c.rect(legend_x, ly + 1, 8, 8, stroke=0, fill=1)
        c.setFillColor(HexColor(PALETTE["ink"]))
        c.setFont(_FONT_BODY, 8)
        c.drawString(legend_x + 12, ly + 2, _truncate(alloc.label, 22))
        c.setFillColor(HexColor(PALETTE["ink_muted"]))
        c.drawRightString(x + width, ly + 2, f"{alloc.weight_pct}%")


# ---------------------------------------------------------------------------
# Signed horizontal bar chart — top P&L contributions
# ---------------------------------------------------------------------------


def draw_top_positions_bar(
    c: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    positions: Sequence[PerformancePosition],
    top_n: int = 10,
) -> None:
    """Horizontal signed-bar chart of top-contribution positions."""
    _draw_card_title(c, x=x, y=y + height, title=title, width=width)

    rows = [p for p in positions if p.total_pnl_chf != 0][:top_n]
    if not rows:
        _draw_empty(c, x=x, y=y, width=width, height=height - 18)
        return

    max_abs = max((abs(p.total_pnl_chf) for p in rows), default=Decimal("0"))
    if max_abs == 0:
        return

    chart_top = y + height - 22
    chart_bottom = y + 6
    bar_h = min(16.0, (chart_top - chart_bottom) / len(rows) - 2)
    row_gap = bar_h + 2

    left_col = 100
    right_col = 120
    chart_width = width - left_col - right_col
    zero_x = x + left_col + chart_width / 2

    # Zero axis.
    c.setStrokeColor(HexColor(PALETTE["rule"]))
    c.setLineWidth(0.5)
    c.line(zero_x, chart_top, zero_x, chart_bottom)

    for idx, pos in enumerate(rows):
        ty = chart_top - (idx + 1) * row_gap
        pnl = pos.total_pnl_chf
        w = float(abs(pnl)) / float(max_abs) * (chart_width / 2 - 4)

        if pnl >= 0:
            bx = zero_x
            color = PALETTE["positive"]
        else:
            bx = zero_x - w
            color = PALETTE["negative"]

        # Symbol label.
        c.setFillColor(HexColor(PALETTE["ink"]))
        c.setFont(_FONT_BODY, 8)
        symbol = pos.symbol or pos.isin or "?"
        c.drawRightString(x + left_col - 6, ty + 3, _truncate(symbol, 16))

        c.setFillColor(HexColor(color))
        c.setStrokeColor(HexColor(color))
        c.rect(bx, ty, w, bar_h, stroke=0, fill=1)

        # Value + optional return.
        amount = _format_signed_chf(pnl)
        ret_suffix = f"  ({_format_pct(pos.return_pct)})" if pos.return_pct is not None else ""
        c.setFillColor(HexColor(PALETTE["ink"] if pnl >= 0 else PALETTE["negative"]))
        c.drawRightString(x + width, ty + 3, _truncate(amount + ret_suffix, 26))


# ---------------------------------------------------------------------------
# Benchmark comparison — portfolio vs. reference indices
# ---------------------------------------------------------------------------


def draw_benchmark_bar(
    c: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    portfolio_return_pct: Decimal | None,
    benchmarks: Sequence[BenchmarkComparison],
) -> None:
    """Horizontal comparison: portfolio in accent, benchmarks neutral."""
    _draw_card_title(c, x=x, y=y + height, title=title, width=width)

    entries: list[tuple[str, Decimal, str]] = []
    if portfolio_return_pct is not None:
        entries.append(("Portfolio", portfolio_return_pct, PALETTE["accent"]))
    for b in benchmarks:
        entries.append((b.label, b.return_pct, PALETTE["primary_80"]))
    if not entries:
        _draw_empty(c, x=x, y=y, width=width, height=height - 18)
        return

    max_abs = max((abs(v) for _, v, _ in entries), default=Decimal("0")) or Decimal("1")

    chart_top = y + height - 22
    chart_bottom = y + 6
    bar_h = min(18.0, (chart_top - chart_bottom) / len(entries) - 4)
    row_gap = bar_h + 4

    left_col = 170
    right_col = 70
    chart_width = width - left_col - right_col
    zero_x = x + left_col + chart_width / 2

    c.setStrokeColor(HexColor(PALETTE["rule"]))
    c.setLineWidth(0.5)
    c.line(zero_x, chart_top, zero_x, chart_bottom)

    for idx, (label, value, color) in enumerate(entries):
        ty = chart_top - (idx + 1) * row_gap
        w = float(abs(value)) / float(max_abs) * (chart_width / 2 - 4)
        bx = zero_x if value >= 0 else zero_x - w

        c.setFillColor(HexColor(PALETTE["ink"]))
        c.setFont(_FONT_BODY, 9)
        c.drawRightString(x + left_col - 6, ty + 4, _truncate(label, 28))

        c.setFillColor(HexColor(color))
        c.setStrokeColor(HexColor(color))
        c.rect(bx, ty, w, bar_h, stroke=0, fill=1)

        c.setFillColor(HexColor(PALETTE["ink"]))
        c.drawRightString(x + width, ty + 4, _format_pct(value))


# ---------------------------------------------------------------------------
# Tabular per-position summary — fits beneath the charts on page 2.
# ---------------------------------------------------------------------------


def draw_position_table(
    c: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    positions: Sequence[PerformancePosition],
    top_n: int = 15,
) -> None:
    """Compact table of the top ``top_n`` positions by absolute P&L."""
    _draw_card_title(c, x=x, y=y + height, title=title, width=width)

    rows = list(positions[:top_n])
    if not rows:
        _draw_empty(c, x=x, y=y, width=width, height=height - 18)
        return

    headers = ["Symbol", "Bezeichnung", "Eröffnung", "Schluss", "P&L CHF", "Rendite"]
    col_widths = [
        width * 0.10,
        width * 0.38,
        width * 0.14,
        width * 0.14,
        width * 0.14,
        width * 0.10,
    ]
    col_x = [x]
    for w in col_widths:
        col_x.append(col_x[-1] + w)

    header_y = y + height - 34
    c.setFillColor(HexColor(PALETTE["primary"]))
    c.rect(x, header_y, width, 14, stroke=0, fill=1)
    c.setFillColor(HexColor(PALETTE["paper"]))
    c.setFont(_FONT_BOLD, 8)
    for idx, header in enumerate(headers):
        if idx <= 1:
            c.drawString(col_x[idx] + 4, header_y + 4, header)
        else:
            c.drawRightString(col_x[idx + 1] - 4, header_y + 4, header)

    row_h = 12
    max_rows = int((header_y - y) // row_h)
    rows = rows[:max_rows]

    c.setFont(_FONT_BODY, 8)
    for i, p in enumerate(rows):
        ry = header_y - (i + 1) * row_h
        if i % 2 == 0:
            c.setFillColor(HexColor(PALETTE["paper_warm"]))
            c.setStrokeColor(HexColor(PALETTE["paper_warm"]))
            c.rect(x, ry, width, row_h, stroke=0, fill=1)

        c.setFillColor(HexColor(PALETTE["ink"]))
        c.drawString(col_x[0] + 4, ry + 3, _truncate(p.symbol or p.isin or "?", 10))
        c.drawString(col_x[1] + 4, ry + 3, _truncate(p.description or "", 46))
        c.drawRightString(col_x[3] - 4, ry + 3, _format_signed_chf(p.opening_value_chf))
        c.drawRightString(col_x[4] - 4, ry + 3, _format_signed_chf(p.closing_value_chf))

        pnl_color = PALETTE["positive"] if p.total_pnl_chf >= 0 else PALETTE["negative"]
        c.setFillColor(HexColor(pnl_color))
        c.drawRightString(col_x[5] - 4, ry + 3, _format_signed_chf(p.total_pnl_chf))
        if p.return_pct is not None:
            c.drawRightString(col_x[6] - 4, ry + 3, _format_pct(p.return_pct))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _draw_card_title(c: canvas.Canvas, *, x: float, y: float, title: str, width: float) -> None:
    c.setFillColor(HexColor(PALETTE["ink_muted"]))
    c.setFont(_FONT_BOLD, 9)
    c.drawString(x, y - 10, title.upper())
    c.setStrokeColor(HexColor(PALETTE["rule"]))
    c.setLineWidth(0.5)
    c.line(x, y - 13, x + width, y - 13)


def _draw_empty(c: canvas.Canvas, *, x: float, y: float, width: float, height: float) -> None:
    c.setFillColor(HexColor(PALETTE["ink_muted"]))
    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(x + width / 2, y + height / 2, "Keine Daten")


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def has_charts(section: PerformanceSection) -> bool:
    """Any chartable data on the section?"""
    return bool(section.positions or section.sectors or section.currencies or section.benchmarks)
