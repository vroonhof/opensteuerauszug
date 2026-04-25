import logging
from typing import List, Dict, Optional, Tuple
import os
from decimal import Decimal
from functools import lru_cache
from opensteuerauszug.model.ech0196 import (
    BankAccountPayment, Client, ClientNumber, Institution, SecurityPayment,
    SecurityStock, TaxStatement,
)
from opensteuerauszug.model.position import SecurityPosition, CashPosition
from opensteuerauszug.render.translations import Language, DEFAULT_LANGUAGE
from .statement_extractor import StatementExtractor
from datetime import date, timedelta
from .fallback_position_extractor import FallbackPositionExtractor
from .position_extractor import PositionExtractor
from .transaction_extractor import TransactionExtractor
from opensteuerauszug.util.date_coverage import DateRangeCoverage
from collections import defaultdict
from opensteuerauszug.core.position_reconciler import PositionReconciler
from opensteuerauszug.config.models import SchwabAccountSettings
from opensteuerauszug.importers.common import (
    CashAccountEntry,
    PositionHints,
    SecurityNameRegistry,
    SecurityPositionData,
    augment_list_of_bank_accounts,
    augment_list_of_securities,
)
import holidays

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settlement date helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _nyse_holidays(year: int) -> holidays.NYSE:
    """Return cached NYSE holiday calendar for *year*."""
    return holidays.NYSE(years=year)


def _is_nyse_holiday(d: date) -> bool:
    """Return True if *d* is a NYSE exchange holiday (weekends excluded)."""
    return d in _nyse_holidays(d.year)


def next_business_day(d: date) -> date:
    """Return the next calendar day that is a NYSE trading day.

    Skips weekends and US exchange (NYSE) holidays so that settlement dates
    accurately reflect days on which the exchange is open for business.
    """
    result = d + timedelta(days=1)
    while result.weekday() >= 5 or _is_nyse_holiday(result):
        result += timedelta(days=1)
    return result


def settlement_date(trade_date: date) -> date:
    """Return the T+1 settlement date for a trade.

    US equities settled T+2 until May 2024, then switched to T+1.
    We use T+1 as the conservative default, skipping weekends and NYSE
    exchange holidays.
    """
    return next_business_day(trade_date)


def split_unsettled_cash(
    stocks: List[SecurityStock],
    period_end: date,
) -> Tuple[List[SecurityStock], List[SecurityStock]]:
    """Partition *stocks* into settled and unsettled at *period_end*.

    For every T+1 mutation (``requires_settlement=True``) that settles within
    the period, the mutation's ``referenceDate`` is unconditionally shifted to
    the settlement date.  Cash moves on settlement day, not trade day, so this
    is the semantically correct date for cash-account entries.  It also
    naturally handles intra-period balance checkpoints: because balance entries
    sort before mutations on the same date, a settlement-dated mutation always
    appears *after* any same-day balance snapshot in the reconciler's sequence.

    Mutations that settle strictly after *period_end* are placed in the
    unsettled bucket; the caller reports them as a separate account.

    Balance entries (mutation=False) and non-settlement mutations are placed
    in the settled bucket unchanged.

    Args:
        stocks: All SecurityStock entries for a cash position.
        period_end: The last day of the reporting period (inclusive).

    Returns:
        (settled_stocks, unsettled_stocks)
    """
    settled: List[SecurityStock] = []
    unsettled: List[SecurityStock] = []
    for s in stocks:
        if s.mutation and s.requires_settlement:
            settle = settlement_date(s.referenceDate)
            if settle > period_end:
                # Will not settle within the period → separate unsettled account.
                unsettled.append(s)
            else:
                # Always date cash at settlement, not trade date.
                settled.append(s.model_copy(update={"referenceDate": settle}))
        else:
            settled.append(s)
    return settled, unsettled



