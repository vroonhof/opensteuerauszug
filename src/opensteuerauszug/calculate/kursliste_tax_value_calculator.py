from decimal import Decimal
from typing import Optional, List
import logging

from ..core.exchange_rate_provider import ExchangeRateProvider
from ..core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from ..core.kursliste_manager import KurslisteManager
from ..core.flag_override_provider import FlagOverrideProvider
from ..model.ech0196 import Security, SecurityTaxValue, SecurityPayment
from ..model.kursliste import PaymentTypeESTV, SecurityGroupESTV
from ..core.position_reconciler import PositionReconciler
from ..core.constants import WITHHOLDING_TAX_RATE
from .base import CalculationMode
from .minimal_tax_value import MinimalTaxValueCalculator
from ..util.converters import security_tax_value_to_stock

logger = logging.getLogger(__name__)


class KurslisteTaxValueCalculator(MinimalTaxValueCalculator):
    """
    Calculator that uses a Kursliste (official tax value list) to determine
    tax values for securities.
    """

    def __init__(self, mode: CalculationMode, exchange_rate_provider: ExchangeRateProvider, flag_override_provider: Optional[FlagOverrideProvider] = None, keep_existing_payments: bool = False):
        super().__init__(mode, exchange_rate_provider, keep_existing_payments=keep_existing_payments)
        logger.info(
            "KurslisteTaxValueCalculator initialized with mode: %s and provider: %s",
            mode.value,
            type(exchange_rate_provider).__name__,
        )
        self.kursliste_manager: Optional[KurslisteManager] = None
        if isinstance(exchange_rate_provider, KurslisteExchangeRateProvider):
            self.kursliste_manager = exchange_rate_provider.kursliste_manager
        self.flag_override_provider = flag_override_provider
        self._current_kursliste_security = None
        self._missing_kursliste_entries = []

    def calculate(self, tax_statement):
        self._missing_kursliste_entries = []
        result = super().calculate(tax_statement)
        if self._missing_kursliste_entries:
            logger.warning("Missing Kursliste entries for securities:")
            for entry in self._missing_kursliste_entries:
                logger.warning("  - %s", entry)
        return result

    def _handle_Security(self, security: Security, path_prefix: str) -> None:
        self._current_kursliste_security = None

        if not self.kursliste_manager:
            super()._handle_Security(security, path_prefix)
            return

        lookup_year = None
        if security.taxValue and security.taxValue.referenceDate:
            lookup_year = security.taxValue.referenceDate.year

        if lookup_year is None:
            super()._handle_Security(security, path_prefix)
            return

        accessor = self.kursliste_manager.get_kurslisten_for_year(lookup_year)
        if not accessor:
            super()._handle_Security(security, path_prefix)
            return

        kl_sec = None
        if security.valorNumber:
            kl_sec = accessor.get_security_by_valor(int(security.valorNumber))
        if not kl_sec and security.isin:
            kl_sec = accessor.get_security_by_isin(security.isin)

        if kl_sec:
            logger.debug("Kursliste security found: %s", kl_sec.isin or kl_sec.valorNumber or kl_sec.securityName)
            
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
                    self._set_field_value(sec_tax_value, "balanceCurrency", "CHF", path_prefix)
                    self._set_field_value(sec_tax_value, "kursliste", True, path_prefix)
                    return

        super()._handle_SecurityTaxValue(sec_tax_value, path_prefix)

    def computePayments(self, security: Security, path_prefix: str) -> None:
        """Compute payments for a security using the Kursliste."""
        if not self.kursliste_manager:
            super().computePayments(security, path_prefix)
            return

        kl_sec = self._current_kursliste_security
        if kl_sec is None:
            super().computePayments(security, path_prefix)
            return

        payments = [p for p in kl_sec.payment if not p.deleted]

        result: List[SecurityPayment] = []

        stock = list(security.stock)
        if security.taxValue:
            stock.append(security_tax_value_to_stock(security.taxValue))

        reconciler = PositionReconciler(stock, identifier=f"{security.isin or 'SEC'}-payments")

        accessor = self.kursliste_manager.get_kurslisten_for_year(security.taxValue.referenceDate.year)

        for pay in payments:
            if not pay.paymentDate:
                continue

            # Capital gains are not relevant for personal income tax and can be omitted.
            if hasattr(pay, "capitalGain") and pay.capitalGain:
                continue

            reconciliation_date = pay.exDate or pay.paymentDate

            pos = reconciler.synthesize_position_at_date(reconciliation_date)
            if pos is None:
                for l in reconciler.get_log():
                    logger.debug(l)
                raise ValueError(
                    f"No position found for {security.isin or security.securityName} on date {reconciliation_date}"
                )

            quantity = pos.quantity

            logger.debug("quantity %s found for date %s", quantity, reconciliation_date)
            if quantity == 0:
                # Skip payment generation if the quantity of outstanding securities is zero
                continue

            if pay.taxEvent:
                legends = getattr(pay, "legend", [])
                split_legend = next(
                    (
                        legend
                        for legend in legends
                        if legend.exchangeRatioPresent is not None
                        and legend.exchangeRatioNew is not None
                    ),
                    None,
                )
                if split_legend:
                    ratio_present = split_legend.exchangeRatioPresent
                    ratio_new = split_legend.exchangeRatioNew
                    if ratio_present:
                        expected_delta = quantity * (ratio_new / ratio_present - Decimal("1"))
                        mutations_on_date = [
                            stock
                            for stock in security.stock
                            if stock.mutation and stock.referenceDate == reconciliation_date
                        ]
                        if not mutations_on_date:
                            raise ValueError(
                                f"Missing stock split mutation for {security.isin or security.securityName} on {reconciliation_date}"
                            )
                        if expected_delta not in {m.quantity for m in mutations_on_date}:
                            raise ValueError(
                                f"Stock split ratio mismatch for {security.isin or security.securityName} on {reconciliation_date}"
                            )

                    if pay.paymentValueCHF in (None, Decimal("0")) and pay.paymentValue in (None, Decimal("0")):
                        continue

            payment_name = f"KL:{security.securityName}"
            if pay.paymentType is None or pay.paymentType == PaymentTypeESTV.STANDARD:
                if kl_sec.securityGroup == "SHARE":
                    payment_name = "Dividend"
                else:
                    payment_name = "Distribution"
            elif pay.paymentType == PaymentTypeESTV.GRATIS:
                payment_name = "Stock Dividend"
            elif pay.paymentType == PaymentTypeESTV.OTHER_BENEFIT:
                payment_name = "Other Monetary Benefits"
            elif pay.paymentType == PaymentTypeESTV.AGIO:
                payment_name = "Premium/Agio"
            elif pay.paymentType == PaymentTypeESTV.FUND_ACCUMULATION:
                payment_name = "Taxable Income from Accumulating Fund"

            if pay.undefined:
                sec_payment = SecurityPayment(
                    paymentDate=pay.paymentDate,
                    exDate=pay.exDate,
                    name=payment_name,
                    quotationType=security.quotationType,
                    quantity=quantity,
                    amountCurrency=security.currency,
                    kursliste=True,
                )
                sec_payment.undefined = True
                if pay.sign is not None:
                    sec_payment.sign = pay.sign
                if hasattr(pay, "gratis") and pay.gratis is not None:
                    sec_payment.gratis = pay.gratis
                result.append(sec_payment)
                continue

            if pay.paymentValueCHF is None:
                raise ValueError(
                    f"Kursliste payment on {pay.paymentDate} for {security.isin or security.securityName} missing paymentValueCHF"
                )

            amount_per_unit = pay.paymentValue if pay.paymentValue is not None else pay.paymentValueCHF
            chf_per_unit = pay.paymentValueCHF

            amount = amount_per_unit * quantity
            chf_amount = chf_per_unit * quantity

            rate = pay.exchangeRate
            if rate is None and pay.paymentValueCHF != 0:
                if pay.currency == "CHF":
                    rate = Decimal("1")
                else:
                    logger.error("Invalid Kursliste payment: %s", pay)
                    raise ValueError(
                        f"Kursliste payment on {pay.paymentDate} for {security.isin or security.securityName} missing exchangeRate"
                    )

            sec_payment = SecurityPayment(
                paymentDate=pay.paymentDate,
                exDate=pay.exDate,
                name=payment_name,
                quotationType=security.quotationType,
                quantity=quantity,
                amountCurrency=pay.currency,
                amountPerUnit=amount_per_unit,
                amount=amount,
                exchangeRate=rate,
                kursliste=True,
            )

            # Not all payment subtypes have these fields
            # TODO: Should the typing be smarter?
            effective_sign = pay.sign if hasattr(pay, "sign") and pay.sign is not None else None
            if self.flag_override_provider and security.isin:
                override_flag = self.flag_override_provider.get_flag(security.isin)
                if override_flag:
                    logger.debug("Found override flag '%s' for %s", override_flag, security.isin)
                    if not (override_flag.startswith('(') and override_flag.endswith(')')):
                        effective_sign = f"({override_flag})"
                    else:
                        effective_sign = override_flag
            
            sec_payment.sign = effective_sign

            if hasattr(pay, "gratis") and pay.gratis:
                sec_payment.gratis = pay.gratis

            # Reality vs spec: Real-world files seem to have all three fields set when at least one is set,
            # possibly with zero values, even though our reading of the spec suggests they should be mutually exclusive
            if pay.withHoldingTax:
                sec_payment.grossRevenueA = chf_amount
                sec_payment.grossRevenueB = Decimal("0")
                sec_payment.withHoldingTaxClaim = (
                    chf_amount * WITHHOLDING_TAX_RATE
                ).quantize(Decimal("0.01"))
            else:
                sec_payment.grossRevenueA = Decimal("0")
                sec_payment.grossRevenueB = chf_amount
                sec_payment.withHoldingTaxClaim = Decimal("0")

            da1_security_group = kl_sec.securityGroup
            da1_security_type = kl_sec.securityType
            if effective_sign == "(Q)":
                da1_security_group = SecurityGroupESTV.SHARE
                da1_security_type = None

            da1_rate = accessor.get_da1_rate(
                kl_sec.country, da1_security_group, da1_security_type, reference_date=pay.paymentDate
            )

            if da1_rate:
                sec_payment.lumpSumTaxCredit = True
                sec_payment.lumpSumTaxCreditPercent = da1_rate.value
                sec_payment.lumpSumTaxCreditAmount = (
                    chf_amount * da1_rate.value / Decimal(100)
                )
                sec_payment.nonRecoverableTaxPercent = da1_rate.nonRecoverable
                sec_payment.nonRecoverableTaxAmount = (
                    chf_amount * da1_rate.nonRecoverable / Decimal(100)
                )

            if effective_sign == "(V)":
                raise NotImplementedError(
                    f"DA-1 for sign='(V)' not implemented for {security.isin or security.securityName} on {pay.paymentDate}"
                )

            result.append(sec_payment)

        self.setKurslistePayments(security, result, path_prefix)
