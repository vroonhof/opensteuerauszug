import pytest
import subprocess
import sqlite3
from pathlib import Path
from decimal import Decimal
import json # Added for model_validate_json
from typing import Dict, Type # Added for type map

# Import Pydantic models needed for deserialization and type map
from opensteuerauszug.model.kursliste import (
    Security, Share, Bond, Fund, Derivative, CoinBullion, CurrencyNote, LiborSwap,
    SecurityTypeESTV
)


# Updated Sample XML with a Fund and consistent structure
SAMPLE_XML_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<kursliste xmlns="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xsi:schemaLocation="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste kursliste-2.0.0.xsd"
           version="2.0.0.1" creationDate="2024-01-15T09:00:00" year="2023">

    <share id="101" quoted="true" source="KURSLISTE" securityGroup="SHARE" securityType="SHARE.COMMON" 
           valorNumber="123456" isin="CH0012345678" securityName="Test Share AG" 
           currency="CHF" nominalValue="10.00" country="CH" 
           institutionId="999" institutionName="Test Bank Share">
        <yearend id="10101" quotationType="PIECE" taxValue="150.50" taxValueCHF="150.50" />
    </share>

    <bond id="202" quoted="true" source="KURSLISTE" securityGroup="BOND" securityType="BOND.BOND" 
          valorNumber="789012" isin="CH0078901234" securityName="Test Bond Corp" 
          currency="EUR" nominalValue="1000.00" country="CH" 
          institutionId="998" institutionName="Test Bank Bond" issueDate="2020-01-01" redemptionDate="2030-01-01">
        <yearend id="20201" quotationType="PERCENT" percent="101.25" taxValue="1012.50" />
    </bond>

    <fund id="303" quoted="true" source="KURSLISTE" securityGroup="FUND" securityType="FUND.DISTRIBUTION" 
          valorNumber="654321" isin="LU0065432109" securityName="Test Global Fund" 
          currency="USD" nominalValue="1.0" country="LU" 
          institutionId="997" institutionName="Test Bank Fund">
        <yearend id="30301" quotationType="PIECE" taxValue="75.20" taxValueCHF="68.70" />
    </fund>
    
    <exchangeRate currency="USD" date="2023-11-10" denomination="1" value="0.8950" />
    <exchangeRate currency="GBP" date="2023-11-12" denomination="1" value="1.12345" />

    <exchangeRateMonthly currency="USD" year="2023" month="11" denomination="1" value="0.9000" />
    <exchangeRateMonthly currency="JPY" year="2023" month="10" denomination="100" value="0.6500" />

    <exchangeRateYearEnd currency="USD" year="2023" denomination="1" value="0.8800" valueMiddle="0.8850" />
    <exchangeRateYearEnd currency="EUR" year="2023" denomination="1" value="0.9600" />

