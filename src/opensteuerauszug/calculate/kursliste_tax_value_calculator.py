from decimal import Decimal
from typing import Optional, List

from ..core.exchange_rate_provider import ExchangeRateProvider
from ..core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from ..core.kursliste_manager import KurslisteManager
from ..model.ech0196 import Security, SecurityTaxValue, SecurityPayment
from ..core.position_reconciler import PositionReconciler
from ..core.constants import WITHHOLDING_TAX_RATE
from .base import CalculationMode
from .minimal_tax_value import MinimalTaxValueCalculator


class KurslisteTaxValueCalculator(MinimalTaxValueCalculator):
    """
    Calculator that uses a Kursliste (official tax value list) to determine
    tax values for securities.
    """

    def __init__(self, mode: CalculationMode, exchange_rate_provider: ExchangeRateProvider, keep_existing_payments: bool = False):
        super().__init__(mode, exchange_rate_provider, keep_existing_payments=keep_existing_payments)
        print(
            f"KurslisteTaxValueCalculator initialized with mode: {mode.value} "
            f"and provider: {type(exchange_rate_provider).__name__}"
        )
        self.kursliste_manager: Optional[KurslisteManager] = None
        if isinstance(exchange_rate_provider, KurslisteExchangeRateProvider):
            self.kursliste_manager = exchange_rate_provider.kursliste_manager
        self._current_kursliste_security = None
        self._missing_kursliste_entries = []

    def calculate(self, tax_statement):
        self._missing_kursliste_entries = []
        result = super().calculate(tax_statement)
        if self._missing_kursliste_entries:
            print("Missing Kursliste entries for securities:")
            for entry in self._missing_kursliste_entries:
                print(f"  - {entry}")
        return result

    def _handle_Security(self, security: Security, path_prefix: str) -> None:
        self._current_kursliste_security = None

        if not self.kursliste_manager:
            return

        lookup_year = None
        if security.taxValue and security.taxValue.referenceDate:
            lookup_year = security.taxValue.referenceDate.year

        if lookup_year is None:
            return

        accessor = self.kursliste_manager.get_kurslisten_for_year(lookup_year)
        if not accessor:
            return

        kl_sec = None
        if security.valorNumber:
            kl_sec = accessor.get_security_by_valor(int(security.valorNumber))
        if not kl_sec and security.isin:
            kl_sec = accessor.get_security_by_isin(security.isin)


        if kl_sec:
            self._current_kursliste_security = kl_sec
            if security.valorNumber is None and kl_sec.valorNumber is not None:
                try:
                    valor_int = int(kl_sec.valorNumber)
                except Exception:
                    valor_int = kl_sec.valorNumber
                self._set_field_value(security, "valorNumber", valor_int, path_prefix)
        else:
            ident = (
                security.isin or f"Valor {security.valorNumber}"
                if security.valorNumber
                else security.securityName
            )
            self._missing_kursliste_entries.append(ident)

        super()._handle_Security(security, path_prefix)

    def _handle_SecurityTaxValue(self, sec_tax_value: SecurityTaxValue, path_prefix: str) -> None:
        if self._current_kursliste_security and self.kursliste_manager:
            ref_date = sec_tax_value.referenceDate
            if ref_date:
                price = self.kursliste_manager.get_security_price(
                    ref_date.year,
                    self._current_kursliste_security.isin or "",
                    price_date=ref_date,
                )
                if price is not None:
                    self._set_field_value(sec_tax_value, "unitPrice", price, path_prefix)
                    value = price * sec_tax_value.quantity
                    self._set_field_value(sec_tax_value, "value", value, path_prefix)
                    self._set_field_value(sec_tax_value, "exchangeRate", Decimal("1"), path_prefix)
                    self._set_field_value(sec_tax_value, "kursliste", True, path_prefix)
                    return

        super()._handle_SecurityTaxValue(sec_tax_value, path_prefix)

    def computePayments(self, security: Security, path_prefix: str) -> None:
        """Compute payments for a security using the Kursliste."""
        if self.mode == CalculationMode.VERIFY:
            return

        if not self.kursliste_manager:
            raise RuntimeError("kursliste_manager is required for Kursliste payments")

        kl_sec = self._current_kursliste_security
        if kl_sec is None:
            super().computePayments(security, path_prefix)
            return

        payments = [p for p in kl_sec.payment if not p.deleted]

        result: List[SecurityPayment] = []

        reconciler = PositionReconciler(list(security.stock), identifier=f"{security.isin or 'SEC'}-payments")

        for pay in payments:
            if not pay.paymentDate:
                continue

            if pay.paymentValueCHF is None:
                raise ValueError(
                    f"Kursliste payment on {pay.paymentDate} for {security.isin or security.securityName} missing paymentValueCHF"
                )

            if not pay.exDate:
                raise ValueError(
                    f"Kursliste payment on {pay.paymentDate} for {security.isin or security.securityName} missing exDate"
                )

            pos = reconciler.synthesize_position_at_date(pay.exDate)
            if pos is None:
                raise ValueError(
                    f"No position found for {security.isin or security.securityName} on exDate {pay.exDate}"
                )

            quantity = pos.quantity

            amount_per_unit = pay.paymentValue if pay.paymentValue is not None else pay.paymentValueCHF
            chf_per_unit = pay.paymentValueCHF

            amount = amount_per_unit * quantity
            chf_amount = chf_per_unit * quantity

            rate = pay.exchangeRate
            if rate is None:
                if pay.currency == "CHF":
                    rate = Decimal("1")
                else:
                    raise ValueError(
                        f"Kursliste payment on {pay.paymentDate} for {security.isin or security.securityName} missing exchangeRate"
                    )

            sec_payment = SecurityPayment(
                paymentDate=pay.paymentDate,
                exDate=pay.exDate,
                name=security.securityName,
                quotationType=security.quotationType,
                quantity=quantity,
                amountCurrency=pay.currency,
                amountPerUnit=amount_per_unit,
                amount=amount,
                exchangeRate=rate,
                kursliste=True,
            )

            if pay.withHoldingTax:
                sec_payment.grossRevenueA = chf_amount
                sec_payment.withHoldingTaxClaim = (
                    chf_amount * WITHHOLDING_TAX_RATE
                ).quantize(Decimal("0.01"))
            else:
                sec_payment.grossRevenueB = chf_amount

            result.append(sec_payment)

        self.setKurslistePayments(security, result, path_prefix)

