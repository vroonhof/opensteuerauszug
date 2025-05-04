from typing import List
import os
from opensteuerauszug.model.ech0196 import TaxStatement
from .StatementExtractor import StatementExtractor
from datetime import date

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
        # TODO: Implement aggregation logic to build a TaxStatement from extracted data
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext == ".pdf":
                extractor = StatementExtractor(filename)
                # data = extractor.extract_data()
                # TODO: Use extracted data to populate TaxStatement
            elif ext == ".json":
                # TransactionExtractor to be implemented
                # extractor = TransactionExtractor(filename)
                # TODO: Use extracted data to populate TaxStatement
                pass
            else:
                # Optionally log or raise for unsupported file types
                pass
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
