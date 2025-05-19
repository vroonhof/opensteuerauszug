from .minimal_tax_value import MinimalTaxValueCalculator
from .base import CalculationMode
from ..core.exchange_rate_provider import ExchangeRateProvider


class KurslisteTaxValueCalculator(MinimalTaxValueCalculator):
    """
    Calculator that uses a Kursliste (official tax value list) to determine
    tax values for securities.
    """
    def __init__(self, mode: CalculationMode, exchange_rate_provider: ExchangeRateProvider):
        super().__init__(mode, exchange_rate_provider)
        print(f"KurslisteTaxValueCalculator initialized with mode: {mode.value} and provider: {type(exchange_rate_provider).__name__}")

