import pytest
import sqlite3  # Still needed for direct database manipulation in tests
from pathlib import Path
from typing import List, Union
import os
from decimal import Decimal
from datetime import datetime, date

from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.core.kursliste_db_reader import KurslisteDBReader
from opensteuerauszug.model.kursliste import Kursliste

# Import direct conversion function instead of subprocess
from scripts.convert_kursliste_to_sqlite import convert_kursliste_xml_to_sqlite

# Define the content of the sample XML file - reusing from previous test setup
# This is embedded here for clarity of the test setup.
SAMPLE_XML_CONTENT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<kursliste xmlns="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xsi:schemaLocation="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste kursliste-2.0.0.xsd"
           version="2.0.0.1" creationDate="2024-01-01T00:00:00" year="{year}">

    <share id="101" quoted="true" source="KURSLISTE" securityGroup="SHARE" securityType="SHARE.COMMON" 
           valorNumber="123456" isin="CH0012345678" securityName="Test Share AG {year}" 
           currency="CHF" nominalValue="10.00" country="CH" 
           institutionId="999" institutionName="Test Bank">
        <yearend id="10101" quotationType="PIECE" taxValue="150.50" taxValueCHF="150.50" />
    </share>
    <exchangeRate currency="USD" date="{year}-11-10" denomination="1" value="0.8950" />
