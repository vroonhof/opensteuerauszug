"""HTML writer for the tax-overview dashboard.

Produces a single self-contained HTML document — no external CSS, no JS —
that mirrors the visible workbook. The CSS ``:root`` block is emitted via
:func:`design.css_variables` so the workbook and the HTML share one
palette/typography source.

Third-party safety mirrors the xlsx gate: the KS 36 section is emitted only
when ``data.preparer_mode`` is true. Traffic-light classes (``ampel-*``)
are restricted to that section — a test iterates the rendered document to
prove they never leak into the visible sections.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional, cast

from jinja2 import Environment

from .charts import render_bar, render_benchmark_comparison, render_pie
from .data import TaxOverviewData
from .design import css_variables

CHF_QUANTUM = Decimal("0.01")


def format_chf(value: Decimal) -> str:
    """Swiss CHF: ``CHF 12'345.67``, ``-CHF 12'345.67``, ``CHF 0.00``.

    Apostrophe thousands separator and dot decimal are the Swiss locale;
    openpyxl emits the same in the workbook via ``NUMBER_FORMAT_CHF``.
    """
    quantized = value.quantize(CHF_QUANTUM, rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    int_part, _, dec_part = f"{abs(quantized):.2f}".partition(".")
    return f"{sign}CHF {_group_thousands(int_part)}.{dec_part}"


def format_number(value: Decimal, *, decimals: int = 2) -> str:
    """Plain Swiss-grouped number, no currency prefix."""
    quantum = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    quantized = value.quantize(quantum, rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    if decimals:
        int_part, _, dec_part = f"{abs(quantized):.{decimals}f}".partition(".")
        return f"{sign}{_group_thousands(int_part)}.{dec_part}"
    int_part = f"{abs(quantized):.0f}"
    return f"{sign}{_group_thousands(int_part)}"


def format_percent(value: Decimal) -> str:
    """Format a decimal rate (``0.15``) as ``15.0%``."""
    return format_number(value * 100, decimals=1) + "%"


def format_pct_signed(value: Optional[Decimal]) -> str:
    """Pre-scaled percent (``6.24`` → ``+6.24%``). Empty string for ``None``."""
    if value is None:
        return ""
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "+" if quantized > 0 else ("-" if quantized < 0 else "±")
    int_part, _, dec_part = f"{abs(quantized):.2f}".partition(".")
    return f"{sign}{_group_thousands(int_part)}.{dec_part}%"


def format_date(value: Optional[date]) -> str:
    """Swiss date format: ``DD.MM.YYYY``; empty string for ``None``."""
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y")


def _group_thousands(int_str: str) -> str:
    """Insert apostrophes every three digits from the right."""
    if len(int_str) <= 3:
        return int_str
    groups = [int_str[max(i - 3, 0) : i] for i in range(len(int_str), 0, -3)]
    return "'".join(reversed(groups))


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

_TEMPLATE_SOURCE = """\
<!doctype html>
<html lang="de-CH">
<head>
<meta charset="utf-8">
<title>Steuer-Übersicht {{ data.tax_year }}</title>
<style>
{{ css_variables }}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
    margin: 0;
    font-family: var(--font-body);
    color: var(--color-ink);
    background: var(--color-paper);
    line-height: 1.45;
}
main {
    max-width: 1400px;
    margin: 0 auto;
    padding: calc(var(--grid-unit) * 4);
}
h1, h2, h3 {
    font-family: var(--font-display);
    color: var(--color-primary);
    margin: 0 0 var(--grid-unit) 0;
}
h1 { font-size: 1.875rem; letter-spacing: -0.01em; }
main > header {
    padding-bottom: calc(var(--grid-unit) * 2);
    border-bottom: 3px double var(--color-rule);
}
h2 {
    font-size: 1.25rem;
    margin-top: 0;
    padding-bottom: var(--grid-unit);
    border-bottom: 2px solid var(--color-rule);
}
h3 { font-size: 1rem; margin-top: calc(var(--grid-unit) * 2); color: var(--color-ink-muted); }
.meta { color: var(--color-ink-muted); font-size: 0.875rem; margin-top: 0; }
/* Sticky wayfinding nav — reviewer jumps to any section without scrolling. */
.dashnav {
    position: sticky;
    top: 0;
    z-index: 10;
    background: var(--color-paper);
    border-bottom: 1px solid var(--color-rule);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.dashnav-inner {
    max-width: 1400px;
    margin: 0 auto;
    padding: calc(var(--grid-unit) * 1.5) calc(var(--grid-unit) * 4);
    display: flex;
    flex-wrap: wrap;
    gap: var(--grid-unit);
    align-items: center;
}
.dashnav-brand {
    font-family: var(--font-display);
    color: var(--color-primary);
    font-weight: 700;
    margin-right: calc(var(--grid-unit) * 2);
    white-space: nowrap;
}
.dashnav-brand small {
    color: var(--color-ink-muted);
    font-weight: 400;
    font-size: 0.8125rem;
    margin-left: var(--grid-unit);
}
.dashnav a {
    color: var(--color-ink);
    text-decoration: none;
    padding: calc(var(--grid-unit) / 2) var(--grid-unit);
    border-radius: 3px;
    font-size: 0.8125rem;
    white-space: nowrap;
    transition: background 0.1s ease;
}
.dashnav a:hover { background: var(--color-paper-warm); color: var(--color-primary); }
.dashnav a .count {
    color: var(--color-ink-muted);
    font-variant-numeric: tabular-nums;
    font-size: 0.75rem;
    margin-left: 4px;
}
.dashnav a.preparer { color: var(--color-accent); }
section[id] {
    scroll-margin-top: 72px;
    background: var(--color-paper);
    border: 1px solid var(--color-rule);
    border-radius: 6px;
    box-shadow: 0 1px 2px rgba(15, 23, 32, 0.04);
    padding: calc(var(--grid-unit) * 3);
    margin-top: calc(var(--grid-unit) * 3);
    overflow-x: auto; /* wide tables scroll inside their card, never the page */
}
section[id]:first-of-type { margin-top: calc(var(--grid-unit) * 2); }
@media print {
    .dashnav { display: none; }
    section[id] { border: none; padding: 0; break-inside: avoid; }
    section[id] { page-break-inside: avoid; margin-top: calc(var(--grid-unit) * 2); }
}
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--grid-unit);
    margin-bottom: calc(var(--grid-unit) * 2);
}
.kpi-tile {
    background: var(--color-paper-warm);
    padding: calc(var(--grid-unit) * 2);
    border: 1px solid var(--color-rule);
    border-top: 3px solid var(--color-primary);
    border-radius: 4px;
}
.kpi-label {
    color: var(--color-ink-muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.kpi-value {
    font-family: var(--font-num);
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--color-ink);
    margin-top: calc(var(--grid-unit) / 2);
    font-variant-numeric: tabular-nums;
}
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
}
th, td {
    padding: 6px 10px;
    border-bottom: 1px solid var(--color-rule);
    text-align: left;
    vertical-align: top;
}
th {
    background: var(--color-paper-warm);
    color: var(--color-ink-muted);
    font-weight: 600;
    font-size: 0.6875rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 2px solid var(--color-primary);
    white-space: nowrap;
}
td.number, th.number {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
tbody tr:nth-child(even) td { background: var(--color-paper-warm); }
tbody tr:hover td { background: rgba(27, 58, 91, 0.06); }
.positive { color: var(--color-positive); }
.negative { color: var(--color-negative); }
.empty { color: var(--color-ink-muted); font-style: italic; }
/* Ampel classes: reserved for the KS36 section only. See test_phase8_html. */
.ampel-green { background: #C6E0B4; }
.ampel-amber { background: #FFE699; }
.ampel-red { background: #F4B3B3; }
.preparer-only {
    border-left: 4px solid var(--color-accent);
    padding-left: calc(var(--grid-unit) * 2);
    margin-top: calc(var(--grid-unit) * 4);
}
.preparer-only h2 { color: var(--color-accent); }
.chart-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: calc(var(--grid-unit) * 3);
    align-items: start;
    margin-top: calc(var(--grid-unit) * 2);
}
.chart-card {
    background: var(--color-paper-warm);
    border: 1px solid var(--color-rule);
    padding: calc(var(--grid-unit) * 2);
}
.chart-card h3 { margin-top: 0; }
.chart-card svg { width: 100%; height: auto; display: block; }
.benchmark-note { color: var(--color-ink-muted); font-size: 0.8125rem; margin-top: calc(var(--grid-unit) / 2); }
.table-wrap { overflow-x: auto; margin-top: calc(var(--grid-unit) * 2); }
</style>
</head>
<body>
<nav class="dashnav" aria-label="Abschnittsnavigation">
<div class="dashnav-inner">
<span class="dashnav-brand">Steuer-Übersicht <small>{{ data.tax_year }} · {{ data.broker }}</small></span>
<a href="#uebersicht">Übersicht</a>
{% if data.performance %}<a href="#performance">Performance</a>{% endif %}
<a href="#wertschriften">Wertschriften<span class="count">{{ data.positions|length }}</span></a>
<a href="#sg-verzeichnis">SG-Verzeichnis<span class="count">{{ data.verzeichnis_lines|length }}</span></a>
<a href="#da1">DA-1<span class="count">{{ data.da1_claims|length }}</span></a>
<a href="#kauf-verkauf">Kauf / Verkauf<span class="count">{{ data.orders|length }}</span></a>
<a href="#dividenden">Dividenden<span class="count">{{ data.dividends|length }}</span></a>
<a href="#zinsen">Zinsen<span class="count">{{ data.interest|length }}</span></a>
<a href="#gebuehren">Gebühren<span class="count">{{ data.fees|length }}</span></a>
<a href="#fx-kurse">FX<span class="count">{{ data.fx_rates|length }}</span></a>
{% if data.preparer_mode %}<a href="#ks36" class="preparer">KS 36</a>{% endif %}
</div>
</nav>
<main>
<header>
<h1>Steuer-Übersicht {{ data.tax_year }}</h1>
<p class="meta">Broker: {{ data.broker }}{% if data.preparer_mode %} · Vorbereiter-Modus{% endif %}</p>
</header>

<section id="uebersicht">
<h2>Übersicht</h2>
<div class="kpi-grid">
<div class="kpi-tile"><div class="kpi-label">Eröffnungswert</div><div class="kpi-value">{{ fmt_chf(data.opening_value_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Schlusswert</div><div class="kpi-value">{{ fmt_chf(data.closing_value_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Dividenden</div><div class="kpi-value">{{ fmt_chf(data.total_dividends_chf()) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Zinsen</div><div class="kpi-value">{{ fmt_chf(data.total_interest_chf()) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Quellensteuer</div><div class="kpi-value">{{ fmt_chf(data.total_withholding_tax_chf()) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">DA-1 rückforderbar</div><div class="kpi-value">{{ fmt_chf(data.total_da1_recoverable_chf()) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Gebühren</div><div class="kpi-value">{{ fmt_chf(data.total_fees_chf()) }}</div></div>
</div>

<h3>Vermögenszuwachs</h3>
<table>
<thead><tr><th>Bezeichnung</th><th>Art</th><th class="number">Betrag (CHF)</th></tr></thead>
<tbody>
{% for line in data.waterfall.as_lines() %}
<tr><td>{{ line.label }}</td><td>{{ line.kind }}</td><td class="number">{{ fmt_chf(line.amount_chf) }}</td></tr>
{% endfor %}
<tr><td><strong>Differenz</strong></td><td>residual</td><td class="number">{{ fmt_chf(data.waterfall.residual) }}</td></tr>
</tbody>
</table>
</section>

{% if data.performance %}
{% set perf = data.performance %}
<section id="performance">
<h2>Performance</h2>
<div class="kpi-grid">
<div class="kpi-tile"><div class="kpi-label">Eröffnung Wertschriften</div><div class="kpi-value">{{ fmt_chf(perf.summary.opening_value_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Schluss Wertschriften</div><div class="kpi-value">{{ fmt_chf(perf.summary.closing_value_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Gesamt-P&amp;L (Wertschriften)</div><div class="kpi-value {% if perf.summary.total_pnl_chf >= 0 %}positive{% else %}negative{% endif %}">{{ fmt_chf(perf.summary.total_pnl_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Rendite (Dietz)</div><div class="kpi-value {% if perf.summary.money_weighted_return_pct and perf.summary.money_weighted_return_pct >= 0 %}positive{% elif perf.summary.money_weighted_return_pct %}negative{% endif %}">{{ fmt_pct_signed(perf.summary.money_weighted_return_pct) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Rendite (einfach)</div><div class="kpi-value">{{ fmt_pct_signed(perf.summary.simple_return_pct) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Schluss Cash</div><div class="kpi-value">{{ fmt_chf(perf.summary.closing_cash_chf) }}{% if not perf.summary.cash_known %} <small style="color:var(--color-ink-muted);font-size:0.7rem;">(Eröffnung n/v)</small>{% endif %}</div></div>
<div class="kpi-tile"><div class="kpi-label">Einzahlungen</div><div class="kpi-value">{{ fmt_chf(perf.summary.deposits_gross_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Auszahlungen</div><div class="kpi-value">{{ fmt_chf(perf.summary.withdrawals_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Netto-Einzahlungen</div><div class="kpi-value">{{ fmt_chf(perf.summary.net_deposits_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Dividenden</div><div class="kpi-value">{{ fmt_chf(perf.summary.dividends_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Zinsen</div><div class="kpi-value">{{ fmt_chf(perf.summary.interest_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Gebühren</div><div class="kpi-value">{{ fmt_chf(perf.summary.fees_chf) }}</div></div>
</div>
{% if not perf.summary.cash_known %}
<p class="benchmark-note">Hinweis: Performance basiert auf Wertschriften ohne Cash-Salden (Eröffnungs-Cash im Flex-Export nicht enthalten).</p>
{% endif %}

<div class="chart-grid">
{% if perf.benchmarks or perf.summary.money_weighted_return_pct is not none %}
<div class="chart-card">
<h3>Portfolio vs. Benchmarks</h3>
{{ benchmark_svg|safe }}
<p class="benchmark-note">Benchmarks sind Total-Return-Werte (kalenderjährlich). Dienen der Orientierung — keine exakte Portfolio-Replikation.</p>
</div>
{% endif %}
{% if perf.sectors %}
<div class="chart-card">
<h3>Allokation nach Sektoren</h3>
{{ sectors_svg|safe }}
</div>
{% endif %}
{% if perf.currencies %}
<div class="chart-card">
<h3>Allokation nach Währungen</h3>
{{ currencies_svg|safe }}
</div>
{% endif %}
</div>

{% if perf.positions %}
<h3>Top-Beiträge zum Ergebnis</h3>
<div class="chart-card">{{ top_positions_svg|safe }}</div>

<h3>Positionen im Detail</h3>
<div class="table-wrap">
<table>
<thead><tr><th>Symbol</th><th>ISIN</th><th>Bezeichnung</th><th>Sektor</th><th>Währung</th><th class="number">Eröffnung</th><th class="number">Schluss</th><th class="number">Käufe</th><th class="number">Verkäufe</th><th class="number">Dividenden</th><th class="number">Realisiert</th><th class="number">Unrealisiert</th><th class="number">Gesamt-P&amp;L</th><th class="number">Rendite</th></tr></thead>
<tbody>
{% for p in perf.positions %}
<tr>
<td>{{ p.symbol }}</td>
<td>{{ p.isin or "" }}</td>
<td>{{ p.description }}</td>
<td>{{ p.sector }}</td>
<td>{{ p.currency }}</td>
<td class="number">{{ fmt_chf(p.opening_value_chf) }}</td>
<td class="number">{{ fmt_chf(p.closing_value_chf) }}</td>
<td class="number">{{ fmt_chf(p.buys_chf) }}</td>
<td class="number">{{ fmt_chf(p.sells_chf) }}</td>
<td class="number">{{ fmt_chf(p.dividends_chf) }}</td>
<td class="number {% if p.realized_pnl_chf >= 0 %}positive{% else %}negative{% endif %}">{{ fmt_chf(p.realized_pnl_chf) }}</td>
<td class="number {% if p.unrealized_pnl_chf >= 0 %}positive{% else %}negative{% endif %}">{{ fmt_chf(p.unrealized_pnl_chf) }}</td>
<td class="number {% if p.total_pnl_chf >= 0 %}positive{% else %}negative{% endif %}">{{ fmt_chf(p.total_pnl_chf) }}</td>
<td class="number {% if p.return_pct is not none and p.return_pct >= 0 %}positive{% elif p.return_pct is not none %}negative{% endif %}">{{ fmt_pct_signed(p.return_pct) }}</td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
{% endif %}

{% if perf.sectors %}
<h3>Sektor-Aggregation</h3>
<table>
<thead><tr><th>Sektor</th><th class="number">Marktwert CHF</th><th class="number">Gewicht</th><th class="number">P&amp;L CHF</th></tr></thead>
<tbody>
{% for s in perf.sectors %}
<tr><td>{{ s.label }}</td><td class="number">{{ fmt_chf(s.market_value_chf) }}</td><td class="number">{{ fmt_pct_signed(s.weight_pct) }}</td><td class="number {% if s.pnl_chf >= 0 %}positive{% else %}negative{% endif %}">{{ fmt_chf(s.pnl_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% endif %}

{% if perf.currencies %}
<h3>Währungs-Aggregation</h3>
<table>
<thead><tr><th>Währung</th><th class="number">Marktwert CHF</th><th class="number">Gewicht</th><th class="number">P&amp;L CHF</th></tr></thead>
<tbody>
{% for c in perf.currencies %}
<tr><td>{{ c.label }}</td><td class="number">{{ fmt_chf(c.market_value_chf) }}</td><td class="number">{{ fmt_pct_signed(c.weight_pct) }}</td><td class="number {% if c.pnl_chf >= 0 %}positive{% else %}negative{% endif %}">{{ fmt_chf(c.pnl_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% endif %}

{% if perf.benchmarks %}
<h3>Benchmark-Referenzen</h3>
<table>
<thead><tr><th>Kürzel</th><th>Bezeichnung</th><th class="number">Rendite {{ data.tax_year }}</th><th>Hinweis</th></tr></thead>
<tbody>
{% for b in perf.benchmarks %}
<tr><td>{{ b.code }}</td><td>{{ b.label }}</td><td class="number">{{ fmt_pct_signed(b.return_pct) }}</td><td>{{ b.note or "" }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}
<h3>Benchmark-Referenzen</h3>
<p class="empty">Keine Benchmark-Referenzwerte für das Steuerjahr {{ data.tax_year }} hinterlegt.</p>
{% endif %}
</section>
{% endif %}

<section id="wertschriften">
<h2>Wertschriften</h2>
{% if data.positions %}
<table>
<thead><tr><th>ISIN</th><th>Symbol</th><th>Bezeichnung</th><th class="number">Menge</th><th>Währung</th><th class="number">Kurs lokal</th><th class="number">Kurs CHF</th><th class="number">Marktwert CHF</th></tr></thead>
<tbody>
{% for p in data.positions %}
<tr><td>{{ p.isin or "" }}</td><td>{{ p.symbol }}</td><td>{{ p.description }}</td><td class="number">{{ fmt_num(p.quantity_closing) }}</td><td>{{ p.currency }}</td><td class="number">{{ fmt_num(p.price_closing_local) }}</td><td class="number">{{ fmt_num(p.price_closing_chf) }}</td><td class="number">{{ fmt_chf(p.market_value_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Positionen.</p>{% endif %}
</section>

<section id="sg-verzeichnis">
<h2>SG Wertschriftenverzeichnis</h2>
{% if data.verzeichnis_lines %}
<table>
<thead><tr><th>Formularfeld</th><th>Kategorie</th><th>ISIN</th><th>Bezeichnung</th><th class="number">Menge</th><th class="number">Marktwert CHF</th><th class="number">Ertrag CHF</th><th class="number">VSt CHF</th><th class="number">QSt CHF</th></tr></thead>
<tbody>
{% for v in data.verzeichnis_lines %}
<tr><td>{{ v.form_field }}</td><td>{{ v.investment_type }}</td><td>{{ v.isin or "" }}</td><td>{{ v.description }}</td><td class="number">{{ fmt_num(v.quantity) }}</td><td class="number">{{ fmt_chf(v.market_value_chf) }}</td><td class="number">{{ fmt_chf(v.income_gross_chf) }}</td><td class="number">{{ fmt_chf(v.verrechnungssteuer_chf) }}</td><td class="number">{{ fmt_chf(v.auslaendische_quellensteuer_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Einträge.</p>{% endif %}
</section>

<section id="da1">
<h2>DA-1 Hilfstabelle</h2>
{% if data.da1_claims %}
<table>
<thead><tr><th>ISIN</th><th>Symbol</th><th>Bezeichnung</th><th>Quellenstaat</th><th class="number">Brutto CHF</th><th class="number">QSt CHF</th><th class="number">Satz</th><th class="number">DBA-Obergrenze</th><th class="number">Rückforderbar CHF</th></tr></thead>
<tbody>
{% for c in data.da1_claims %}
<tr><td>{{ c.isin or "" }}</td><td>{{ c.symbol }}</td><td>{{ c.description }}</td><td>{{ c.source_country }}</td><td class="number">{{ fmt_chf(c.gross_chf) }}</td><td class="number">{{ fmt_chf(c.withholding_tax_chf) }}</td><td class="number">{{ fmt_percent(c.withholding_rate) }}</td><td class="number">{% if c.treaty_rate_ceiling is not none %}{{ fmt_percent(c.treaty_rate_ceiling) }}{% endif %}</td><td class="number">{{ fmt_chf(c.recoverable_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine DA-1 Ansprüche.</p>{% endif %}
</section>

<section id="kauf-verkauf">
<h2>Kauf / Verkauf</h2>
{% if data.orders %}
<table>
<thead><tr><th>Order-ID</th><th>Symbol</th><th>Seite</th><th class="number">Menge</th><th class="number">Ø Preis</th><th>Währung</th><th class="number">Gegenwert</th><th class="number">Kommission</th><th>Zeitraum</th><th>Gruppierung</th></tr></thead>
<tbody>
{% for o in data.orders %}
<tr><td>{{ o.order_id }}</td><td>{{ o.symbol }}</td><td>{{ o.side }}</td><td class="number">{{ fmt_num(o.total_quantity) }}</td><td class="number">{{ fmt_num(o.avg_price, decimals=4) }}</td><td>{{ o.currency }}</td><td class="number">{{ fmt_num(o.total_money) }}</td><td class="number">{{ fmt_num(o.total_commission) }}</td><td>{{ fmt_date(o.earliest_fill_time.date()) }}{% if o.earliest_fill_time.date() != o.latest_fill_time.date() %} – {{ fmt_date(o.latest_fill_time.date()) }}{% endif %}</td><td>{{ o.grouping_method }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Transaktionen.</p>{% endif %}

<h3>FIFO Schliessungen</h3>
{% if data.lot_closes %}
<table>
<thead><tr><th>Symbol</th><th>Eröffnet</th><th>Geschlossen</th><th class="number">Menge</th><th class="number">Einstand</th><th class="number">Erlös</th><th class="number">Realisierter G/V</th></tr></thead>
<tbody>
{% for lc in data.lot_closes %}
<tr><td>{{ lc.symbol }}</td><td>{{ fmt_date(lc.opened_at.date()) }}</td><td>{{ fmt_date(lc.closed_at.date()) }}</td><td class="number">{{ fmt_num(lc.quantity_closed) }}</td><td class="number">{{ fmt_num(lc.cost_basis) }}</td><td class="number">{{ fmt_num(lc.proceeds) }}</td><td class="number {% if lc.realized_pnl >= 0 %}positive{% else %}negative{% endif %}">{{ fmt_num(lc.realized_pnl) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Schliessungen.</p>{% endif %}
</section>

<section id="dividenden">
<h2>Dividenden</h2>
{{ income_table(data.dividends) }}
</section>

<section id="zinsen">
<h2>Zinsen</h2>
{{ income_table(data.interest) }}
</section>

<section id="gebuehren">
<h2>Gebühren</h2>
{% if data.fees %}
<table>
<thead><tr><th>Datum</th><th>Art</th><th>Beschreibung</th><th class="number">Betrag lokal</th><th>Währung</th><th class="number">Betrag CHF</th></tr></thead>
<tbody>
{% for f in data.fees %}
<tr><td>{{ fmt_date(f.fee_date) }}</td><td>{{ f.kind }}</td><td>{{ f.description }}</td><td class="number">{{ fmt_num(f.amount_local) }}</td><td>{{ f.currency }}</td><td class="number">{{ fmt_chf(f.amount_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Gebühren.</p>{% endif %}
</section>

<section id="fx-kurse">
<h2>FX Kurse</h2>
{% if data.fx_rates %}
<table>
<thead><tr><th>Währung</th><th>Referenzdatum</th><th class="number">Kurs (CHF je 1)</th><th>Quelle</th></tr></thead>
<tbody>
{% for r in data.fx_rates %}
<tr><td>{{ r.currency }}</td><td>{{ fmt_date(r.reference_date) }}</td><td class="number">{{ fmt_num(r.rate, decimals=6) }}</td><td>{{ r.source }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine FX-Kurse.</p>{% endif %}
</section>

{% if data.preparer_mode %}
<section id="ks36" class="preparer-only">
<h2>KS 36 — Selbstprüfung (Vorbereiter-Modus)</h2>
<p class="meta">Nicht für Dritte bestimmt. Eingebetteter Selbst-Check gemäss ESTV Kreisschreiben Nr. 36.</p>
<h3>Kriterien</h3>
{% if data.ks36_criteria %}
<table>
<thead><tr><th>Kriterium</th><th class="number">Beobachtet</th><th class="number">Schwelle</th><th>Einheit</th><th>Status</th><th>Hinweis</th></tr></thead>
<tbody>
{% for k in data.ks36_criteria %}
<tr><td>{{ k.label }}</td><td class="number">{{ fmt_num(k.observed_value, decimals=4) }}</td><td class="number">{{ fmt_num(k.threshold, decimals=4) }}</td><td>{{ k.unit }}</td><td class="ampel-{{ k.status }}">{{ k.status }}</td><td>{{ k.note or "" }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Kriterien erfasst.</p>{% endif %}

<h3>Belege</h3>
{% if data.ks36_evidence %}
<table>
<thead><tr><th>Kriterium</th><th>Kategorie</th><th>Beschreibung</th><th class="number">Betrag CHF</th><th>Datum</th></tr></thead>
<tbody>
{% for e in data.ks36_evidence %}
<tr><td>{{ e.criterion_code }}</td><td>{{ e.category }}</td><td>{{ e.description }}</td><td class="number">{{ fmt_chf(e.value_chf) }}</td><td>{{ fmt_date(e.evidence_date) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Belege erfasst.</p>{% endif %}
</section>
{% endif %}
</main>
</body>
</html>
"""


_INCOME_TABLE_MACRO = """\
{% macro income_table(rows) -%}
{% if rows %}
<table>
<thead><tr><th>Datum</th><th>ISIN</th><th>Symbol</th><th>Bezeichnung</th><th class="number">Brutto lokal</th><th>Währung</th><th class="number">QSt lokal</th><th class="number">Netto lokal</th><th class="number">Brutto CHF</th><th class="number">QSt CHF</th><th class="number">Netto CHF</th></tr></thead>
<tbody>
{% for r in rows %}
<tr><td>{{ fmt_date(r.payment_date) }}</td><td>{{ r.isin or "" }}</td><td>{{ r.symbol }}</td><td>{{ r.description }}</td><td class="number">{{ fmt_num(r.gross_local) }}</td><td>{{ r.currency }}</td><td class="number">{{ fmt_num(r.withholding_tax_local) }}</td><td class="number">{{ fmt_num(r.net_local) }}</td><td class="number">{{ fmt_chf(r.gross_chf) }}</td><td class="number">{{ fmt_chf(r.withholding_tax_chf) }}</td><td class="number">{{ fmt_chf(r.net_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Einträge.</p>{% endif %}
{%- endmacro %}
"""


def _build_environment() -> Environment:
    env = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
    # jinja2 types the default globals narrowly; widen before adding our helpers.
    env_globals = cast(Dict[str, Any], env.globals)
    env_globals.update(
        fmt_chf=format_chf,
        fmt_num=format_number,
        fmt_percent=format_percent,
        fmt_pct_signed=format_pct_signed,
        fmt_date=format_date,
    )
    return env


def render_html(data: TaxOverviewData) -> str:
    """Render a self-contained HTML report for the tax-overview dashboard.

    Returns the full HTML string. The KS 36 section is emitted only when
    ``data.preparer_mode`` is true — mirrors the xlsx third-party-safety gate.
    """
    env = _build_environment()
    # Register the income-row macro as a global so the main template can call it.
    macro_module = env.from_string(_INCOME_TABLE_MACRO).module
    env.globals["income_table"] = getattr(macro_module, "income_table")

    # Pre-render SVGs so the template just embeds them (keeps Jinja clean).
    if data.performance:
        perf = data.performance
        sectors_svg = render_pie(perf.sectors, aria_label="Allokation nach Sektoren")
        currencies_svg = render_pie(perf.currencies, aria_label="Allokation nach Währungen")
        top_positions_svg = render_bar(perf.positions)
        benchmark_svg = render_benchmark_comparison(
            perf.summary.money_weighted_return_pct,
            perf.benchmarks,
        )
    else:
        sectors_svg = currencies_svg = top_positions_svg = benchmark_svg = ""

    template = env.from_string(_TEMPLATE_SOURCE)
    return template.render(
        data=data,
        css_variables=css_variables(),
        sectors_svg=sectors_svg,
        currencies_svg=currencies_svg,
        top_positions_svg=top_positions_svg,
        benchmark_svg=benchmark_svg,
    )
