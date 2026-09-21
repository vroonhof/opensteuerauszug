"""Phase-2 tests: reconstruct logical orders from broker fills.

Covers the three-tier grouping (ib_order_id → order_reference → time cluster),
plus boundary cases that would silently merge unrelated trades if we got the
key wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import pytest

from opensteuerauszug.render.tax_overview.orders import (
    DEFAULT_TIME_CLUSTER_WINDOW,
    Fill,
    reconstruct_orders,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

T0 = datetime(2025, 3, 14, 9, 30, 0)


def make_fill(
    fill_id: str,
    *,
    symbol: str = "AAPL",
    side: str = "BUY",
    quantity: Decimal = Decimal("10"),
    price: Decimal = Decimal("180.00"),
    money: Optional[Decimal] = None,
    commission: Decimal = Decimal("-1.00"),
    currency: str = "USD",
    trade_time: Optional[datetime] = None,
    asset_category: str = "STK",
    isin: Optional[str] = "US0378331005",
    conid: Optional[str] = "265598",
    ib_order_id: Optional[str] = None,
    order_reference: Optional[str] = None,
) -> Fill:
    return Fill(
        fill_id=fill_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        money=money if money is not None else quantity * price,
        commission=commission,
        currency=currency,
        trade_time=trade_time or T0,
        asset_category=asset_category,
        isin=isin,
        conid=conid,
        ib_order_id=ib_order_id,
        order_reference=order_reference,
    )


# ---------------------------------------------------------------------------
# Empty / singleton cases
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_list() -> None:
    assert reconstruct_orders([]) == []


def test_single_fill_becomes_singleton_order() -> None:
    orders = reconstruct_orders([make_fill("f1", ib_order_id="IB-1")])
    assert len(orders) == 1
    assert orders[0].fill_count == 1
    assert orders[0].grouping_method == "singleton"
    assert orders[0].order_id == "ib:IB-1"


# ---------------------------------------------------------------------------
# Tier 1: ib_order_id
# ---------------------------------------------------------------------------


def test_fills_with_same_ib_order_id_merge() -> None:
    fills = [
        make_fill("f1", quantity=Decimal("10"), price=Decimal("180.00"), ib_order_id="IB-1"),
        make_fill(
            "f2",
            quantity=Decimal("15"),
            price=Decimal("181.00"),
            ib_order_id="IB-1",
            trade_time=T0 + timedelta(seconds=45),
        ),
        make_fill(
            "f3",
            quantity=Decimal("5"),
            price=Decimal("182.00"),
            ib_order_id="IB-1",
            trade_time=T0 + timedelta(seconds=120),
        ),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 1
    order = orders[0]
    assert order.grouping_method == "ib_order_id"
    assert order.fill_count == 3
    assert order.total_quantity == Decimal("30")
    # weighted: (10*180 + 15*181 + 5*182) / 30 = 5425/30
    assert order.avg_price == Decimal("5425") / Decimal("30")
    assert order.total_commission == Decimal("-3.00")
    assert order.earliest_fill_time == T0
    assert order.latest_fill_time == T0 + timedelta(seconds=120)


def test_different_ib_order_ids_stay_separate() -> None:
    fills = [
        make_fill("f1", ib_order_id="IB-1"),
        make_fill("f2", ib_order_id="IB-2"),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 2
    assert {o.order_id for o in orders} == {"ib:IB-1", "ib:IB-2"}


def test_ib_order_id_wins_over_order_reference() -> None:
    """If both ids are present, ib_order_id takes precedence (spec tier 1)."""
    fills = [
        make_fill("f1", ib_order_id="IB-1", order_reference="REF-A"),
        make_fill(
            "f2", ib_order_id="IB-1", order_reference="REF-B", trade_time=T0 + timedelta(seconds=30)
        ),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 1
    assert orders[0].grouping_method == "ib_order_id"


def test_ib_order_id_namespace_isolated_from_order_reference() -> None:
    """An ib_order_id and an orderReference with the same text must not merge."""
    fills = [
        make_fill("f1", ib_order_id="SHARED"),
        make_fill("f2", order_reference="SHARED"),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 2


# ---------------------------------------------------------------------------
# Tier 2: order_reference fallback
# ---------------------------------------------------------------------------


def test_order_reference_used_when_ib_order_id_missing() -> None:
    fills = [
        make_fill("f1", ib_order_id=None, order_reference="REF-A"),
        make_fill(
            "f2", ib_order_id=None, order_reference="REF-A", trade_time=T0 + timedelta(seconds=60)
        ),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 1
    assert orders[0].grouping_method == "order_reference"
    assert orders[0].order_id == "ref:REF-A"


# ---------------------------------------------------------------------------
# Tier 3: time clustering
# ---------------------------------------------------------------------------


def test_time_cluster_within_default_window_merges() -> None:
    fills = [
        make_fill("f1", trade_time=T0),
        make_fill("f2", trade_time=T0 + timedelta(seconds=250)),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 1
    assert orders[0].grouping_method == "time_cluster"


def test_time_cluster_exactly_at_window_boundary_merges() -> None:
    """Boundary is inclusive: gap == window keeps fills in same cluster."""
    fills = [
        make_fill("f1", trade_time=T0),
        make_fill("f2", trade_time=T0 + DEFAULT_TIME_CLUSTER_WINDOW),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 1


def test_time_cluster_past_window_splits() -> None:
    gap = DEFAULT_TIME_CLUSTER_WINDOW + timedelta(seconds=1)
    fills = [
        make_fill("f1", trade_time=T0),
        make_fill("f2", trade_time=T0 + gap),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 2


def test_time_cluster_rolling_anchor_allows_long_chains() -> None:
    """Anchor slides with each fill: 3 fills each 200s apart form one cluster."""
    fills = [
        make_fill("f1", trade_time=T0),
        make_fill("f2", trade_time=T0 + timedelta(seconds=200)),
        make_fill("f3", trade_time=T0 + timedelta(seconds=400)),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 1
    assert orders[0].fill_count == 3


def test_time_cluster_does_not_merge_different_symbols() -> None:
    fills = [
        make_fill("f1", symbol="AAPL"),
        make_fill("f2", symbol="MSFT", trade_time=T0 + timedelta(seconds=30)),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 2


def test_time_cluster_does_not_merge_different_sides() -> None:
    fills = [
        make_fill("f1", side="BUY"),
        make_fill("f2", side="SELL", trade_time=T0 + timedelta(seconds=30)),
    ]
    orders = reconstruct_orders(fills)
    assert len(orders) == 2


def test_custom_time_cluster_window_is_respected() -> None:
    fills = [
        make_fill("f1", trade_time=T0),
        make_fill("f2", trade_time=T0 + timedelta(seconds=45)),
    ]
    # 30s window → fills should NOT merge.
    orders = reconstruct_orders(fills, time_cluster_window=timedelta(seconds=30))
    assert len(orders) == 2


# ---------------------------------------------------------------------------
# Output contract: sort stability, aggregation correctness
# ---------------------------------------------------------------------------


def test_orders_sorted_by_earliest_fill_time() -> None:
    fills = [
        make_fill("f1", ib_order_id="IB-LATE", trade_time=T0 + timedelta(hours=2)),
        make_fill("f2", ib_order_id="IB-EARLY", trade_time=T0),
    ]
    orders = reconstruct_orders(fills)
    assert [o.order_id for o in orders] == ["ib:IB-EARLY", "ib:IB-LATE"]


def test_commission_sums_across_fills() -> None:
    fills = [
        make_fill("f1", commission=Decimal("-1.00"), ib_order_id="IB-1"),
        make_fill(
            "f2",
            commission=Decimal("-2.50"),
            ib_order_id="IB-1",
            trade_time=T0 + timedelta(seconds=10),
        ),
    ]
    orders = reconstruct_orders(fills)
    assert orders[0].total_commission == Decimal("-3.50")


def test_reconstruction_is_deterministic_across_input_order() -> None:
    a = make_fill("f1", ib_order_id="IB-1", trade_time=T0)
    b = make_fill("f2", ib_order_id="IB-1", trade_time=T0 + timedelta(seconds=5))
    c = make_fill("f3", ib_order_id="IB-2", trade_time=T0 + timedelta(minutes=10))
    o1 = reconstruct_orders([a, b, c])
    o2 = reconstruct_orders([c, b, a])
    assert [o.order_id for o in o1] == [o.order_id for o in o2]
    assert [o.fill_count for o in o1] == [o.fill_count for o in o2]


def test_weighted_avg_price_uses_absolute_quantity() -> None:
    """SELL fills often have negative quantities; the weighting must still work."""
    fills = [
        make_fill(
            "f1", side="SELL", quantity=Decimal("-10"), price=Decimal("100"), ib_order_id="IB-1"
        ),
        make_fill(
            "f2",
            side="SELL",
            quantity=Decimal("-30"),
            price=Decimal("110"),
            ib_order_id="IB-1",
            trade_time=T0 + timedelta(seconds=15),
        ),
    ]
    orders = reconstruct_orders(fills)
    # (10*100 + 30*110) / 40 = 4300/40 = 107.5
    assert orders[0].avg_price == Decimal("107.5")


def test_asset_category_propagates_from_first_fill() -> None:
    fills = [
        make_fill("f1", asset_category="OPT", ib_order_id="IB-1"),
        make_fill(
            "f2", asset_category="OPT", ib_order_id="IB-1", trade_time=T0 + timedelta(seconds=20)
        ),
    ]
    orders = reconstruct_orders(fills)
    assert orders[0].asset_category == "OPT"
