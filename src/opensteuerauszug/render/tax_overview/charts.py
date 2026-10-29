"""Inline SVG chart helpers for the performance tab.

Produces self-contained SVG strings (no JS, no external assets) so the
generated HTML remains one file. Charts are defensive: given empty data
they return an empty string so the template can ``{{ chart or "" }}``
without guarding.

The palette intentionally rotates through the locked design tokens
(``primary``, ``accent``, ``primary_80``) before falling back to a
deterministic HSL ramp — keeps branding consistent for small n, and
remains legible once a large portfolio produces 20+ sectors.
"""

from __future__ import annotations

import colorsys
import math
from decimal import Decimal
from typing import List, Sequence

from .data import BenchmarkComparison, PerformancePosition, SectorAllocation
from .design import CHART_SERIES, PALETTE

ZERO = Decimal("0")

# Validated categorical series first, then deterministic HSL ramp for overflow.
_SLICE_COLORS = list(CHART_SERIES)


def _color_for(index: int) -> str:
    if index < len(_SLICE_COLORS):
        return _SLICE_COLORS[index]
    # Golden-ratio hue hop keeps adjacent slices visibly different; 0.55
    # saturation / 0.45 lightness lands in a muted, print-friendly band.
    hue = (index * 0.6180339887) % 1.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.45, 0.55)
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Pie chart — sector / currency allocation
# ---------------------------------------------------------------------------


