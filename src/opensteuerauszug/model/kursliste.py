"""
Model for the Swiss "Kursliste" (price list) format.

The Kursliste is a standardized format used by Swiss financial institutions
to report security prices for tax purposes.
"""

import os
import xml.etree.ElementTree as ET
import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import Annotated
from pydantic_xml import BaseXmlModel as PydanticXmlModel, element, attr

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


class SecurityIdentifier(PydanticXmlModel, tag="identifiers"):
    """Identifiers for a security."""
    
    valorNumber: Optional[str] = element(
        tag="valorNumber",
        default=None, 
        description="Swiss valor number",
        max_length=12,
        pattern=r"^\d+$"
    )
    isin: Optional[str] = element(
        tag="isin",
        default=None, 
        description="International Securities Identification Number",
        max_length=12,
        pattern=r"^[A-Z]{2}[A-Z0-9]{9}\d$"
    )
    ticker: Optional[str] = element(
        tag="ticker",
        default=None, 
        description="Ticker symbol",
        max_length=20
    )
    cusip: Optional[str] = element(
        tag="cusip",
        default=None, 
        description="Committee on Uniform Security Identification Procedures number",
        max_length=9,
        pattern=r"^[A-Z0-9]{9}$"
    )
    sedol: Optional[str] = element(
        tag="sedol",
        default=None, 
        description="Stock Exchange Daily Official List number",
        max_length=7,
        pattern=r"^[A-Z0-9]{7}$"
    )
    wkn: Optional[str] = element(
        tag="wkn",
        default=None, 
        description="Wertpapierkennnummer (German security identification code)",
        max_length=6,
        pattern=r"^[A-Z0-9]{6}$"
    )
    
    model_config = {
        "validate_assignment": True
    }


class SecurityPrice(PydanticXmlModel, tag="price"):
    """Price information for a security at a specific datetime.date."""
    
    date: datetime.date = element(tag="date", description="Date of the price")
    price: Decimal = element(tag="value", description="Price value", ge=0)
    currency_code: Currency = element(tag="currencyCode", description="Currency of the price")
    price_type: PriceType = element(tag="priceType", description="Type of price")
    source: PriceSource = element(tag="source", description="Source of the price information")
    exchangeRate: Optional[Decimal] = element(
        tag="exchangeRate",
        default=None, 
        description="Exchange rate to CHF if price is in foreign currency",
        ge=0
    )
    priceInCHF: Optional[Decimal] = element(
        tag="priceInCHF",
        default=None, 
        description="Price converted to CHF",
        ge=0
    )
    
    model_config = {
        "validate_assignment": True
    }


class KurslisteSecurity(PydanticXmlModel, tag="security"):
    """Security entry in the Kursliste."""
    
    name: Annotated[str, StringConstraints(max_length=255)] = element(
        tag="name", 
        description="Name of the security"
    )
    identifiers: SecurityIdentifier = element()
    category: SecurityCategory = element(
        tag="category", 
        description="Category of the security"
    )
    security_type: Optional[SecurityType] = element(
        tag="securityType",
        default=None, 
        description="Type of the security"
    )
    nominalValue: Optional[Decimal] = element(
        tag="nominalValue",
        default=None, 
        description="Nominal value of the security",
        ge=0
    )
    nominal_currency_code: Optional[Currency] = element(
        tag="nominalCurrencyCode",
        default=None, 
        description="Currency of the nominal value"
    )
    prices: List[SecurityPrice] = element(
        tag="prices",
        default_factory=list,
        description="Historical prices for the security"
    )
    
    model_config = {
        "validate_assignment": True
    }


class KurslisteMetadata(PydanticXmlModel, tag="metadata"):
    """Metadata for the Kursliste."""
    
    issuer: Annotated[str, StringConstraints(max_length=255)] = element(
        tag="issuer", 
        description="Issuing institution"
    )
    issueDate: datetime.date = element(
        tag="issueDate", 
        description="Date when the Kursliste was issued"
    )
    validForTaxYear: int = element(
        tag="validForTaxYear", 
        description="Tax year for which this Kursliste is valid",
        ge=1900,
        le=2100
    )
    version: str = element(
        tag="version",
        default="1.0", 
        description="Version of the Kursliste format"
    )
    
    model_config = {
        "validate_assignment": True
    }


# Define the namespace URI
KURSLISTE_NS = "http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste"

class Kursliste(PydanticXmlModel, tag="kursliste", ns=KURSLISTE_NS):
    """
    Model for the Swiss "Kursliste" (price list).
    
    The Kursliste contains security prices used for tax purposes.
    """
    
    metadata: KurslisteMetadata = element()
    securities: List[KurslisteSecurity] = element(
        tag="securities",
        default_factory=list,
        description="List of securities with their prices"
    )
    
    model_config = {
        "validate_assignment": True
    }
    
    @classmethod
    def from_xml_file(cls, file_path: Path) -> "Kursliste":
        """Load a Kursliste from an XML file."""
        with open(file_path, "rb") as f:
            xml_content = f.read()
        return cls.from_xml(xml_content)
    
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
    
    def get_price_at_date(self, security: KurslisteSecurity, target_date: datetime.date) -> Optional[SecurityPrice]:
        """
        Get the price closest to the target datetime.date, preferring earlier datetime.dates.
        Returns None if no price is available before or on the target datetime.date.
        """
        valid_prices = [p for p in security.prices if p.date <= target_date]
        if not valid_prices:
            return None
        return max(valid_prices, key=lambda p: p.date)


