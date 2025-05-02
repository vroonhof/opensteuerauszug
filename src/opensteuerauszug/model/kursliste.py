"""
Model for the Swiss "Kursliste" (price list) format.

The Kursliste is a standardized format used by Swiss financial institutions
to report security prices for tax purposes.
"""

import os
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import Annotated

from opensteuerauszug.model.ech0196 import (
    BaseXmlModel,
    SecurityCategory,
    SecurityType,
    check_positive,
)


class PriceType(str, Enum):
    """Type of price quotation."""
    
    CLOSING = "CLOSING"  # Closing price
    AVERAGE = "AVERAGE"  # Average price
    BID = "BID"          # Bid price
    ASK = "ASK"          # Ask price
    MID = "MID"          # Mid price
    NAV = "NAV"          # Net asset value
    OTHER = "OTHER"      # Other price type


class PriceSource(str, Enum):
    """Source of the price information."""
    
    SIX = "SIX"          # SIX Swiss Exchange
    BLOOMBERG = "BLOOMBERG"  # Bloomberg
    REUTERS = "REUTERS"  # Reuters
    TELEKURS = "TELEKURS"  # Telekurs
    BANK = "BANK"        # Bank's own valuation
    OTHER = "OTHER"      # Other source


class Currency(str, Enum):
    """ISO 4217 currency codes for the most common currencies."""
    
    CHF = "CHF"  # Swiss Franc
    EUR = "EUR"  # Euro
    USD = "USD"  # US Dollar
    GBP = "GBP"  # British Pound
    JPY = "JPY"  # Japanese Yen
    AUD = "AUD"  # Australian Dollar
    CAD = "CAD"  # Canadian Dollar
    CNY = "CNY"  # Chinese Yuan
    DKK = "DKK"  # Danish Krone
    HKD = "HKD"  # Hong Kong Dollar
    NOK = "NOK"  # Norwegian Krone
    NZD = "NZD"  # New Zealand Dollar
    SEK = "SEK"  # Swedish Krona
    SGD = "SGD"  # Singapore Dollar
    ZAR = "ZAR"  # South African Rand


class SecurityIdentifier(BaseModel):
    """Identifiers for a security."""
    
    valorNumber: Optional[str] = Field(
        None, 
        description="Swiss valor number",
        max_length=12,
        pattern=r"^\d+$"
    )
    isin: Optional[str] = Field(
        None, 
        description="International Securities Identification Number",
        max_length=12,
        pattern=r"^[A-Z]{2}[A-Z0-9]{9}\d$"
    )
    ticker: Optional[str] = Field(
        None, 
        description="Ticker symbol",
        max_length=20
    )
    cusip: Optional[str] = Field(
        None, 
        description="Committee on Uniform Security Identification Procedures number",
        max_length=9,
        pattern=r"^[A-Z0-9]{9}$"
    )
    sedol: Optional[str] = Field(
        None, 
        description="Stock Exchange Daily Official List number",
        max_length=7,
        pattern=r"^[A-Z0-9]{7}$"
    )
    wkn: Optional[str] = Field(
        None, 
        description="Wertpapierkennnummer (German security identification code)",
        max_length=6,
        pattern=r"^[A-Z0-9]{6}$"
    )
    
    model_config = {
        "validate_assignment": True
    }


class SecurityPrice(BaseModel):
    """Price information for a security at a specific date."""
    
    date: date = Field(..., description="Date of the price")
    price: Decimal = Field(..., description="Price value", ge=0)
    currency_code: Currency = Field(..., description="Currency of the price", alias="currency")
    priceType: PriceType = Field(..., description="Type of price")
    source: PriceSource = Field(..., description="Source of the price information")
    exchangeRate: Optional[Decimal] = Field(
        None, 
        description="Exchange rate to CHF if price is in foreign currency",
        ge=0
    )
    priceInCHF: Optional[Decimal] = Field(
        None, 
        description="Price converted to CHF",
        ge=0
    )
    
    model_config = {
        "validate_assignment": True
    }


class KurslisteSecurity(BaseModel):
    """Security entry in the Kursliste."""
    
    name: Annotated[str, StringConstraints(max_length=255)] = Field(
        ..., 
        description="Name of the security"
    )
    identifiers: SecurityIdentifier = Field(
        ..., 
        description="Identifiers for the security"
    )
    category: SecurityCategory = Field(
        ..., 
        description="Category of the security"
    )
    security_type: Optional[SecurityType] = Field(
        None, 
        description="Type of the security",
        alias="type"
    )
    nominalValue: Optional[Decimal] = Field(
        None, 
        description="Nominal value of the security",
        ge=0
    )
    nominal_currency_code: Optional[Currency] = Field(
        None, 
        description="Currency of the nominal value",
        alias="nominalCurrency"
    )
    prices: List[SecurityPrice] = Field(
        default_factory=list,
        description="Historical prices for the security"
    )
    
    model_config = {
        "validate_assignment": True
    }


