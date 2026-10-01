"""FIFO lot accounting for reconstructed orders.

Applies a stream of :class:`~opensteuerauszug.render.tax_overview.orders.Order`
objects to an opening inventory, emitting per-close records with realized
gain/loss attribution. Phase 3 is intentionally long-only: short selling is
out of scope for the SG dashboard and raises :class:`FifoError`.

Cost basis is taken **net of commission**: a BUY's commission inflates the
per-share cost, a SELL's commission reduces per-share proceeds. This matches
the Swiss realization-principle convention where commissions are part of the
acquisition / disposition cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from .orders import Order


class FifoError(Exception):
    """Raised when the order stream violates FIFO accounting invariants."""


@dataclass(frozen=True)
class Lot:
    """One open position batch. Immutable; partial closes produce a new Lot."""

    lot_id: str
    symbol: str
    isin: Optional[str]
    quantity: Decimal
    cost_per_share: Decimal  # includes allocated commission
    currency: str
    opened_at: datetime
    opening_order_id: str


@dataclass(frozen=True)
class LotClose:
    """One FIFO close event. One SELL order can close slices of several lots."""

    lot_id: str
    symbol: str
    isin: Optional[str]
    quantity_closed: Decimal
    cost_per_share: Decimal
    proceeds_per_share: Decimal  # net of allocated commission
    currency: str
    opened_at: datetime
    closed_at: datetime
    opening_order_id: str
    closing_order_id: str

    @property
    def cost_basis(self) -> Decimal:
        return self.cost_per_share * self.quantity_closed

    @property
    def proceeds(self) -> Decimal:
        return self.proceeds_per_share * self.quantity_closed

    @property
    def realized_pnl(self) -> Decimal:
        return (self.proceeds_per_share - self.cost_per_share) * self.quantity_closed


@dataclass
class FifoResult:
    """Final state after applying all orders."""

    open_lots: Dict[str, List[Lot]] = field(default_factory=dict)
    closes: List[LotClose] = field(default_factory=list)

    @property
    def total_realized_pnl(self) -> Decimal:
        return sum((c.realized_pnl for c in self.closes), Decimal(0))


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def apply_orders(
    orders: Sequence[Order],
    opening_lots: Optional[Sequence[Lot]] = None,
) -> FifoResult:
    """Apply ``orders`` to ``opening_lots`` under FIFO semantics.

    Orders are processed in chronological order (``earliest_fill_time``) and
    then by ``order_id`` to break ties deterministically. Opening lots are
    consumed first, preserving their original ``opened_at`` so realized gains
    reflect true holding periods.
    """
    result = FifoResult()
    if opening_lots:
        for lot in opening_lots:
            result.open_lots.setdefault(lot.symbol, []).append(lot)

    for order in sorted(orders, key=lambda o: (o.earliest_fill_time, o.order_id)):
        if order.side == "BUY":
            _apply_buy(order, result)
        elif order.side == "SELL":
            _apply_sell(order, result)
        else:
            raise FifoError(f"Unsupported order side {order.side!r}")

    # Drop the per-symbol empty lists so ``open_lots`` only lists live symbols.
    result.open_lots = {k: v for k, v in result.open_lots.items() if v}
    return result


# ---------------------------------------------------------------------------
# BUY / SELL handlers
# ---------------------------------------------------------------------------


def _apply_buy(order: Order, result: FifoResult) -> None:
    qty = abs(order.total_quantity)
    if qty == 0:
        return
    cost_per_share = _cost_per_share_for_buy(order)
    lot = Lot(
        lot_id=f"lot:{order.order_id}",
        symbol=order.symbol,
        isin=order.isin,
        quantity=qty,
        cost_per_share=cost_per_share,
        currency=order.currency,
        opened_at=order.earliest_fill_time,
        opening_order_id=order.order_id,
    )
    result.open_lots.setdefault(order.symbol, []).append(lot)


def _apply_sell(order: Order, result: FifoResult) -> None:
    qty_remaining = abs(order.total_quantity)
    if qty_remaining == 0:
        return
    proceeds_per_share = _proceeds_per_share_for_sell(order)
    inventory = result.open_lots.get(order.symbol, [])

    while qty_remaining > 0:
        if not inventory:
            raise FifoError(
                f"SELL of {order.total_quantity} {order.symbol} on "
                f"{order.earliest_fill_time.date()} would short the position — "
                f"short selling is out of scope (order_id={order.order_id})"
            )
        lot = inventory[0]
        take = min(lot.quantity, qty_remaining)
        result.closes.append(
            LotClose(
                lot_id=lot.lot_id,
                symbol=lot.symbol,
                isin=lot.isin,
                quantity_closed=take,
                cost_per_share=lot.cost_per_share,
                proceeds_per_share=proceeds_per_share,
                currency=order.currency,
                opened_at=lot.opened_at,
                closed_at=order.earliest_fill_time,
                opening_order_id=lot.opening_order_id,
                closing_order_id=order.order_id,
            )
        )
        if take == lot.quantity:
            inventory.pop(0)
        else:
            inventory[0] = replace(lot, quantity=lot.quantity - take)
        qty_remaining -= take


# ---------------------------------------------------------------------------
# Commission-inclusive per-share math
# ---------------------------------------------------------------------------


def _cost_per_share_for_buy(order: Order) -> Decimal:
    qty = abs(order.total_quantity)
    gross = abs(order.total_money)
    commission = abs(order.total_commission)
    return (gross + commission) / qty


def _proceeds_per_share_for_sell(order: Order) -> Decimal:
    qty = abs(order.total_quantity)
    gross = abs(order.total_money)
    commission = abs(order.total_commission)
    return (gross - commission) / qty
