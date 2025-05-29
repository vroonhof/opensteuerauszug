"""
Pytest fixtures for tests/calculate directory.

This module provides session-scoped fixtures that are shared across all tests
in the calculate subdirectory, including fixtures for kursliste directories,
kursliste instances, and exchange rate providers.
"""

import pytest
from pathlib import Path
from typing import List

from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.model.kursliste import Kursliste
from tests.utils.samples import get_sample_dirs


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
def kursliste(kursliste_manager: KurslisteManager) -> Kursliste:
    """
    Get a sample Kursliste instance from the loaded kursliste manager.
    
    This fixture provides access to a single Kursliste instance for tests
    that need to examine kursliste data directly. It selects the first
    available kursliste from the latest available year.
    
    Args:
        kursliste_manager: The loaded KurslisteManager instance
        
    Returns:
        A Kursliste instance
    """
    available_years = kursliste_manager.get_available_years()
    if not available_years:
        pytest.skip("No kurslisten available in manager")
    
    # Get the latest available year and its first kursliste
    latest_year = max(available_years)
    kurslisten = kursliste_manager.get_kurslisten_for_year(latest_year)
    
    if not kurslisten:
        pytest.skip(f"No kurslisten found for year {latest_year}")
    
    return kurslisten[0]


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
