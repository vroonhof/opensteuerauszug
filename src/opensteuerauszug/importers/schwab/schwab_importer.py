import pprint
from typing import List, Dict, Any, Tuple
import os
from decimal import Decimal
from opensteuerauszug.model.ech0196 import (
    ListOfSecurities, ListOfBankAccounts, TaxStatement, Depot, Security, BankAccount, SecurityStock, SecurityPayment, DepotNumber, BankAccountNumber, CurrencyId, QuotationType
)
from opensteuerauszug.model.position import SecurityPosition, CashPosition, Position
from .statement_extractor import StatementExtractor
from datetime import date, timedelta
from .position_extractor import PositionExtractor
from .transaction_extractor import TransactionExtractor
from opensteuerauszug.util.date_coverage import DateRangeCoverage
from collections import defaultdict
from opensteuerauszug.core.position_reconciler import PositionReconciler, ReconciledQuantity

# Placeholder import for TransactionExtractor (to be implemented)
# from .TransactionExtractor import TransactionExtractor

class SchwabImporter:
    """
    Imports Schwab account data for a given tax period from PDF and JSON files.
    """
    def __init__(self, period_from: date, period_to: date, strict_consistency: bool = True):
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
        self.strict_consistency = strict_consistency

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
                    print(f"Extracted positions from {filename}: {positions}")
                    for pos, stock in positions:
                        all_positions.append((pos, stock, None))
                # TODO: Use extracted data to populate TaxStatement
            elif ext == ".json":
                extractor = TransactionExtractor(filename)
                transactions = extractor.extract_transactions()
                if transactions is not None:
                    for position, stocks, payments, depot, (start_date, end_date) in transactions:
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
                        newly_covered_segments = potential_new_segments
                        
                        # Now, mark the entire transaction range as covered in the main tracker for future transactions
                        depot_coverage[depot].mark_covered(start_date, end_date)

                        filtered_stocks = []
                        if stocks:
                            for stock_item in stocks:
                                # Corrected attribute: referenceDate instead of balanceDate
                                if stock_item.referenceDate is not None and \
                                   any(seg_start <= stock_item.referenceDate <= seg_end \
                                       for seg_start, seg_end in newly_covered_segments):
                                    filtered_stocks.append(stock_item)
                        
                        filtered_payments = []
                        if payments:
                            for payment_item in payments:
                                if payment_item.paymentDate is not None and \
                                   any(seg_start <= payment_item.paymentDate <= seg_end \
                                       for seg_start, seg_end in newly_covered_segments):
                                    filtered_payments.append(payment_item)
                        
                        if filtered_stocks:
                            for i, stock_item in enumerate(filtered_stocks):
                                payments_for_this_entry = None
                                if i == 0 and filtered_payments: \
                                    payments_for_this_entry = filtered_payments
                                all_positions.append((position, stock_item, payments_for_this_entry))
                        elif filtered_payments: \
                            print(f"WARNING: Transaction for {position} from {filename} (period {start_date}-{end_date}) has {len(filtered_payments)} filtered_payments for newly covered segments {newly_covered_segments} but no corresponding filtered_stocks. These payments will not be added to all_positions.")
                            
                    print(f"Extracted transactions from {filename}: {transactions}")
                # TODO: Use extracted data to populate TaxStatement
            elif ext == ".csv":
                extractor = PositionExtractor(filename)
                positions_data = extractor.extract_positions()
                if positions_data is not None:
                    positions, statement_date, depot = positions_data
                    if depot not in depot_position_dates:
                        depot_position_dates[depot] = set()
                    depot_position_dates[depot].add(statement_date)
                    print(f"Extracted positions from {filename}: {positions}")
                    for pos, stock in positions:
                        all_positions.append((pos, stock, None))
                    # TODO: Integrate positions_data into TaxStatement
                else:
                    print(f"Skipped file (not a Schwab positions CSV): {filename}")
            else:
                # Optionally log or raise for unsupported file types
                pass
        
        # Print known position dates per depot for demonstration
        for depot, dates in depot_position_dates.items():
            print(f"Depot {depot} has known position dates: {sorted(dates)}")
        # Print covered date ranges per depot for demonstration
        for depot, coverage in depot_coverage.items():
            print(f"Depot {depot} has covered date ranges: {coverage.covered}")

        # --- Tax period coverage and statement date check ---
        for depot, coverage in depot_coverage.items():
            # Check if the tax period is fully covered
            if not coverage.is_covered(self.period_from, self.period_to):
                raise ValueError(f"Depot {depot}: Tax period {self.period_from} to {self.period_to} is not fully covered by available data.\nSuggestion: Download and import statements covering this range for depot '{depot}'.")
            # Find the maximal covered range containing the tax period start
            max_range = coverage.maximal_covered_range_containing(self.period_from)
            if not max_range:
                raise ValueError(f"Depot {depot}: No covered range contains the tax period start {self.period_from}.\nSuggestion: Download and import statements covering this date for depot '{depot}'.")
            # Check that at least one statement date is in this range
            statement_dates = depot_position_dates.get(depot, set())
            # Accept a statement date in the range OR exactly one day after the range end
            if not any((max_range[0] <= d <= max_range[1]) or (d == max_range[1] + timedelta(days=1)) for d in statement_dates):
                raise ValueError(f"Depot {depot}: No statement date in the maximal covered range {max_range} (or the day after) for the tax period.\nSuggestion: Download and import a statement with a statement date within {max_range} or the day after for depot '{depot}'.")
        # --- End coverage check ---
            
        # Post-process: aggregate stocks/payments per unique Position
        security_map = defaultdict(lambda: ([], []))  # SecurityPosition -> (list of SecurityStock, list of SecurityPayment)
        cash_map = defaultdict(list)      # CashPosition -> list of SecurityStock
        payments_added = set()  # Track which SecurityPositions have had payments added
        
        for pos, stock, payments in all_positions:
            if isinstance(pos, SecurityPosition):
                # Ensure stock is a list for security_map, even if it's a single item initially from all_positions
                current_stocks, current_payments = security_map[pos]
                current_stocks.append(stock)
                if payments: # payments can be a list or a single item
                    if isinstance(payments, list):
                        current_payments.extend(payments)
                    else:
                        current_payments.append(payments)
            elif isinstance(pos, CashPosition):
                # cash_map value is a list of SecurityStock items directly associated with the CashPosition key
                cash_map[pos].append(stock)
        
        tax_year = self.period_from.year
        
        # --- Reconcile and ensure period boundary stock records --- 
        final_security_tuples = []
        processed_security_positions_for_reconciliation = set()

        temp_all_security_stocks_map = defaultdict(list)
        for p, s, _ in all_positions:
            if isinstance(p, SecurityPosition):
                temp_all_security_stocks_map[p].append(s)

        for sec_pos, (initial_stocks, associated_payments) in security_map.items():
            if sec_pos in processed_security_positions_for_reconciliation:
                continue
            processed_security_positions_for_reconciliation.add(sec_pos)

            current_identifier = f"{sec_pos.depot}-{sec_pos.symbol}"
            
            # 1. Initial Consistency Check on original data
            # Use a copy of initial_stocks for this check if it might be modified by the reconciler itself (e.g. internal sorting)
            # PositionReconciler sorts internally, so passing a list directly is fine.
            initial_reconciler = PositionReconciler(list(initial_stocks), identifier=f"{current_identifier}-initial_check")
            is_consistent_initial, logs_initial = initial_reconciler.check_consistency(
                print_log=True, 
                raise_on_error=self.strict_consistency
            )
            if not is_consistent_initial and not self.strict_consistency:
                print(f"WARNING: [{current_identifier}] Initial consistency check on raw data failed. Review logs above. Proceeding with synthesis.")

            live_stocks = list(initial_stocks) # Work with a copy for modifications

            # 2. Ensure start-of-period balance (self.period_from)
            reconciler_for_start = PositionReconciler(list(live_stocks), identifier=f"{current_identifier}-start_synth")
            start_pos_synth = reconciler_for_start.synthesize_position_at_date(self.period_from)
            
            has_start_balance = any(not s.mutation and s.referenceDate == self.period_from for s in live_stocks)

            if not has_start_balance:
                qty_to_set_at_start = Decimal('0')
                currency_at_start = live_stocks[0].balanceCurrency if live_stocks else "USD" # Default if no stocks
                q_type_at_start = live_stocks[0].quotationType if live_stocks else "PIECE"

                if start_pos_synth:
                    qty_to_set_at_start = start_pos_synth.quantity
                    if start_pos_synth.currency:
                         currency_at_start = start_pos_synth.currency
                    print(f"[{current_identifier}] Synthesized start position for {self.period_from}: Qty {qty_to_set_at_start} {currency_at_start}")
                else:
                    # Could not synthesize (e.g. no prior balance). Insert zero if no stocks before period_from.
                    # Or if earliest stock is a mutation after period_from.
                    earliest_stock_date = min(s.referenceDate for s in live_stocks) if live_stocks else None
                    if not earliest_stock_date or earliest_stock_date > self.period_from or \
                       (earliest_stock_date == self.period_from and live_stocks[0].mutation):
                        print(f"[{current_identifier}] No suitable existing/synthesizable start balance for {self.period_from}. Inserting zero balance.")
                    # If start_pos_synth was None but there was an earlier balance that led to a non-zero calculation somehow, that case is complex.
                    # Current synthesize_position_at_date returns None if no base balance. So qty_to_set_at_start remains 0 here.
               
                start_balance_stock = SecurityStock(\
                    referenceDate=self.period_from,\
                    mutation=False,\
                    quantity=qty_to_set_at_start,\
                    balanceCurrency=currency_at_start,\
                    quotationType=q_type_at_start,\
                    name=f"Opening Balance (Tax Period Start)"\
                )
                live_stocks.append(start_balance_stock)
                live_stocks = sorted(live_stocks, key=lambda s: (s.referenceDate, s.mutation))
                print(f"[{current_identifier}] Added/updated start-of-period balance for {self.period_from}.")

            # 3. Ensure end-of-period balance (day after self.period_to)
            effective_period_end_date = self.period_to + timedelta(days=1)
            reconciler_for_end = PositionReconciler(list(live_stocks), identifier=f"{current_identifier}-end_synth") # Use updated live_stocks
            end_pos_synth = reconciler_for_end.synthesize_position_at_date(effective_period_end_date)

            has_end_balance = any(not s.mutation and s.referenceDate == effective_period_end_date for s in live_stocks)

            if not has_end_balance and end_pos_synth:
                print(f"[{current_identifier}] Synthesized end position for {effective_period_end_date}: Qty {end_pos_synth.quantity} {end_pos_synth.currency}")
                end_balance_stock = SecurityStock(\
                    referenceDate=effective_period_end_date,\
                    mutation=False,\
                    quantity=end_pos_synth.quantity,\
                    balanceCurrency=end_pos_synth.currency if end_pos_synth.currency else (live_stocks[0].balanceCurrency if live_stocks else "USD"),\
                    quotationType=live_stocks[0].quotationType if live_stocks else "PIECE",\
                    name=f"Closing Balance (Tax Period End+1)"\
                )
                live_stocks.append(end_balance_stock)
                live_stocks = sorted(live_stocks, key=lambda s: (s.referenceDate, s.mutation))
                print(f"[{current_identifier}] Added end-of-period balance for {effective_period_end_date}.")
            elif not has_end_balance and not end_pos_synth:
                 print(f"[{current_identifier}] Could not synthesize end-of-period balance for {effective_period_end_date}. It might be missing.")

            # 4. Final state (live_stocks now includes synthesized start/end if created)
            # The main consistency check on raw data was done earlier.
            # If strict_consistency=True and raw data failed, we wouldn't reach here.
            # If strict_consistency=False, a warning was already printed.
            # No further *raising* consistency check is done here on the modified list by default,
            # as the crucial check is on the original data quality.
            # However, one might add a non-raising check here for debugging synthesized states if needed.
            # Example for debugging: 
            # final_state_reconciler = PositionReconciler(live_stocks, identifier=f"{current_identifier}-final_state_check")
            # final_state_reconciler.check_consistency(print_log=True, raise_on_error=False)
           
            final_security_tuples.append((sec_pos, live_stocks, associated_payments))

        # Process cash positions similarly
        final_cash_tuples = []
        for cash_pos, initial_cash_stocks in cash_map.items():
            current_identifier = f"Cash-{cash_pos.depot}-{cash_pos.currentCy}"

            # 1. Initial Consistency Check on original cash data
            initial_cash_reconciler = PositionReconciler(list(initial_cash_stocks), identifier=f"{current_identifier}-initial_check")
            is_consistent_initial_cash, logs_initial_cash = initial_cash_reconciler.check_consistency(
                print_log=True, 
                raise_on_error=self.strict_consistency
            )
            if not is_consistent_initial_cash and not self.strict_consistency:
                print(f"WARNING: [{current_identifier}] Initial consistency check on raw cash data failed. Review logs. Proceeding with synthesis.")

            live_stocks = list(initial_cash_stocks) # Work with a copy

            # 2. Ensure start-of-period balance for cash (self.period_from)
            reconciler_for_cash_start = PositionReconciler(list(live_stocks), identifier=f"{current_identifier}-start_synth")
            start_cash_pos_synth = reconciler_for_cash_start.synthesize_position_at_date(self.period_from)
            
            has_cash_start_balance = any(not s.mutation and s.referenceDate == self.period_from for s in live_stocks)

            if not has_cash_start_balance:
                qty_to_set_at_start = Decimal('0')
                # For cash, currency is from CashPosition itself or a default
                currency_at_start = cash_pos.currentCy if cash_pos.currentCy else "USD" 
                q_type_at_start = live_stocks[0].quotationType if live_stocks else "PIECE" # Default if no stocks

                if start_cash_pos_synth:
                    qty_to_set_at_start = start_cash_pos_synth.quantity
                    if start_cash_pos_synth.currency: # Synthesized currency might be more specific
                         currency_at_start = start_cash_pos_synth.currency
                    print(f"[{current_identifier}] Synthesized start cash position for {self.period_from}: Qty {qty_to_set_at_start} {currency_at_start}")
                else:
                    earliest_stock_date = min(s.referenceDate for s in live_stocks) if live_stocks else None
                    if not earliest_stock_date or earliest_stock_date > self.period_from or \
                       (earliest_stock_date == self.period_from and live_stocks[0].mutation):
                        print(f"[{current_identifier}] No suitable existing/synthesizable start cash balance for {self.period_from}. Inserting zero balance.")
                
                start_balance_stock = SecurityStock(\
                    referenceDate=self.period_from,\
                    mutation=False,\
                    quantity=qty_to_set_at_start,\
                    balanceCurrency=currency_at_start,\
                    quotationType=q_type_at_start,\
                    name=f"Opening Cash Balance (Tax Period Start)"\
                )
                live_stocks.append(start_balance_stock)
                live_stocks = sorted(live_stocks, key=lambda s: (s.referenceDate, s.mutation))
                print(f"[{current_identifier}] Added/updated start-of-period cash balance for {self.period_from}.")

            # 3. Ensure end-of-period cash balance (day after self.period_to)
            effective_period_end_date = self.period_to + timedelta(days=1)
            reconciler_for_cash_end = PositionReconciler(list(live_stocks), identifier=f"{current_identifier}-end_synth")
            end_cash_pos_synth = reconciler_for_cash_end.synthesize_position_at_date(effective_period_end_date)

            has_cash_end_balance = any(not s.mutation and s.referenceDate == effective_period_end_date for s in live_stocks)

            if not has_cash_end_balance and end_cash_pos_synth:
                # Use synthesized currency if available, otherwise cash_pos currency or default
                currency_at_end = end_cash_pos_synth.currency if end_cash_pos_synth.currency else (cash_pos.currentCy if cash_pos.currentCy else "USD")
                q_type_at_end = live_stocks[0].quotationType if live_stocks else "PIECE"

                print(f"[{current_identifier}] Synthesized end cash position for {effective_period_end_date}: Qty {end_cash_pos_synth.quantity} {currency_at_end}")
                end_balance_stock = SecurityStock(\
                    referenceDate=effective_period_end_date,\
                    mutation=False,\
                    quantity=end_cash_pos_synth.quantity,\
                    balanceCurrency=currency_at_end,\
                    quotationType=q_type_at_end,\
                    name=f"Closing Cash Balance (Tax Period End+1)"\
                )
                live_stocks.append(end_balance_stock)
                live_stocks = sorted(live_stocks, key=lambda s: (s.referenceDate, s.mutation))
                print(f"[{current_identifier}] Added end-of-period cash balance for {effective_period_end_date}.")
            elif not has_cash_end_balance and not end_cash_pos_synth:
                 print(f"[{current_identifier}] Could not synthesize end-of-period cash balance for {effective_period_end_date}. It might be missing.")

            # 4. Final state for cash (live_stocks now includes synthesized start/end if created)
            # Similar to securities, the main consistency check was on raw data.
            # Example for debugging:
            # final_cash_state_reconciler = PositionReconciler(live_stocks, identifier=f"{current_identifier}-final_state_check")
            # final_cash_state_reconciler.check_consistency(print_log=True, raise_on_error=False)
            
            final_cash_tuples.append((cash_pos, live_stocks)) # Use the reconciled list of stocks

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
        first_stock = stocks[0]
        sec = Security(
            positionId=1,  # In real code, ensure unique per security
            country="US",  # Stub
            currency=first_stock.balanceCurrency,
            quotationType=first_stock.quotationType,
            securityCategory="SHARE",  # Stub
            securityName=pos.symbol,
            stock=stocks,
            payment=payments or []
        )
        depots[depot_number].security.append(sec)
    return ListOfSecurities(depot=list(depots.values()))

