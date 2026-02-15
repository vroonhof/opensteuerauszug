from decimal import Decimal
from typing import Optional, List, Set
import logging

from ..core.exchange_rate_provider import ExchangeRateProvider
from ..core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from ..core.kursliste_manager import KurslisteManager
from ..core.flag_override_provider import FlagOverrideProvider
from ..model.ech0196 import Security, SecurityTaxValue, SecurityPayment
from ..model.kursliste import PaymentTypeESTV, SecurityGroupESTV
from ..model.critical_warning import CriticalWarning, CriticalWarningCategory
from ..core.position_reconciler import PositionReconciler
from ..core.constants import WITHHOLDING_TAX_RATE
from .base import CalculationMode
from .minimal_tax_value import MinimalTaxValueCalculator
from ..util.converters import security_tax_value_to_stock

logger = logging.getLogger(__name__)

# Known sign types that we explicitly handle. Any sign not in this set will raise an error.
# Signs are defined in the ESTV Kursliste and have specific tax treatment meanings.
# - KEP: Return of capital contributions (Rückzahlung Kapitaleinlagen) - non-taxable, skip payment
# - (Q): With foreign withholding tax - requires special DA-1 treatment
# - (V): Distribution in form of shares - not implemented
# - (KG): Capital gain - non-taxable for private investors, skip payment
# - (KR): Return of Capital - non-taxable, skip payment
# - Other signs are informational and don't affect tax calculation
KNOWN_SIGN_TYPES: Set[str] = {
    "(B)",  # Bonus
    "(E)",  # Ex-date related
    "(G)",  # Withholding tax free capital gains
    "(H)",  # Investment fund with direct real estate
    "(I)",  # Taxable earnings not yet determined
    "(IK)",  # Non-taxable KEP distribution not yet determined
    "(IM)",  # Reinvestment of retained earnings
    "KEP",  # Return of capital contributions - SKIP PAYMENT
    "(KG)",  # Capital gain - SKIP PAYMENT
    "(KR)",  # Return of Capital - SKIP PAYMENT
    "(L)",  # No withholding tax deduction
    "(M)",  # Re-investment fund (Switzerland)
    "(MV)",  # Distribution notification procedure
    "(N)",  # Re-investment fund (abroad)
    "(P)",  # Foreign earnings subject to withholding tax
    "PRO",  # Provisional
    "(Q)",  # With foreign withholding tax - SPECIAL HANDLING
    "(V)",  # Distribution in form of shares - NOT IMPLEMENTED
    "(Y)",  # Purchasing own shares
    "(Z)",  # Without withholding tax
}

# Signs that indicate non-taxable payments that should be skipped entirely
NON_TAXABLE_SIGNS: Set[str] = {
    "KEP",  # Return of capital contributions
    "(KG)",  # Capital gain
    "(KR)",  # Return of Capital
}


