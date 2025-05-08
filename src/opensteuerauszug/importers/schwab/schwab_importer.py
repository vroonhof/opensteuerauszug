import pprint
from typing import List, Dict, Any
import os
from opensteuerauszug.model.ech0196 import (
    ListOfSecurities, ListOfBankAccounts, TaxStatement, Depot, Security, BankAccount, SecurityStock, SecurityPayment, DepotNumber, BankAccountNumber, CurrencyId
)
from opensteuerauszug.model.position import SecurityPosition, CashPosition, Position
from .statement_extractor import StatementExtractor
from datetime import date
from .position_extractor import PositionExtractor
from .transaction_extractor import TransactionExtractor
from opensteuerauszug.util.date_coverage import DateRangeCoverage
from collections import defaultdict

# Placeholder import for TransactionExtractor (to be implemented)
# from .TransactionExtractor import TransactionExtractor

class SchwabImporter:
    """
    Imports Schwab account data for a given tax period from PDF and JSON files.
    """
    def __init__(self, period_from: date, period_to: date):
        """
        Initialize the importer with a tax period defined by a start and end date.

        Args:
            period_from (date): The start date of the tax period.
            period_to (date): The end date of the tax period.
        """
        self.period_from = period_from
        self.period_to = period_to

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
                        depot_coverage[depot].mark_covered(start_date, end_date)
                        for stock in stocks:
                            all_positions.append((position, stock, payments))
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
        # Post-process: aggregate stocks/payments per unique Position
        security_map = defaultdict(lambda: ([], []))  # SecurityPosition -> (list of SecurityStock, list of SecurityPayment)
        cash_map = defaultdict(list)      # CashPosition -> list of SecurityStock
        for pos, stock, payments in all_positions:
            if isinstance(pos, SecurityPosition):
                security_map[pos][0].append(stock)
                if payments:
                    if isinstance(payments, list):
                        security_map[pos][1].extend(payments)
                    else:
                        security_map[pos][1].append(payments)
            elif isinstance(pos, CashPosition):
                cash_map[pos].append(stock)
        tax_year = self.period_from.year
        # Prepare tuples for create_tax_statement_from_positions
        security_tuples = []
        for pos, (stocks, payments) in security_map.items():
            if stocks:
                security_tuples.append((pos, list(stocks), list(payments) if payments else None))
        cash_tuples = [(pos, stock) for pos, stocks in cash_map.items() for stock in stocks]
        return create_tax_statement_from_positions(
            security_tuples,
            cash_tuples,
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
    cash_tuples: list[tuple[CashPosition, SecurityStock]]
) -> ListOfBankAccounts:
    """
    Convert a list of (CashPosition, SecurityStock) tuples into a ListOfBankAccounts object.
    Minimal stub: one bank account per depot.
    """
    accounts: Dict[str, BankAccount] = {}
    for pos, stock in cash_tuples:
        depot_number = pos.depot
        if depot_number not in accounts:
            accounts[depot_number] = BankAccount(
                bankAccountNumber=BankAccountNumber(depot_number),
                bankAccountCurrency=stock.balanceCurrency,
                payment=[],
            )
        # Add stock as a taxValue (minimal stub)
        accounts[depot_number].taxValue = None  # Not implemented
    return ListOfBankAccounts(bankAccount=list(accounts.values()))

def create_tax_statement_from_positions(
    security_tuples: list[tuple[SecurityPosition, list[SecurityStock], list[SecurityPayment] | None]],
    cash_tuples: list[tuple[CashPosition, SecurityStock]],
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
