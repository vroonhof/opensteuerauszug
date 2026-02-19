import os
import pytest
from datetime import date
from src.opensteuerauszug.importers.schwab.schwab_importer import SchwabImporter
from opensteuerauszug.model.ech0196 import TaxStatement
from tests.utils.samples import get_sample_dirs

SAMPLE_DIRS = get_sample_dirs('import/schwab')

import re

def detect_tax_year(sample_dir: str) -> int:
    """Detect the tax year from filenames in the sample directory."""
    for filename in os.listdir(sample_dir):
        # Look for _YYYY pattern (e.g., _2025)
        match = re.search(r"_(20[2-3]\d)\b", filename)
        if match:
            return int(match.group(1))
    return 2024 # Default fallback

@pytest.mark.parametrize("sample_dir", SAMPLE_DIRS)
def test_schwab_import_integration(sample_dir):
    if not SAMPLE_DIRS:
        pytest.skip("No Schwab sample directories with .pdf or .json files found.")
    
    tax_year = detect_tax_year(sample_dir)
    period_from = date(tax_year, 1, 1)
    period_to = date(tax_year, 12, 31)
    # TODO Create a real configuration for the test
    importer = SchwabImporter(period_from=period_from, period_to=period_to, account_settings_list=[], strict_consistency= True)
    tax_statement = importer.import_dir(sample_dir)
    assert tax_statement is not None, f"TaxStatement should not be None for {tax_year} non-strict"
    assert tax_statement.listOfSecurities is not None, f"ListOfSecurities should not be None for {tax_year} non-strict"
    # The integration test data is private, so we should add assertions on the contents
    # of the statement.
    assert tax_statement.periodFrom == period_from
    assert tax_statement.periodTo == period_to
    assert tax_statement.taxPeriod == tax_year
    # Optionally, add more checks on the tax_statement fields 
 