class KurslisteTaxValueCalculator(MinimalTaxValueCalculator):
    """
    Calculator that uses a Kursliste (official tax value list) to determine
    tax values for securities.
    """

    def __init__(
        self,
        mode: CalculationMode,
        exchange_rate_provider: ExchangeRateProvider,
        flag_override_provider: Optional[FlagOverrideProvider] = None,
        keep_existing_payments: bool = False,
    ):
        super().__init__(
            mode, exchange_rate_provider, keep_existing_payments=keep_existing_payments
        )
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
        self._previous_year_exdate_warnings = []
        self._all_securities: List[Security] = []

    def calculate(self, tax_statement):
        self._missing_kursliste_entries = []
        self._previous_year_exdate_warnings = []
        # Collect all securities across all depots so that cross-security
        # split validation (valorNumberNew) can look up the target security.
        self._all_securities = []
        if tax_statement.listOfSecurities:
            for depot in tax_statement.listOfSecurities.depot:
                self._all_securities.extend(depot.security)
        result = super().calculate(tax_statement)
        if self._missing_kursliste_entries:
            logger.warning("Missing Kursliste entries for securities:")
            for entry in self._missing_kursliste_entries:
                logger.warning("  - %s", entry)
                result.critical_warnings.append(
                    CriticalWarning(
                        category=CriticalWarningCategory.MISSING_KURSLISTE,
                        message=(
                            f"Security {entry} was not found in the Kursliste. "
                            "Tax values and income for this security may be "
                            "incorrect or missing."
                        ),
                        source="KurslisteTaxValueCalculator",
                        identifier=entry,
                    )
                )
        for warning_info in self._previous_year_exdate_warnings:
            result.critical_warnings.append(
                CriticalWarning(
                    category=CriticalWarningCategory.PREVIOUS_YEAR_EXDATE,
                    message=warning_info["message"],
                    source="KurslisteTaxValueCalculator",
                    identifier=warning_info["identifier"],
                )
            )
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
            logger.debug(
                "Kursliste security found: %s",
                kl_sec.isin or kl_sec.valorNumber or kl_sec.securityName,
            )

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

            # Check if this is a rights issue that we should ignore if not found
            is_rights = security.is_rights_issue
            closing_balance = Decimal("0")

            if security.taxValue:
                closing_balance = security.taxValue.quantity

            if is_rights and closing_balance == 0:
                logger.debug(
                    "Suppressing missing Kursliste warning for rights issue %s with zero balance.",
                    ident,
                )
            else:
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

    def _validate_stock_split(
        self,
        security: Security,
        reconciliation_date,
        quantity: Decimal,
        ratio_present: Decimal,
        ratio_new: Decimal,
        valor_number_new: Optional[int],
    ) -> None:
        """Validate that a stock split is correctly reflected in the imported mutations.

        There are two distinct cases:

        **Same-ISIN split** (``valor_number_new`` is ``None``):
        The security keeps its ISIN/valor number and the broker reports a single
        corporate-action whose quantity equals the net change in shares.  We
        expect a mutation on *this* security of
        ``quantity * (ratio_new / ratio_present - 1)``.

        **Cross-ISIN split** (``valor_number_new`` is set):
        The security's ISIN/valor number changes as part of the split.  The
        broker reports *two* corporate-actions – one negative on the old ISIN
        (removing all old shares) and one positive on the new ISIN (adding the
        post-split shares).  We expect:
          - a negative mutation on the *old* (current) security of ``-quantity``
          - a positive mutation on a *new* security (identified by
            ``valor_number_new``) of ``quantity * ratio_new / ratio_present``
        """
        sec_ident = security.isin or security.securityName

        mutations_on_date = [
            stock
            for stock in security.stock
            if stock.mutation and stock.referenceDate == reconciliation_date
        ]

        if valor_number_new is None:
            # ---- Same-ISIN split: look for a single delta on this security ----
            expected_delta = quantity * (ratio_new / ratio_present - Decimal("1"))
            if not mutations_on_date:
                raise ValueError(
                    f"Missing stock split mutation for {sec_ident} on "
                    f"{reconciliation_date}: expected a mutation of "
                    f"{expected_delta} shares (split ratio "
                    f"{ratio_new}:{ratio_present}, pre-split position "
                    f"{quantity}), but no mutations were found on that date."
                )
            mutation_quantities = {m.quantity for m in mutations_on_date}
            if expected_delta not in mutation_quantities:
                raise ValueError(
                    f"Stock split ratio mismatch for {sec_ident} on "
                    f"{reconciliation_date}: expected a mutation of "
                    f"{expected_delta} shares (split ratio "
                    f"{ratio_new}:{ratio_present}, pre-split position "
                    f"{quantity}), but the mutations found on that date "
                    f"have quantities {sorted(mutation_quantities)}."
                )
        else:
            # ---- Cross-ISIN split (valorNumberNew): two securities involved ----
            expected_removal = -quantity
            expected_addition = quantity * ratio_new / ratio_present

            # 1. Validate the negative mutation on the old (current) security
            mutation_quantities = {m.quantity for m in mutations_on_date}
            if expected_removal not in mutation_quantities:
                raise ValueError(
                    f"Stock split with ISIN change for {sec_ident} on "
                    f"{reconciliation_date}: expected a removal mutation of "
                    f"{expected_removal} shares on the old security (split "
                    f"ratio {ratio_new}:{ratio_present}, pre-split position "
                    f"{quantity}, new valor {valor_number_new}), but the "
                    f"mutations found on that date have quantities "
                    f"{sorted(mutation_quantities)}."
                )

            # 2. Validate the positive mutation on the new security
            new_security = None
            for sec in self._all_securities:
                if sec.valorNumber == valor_number_new:
                    new_security = sec
                    break

            if (
                new_security is None
                and self.kursliste_manager
                and security.taxValue
                and security.taxValue.referenceDate
            ):
                accessor = self.kursliste_manager.get_kurslisten_for_year(
                    security.taxValue.referenceDate.year
                )
                if accessor:
                    new_kl_security = accessor.get_security_by_valor(int(valor_number_new))
                    if new_kl_security and new_kl_security.isin:
                        for sec in self._all_securities:
                            if sec.isin == new_kl_security.isin:
                                new_security = sec
                                break

            if new_security is None:
                raise ValueError(
                    f"Stock split with ISIN change for {sec_ident} on "
                    f"{reconciliation_date}: the Kursliste split legend "
                    f"references new valor number {valor_number_new}, but no "
                    f"security with that valor number was found in the tax "
                    f"statement. This typically means the broker's corporate "
                    f"action for the new ISIN was not imported. Expected "
                    f"{expected_addition} shares to appear on the new security "
                    f"(split ratio {ratio_new}:{ratio_present}, pre-split "
                    f"position {quantity})."
                )

            new_sec_ident = new_security.isin or new_security.securityName
            new_mutations_on_date = [
                stock
                for stock in new_security.stock
                if stock.mutation and stock.referenceDate == reconciliation_date
            ]
            if not new_mutations_on_date:
                raise ValueError(
                    f"Stock split with ISIN change for {sec_ident} on "
                    f"{reconciliation_date}: the new security "
                    f"{new_sec_ident} (valor {valor_number_new}) has no "
                    f"mutations on the split date. Expected an addition of "
                    f"{expected_addition} shares (split ratio "
                    f"{ratio_new}:{ratio_present}, pre-split position "
                    f"{quantity})."
                )
            new_mutation_quantities = {m.quantity for m in new_mutations_on_date}
            if expected_addition not in new_mutation_quantities:
                raise ValueError(
                    f"Stock split with ISIN change for {sec_ident} on "
                    f"{reconciliation_date}: the new security "
                    f"{new_sec_ident} (valor {valor_number_new}) has "
                    f"mutations with quantities "
                    f"{sorted(new_mutation_quantities)} on the split date, "
                    f"but expected an addition of {expected_addition} shares "
                    f"(split ratio {ratio_new}:{ratio_present}, pre-split "
                    f"position {quantity})."
                )

            logger.info(
                "Validated cross-ISIN stock split for %s on %s: "
                "removed %s shares from old security, added %s shares "
                "to new security %s (valor %s).",
                sec_ident,
                reconciliation_date,
                expected_removal,
                expected_addition,
                new_sec_ident,
                valor_number_new,
            )

    def computePayments(self, security: Security, path_prefix: str) -> None:
        """Compute payments for a security using the Kursliste."""
        if not self.kursliste_manager:
            raise RuntimeError("kursliste_manager is required for Kursliste payments")

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

        accessor = self.kursliste_manager.get_kurslisten_for_year(
            security.taxValue.referenceDate.year
        )

        for pay in payments:
            if not pay.paymentDate:
                continue

            # Capital gains are not relevant for personal income tax and can be omitted.
            if hasattr(pay, "capitalGain") and pay.capitalGain:
                continue

            reconciliation_date = pay.exDate or pay.paymentDate

            # Warn if exDate is in the previous year (before the tax period)
            if pay.exDate and security.taxValue and security.taxValue.referenceDate:
                tax_year = security.taxValue.referenceDate.year
                if pay.exDate.year < tax_year:
                    sec_ident = security.isin or security.securityName
                    warning_msg = (
                        f"Payment '{pay.paymentDate}' for security "
                        f"'{sec_ident}' has an ex-date "
                        f"({pay.exDate}) in the previous year. "
                        f"The dividend amount is based on the "
                        f"opening position of the period because "
                        f"mutations from the previous year are not "
                        f"processed. Please double-check the amount."
                    )
                    logger.warning(warning_msg)
                    self._previous_year_exdate_warnings.append(
                        {
                            "message": warning_msg,
                            "identifier": sec_ident,
                        }
                    )

            pos = reconciler.synthesize_position_at_date(reconciliation_date, assume_zero_if_no_balances=True)
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
                    valor_number_new = split_legend.valorNumberNew
                    if ratio_present:
                        self._validate_stock_split(
                            security=security,
                            reconciliation_date=reconciliation_date,
                            quantity=quantity,
                            ratio_present=ratio_present,
                            ratio_new=ratio_new,
                            valor_number_new=valor_number_new,
                        )

                    if pay.paymentValueCHF in (None, Decimal("0")) and pay.paymentValue in (
                        None,
                        Decimal("0"),
                    ):
                        continue

            # Validate sign type if present
            current_sign = pay.sign if hasattr(pay, "sign") else None
            if current_sign is not None and current_sign not in KNOWN_SIGN_TYPES:
                raise ValueError(
                    f"Unknown sign type '{current_sign}' for payment on {pay.paymentDate} "
                    f"for {security.isin or security.securityName}. "
                    f"Please add handling for this sign type."
                )

            # Skip non-taxable payments (return of capital, capital gains)
            if current_sign in NON_TAXABLE_SIGNS:
                logger.debug(
                    "Skipping non-taxable payment with sign '%s' on %s for %s",
                    current_sign,
                    pay.paymentDate,
                    security.isin or security.securityName,
                )
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
                    payment_type_original=(pay.paymentType.value if pay.paymentType is not None else None),
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

            amount_per_unit = (
                pay.paymentValue if pay.paymentValue is not None else pay.paymentValueCHF
            )
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
                payment_type_original=(pay.paymentType.value if pay.paymentType is not None else None),
            )

            # Not all payment subtypes have these fields
            # TODO: Should the typing be smarter?
            effective_sign = pay.sign if hasattr(pay, "sign") and pay.sign is not None else None
            if self.flag_override_provider and security.isin:
                override_flag = self.flag_override_provider.get_flag(security.isin)
                if override_flag:
                    logger.debug("Found override flag '%s' for %s", override_flag, security.isin)
                    if not (override_flag.startswith("(") and override_flag.endswith(")")):
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
                sec_payment.withHoldingTaxClaim = (chf_amount * WITHHOLDING_TAX_RATE).quantize(
                    Decimal("0.01")
                )
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
                kl_sec.country,
                da1_security_group,
                da1_security_type,
                reference_date=pay.paymentDate,
            )

            if da1_rate:
                lump_sum_amount = chf_amount * da1_rate.value / Decimal(100)
                non_recoverable_amount = chf_amount * da1_rate.nonRecoverable / Decimal(100)
                if lump_sum_amount > 0 or non_recoverable_amount > 0:
                    sec_payment.lumpSumTaxCreditPercent = da1_rate.value
                    sec_payment.lumpSumTaxCreditAmount = lump_sum_amount
                    sec_payment.nonRecoverableTaxPercent = da1_rate.nonRecoverable
                    sec_payment.nonRecoverableTaxAmount = non_recoverable_amount
                    if kl_sec.country == "US":
                        sec_payment.additionalWithHoldingTaxUSA = Decimal("0")
                    sec_payment.lumpSumTaxCredit = True

            if effective_sign == "(V)":
                raise NotImplementedError(
                    f"DA-1 for sign='(V)' not implemented for {security.isin or security.securityName} on {pay.paymentDate}"
                )

            result.append(sec_payment)

        self.setKurslistePayments(security, result, path_prefix)
