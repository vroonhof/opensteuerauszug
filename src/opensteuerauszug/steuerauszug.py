"""Main module for handling tax statements."""

from datetime import date
from typing import List

import pandas as pd
from pydantic import BaseModel


class TaxEntry(BaseModel):
    """A single tax-relevant entry."""
    date: date
    description: str
    amount: float
    category: str
    tax_year: int


class SteuerAuszug:
    """Main class for handling tax statements."""

    def __init__(self, year: int):
        """Initialize a new tax statement.
        
        Args:
            year: The tax year this statement is for
        """
        self.year = year
        self.entries: List[TaxEntry] = []

    def add_entry(self, entry: TaxEntry) -> None:
        """Add a new entry to the tax statement.
        
        Args:
            entry: The tax entry to add
        """
        if entry.tax_year != self.year:
            raise ValueError(f"Entry year {entry.tax_year} does not match statement year {self.year}")
        self.entries.append(entry)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the tax statement to a pandas DataFrame.
        
        Returns:
            A DataFrame containing all entries
        """
        return pd.DataFrame([entry.model_dump() for entry in self.entries])

    def total(self) -> float:
        """Calculate the total amount of all entries.
        
        Returns:
            The sum of all entry amounts
        """
        return sum(entry.amount for entry in self.entries) 