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
    importer = SchwabImporter(period_from=period_from, period_to=period_to, strict_consistency=False)
    tax_statement = importer.import_dir(sample_dir)
    assert tax_statement is not None, "TaxStatement should not be None for 2024 non-strict"
    assert tax_statement.listOfSecurities is not None, "ListOfSecurities should not be None for 2024 non-strict"
    # Add more specific assertions if the structure of the output for 2024 is known
    # For now, just ensuring it runs without a consistency error is the goal.
    # Example: check if any securities were processed for known depots if applicable
    found_depot_178 = any(d.depotNumber == "178" for d in tax_statement.listOfSecurities.depot)
    found_depot_AWARDS = any(d.depotNumber == "AWARDS" for d in tax_statement.listOfSecurities.depot)
    assert found_depot_178 or found_depot_AWARDS, "Expected to process at least one known depot (178 or AWARDS) for 2024 non-strict"
    assert tax_statement.periodFrom == period_from
    assert tax_statement.periodTo == period_to
    assert tax_statement.taxPeriod == 2024
    # Optionally, add more checks on the tax_statement fields 