"""Order reconstruction: group broker fills back into logical orders.

Brokers report individual executions (fills). A single user-intended "order" may
be split into many fills by the execution venue. For tax disclosure and
realized-gain reporting we want the logical order, not the underlying fills, so
this module reconstructs it using a three-tier grouping strategy:

1. **Broker order id** — IBKR's ``ibOrderID`` / Schwab's order id. Two fills
   that share this id are the same order.
2. **Order reference** — user-supplied ``orderReference``. Used only when the
   broker order id is missing (older flex reports, partial exports).
3. **Time cluster** — same ``(symbol, side)`` within a configurable window
   (default 300 s). Last-resort fallback for fills with neither id.

The module is broker-agnostic: callers map their broker-native records into
:class:`Fill` and get :class:`Order` back. Currency conversion happens
elsewhere (phase 4) — this module stays numeric and unit-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple

DEFAULT_TIME_CLUSTER_WINDOW = timedelta(seconds=300)


@dataclass(frozen=True)
class Fill:
    """One broker execution. Immutable so orders can hold shared references."""

    fill_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: Decimal  # signed by side is not required; sign mirrors buy/sell convention of caller
    price: Decimal
    money: Decimal  # gross proceeds or cost, signed per broker convention
    commission: Decimal  # negative when deducted (IBKR convention)
    currency: str
    trade_time: datetime
    asset_category: str
    isin: Optional[str] = None
    conid: Optional[str] = None
    ib_order_id: Optional[str] = None
    order_reference: Optional[str] = None
    fx_rate_to_base: Optional[Decimal] = None


@dataclass(frozen=True)
class Order:
    """A reconstructed logical order built from one or more :class:`Fill`s."""

    order_id: str  # stable, deterministic — see :func:`_synthesise_order_id`
    symbol: str
    side: str
    total_quantity: Decimal
    avg_price: Decimal  # quantity-weighted mean across fills
    total_money: Decimal
    total_commission: Decimal
    currency: str
    earliest_fill_time: datetime
    latest_fill_time: datetime
    asset_category: str
    isin: Optional[str]
    conid: Optional[str]
    fills: Tuple[Fill, ...]
    grouping_method: str  # "ib_order_id" | "order_reference" | "time_cluster" | "singleton"

    @property
    def fill_count(self) -> int:
        return len(self.fills)


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def reconstruct_orders(
    fills: Iterable[Fill],
    *,
    time_cluster_window: timedelta = DEFAULT_TIME_CLUSTER_WINDOW,
) -> List[Order]:
    """Reconstruct logical orders from a stream of broker fills.

    The returned list is sorted by ``earliest_fill_time`` then ``order_id`` so
    callers can iterate deterministically without re-sorting.
    """
    fill_list = list(fills)
    if not fill_list:
        return []

    # Three-tier grouping keyed by a composite (tier, key) tuple. The tier part
    # prevents an ib_order_id from colliding with an identically-named
    # order_reference.
    groups: dict[Tuple[str, str], List[Fill]] = {}
    for fill in fill_list:
        key = _group_key(fill)
        groups.setdefault(key, []).append(fill)

    orders: List[Order] = []
    for (tier, _), grouped_fills in groups.items():
        if tier == "time_cluster":
            for cluster in _time_cluster(grouped_fills, time_cluster_window):
                orders.append(_build_order(cluster, grouping_method="time_cluster"))
        else:
            method = "ib_order_id" if tier == "ib" else "order_reference"
            # A cluster of one fill from an id-based group is still an id-based
            # group — keep the provenance accurate.
            orders.append(_build_order(grouped_fills, grouping_method=method))

    orders.sort(key=lambda o: (o.earliest_fill_time, o.order_id))
    return orders


def _group_key(fill: Fill) -> Tuple[str, str]:
    if fill.ib_order_id:
        return ("ib", fill.ib_order_id)
    if fill.order_reference:
        return ("ref", fill.order_reference)
    # Time-cluster candidates share a bucket per (symbol, side); the actual
    # window split happens in :func:`_time_cluster`.
    return ("time_cluster", f"{fill.symbol}|{fill.side}")


def _time_cluster(fills: Sequence[Fill], window: timedelta) -> List[List[Fill]]:
    """Split fills into clusters where consecutive fills are <= ``window`` apart.

    Uses a rolling "last fill time" as the anchor: as long as the next fill is
    within ``window`` of the previous one it extends the cluster. This matches
    the IBKR behaviour where slow fills of a single order can span several
    minutes in aggregate while each individual gap stays small.
    """
    if not fills:
        return []
    ordered = sorted(fills, key=lambda f: f.trade_time)
    clusters: List[List[Fill]] = [[ordered[0]]]
    for fill in ordered[1:]:
        if fill.trade_time - clusters[-1][-1].trade_time <= window:
            clusters[-1].append(fill)
        else:
            clusters.append([fill])
    return clusters


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _build_order(fills: Sequence[Fill], *, grouping_method: str) -> Order:
    ordered = sorted(fills, key=lambda f: (f.trade_time, f.fill_id))
    head = ordered[0]
    total_quantity = sum((f.quantity for f in ordered), Decimal(0))
    total_money = sum((f.money for f in ordered), Decimal(0))
    total_commission = sum((f.commission for f in ordered), Decimal(0))
    avg_price = _weighted_avg_price(ordered)

    actual_method = grouping_method if len(ordered) > 1 else "singleton"

    return Order(
        order_id=_synthesise_order_id(ordered, grouping_method),
        symbol=head.symbol,
        side=head.side,
        total_quantity=total_quantity,
        avg_price=avg_price,
        total_money=total_money,
        total_commission=total_commission,
        currency=head.currency,
        earliest_fill_time=ordered[0].trade_time,
        latest_fill_time=ordered[-1].trade_time,
        asset_category=head.asset_category,
        isin=head.isin,
        conid=head.conid,
        fills=tuple(ordered),
        grouping_method=actual_method,
    )


def _weighted_avg_price(fills: Sequence[Fill]) -> Decimal:
    """Quantity-weighted mean price. Falls back to simple mean if qty sums to 0."""
    total_qty = sum((abs(f.quantity) for f in fills), Decimal(0))
    if total_qty == 0:
        # Degenerate case (e.g. cancelled + re-booked fills): mean of prices.
        prices = [f.price for f in fills]
        return sum(prices, Decimal(0)) / Decimal(len(prices))
    weighted = sum((f.price * abs(f.quantity) for f in fills), Decimal(0))
    return weighted / total_qty


def _synthesise_order_id(fills: Sequence[Fill], grouping_method: str) -> str:
    """Deterministic id for the reconstructed order.

    We prefer the broker-supplied id when available so downstream reports can
    cross-reference the flex statement. Otherwise we derive an id from the
    earliest fill so re-runs produce stable output.
    """
    head = fills[0]
    if grouping_method == "ib_order_id" and head.ib_order_id:
        return f"ib:{head.ib_order_id}"
    if grouping_method == "order_reference" and head.order_reference:
        return f"ref:{head.order_reference}"
    return f"cluster:{head.symbol}:{head.side}:{head.trade_time.isoformat()}:{head.fill_id}"
