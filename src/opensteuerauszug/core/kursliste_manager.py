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
        import xml.etree.ElementTree as ET
        
        # Parse the XML file
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # Extract metadata
        metadata_elem = root.find("metadata")
        if metadata_elem is None:
            raise ValueError(f"Missing metadata element in {file_path}")
        
        metadata = KurslisteMetadata(
            issuer=metadata_elem.findtext("issuer", "Unknown"),
            issueDate=datetime.date.fromisoformat(metadata_elem.findtext("issueDate", datetime.date.today().isoformat())),
            validForTaxYear=int(metadata_elem.findtext("validForTaxYear", "2023")),
            version=metadata_elem.findtext("version", "1.0")
        )
        
        # Create Kursliste object
        kursliste = Kursliste(metadata=metadata)
        
        # Extract securities
        securities_elem = root.find("securities")
        if securities_elem is not None:
            for security_elem in securities_elem.findall("security"):
                # Extract security identifiers
                identifiers_elem = security_elem.find("identifiers")
                if identifiers_elem is None:
                    continue
                
                identifiers = SecurityIdentifier(
                    valorNumber=identifiers_elem.findtext("valorNumber"),
                    isin=identifiers_elem.findtext("isin"),
                    ticker=identifiers_elem.findtext("ticker"),
                    cusip=identifiers_elem.findtext("cusip"),
                    sedol=identifiers_elem.findtext("sedol"),
                    wkn=identifiers_elem.findtext("wkn")
                )
                
                # Create security object
                security = KurslisteSecurity(
                    name=security_elem.findtext("name", "Unknown Security"),
                    identifiers=identifiers,
                    category=security_elem.findtext("category", "OTHER"),
                    security_type=security_elem.findtext("securityType")
                )
                
                # Extract prices
                prices_elem = security_elem.find("prices")
                if prices_elem is not None:
                    for price_elem in prices_elem.findall("price"):
                        try:
                            price = SecurityPrice(
                                date=datetime.date.fromisoformat(price_elem.findtext("date", datetime.date.today().isoformat())),
                                price=Decimal(price_elem.findtext("value", "0")),
                                currency_code=price_elem.findtext("currencyCode", "CHF"),
                                price_type=price_elem.findtext("priceType", "CLOSING"),
                                source=price_elem.findtext("source", "OTHER"),
                                exchangeRate=Decimal(price_elem.findtext("exchangeRate", "0")) if price_elem.findtext("exchangeRate") else None,
                                priceInCHF=Decimal(price_elem.findtext("priceInCHF", "0")) if price_elem.findtext("priceInCHF") else None
                            )
                            security.prices.append(price)
                        except (ValueError, TypeError) as e:
                            # Skip invalid prices but continue processing
                            print(f"Error parsing price in {file_path}: {e}")
                
                kursliste.securities.append(security)
        
        return kursliste
        
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
