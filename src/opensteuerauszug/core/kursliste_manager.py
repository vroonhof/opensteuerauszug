"""
Manager for Kursliste (price list) files.

This module provides functionality to load and manage multiple Kursliste instances
for different tax years.
"""

import os
import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Union

from opensteuerauszug.model.kursliste import Kursliste


class KurslisteManager:
    """
    Manages multiple Kursliste instances for different tax years.
    
    This class loads and provides access to Kursliste files from a directory,
    organizing them by tax year for easy lookup.
    """
    
    def __init__(self):
        """Initialize an empty KurslisteManager."""
        self.kurslisten: Dict[int, List[Kursliste]] = {}
    
    def load_directory(self, directory_path: Union[str, Path]) -> None:
        """
        Load all Kursliste XML files from the specified directory.
        
        Args:
            directory_path: Path to directory containing Kursliste XML files
        """
        directory = Path(directory_path)
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Directory does not exist: {directory}")
        
        for file_path in directory.glob("*.xml"):
            try:
                kursliste = self._load_kursliste_from_file(file_path)
                tax_year = kursliste.metadata.validForTaxYear
                
                if tax_year not in self.kurslisten:
                    self.kurslisten[tax_year] = []
                
                self.kurslisten[tax_year].append(kursliste)
            except Exception as e:
                # Log error but continue processing other files
                print(f"Error loading Kursliste from {file_path}: {e}")
    
    def _load_kursliste_from_file(self, file_path: Path) -> Kursliste:
        """
        Load a Kursliste from an XML file.
        
        Args:
            file_path: Path to the XML file
            
        Returns:
            Parsed Kursliste object
        """
        try:
            # Use the from_xml_file class method to parse the XML file
            return Kursliste.from_xml_file(file_path)
        except Exception as e:
            # Provide more context about the error
            raise ValueError(f"Error parsing Kursliste from {file_path}: {str(e)}") from e
        
    def get_kurslisten_for_year(self, tax_year: int) -> List[Kursliste]:
        """
        Get all Kursliste instances for a specific tax year.
        
        Args:
            tax_year: The tax year to retrieve Kurslisten for
            
        Returns:
            List of Kursliste objects for the specified year
        """
        return self.kurslisten.get(tax_year, [])
    
    
    def get_available_years(self) -> List[int]:
        """
        Get a list of all tax years for which Kurslisten are available.
        
        Returns:
            List of available tax years, sorted
        """
        return sorted(self.kurslisten.keys())
        
    def get_security_price(self, tax_year: int, isin: str, date: Optional[datetime.date] = None) -> Optional[Decimal]:
        """
        Get the price of a security for a specific tax year and ISIN.
        
        Args:
            tax_year: The tax year to retrieve the price for
            isin: The ISIN of the security
            date: Optional specific date to get price for, defaults to latest available
            
        Returns:
            Price in CHF if available, otherwise None
        """
        # Get all Kurslisten for the specified year
        kurslisten = self.get_kurslisten_for_year(tax_year)
        if not kurslisten:
            return None
            
        # Look for the security in all Kurslisten
        for kursliste in kurslisten:
            security = kursliste.get_security_by_isin(isin)
            if security and security.prices:
                # If a specific date is requested, try to get that price
                if date:
                    price_info = kursliste.get_price_at_date(security, date)
                    if price_info:
                        # Return price in CHF if available, otherwise the original price
                        return price_info.priceInCHF or price_info.price
                # Otherwise return the most recent price
                latest_price = max(security.prices, key=lambda p: p.date)
                return latest_price.priceInCHF or latest_price.price
                
        return None
