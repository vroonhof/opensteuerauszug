"""CHF conversion boundary.

Every non-CHF figure that reaches a workbook, HTML table, or PDF cover flows
through :func:`to_chf` first. Centralising this guarantees we use the same
rounding mode everywhere and that we always retain the source amount / rate
for audit (the eCH-0196 standard and cantonal tax offices expect the
conversion trail to be reproducible).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from opensteuerauszug.core.exchange_rate_provider import ExchangeRateProvider

CHF = "CHF"
CHF_QUANTUM = Decimal("0.01")  # Swiss tax statements report CHF to the rappen.


@dataclass(frozen=True)
class MoneyCHF:
    """CHF amount plus the conversion trail that produced it."""

    amount: Decimal  # rounded to 0.01 CHF (Rappen)
    source_currency: str
    source_amount: Decimal
    rate: Decimal
    reference_date: date

    def __add__(self, other: "MoneyCHF") -> "MoneyCHF":
        """Summing CHF amounts loses the per-leg source trail by design.

        We keep the first leg's currency metadata as a hint but the resulting
        ``MoneyCHF`` should be treated as an aggregate. Callers that need
        per-leg breakdowns should keep a list rather than folding.
        """
        if not isinstance(other, MoneyCHF):
            return NotImplemented
        return MoneyCHF(
            amount=_round_chf(self.amount + other.amount),
            source_currency=(
                "MIXED" if self.source_currency != other.source_currency else self.source_currency
            ),
            source_amount=self.source_amount + other.source_amount,
            rate=Decimal("0"),  # no single rate for aggregates
            reference_date=max(self.reference_date, other.reference_date),
        )


def to_chf(
    amount: Decimal,
    currency: str,
    reference_date: date,
    provider: ExchangeRateProvider,
    *,
    path_prefix_for_log: str | None = None,
) -> MoneyCHF:
    """Convert ``amount`` in ``currency`` to CHF using ``provider`` rates.

    CHF inputs short-circuit with ``rate = 1`` and no provider call, so unit
    tests don't need to stub a rate for the base currency.
    """
    if currency == CHF:
        rounded = _round_chf(amount)
        return MoneyCHF(
            amount=rounded,
            source_currency=CHF,
            source_amount=amount,
            rate=Decimal("1"),
            reference_date=reference_date,
        )
    rate = provider.get_exchange_rate(
        currency, reference_date, path_prefix_for_log=path_prefix_for_log
    )
    converted = _round_chf(amount * rate)
    return MoneyCHF(
        amount=converted,
        source_currency=currency,
        source_amount=amount,
        rate=rate,
        reference_date=reference_date,
    )


def sum_chf(amounts: Iterable[MoneyCHF]) -> Decimal:
    """Sum the CHF amounts of an iterable of :class:`MoneyCHF`."""
    return _round_chf(sum((m.amount for m in amounts), Decimal(0)))


def _round_chf(value: Decimal) -> Decimal:
    return value.quantize(CHF_QUANTUM, rounding=ROUND_HALF_UP)