def _get_configured_account_info(depot_short_id: str, account_settings_list: List[SchwabAccountSettings], is_awards_depot: bool) -> Tuple[Optional[str], str]:
    """
    Determines the account number and display name based on configuration and depot type.
    """
    if is_awards_depot:
        # For awards, depot_short_id might be a symbol or specific awards account ID if available
        return None, f"Equity Awards {depot_short_id}"
    else:
        found_account_number: Optional[str] = None
        first_matching_alias: Optional[str] = None
        for setting in account_settings_list:
            if setting.account_number.endswith(depot_short_id):
                if found_account_number is not None:
                    logger.warning(f"Multiple configured Schwab accounts end with '...{depot_short_id}'. Using first found: '{found_account_number}' (alias: '{first_matching_alias}'). Consider refining configurations if this is not intended.")
                    continue  # Stick with the first one found
                else:
                    found_account_number = setting.account_number
                    first_matching_alias = setting.account_name_alias

        if found_account_number:
            # If a match is found, return the full account number for both elements of the tuple.
            return found_account_number, found_account_number
        else:
            return None, f"...{depot_short_id}"

def _resolve_security_depot_display_name(
    depot_short_id: str, account_settings_list: List[SchwabAccountSettings]
) -> str:
    """Schwab-specific depot display name for the eCH-0196 ``DepotNumber``.

    * ``AWARDS`` stays verbatim — it is a synthetic depot name for stock-plan
      activity and predates settings-based resolution.
    * Otherwise the first settings row whose ``account_number`` ends with the
      short depot id supplies the full account number; an unmatched depot
      falls back to ``"...<short_id>"``.
    """
    if depot_short_id == "AWARDS":
        return "AWARDS"
    _, display = _get_configured_account_info(
        depot_short_id, account_settings_list, False
    )
    return display


def _resolve_cash_account_identity(
    pos: CashPosition, account_settings_list: List[SchwabAccountSettings]
) -> Tuple[str, Optional[str]]:
    """Produce ``(bankAccountName, bankAccountNumber)`` for a Schwab cash bucket.

    Mirrors the legacy ``convert_cash_positions_to_list_of_bank_accounts``:
    awards cash becomes ``"Equity Awards <cash_account_id>"`` with no number,
    configured cash uses the full account number for both fields, and
    unmatched cash gets a currency-prefixed fallback. Unsettled cash appends
    the ``" (Unsettled)"`` marker, truncating the base name so the final
    string fits within the 40-char eCH limit.
    """
    is_awards = pos.depot == "AWARDS"
    lookup_id = pos.cash_account_id if is_awards else pos.depot
    if is_awards and lookup_id is None:
        logger.warning(
            "Awards depot for %s has a None cash_account_id; using 'UNKNOWN'.",
            pos.depot,
        )
        lookup_id = "UNKNOWN"
    lookup_id = lookup_id or "UNKNOWN"

    config_acc_num, display_id = _get_configured_account_info(
        lookup_id, account_settings_list, is_awards
    )

    if is_awards:
        base_name = display_id
    elif config_acc_num is not None:
        base_name = display_id
    else:
        base_name = f"{pos.currentCy} Account {display_id}"

    if pos.is_unsettled_balance:
        suffix = " (Unsettled)"
        base_name = base_name[: 40 - len(suffix)] + suffix

    name = base_name[:40]
    number = config_acc_num[:32] if config_acc_num else None
    return name, number


def _pick_primary_client_number(
    account_settings_list: List[SchwabAccountSettings],
) -> Optional[str]:
    """Return the ``account_number`` that should drive ``TaxStatement.client``.

    Schwab's "awards" depot (stock-plan activity) is reported as a separate
    account but is never used for tax-statement client identification.  We
    pick the first settings row whose ``account_name_alias`` is not, case
    insensitively, ``"awards"``.  If every row is flagged as awards we
    return ``None`` and the caller leaves ``TaxStatement.client`` empty.
    """
    for setting in account_settings_list:
        alias = setting.account_name_alias
        if alias and alias.lower() != "awards":
            return setting.account_number
    return None


