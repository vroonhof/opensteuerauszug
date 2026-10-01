"""Performance section computation: per-position returns, sector splits, benchmarks.

Uses :func:`.perf_records.compute_performance_records` for the per-security
P&L math (opening/closing/buys/sells/dividends, weighted-average FX,
average-cost split of realized vs unrealized).

Everything returned here is CHF-normalised: the sector / currency buckets are
weighted by closing market value, and the Dietz total-return uses the period's
net deposits to correct for the cash the taxpayer added mid-year.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ...model.ech0196 import TaxStatement
from .perf_records import PerformanceRecord, compute_performance_records
from .data import (
    BenchmarkComparison,
    PerformancePosition,
    PerformanceSection,
    PerformanceSummary,
    PositionSummary,
    SectorAllocation,
)

logger = logging.getLogger(__name__)


ZERO = Decimal("0")
HUNDRED = Decimal("100")


# Annual benchmark reference returns live in benchmark_returns.json next to
# this module: data, not code, so adding a tax year (or correcting a figure)
# needs no code change. A year missing from the file renders an explicit
# "no benchmark data" notice rather than silently dropping the table.
_BENCHMARK_FILE = Path(__file__).with_name("benchmark_returns.json")


def _load_benchmark_catalog() -> Dict[int, List[BenchmarkComparison]]:
    try:
        raw = json.loads(_BENCHMARK_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("tax-overview: benchmark catalog unreadable (%s)", exc)
        return {}
    catalog: Dict[int, List[BenchmarkComparison]] = {}
    for year_str, entries in raw.items():
        if not year_str.isdigit():
            continue  # skip _comment and similar metadata keys
        catalog[int(year_str)] = [
            BenchmarkComparison(
                code=e["code"],
                label=e["label"],
                return_pct=Decimal(e["return_pct"]),
                note=e.get("note"),
            )
            for e in entries
        ]
    return catalog


def build_performance_section(
    statement: TaxStatement,
    *,
    tax_year: int,
    opening_securities_chf: Decimal,
    closing_securities_chf: Decimal,
    closing_cash_chf: Decimal = ZERO,
    cash_known: bool = False,
    net_deposits_chf: Decimal,
    deposits_gross_chf: Decimal = ZERO,
    withdrawals_chf: Decimal = ZERO,
    dividends_chf: Decimal,
    interest_chf: Decimal,
    fees_chf: Decimal,
    positions: Sequence[PositionSummary],
    opening_by_isin: Optional[Dict[str, Decimal]] = None,
    sector_lookup: Optional["SectorLookup"] = None,
    asset_class_by_isin: Optional[Dict[str, str]] = None,
) -> PerformanceSection:
    """Assemble the PerformanceSection for a tax year.

    Performance is computed on the *securities portfolio only*. Opening and
    closing cash are deliberately left out of the return math because most
    Flex queries don't carry a ``startingCash`` figure and the closing-minus-
    payments heuristic systematically inflates opening cash. Year-end cash is
    surfaced as a separate informational tile.

    ``opening_by_isin`` overrides the util's opening CHF values (which are
    computed from the raw SecurityStock entries, often missing the unitPrice
    on the opening row). The pipeline's ``_sum_security_opening`` applies a
    3-tier price/FX fallback; we pass those enriched values in so per-position
    P&L reconciles with the portfolio-level summary.
    """
    records = compute_performance_records(statement)
    lookup = sector_lookup or SectorLookup.noop()
    opening_by_isin = opening_by_isin or {}
    asset_class_by_isin = asset_class_by_isin or {}

    # Map ISIN → closing market value CHF from the curated positions list
    # (which already benefits from OpenPosition fallback for un-Kursliste'd
    # securities). The util module uses taxValue directly and would miss
    # those; we prefer the enriched figure.
    closing_by_isin: Dict[str, Decimal] = {}
    currency_by_isin: Dict[str, str] = {}
    for pos in positions:
        if pos.isin:
            closing_by_isin[pos.isin] = pos.market_value_chf
            currency_by_isin[pos.isin] = pos.currency

    perf_positions: List[PerformancePosition] = []
    for r in records:
        isin = r.isin or ""
        opening_chf = opening_by_isin.get(isin, r.opening_value_chf)
        closing_chf = closing_by_isin.get(isin, r.closing_value_chf)

        # Only keep positions with economic activity or non-zero holdings.
        has_activity = (
            opening_chf != 0
            or closing_chf != 0
            or r.dividends_chf != 0
            or r.buys_native != 0
            or r.sells_native != 0
        )
        if not has_activity:
            continue

        sector = lookup.sector_for(isin=isin, symbol=r.symbol)
        currency = r.native_currency or currency_by_isin.get(isin, "")

        buys_chf = r.buys_chf
        sells_chf = r.sells_chf
        # Total P&L uses the enriched opening / closing values so it matches
        # the Dietz numerator that the summary is built on.
        total_pnl_chf = closing_chf + sells_chf + r.dividends_chf - opening_chf - buys_chf

        # Realized / unrealized split: realized comes from the record's own
        # FX-converted figure (avoids the unbounded realized/total ratio when
        # total P&L is near zero); unrealized absorbs the remainder so the
        # split always sums to the enriched total.
        realized_chf = r.realized_pl_chf.quantize(Decimal("0.01"))
        unrealized_chf = total_pnl_chf - realized_chf

        # Return on invested capital: P&L / (opening + buys). This is more
        # meaningful than "P&L / opening" when a position was opened mid-year
        # (opening == 0). Falls back to None only when nothing was invested.
        invested = opening_chf + buys_chf
        return_pct = None
        if invested > 0:
            return_pct = (total_pnl_chf / invested * HUNDRED).quantize(Decimal("0.01"))

        perf_positions.append(
            PerformancePosition(
                isin=r.isin or None,
                symbol=r.symbol or "",
                description=r.name,
                currency=currency,
                sector=sector,
                opening_value_chf=opening_chf,
                closing_value_chf=closing_chf,
                buys_chf=buys_chf,
                sells_chf=sells_chf,
                dividends_chf=r.dividends_chf,
                unrealized_pnl_chf=unrealized_chf,
                realized_pnl_chf=realized_chf,
                total_pnl_chf=total_pnl_chf,
                return_pct=return_pct,
            )
        )

    # Sort by absolute contribution so the most-impactful lines lead.
    perf_positions.sort(key=lambda p: abs(p.total_pnl_chf), reverse=True)

    sectors = _aggregate(
        perf_positions,
        key=lambda p: p.sector or "Unbekannt",
    )
    currencies = _aggregate(
        perf_positions,
        key=lambda p: p.currency or "?",
    )

    # Securities-only P&L: sum of per-position P&L lines (already includes
    # dividends, realized + unrealized capital changes). Equivalently:
    # closing_sec + sells + dividends - opening_sec - buys.
    securities_buys_chf = sum((p.buys_chf for p in perf_positions), ZERO)
    securities_sells_chf = sum((p.sells_chf for p in perf_positions), ZERO)
    securities_net_flow_chf = securities_buys_chf - securities_sells_chf
    portfolio_pnl_chf = sum((p.total_pnl_chf for p in perf_positions), ZERO)
    summary = _build_summary(
        opening_securities_chf=opening_securities_chf,
        closing_securities_chf=closing_securities_chf,
        closing_cash_chf=closing_cash_chf,
        cash_known=cash_known,
        net_deposits_chf=net_deposits_chf,
        deposits_gross_chf=deposits_gross_chf,
        withdrawals_chf=withdrawals_chf,
        securities_net_flow_chf=securities_net_flow_chf,
        total_pnl_chf=portfolio_pnl_chf,
        dividends_chf=dividends_chf,
        interest_chf=interest_chf,
        fees_chf=fees_chf,
    )

    benchmarks = _load_benchmark_catalog().get(tax_year, [])
    if not benchmarks:
        logger.warning(
            "tax-overview: no benchmark reference data for tax year %s "
            "(extend render/tax_overview/benchmark_returns.json)",
            tax_year,
        )

    return PerformanceSection(
        summary=summary,
        positions=perf_positions,
        sectors=sectors,
        currencies=currencies,
        benchmarks=benchmarks,
    )


def _build_summary(
    *,
    opening_securities_chf: Decimal,
    closing_securities_chf: Decimal,
    closing_cash_chf: Decimal,
    cash_known: bool,
    net_deposits_chf: Decimal,
    deposits_gross_chf: Decimal,
    withdrawals_chf: Decimal,
    securities_net_flow_chf: Decimal,
    total_pnl_chf: Decimal,
    dividends_chf: Decimal,
    interest_chf: Decimal,
    fees_chf: Decimal,
) -> PerformanceSummary:
    simple_return = None
    if opening_securities_chf > 0:
        simple_return = (total_pnl_chf / opening_securities_chf * HUNDRED).quantize(Decimal("0.01"))

    # Modified Dietz on the security portfolio: external flows are the net
    # buy-vs-sell movements (cash → securities or vice versa). Dividends are
    # treated as part of the return, not a flow.
    dietz_denom = opening_securities_chf + (securities_net_flow_chf / 2)
    money_weighted = None
    if dietz_denom > 0:
        money_weighted = (total_pnl_chf / dietz_denom * HUNDRED).quantize(Decimal("0.01"))

    return PerformanceSummary(
        opening_value_chf=opening_securities_chf,
        closing_value_chf=closing_securities_chf,
        closing_cash_chf=closing_cash_chf,
        cash_known=cash_known,
        net_deposits_chf=net_deposits_chf,
        deposits_gross_chf=deposits_gross_chf,
        withdrawals_chf=withdrawals_chf,
        securities_net_flow_chf=securities_net_flow_chf,
        total_pnl_chf=total_pnl_chf,
        dividends_chf=dividends_chf,
        interest_chf=interest_chf,
        fees_chf=fees_chf,
        money_weighted_return_pct=money_weighted,
        simple_return_pct=simple_return,
    )


def _aggregate(
    positions: Sequence[PerformancePosition],
    *,
    key,
) -> List[SectorAllocation]:
    """Bucket positions by a key function and emit SectorAllocation rows."""
    buckets: Dict[str, Dict[str, Decimal]] = {}
    for p in positions:
        label = key(p)
        b = buckets.setdefault(label, {"value": ZERO, "pnl": ZERO})
        b["value"] += p.closing_value_chf
        b["pnl"] += p.total_pnl_chf

    total_value = sum((b["value"] for b in buckets.values()), ZERO)
    rows: List[SectorAllocation] = []
    for label, b in buckets.items():
        weight = ZERO
        if total_value > 0:
            weight = (b["value"] / total_value * HUNDRED).quantize(Decimal("0.01"))
        rows.append(
            SectorAllocation(
                label=label,
                market_value_chf=b["value"],
                pnl_chf=b["pnl"],
                weight_pct=weight,
            )
        )
    rows.sort(key=lambda r: r.market_value_chf, reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Sector lookup (yfinance-backed, with on-disk cache)
# ---------------------------------------------------------------------------


class SectorLookup:
    """Map ISIN / symbol → sector, using a disk cache and optionally yfinance.

    The dashboard is self-contained and should not block on a network call;
    missing entries resolve to ``"Unbekannt"`` rather than hanging. Populate
    the cache ahead of time (or pass ``online=True`` to try yfinance once per
    unknown symbol, storing the result).
    """

    def __init__(self, cache_path: Optional[Path], online: bool = False) -> None:
        self._cache_path = cache_path
        self._online = online
        self._cache: Dict[str, str] = {}
        if cache_path and cache_path.exists():
            try:
                self._cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover
                logger.warning("sector-lookup: cache read failed (%s) — starting empty", exc)
                self._cache = {}

    @classmethod
    def noop(cls) -> "SectorLookup":
        return cls(cache_path=None, online=False)

    def sector_for(self, *, isin: str, symbol: str) -> str:
        key = (isin or symbol or "").upper()
        if not key:
            return "Unbekannt"
        if key in self._cache:
            return self._cache[key] or "Unbekannt"
        if isin and isin.upper() in self._cache:
            return self._cache[isin.upper()] or "Unbekannt"

        sector: Optional[str] = None
        if self._online and symbol:
            sector = self._fetch_yfinance(symbol)

        if sector:
            # Cache successes only: a failed lookup (offline, yfinance missing,
            # no sector) must stay retryable instead of poisoning the cache.
            self._cache[key] = sector
            self._persist()
            return sector
        return "Unbekannt"

    def _fetch_yfinance(self, symbol: str) -> Optional[str]:
        try:
            import yfinance as yf  # type: ignore[import-untyped]
        except ImportError:
            return None
        try:
            info = yf.Ticker(symbol).info
        except Exception as exc:  # pragma: no cover
            logger.debug("yfinance lookup failed for %s: %s", symbol, exc)
            return None
        return (info or {}).get("sector") or None

    def _persist(self) -> None:
        if not self._cache_path:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(self._cache, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("sector-lookup: cache write failed (%s)", exc)
