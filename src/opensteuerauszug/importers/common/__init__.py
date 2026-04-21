"""Shared helpers used by multiple broker importers.

Importers historically re-implemented similar glue (TypedDict aggregators,
decimal parsing, stock-aggregation, name/canton/client building).  This
package collects the reusable pieces so each importer can focus on the
extraction that is actually broker-specific.

The helpers here are intentionally plain functions or small value objects,
composed into the importers rather than imposed via inheritance.
"""

from .parsing import to_decimal
from .stock_aggregation import aggregate_mutations
from .types import CashPositionData, SecurityNameMetadata, SecurityPositionData

__all__ = [
    "CashPositionData",
    "SecurityPositionData",
    "SecurityNameMetadata",
    "aggregate_mutations",
    "to_decimal",
]
