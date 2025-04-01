"""Tests for the SteuerAuszug class."""

from datetime import date

import pytest

from opensteuerauszug import SteuerAuszug
from opensteuerauszug.steuerauszug import TaxEntry


def test_steuerauszug_creation():
    """Test basic creation of a SteuerAuszug instance."""
    auszug = SteuerAuszug(2024)
    assert auszug.year == 2024
    assert len(auszug.entries) == 0


def test_add_entry():
    """Test adding entries to a SteuerAuszug."""
    auszug = SteuerAuszug(2024)
    entry = TaxEntry(
        date=date(2024, 1, 1),
        description="Test Entry",
        amount=100.0,
        category="Income",
        tax_year=2024,
    )
    auszug.add_entry(entry)
    assert len(auszug.entries) == 1
    assert auszug.total() == 100.0


def test_add_entry_wrong_year():
    """Test adding an entry with wrong year raises error."""
    auszug = SteuerAuszug(2024)
    entry = TaxEntry(
        date=date(2023, 12, 31),
        description="Wrong Year Entry",
        amount=100.0,
        category="Income",
        tax_year=2023,
    )
    with pytest.raises(ValueError):
        auszug.add_entry(entry) 