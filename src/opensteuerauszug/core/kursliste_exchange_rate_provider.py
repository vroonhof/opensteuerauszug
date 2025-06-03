# Removed: from functools import lru_cache
# Removed: from ..model.kursliste import Kursliste, ExchangeRateYearEnd, ExchangeRateMonthly, ExchangeRate
# Removed: from .kursliste_db_reader import KurslisteDBReader
from abc import ABC, abstractmethod # Keep if ExchangeRateProvider is ABC
from decimal import Decimal
from typing import Optional
from datetime import date

from .exchange_rate_provider import ExchangeRateProvider
from ..core.kursliste_manager import KurslisteManager
from .kursliste_accessor import KurslisteAccessor # Added import

class KurslisteExchangeRateProvider(ExchangeRateProvider):
    def __init__(self, kursliste_manager: KurslisteManager):
        self.kursliste_manager = kursliste_manager

    def get_exchange_rate(self, currency: str, reference_date: date, path_prefix_for_log: Optional[str] = None) -> Decimal:
        if currency == "CHF":
            return Decimal("1")

        tax_year = reference_date.year
        # Expect KurslisteManager.get_kurslisten_for_year to return Optional[KurslisteAccessor]
        accessor = self.kursliste_manager.get_kurslisten_for_year(tax_year)

        if accessor:
            # KurslisteAccessor.get_exchange_rate is already cached
            rate = accessor.get_exchange_rate(currency, reference_date)
            if rate is not None:
                return rate
        
        # If accessor is None, or accessor.get_exchange_rate returned None
        raise ValueError(f"Exchange rate for {currency} on {reference_date} not found in any Kursliste source for tax year {tax_year}.")

# Removed _get_exchange_rate_from_xml_kursliste method