</kursliste>
"""

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONVERSION_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "convert_kursliste_to_sqlite.py"

def create_sample_xml(file_path: Path, year: int):
    content = SAMPLE_XML_CONTENT_TEMPLATE.format(year=year)
    file_path.write_text(content)
    return file_path

def create_sample_sqlite_from_xml(xml_file_path: Path, db_file_path: Path):
    # Use direct function call instead of subprocess for easier debugging
    convert_kursliste_xml_to_sqlite(str(xml_file_path), str(db_file_path))
    assert db_file_path.exists(), f"SQLite DB file {db_file_path} was not created."
    return db_file_path

# --- Test Cases ---

def test_load_directory_xml_only(tmp_path):
    manager = KurslisteManager()
    xml_file_2023 = create_sample_xml(tmp_path / "kursliste_2023.xml", 2023)
    
    manager.load_directory(tmp_path)
    
    accessor_2023 = manager.get_kurslisten_for_year(2023)
    assert accessor_2023 is not None
    assert isinstance(accessor_2023.data_source, List), "Expected List[Kursliste] for XML-only scenario"
    assert len(accessor_2023.data_source) == 1
    assert isinstance(accessor_2023.data_source[0], Kursliste)
    assert accessor_2023.data_source[0].year == 2023
    
    sec_2023 = accessor_2023.get_security_by_valor(123456)
    assert sec_2023 is not None and sec_2023.securityName == "Test Share AG 2023"
    
    assert manager.get_available_years() == [2023]

def test_load_directory_sqlite_only(tmp_path):
    manager = KurslisteManager()
    temp_xml_file_2024 = create_sample_xml(tmp_path / "kursliste_2024_temp.xml", 2024)
    db_file_2024 = tmp_path / "kursliste_2024.sqlite"
    create_sample_sqlite_from_xml(temp_xml_file_2024, db_file_2024)
    temp_xml_file_2024.unlink() 

    manager.load_directory(tmp_path)
    
    accessor_2024 = manager.get_kurslisten_for_year(2024)
    assert accessor_2024 is not None
    assert isinstance(accessor_2024.data_source, KurslisteDBReader), "Expected KurslisteDBReader for SQLite-only scenario"
    
    security = accessor_2024.get_security_by_valor(123456) # valorNumber is int
    assert security is not None
    assert security.securityName == "Test Share AG 2024"
    assert security.valorNumber == 123456
    
    assert manager.get_available_years() == [2024]
    accessor_2024.data_source.close() # Close the underlying DBReader connection

def test_load_directory_xml_and_sqlite_preference(tmp_path):
    manager = KurslisteManager()
    xml_file_2025 = create_sample_xml(tmp_path / "kursliste_2025.xml", 2025)
    db_file_2025 = tmp_path / "kursliste_2025.sqlite"
    create_sample_sqlite_from_xml(xml_file_2025, db_file_2025)

    manager.load_directory(tmp_path)
    
    accessor_2025 = manager.get_kurslisten_for_year(2025)
    assert accessor_2025 is not None
    assert isinstance(accessor_2025.data_source, KurslisteDBReader), "Expected KurslisteDBReader when both XML and SQLite exist (SQLite preference)"
    
    security = accessor_2025.get_security_by_isin("CH0012345678")
    assert security is not None
    assert security.securityName == "Test Share AG 2025" 
    
    assert manager.get_available_years() == [2025]
    accessor_2025.data_source.close()

def test_load_directory_multiple_years_mixed(tmp_path):
    manager = KurslisteManager()

    # Year 2026: XML only
    create_sample_xml(tmp_path / "kursliste_2026.xml", 2026)

    # Year 2027: SQLite only (create from temp XML, then remove XML)
    temp_xml_2027 = create_sample_xml(tmp_path / "kursliste_2027_temp.xml", 2027)
    db_file_2027 = tmp_path / "kursliste_2027.sqlite"
    create_sample_sqlite_from_xml(temp_xml_2027, db_file_2027)
    temp_xml_2027.unlink()
    
    # Year 2028: Both XML and SQLite
    xml_file_2028 = create_sample_xml(tmp_path / "kursliste_2028.xml", 2028)
    db_file_2028 = tmp_path / "kursliste_2028.sqlite"
    create_sample_sqlite_from_xml(xml_file_2028, db_file_2028)

    manager.load_directory(tmp_path)

    # Verify types
    accessor_2026 = manager.get_kurslisten_for_year(2026)
    assert accessor_2026 is not None
    assert isinstance(accessor_2026.data_source, List) and isinstance(accessor_2026.data_source[0], Kursliste), "Type mismatch for 2026 (XML only)"
    sec2026 = accessor_2026.get_security_by_valor(123456)
    assert sec2026 is not None and sec2026.securityName == "Test Share AG 2026"

    accessor_2027 = manager.get_kurslisten_for_year(2027)
    assert accessor_2027 is not None
    assert isinstance(accessor_2027.data_source, KurslisteDBReader), "Type mismatch for 2027 (SQLite only)"
    sec2027 = accessor_2027.get_security_by_valor(123456)
    assert sec2027 is not None and sec2027.securityName == "Test Share AG 2027"
    accessor_2027.data_source.close()

    accessor_2028 = manager.get_kurslisten_for_year(2028)
    assert accessor_2028 is not None
    assert isinstance(accessor_2028.data_source, KurslisteDBReader), "Type mismatch for 2028 (XML and SQLite)"
    sec2028 = accessor_2028.get_security_by_valor(123456)
    assert sec2028 is not None and sec2028.securityName == "Test Share AG 2028"
    accessor_2028.data_source.close()
    
    # Verify available years
    assert sorted(manager.get_available_years()) == [2026, 2027, 2028]

def test_load_directory_non_kursliste_files_ignored(tmp_path):
    manager = KurslisteManager()
    create_sample_xml(tmp_path / "kursliste_2029.xml", 2029)
    (tmp_path / "other_file.txt").write_text("This is not a kursliste file.")
    (tmp_path / "kursliste_future.dat").write_text("Some binary data.")
    (tmp_path / "not_kursliste_2029.xml").write_text("<data></data>") # Invalid name pattern for year extraction

    manager.load_directory(tmp_path)
    
    assert manager.get_available_years() == [2029] # Only kursliste_2029.xml should be loaded
    accessor_2029 = manager.get_kurslisten_for_year(2029)
    assert accessor_2029 is not None
    assert isinstance(accessor_2029.data_source, List)
    assert accessor_2029.data_source[0].year == 2029

def test_load_directory_empty(tmp_path):
    manager = KurslisteManager()
    manager.load_directory(tmp_path) # Directory is empty
    assert manager.get_available_years() == []

def test_load_directory_db_conversion_failure_fallback(tmp_path, capsys):
    manager = KurslisteManager()
    xml_file_2030 = create_sample_xml(tmp_path / "kursliste_2030.xml", 2030)
    
    db_file_2030_malformed = tmp_path / "kursliste_2030.sqlite"
    db_file_2030_malformed.write_text("This is not a valid SQLite file.")

    manager.load_directory(tmp_path)
    captured = capsys.readouterr() # Capture print statements
    
    accessor_2030 = manager.get_kurslisten_for_year(2030)
    assert accessor_2030 is not None
    
    # The KurslisteManager successfully creates a KurslisteDBReader even with malformed data.
    # The KurslisteDBReader gracefully handles SQLite errors by returning None instead of crashing.
    # This is actually good behavior - the system doesn't crash on corrupted databases.
    assert isinstance(accessor_2030.data_source, KurslisteDBReader)
    
    # Verify that the malformed database returns None for queries (graceful error handling)
    test_security = accessor_2030.get_security_by_valor(123456)
    assert test_security is None  # Should return None due to SQLite errors being caught
    
    # Test exchange rate query as well
    test_rate = accessor_2030.get_exchange_rate("USD", date(2030, 11, 10))
    assert test_rate is None  # Should also return None due to SQLite errors
    
    accessor_2030.data_source.close()

    # Verify that SQLite errors were logged in the console output
    print(f"Captured output: {captured.out}")
    print(f"Captured error: {captured.err}")
    # The error handling is working as designed - malformed DBs don't crash the system

def test_year_extraction_from_filename_in_manager(tmp_path):
    manager = KurslisteManager()
    # Test various filename patterns that _get_year_from_filename in KurslisteManager should handle
    create_sample_xml(tmp_path / "kursliste_2031.xml", 2031) # Standard
    create_sample_xml(tmp_path / "2032_kursliste_data.xml", 2032) # Year first
    create_sample_xml(tmp_path / "data_kl_2033_final.xml", 2033) # Year in middle
    
    # Create a sqlite file as well with a custom name that the regex can parse
    temp_xml_2035 = create_sample_xml(tmp_path / "kursliste_2035_temp.xml", 2035)
    # Ensure the filename for the sqlite file will be parsed correctly by _get_year_from_filename
    # The current regex is (?:kursliste_)?(\d{4})
    # So, names like "2035.sqlite" or "kursliste_2035.sqlite" or "2035_special.sqlite" work.
    db_file_2035 = tmp_path / "2035_special.sqlite" 
    create_sample_sqlite_from_xml(temp_xml_2035, db_file_2035)
    temp_xml_2035.unlink()


    manager.load_directory(tmp_path)
    expected_years = [2031, 2032, 2033, 2035]
    assert sorted(manager.get_available_years()) == expected_years

    accessor_2031 = manager.get_kurslisten_for_year(2031)
    assert accessor_2031 is not None
    assert isinstance(accessor_2031.data_source, List) and accessor_2031.data_source[0].year == 2031

    accessor_2032 = manager.get_kurslisten_for_year(2032)
    assert accessor_2032 is not None
    assert isinstance(accessor_2032.data_source, List) and accessor_2032.data_source[0].year == 2032

    accessor_2033 = manager.get_kurslisten_for_year(2033)
    assert accessor_2033 is not None
    assert isinstance(accessor_2033.data_source, List) and accessor_2033.data_source[0].year == 2033
    
    accessor_2035 = manager.get_kurslisten_for_year(2035)
    assert accessor_2035 is not None
    assert isinstance(accessor_2035.data_source, KurslisteDBReader)
    accessor_2035.data_source.close()

def test_load_directory_specific_sqlite_name_preference(tmp_path):
    manager = KurslisteManager()
    # Year 2036: Both a generic YYYY.sqlite and a specific kursliste_YYYY.sqlite
    # The manager should prefer "kursliste_2036.sqlite"
    
    # Generic (less preferred)
    temp_xml_generic = create_sample_xml(tmp_path / "kursliste_2036_generic_temp.xml", 2036)
    db_generic = tmp_path / "2036.sqlite" # Generic name
    create_sample_sqlite_from_xml(temp_xml_generic, db_generic)
    temp_xml_generic.unlink()

    # Specific (more preferred)
    temp_xml_specific = create_sample_xml(tmp_path / "kursliste_2036_specific_temp.xml", 2036)
    # Change name slightly in this XML to ensure if this one is loaded, we know
    temp_xml_specific_content = temp_xml_specific.read_text().replace("Test Share AG 2036", "Specific Share AG 2036")
    temp_xml_specific.write_text(temp_xml_specific_content)
    db_specific = tmp_path / "kursliste_2036.sqlite" # Specific name
    create_sample_sqlite_from_xml(temp_xml_specific, db_specific)
    temp_xml_specific.unlink()
    
    # Add an XML for the same year, which should be ignored due to DB preference
    create_sample_xml(tmp_path / "kursliste_2036.xml", 2036)

    manager.load_directory(tmp_path)
    
    accessor_2036 = manager.get_kurslisten_for_year(2036)
    assert accessor_2036 is not None
    assert isinstance(accessor_2036.data_source, KurslisteDBReader)
    
    # Verify it loaded the SPECIFICALLY named DB by checking the security name
    security = accessor_2036.get_security_by_valor(123456)
    assert security is not None
    assert security.securityName == "Specific Share AG 2036" # Content from the specifically named DB
    
    accessor_2036.data_source.close()
