"""
Pytest fixtures for tests/calculate directory.

This module provides session-scoped fixtures that are shared across all tests
in the calculate subdirectory, including fixtures for kursliste directories,
kursliste instances, and exchange rate providers.
"""

import pytest
import re
from pathlib import Path
from typing import List, Optional

from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.core.kursliste_accessor import KurslisteAccessor
from opensteuerauszug.model.kursliste import Kursliste
from opensteuerauszug.model.ech0196 import TaxStatement
from tests.utils.samples import get_sample_dirs


def extract_year_from_filename(filename: str) -> Optional[int]:
    """
    Extract a 4-digit year (20XX) from a filename.
    
    Args:
        filename: The filename to extract year from
        
    Returns:
        The extracted year as an integer, or None if no year found
    """
    match = re.search(r'(20[0-9]{2})', filename)
    if match:
        return int(match.group(1))
    return None


def get_tax_year_for_sample(sample_file: str, default_year: int = 2024) -> int:
    """
    Determine the tax year for a sample file.
    
    First tries to extract year from filename, then loads the file to check
    taxPeriod field, and falls back to default if neither is available.
    
    Args:
        sample_file: Path to the sample XML file
        default_year: Default year to use if none can be determined
        
    Returns:
        The tax year as an integer
    """
    # First try filename
    filename = Path(sample_file).name
    year = extract_year_from_filename(filename)
    if year:
        return year
    
    # Try loading the file and checking taxPeriod
    try:
        statement = TaxStatement.from_xml_file(sample_file)
        if statement.taxPeriod:
            return statement.taxPeriod
    except Exception:
        pass
    
    return default_year


def ensure_kursliste_year_available(kursliste_manager: KurslisteManager, required_year: int, sample_file: str) -> None:
    """
    Verify that kursliste data for the required year is available.
    
    Skips the test if the required year is not available in the kursliste manager.
    
    Args:
        kursliste_manager: The KurslisteManager instance
        required_year: The required tax year
        sample_file: The sample file being tested (for error message)
    """
    available_years = kursliste_manager.get_available_years()
    if required_year not in available_years:
        pytest.skip(
            f"Kursliste for year {required_year} not available for {sample_file}. "
            f"Available years: {sorted(available_years)}. "
            f"Please ensure kursliste_{required_year}.xml or kursliste_{required_year}.sqlite exists."
        )


@pytest.fixture(scope="session")
def sample_kursliste_dirs() -> List[str]:
    """
    Return a list of sample kursliste directories containing XML files.
    
    Uses get_sample_dirs to find kursliste/ subdirectories that contain *.xml files.
    This fixture is shared across the session for efficiency.
    
    Returns:
        List of directory paths containing kursliste XML files
    """
    dirs = get_sample_dirs("kursliste", extensions=['.xml'])
    if not dirs:
        pytest.skip("No kursliste sample directories with XML files found")
    return dirs


@pytest.fixture(scope="session") 
def kursliste_manager(sample_kursliste_dirs: List[str]) -> KurslisteManager:
    """
    Create and load a KurslisteManager with sample kursliste directories.
    
    This fixture loads XML files only from the first kursliste directory in the list
    (which is typically the kurstliste most specific to our integraion tests) into a KurslisteManager 
    instance. It's session-scoped for efficiency since loading kursliste files can be expensive.
    
    Args:
        sample_kursliste_dirs: List of directories containing kursliste XML files
        
    Returns:
        Configured KurslisteManager instance with loaded kurslisten
    """
    manager = KurslisteManager()
    
    if not sample_kursliste_dirs:
        pytest.skip("No kursliste sample directories found")
    
    # Load kurslisten only from the most specific directory in the list
    last_directory = sample_kursliste_dirs[0]
    try:
        manager.load_directory(last_directory)
    except Exception as e:
        pytest.skip(f"Failed to load kursliste directory {last_directory}: {e}")
    
    # Verify we have some kurslisten loaded
    if not manager.get_available_years():
        pytest.skip("No kurslisten were successfully loaded from sample directories")
    
    return manager


@pytest.fixture(scope="session")
def kursliste(kursliste_manager: KurslisteManager) -> KurslisteAccessor:
    """
    Get a sample KurslisteAccessor instance from the loaded kursliste manager.
    
    This fixture provides access to a KurslisteAccessor instance for tests
    that need to examine kursliste data. It selects the accessor for the latest
    available year.
    
    Args:
        kursliste_manager: The loaded KurslisteManager instance
        
    Returns:
        A KurslisteAccessor instance
    """
    available_years = kursliste_manager.get_available_years()
    if not available_years:
        pytest.skip("No kurslisten available in manager")
    
    # Get the latest available year and its accessor
    latest_year = max(available_years)
    accessor = kursliste_manager.get_kurslisten_for_year(latest_year)
    
    if not accessor:
        pytest.skip(f"No kursliste accessor found for year {latest_year}")
    
    return accessor


@pytest.fixture(scope="session")
def exchange_rate_provider(kursliste_manager: KurslisteManager) -> KurslisteExchangeRateProvider:
    """
    Create a KurslisteExchangeRateProvider using the loaded kursliste manager.
    
    This fixture provides a fully configured exchange rate provider that can
    be used across all tests in the calculate directory. It's session-scoped
    since the underlying kursliste data doesn't change.
    
    Args:
        kursliste_manager: The loaded KurslisteManager instance
        
    Returns:
        Configured KurslisteExchangeRateProvider instance
    """
    return KurslisteExchangeRateProvider(kursliste_manager)
