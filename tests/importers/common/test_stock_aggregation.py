from datetime import date
from decimal import Decimal

from opensteuerauszug.importers.common import aggregate_mutations
from opensteuerauszug.model.ech0196 import SecurityStock


def _mut(qty, price, order_id="O1", d=date(2024, 6, 1)):
    return SecurityStock(
        referenceDate=d,
        mutation=True,
        quantity=Decimal(qty),
        unitPrice=Decimal(price),
        orderId=order_id,
        balanceCurrency="USD",
        quotationType="PIECE",
    )


def _balance(qty, d):
    return SecurityStock(
        referenceDate=d,
        mutation=False,
        quantity=Decimal(qty),
        balanceCurrency="USD",
        quotationType="PIECE",
    )


def test_same_order_same_side_merges_with_weighted_price():
    result = aggregate_mutations([_mut("10", "100"), _mut("10", "110")])
    assert len(result) == 1
    assert result[0].quantity == Decimal("20")
    assert result[0].unitPrice == Decimal("105")


def test_different_order_id_does_not_merge():
    result = aggregate_mutations(
        [_mut("10", "100", order_id="O1"), _mut("10", "100", order_id="O2")]
    )
    assert len(result) == 2


def test_opposite_side_does_not_merge():
    result = aggregate_mutations([_mut("10", "100"), _mut("-5", "100")])
    assert len(result) == 2


def test_balance_entries_pass_through_and_break_pending():
    result = aggregate_mutations(
        [_mut("10", "100"), _balance("10", date(2024, 6, 2)), _mut("5", "100")]
    )
    # first mutation flushed on balance, second mutation kept separate
    assert [s.mutation for s in result] == [True, False, True]
    assert result[0].quantity == Decimal("10")
    assert result[2].quantity == Decimal("5")
