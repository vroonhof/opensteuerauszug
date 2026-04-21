"""Accumulator TypedDicts shared by broker importers.

Every importer builds up the same two per-position buckets while walking
the broker's source data: a list of ``SecurityStock`` entries and a list
of per-position payments.  Keeping the shapes in one place avoids the
cross-importer imports that grew organically (e.g. the Fidelity importer
previously reached into ``ibkr_importer`` for these).
"""

from typing import TypedDict

from opensteuerauszug.model.ech0196 import (
    BankAccountPayment,
    SecurityPayment,
    SecurityStock,
)


class SecurityPositionData(TypedDict):
    """Per-security accumulator: stock entries and security-level payments."""

    stocks: list[SecurityStock]
    payments: list[SecurityPayment]


class CashPositionData(TypedDict):
    """Per-cash-bucket accumulator: stock entries and bank-account payments."""

    stocks: list[SecurityStock]
    payments: list[BankAccountPayment]


class SecurityNameMetadata(TypedDict):
    """Best-name tracking state for a single security position."""

    best_name: str | None
    priority: int
