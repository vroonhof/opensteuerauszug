from datetime import date, timedelta
from decimal import Decimal
from datetime import date
from typing import Optional, List, Set
import logging

from opensteuerauszug.core.exchange_rate_provider import ExchangeRateProvider
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.core.flag_override_provider import FlagOverrideProvider
from opensteuerauszug.model.ech0196 import Security, SecurityTaxValue, SecurityPayment, SecurityStock, PaymentTypeOriginal
from opensteuerauszug.model.kursliste import PaymentTypeESTV, SecurityGroupESTV
from opensteuerauszug.model.critical_warning import CriticalWarning, CriticalWarningCategory
from opensteuerauszug.core.position_reconciler import PositionReconciler
from opensteuerauszug.core.constants import WITHHOLDING_TAX_RATE
from .base import CalculationMode
from .minimal_tax_value import MinimalTaxValueCalculator
from opensteuerauszug.util.converters import security_tax_value_to_stock
from opensteuerauszug.render.translations import get_text, DEFAULT_LANGUAGE, Language

logger = logging.getLogger(__name__)


def _next_business_day(d: date) -> date:
    """Return the next business day after ``d``, skipping weekends."""
    next_day = d + timedelta(days=1)
    while next_day.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        next_day += timedelta(days=1)
    return next_day


