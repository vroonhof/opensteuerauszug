"""Shared post-processing: fold per-position accumulators into a TaxStatement.

After extraction each importer has two dict-of-accumulators:

* ``processed_security_positions[SecurityPosition] -> SecurityPositionData``
* ``processed_cash_positions[key] -> CashPositionData``

and a ``SecurityNameRegistry`` capturing best-name-wins picks.  The loop
that turns these into ``ListOfSecurities`` / ``ListOfBankAccounts`` is
almost identical across importers — it aggregates same-day mutations,
picks a currency/quotationType, reconciles period-start and period-end
balances via :class:`PositionReconciler`, appends synthetic opening /
closing boundary stocks when missing, sorts, and builds ``Security`` /
``BankAccount`` models.

The helpers in this module take a *partially filled* ``TaxStatement``
— the importer pre-populates ``periodFrom`` / ``periodTo`` /
``institution`` / ``client`` / ``canton`` — and augment it in place
with ``listOfSecurities`` / ``listOfBankAccounts``.  Importer-specific
flavour (which eCH category applies, whether short positions are
allowed, whether to attach an ISIN) is routed through a callable or a
small per-position :class:`PositionHints` record; no broker-specific
types leak into this module.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import (
    Callable,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from opensteuerauszug.core.position_reconciler import PositionReconciler
from opensteuerauszug.model.ech0196 import (
    BankAccount,
    BankAccountName,
    BankAccountNumber,
    BankAccountPayment,
    BankAccountTaxValue,
    Depot,
    DepotNumber,
    ISINType,
    ListOfBankAccounts,
    ListOfSecurities,
    Security,
    SecurityCategory,
    SecurityStock,
    TaxStatement,
)
from opensteuerauszug.model.position import SecurityPosition

from .security_name import SecurityNameRegistry
from .stock_aggregation import aggregate_mutations
from .types import CashPositionData, SecurityPositionData


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PositionHints:
    """Per-position flavour that the shared postprocess needs from the caller.

    Importers derive these from whatever broker-native classification
    they keep (e.g. IBKR's ``asset_category``/``sub_category`` tuple or
    Fidelity's bare category string).  Everything on this record has a
    sensible default so callers only need to override what differs from
    the common case.
    """

    security_category: SecurityCategory = "SHARE"
    country: str = "US"
    # Whether a negative tentative opening balance should be kept as-is
    # (short positions / written options) rather than clamped to zero.
    allow_negative_opening: bool = False
    # Whether a final negative opening/closing balance should only warn
    # instead of raising. Distinct from ``allow_negative_opening`` since
    # IBKR distinguishes OPT/FOP vs OPT/FOP with sub C/P.
    allow_negative_balance: bool = False
    # Mark the synthesized Security as a rights issue.
    is_rights_issue: bool = False
    # Drop the security entirely when both opening and closing are zero.
    skip_if_zero: bool = False


_DEFAULT_HINTS = PositionHints()


def _hints_for(
    sec_pos: SecurityPosition,
    hints_fn: Optional[Callable[[SecurityPosition], PositionHints]],
) -> PositionHints:
    if hints_fn is None:
        return _DEFAULT_HINTS
    return hints_fn(sec_pos)


def _pick_currency_and_quotation(
    stocks: Sequence[SecurityStock],
    payments: Sequence,
    identifier: str,
) -> Tuple[str, str]:
    """Replicates the IBKR/Fidelity currency + quotationType selection."""
    primary_currency: Optional[str] = None
    primary_quotation_type: str = "PIECE"
    if stocks:
        balance_stocks = [s for s in stocks if not s.mutation and s.balanceCurrency]
        source = balance_stocks[0] if balance_stocks else stocks[0]
        primary_currency = source.balanceCurrency
        primary_quotation_type = source.quotationType
    if not primary_currency:
        if payments:
            primary_currency = payments[0].amountCurrency
        else:
            raise ValueError(
                f"Cannot determine currency for security {identifier}. "
                "No stocks or payments with currency info."
            )
    return primary_currency, primary_quotation_type


def _synthesize_boundary_balances(
    stocks: List[SecurityStock],
    *,
    period_from: date,
    period_to: date,
    hints: PositionHints,
    identifier: str,
    strict_consistency: bool,
    run_initial_consistency_check: bool,
) -> Tuple[Decimal, Decimal, date]:
    end_plus_one = period_to + timedelta(days=1)

    if run_initial_consistency_check:
        initial = PositionReconciler(
            list(stocks), identifier=f"{identifier}-initial_check"
        )
        is_consistent, _ = initial.check_consistency(
            print_log=True,
            raise_on_error=strict_consistency,
            assume_zero_if_no_balances=True,
        )
        if not is_consistent and not strict_consistency:
            logger.warning(
                "%s: initial consistency check on raw data failed; "
                "proceeding with synthesis.",
                identifier,
            )

    reconciler = PositionReconciler(
        list(stocks), identifier=f"{identifier}-reconcile"
    )
    end_pos = reconciler.synthesize_position_at_date(end_plus_one)
    closing_balance = end_pos.quantity if end_pos else Decimal("0")

    start_pos = reconciler.synthesize_position_at_date(period_from)
    if start_pos:
        opening_balance = start_pos.quantity
    else:
        trades_quantity_total = sum(
            (s.quantity for s in stocks if s.mutation), Decimal("0")
        )
        tentative = closing_balance - trades_quantity_total
        opening_balance = (
            tentative
            if tentative >= 0 or hints.allow_negative_opening
            else Decimal("0")
        )

    if opening_balance < 0 or closing_balance < 0:
        message = (
            f"Negative balance computed for security {identifier} "
            f"(start {opening_balance}, end {closing_balance}). "
            "In case you expect short positions, please report this to "
            "the developers for further investigation."
        )
        if hints.allow_negative_balance:
            logger.warning(message)
        else:
            raise ValueError(message)

    return opening_balance, closing_balance, end_plus_one


def _append_boundary_stock_if_missing(
    stocks: List[SecurityStock],
    *,
    reference_date: date,
    quantity: Decimal,
    currency: str,
    quotation_type: str,
    name: Optional[str],
    skip_when_zero: bool,
) -> None:
    exists = any(
        (not s.mutation and s.referenceDate == reference_date) for s in stocks
    )
    if exists:
        return
    if skip_when_zero and quantity == 0:
        return
    stocks.append(
        SecurityStock(
            referenceDate=reference_date,
            mutation=False,
            quotationType=quotation_type,
            quantity=quantity,
            balanceCurrency=currency,
            name=name,
        )
    )


def augment_list_of_securities(
    statement: TaxStatement,
    positions: Mapping[SecurityPosition, SecurityPositionData],
    *,
    name_registry: SecurityNameRegistry,
    hints_for: Optional[Callable[[SecurityPosition], PositionHints]] = None,
    strict_consistency: bool = True,
    run_initial_consistency_check: bool = False,
    opening_stock_name: Optional[str] = None,
    closing_stock_name: Optional[str] = None,
) -> None:
    """Fold ``positions`` into ``statement.listOfSecurities`` in place.

    ``statement.periodFrom`` / ``statement.periodTo`` must be set; they
    drive the boundary-balance synthesis.

    ``hints_for`` lets the caller inject per-position category / country
    / short-position flavour without leaking broker enums in here.
    ``opening_stock_name`` / ``closing_stock_name`` are attached to the
    synthetic balance rows when the caller wants a human-readable label
    (Fidelity does; IBKR leaves them unnamed).
    """
    period_from = statement.periodFrom
    period_to = statement.periodTo
    if period_from is None or period_to is None:
        raise ValueError(
            "augment_list_of_securities requires statement.periodFrom and "
            "statement.periodTo to be set before the call."
        )

    depot_securities_map: defaultdict[str, List[Security]] = defaultdict(list)
    position_id = 0
    for sec_pos_obj, data in positions.items():
        position_id += 1
        hints = _hints_for(sec_pos_obj, hints_for)

        sorted_stocks = aggregate_mutations(data["stocks"])
        sorted_payments = sorted(data["payments"], key=lambda p: p.paymentDate)

        identifier = sec_pos_obj.symbol or sec_pos_obj.description or "<unknown>"
        primary_currency, primary_quotation_type = _pick_currency_and_quotation(
            sorted_stocks, sorted_payments, identifier
        )

        opening_balance, closing_balance, end_plus_one = _synthesize_boundary_balances(
            sorted_stocks,
            period_from=period_from,
            period_to=period_to,
            hints=hints,
            identifier=identifier,
            strict_consistency=strict_consistency,
            run_initial_consistency_check=run_initial_consistency_check,
        )

        if hints.skip_if_zero and opening_balance == 0 and closing_balance == 0:
            logger.info(
                "Skipping security %s because balances are zero and "
                "skip_if_zero is set.",
                identifier,
            )
            continue

        _append_boundary_stock_if_missing(
            sorted_stocks,
            reference_date=period_from,
            quantity=opening_balance,
            currency=primary_currency,
            quotation_type=primary_quotation_type,
            name=opening_stock_name,
            skip_when_zero=True,
        )
        _append_boundary_stock_if_missing(
            sorted_stocks,
            reference_date=end_plus_one,
            quantity=closing_balance,
            currency=primary_currency,
            quotation_type=primary_quotation_type,
            name=closing_stock_name,
            skip_when_zero=False,
        )

        sorted_stocks = sorted(
            sorted_stocks, key=lambda s: (s.referenceDate, s.mutation)
        )

        security = Security(
            positionId=position_id,
            currency=primary_currency,
            quotationType=primary_quotation_type,
            securityCategory=hints.security_category,
            securityName=name_registry.resolve(sec_pos_obj),
            symbol=sec_pos_obj.symbol,
            isin=(
                ISINType(sec_pos_obj.isin)
                if sec_pos_obj.isin is not None
                else None
            ),
            valorNumber=sec_pos_obj.valor,
            country=hints.country,
            stock=sorted_stocks,
            payment=sorted_payments,
            is_rights_issue=hints.is_rights_issue,
        )
        depot_securities_map[sec_pos_obj.depot].append(security)

    depots = [
        Depot(depotNumber=DepotNumber(depot_id), security=securities)
        for depot_id, securities in depot_securities_map.items()
        if securities
    ]
    statement.listOfSecurities = (
        ListOfSecurities(depot=depots) if depots else None
    )


# ---------------------------------------------------------------------------
# Bank-accounts side
# ---------------------------------------------------------------------------


@dataclass
class CashAccountEntry:
    """Per-(account, currency) bucket consumed by :func:`augment_list_of_bank_accounts`.

    Each importer produces these from its own source-of-truth: IBKR from
    the ``CashReport`` section, Fidelity from the statement summary.
    ``closing_balance`` is required (``None`` triggers a ValueError
    during assembly, as in the original importer code).
    """

    account_id: str
    currency: str
    closing_balance: Optional[Decimal]
    payments: List[BankAccountPayment] = field(default_factory=list)
    country: str = "US"
    name: Optional[str] = None
    number: Optional[str] = None
    opening_date: Optional[date] = None
    closing_date: Optional[date] = None


def fold_cash_payments(
    seed_entries: Iterable[CashAccountEntry],
    processed_cash_positions: Mapping[tuple, CashPositionData],
) -> List[CashAccountEntry]:
    """Merge ``processed_cash_positions`` payments onto ``seed_entries``.

    Seeds are matched on ``(account_id, currency)``.  Payment-only
    buckets (i.e. currencies with cash transactions but no closing
    balance in the statement summary) produce a synthetic entry with
    ``closing_balance=None`` — downstream ``augment_list_of_bank_accounts``
    will surface this as a ValueError, preserving existing behaviour.
    """
    by_key: dict[tuple[str, str], CashAccountEntry] = {}
    for entry in seed_entries:
        by_key[(entry.account_id, entry.currency)] = entry

    for (stmt_account_id, currency_code, _), data in processed_cash_positions.items():
        key = (str(stmt_account_id), str(currency_code))
        if key in by_key:
            by_key[key].payments.extend(data["payments"])
        else:
            by_key[key] = CashAccountEntry(
                account_id=str(stmt_account_id),
                currency=str(currency_code),
                closing_balance=None,
                payments=list(data["payments"]),
            )
    return list(by_key.values())


def augment_list_of_bank_accounts(
    statement: TaxStatement,
    entries: Iterable[CashAccountEntry],
) -> None:
    """Fold ``entries`` into ``statement.listOfBankAccounts`` in place.

    ``statement.periodTo`` is used as the ``BankAccountTaxValue``
    reference date.  Entries without a ``closing_balance`` raise, which
    matches the existing IBKR / Fidelity behaviour ("hard error if no
    closing balance").
    """
    period_to = statement.periodTo
    if period_to is None:
        raise ValueError(
            "augment_list_of_bank_accounts requires statement.periodTo "
            "to be set before the call."
        )

    bank_accounts: List[BankAccount] = []
    for entry in entries:
        if entry.closing_balance is None:
            raise ValueError(
                f"No closing cash balance for account {entry.account_id}, "
                f"currency {entry.currency} for date {period_to}."
            )
        name = entry.name or f"{entry.account_id} {entry.currency}"
        number = entry.number or f"{entry.account_id}-{entry.currency}"
        sorted_payments = sorted(
            entry.payments or [], key=lambda p: p.paymentDate
        )
        tax_value = BankAccountTaxValue(
            referenceDate=period_to,
            balanceCurrency=entry.currency,
            balance=entry.closing_balance,
        )
        bank_accounts.append(
            BankAccount(
                bankAccountName=BankAccountName(name),
                bankAccountNumber=BankAccountNumber(number),
                bankAccountCountry=entry.country,
                bankAccountCurrency=entry.currency,
                openingDate=entry.opening_date,
                closingDate=entry.closing_date,
                payment=sorted_payments,
                taxValue=tax_value,
            )
        )
    statement.listOfBankAccounts = (
        ListOfBankAccounts(bankAccount=bank_accounts) if bank_accounts else None
    )
