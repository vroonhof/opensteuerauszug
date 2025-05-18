from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional
from datetime import date

class ExchangeRateProvider(ABC):
    """
    Interface for providing exchange rates against a base currency (implicitly CHF).
    """
    @abstractmethod
    def get_exchange_rate(self, currency: str, reference_date: date, path_prefix_for_log: Optional[str] = None) -> Decimal:
        """
        Returns the exchange rate for the given currency against CHF.
        
        Args:
            currency: The currency code (e.g., \"USD\", \"EUR\").
            reference_date: The date for which the exchange rate is requested.
                            This might be used by implementations to fetch historical rates.
            path_prefix_for_log: An optional string providing context (e.g., a path in the data model) 
                                 for logging purposes by the provider.

        Returns:
            The exchange rate as a Decimal. For example, if 1 USD = 0.9 CHF, this would return 0.9.
            For CHF itself, it should return Decimal(\"1\").
        """
        pass

class DummyExchangeRateProvider(ExchangeRateProvider):
    """
    A dummy implementation of ExchangeRateProvider that returns a fixed rate
    for non-CHF currencies and 1.0 for CHF.
    """
    _CHF_CURRENCY = "CHF"
    _STUB_EXCHANGE_RATE = Decimal("0.5") # Placeholder for non-CHF

    def get_exchange_rate(self, currency: str, reference_date: date, path_prefix_for_log: Optional[str] = None) -> Decimal:
        """
        Returns 1.0 for CHF, and a stub rate for other currencies.
        `reference_date` is used to conform to the interface, but not in the dummy logic itself.
        `path_prefix_for_log` is used in the warning message.
        """
        if currency == self._CHF_CURRENCY:
            return Decimal("1")
        else:
            log_context = f" (Path: {path_prefix_for_log})" if path_prefix_for_log else ""
            print(f"Warning: Using stub exchange rate ({self._STUB_EXCHANGE_RATE}) for currency {currency}{log_context}.")
            # In a real scenario, fetch from Kursliste or other source based on reference_date
            return self._STUB_EXCHANGE_RATE

