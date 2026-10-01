"""Single-page PDF cover for the tax-overview dashboard.

The PDF is a one-page executive summary: title, headline KPIs, the
Vermögenszuwachs waterfall, and a reconciliation marker. It is *not* a
replacement for the xlsx — it's the page a preparer would clip to the top
of a paper submission or share by email for a first look.

Third-party safety: KS 36 content is omitted entirely when
``data.preparer_mode`` is false (same gate as the xlsx hidden sheets and
the HTML section). A short preparer-only summary line appears in
preparer-mode output so the preparer sees the status at a glance.
"""

from __future__ import annotations

import io
from decimal import Decimal

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .data import TaxOverviewData
from .design import PALETTE
from .html import format_chf, format_pct_signed
from .pdf_charts import (
    draw_benchmark_bar,
    draw_pie,
    draw_position_table,
    draw_top_positions_bar,
    has_charts,
)
from .waterfall import DEFAULT_RECONCILIATION_TOLERANCE_CHF

# Typography — Helvetica is built into every PDF reader, so the cover works
# without embedding Inter. Phase 10 may add a /Resources font embed if we
# want the cover to visually match the HTML exactly.
_FONT_BODY = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_OBLIQUE = "Helvetica-Oblique"

# Page geometry (A4, 595 × 842 pt). Margins match the spec's 18 mm default.
_MARGIN = 18 * 72 / 25.4  # ≈ 51 pt


def render_pdf_cover(data: TaxOverviewData) -> bytes:
    """Render the single-page PDF cover for the dashboard.

    Returns the PDF document as bytes. Deterministic: given identical
    ``data``, the byte output is identical (modulo reportlab's xref table
    which is already deterministic by construction).
    """
    buffer = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"Steuer-Übersicht {data.tax_year}")
    c.setAuthor("OpenSteuerAuszug")
    c.setSubject(f"Tax overview {data.tax_year} — broker {data.broker}")

    cursor_y = height - _MARGIN
    cursor_y = _draw_header(c, cursor_y, width, data)
    cursor_y = _draw_kpi_grid(c, cursor_y, width, data)
    cursor_y = _draw_performance_line(c, cursor_y, width, data)
    cursor_y = _draw_waterfall_block(c, cursor_y, width, data)
    cursor_y = _draw_reconciliation(c, cursor_y, width, data)
    if data.preparer_mode:
        cursor_y = _draw_ks36_summary(c, cursor_y, width, data)
    _draw_footer(c, width, data)

    c.showPage()
    # Second page: performance charts, only when the pipeline attached a
    # Performance section with actual data to plot.
    if data.performance is not None and has_charts(data.performance):
        _draw_performance_page(c, width, height, data)
        c.showPage()
    c.save()
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _draw_header(c: canvas.Canvas, y: float, width: float, data: TaxOverviewData) -> float:
    c.setFillColor(HexColor(PALETTE["primary"]))
    c.setFont(_FONT_BOLD, 22)
    c.drawString(_MARGIN, y - 22, f"Steuer-Übersicht {data.tax_year}")

    meta = f"Broker: {data.broker}"
    if data.preparer_mode:
        meta += "  ·  Vorbereiter-Modus"
    c.setFillColor(HexColor(PALETTE["ink_muted"]))
    c.setFont(_FONT_BODY, 10)
    c.drawString(_MARGIN, y - 40, meta)

    # Thin rule beneath the header.
    c.setStrokeColor(HexColor(PALETTE["rule"]))
    c.setLineWidth(0.5)
    c.line(_MARGIN, y - 50, width - _MARGIN, y - 50)
    return y - 70


def _draw_kpi_grid(c: canvas.Canvas, y: float, width: float, data: TaxOverviewData) -> float:
    tiles: list[tuple[str, Decimal]] = [
        ("Eröffnungswert", data.opening_value_chf),
        ("Schlusswert", data.closing_value_chf),
        ("Dividenden", data.total_dividends_chf()),
        ("Zinsen", data.total_interest_chf()),
        ("Quellensteuer", data.total_withholding_tax_chf()),
        ("DA-1 rückforderbar", data.total_da1_recoverable_chf()),
    ]

    cols = 3
    usable = width - 2 * _MARGIN
    gap = 8
    tile_w = (usable - gap * (cols - 1)) / cols
    tile_h = 54

    for idx, (label, value) in enumerate(tiles):
        row, col = divmod(idx, cols)
        tx = _MARGIN + col * (tile_w + gap)
        ty = y - row * (tile_h + gap) - tile_h

        c.setFillColor(HexColor(PALETTE["paper_warm"]))
        c.setStrokeColor(HexColor(PALETTE["rule"]))
        c.setLineWidth(0.5)
        c.rect(tx, ty, tile_w, tile_h, stroke=1, fill=1)

        c.setFillColor(HexColor(PALETTE["ink_muted"]))
        c.setFont(_FONT_BODY, 7)
        c.drawString(tx + 8, ty + tile_h - 14, label.upper())

        c.setFillColor(HexColor(PALETTE["ink"]))
        c.setFont(_FONT_BOLD, 14)
        c.drawString(tx + 8, ty + 10, format_chf(value))

    rows = (len(tiles) + cols - 1) // cols
    return y - rows * (tile_h + gap) - 10