class KurslisteMetadata(BaseModel):
    """Metadata for the Kursliste."""
    
    issuer: Annotated[str, StringConstraints(max_length=255)] = Field(
        ..., 
        description="Issuing institution"
    )
    issueDate: date = Field(
        ..., 
        description="Date when the Kursliste was issued"
    )
    validForTaxYear: int = Field(
        ..., 
        description="Tax year for which this Kursliste is valid",
        ge=1900,
        le=2100
    )
    version: str = Field(
        "1.0", 
        description="Version of the Kursliste format"
    )
    
    model_config = {
        "validate_assignment": True
    }


class Kursliste(BaseModel):
    """
    Model for the Swiss "Kursliste" (price list).
    
    The Kursliste contains security prices used for tax purposes.
    """
    
    metadata: KurslisteMetadata = Field(
        ..., 
        description="Metadata about this Kursliste"
    )
    securities: List[KurslisteSecurity] = Field(
        default_factory=list,
        description="List of securities with their prices"
    )
    
    model_config = {
        "validate_assignment": True
    }
    
    def get_security_by_isin(self, isin: str) -> Optional[KurslisteSecurity]:
        """Get a security by its ISIN."""
        for security in self.securities:
            if security.identifiers.isin == isin:
                return security
        return None
    
    def get_security_by_valor(self, valor: str) -> Optional[KurslisteSecurity]:
        """Get a security by its valor number."""
        for security in self.securities:
            if security.identifiers.valorNumber == valor:
                return security
        return None
    
    def get_price_at_date(self, security: KurslisteSecurity, target_date: date) -> Optional[SecurityPrice]:
        """
        Get the price closest to the target date, preferring earlier dates.
        Returns None if no price is available before or on the target date.
        """
        valid_prices = [p for p in security.prices if p.date <= target_date]
        if not valid_prices:
            return None
        return max(valid_prices, key=lambda p: p.date)


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
        # This is a placeholder for actual XML parsing logic
        # In a real implementation, this would parse the XML into the Kursliste model
        
        # For now, we'll create a simple Kursliste with metadata from the filename
        filename = file_path.stem
        parts = filename.split('_')
        
        # Extract year from filename (assuming format like "kursliste_2023_...")
        year = None
        for part in parts:
            if part.isdigit() and len(part) == 4 and 1900 <= int(part) <= 2100:
                year = int(part)
                break
        
        if year is None:
            # Default to current year if we can't extract from filename
            year = date.today().year
        
        # Create a basic Kursliste with metadata
        return Kursliste(
            metadata=KurslisteMetadata(
                issuer="Extracted from " + file_path.name,
                issueDate=date.today(),
                validForTaxYear=year
            ),
            securities=[]
        )
    
    def get_kurslisten_for_year(self, tax_year: int) -> List[Kursliste]:
        """
        Get all Kursliste instances for a specific tax year.
        
        Args:
            tax_year: The tax year to retrieve Kurslisten for
            
        Returns:
            List of Kursliste objects for the specified year
        """
        return self.kurslisten.get(tax_year, [])
    
    def get_security_price(self, 
                          tax_year: int, 
                          isin: Optional[str] = None,
                          valor: Optional[str] = None,
                          price_date: Optional[date] = None) -> Optional[SecurityPrice]:
        """
        Find a security price across all Kurslisten for a given year.
        
        Args:
            tax_year: Tax year to search in
            isin: ISIN of the security (optional)
            valor: Valor number of the security (optional)
            price_date: Date for which to get the price (defaults to Dec 31 of tax year)
            
        Returns:
            SecurityPrice if found, None otherwise
        """
        if isin is None and valor is None:
            raise ValueError("Either ISIN or valor must be provided")
        
        # Default to December 31st of the tax year if no date provided
        if price_date is None:
            price_date = date(tax_year, 12, 31)
        
        kurslisten = self.get_kurslisten_for_year(tax_year)
        
        for kursliste in kurslisten:
            security = None
            
            if isin is not None:
                security = kursliste.get_security_by_isin(isin)
            
            if security is None and valor is not None:
                security = kursliste.get_security_by_valor(valor)
            
            if security is not None:
                price = kursliste.get_price_at_date(security, price_date)
                if price is not None:
                    return price
        
        return None
    
    def get_available_years(self) -> List[int]:
        """
        Get a list of all tax years for which Kurslisten are available.
        
        Returns:
            List of available tax years, sorted
        """
        return sorted(self.kurslisten.keys())