def convert_cash_positions_to_list_of_bank_accounts(
    cash_tuples: list[tuple[CashPosition, list[SecurityStock]]]
) -> ListOfBankAccounts:
    """
    Convert a list of (CashPosition, List[SecurityStock]) tuples into a ListOfBankAccounts object.
    Minimal stub: one bank account per depot.
    """
    accounts: Dict[str, BankAccount] = {}
    for pos, stocks in cash_tuples:
        depot_number = pos.depot
        if depot_number not in accounts:
            # Ensure stocks is not None and has items before accessing stocks[0]
            default_currency = "USD" # Fallback if no stock items
            if stocks:
                default_currency = stocks[0].balanceCurrency
            else:
                print(f"Warning: CashPosition in depot {depot_number} has no stock items. Using default currency {default_currency}.")

            accounts[depot_number] = BankAccount(
                bankAccountNumber=BankAccountNumber(depot_number),
                bankAccountCurrency=default_currency,
                payment=[],
            )
        # Add stock as a taxValue (minimal stub) / or sum up quantities for a taxValue
        # This part needs more thought: how do cash SecurityStock items translate to BankAccountTaxValue?
        # For now, not creating BankAccountTaxValue from these stocks here.
        # accounts[depot_number].taxValue = None # Not implemented simply from list of stocks
    return ListOfBankAccounts(bankAccount=list(accounts.values()))

def create_tax_statement_from_positions(
    security_tuples: list[tuple[SecurityPosition, list[SecurityStock], list[SecurityPayment] | None]],
    cash_tuples: list[tuple[CashPosition, list[SecurityStock]]],
    period_from: date,
    period_to: date,
    tax_period: int
) -> TaxStatement:
    """
    Create a TaxStatement from security and cash tuples.
    """
    list_of_securities = convert_security_positions_to_list_of_securities(security_tuples)
    list_of_bank_accounts = convert_cash_positions_to_list_of_bank_accounts(cash_tuples)
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
