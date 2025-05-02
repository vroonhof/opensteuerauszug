"""
Model for the Swiss "Kursliste" (price list) format.

The Kursliste is a standardized format used by Swiss financial institutions
to report security prices for tax purposes.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
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
    
    class Config:
        validate_assignment = True


class SecurityPrice(BaseModel):
    """Price information for a security at a specific date."""
    
    date: date = Field(..., description="Date of the price")
    price: Decimal = Field(..., description="Price value", ge=0)
    currency: Currency = Field(..., description="Currency of the price")
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
    
    class Config:
        validate_assignment = True


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
    type: Optional[SecurityType] = Field(
        None, 
        description="Type of the security"
    )
    nominalValue: Optional[Decimal] = Field(
        None, 
        description="Nominal value of the security",
        ge=0
    )
    nominalCurrency: Optional[Currency] = Field(
        None, 
        description="Currency of the nominal value"
    )
    prices: List[SecurityPrice] = Field(
        default_factory=list,
        description="Historical prices for the security"
    )
    
    class Config:
        validate_assignment = True


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
    
    class Config:
        validate_assignment = True


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
    
    class Config:
        validate_assignment = True
    
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
