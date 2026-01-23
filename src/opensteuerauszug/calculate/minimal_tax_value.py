from .base import BaseCalculator, CalculationMode, CalculationError
from ..model.ech0196 import (
    TaxStatement,
    BankAccount,  # Added BankAccount
    BankAccountTaxValue,
    BankAccountPayment,
    LiabilityAccountTaxValue,
    LiabilityAccountPayment,
    Security,  # Added Security
    SecurityTaxValue,
    SecurityPayment,  # Added SecurityPayment
)
from ..core.exchange_rate_provider import ExchangeRateProvider
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from ..core.constants import WITHHOLDING_TAX_RATE
from typing import Tuple, Optional, List
from datetime import date
import logging


class MinimalTaxValueCalculator(BaseCalculator):
    """
    A minimal implementation of a tax value calculator. This computes only simple
    uncontroversial values. Mainly currenty conversions.
    """
    _CHF_CURRENCY = "CHF"
    _current_account_is_type_A: Optional[bool]
    _current_security_is_type_A: Optional[bool]
    _current_security_country: Optional[str]

    def __init__(self, mode: CalculationMode, exchange_rate_provider: ExchangeRateProvider, keep_existing_payments: bool = False):
        super().__init__(mode)
        self.exchange_rate_provider = exchange_rate_provider
        self.keep_existing_payments = keep_existing_payments
        self._current_account_is_type_A = None
        self._current_security_is_type_A = None
        self._current_security_country = None
        self.logger = logging.getLogger(__name__)
        self.logger.info(
            "MinimalTaxValueCalculator initialized with mode: %s and provider: %s",
            mode.value,
            type(exchange_rate_provider).__name__,
        )

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
        """
        self._current_account_is_type_A = None  # Reset state at the beginning of a calculation run
        self._current_security_is_type_A = None  # Reset state
        self._current_security_country = None  # Reset state
        super().calculate(tax_statement)
        self.logger.info(
            "MinimalTaxValueCalculator: Finished processing. Errors: %s, Modified fields: %s",
            len(self.errors),
            len(self.modified_fields),
        )
        return tax_statement

    def _handle_BankAccount(self, bank_account: BankAccount, path_prefix: str) -> None:
        """Sets the type A/B context based on the bank account's institution country code."""
        country_code = bank_account.bankAccountCountry

        if country_code:
            if country_code == "CH":
                self._current_account_is_type_A = True
            else:
                self._current_account_is_type_A = False
        else:
            self._current_account_is_type_A = None
        
        # BaseCalculator does not have a _handle_BankAccount method.

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
        else:
            raise ValueError(f"BankAccountTaxValue at {path_prefix} has no balanceCurrency. Cannot determine exchange rate.")

    def _handle_BankAccountPayment(self, ba_payment: BankAccountPayment, path_prefix: str) -> None:
        """Handles BankAccountPayment objects during traversal."""
        if ba_payment.amountCurrency:
            if ba_payment.paymentDate is None:
                raise ValueError(f"BankAccountPayment at {path_prefix} has amountCurrency but no paymentDate. Cannot determine exchange rate.")
            
            chf_revenue, rate = self._convert_to_chf(
                ba_payment.amount, 
                ba_payment.amountCurrency,
                f"{path_prefix}.exchangeRate",
                ba_payment.paymentDate
            )
            self._set_field_value(ba_payment, "exchangeRate", rate, path_prefix)

            gross_revenue_a = Decimal(0)
            gross_revenue_b = Decimal(0)
            withholding_tax = Decimal(0)

            if chf_revenue is not None and chf_revenue > 0: # Only process if there's actual revenue
                if self._current_account_is_type_A is True:
                    gross_revenue_a = chf_revenue
                    # Calculate and set withholding tax for Type A revenue
                    withholding_tax = (
                        chf_revenue * WITHHOLDING_TAX_RATE
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                elif self._current_account_is_type_A is False:
                    gross_revenue_b = chf_revenue
                elif self._current_account_is_type_A is None:
                    # If country was not set on parent BankAccount and there's revenue, it's an error.
                    raise ValueError(f"BankAccountPayment at {path_prefix} has revenue, but parent BankAccount has no country specified to determine Type A/B revenue.")

            self._set_field_value(ba_payment, "grossRevenueA", gross_revenue_a, path_prefix)
            self._set_field_value(ba_payment, "grossRevenueB", gross_revenue_b, path_prefix)
            self._set_field_value(ba_payment, "withHoldingTaxClaim", withholding_tax, path_prefix)

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

            chf_amount, rate = self._convert_to_chf(
                lia_payment.amount,
                lia_payment.amountCurrency,
                f"{path_prefix}.exchangeRate",
                lia_payment.paymentDate
            )
            self._set_field_value(lia_payment, "exchangeRate", rate, path_prefix)

            if chf_amount is not None and chf_amount != Decimal(0):
                # Liabilities are considered Type B for revenue purposes
                self._set_field_value(lia_payment, "grossRevenueB", chf_amount, path_prefix)

    def _handle_Security(self, security: Security, path_prefix: str) -> None:
        """Sets the type A/B context based on the security's country of taxation."""
        country_code = security.country
        self._current_security_country = country_code

        if country_code:
            if country_code == "CH":
                self._current_security_is_type_A = True
            else:
                self._current_security_is_type_A = False
        else:
            self._current_security_is_type_A = None

        # BaseCalculator does not have a _handle_Security method.

        # After the basic context is set up compute the expected payments
        # from the Kursliste (empty for this minimal calculator).
        self.computePayments(security, path_prefix)

    def _handle_SecurityTaxValue(self, sec_tax_value: SecurityTaxValue, path_prefix: str) -> None:
        """Handles SecurityTaxValue objects for currency conversion."""
        # This calculator converts an existing 'value' (assumed to be in 'balanceCurrency') to CHF 
        # and sets 'exchangeRate'. It does not derive 'value' from quantity/quotation.

        has_balance_currency = hasattr(sec_tax_value, 'balanceCurrency') and sec_tax_value.balanceCurrency

        if has_balance_currency:
            value_to_convert = sec_tax_value.balance
            ref_date = sec_tax_value.referenceDate

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

        elif sec_tax_value.balance and not has_balance_currency:
            # If there's a value but no currency, this is an error as we cannot process it.
            raise ValueError(f"SecurityTaxValue at {path_prefix} has a 'value' but no 'balanceCurrency'. Cannot perform currency conversion or set exchange rate accurately.")

    def _handle_SecurityPayment(self, sec_payment: SecurityPayment, path_prefix: str) -> None:
        """Handles SecurityPayment objects for currency conversion and revenue categorization."""
        # In the base implementation all payments will have been cleared (outside of debugging and verify mode)
        # Avoid doing computation here to handle broken inputs on verify + minimal mode.
        if self._current_security_country == "US":
            if sec_payment.additionalWithHoldingTaxUSA is None:
                self._set_field_value(
                    sec_payment,
                    "additionalWithHoldingTaxUSA",
                    Decimal("0"),
                    path_prefix,
                )

    def computePayments(self, security: Security, path_prefix: str) -> None:
        """Compute and set payments for a security.

        This minimal implementation passes an empty list to ``setKurslistePayments``.
        Subclasses can override to provide actual computation.
        """
        self.setKurslistePayments(security, [], path_prefix)

    def setKurslistePayments(self, security: Security, payments: List[SecurityPayment], path_prefix: str) -> None:
        """Set or verify the list of payments derived from the Kursliste.

        In ``OVERWRITE`` mode the given ``payments`` are written to ``security.payment``.
        In ``VERIFY`` mode the method checks that the payments already present on
        ``security`` are equal to ``payments`` and records a ``CalculationError``
        otherwise. ``FILL`` behaves like ``VERIFY`` but writes the payments if the
        list on the security is empty.
        """

        # If no payments are provided there is nothing to check or set.
        # if payments == None:
        #    return

        field_path = f"{path_prefix}.payment" if path_prefix else "payment"
        current = security.payment

        if self.mode == CalculationMode.OVERWRITE:
            if self.keep_existing_payments:
                payments = current + payments
            security.payment = sorted(payments, key=lambda p: p.paymentDate)
            self.modified_fields.add(field_path)
            return

        if self.mode == CalculationMode.FILL and not current:
            security.payment = sorted(payments, key=lambda p: p.paymentDate)
            self.modified_fields.add(field_path)
            return

        if self.mode not in (CalculationMode.VERIFY, CalculationMode.FILL):
            return

        if self.keep_existing_payments:
            # For debugging we force the list to be the merge even when verifying so
            # we can look at the rendered copy.
            merged = current + payments
            security.payment = sorted(merged, key=lambda p: p.paymentDate)
        
        # Detailed comparison for VERIFY and FILL (with existing payments)
        current_by_date = defaultdict(list)
        for p in current:
            current_by_date[p.paymentDate].append(p)

        expected_by_date = defaultdict(list)
        for p in payments:
            expected_by_date[p.paymentDate].append(p)

        all_dates = sorted(list(set(current_by_date.keys()) | set(expected_by_date.keys())))

        for d in all_dates:
            current_on_date = current_by_date.get(d, [])
            expected_on_date = expected_by_date.get(d, [])

            if not current_on_date:
                for p in expected_on_date:
                    self.errors.append(CalculationError(f"{field_path}.date={d}", p, None))
                continue

            if not expected_on_date:
                for p in current_on_date:
                    self.errors.append(CalculationError(f"{field_path}.date={d}", None, p))
                continue

            # Try to match payments on the same date
            unmatched_current = list(current_on_date)
            remaining_expected = []
            for p_expected in expected_on_date:
                try:
                    unmatched_current.remove(p_expected)
                except ValueError:
                    remaining_expected.append(p_expected)

            if len(unmatched_current) == len(remaining_expected):
                # To provide a stable diff, sort if possible.
                try:
                    unmatched_current.sort()
                    remaining_expected.sort()
                except TypeError:
                    pass  # Not sortable, compare as is.

                for p_curr, p_exp in zip(unmatched_current, remaining_expected):
                    p_curr_vars = vars(p_curr)
                    p_exp_vars = vars(p_exp)
                    all_keys = sorted(list(set(p_curr_vars.keys()) | set(p_exp_vars.keys())))
                    for key in all_keys:
                        v_curr = p_curr_vars.get(key)
                        v_exp = p_exp_vars.get(key)
                        if v_curr != v_exp:
                            # Create one error per differing field.
                            error_path = f"{field_path}.date={d}.{key}"
                            self.errors.append(CalculationError(error_path, v_exp, v_curr))
            else:
                for p in unmatched_current:
                    self.errors.append(CalculationError(f"{field_path}.date={d}", None, p))
                for p in remaining_expected:
                    self.errors.append(CalculationError(f"{field_path}.date={d}", p, None))
