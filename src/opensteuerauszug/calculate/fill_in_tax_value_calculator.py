from decimal import Decimal

from opensteuerauszug.model.ech0196 import SecurityPayment
from .kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from .base import CalculationMode
from ..core.exchange_rate_provider import ExchangeRateProvider


class FillInTaxValueCalculator(KurslisteTaxValueCalculator):
    """
    Calculator that fills in missing values based on other available data,
    potentially after Kursliste and minimal calculations have been performed.
    """
    def __init__(self, mode: CalculationMode, exchange_rate_provider: ExchangeRateProvider, keep_existing_payments: bool = False):
        super().__init__(mode, exchange_rate_provider, keep_existing_payments=keep_existing_payments)
        print(f"FillInTaxValueCalculator initialized with mode: {mode.value} and provider: {type(exchange_rate_provider).__name__}")

    def _handle_SecurityPayment(self, sec_payment: SecurityPayment, path_prefix: str) -> None:
        """Handles SecurityPayment objects for currency conversion and revenue categorization."""
        
        # TODO: Do not recompute values if set by the KurslisteTaxValueCalculator
        if sec_payment.amountCurrency and sec_payment.paymentDate:
            payment_date = sec_payment.paymentDate
            amount = sec_payment.amount
            
            chf_revenue, rate = self._convert_to_chf(
                amount,
                sec_payment.amountCurrency,
                f"{path_prefix}.exchangeRate",
                payment_date
            )
            self._set_field_value(sec_payment, "exchangeRate", rate, path_prefix)

            if chf_revenue is not None and chf_revenue != Decimal(0): # Only process if there's actual revenue
                if self._current_security_is_type_A is True:
                    self._set_field_value(sec_payment, "grossRevenueA", chf_revenue, path_prefix)
                elif self._current_security_is_type_A is False:
                    self._set_field_value(sec_payment, "grossRevenueB", chf_revenue, path_prefix)
                elif self._current_security_is_type_A is None:
                    raise ValueError(f"SecurityPayment at {path_prefix} has revenue, but parent Security has no country specified to determine Type A/B revenue.")
        else:
            raise ValueError(f"SecurityPayment at {path_prefix} is missing amountCurrency or paymentDate.")