def _schwab_security_display_name(pos: SecurityPosition) -> Optional[str]:
    """Schwab's OpenPosition-priority display name for the name registry.

    Returns ``"<description> (<symbol>)"`` when both are available, or just
    the symbol when the description is missing, matching the legacy
    convert-to-ListOfSecurities behaviour.  Returns ``None`` when neither
    is present, in which case the caller should skip the name-registry
    update so the shared postprocess falls back to ``pos.description`` /
    ``pos.symbol`` on its own.
    """
    if pos.description:
        return f"{pos.description} ({pos.symbol})"
    if pos.symbol:
        return pos.symbol
    return None


def is_date_in_valid_transaction_range(date_to_check: date, transaction_range: Tuple[date, date]) -> bool:
    """
    Checks if a date is within a given transaction range (inclusive) 
    or if it's the day immediately following the end of that range.
    """
    transaction_range_start, transaction_range_end = transaction_range
    return (transaction_range_start <= date_to_check <= transaction_range_end) or \
           (date_to_check == transaction_range_end + timedelta(days=1))

class SchwabImporter:
    """
    Imports Schwab account data for a given tax period from PDF and JSON files.
    """
    def __init__(self, 
                 period_from: date, 
                 period_to: date, 
                 account_settings_list: List[SchwabAccountSettings], # MODIFIED
                 strict_consistency: bool = True,
                 render_language: Language = DEFAULT_LANGUAGE):
        """
        Initialize the importer with a tax period defined by a start and end date.

        Args:
            period_from (date): The start date of the tax period.
            period_to (date): The end date of the tax period.
            strict_consistency (bool): If True, raises an error on position reconciliation
                                       inconsistencies. If False, logs a warning.
            render_language (Language): Language for translations.
        """
        self.period_from = period_from
        self.period_to = period_to
        self.account_settings_list = account_settings_list # MODIFIED
        self.strict_consistency = strict_consistency
        self.render_language = render_language

        # If there's any immediate use of a single account setting (e.g. for logging, or a default identifier)
        # it needs to be adapted. For now, we'll assume most logic will be adapted later.
        # If absolutely needed for the code to run, use the first account with a TODO.
        if self.account_settings_list:
            logger.info(f"SchwabImporter initialized with {len(self.account_settings_list)} account(s). First account number: {self.account_settings_list[0].account_number}")
        else:
            # This case should ideally be prevented by the CLI loading logic
            logger.warning("SchwabImporter initialized with an empty list of account settings.")

    def import_files(self, filenames: List[str]) -> TaxStatement:
        """
        Import data from a list of filenames (PDF or JSON) and return a TaxStatement.

        Args:
            filenames (List[str]): List of file paths to import (PDF or JSON).

        Returns:
            TaxStatement: The imported tax statement.
        """
        # Track known position dates for each depot
        depot_position_dates = {}
        # Track covered date ranges for each depot (using DateRangeCoverage)
        depot_coverage = {}
        # Collect all positions for common post-processing
        all_positions = []  # (Position, SecurityStock, Optional[List[SecurityPayment]])

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext == ".pdf":
                extractor = StatementExtractor(filename)
                result = extractor.extract_positions()
                if result is not None:
                    positions, open_date, close_date_plus1, depot = result
                    if depot not in depot_position_dates:
                        depot_position_dates[depot] = set()
                    depot_position_dates[depot].add(open_date)
                    depot_position_dates[depot].add(close_date_plus1)
                    # print(f"Extracted positions from {filename}: {positions}")
                    for pos, stock in positions:
                        all_positions.append((pos, stock, None))
            elif ext == ".json":
                extractor = TransactionExtractor(filename, self.render_language)
                transactions = extractor.extract_transactions()
                if transactions is not None:
                    newly_covered_segments = defaultdict(list)
                    # TODO this loops partly sill as the coverage is the same for all transactions
                    for _, _, _, depot, (start_date, end_date) in transactions:
                        if depot in newly_covered_segments:
                            continue
                        if depot not in depot_coverage:
                            depot_coverage[depot] = DateRangeCoverage()
                        
                        # Determine newly covered segments for this transaction's date range.
                        # This simulation of get_uncovered_sub_ranges_within is to avoid altering DateRangeCoverage
                        # in this step. A direct method on DateRangeCoverage would be cleaner.
                        temp_coverage_for_new_segments = DateRangeCoverage()
                        if depot_coverage[depot].covered: # Check if there are existing covered ranges
                            temp_coverage_for_new_segments.covered = [r for r in depot_coverage[depot].covered] # Clone current coverage
                        
                        potential_new_segments = []
                        current_check_date = start_date
                        while current_check_date <= end_date:
                            # Check if the current single day is covered by the *original* depot coverage
                            if not temp_coverage_for_new_segments.is_covered(current_check_date, current_check_date):
                                seg_start = current_check_date
                                seg_end = seg_start
                                # Extend the segment as long as it's within the transaction and uncovered by original coverage
                                while seg_end < end_date and \
                                      not temp_coverage_for_new_segments.is_covered(seg_end + timedelta(days=1), seg_end + timedelta(days=1)):
                                    seg_end += timedelta(days=1)
                                potential_new_segments.append((seg_start, seg_end))
                                current_check_date = seg_end + timedelta(days=1)
                            else:
                                current_check_date += timedelta(days=1)
                        newly_covered_segments[depot] = potential_new_segments

                        print(f"Newly covered segments({depot}): {newly_covered_segments}")
                        
                        # Now, mark the entire transaction range as covered in the main tracker for future transactions
                        depot_coverage[depot].mark_covered(start_date, end_date)

                    for position, stocks, payments, depot, (start_date, end_date) in transactions:
                        filtered_stocks = []
                        if stocks:
                            for stock_item in stocks:
                                # Corrected attribute: referenceDate instead of balanceDate
                                if stock_item.referenceDate is not None and \
                                   any(seg_start <= stock_item.referenceDate <= seg_end \
                                       for seg_start, seg_end in newly_covered_segments[depot]):
                                    filtered_stocks.append(stock_item)
                        
                        filtered_payments = []
                        if payments:
                            for payment_item in payments:
                                if payment_item.paymentDate is not None and \
                                   any(seg_start <= payment_item.paymentDate <= seg_end \
                                       for seg_start, seg_end in newly_covered_segments[depot]):
                                    filtered_payments.append(payment_item)
                        
                        if filtered_stocks:
                            for i, stock_item in enumerate(filtered_stocks):
                                payments_for_this_entry = None
                                if i == 0 and filtered_payments:
                                    payments_for_this_entry = filtered_payments
                                all_positions.append((position, stock_item, payments_for_this_entry))
                        elif filtered_payments:
                            all_positions.append((position, None, filtered_payments))
                            
                    # print(f"Extracted transactions from {filename}: {transactions}")
            elif ext == ".csv":
                # Try primary PositionExtractor first
                primary_extractor = PositionExtractor(filename)
                primary_positions_data = primary_extractor.extract_positions()

                if primary_positions_data is not None:
                    positions, statement_date, depot = primary_positions_data
                    if depot not in depot_position_dates:
                        depot_position_dates[depot] = set()
                    depot_position_dates[depot].add(statement_date)
                    # print(f"Extracted positions from {filename}: {positions}")
                    for pos, stock in positions:
                        all_positions.append((pos, stock, None))
                else:
                    # If primary fails, try FallbackPositionExtractor
                    print(f"Primary PositionExtractor failed for {filename}. Trying FallbackPositionExtractor.")
                    fallback_extractor = FallbackPositionExtractor(filename)
                    fallback_positions_data = fallback_extractor.extract_positions() # Now List[Tuple[Position, SecurityStock]]

                    if fallback_positions_data is not None:
                        for pos, stock in fallback_positions_data:
                            item_depot = pos.depot
                            item_date = stock.referenceDate # Assuming SecurityStock always has referenceDate
                            if item_depot not in depot_position_dates:
                                depot_position_dates[item_depot] = set()
                            depot_position_dates[item_depot].add(item_date) # Add the date from the stock item
                            all_positions.append((pos, stock, None)) # Add to the common list
                    else:
                        print(f"Skipped file (not a recognized Schwab positions CSV by primary or fallback): {filename}")
            else:
                # Optionally log or raise for unsupported file types
                pass
        
        # Print known position dates per depot for demonstration
        for depot, dates in depot_position_dates.items():
            print(f"Depot {depot} has known position dates: {sorted(dates)}")
        # Print covered date ranges per depot for demonstration
        for depot, coverage in depot_coverage.items():
            print(f"Depot {depot} has covered date ranges: {coverage.covered}")

        max_ranges = dict()
        # --- Tax period coverage and statement date check ---
        for depot, coverage in depot_coverage.items():
            # Check if the tax period is fully covered
            if not coverage.is_covered(self.period_from, self.period_to):
                raise ValueError(f"Depot {depot}: Tax period {self.period_from} to {self.period_to} is not fully covered by available data.\nSuggestion: Download and import statements covering this range for depot '{depot}'.")
            # Find the maximal covered range containing the tax period start
            max_range = coverage.maximal_covered_range_containing(self.period_from)
            if not max_range:
                raise ValueError(f"Depot {depot}: No covered range contains the tax period start {self.period_from}.\nSuggestion: Download and import statements covering this date for depot '{depot}'.")
            max_ranges[depot] = max_range
            # Check that at least one statement date is in this range
            statement_dates = depot_position_dates.get(depot, set())
            # Accept a statement date in the range OR exactly one day after the range end
            if not any(is_date_in_valid_transaction_range(d, max_range) for d in statement_dates):
                raise ValueError(f"Depot {depot}: No statement date in the maximal covered range {max_range} (or the day after) for the tax period.\nSuggestion: Download and import a statement with a statement date within {max_range} or the day after for depot '{depot}'.")
        # --- End coverage check ---
            
        # Post-process: aggregate stocks/payments per unique Position
        position_map = defaultdict(lambda: ([], []))  # Position -> (list of SecurityStock, list of SecurityPayment)
        
        for pos, stock, payments in all_positions:
            if stock:
                if not is_date_in_valid_transaction_range(stock.referenceDate, max_ranges[pos.depot]):
                    print(f"WARNING: Skipping stock {stock} for position {pos} because its referenceDate {stock.referenceDate} is not in the valid transaction range {max_ranges[pos.depot]}.")
                    continue
            
            if not stock and payments:
                # Filter payments by valid transaction range if they are not associated with a stock
                valid_payments = []
                for p in payments:
                    if is_date_in_valid_transaction_range(p.paymentDate, max_ranges[pos.depot]):
                        valid_payments.append(p)
                    else:
                        print(f"WARNING: Skipping payment {p} for position {pos} because its paymentDate {p.paymentDate} is not in the valid transaction range {max_ranges[pos.depot]}.")
                payments = valid_payments
                if not payments:
                    continue

            # Ensure pos is a known type before using it as a key
            if not isinstance(pos, (SecurityPosition, CashPosition)):
                raise TypeError(f"Unknown position type: {type(pos)}")

            current_stocks, current_payments = position_map[pos]
            if stock:
                current_stocks.append(stock)
            if payments: # payments can be a list or a single item
                if isinstance(payments, list):
                    current_payments.extend(payments)
                else:
                    current_payments.append(payments)

        tax_year = self.period_from.year

        # --- Split the aggregator into the shared accumulator shapes and
        # rewrite Schwab-specific display names so the shared postprocess can
        # operate directly on SecurityPosition.depot / CashAccountEntry.* ---
        processed_security_positions: Dict[SecurityPosition, SecurityPositionData] = {}
        name_registry = SecurityNameRegistry()
        cash_entries: List[CashAccountEntry] = []

        for pos_obj, (initial_stocks, associated_payments) in position_map.items():
            if isinstance(pos_obj, SecurityPosition):
                display_depot = _resolve_security_depot_display_name(
                    pos_obj.depot, self.account_settings_list
                )
                rekeyed = pos_obj.model_copy(update={"depot": display_depot})
                processed_security_positions[rekeyed] = SecurityPositionData(
                    stocks=list(initial_stocks),
                    payments=list(associated_payments),
                )
                display_name = _schwab_security_display_name(pos_obj)
                if display_name is not None:
                    name_registry.update(rekeyed, display_name, 10)
            elif isinstance(pos_obj, CashPosition):
                # Cash needs its own reconciliation to derive the closing
                # balance that augment_list_of_bank_accounts expects on the
                # CashAccountEntry. Split settled vs unsettled first.
                settled_stocks, unsettled_stocks = split_unsettled_cash(
                    initial_stocks, self.period_to
                )
                settled_entry = self._build_settled_cash_entry(
                    pos_obj, settled_stocks, associated_payments
                )
                if settled_entry is not None:
                    cash_entries.append(settled_entry)

                if unsettled_stocks:
                    total_unsettled = sum(
                        (s.quantity for s in unsettled_stocks), Decimal("0")
                    )
                    if total_unsettled != Decimal("0"):
                        logger.info(
                            f"[{pos_obj.get_processing_identifier()}] {len(unsettled_stocks)} "
                            f"unsettled trade(s) at period end {self.period_to} "
                            f"(net {total_unsettled}); will be reported as a separate account."
                        )
                        cash_entries.append(
                            self._build_unsettled_cash_entry(
                                pos_obj, unsettled_stocks, total_unsettled
                            )
                        )
            else:
                logger.warning(
                    "Ignoring unknown position type after aggregation: %s",
                    type(pos_obj),
                )

        # --- Partial TaxStatement, then delegate to the shared post-processing ---
        tax_statement = TaxStatement(
            minorVersion=1,
            periodFrom=self.period_from,
            periodTo=self.period_to,
            taxPeriod=tax_year,
            institution=Institution(name="Charles Schwab"),
        )

        primary_client_number = _pick_primary_client_number(
            self.account_settings_list
        )
        if primary_client_number is not None:
            tax_statement.client = [
                Client(clientNumber=ClientNumber(primary_client_number))
            ]

        augment_list_of_securities(
            tax_statement,
            processed_security_positions,
            name_registry=name_registry,
            hints_for=lambda _sp: PositionHints(
                security_category="SHARE",
                country="US",
                # Schwab historically never raised on negative balances; keep
                # that contract to avoid regressing on edge cases.
                allow_negative_opening=True,
                allow_negative_balance=True,
            ),
            strict_consistency=self.strict_consistency,
            run_initial_consistency_check=True,
            # Mutation-only symbols (e.g. awards that never appear on a
            # position snapshot) must be reconciled by walking mutations
            # from an implicit zero; otherwise their net closing balance
            # would be dropped to 0.
            assume_zero_if_no_balances=True,
            # Schwab extractors emit one row per real event (a vesting
            # grant, a transfer, a sale) whose ``name`` carries unique
            # per-event text (grant date, wash-sale note, ...). Merging
            # same-day rows would silently drop that information.
            aggregate_same_day_mutations=False,
        )
        augment_list_of_bank_accounts(tax_statement, cash_entries)
        return tax_statement

    # ------------------------------------------------------------------
    # CashAccountEntry builders (Schwab-specific naming lives here)
    # ------------------------------------------------------------------

    def _build_settled_cash_entry(
        self,
        pos_obj: CashPosition,
        settled_stocks: List[SecurityStock],
        payments: List[SecurityPayment],
    ) -> Optional[CashAccountEntry]:
        """Reconcile *settled_stocks* and wrap the result in a CashAccountEntry.

        Returns ``None`` when the caller provided nothing at all — avoids
        emitting an empty bank account for a currency we have no data for.
        """
        if not settled_stocks and not payments:
            return None

        # Initial consistency check preserved from the legacy helper.
        identifier = pos_obj.get_processing_identifier()
        initial = PositionReconciler(
            list(settled_stocks), identifier=f"{identifier}-initial_check"
        )
        is_consistent, _ = initial.check_consistency(
            print_log=True,
            raise_on_error=self.strict_consistency,
            assume_zero_if_no_balances=True,
        )
        if not is_consistent and not self.strict_consistency:
            logger.warning(
                f"[{identifier}] Initial consistency check on raw cash data failed. "
                "Review logs. Proceeding with synthesis.",
            )

        end_plus_one = self.period_to + timedelta(days=1)
        reconciler = PositionReconciler(
            list(settled_stocks), identifier=f"{identifier}-end_synth"
        )
        end_pos = reconciler.synthesize_position_at_date(
            end_plus_one, assume_zero_if_no_balances=True
        )
        closing_balance = end_pos.quantity if end_pos else Decimal("0")
        currency = pos_obj.currentCy or "USD"

        bank_payments = [
            BankAccountPayment(
                paymentDate=p.paymentDate,
                name=p.name,
                amountCurrency=p.amountCurrency,
                amount=p.amount,
            )
            for p in (payments or [])
        ]

        name, number = _resolve_cash_account_identity(
            pos_obj, self.account_settings_list
        )
        return CashAccountEntry(
            account_id=name,
            currency=currency,
            closing_balance=closing_balance,
            payments=bank_payments,
            name=name,
            number=number,
        )

    def _build_unsettled_cash_entry(
        self,
        pos_obj: CashPosition,
        unsettled_stocks: List[SecurityStock],
        total_unsettled: Decimal,
    ) -> CashAccountEntry:
        currency = (
            unsettled_stocks[0].balanceCurrency
            if unsettled_stocks
            else (pos_obj.currentCy or "USD")
        )
        # A synthetic CashPosition flagged as unsettled drives the " (Unsettled)"
        # name suffix below, matching the legacy behaviour.
        marker = pos_obj.model_copy(update={"is_unsettled_balance": True})
        name, number = _resolve_cash_account_identity(
            marker, self.account_settings_list
        )
        return CashAccountEntry(
            account_id=name,
            currency=currency,
            closing_balance=total_unsettled,
            payments=[],
            name=name,
            number=number,
        )

    def import_dir(self, directory: str) -> TaxStatement:
        """
        Import all PDF and JSON files in the given directory and return a TaxStatement.

        Args:
            directory (str): Path to the directory containing files to import.

        Returns:
            TaxStatement: The imported tax statement.
        """
        files = []
        for fname in os.listdir(directory):
            if fname.lower().endswith('.pdf') or fname.lower().endswith('.json'):
                files.append(os.path.join(directory, fname))
            elif fname.lower().endswith('.csv'):
                files.append(os.path.join(directory, fname))
        return self.import_files(files)

if __name__ == "__main__":
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser(description="Run SchwabImporter on a directory of files.")
    parser.add_argument("directory", type=str, help="Directory containing PDF and JSON files")
    parser.add_argument("period_from", type=str, help="Start date of tax period (YYYY-MM-DD)")
    parser.add_argument("period_to", type=str, help="End date of tax period (YYYY-MM-DD)")
    args = parser.parse_args()

    # Parse dates
    period_from = datetime.strptime(args.period_from, "%Y-%m-%d").date()
    period_to = datetime.strptime(args.period_to, "%Y-%m-%d").date()

    importer = SchwabImporter(period_from, period_to, [])
    tax_statement = importer.import_dir(args.directory)
       
    from devtools import debug  
    debug(tax_statement)