def _draw_performance_line(
    c: canvas.Canvas, y: float, width: float, data: TaxOverviewData
) -> float:
    """One-line Performance KPI: total P&L in CHF + Modified-Dietz return."""
    perf = data.performance
    if perf is None:
        return y
    summary = perf.summary
    parts = [f"Gesamt-P&L: {format_chf(summary.total_pnl_chf)}"]
    if summary.money_weighted_return_pct is not None:
        parts.append(f"Rendite (Dietz): {format_pct_signed(summary.money_weighted_return_pct)}")
    if summary.simple_return_pct is not None:
        parts.append(f"Rendite (einfach): {format_pct_signed(summary.simple_return_pct)}")
    color = PALETTE["positive"] if summary.total_pnl_chf >= 0 else PALETTE["negative"]
    c.setFillColor(HexColor(color))
    c.setFont(_FONT_BOLD, 10)
    c.drawString(_MARGIN, y, "   ·   ".join(parts))
    return y - 16


def _draw_waterfall_block(c: canvas.Canvas, y: float, width: float, data: TaxOverviewData) -> float:
    c.setFillColor(HexColor(PALETTE["primary"]))
    c.setFont(_FONT_BOLD, 12)
    c.drawString(_MARGIN, y, "Vermögenszuwachs")
    y -= 18

    c.setFont(_FONT_BODY, 10)
    row_h = 14
    amount_x = width - _MARGIN
    for line in data.waterfall.as_lines():
        c.setFillColor(HexColor(PALETTE["ink"]))
        c.drawString(_MARGIN, y, line.label)
        c.setFillColor(HexColor(_color_for_kind(line.kind)))
        c.drawRightString(amount_x, y, format_chf(line.amount_chf))
        y -= row_h

    # Thin rule, then the residual.
    c.setStrokeColor(HexColor(PALETTE["rule"]))
    c.line(_MARGIN, y + 4, width - _MARGIN, y + 4)
    residual = data.waterfall.residual
    c.setFillColor(HexColor(PALETTE["ink_muted"]))
    c.setFont(_FONT_BOLD, 10)
    c.drawString(_MARGIN, y - 8, "Differenz (Soll − Ist)")
    c.setFillColor(HexColor(_color_for_residual(residual)))
    c.drawRightString(amount_x, y - 8, format_chf(residual))
    return y - 28


def _draw_reconciliation(c: canvas.Canvas, y: float, width: float, data: TaxOverviewData) -> float:
    reconciles = data.waterfall.reconciles(DEFAULT_RECONCILIATION_TOLERANCE_CHF)
    if reconciles:
        label = (
            f"Abstimmung: innerhalb ±CHF "
            f"{DEFAULT_RECONCILIATION_TOLERANCE_CHF.normalize():f}  ✓"
        )
        color = PALETTE["positive"]
    else:
        label = (
            f"Abstimmung ausserhalb Toleranz — Differenz " f"{format_chf(data.waterfall.residual)}"
        )
        color = PALETTE["negative"]
    c.setFillColor(HexColor(color))
    c.setFont(_FONT_BOLD, 10)
    c.drawString(_MARGIN, y, label)
    return y - 20


def _draw_ks36_summary(c: canvas.Canvas, y: float, width: float, data: TaxOverviewData) -> float:
    counts = {"green": 0, "amber": 0, "red": 0}
    for crit in data.ks36_criteria:
        counts[crit.status] = counts.get(crit.status, 0) + 1
    summary = (
        f"KS 36 Selbstprüfung: {len(data.ks36_criteria)} Kriterien  "
        f"({counts.get('green', 0)} grün · {counts.get('amber', 0)} amber · "
        f"{counts.get('red', 0)} rot)"
    )
    c.setFillColor(HexColor(PALETTE["accent"]))
    c.setFont(_FONT_OBLIQUE, 9)
    c.drawString(_MARGIN, y, summary)
    return y - 16