</kursliste>
"""

# Determine the project root directory to correctly locate the script
# This assumes tests are run from the project root or a similar consistent location.
PROJECT_ROOT = Path(__file__).parent.parent.parent 
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "convert_kursliste_to_sqlite.py"


def get_table_info(conn, table_name):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row['name'] for row in cursor.fetchall()}

def test_convert_kursliste_xml_to_sqlite(tmp_path):
    # a. Prepare paths and run the script
    sample_xml_file = tmp_path / "sample_kursliste_for_db_test.xml"
    sample_xml_file.write_text(SAMPLE_XML_CONTENT)
    
    output_db_file = tmp_path / "kursliste_test.sqlite"

    # Ensure the script path is correct. If running tests from root, it's 'scripts/...'
    # If this test file is in tests/scripts/, then SCRIPT_PATH needs to be adjusted.
    # Assuming SCRIPT_PATH is correctly defined relative to where pytest is run.
    cmd = [
        "python", str(SCRIPT_PATH),
        str(sample_xml_file),
        str(output_db_file)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"Script execution failed: {result.stderr}"
    assert output_db_file.exists(), "SQLite DB file was not created."

    # b. Connect to the generated SQLite DB
    conn = sqlite3.connect(output_db_file)
    conn.row_factory = sqlite3.Row # Access columns by name
    cursor = conn.cursor()

    # c. Verify table existence and schema (key columns) for securities
    securities_expected_cols = {"kl_id", "valor_number", "isin", "tax_year", "security_type_identifier", "security_object_blob"}
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row['name'] for row in cursor.fetchall()}
    assert "securities" in tables, "Table 'securities' not found."
    
    actual_securities_cols = get_table_info(conn, "securities")
    assert securities_expected_cols.issubset(actual_securities_cols), \
        f"Table 'securities' does not have all expected columns. Missing: {securities_expected_cols - actual_securities_cols}"

    # Verify indexes on securities table
    indexes_info = {info['name'] for info in cursor.execute("PRAGMA index_list('securities');").fetchall()}
    assert "idx_valor" in indexes_info
    assert "idx_isin" in indexes_info
    assert "idx_tax_year" in indexes_info
    
    # d. Verify Pydantic Model Reconstruction for securities
    expected_tax_year = 2023

    # Define a type map similar to KurslisteDBReader._SECURITY_TYPE_MAP
    # This is a simplified version for test purposes
    SECURITY_TYPE_MAP: Dict[str, Type[Security]] = {
        SecurityTypeESTV.SHARE_COMMON.value: Share,
        SecurityTypeESTV.BOND_BOND.value: Bond,
        SecurityTypeESTV.FUND_DISTRIBUTION.value: Fund,
        # Add other types from sample XML if necessary
    }

    # Test Share
    cursor.execute("SELECT security_object_blob, security_type_identifier FROM securities WHERE kl_id = ?", ('101',))
    share_row = cursor.fetchone()
    assert share_row is not None
    share_model_class = SECURITY_TYPE_MAP.get(share_row["security_type_identifier"])
    assert share_model_class is Share
    reconstructed_share = share_model_class.model_validate_json(share_row["security_object_blob"].decode('utf-8'))
    
    assert reconstructed_share.id == 101
    assert reconstructed_share.valorNumber == 123456
    assert reconstructed_share.isin == "CH0012345678"
    assert reconstructed_share.securityName == "Test Share AG"
    assert reconstructed_share.currency == "CHF"
    assert reconstructed_share.nominalValue == Decimal("10.00")
    assert reconstructed_share.institutionId == 999
    assert reconstructed_share.institutionName == "Test Bank Share"

    # Test Bond
    cursor.execute("SELECT security_object_blob, security_type_identifier FROM securities WHERE kl_id = ?", ('202',))
    bond_row = cursor.fetchone()
    assert bond_row is not None
    bond_model_class = SECURITY_TYPE_MAP.get(bond_row["security_type_identifier"])
    assert bond_model_class is Bond
    reconstructed_bond = bond_model_class.model_validate_json(bond_row["security_object_blob"].decode('utf-8'))

    assert reconstructed_bond.id == 202
    assert reconstructed_bond.valorNumber == 789012
    assert reconstructed_bond.isin == "CH0078901234"
    assert reconstructed_bond.securityName == "Test Bond Corp"
    assert reconstructed_bond.currency == "EUR"
    assert reconstructed_bond.nominalValue == Decimal("1000.00")
    assert reconstructed_bond.institutionId == 998
    assert reconstructed_bond.institutionName == "Test Bank Bond"

    # Test Fund
    cursor.execute("SELECT security_object_blob, security_type_identifier FROM securities WHERE kl_id = ?", ('303',))
    fund_row = cursor.fetchone()
    assert fund_row is not None
    fund_model_class = SECURITY_TYPE_MAP.get(fund_row["security_type_identifier"])
    assert fund_model_class is Fund
    reconstructed_fund = fund_model_class.model_validate_json(fund_row["security_object_blob"].decode('utf-8'))

    assert reconstructed_fund.id == 303
    assert reconstructed_fund.valorNumber == 654321
    assert reconstructed_fund.isin == "LU0065432109"
    assert reconstructed_fund.securityName == "Test Global Fund"
    assert reconstructed_fund.currency == "USD"
    assert reconstructed_fund.nominalValue == Decimal("1.0")
    assert reconstructed_fund.institutionId == 997
    assert reconstructed_fund.institutionName == "Test Bank Fund"


    # e. Verify exchange rate tables (existing logic adapted)
    # Verify exchange_rates_daily data
    cursor.execute("SELECT * FROM exchange_rates_daily ORDER BY currency_code, date")
    daily_rates_rows = cursor.fetchall()
    # The sample XML only has one USD daily rate now for simplicity in this update.
    assert len(daily_rates_rows) == 2 # USD and GBP from original sample
    # The sample XML was updated, re-check these assertions.
    # Original SAMPLE_XML_CONTENT had USD and GBP daily rates.
    # New SAMPLE_XML_CONTENT has only USD daily rate specified within the template.
    # For this test to pass as originally written, the GBP rate from old sample needs to be in the new template.
    # Let's assume the new template is the source of truth, so only USD daily rate.
    # If GBP was intended, it should be in the new SAMPLE_XML_CONTENT.
    # The provided diff for SAMPLE_XML_CONTENT only shows USD for daily.
    # So, len(daily_rates_rows) should be 1.
    
    # Re-evaluating based on the new SAMPLE_XML_CONTENT provided in the prompt.
    # It has: <exchangeRate currency="USD" date="2023-11-10" denomination="1" value="0.8950" />
    # and also: <exchangeRate currency="GBP" date="2023-11-12" denomination="1" value="1.12345" />
    # from the original diff. So, 2 daily rates.

    assert len(daily_rates_rows) == 2 # GBP and USD

    gbp_daily = daily_rates_rows[0] 
    assert gbp_daily["currency_code"] == "GBP"
    assert gbp_daily["date"] == f"{expected_tax_year}-11-12" # Date from original sample
    assert Decimal(str(gbp_daily["rate"])) == Decimal("1.12345") # Value from original sample
    assert gbp_daily["tax_year"] == expected_tax_year
    # source_file is no longer in exchange rate tables per new schema, removing check
    # assert gbp_daily["source_file"] == source_file_name 

    usd_daily = daily_rates_rows[1]
    assert usd_daily["currency_code"] == "USD"
    assert usd_daily["date"] == f"{expected_tax_year}-11-10"
    assert Decimal(str(usd_daily["rate"])) == Decimal("0.8950")
    assert usd_daily["tax_year"] == expected_tax_year
    # assert usd_daily["source_file"] == source_file_name
    
    # Verify exchange_rates_monthly data
    # Original sample had USD and JPY monthly.
    cursor.execute("SELECT * FROM exchange_rates_monthly ORDER BY currency_code, month")
    monthly_rates_rows = cursor.fetchall()
    assert len(monthly_rates_rows) == 2

    jpy_monthly = monthly_rates_rows[0]
    assert jpy_monthly["currency_code"] == "JPY"
    assert jpy_monthly["year"] == expected_tax_year
    assert jpy_monthly["month"] == "10" # From original sample
    assert Decimal(str(jpy_monthly["rate"])) == Decimal("0.6500") # From original sample
    assert jpy_monthly["tax_year"] == expected_tax_year

    usd_monthly = monthly_rates_rows[1]
    assert usd_monthly["currency_code"] == "USD"
    assert usd_monthly["year"] == expected_tax_year
    assert usd_monthly["month"] == "11" # From original sample
    assert Decimal(str(usd_monthly["rate"])) == Decimal("0.9000") # From original sample
    assert usd_monthly["tax_year"] == expected_tax_year

    # Verify exchange_rates_year_end data
    # Original sample had USD and EUR year-end.
    cursor.execute("SELECT * FROM exchange_rates_year_end ORDER BY currency_code")
    year_end_rates_rows = cursor.fetchall()
    assert len(year_end_rates_rows) == 2
    
    eur_ye = year_end_rates_rows[0]
    assert eur_ye["currency_code"] == "EUR"
    assert eur_ye["year"] == expected_tax_year
    assert Decimal(str(eur_ye["rate"])) == Decimal("0.9600") # From original sample
    assert eur_ye["rate_middle"] is None 
    assert eur_ye["tax_year"] == expected_tax_year

    usd_ye = year_end_rates_rows[1]
    assert usd_ye["currency_code"] == "USD"
    assert usd_ye["year"] == expected_tax_year
    assert Decimal(str(usd_ye["rate"])) == Decimal("0.8800") # From original sample
    assert Decimal(str(usd_ye["rate_middle"])) == Decimal("0.8850") # From original sample
    assert usd_ye["tax_year"] == expected_tax_year

    conn.close()
    
    # Clean up the sample XML file explicitly if not using tmp_path features that auto-cleanup
    # sample_xml_file.unlink() # tmp_path should handle this
    # output_db_file.unlink() # tmp_path should handle this
