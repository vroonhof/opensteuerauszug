import os
import re
import pytest
from datetime import date
from opensteuerauszug.importers.fidelity.fidelity_importer import FidelityImporter
from tests.utils.samples import get_sample_dirs

SAMPLE_DIRS = get_sample_dirs('import/fidelity', extensions=['.csv'])

def detect_tax_year(sample_dir: str) -> int:
    """Detect the tax year from filenames in the sample directory."""
    for filename in os.listdir(sample_dir):
        # Look for StatementMMDDYYYY pattern (e.g., Statement12312025)
        match = re.search(r"Statement\d{4}(20[2-3]\d)", filename)
        if match:
            return int(match.group(1))
        # Look for _YYYY pattern (e.g., _2025)
        match = re.search(r"_(20[2-3]\d)\b", filename)
        if match:
            return int(match.group(1))
    return 2025 # Default fallback

@pytest.mark.parametrize("sample_dir", SAMPLE_DIRS)
def test_fidelity_import_integration(sample_dir):
    if not SAMPLE_DIRS:
        pytest.skip("No Fidelity sample directories with .csv files found.")
    
    tax_year = detect_tax_year(sample_dir)
    period_from = date(tax_year, 1, 1)
    period_to = date(tax_year, 12, 31)
    
    # Initialize with empty settings to test robustness with unknown accounts
    importer = FidelityImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=[],
        strict_consistency=True
    )
    
    tax_statement = importer.import_dir(sample_dir)
    
    # Basic structural assertions
    assert tax_statement is not None
    assert tax_statement.taxPeriod == tax_year
    assert tax_statement.institution is not None
    assert "Fidelity" in tax_statement.institution.name
    
    # Ensure at least some data was imported
    has_securities = (tax_statement.listOfSecurities is not None and 
                     tax_statement.listOfSecurities.depot and 
                     len(tax_statement.listOfSecurities.depot) > 0)
    
    has_bank_accounts = (tax_statement.listOfBankAccounts is not None and 
                        tax_statement.listOfBankAccounts.bankAccount and 
                        len(tax_statement.listOfBankAccounts.bankAccount) > 0)
    
    assert has_securities or has_bank_accounts, f"Sample in {sample_dir} imported no securities and no bank accounts"

    # If we have securities, check they have basic required info
    if has_securities:
        for depot in tax_statement.listOfSecurities.depot:
            assert depot.depotNumber is not None
            for security in depot.security:
                assert security.securityName is not None
                assert len(security.stock) >= 2 # At least opening and closing balance
                assert security.currency is not None

    # If we have bank accounts, check they have basic required info
    if has_bank_accounts:
        for ba in tax_statement.listOfBankAccounts.bankAccount:
            assert ba.bankAccountNumber is not None
            assert ba.bankAccountCurrency is not None
            assert ba.taxValue is not None
