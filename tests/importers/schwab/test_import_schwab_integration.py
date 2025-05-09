import os
import pytest
from datetime import date
from src.opensteuerauszug.importers.schwab.schwab_importer import SchwabImporter
from opensteuerauszug.model.ech0196 import TaxStatement
from tests.utils.samples import get_sample_dirs

SAMPLE_DIRS = get_sample_dirs('import/schwab')

@pytest.mark.parametrize("sample_dir", SAMPLE_DIRS)
def test_schwab_import_integration(sample_dir):
    if not SAMPLE_DIRS:
        pytest.skip("No Schwab sample directories with .pdf or .json files found.")
    period_from = date(2024, 1, 1)
    period_to = date(2024, 12, 31)
    importer = SchwabImporter(period_from=period_from, period_to=period_to, strict_consistency= True)
    tax_statement = importer.import_dir(sample_dir)
    assert tax_statement is not None, "TaxStatement should not be None for 2024 non-strict"
    assert tax_statement.listOfSecurities is not None, "ListOfSecurities should not be None for 2024 non-strict"
    # The integration test data is private, so we should add assertions on the contents
    # of the statement.
    assert tax_statement.periodFrom == period_from
    assert tax_statement.periodTo == period_to
    assert tax_statement.taxPeriod == 2024
    # Optionally, add more checks on the tax_statement fields 