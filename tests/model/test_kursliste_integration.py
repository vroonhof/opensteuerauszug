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
    
    assert len(xml_files) > 0, "No XML files found in kursliste directory"
    
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
