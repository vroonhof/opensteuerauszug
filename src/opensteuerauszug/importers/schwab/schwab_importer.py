import pprint
from typing import List, Dict, Any, Optional, Tuple
import os
from decimal import Decimal
from opensteuerauszug.model.ech0196 import (
    ListOfSecurities, ListOfBankAccounts, TaxStatement, Depot, Security, BankAccount, BankAccountPayment, SecurityStock, SecurityPayment, DepotNumber, BankAccountNumber, CurrencyId, QuotationType, BankAccountTaxValue
)
from opensteuerauszug.model.position import BasePosition, SecurityPosition, CashPosition, Position
from .statement_extractor import StatementExtractor
from datetime import date, timedelta
from .fallback_position_extractor import FallbackPositionExtractor
from .position_extractor import PositionExtractor
from .transaction_extractor import TransactionExtractor
from opensteuerauszug.util.date_coverage import DateRangeCoverage
from collections import defaultdict
from opensteuerauszug.core.position_reconciler import PositionReconciler, ReconciledQuantity
from ....config.models import SchwabAccountSettings # Add this

# Placeholder import for TransactionExtractor (to be implemented)
# from .TransactionExtractor import TransactionExtractor

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
                 strict_consistency: bool = True):
        """
        Initialize the importer with a tax period defined by a start and end date.

        Args:
            period_from (date): The start date of the tax period.
            period_to (date): The end date of the tax period.
            strict_consistency (bool): If True, raises an error on position reconciliation
                                       inconsistencies. If False, logs a warning.
        """
        self.period_from = period_from
        self.period_to = period_to
        self.account_settings_list = account_settings_list # MODIFIED
        self.strict_consistency = strict_consistency

        # If there's any immediate use of a single account setting (e.g. for logging, or a default identifier)
        # it needs to be adapted. For now, we'll assume most logic will be adapted later.
        # If absolutely needed for the code to run, use the first account with a TODO.
        if self.account_settings_list:
            print(f"SchwabImporter initialized with {len(self.account_settings_list)} account(s). First account number: {self.account_settings_list[0].account_number}")
        else:
            # This case should ideally be prevented by the CLI loading logic
            print("Warning: SchwabImporter initialized with an empty list of account settings.")

    def _determine_synthesized_stock_currency(
        self,
        pos_obj: BasePosition,
        live_stocks_list: List[SecurityStock],
        synthesized_value_currency: Optional[str]
    ) -> str:
        if synthesized_value_currency:
            return synthesized_value_currency

        if isinstance(pos_obj, SecurityPosition):
            if live_stocks_list and hasattr(live_stocks_list[0], 'balanceCurrency') and live_stocks_list[0].balanceCurrency:
                return live_stocks_list[0].balanceCurrency
            return "USD"  # Default for securities if no live stocks or first stock has no currency
        elif isinstance(pos_obj, CashPosition):
            return pos_obj.currentCy if pos_obj.currentCy else "USD"
        return "USD"  # Ultimate fallback

    def _reconcile_and_ensure_boundary_stocks_for_position(
        self,
        pos_obj: BasePosition,
        initial_pos_stocks: List[SecurityStock],
        associated_pos_payments: List[SecurityPayment]
    ) -> Tuple[BasePosition, List[SecurityStock], List[SecurityPayment]]:

        current_identifier = pos_obj.get_processing_identifier()
        balance_name_prefix = pos_obj.get_balance_name_prefix()

        # 1. Initial Consistency Check
        initial_reconciler = PositionReconciler(list(initial_pos_stocks), identifier=f"{current_identifier}-initial_check")
        is_consistent_initial, _ = initial_reconciler.check_consistency(
            print_log=True,
            raise_on_error=self.strict_consistency
        )
        if not is_consistent_initial and not self.strict_consistency:
            print(f"WARNING: [{current_identifier}] Initial consistency check on raw data failed. Review logs. Proceeding with synthesis.")

        live_stocks_list = list(initial_pos_stocks) # Use a distinct name for the list being modified

        # 2. Ensure start-of-period balance
        reconciler_for_start = PositionReconciler(list(live_stocks_list), identifier=f"{current_identifier}-start_synth")
        start_pos_synth = reconciler_for_start.synthesize_position_at_date(self.period_from)
        has_start_balance = any(not s.mutation and s.referenceDate == self.period_from for s in live_stocks_list)

        if not has_start_balance:
            qty_to_set_at_start = Decimal('0')
            currency_at_start = self._determine_synthesized_stock_currency(
                pos_obj, live_stocks_list, start_pos_synth.currency if start_pos_synth else None
            )
            q_type_at_start = live_stocks_list[0].quotationType if live_stocks_list else "PIECE"

            if start_pos_synth:
                qty_to_set_at_start = start_pos_synth.quantity
                print(f"[{current_identifier}] Synthesized start position for {self.period_from}: Qty {qty_to_set_at_start} {currency_at_start}")
            else:
                earliest_stock_date = min(s.referenceDate for s in live_stocks_list) if live_stocks_list else None
                if not earliest_stock_date or earliest_stock_date > self.period_from or \
                   (earliest_stock_date == self.period_from and live_stocks_list[0].mutation):
                    print(f"[{current_identifier}] No suitable existing/synthesizable start balance for {self.period_from}. Inserting zero balance.")

            start_balance_stock = SecurityStock(
                referenceDate=self.period_from,
                mutation=False,
                quantity=qty_to_set_at_start,
                balanceCurrency=currency_at_start,
                quotationType=q_type_at_start,
                name=f"{balance_name_prefix}Opening Balance (Tax Period Start)".strip()
            )
            live_stocks_list.append(start_balance_stock)
            live_stocks_list = sorted(live_stocks_list, key=lambda s: (s.referenceDate, s.mutation))
            print(f"[{current_identifier}] Added/updated start-of-period balance for {self.period_from}.")

        # 3. Ensure end-of-period balance
        effective_period_end_date = self.period_to + timedelta(days=1)
        reconciler_for_end = PositionReconciler(list(live_stocks_list), identifier=f"{current_identifier}-end_synth")
        end_pos_synth = reconciler_for_end.synthesize_position_at_date(effective_period_end_date)
        has_end_balance = any(not s.mutation and s.referenceDate == effective_period_end_date for s in live_stocks_list)

        if not has_end_balance and end_pos_synth:
            currency_at_end = self._determine_synthesized_stock_currency(
                pos_obj, live_stocks_list, end_pos_synth.currency if end_pos_synth else None
            )
            q_type_at_end = live_stocks_list[0].quotationType if live_stocks_list else "PIECE"

            print(f"[{current_identifier}] Synthesized end position for {effective_period_end_date}: Qty {end_pos_synth.quantity} {currency_at_end}")
            end_balance_stock = SecurityStock(
                referenceDate=effective_period_end_date,
                mutation=False,
                quantity=end_pos_synth.quantity,
                balanceCurrency=currency_at_end,
                quotationType=q_type_at_end,
                name=f"{balance_name_prefix}Closing Balance (Tax Period End+1)".strip()
            )
            live_stocks_list.append(end_balance_stock)
            live_stocks_list = sorted(live_stocks_list, key=lambda s: (s.referenceDate, s.mutation))
            print(f"[{current_identifier}] Added end-of-period balance for {effective_period_end_date}.")
        elif not has_end_balance and not end_pos_synth:
            print(f"[{current_identifier}] Could not synthesize end-of-period balance for {effective_period_end_date}. It might be missing.")

        return pos_obj, live_stocks_list, associated_pos_payments

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
                extractor = TransactionExtractor(filename)
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
                                if i == 0 and filtered_payments: \
                                    payments_for_this_entry = filtered_payments
                                all_positions.append((position, stock_item, payments_for_this_entry))
                        elif filtered_payments: \
                            print(f"WARNING: Transaction for {position} from {filename} (period {start_date}-{end_date}) has {len(filtered_payments)} filtered_payments for newly covered segments {newly_covered_segments} but no corresponding filtered_stocks. These payments will not be added to all_positions.")
                            
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
            if not is_date_in_valid_transaction_range(stock.referenceDate, max_ranges[pos.depot]):
                print(f"WARNING: Skipping stock {stock} for position {pos} because its referenceDate {stock.referenceDate} is not in the valid transaction range {max_ranges[pos.depot]}.")
                continue
            
            # Ensure pos is a known type before using it as a key
            if not isinstance(pos, (SecurityPosition, CashPosition)):
                raise TypeError(f"Unknown position type: {type(pos)}")

            current_stocks, current_payments = position_map[pos]
            current_stocks.append(stock)
            if payments: # payments can be a list or a single item
                if isinstance(payments, list):
                    current_payments.extend(payments)
                else:
                    current_payments.append(payments)

        tax_year = self.period_from.year
        
        # --- Reconcile and ensure period boundary stock records --- 
        all_processed_tuples = []
        for pos_obj, (initial_stocks, associated_payments) in position_map.items():
            processed_tuple = self._reconcile_and_ensure_boundary_stocks_for_position(
                pos_obj, initial_stocks, associated_payments
            )
            all_processed_tuples.append(processed_tuple)

        # Now, filter the processed tuples into security and cash lists
        final_security_tuples = []
        final_cash_tuples = []
        for pos_obj, stocks, payments in all_processed_tuples:
            if isinstance(pos_obj, SecurityPosition):
                final_security_tuples.append((pos_obj, stocks, payments))
            elif isinstance(pos_obj, CashPosition):
                final_cash_tuples.append((pos_obj, stocks, payments))
            else:
                # This case should ideally not be reached if input `all_positions` was validated
                print(f"WARNING: Unknown position type encountered after reconciliation: {type(pos_obj)}")

        return create_tax_statement_from_positions(
            final_security_tuples,
            final_cash_tuples,
            period_from=self.period_from,
            period_to=self.period_to,
            tax_period=tax_year
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

def convert_security_positions_to_list_of_securities(
    security_tuples: list[tuple[SecurityPosition, list[SecurityStock], list[SecurityPayment] | None]]
) -> ListOfSecurities:
    """
    Convert a list of (SecurityPosition, List[SecurityStock], Optional[List[SecurityPayment]]) tuples
    into a ListOfSecurities object. Minimal stub: one depot, one security per position.
    """
    depots: Dict[str, Depot] = {}
    for pos, stocks, payments in security_tuples:
        depot_number = pos.depot
        if depot_number not in depots:
            depots[depot_number] = Depot(depotNumber=DepotNumber(depot_number), security=[])
        # Use the first stock for required attributes, but include all stocks in the list
        
        # Determine security name based on description and symbol
        security_name: str
        if pos.description:
            security_name = f"{pos.description} ({pos.symbol})"
        else:
            security_name = pos.symbol
            
        first_stock = stocks[0]
        sec = Security(
            positionId=1,  # In real code, ensure unique per security
            country="US",  # Stub
            currency=first_stock.balanceCurrency,
            quotationType=first_stock.quotationType,
            securityCategory="SHARE",  # Stub
            securityName=security_name,
            stock=stocks,
            payment=payments or []
        )
        depots[depot_number].security.append(sec)
    return ListOfSecurities(depot=list(depots.values()))

def convert_cash_positions_to_list_of_bank_accounts(
    cash_tuples: list[tuple[CashPosition, list[SecurityStock], list[SecurityPayment] | None]],
    period_to: date
) -> ListOfBankAccounts:
    """
    Convert a list of (CashPosition, List[SecurityStock], Optional[List[SecurityPayment]]) tuples into a ListOfBankAccounts object.
    """
    accounts: List[BankAccount] = []
    for pos, stocks, payments in cash_tuples:
        depot_number = pos.depot
        currency = "USD" # Fallback if no stock items
        if stocks:
            currency = stocks[0].balanceCurrency
        else:
            print(f"Warning: CashPosition in depot {depot_number} has no stock items. Using default currency.")

        if pos.depot == 'AWARDS':
            # Special case for awards depot
            account_number = f"Equity Awards {pos.cash_account_id}"
        else:
            account_number = f"{pos.currentCy} Account ...{depot_number}"

        bank_payments = [BankAccountPayment(
            paymentDate=payment.paymentDate,
            name=payment.name,
            amountCurrency=payment.amountCurrency,
            amount=payment.amount,
        ) for payment in payments] if payments else []
            
        bank_account = BankAccount(
                bankAccountNumber=BankAccountNumber(account_number),
                bankAccountCountry="US", # Assume Schwab is always US based
                bankAccountCurrency=currency,
                payment=bank_payments
        )

        # Find the closing balance stock for the period_to date
        # The reconciliation ensures a stock exists for period_to + 1 day (start of next day)
        closing_stock_date = period_to + timedelta(days=1)
        closing_stock_entry = None
        if stocks:
            for stock_item in stocks:
                if stock_item.referenceDate == closing_stock_date and not stock_item.mutation:
                    closing_stock_entry = stock_item
                    break
        
        if closing_stock_entry:
            bank_account.taxValue = BankAccountTaxValue(
                referenceDate=period_to, # Tax value is as of end of period_to
                name="Closing Balance",
                balanceCurrency=closing_stock_entry.balanceCurrency,
                balance=closing_stock_entry.quantity # Quantity of cash is its balance
            )
        accounts.append(bank_account)
    return ListOfBankAccounts(bankAccount=accounts)

def create_tax_statement_from_positions(
    security_tuples: list[tuple[SecurityPosition, list[SecurityStock], list[SecurityPayment] | None]],
    cash_tuples: list[tuple[CashPosition, list[SecurityStock], list[SecurityPayment] | None]],
    period_from: date,
    period_to: date,
    tax_period: int
) -> TaxStatement:
    """
    Create a TaxStatement from security and cash tuples.
    """
    list_of_securities = convert_security_positions_to_list_of_securities(security_tuples)
    list_of_bank_accounts = convert_cash_positions_to_list_of_bank_accounts(cash_tuples, period_to)
    return TaxStatement(
        minorVersion=1,
        periodFrom=period_from,
        periodTo=period_to,
        taxPeriod=tax_period,
        listOfSecurities=list_of_securities,
        listOfBankAccounts=list_of_bank_accounts
    )

if __name__ == "__main__":
    import sys
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

    importer = SchwabImporter(period_from, period_to)
    tax_statement = importer.import_dir(args.directory)
       
    from devtools import debug  
    debug(tax_statement)
