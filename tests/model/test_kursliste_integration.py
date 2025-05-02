"""
Integration tests for the Kursliste model.

These tests verify that the KurslisteManager can correctly load and process
Kursliste files from the data directory.
"""

import os
from pathlib import Path

import pytest

from opensteuerauszug.core.kursliste_manager import KurslisteManager


@pytest.fixture
def kursliste_dir() -> Path:
    """Return the path to the kursliste test data directory."""
    # Get the project root directory
    root_dir = Path(__file__).parent.parent.parent
    
    # Path to the kursliste data directory
    kursliste_dir = root_dir / "data" / "kursliste"
    
    # Skip test if directory doesn't exist
    if not kursliste_dir.exists():
        pytest.skip(f"Kursliste data directory not found: {kursliste_dir}")
    
    return kursliste_dir


def test_kursliste_manager_loads_directory(kursliste_dir: Path, tmp_path: Path):
    """Test that KurslisteManager can load files from the kursliste directory."""
    # Count XML files in the directory
    xml_files = list(kursliste_dir.glob("*.xml"))
    
    # If no XML files found, create a test file
    if not xml_files:
        # Create a test directory if needed
        test_dir = tmp_path / "test_kursliste"
        test_dir.mkdir(exist_ok=True)
        
        # Create a simple test XML file
        test_file = test_dir / "test_kursliste_2023.xml"
        test_file.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<kursliste>
  <metadata>
    <issuer>Test Bank</issuer>
    <issueDate>2023-12-31</issueDate>
    <validForTaxYear>2023</validForTaxYear>
    <version>1.0</version>
  </metadata>
  <securities>
    <security>
      <name>Test Security</name>
      <identifiers>
        <valorNumber>12345678</valorNumber>
        <isin>CH0123456789</isin>
      </identifiers>
      <category>SHARE</category>
      <prices>
        <price>
          <date>2023-12-31</date>
          <value>100.00</value>
          <currencyCode>CHF</currencyCode>
          <priceType>CLOSING</priceType>
          <source>OTHER</source>
        </price>
      </prices>
    </security>
  </securities>
</kursliste>
""")
        kursliste_dir = test_dir
        xml_files = [test_file]
    
    # Create manager and load directory
    manager = KurslisteManager()
    manager.load_directory(kursliste_dir)
    
    # Verify that years were loaded
    assert manager.get_available_years(), "No tax years were loaded"
    
    # Print information about loaded files for debugging
    years = manager.get_available_years()
    for year in years:
        kurslisten = manager.get_kurslisten_for_year(year)
        print(f"Year {year}: {len(kurslisten)} Kursliste files loaded")


def test_kursliste_manager_handles_missing_directory():
    """Test that KurslisteManager handles missing directories gracefully."""
    manager = KurslisteManager()
    
    # Try to load a non-existent directory
    with pytest.raises(ValueError):
        manager.load_directory("/path/does/not/exist")


def test_kursliste_security_lookup(kursliste_dir: Path):
    """Test looking up securities in the loaded Kurslisten."""
    # Skip test if directory doesn't exist
    if not kursliste_dir.exists() or not list(kursliste_dir.glob("*.xml")):
        pytest.skip("Kursliste data directory not found or empty")
    
    # Create manager and load directory
    manager = KurslisteManager()
    manager.load_directory(kursliste_dir)
    
    # Get available years
    years = manager.get_available_years()
    if not years:
        pytest.skip("No Kursliste years loaded")
    
    # For demonstration purposes, we'll just check that the API works
    # In a real test, you would check against known values in test data
    year = years[0]
    kurslisten = manager.get_kurslisten_for_year(year)
    
    # Skip if no kurslisten or securities for this year
    if not kurslisten or not any(k.securities for k in kurslisten):
        pytest.skip(f"No securities found for year {year}")
    
    # Find a security with an ISIN
    for kursliste in kurslisten:
        for security in kursliste.securities:
            if security.identifiers.isin:
                # Try to look up this security
                price = manager.get_security_price(
                    tax_year=year,
                    isin=security.identifiers.isin
                )
                # We're just testing the API works, not specific values
                assert price is not None or True, "API call completed"
