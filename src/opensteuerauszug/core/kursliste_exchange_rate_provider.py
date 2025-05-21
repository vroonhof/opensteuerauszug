from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional
from datetime import date

from .exchange_rate_provider import ExchangeRateProvider # Assuming this is the base class
from ..core.kursliste_manager import KurslisteManager
from ..model.kursliste import Kursliste, ExchangeRateYearEnd, ExchangeRateMonthly, ExchangeRate # Keep relevant model imports

class KurslisteExchangeRateProvider(ExchangeRateProvider):
    def __init__(self, kursliste_manager: KurslisteManager):
        self.kursliste_manager = kursliste_manager

    def get_exchange_rate(self, currency: str, reference_date: date, path_prefix_for_log: Optional[str] = None) -> Decimal:
        if currency == "CHF":
            return Decimal("1")

        tax_year = reference_date.year
        kurslisten = self.kursliste_manager.get_kurslisten_for_year(tax_year)

        if not kurslisten:
            raise ValueError(f"No Kursliste found for tax year {tax_year}.")

        for kursliste_instance in kurslisten:
            # End-of-Year Logic
            if reference_date.month == 12 and reference_date.day == 31:
                for rate in kursliste_instance.exchangeRatesYearEnd:
                    if rate.currency == currency and rate.year == tax_year:
                        if rate.value is not None:
                            return rate.value
                        elif rate.valueMiddle is not None:
                            return rate.valueMiddle
            
            # Monthly Average Logic
            month_str = f"{reference_date.month:02d}"
            for rate in kursliste_instance.exchangeRatesMonthly:
                if rate.currency == currency and rate.year == tax_year and rate.month == month_str:
                    if rate.value is not None:
                        return rate.value

            # Daily Rate Logic
            for rate in kursliste_instance.exchangeRates:
                if rate.currency == currency and rate.date == reference_date:
                    if rate.value is not None:
                        return rate.value
        
        # If currency not found after checking all kurslisten
        raise ValueError(f"Exchange rate for {currency} on {reference_date} not found in Kursliste for tax year {tax_year}.")
