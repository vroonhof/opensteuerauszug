"""Phase-3 tests: FIFO lot tracker with realized P&L attribution.

Covers the FIFO invariants the SG dashboard relies on: oldest lots close
first, partial closes preserve remaining quantity, commissions enter cost
basis, and the opening inventory feeds into the same queue.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from opensteuerauszug.render.tax_overview.fifo import (
    FifoError,
    Lot,
    apply_orders,
)
from opensteuerauszug.render.tax_overview.orders import Fill, reconstruct_orders

T0 = datetime(2025, 1, 15, 9, 30, 0)


def make_order_from_fill(
    fill_id: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    *,
    commission: Decimal = Decimal("-1.00"),
    trade_time: datetime | None = None,
    ib_order_id: str | None = None,
    symbol: str = "AAPL",
):
    """Build a single-fill Order through the real reconstruction path.

    Keeps tests close to production behaviour (we never hand-roll Order
    objects; they always come out of reconstruct_orders).
    """
    fill = Fill(
        fill_id=fill_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        money=abs(quantity) * price,
        commission=commission,
        currency="USD",
        trade_time=trade_time or T0,
        asset_category="STK",
        isin="US0378331005",
        conid="265598",
        ib_order_id=ib_order_id or f"IB-{fill_id}",
    )
    return reconstruct_orders([fill])[0]


# ---------------------------------------------------------------------------
# BUY-only behaviour
# ---------------------------------------------------------------------------


def test_empty_inputs_produce_empty_result() -> None:
    result = apply_orders([])
    assert result.open_lots == {}
    assert result.closes == []
    assert result.total_realized_pnl == Decimal("0")


def test_single_buy_opens_one_lot() -> None:
    buy = make_order_from_fill("f1", "BUY", Decimal("10"), Decimal("180"))
    result = apply_orders([buy])
    assert "AAPL" in result.open_lots
    (lot,) = result.open_lots["AAPL"]
    assert lot.quantity == Decimal("10")
    # cost basis = (10*180 + 1) / 10 = 180.10
    assert lot.cost_per_share == Decimal("180.1")


def test_two_buys_open_two_lots_in_order() -> None:
    b1 = make_order_from_fill("f1", "BUY", Decimal("10"), Decimal("180"), trade_time=T0)
    b2 = make_order_from_fill(
        "f2", "BUY", Decimal("5"), Decimal("190"), trade_time=T0 + timedelta(days=1)
    )
    result = apply_orders([b1, b2])
    assert len(result.open_lots["AAPL"]) == 2
    assert result.open_lots["AAPL"][0].opened_at == T0
    assert result.open_lots["AAPL"][1].opened_at == T0 + timedelta(days=1)


# ---------------------------------------------------------------------------
# FIFO close ordering
# ---------------------------------------------------------------------------


def test_sell_closes_oldest_lot_first() -> None:
    b1 = make_order_from_fill("f1", "BUY", Decimal("10"), Decimal("180"), trade_time=T0)
    b2 = make_order_from_fill(
        "f2", "BUY", Decimal("10"), Decimal("190"), trade_time=T0 + timedelta(days=1)
    )
    s = make_order_from_fill(
        "f3", "SELL", Decimal("-5"), Decimal("200"), trade_time=T0 + timedelta(days=10)
    )
    result = apply_orders([b1, b2, s])
    (close,) = result.closes
    assert close.cost_per_share == Decimal("180.1")  # came from the T0 lot
    assert close.quantity_closed == Decimal("5")


def test_partial_close_leaves_remaining_quantity_in_first_lot() -> None:
    b1 = make_order_from_fill("f1", "BUY", Decimal("10"), Decimal("180"), trade_time=T0)
    s = make_order_from_fill(
        "f2", "SELL", Decimal("-3"), Decimal("200"), trade_time=T0 + timedelta(days=5)
    )
    result = apply_orders([b1, s])
    (remaining,) = result.open_lots["AAPL"]
    assert remaining.quantity == Decimal("7")
    # Cost basis per share must be preserved after a partial close.
    assert remaining.cost_per_share == Decimal("180.1")


def test_sell_spanning_multiple_lots_emits_one_close_per_lot() -> None:
    b1 = make_order_from_fill("f1", "BUY", Decimal("10"), Decimal("180"), trade_time=T0)
    b2 = make_order_from_fill(
        "f2", "BUY", Decimal("10"), Decimal("190"), trade_time=T0 + timedelta(days=1)
    )
    s = make_order_from_fill(
        "f3", "SELL", Decimal("-15"), Decimal("200"), trade_time=T0 + timedelta(days=10)
    )
    result = apply_orders([b1, b2, s])
    assert len(result.closes) == 2
    qtys = [c.quantity_closed for c in result.closes]
    # Oldest lot fully consumed first, then 5 from the second.
    assert qtys == [Decimal("10"), Decimal("5")]
    assert result.open_lots["AAPL"][0].quantity == Decimal("5")


# ---------------------------------------------------------------------------
# Commission-inclusive P&L
# ---------------------------------------------------------------------------


def test_commissions_flow_into_cost_basis_and_proceeds() -> None:
    b = make_order_from_fill("f1", "BUY", Decimal("10"), Decimal("100"), commission=Decimal("-2"))
    s = make_order_from_fill(
        "f2",
        "SELL",
        Decimal("-10"),
        Decimal("110"),
        commission=Decimal("-3"),
        trade_time=T0 + timedelta(days=30),
    )
    result = apply_orders([b, s])
    (close,) = result.closes
    # cost per share = (1000 + 2) / 10 = 100.2
    assert close.cost_per_share == Decimal("100.2")
    # proceeds per share = (1100 - 3) / 10 = 109.7
    assert close.proceeds_per_share == Decimal("109.7")
    # realized = (109.7 - 100.2) * 10 = 95
    assert close.realized_pnl == Decimal("95")


def test_total_realized_pnl_sums_every_close() -> None:
    b1 = make_order_from_fill("f1", "BUY", Decimal("10"), Decimal("100"), trade_time=T0)
    b2 = make_order_from_fill(
        "f2", "BUY", Decimal("10"), Decimal("110"), trade_time=T0 + timedelta(days=1)
    )
    s = make_order_from_fill(
        "f3", "SELL", Decimal("-15"), Decimal("120"), trade_time=T0 + timedelta(days=10)
    )
    result = apply_orders([b1, b2, s])
    # Two closes: 10@100 -> 120 (ignoring small commissions roughly 200 gain)
    # and 5@110 -> 120 (~50 gain). Exact value uses the commission math.
    total = sum(c.realized_pnl for c in result.closes)
    assert total == result.total_realized_pnl


# ---------------------------------------------------------------------------
# Opening inventory (prior-year carryover)
# ---------------------------------------------------------------------------


def test_opening_lots_are_consumed_before_current_year_buys() -> None:
    opening = Lot(
        lot_id="opening-1",
        symbol="AAPL",
        isin="US0378331005",
        quantity=Decimal("10"),
        cost_per_share=Decimal("150.00"),
        currency="USD",
        opened_at=datetime(2023, 6, 1),
        opening_order_id="CARRY-2023",
    )
    new_buy = make_order_from_fill("f1", "BUY", Decimal("10"), Decimal("180"), trade_time=T0)
    s = make_order_from_fill(
        "f2", "SELL", Decimal("-10"), Decimal("200"), trade_time=T0 + timedelta(days=5)
    )
    result = apply_orders([new_buy, s], opening_lots=[opening])
    (close,) = result.closes
    # The prior-year lot went first — holding period reflects 2023 purchase.
    assert close.opened_at == datetime(2023, 6, 1)
    assert close.cost_per_share == Decimal("150")
    assert close.opening_order_id == "CARRY-2023"
    # New buy still open.
    (remaining,) = result.open_lots["AAPL"]
    assert remaining.opening_order_id == new_buy.order_id


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_selling_more_than_held_raises_fifo_error() -> None:
    b = make_order_from_fill("f1", "BUY", Decimal("5"), Decimal("100"), trade_time=T0)
    s = make_order_from_fill(
        "f2", "SELL", Decimal("-10"), Decimal("110"), trade_time=T0 + timedelta(days=1)
    )
    with pytest.raises(FifoError, match="short selling is out of scope"):
        apply_orders([b, s])


def test_opening_sell_without_inventory_raises() -> None:
    s = make_order_from_fill("f1", "SELL", Decimal("-1"), Decimal("100"))
    with pytest.raises(FifoError, match="short selling is out of scope"):
        apply_orders([s])


def test_unknown_side_raises() -> None:
    # Build an Order with an invalid side by abusing reconstruct_orders.
    fill = Fill(
        fill_id="f1",
        symbol="AAPL",
        side="CANCEL",
        quantity=Decimal("1"),
        price=Decimal("100"),
        money=Decimal("100"),
        commission=Decimal("0"),
        currency="USD",
        trade_time=T0,
        asset_category="STK",
        ib_order_id="IB-1",
    )
    (order,) = reconstruct_orders([fill])
    with pytest.raises(FifoError, match="Unsupported order side"):
        apply_orders([order])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_apply_orders_is_order_independent() -> None:
    b1 = make_order_from_fill("f1", "BUY", Decimal("10"), Decimal("100"), trade_time=T0)
    b2 = make_order_from_fill(
        "f2", "BUY", Decimal("10"), Decimal("110"), trade_time=T0 + timedelta(days=1)
    )
    s = make_order_from_fill(
        "f3", "SELL", Decimal("-5"), Decimal("150"), trade_time=T0 + timedelta(days=2)
    )
    # Shuffled input must yield identical output because apply_orders sorts
    # by (earliest_fill_time, order_id) internally.
    forward = apply_orders([b1, b2, s])
    shuffled = apply_orders([s, b2, b1])
    assert [c.realized_pnl for c in forward.closes] == [c.realized_pnl for c in shuffled.closes]
    assert [l.quantity for l in forward.open_lots["AAPL"]] == [
        l.quantity for l in shuffled.open_lots["AAPL"]
    ]
