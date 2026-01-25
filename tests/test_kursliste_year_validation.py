"""
Test that validates early detection of missing Kursliste for the tax year.
"""
import pytest
from pathlib import Path
from datetime import date
from unittest.mock import Mock, patch

from opensteuerauszug.core.kursliste_manager import KurslisteManager


def test_missing_kursliste_year_detected_early(tmp_path):
    """
    Test that when processing a tax year without a corresponding Kursliste,
    the error is raised early with a helpful message, not during later calculation.
    """
    manager = KurslisteManager()
    
    # Simulate loading a directory with only 2024 data
    manager.kurslisten = {2024: Mock()}  # Mock accessor for 2024
    
    # Check available years
    available_years = manager.get_available_years()
    assert available_years == [2024]
    
    # Simulate trying to process 2025 tax year
    required_tax_year = 2025
    
    # This should raise a clear error
    with pytest.raises(ValueError) as exc_info:
        manager.ensure_year_available(required_tax_year, Path("data/kursliste"))
    
    error_message = str(exc_info.value)
    assert "Kursliste data for tax year 2025 not found" in error_message
    assert "Available years: 2024" in error_message
    assert "kursliste_2025.sqlite or kursliste_2025.xml" in error_message


def test_correct_kursliste_year_available(tmp_path):
    """
    Test that when the correct Kursliste year is available, no error is raised.
    """
    manager = KurslisteManager()
    
    # Simulate loading a directory with 2025 data
    manager.kurslisten = {2025: Mock()}  # Mock accessor for 2025
    
    # Check available years
    available_years = manager.get_available_years()
    assert available_years == [2025]
    
    # Simulate trying to process 2025 tax year - should not raise
    required_tax_year = 2025
    manager.ensure_year_available(required_tax_year, Path("data/kursliste"))  # Should not raise


def test_multiple_years_available():
    """
    Test that multiple years can be loaded and validated correctly.
    """
    manager = KurslisteManager()
    
    # Simulate loading multiple years
    manager.kurslisten = {
        2023: Mock(),
        2024: Mock(),
        2025: Mock()
    }
    
    available_years = manager.get_available_years()
    assert available_years == [2023, 2024, 2025]
    
    # Each year should be accessible and validated without error
    for year in [2023, 2024, 2025]:
        assert year in available_years
        assert manager.get_kurslisten_for_year(year) is not None
        manager.ensure_year_available(year)  # Should not raise


def test_ensure_year_available_no_directory_path():
    """
    Test that ensure_year_available works without providing a directory path.
    """
    manager = KurslisteManager()
    manager.kurslisten = {2024: Mock()}
    
    # Should work without directory path
    manager.ensure_year_available(2024)  # Should not raise
    
    # Should still raise error for missing year, just without directory in message
    with pytest.raises(ValueError) as exc_info:
        manager.ensure_year_available(2025)
    
    error_message = str(exc_info.value)
    assert "Kursliste data for tax year 2025 not found" in error_message
    assert "Available years: 2024" in error_message