def render_pie(
    allocations: Sequence[SectorAllocation],
    *,
    size: int = 280,
    aria_label: str = "Pie chart",
) -> str:
    """Render a donut pie with side legend.

    ``allocations`` must be sorted in display order; weight_pct is used for
    angular extent. Slices with zero weight are skipped (they would render
    as zero-arc paths and pollute the legend).
    """
    rows = [a for a in allocations if a.weight_pct > 0]
    if not rows:
        return ""

    radius_outer = size / 2 - 10
    radius_inner = radius_outer * 0.55
    cx = cy = size / 2

    total_pct = sum((a.weight_pct for a in rows), ZERO)
    if total_pct <= 0:
        return ""

    parts: List[str] = []
    # Main SVG canvas includes both the donut (size × size on the left) and
    # the legend column to its right; width grows with the legend entries.
    legend_x = size + 16
    row_height = 18
    legend_width = 240
    canvas_width = legend_x + legend_width
    canvas_height = max(size, row_height * len(rows) + 16)

    parts.append(
        f'<svg viewBox="0 0 {canvas_width} {canvas_height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{_escape(aria_label)}">'
    )

    # Donut slices.
    cumulative = Decimal("0")
    for idx, alloc in enumerate(rows):
        start_pct = cumulative
        end_pct = cumulative + alloc.weight_pct
        cumulative = end_pct

        start_angle = float(start_pct) / float(total_pct) * 2 * math.pi - math.pi / 2
        end_angle = float(end_pct) / float(total_pct) * 2 * math.pi - math.pi / 2
        large_arc = 1 if (end_angle - start_angle) > math.pi else 0

        color = _color_for(idx)
        label = _escape(f"{alloc.label}: {alloc.weight_pct}%")

        # A slice spanning the full circle would have coincident arc start and
        # end points, which the SVG spec renders as nothing. Draw a ring instead.
        if end_angle - start_angle >= 2 * math.pi - 1e-9:
            ring_radius = (radius_outer + radius_inner) / 2
            ring_width = radius_outer - radius_inner
            parts.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{ring_radius:.2f}" '
                f'fill="none" stroke="{color}" stroke-width="{ring_width:.2f}">'
                f"<title>{label}</title></circle>"
            )
            continue

        x0 = cx + radius_outer * math.cos(start_angle)
        y0 = cy + radius_outer * math.sin(start_angle)
        x1 = cx + radius_outer * math.cos(end_angle)
        y1 = cy + radius_outer * math.sin(end_angle)
        ix0 = cx + radius_inner * math.cos(end_angle)
        iy0 = cy + radius_inner * math.sin(end_angle)
        ix1 = cx + radius_inner * math.cos(start_angle)
        iy1 = cy + radius_inner * math.sin(start_angle)

        path = (
            f"M {x0:.2f} {y0:.2f} "
            f"A {radius_outer:.2f} {radius_outer:.2f} 0 {large_arc} 1 {x1:.2f} {y1:.2f} "
            f"L {ix0:.2f} {iy0:.2f} "
            f"A {radius_inner:.2f} {radius_inner:.2f} 0 {large_arc} 0 {ix1:.2f} {iy1:.2f} "
            "Z"
        )
        parts.append(
            f'<path d="{path}" fill="{color}" stroke="#ffffff" stroke-width="1">'
            f"<title>{label}</title></path>"
        )

    # Legend.
    for idx, alloc in enumerate(rows):
        y = 8 + idx * row_height
        color = _color_for(idx)
        label = _escape(alloc.label)
        pct = _escape(f"{alloc.weight_pct}%")
        parts.append(f'<rect x="{legend_x}" y="{y}" width="12" height="12" fill="{color}" />')
        parts.append(
            f'<text x="{legend_x + 18}" y="{y + 10}" '
            f'font-size="12" fill="{PALETTE["ink"]}">{label}</text>'
        )
        parts.append(
            f'<text x="{legend_x + legend_width - 4}" y="{y + 10}" '
            f'font-size="12" text-anchor="end" '
            f'fill="{PALETTE["ink_muted"]}">{pct}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Bar chart — signed P&L per position (or return per position)
# ---------------------------------------------------------------------------


def render_bar(
    positions: Sequence[PerformancePosition],
    *,
    width: int = 720,
    bar_height: int = 22,
    top_n: int = 12,
) -> str:
    """Horizontal signed-bar chart of ``top_n`` positions by P&L magnitude.

    Positive bars extend right in the ``positive`` token colour; negative
    bars extend left in ``negative``. Labels (symbol + CHF amount) sit on
    the outer edge so the bar itself stays uncluttered.
    """
    rows = [p for p in positions if p.total_pnl_chf != 0][:top_n]
    if not rows:
        return ""

    max_abs = max((abs(p.total_pnl_chf) for p in rows), default=Decimal("0"))
    if max_abs == 0:
        return ""

    left_col = 140  # symbol
    right_col = 170  # amount
    chart_width = width - left_col - right_col
    zero_x = left_col + chart_width / 2

    height = bar_height * len(rows) + 20
    parts: List[str] = [
        f'<svg viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Bar chart of position contribution to portfolio P&amp;L">'
    ]

    # Center line.
    parts.append(
        f'<line x1="{zero_x}" y1="0" x2="{zero_x}" y2="{height}" '
        f'stroke="{PALETTE["rule"]}" stroke-width="1" />'
    )

    for idx, pos in enumerate(rows):
        y = 10 + idx * bar_height
        pnl = pos.total_pnl_chf
        w = float(abs(pnl)) / float(max_abs) * (chart_width / 2 - 4)
        if pnl >= 0:
            x = zero_x
            color = PALETTE["positive"]
        else:
            x = zero_x - w
            color = PALETTE["negative"]
        symbol = _escape((pos.symbol or pos.isin or "?")[:20])
        parts.append(
            f'<text x="{left_col - 8}" y="{y + bar_height / 2 + 4}" '
            f'font-size="12" text-anchor="end" '
            f'fill="{PALETTE["ink"]}">{symbol}</text>'
        )
        parts.append(
            f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="{bar_height - 6}" '
            f'fill="{color}" rx="2" ry="2">'
            f'<title>{_escape(pos.description)}</title></rect>'
        )
        amount = _format_signed_chf(pnl)
        ret_suffix = f"  ({_format_pct(pos.return_pct)})" if pos.return_pct is not None else ""
        parts.append(
            f'<text x="{width - 8}" y="{y + bar_height / 2 + 4}" '
            f'font-size="12" text-anchor="end" '
            f'fill="{PALETTE["ink"] if pnl >= 0 else PALETTE["negative"]}">'
            f"{_escape(amount + ret_suffix)}</text>"
        )

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Benchmark comparison — portfolio return vs. reference indices
# ---------------------------------------------------------------------------


def render_benchmark_comparison(
    portfolio_return_pct: Decimal | None,
    benchmarks: Sequence[BenchmarkComparison],
    *,
    width: int = 720,
    bar_height: int = 28,
) -> str:
    """Horizontal bar chart comparing the portfolio's return to benchmarks.

    The portfolio bar is drawn first with the ``primary`` accent so it reads
    as the protagonist; benchmarks follow in ``primary_80`` (neutral).
    """
    entries: List[tuple[str, Decimal, str, str | None]] = []
    if portfolio_return_pct is not None:
        entries.append(("Portfolio", portfolio_return_pct, PALETTE["accent"], None))
    for b in benchmarks:
        entries.append((b.label, b.return_pct, PALETTE["primary_80"], b.note))
    if not entries:
        return ""

    max_abs = max((abs(v) for _, v, _, _ in entries), default=Decimal("0"))
    if max_abs == 0:
        max_abs = Decimal("1")

    left_col = 200
    right_col = 100
    chart_width = width - left_col - right_col
    zero_x = left_col + chart_width / 2

    height = bar_height * len(entries) + 20
    parts: List[str] = [
        f'<svg viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Portfolio return vs. benchmarks">'
    ]
    parts.append(
        f'<line x1="{zero_x}" y1="0" x2="{zero_x}" y2="{height}" '
        f'stroke="{PALETTE["rule"]}" stroke-width="1" />'
    )

    for idx, (label, value, color, note) in enumerate(entries):
        y = 10 + idx * bar_height
        w = float(abs(value)) / float(max_abs) * (chart_width / 2 - 4)
        if value >= 0:
            x = zero_x
        else:
            x = zero_x - w
        parts.append(
            f'<text x="{left_col - 8}" y="{y + bar_height / 2 + 4}" '
            f'font-size="12" text-anchor="end" '
            f'fill="{PALETTE["ink"]}">{_escape(label)}</text>'
        )
        title = _escape(note) if note else ""
        parts.append(
            f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="{bar_height - 8}" '
            f'fill="{color}" rx="3" ry="3">'
            + (f"<title>{title}</title>" if title else "")
            + "</rect>"
        )
        pct = _format_pct(value)
        parts.append(
            f'<text x="{width - 8}" y="{y + bar_height / 2 + 4}" '
            f'font-size="12" text-anchor="end" '
            f'fill="{PALETTE["ink"]}">{_escape(pct)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Formatting helpers (mirror html.format_* but return ASCII so they're safe
# to embed in SVG <text> nodes without extra escaping).
# ---------------------------------------------------------------------------


def _format_signed_chf(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    int_part, _, dec_part = f"{abs(value):.0f}".partition(".")
    return f"{sign}CHF {_group_thousands(int_part)}"


def _format_pct(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:+.2f}%"


def _group_thousands(int_str: str) -> str:
    if len(int_str) <= 3:
        return int_str
    groups = [int_str[max(i - 3, 0) : i] for i in range(len(int_str), 0, -3)]
    return "'".join(reversed(groups))
