import sqlite3
import pytest
import xml.etree.ElementTree as ET
from pathlib import Path
from scripts.convert_kursliste_to_sqlite import convert_kursliste_xml_to_sqlite

@pytest.fixture
def temp_kursliste_xml(tmp_path):
    """Creates a minimal temporary Kursliste XML file."""
    xml_path = tmp_path / "kursliste_2024_test.xml"

    root = ET.Element("kursliste", {
        "xmlns": "http://xmlns.estv.admin.ch/ictax/2.2.0/kursliste",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "year": "2024"
    })

    # Add a share with a payment (Implied Rate)
    # USD rate on 2024-01-01 (Monday)
    share = ET.SubElement(root, "share", {
        "id": "s1", "valorNumber": "123", "isin": "CH0000000001",
        "securityType": "SHARE.COMMON", "securityGroup": "SHARE",
        "institutionId": "1", "institutionName": "Test Corp",
        "country": "US", "currency": "USD"
    })
    ET.SubElement(share, "payment", {
        "paymentDate": "2024-01-01",
        "currency": "USD",
        "exchangeRate": "0.85",
        "paymentValue": "10.0"
    })
    # Add a conflicting payment to test warning (same day, diff rate)
    ET.SubElement(share, "payment", {
        "paymentDate": "2024-01-01",
        "currency": "USD",
        "exchangeRate": "0.90", # Conflict!
        "paymentValue": "10.0"
    })

    # Add an explicit Exchange Rate (Official Rate)
    # EUR rate on 2024-01-02 (Tuesday)
    ET.SubElement(root, "exchangeRate", {
        "currency": "EUR",
        "date": "2024-01-02",
        "value": "0.95",
        "denomination": "1"
    })

    # Add an explicit Exchange Rate for USD that overlaps with payment
    # USD rate on 2024-01-03 (Wednesday) - explicit
    ET.SubElement(root, "exchangeRate", {
        "currency": "USD",
        "date": "2024-01-03",
        "value": "0.86",
        "denomination": "1"
    })

    # Add a payment that overlaps with explicit rate (should be ignored for DB insert but tracked)
    ET.SubElement(share, "payment", {
        "paymentDate": "2024-01-03",
        "currency": "USD",
        "exchangeRate": "0.865", # Implied differes slightly
        "paymentValue": "10.0"
    })

    tree = ET.ElementTree(root)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return xml_path

def test_no_flags(temp_kursliste_xml, tmp_path, capsys):
    """Test that without flags, no implied rates are inserted or reported."""
    db_path = tmp_path / "test_no_flags.sqlite"

    convert_kursliste_xml_to_sqlite(str(temp_kursliste_xml), str(db_path))

    captured = capsys.readouterr()
    assert "Uncovered Trading Days Report" not in captured.out

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Should contain explicit rates
    cursor.execute("SELECT count(*) FROM exchange_rates_daily WHERE currency_code='EUR'")
    assert cursor.fetchone()[0] == 1

    # Should NOT contain implied rates (USD on 2024-01-01)
    cursor.execute("SELECT count(*) FROM exchange_rates_daily WHERE currency_code='USD' AND date='2024-01-01'")
    assert cursor.fetchone()[0] == 0

    conn.close()

def test_extract_only(temp_kursliste_xml, tmp_path, capsys):
    """Test reporting of missing days."""
    db_path = tmp_path / "test_extract.sqlite"

    convert_kursliste_xml_to_sqlite(str(temp_kursliste_xml), str(db_path), extract_implied_rates=True)

    captured = capsys.readouterr()
    assert "Uncovered Trading Days Report" in captured.out
    assert "USD:" in captured.out
    assert "EUR:" in captured.out
    # We expect missing days because we only provided 2 days for USD and 1 for EUR in 2024

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # DB should still be empty of implied rates
    cursor.execute("SELECT count(*) FROM exchange_rates_daily WHERE currency_code='USD' AND date='2024-01-01'")
    assert cursor.fetchone()[0] == 0
    conn.close()

def test_insert_implied(temp_kursliste_xml, tmp_path, capsys):
    """Test insertion of implied rates."""
    db_path = tmp_path / "test_insert.sqlite"

    # Capture logs to check for conflict warning?
    # The script uses logger.warning which might go to stderr or defined logging config.
    # The script uses `logger = logging.getLogger(__name__)` in rate_extractor.py

    convert_kursliste_xml_to_sqlite(str(temp_kursliste_xml), str(db_path), insert_implied_rates=True)

    captured = capsys.readouterr()
    assert "Inserting implied exchange rates" in captured.out

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check 2024-01-01 USD implied rate (first one wins: 0.85)
    cursor.execute("SELECT rate, source_file FROM exchange_rates_daily WHERE currency_code='USD' AND date='2024-01-01'")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "0.85"
    assert "(IMPLIED)" in row[1]

    # Check 2024-01-03 USD explicit rate (should exist)
    cursor.execute("SELECT rate, source_file FROM exchange_rates_daily WHERE currency_code='USD' AND date='2024-01-03'")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "0.86"
    # The source file for explicit rates is just the filename, no IMPLIED marker
    assert "(IMPLIED)" not in row[1]

    # Ensure the implied rate for 2024-01-03 (0.865) was NOT inserted (conflict with official)
    # The query above confirmed we got 0.86. Let's make sure we don't have duplicates if that's a concern,
    # or that the implied row wasn't added.
    cursor.execute("SELECT count(*) FROM exchange_rates_daily WHERE currency_code='USD' AND date='2024-01-03'")
    assert cursor.fetchone()[0] == 1 # Only one entry, the official one

    conn.close()

def test_rate_compatibility():
    """Test specific rate compatibility logic."""
    manager = ImpliedRateManager()

    # Case 1: Compatible, higher precision wins
    # 0.85 vs 0.851 (rounds to 0.85) -> Keep 0.851
    manager.add_payment("2024-01-01", "USD", "0.85")
    assert manager.implied_rates["USD"][datetime.date(2024, 1, 1)] == "0.85"

    manager.add_payment("2024-01-01", "USD", "0.851")
    assert manager.implied_rates["USD"][datetime.date(2024, 1, 1)] == "0.851" # Upgraded

    # Case 2: Compatible, lower precision ignored
    # 0.851 vs 0.85 (rounds to 0.85) -> Keep 0.851
    manager.add_payment("2024-01-02", "USD", "0.851")
    manager.add_payment("2024-01-02", "USD", "0.85")
    assert manager.implied_rates["USD"][datetime.date(2024, 1, 2)] == "0.851" # Kept high precision

    # Case 3: Incompatible
    # 0.85 vs 0.856 (rounds to 0.86) -> Conflict, keep original
    manager.add_payment("2024-01-03", "USD", "0.85")
    manager.add_payment("2024-01-03", "USD", "0.856")
    assert manager.implied_rates["USD"][datetime.date(2024, 1, 3)] == "0.85" # Rejected 0.856

    # Case 4: Equal
    manager.add_payment("2024-01-04", "USD", "0.85")
    manager.add_payment("2024-01-04", "USD", "0.85")
    assert manager.implied_rates["USD"][datetime.date(2024, 1, 4)] == "0.85"
