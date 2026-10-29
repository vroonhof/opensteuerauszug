"""Per-security performance records derived from an eCH-0196 TaxStatement.

Pure computation (no GUI dependencies): for every security in the statement,
derive opening/closing values, buys/sells, dividends, and a realized /
unrealized P&L split, in native currency and CHF.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from opensteuerauszug.model.ech0196 import TaxStatement

_ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PerformanceRecord:
    name: str
    symbol: str
    isin: str
    native_currency: str

    opening_value_native: Decimal = field(default=_ZERO)
    opening_value_chf: Decimal = field(default=_ZERO)
    closing_value_native: Decimal = field(default=_ZERO)
    closing_value_chf: Decimal = field(default=_ZERO)
    buys_native: Decimal = field(default=_ZERO)
    buys_chf: Decimal = field(default=_ZERO)
    sells_native: Decimal = field(default=_ZERO)
    sells_chf: Decimal = field(default=_ZERO)
    dividends_native: Decimal = field(default=_ZERO)
    dividends_chf: Decimal = field(default=_ZERO)
    unrealized_pl_native: Decimal = field(default=_ZERO)
    realized_pl_native: Decimal = field(default=_ZERO)
    realized_pl_chf: Decimal = field(default=_ZERO)
    total_pl_native: Decimal = field(default=_ZERO)
    total_pl_chf: Decimal = field(default=_ZERO)
    return_pct: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------


def _fx(stock_or_tv) -> Decimal:
    """Return exchange-rate (native → CHF) from a stock or taxValue entry, defaulting to 1."""
    rate = getattr(stock_or_tv, "exchangeRate", None)
    return Decimal(str(rate)) if rate else Decimal("1")


def compute_performance_records(statement: "TaxStatement") -> List[PerformanceRecord]:
    """Derive a PerformanceRecord for every security in the statement."""
    records: List[PerformanceRecord] = []

    list_of_securities = getattr(statement, "listOfSecurities", None)
    if list_of_securities is None:
        return records

    period_from = getattr(statement, "periodFrom", None)
    period_to = getattr(statement, "periodTo", None)

    securities = [
        sec
        for depot in (getattr(list_of_securities, "depot", None) or [])
        for sec in (getattr(depot, "security", None) or [])
    ]

    for sec in securities:
        symbol = str(getattr(sec, "symbol", None) or "")
        name = str(getattr(sec, "securityName", None) or "")
        # ECH-0196 Security has no symbol field; importer encodes it as "NAME (SYM)"
        if not symbol and name:
            m = re.search(r'\(([A-Z0-9.]+)\)$', name)
            if m:
                symbol = m.group(1)
        isin = str(getattr(sec, "isin", None) or getattr(sec, "valorNumber", None) or symbol or "")
        if not name:
            name = isin
        ccy = str(getattr(sec, "currency", "?"))

        stocks = list(getattr(sec, "stock", []) or [])
        payments = list(getattr(sec, "payment", []) or [])
        tax_value = getattr(sec, "taxValue", None)

        # --- Opening value (balance entry at period start: mutation=False) ---
        balance_entries = [s for s in stocks if not getattr(s, "mutation", True)]
        if period_from is not None:
            # Only a balance dated at the period start is an opening balance;
            # picking any balance row would mistake a closing balance (e.g. a
            # position bought mid-year) for the opening value.
            balance_entries = [
                s for s in balance_entries if getattr(s, "referenceDate", None) == period_from
            ]
        opening_native = _ZERO
        opening_chf = _ZERO
        opening_qty = _ZERO
        if balance_entries:
            b = balance_entries[0]
            qty = Decimal(str(getattr(b, "quantity", 0) or 0))
            price = Decimal(str(getattr(b, "unitPrice", 0) or 0))
            opening_native = qty * price
            opening_chf = opening_native * _fx(b)
            opening_qty = qty

        # --- Closing value (from SecurityTaxValue) ---
        closing_native = _ZERO
        closing_chf = _ZERO
        closing_qty = _ZERO
        if tax_value is not None:
            qty = Decimal(str(getattr(tax_value, "quantity", 0) or 0))
            price = Decimal(str(getattr(tax_value, "unitPrice", 0) or 0))
            closing_native = qty * price
            closing_chf = Decimal(str(getattr(tax_value, "value", 0) or 0))
            closing_qty = qty

        # --- Buys and sells (mutation=True transactions within period) ---
        buys_native = _ZERO
        sells_native = _ZERO
        for s in stocks:
            if not getattr(s, "mutation", False):
                continue
            ref = getattr(s, "referenceDate", None)
            if period_from and ref and ref < period_from:
                continue
            if period_to and ref and ref > period_to:
                continue
            qty = Decimal(str(getattr(s, "quantity", 0) or 0))
            price = Decimal(str(getattr(s, "unitPrice", 0) or 0))
            notional = abs(qty) * price
            if qty >= _ZERO:
                buys_native += notional
            else:
                sells_native += notional

        # --- Dividends (sum of payment amounts in native currency within period) ---
        dividends_native = _ZERO
        for p in payments:
            pay_date = getattr(p, "paymentDate", None)
            if period_from and pay_date and pay_date < period_from:
                continue
            if period_to and pay_date and pay_date > period_to:
                continue
            amount = getattr(p, "amount", None)
            if amount is not None:
                # payment.amount is typically in amountCurrency (native)
                dividends_native += Decimal(str(amount))
            else:
                # Fallback: amountPerUnit * quantity
                per_unit = getattr(p, "amountPerUnit", None)
                qty = getattr(p, "quantity", None)
                if per_unit is not None and qty is not None:
                    dividends_native += Decimal(str(per_unit)) * Decimal(str(qty))

        # --- Total P&L ---
        total_pl_native = (
            closing_native + sells_native + dividends_native - opening_native - buys_native
        )

        # Derive CHF P&L.  Preference order for FX rate:
        # 1. taxValue (has the official year-end rate)
        # 2. Sell-side weighted average from mutation entries (now stored on each SecurityStock)
        # 3. Buy-side weighted average
        # 4. Fallback 1:1
        if tax_value is not None:
            fx_close = _fx(tax_value)
        else:
            sell_notional = _ZERO
            sell_notional_chf = _ZERO
            buy_notional = _ZERO
            buy_notional_chf = _ZERO
            for s in stocks:
                if not getattr(s, "mutation", False):
                    continue
                fx_s = _fx(s)
                if fx_s == Decimal("1"):
                    continue  # no FX stored, skip
                ref = getattr(s, "referenceDate", None)
                if period_from and ref and ref < period_from:
                    continue
                if period_to and ref and ref > period_to:
                    continue
                qty_s = abs(Decimal(str(getattr(s, "quantity", 0) or 0)))
                price_s = Decimal(str(getattr(s, "unitPrice", 0) or 0))
                notional_s = qty_s * price_s
                q = Decimal(str(getattr(s, "quantity", 0) or 0))
                if q < _ZERO:
                    sell_notional += notional_s
                    sell_notional_chf += notional_s * fx_s
                else:
                    buy_notional += notional_s
                    buy_notional_chf += notional_s * fx_s
            if sell_notional > _ZERO:
                fx_close = sell_notional_chf / sell_notional
            elif buy_notional > _ZERO:
                fx_close = buy_notional_chf / buy_notional
            else:
                fx_close = Decimal("1")
        total_pl_chf = total_pl_native * fx_close if fx_close else _ZERO
        dividends_chf = dividends_native * fx_close if fx_close else _ZERO
        # Trade notionals converted at the same rate as dividends/P&L. This is
        # the year-end (or trade-weighted) rate, not per-trade FX — mutations
        # carry no exchangeRate — but far better than treating native as CHF.
        buys_chf = buys_native * fx_close if fx_close else _ZERO
        sells_chf = sells_native * fx_close if fx_close else _ZERO

        # --- Unrealized / Realized split (average-cost approximation) ---
        net_invested = opening_native + buys_native - sells_native
        avg_qty = (opening_qty + closing_qty) / 2
        if avg_qty > _ZERO and net_invested >= _ZERO:
            unrealized_pl_native = closing_native - (net_invested * closing_qty / avg_qty)
        elif closing_qty == _ZERO:
            # Position fully closed → all P&L is realized
            unrealized_pl_native = _ZERO
        else:
            unrealized_pl_native = closing_native - net_invested

        realized_pl_native = total_pl_native - unrealized_pl_native
        realized_pl_chf = realized_pl_native * fx_close if fx_close else _ZERO

        # --- Return % ---
        if opening_native > _ZERO:
            return_pct = (total_pl_native / opening_native) * 100
        else:
            return_pct = None

        records.append(
            PerformanceRecord(
                name=name,
                symbol=symbol,
                isin=isin,
                native_currency=ccy,
                opening_value_native=opening_native,
                opening_value_chf=opening_chf,
                closing_value_native=closing_native,
                closing_value_chf=closing_chf,
                buys_native=buys_native,
                buys_chf=buys_chf,
                sells_native=sells_native,
                sells_chf=sells_chf,
                dividends_native=dividends_native,
                dividends_chf=dividends_chf,
                unrealized_pl_native=unrealized_pl_native,
                realized_pl_native=realized_pl_native,
                realized_pl_chf=realized_pl_chf,
                total_pl_native=total_pl_native,
                total_pl_chf=total_pl_chf,
                return_pct=return_pct,
            )
        )

    records.sort(key=lambda r: abs(r.total_pl_native), reverse=True)
    return records
