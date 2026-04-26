"""Shared helpers used by multiple broker importers.

Importers historically re-implemented similar glue (TypedDict aggregators,
decimal parsing, stock-aggregation, name/canton/client building).  This
package collects the reusable pieces so each importer can focus on the
extraction that is actually broker-specific.

The helpers here are intentionally plain functions or small value objects,
composed into the importers rather than imposed via inheritance.
"""

from .client import (
    build_client,
    is_nonempty_string,
    parse_swiss_canton,
    resolve_first_last_name,
    split_full_name,
)
from .parsing import to_decimal
from .payments import apply_withholding_tax_fields, build_security_payment
from .postprocess import (
    CashAccountEntry,
    PositionHints,
    augment_list_of_bank_accounts,
    augment_list_of_securities,
    fold_cash_payments,
)
from .security_name import SecurityNameRegistry
from .stock_aggregation import aggregate_mutations
from .types import CashPositionData, SecurityNameMetadata, SecurityPositionData

__all__ = [
    "CashAccountEntry",
    "CashPositionData",
    "PositionHints",
    "SecurityPositionData",
    "SecurityNameMetadata",
    "SecurityNameRegistry",
    "aggregate_mutations",
    "apply_withholding_tax_fields",
    "augment_list_of_bank_accounts",
    "augment_list_of_securities",
    "build_client",
    "build_security_payment",
    "fold_cash_payments",
    "is_nonempty_string",
    "parse_swiss_canton",
    "resolve_first_last_name",
    "split_full_name",
    "to_decimal",
]
