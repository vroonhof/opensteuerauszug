from .base import BaseCalculator, CalculationMode
from ..model.ech0196 import (
    TaxStatement,
    BankAccountTaxValue,
    BankAccountPayment,
    LiabilityAccountTaxValue,
    LiabilityAccountPayment,
    SecurityTaxValue,
    Security
)
from ..core.exchange_rate_provider import ExchangeRateProvider
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple, Optional
from datetime import date


class MinimalTaxValueCalculator(BaseCalculator):
    """
    A minimal implementation of a tax value calculator. This computes only simple
    uncontroversial values. Mainly currenty conversions.
    """
    _CHF_CURRENCY = "CHF"

    def __init__(self, mode: CalculationMode, exchange_rate_provider: ExchangeRateProvider):
        super().__init__(mode)
        self.exchange_rate_provider = exchange_rate_provider
        print(f"MinimalTaxValueCalculator initialized with mode: {mode.value} and provider: {type(exchange_rate_provider).__name__}")

    def _convert_to_chf(self, amount: Optional[Decimal], currency: str, path_prefix_for_rate: str, reference_date: date) -> Tuple[Optional[Decimal], Decimal]:
        """
        Converts an amount to CHF using the exchange rate from the provider.
        Returns the CHF amount and the exchange rate used.
        If amount is None, returns None for CHF amount and the determined exchange rate.
        For CHF currency, the original amount is returned and the rate is 1 (no calculation performed by this method directly, provider handles CHF rate).
        No quantization is performed.
        """
        # Get exchange rate from the provider
        exchange_rate = self.exchange_rate_provider.get_exchange_rate(currency, reference_date, path_prefix_for_rate)
        
        if currency == self._CHF_CURRENCY:
            # For CHF, rate is 1 (as per provider) and amount remains unchanged.
            # This explicit check can remain for clarity or be removed if provider guarantees Decimal("1") for CHF.
            return amount, Decimal("1")

        if amount is None:
            return None, exchange_rate

        # Perform conversion without quantization
        chf_amount = amount * exchange_rate
        return chf_amount, exchange_rate

    def calculate(self, tax_statement: TaxStatement) -> TaxStatement:
        """
        Processes the tax statement.
        For this stub version, it currently relies on the base class implementation
        which might iterate through the model but won't perform specific calculations
        unless _handle_... methods are implemented.
        """
        # Perform pre-calculation checks or setup
        super().calculate(tax_statement) # Calls _process_tax_statement and then _process_model
        # Perform post-calculation actions or logging
        print(f"MinimalTaxValueCalculator: Finished processing. Errors: {len(self.errors)}, Modified fields: {len(self.modified_fields)}")
        return tax_statement

    def _handle_BankAccountTaxValue(self, ba_tax_value: BankAccountTaxValue, path_prefix: str) -> None:
        """Handles BankAccountTaxValue objects during traversal."""
        if ba_tax_value.balanceCurrency: # We need currency to determine/set the rate
            if ba_tax_value.referenceDate is None:
                raise ValueError(f"BankAccountTaxValue at {path_prefix} has balanceCurrency but no referenceDate. Cannot determine exchange rate.")
            
            chf_value, rate = self._convert_to_chf(
                ba_tax_value.balance, # _convert_to_chf handles amount=None
                ba_tax_value.balanceCurrency,
                f"{path_prefix}.exchangeRate", 
                ba_tax_value.referenceDate
            )
            # Set rate regardless of whether balance was present
            self._set_field_value(ba_tax_value, "exchangeRate", rate, path_prefix)
            
            if chf_value is not None: # Only set value if it could be calculated
                self._set_field_value(ba_tax_value, "value", chf_value, path_prefix)
        # If balanceCurrency is None, we can't do much for currency conversion.

    def _handle_BankAccountPayment(self, ba_payment: BankAccountPayment, path_prefix: str) -> None:
        """Handles BankAccountPayment objects during traversal."""
        if ba_payment.amountCurrency:
            if ba_payment.paymentDate is None:
                raise ValueError(f"BankAccountPayment at {path_prefix} has amountCurrency but no paymentDate. Cannot determine exchange rate.")
            # Get the rate to set the exchangeRate field.
            # _convert_to_chf handles amount being None, returning the rate.
            _, rate = self._convert_to_chf(
                ba_payment.amount, 
                ba_payment.amountCurrency,
                f"{path_prefix}.exchangeRate",
                ba_payment.paymentDate
            )
            self._set_field_value(ba_payment, "exchangeRate", rate, path_prefix)
        # Note: This calculator does not derive grossRevenueA/B from amount * rate.
        # It assumes grossRevenueA/B are either pre-filled or handled by another calculator.

    def _handle_LiabilityAccountTaxValue(self, lia_tax_value: LiabilityAccountTaxValue, path_prefix: str) -> None:
        """Handles LiabilityAccountTaxValue objects during traversal."""
        if lia_tax_value.balanceCurrency:
            if lia_tax_value.referenceDate is None:
                raise ValueError(f"LiabilityAccountTaxValue at {path_prefix} has balanceCurrency but no referenceDate. Cannot determine exchange rate.")

            chf_value, rate = self._convert_to_chf(
                lia_tax_value.balance,
                lia_tax_value.balanceCurrency,
                f"{path_prefix}.exchangeRate",
                lia_tax_value.referenceDate
            )
            self._set_field_value(lia_tax_value, "exchangeRate", rate, path_prefix)
            
            if chf_value is not None:
                self._set_field_value(lia_tax_value, "value", chf_value, path_prefix)

    def _handle_LiabilityAccountPayment(self, lia_payment: LiabilityAccountPayment, path_prefix: str) -> None:
        """Handles LiabilityAccountPayment objects during traversal."""
        if lia_payment.amountCurrency:
            if lia_payment.paymentDate is None:
                raise ValueError(f"LiabilityAccountPayment at {path_prefix} has amountCurrency but no paymentDate. Cannot determine exchange rate.")

            _, rate = self._convert_to_chf(
                lia_payment.amount,
                lia_payment.amountCurrency,
                f"{path_prefix}.exchangeRate",
                lia_payment.paymentDate
            )
            self._set_field_value(lia_payment, "exchangeRate", rate, path_prefix)

    def _handle_SecurityTaxValue(self, sec_tax_value: SecurityTaxValue, path_prefix: str) -> None:
        """Handles SecurityTaxValue objects for currency conversion."""
        # This calculator converts an existing 'value' (assumed to be in 'balanceCurrency') to CHF 
        # and sets 'exchangeRate'. It does not derive 'value' from quantity/quotation.

        has_balance_currency = hasattr(sec_tax_value, 'balanceCurrency') and sec_tax_value.balanceCurrency
        has_value = hasattr(sec_tax_value, 'value') and getattr(sec_tax_value, 'value') is not None

        if has_balance_currency:
            value_to_convert = getattr(sec_tax_value, 'value', None)
            ref_date = getattr(sec_tax_value, 'referenceDate', None)

            if ref_date is None:
                raise ValueError(f"SecurityTaxValue at {path_prefix} has balanceCurrency but no referenceDate. Cannot determine exchange rate.")

            chf_value, rate = self._convert_to_chf(
                value_to_convert,
                sec_tax_value.balanceCurrency,
                f"{path_prefix}.exchangeRate",
                ref_date
            )
            
            self._set_field_value(sec_tax_value, "exchangeRate", rate, path_prefix)
            
            # Only attempt to set 'value' if the original value was present (chf_value is not None)
            if chf_value is not None:
                self._set_field_value(sec_tax_value, "value", chf_value, path_prefix)
            # If value_to_convert was None, chf_value will be None. 
            # _set_field_value handles VERIFY/FILL/OVERWRITE modes appropriately for None.

        elif has_value and not has_balance_currency:
            # If there's a value but no currency, this is an error as we cannot process it.
            raise ValueError(f"SecurityTaxValue at {path_prefix} has a 'value' but no 'balanceCurrency'. Cannot perform currency conversion or set exchange rate accurately.")
        # Other fields like quotationCurrency, quantity, quotationType, nominal are not used
        # by this minimal calculator for converting an existing 'value' field. They would be handled 
        # by a more comprehensive calculator if the task was to derive 'value'.
