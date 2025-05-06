from typing import List
import os
from opensteuerauszug.model.ech0196 import TaxStatement
from .statement_extractor import StatementExtractor
from datetime import date
from .position_extractor import PositionExtractor

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
                # TODO: Use extracted data to populate TaxStatement
            elif ext == ".json":
                # TransactionExtractor to be implemented
                # extractor = TransactionExtractor(filename)
                # TODO: Use extracted data to populate TaxStatement
                pass
            elif ext == ".csv":
                extractor = PositionExtractor(filename)
                positions_data = extractor.extract_positions()
                if positions_data is not None:
                    positions, statement_date, depot = positions_data
                    if depot not in depot_position_dates:
                        depot_position_dates[depot] = set()
                    depot_position_dates[depot].add(statement_date)
                    print(f"Extracted positions from {filename}: {positions}")
                    # TODO: Integrate positions_data into TaxStatement
                else:
                    print(f"Skipped file (not a Schwab positions CSV): {filename}")
            else:
                # Optionally log or raise for unsupported file types
                pass
        # Print known position dates per depot for demonstration
        for depot, dates in depot_position_dates.items():
            print(f"Depot {depot} has known position dates: {sorted(dates)}")
        # Return an empty TaxStatement for now (to be implemented)
        tax_year = self.period_from.year
        return TaxStatement(minorVersion=1, periodFrom=self.period_from, periodTo=self.period_to, taxPeriod=tax_year)

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
    print(tax_statement)
