"""
Test file to verify that the new fixtures work correctly.
"""

import pytest
from pathlib import Path
from typing import List

from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.model.kursliste import Kursliste


def test_sample_kursliste_dirs_fixture(sample_kursliste_dirs: List[str]):
    """Test that the sample_kursliste_dirs fixture works."""
    assert isinstance(sample_kursliste_dirs, list)
    assert len(sample_kursliste_dirs) > 0
    for directory in sample_kursliste_dirs:
        assert Path(directory).exists()
        print(f"Found kursliste directory: {directory}")


def test_kursliste_manager_fixture(kursliste_manager: KurslisteManager):
    """Test that the kursliste_manager fixture works."""
    assert isinstance(kursliste_manager, KurslisteManager)
    available_years = kursliste_manager.get_available_years()
    assert len(available_years) > 0
    print(f"Available years: {available_years}")


def test_kursliste_fixture(kursliste: Kursliste):
    """Test that the kursliste fixture works."""
    assert isinstance(kursliste, Kursliste)
    assert kursliste.year is not None
    print(f"Kursliste year: {kursliste.year}")


def test_exchange_rate_provider_fixture(exchange_rate_provider: KurslisteExchangeRateProvider):
    """Test that the exchange_rate_provider fixture works."""
    assert isinstance(exchange_rate_provider, KurslisteExchangeRateProvider)
    # Test getting CHF rate (should always be 1.0)
    from datetime import date
    from decimal import Decimal
    
    chf_rate = exchange_rate_provider.get_exchange_rate("CHF", date(2023, 12, 31))
    assert chf_rate == Decimal("1")
    print(f"CHF exchange rate: {chf_rate}")