def _has_intervening_event(d1: date, d2: date, event_dates: Set[date]) -> bool:
    """Return True if any date in *event_dates* falls strictly between *d1* and *d2*."""
    if d1 == d2:
        return False
    lo, hi = (d1, d2) if d1 < d2 else (d2, d1)
    return any(lo < d < hi for d in event_dates)


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
        render_language: Language = DEFAULT_LANGUAGE,
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
        self.render_language = render_language
        self._current_kursliste_security = None
        self._current_security_is_zero_balance_option = False
        self._missing_kursliste_entries = []
        self._stock_split_warnings: List[dict] = []
        self._previous_year_exdate_warnings = []
        self._all_securities: List[Security] = []

    def _translate(self, key: str) -> str:
        return get_text(key, self.render_language)

    def calculate(self, tax_statement):
        self._missing_kursliste_entries = []
        self._stock_split_warnings = []
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
        for warning_info in self._stock_split_warnings:
            result.critical_warnings.append(
                CriticalWarning(
                    category=CriticalWarningCategory.STOCK_SPLIT_MISMATCH,
                    message=warning_info["message"],
                    source="KurslisteTaxValueCalculator",
                    identifier=warning_info["identifier"],
                )
            )
        for warning_info in self._previous_year_exdate_warnings:
            result.critical_warnings.append(
                CriticalWarning(
                    category=CriticalWarningCategory.PREVIOUS_YEAR_EXDATE,
                    message=warning_info["message"],
                    source="KurslisteTaxValueCalculator",
                    identifier=warning_info["identifier"],
                    payment_date=warning_info["payment_date"],
                )
            )
        return result

    def _handle_Security(self, security: Security, path_prefix: str) -> None:
        self._current_kursliste_security = None
        self._current_security_is_zero_balance_option = False

        if not self.kursliste_manager:
            super()._handle_Security(security, path_prefix)
            return

        lookup_year = None
        if security.taxValue and security.taxValue.referenceDate:
            lookup_year = security.taxValue.referenceDate.year

        if lookup_year is None and security.stock and security.stock[-1].referenceDate:
            # Infer the year from the last stock entry for securities with no end-of-period
            # position (e.g. fully sold during the year) so that we can still check
            # whether the security is listed in the Kursliste and emit a warning if not.
            lookup_year = security.stock[-1].referenceDate.year

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
                security.isin
                or (f"Valor {security.valorNumber}" if security.valorNumber else None)
                or security.securityName
            )

            # Check if this is a rights issue or zero-balance option that we should ignore if not found
            is_rights = security.is_rights_issue
            is_option = security.securityCategory == "OPTION"
            closing_balance = Decimal("0")

            if security.taxValue:
                closing_balance = security.taxValue.quantity

            if is_rights and closing_balance == 0:
                logger.debug(
                    "Suppressing missing Kursliste warning for rights issue %s with zero balance.",
                    ident,
                )
            elif is_option and closing_balance == 0:
                # TODO come up with a a plan for to have a relatively safe intermediate version
                # of fill-in mode that allows keeping the brokers valuaton for security types
                # that have no tax effects other than due to their end of year value.
                logger.debug(
                    "Suppressing missing Kursliste warning for option %s with zero balance.",
                    ident,
                )
                self._current_security_is_zero_balance_option = True
            elif closing_balance == 0 and not security.payment:
                # Security fully closed before year-end with no broker payments: no tax impact.
                # If payments exist (e.g. dividends paid intra-year), keep the warning so the
                # user knows Kursliste-based income enrichment was skipped.
                logger.debug(
                    "Suppressing missing Kursliste warning for %s with zero balance and no payments.",
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
                    # The Kursliste price is in CHF, so if balance was previously set
                    # (e.g. from the broker's position value), it must be updated to the CHF value.
                    self._set_field_value(sec_tax_value, "balance", value, path_prefix)
                    self._set_field_value(sec_tax_value, "exchangeRate", Decimal("1"), path_prefix)
                    self._set_field_value(sec_tax_value, "balanceCurrency", "CHF", path_prefix)
                    self._set_field_value(sec_tax_value, "kursliste", True, path_prefix)
                    return
        elif self._current_security_is_zero_balance_option:
            # The option position was fully closed before year-end: value is definitively 0.
            # Compute the exchange rate for the currency so the report shows a proper CHF value.
            if sec_tax_value.balanceCurrency and sec_tax_value.referenceDate:
                _, rate = self._convert_to_chf(
                    None, sec_tax_value.balanceCurrency, path_prefix, sec_tax_value.referenceDate
                )
                self._set_field_value(sec_tax_value, "unitPrice", Decimal("0"), path_prefix)
                self._set_field_value(sec_tax_value, "value", Decimal("0"), path_prefix)
                self._set_field_value(sec_tax_value, "exchangeRate", rate, path_prefix)
            return
        else:
            self._set_field_value(sec_tax_value, "undefined", True, path_prefix)

        super()._handle_SecurityTaxValue(sec_tax_value, path_prefix)

    def _validate_stock_split(
        self,
        security: Security,
        reconciliation_date,
        quantity: Decimal,
        ratio_present: Decimal,
        ratio_new: Decimal,
        valor_number_new: Optional[int],
        is_gratis: bool = False,
        payment_date=None,
        all_tax_event_dates: Optional[Set[date]] = None,
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

        For stock dividends (gratis=True), the mutation typically occurs on the
        payment date rather than the effective date.

        Fallback date matching is supported: if no mutation is found on the primary
        date, the validator also checks the alternative date (ex-date vs. pay-date)
        and the next business day after the primary date, provided no other tax
        event for this security falls between those dates.
        """
        sec_ident = security.isin or security.securityName

        # When valorNumberNew points to the same security (e.g. Kursliste records the
        # new valor as identical to the existing one), treat it as a same-ISIN split.
        if (
            valor_number_new is not None
            and security.valorNumber is not None
            and int(valor_number_new) == int(security.valorNumber)
        ):
            valor_number_new = None

        # For stock dividends (gratis), the mutation typically occurs on the payment
        # date rather than the effective date (ex-date).
        primary_date = payment_date if is_gratis and payment_date else reconciliation_date

        # Build ordered list of candidate dates to search for matching mutations.
        # Fallback dates are only considered when no other tax event for this security
        # falls strictly between the primary date and the candidate date.
        # Exclude the current event's own dates so they don't block fallback matching
        # within the same event window.
        current_event_dates: Set[date] = {
            d for d in (reconciliation_date, payment_date) if d is not None
        }
        event_dates: Set[date] = (all_tax_event_dates or set()) - current_event_dates
        candidate_dates = [primary_date]

        # Alternative date: paydate <-> exdate swap
        alt_date = reconciliation_date if is_gratis else payment_date
        if alt_date and alt_date != primary_date and not _has_intervening_event(
            primary_date, alt_date, event_dates
        ):
            candidate_dates.append(alt_date)

        # Next business day after the primary date
        next_bday = _next_business_day(primary_date)
        if next_bday not in candidate_dates and not _has_intervening_event(
            primary_date, next_bday, event_dates
        ):
            candidate_dates.append(next_bday)

        # Find mutations on the first matching candidate date
        mutation_date = primary_date
        mutations_on_date: List[SecurityStock] = []
        for candidate in candidate_dates:
            found = [
                stock
                for stock in security.stock
                if stock.mutation and stock.referenceDate == candidate
            ]
            if found:
                if candidate != primary_date:
                    logger.debug(
                        "Found %s mutation for %s on fallback date %s (primary was %s).",
                        "stock dividend" if is_gratis else "stock split",
                        sec_ident,
                        candidate,
                        primary_date,
                    )
                mutation_date = candidate
                mutations_on_date = found
                break

        event_type = "stock dividend" if is_gratis else "stock split"

        # Resolve the Kursliste year for cross-ISIN lookups even when the old
        # security has no year-end taxValue (fully replaced during the year).
        split_lookup_year = None
        if security.taxValue and security.taxValue.referenceDate:
            split_lookup_year = security.taxValue.referenceDate.year
        elif payment_date is not None:
            split_lookup_year = payment_date.year
        elif reconciliation_date is not None:
            split_lookup_year = reconciliation_date.year

        if valor_number_new is None:
            # ---- Same-ISIN split: look for a single delta on this security ----
            expected_delta = quantity * (ratio_new / ratio_present - Decimal("1"))
            if not mutations_on_date:
                msg = (
                    f"Missing {event_type} mutation for {sec_ident} on "
                    f"{mutation_date}: expected a mutation of "
                    f"{expected_delta} shares (split ratio "
                    f"{ratio_new}:{ratio_present}, pre-split position "
                    f"{quantity}), but no mutations were found on that date. "
                    f"Please verify this security manually."
                )
                logger.warning(msg)
                self._stock_split_warnings.append(
                    {"message": msg, "identifier": sec_ident}
                )
                return
            mutation_quantities = {m.quantity for m in mutations_on_date}
            if expected_delta not in mutation_quantities:
                msg = (
                    f"{event_type.capitalize()} ratio mismatch for {sec_ident} on "
                    f"{mutation_date}: expected a mutation of "
                    f"{expected_delta} shares (split ratio "
                    f"{ratio_new}:{ratio_present}, pre-split position "
                    f"{quantity}), but the mutations found on that date "
                    f"have quantities {sorted(mutation_quantities)}. "
                    f"Please verify this security manually."
                )
                logger.warning(msg)
                self._stock_split_warnings.append(
                    {"message": msg, "identifier": sec_ident}
                )
                return
        else:
            # ---- Cross-ISIN split (valorNumberNew): two securities involved ----
            expected_removal = -quantity
            expected_addition = quantity * ratio_new / ratio_present

            # 1. Validate the negative mutation on the old (current) security
            mutation_quantities = {m.quantity for m in mutations_on_date}
            if expected_removal not in mutation_quantities:
                msg = (
                    f"{event_type.capitalize()} with ISIN change for {sec_ident} on "
                    f"{mutation_date}: expected a removal mutation of "
                    f"{expected_removal} shares on the old security (split "
                    f"ratio {ratio_new}:{ratio_present}, pre-split position "
                    f"{quantity}, new valor {valor_number_new}), but the "
                    f"mutations found on that date have quantities "
                    f"{sorted(mutation_quantities)}. "
                    f"Please verify this security manually."
                )
                logger.warning(msg)
                self._stock_split_warnings.append(
                    {"message": msg, "identifier": sec_ident}
                )
                return

            # 2. Validate the positive mutation on the new security
            new_security = None
            for sec in self._all_securities:
                if sec.valorNumber == valor_number_new:
                    new_security = sec
                    break

            if new_security is None and self.kursliste_manager and split_lookup_year is not None:
                accessor = self.kursliste_manager.get_kurslisten_for_year(split_lookup_year)
                if accessor:
                    new_kl_security = accessor.get_security_by_valor(int(valor_number_new))
                    if new_kl_security and new_kl_security.isin:
                        for sec in self._all_securities:
                            if sec.isin == new_kl_security.isin:
                                new_security = sec
                                break

            if new_security is None:
                msg = (
                    f"{event_type.capitalize()} with ISIN change for {sec_ident} on "
                    f"{mutation_date}: the Kursliste split legend "
                    f"references new valor number {valor_number_new}, but no "
                    f"security with that valor number was found in the tax "
                    f"statement. This typically means the broker's corporate "
                    f"action for the new ISIN was not imported. Expected "
                    f"{expected_addition} shares to appear on the new security "
                    f"(split ratio {ratio_new}:{ratio_present}, pre-split "
                    f"position {quantity}). "
                    f"Please verify this security manually."
                )
                logger.warning(msg)
                self._stock_split_warnings.append(
                    {"message": msg, "identifier": sec_ident}
                )
                return

            new_sec_ident = new_security.isin or new_security.securityName
            # Search for the addition mutation using the same candidate dates as the removal.
            new_mutation_date = mutation_date
            new_mutations_on_date: List[SecurityStock] = []
            for candidate in candidate_dates:
                found = [
                    stock
                    for stock in new_security.stock
                    if stock.mutation and stock.referenceDate == candidate
                ]
                if found:
                    new_mutation_date = candidate
                    new_mutations_on_date = found
                    break
            if not new_mutations_on_date:
                msg = (
                    f"{event_type.capitalize()} with ISIN change for {sec_ident} on "
                    f"{primary_date}: the new security "
                    f"{new_sec_ident} (valor {valor_number_new}) has no "
                    f"mutations on the split date. Expected an addition of "
                    f"{expected_addition} shares (split ratio "
                    f"{ratio_new}:{ratio_present}, pre-split position "
                    f"{quantity}). "
                    f"Please verify this security manually."
                )
                logger.warning(msg)
                self._stock_split_warnings.append(
                    {"message": msg, "identifier": sec_ident}
                )
                return
            new_mutation_quantities = {m.quantity for m in new_mutations_on_date}
            if expected_addition not in new_mutation_quantities:
                msg = (
                    f"{event_type.capitalize()} with ISIN change for {sec_ident} on "
                    f"{new_mutation_date}: the new security "
                    f"{new_sec_ident} (valor {valor_number_new}) has "
                    f"mutations with quantities "
                    f"{sorted(new_mutation_quantities)} on the split date, "
                    f"but expected an addition of {expected_addition} shares "
                    f"(split ratio {ratio_new}:{ratio_present}, pre-split "
                    f"position {quantity}). "
                    f"Please verify this security manually."
                )
                logger.warning(msg)
                self._stock_split_warnings.append(
                    {"message": msg, "identifier": sec_ident}
                )
                return

            logger.info(
                "Validated cross-ISIN %s for %s on %s: "
                "removed %s shares from old security, added %s shares "
                "to new security %s (valor %s).",
                event_type,
                sec_ident,
                mutation_date,
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

        # Track variant numbers seen per event key so we can detect payments that
        # represent an OR-choice (e.g. cash dividend vs. stock dividend). The check
        # is woven into the main loop so it only considers payments that are
        # actually processed (respecting the paymentDate and capitalGain filters).
        variants_by_event: dict[date, set[int]] = {}

        stock = list(security.stock)
        if security.taxValue:
            stock.append(security_tax_value_to_stock(security.taxValue))

        reconciler = PositionReconciler(stock, identifier=f"{security.isin or 'SEC'}-payments")

        ref_year = (
            security.taxValue.referenceDate.year
            if security.taxValue and security.taxValue.referenceDate
            else security.stock[-1].referenceDate.year
        )
        accessor = self.kursliste_manager.get_kurslisten_for_year(ref_year)

        # Pre-compute all tax-event dates across this security's payments so that
        # _validate_stock_split can skip fallback dates that would cross another event.
        all_kl_tax_event_dates: Set[date] = {
            d
            for p in payments
            if p.paymentDate and p.taxEvent
            for d in (p.exDate, p.paymentDate)
            if d is not None
        }

        for pay in payments:
            if not pay.paymentDate:
                continue

            # Capital gains are not relevant for personal income tax and can be omitted.
            if hasattr(pay, "capitalGain") and pay.capitalGain:
                continue

            reconciliation_date = pay.exDate or pay.paymentDate

            # The variant attribute marks an OR-choice between mutually exclusive
            # payment alternatives (e.g. cash dividend vs. stock dividend). If we
            # encounter more than one distinct variant for the same event, there
            # is no mechanical way to choose — surface this to the user.
            if pay.variant is not None:
                seen = variants_by_event.setdefault(reconciliation_date, set())
                seen.add(pay.variant)
                if len(seen) > 1:
                    sec_ident = security.isin or security.securityName
                    raise NotImplementedError(
                        f"Payment on {reconciliation_date} for '{sec_ident}' has multiple variants "
                        f"({sorted(seen)}). Manual selection of a variant is required."
                    )

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
                            "payment_date": pay.paymentDate,
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
                    is_gratis = hasattr(pay, "gratis") and pay.gratis
                    if ratio_present:
                        self._validate_stock_split(
                            security=security,
                            reconciliation_date=reconciliation_date,
                            quantity=quantity,
                            ratio_present=ratio_present,
                            ratio_new=ratio_new,
                            valor_number_new=valor_number_new,
                            is_gratis=is_gratis,
                            payment_date=pay.paymentDate,
                            all_tax_event_dates=all_kl_tax_event_dates,
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
                    payment_name = self._translate("dividend")
                else:
                    payment_name = self._translate("distribution")
            elif pay.paymentType == PaymentTypeESTV.GRATIS:
                payment_name = self._translate("stock_dividend")
            elif pay.paymentType == PaymentTypeESTV.OTHER_BENEFIT:
                payment_name = self._translate("other_monetary_benefits")
            elif pay.paymentType == PaymentTypeESTV.AGIO:
                payment_name = self._translate("premium_agio")
            elif pay.paymentType == PaymentTypeESTV.FUND_ACCUMULATION:
                payment_name = self._translate("taxable_income_from_accumulating_fund")

            # Preserve the original payment subtype only when it is explicitly non-standard.
            # Standard is the default and should remain unset so VERIFY mode does not fail
            # against XML inputs that never contained this internal metadata field.
            payment_type_original = None
            if pay.paymentType is not None and pay.paymentType != PaymentTypeESTV.STANDARD:
                payment_type_original = PaymentTypeOriginal(pay.paymentType.value)

            if pay.undefined:
                sec_payment = SecurityPayment(
                    paymentDate=pay.paymentDate,
                    exDate=pay.exDate,
                    name=payment_name,
                    quotationType=security.quotationType,
                    quantity=quantity,
                    amountCurrency=security.currency,
                    kursliste=True,
                    payment_type_original=payment_type_original,
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

            if quantity < Decimal("0") and (amount < Decimal("0") or chf_amount < Decimal("0")):
                logger.warning(
                    f"Negative payment amount for {security.isin or security.securityName} on {pay.paymentDate}: {amount} {pay.currency}. "
                    f"Position: {quantity} on record date {pay.exDate-timedelta(days=1)}. "
                    "Please verify this payment manually. Negative dividends are not tax-deductible."
                )
                amount = Decimal("0")
                chf_amount = Decimal("0")

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
                payment_type_original=payment_type_original,
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
            # All payments have taxable revenue (grossRevenueA/B) and withholding tax claim.
            # The withHoldingTax flag from Kursliste is authoritative.
            # Only STANDARD payment types get DA-1 reclaim calculation.
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

            # DA-1 reclaim is only computed for STANDARD payment types
            if pay.paymentType is None or pay.paymentType == PaymentTypeESTV.STANDARD:
                da1_security_group = kl_sec.securityGroup
                da1_security_type = kl_sec.securityType
                if effective_sign == "(Q)":
                    # Q sign forces treatment like shares for DA-1 purposes,
                    # e.g. for an ETF which would be FUND.DISTRIBUTING.
                    da1_security_group = SecurityGroupESTV.SHARE
                    da1_security_type = None

                da1_rate = accessor.get_da1_rate(
                    kl_sec.country,
                    da1_security_group,
                    da1_security_type,
                    reference_date=pay.paymentDate,
                )

                if da1_rate and effective_sign != "(Z)":
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
