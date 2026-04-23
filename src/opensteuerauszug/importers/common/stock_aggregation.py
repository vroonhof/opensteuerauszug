"""Aggregate successive same-day, same-order mutations.

Multiple partial fills of a single order appear as separate ``SecurityStock``
entries.  Importers want them collapsed into one entry per (date, orderId,
side) so the resulting statement reads cleanly.

This is a pure list-to-list transformation; importers call it on the
per-position stock list just before post-processing.
"""

from typing import List

from opensteuerauszug.model.ech0196 import SecurityStock


def aggregate_mutations(stocks: List[SecurityStock]) -> List[SecurityStock]:
    """Merge runs of same-side mutations sharing date + orderId + currency.

    Preserves input order; non-mutation balance entries pass through
    unchanged.  When mutations are merged the combined quantity is the
    sum, and the combined unit price is the quantity-weighted average if
    prices differed.
    """
    aggregated: List[SecurityStock] = []
    pending: SecurityStock | None = None

    for stock in stocks:
        if stock.mutation:
            if (
                pending
                and pending.referenceDate == stock.referenceDate
                and pending.orderId == stock.orderId
                and pending.balanceCurrency == stock.balanceCurrency
                and pending.quotationType == stock.quotationType
                # same sign => same side (buy vs sell)
                and (pending.quantity * stock.quantity) > 0
            ):
                total_quantity = pending.quantity + stock.quantity
                if pending.unitPrice != stock.unitPrice:
                    pending.unitPrice = (
                        pending.quantity * pending.unitPrice
                        + stock.quantity * stock.unitPrice
                    ) / total_quantity
                pending.quantity = total_quantity
            else:
                if pending:
                    aggregated.append(pending)
                pending = SecurityStock(
                    referenceDate=stock.referenceDate,
                    mutation=True,
                    quantity=stock.quantity,
                    unitPrice=stock.unitPrice,
                    name=stock.name,
                    orderId=stock.orderId,
                    balanceCurrency=stock.balanceCurrency,
                    quotationType=stock.quotationType,
                )
        else:
            if pending:
                aggregated.append(pending)
                pending = None
            aggregated.append(stock)

    if pending:
        aggregated.append(pending)

    return aggregated