def _draw_performance_page(
    c: canvas.Canvas, width: float, height: float, data: TaxOverviewData
) -> None:
    """Second page: full-width benchmark chart + side-by-side pies + bar chart."""
    perf = data.performance
    assert perf is not None  # guarded by caller

    # Page header.
    c.setFillColor(HexColor(PALETTE["primary"]))
    c.setFont(_FONT_BOLD, 20)
    c.drawString(_MARGIN, height - _MARGIN - 4, f"Performance {data.tax_year}")
    c.setFillColor(HexColor(PALETTE["ink_muted"]))
    c.setFont(_FONT_BODY, 10)
    c.drawString(
        _MARGIN,
        height - _MARGIN - 22,
        "P&L-Beiträge, Sektor- und Währungsallokation, Benchmark-Vergleich",
    )
    c.setStrokeColor(HexColor(PALETTE["rule"]))
    c.setLineWidth(0.5)
    c.line(_MARGIN, height - _MARGIN - 32, width - _MARGIN, height - _MARGIN - 32)

    # Page geometry — two rows of charts above a position table.
    usable_w = width - 2 * _MARGIN
    gap = 12
    top_y = height - _MARGIN - 44

    # Row 1: benchmark chart (full width).
    bench_h = 130
    draw_benchmark_bar(
        c,
        x=_MARGIN,
        y=top_y - bench_h,
        width=usable_w,
        height=bench_h,
        title="Portfolio vs. Benchmarks",
        portfolio_return_pct=perf.summary.money_weighted_return_pct,
        benchmarks=perf.benchmarks,
    )

    # Row 2: sector pie + currency pie side by side.
    row2_y = top_y - bench_h - gap
    pie_h = 170
    pie_w = (usable_w - gap) / 2
    draw_pie(
        c,
        x=_MARGIN,
        y=row2_y - pie_h,
        width=pie_w,
        height=pie_h,
        title="Sektor-Allokation",
        allocations=perf.sectors,
    )
    draw_pie(
        c,
        x=_MARGIN + pie_w + gap,
        y=row2_y - pie_h,
        width=pie_w,
        height=pie_h,
        title="Währungs-Allokation",
        allocations=perf.currencies,
    )

    # Row 3: top-contribution bar chart.
    row3_y = row2_y - pie_h - gap
    bar_h = 200
    draw_top_positions_bar(
        c,
        x=_MARGIN,
        y=row3_y - bar_h,
        width=usable_w,
        height=bar_h,
        title="Top-Beiträge zum Ergebnis",
        positions=perf.positions,
    )

    # Row 4: compact position table, up to the footer.
    row4_y = row3_y - bar_h - gap
    table_h = max(row4_y - _MARGIN - 24, 0)
    if table_h > 40 and perf.positions:
        draw_position_table(
            c,
            x=_MARGIN,
            y=row4_y - table_h,
            width=usable_w,
            height=table_h,
            title="Positionen im Detail",
            positions=perf.positions,
        )

    # Footer for the charts page.
    c.setFillColor(HexColor(PALETTE["ink_muted"]))
    c.setFont(_FONT_BODY, 8)
    c.drawString(
        _MARGIN,
        _MARGIN / 2,
        f"Performance-Bericht  ·  Steuerjahr {data.tax_year}  ·  Broker {data.broker}",
    )


def _draw_footer(c: canvas.Canvas, width: float, data: TaxOverviewData) -> None:
    c.setFillColor(HexColor(PALETTE["ink_muted"]))
    c.setFont(_FONT_BODY, 8)
    c.drawString(
        _MARGIN,
        _MARGIN / 2,
        f"Generiert von OpenSteuerAuszug  ·  Steuerjahr {data.tax_year}  ·  "
        f"Broker {data.broker}",
    )


def _color_for_kind(kind: str) -> str:
    if kind == "inflow":
        return PALETTE["positive"]
    if kind == "outflow":
        return PALETTE["negative"]
    return PALETTE["ink"]


def _color_for_residual(residual: Decimal) -> str:
    if abs(residual) <= DEFAULT_RECONCILIATION_TOLERANCE_CHF:
        return PALETTE["ink_muted"]
    return PALETTE["negative"]
