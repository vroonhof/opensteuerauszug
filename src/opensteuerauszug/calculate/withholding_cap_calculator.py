"""Cap Kursliste withholding tax at the broker's effective level.

After IBKR's 1042-S reclassification, interest-related dividends from a RIC
are exempt from US tax, so the broker reverses the withholding.

This calculator compares the broker's net withholding against the Kursliste
value and, when the broker's effective withholding is lower, adjusts the
payment:

* Broker WHT ≈ 0  →  full reversal: all income moves to ``grossRevenueB``,
  WHT is zeroed, ``(Q)`` sign is cleared.
* Broker WHT ≈ Kursliste WHT  →  no change.
* Broker WHT is in between  →  for ``nonRecoverableTaxAmount`` the partial
  amount is applied; for ``withHoldingTaxClaim`` this is an error.

The calculator is run as a separate step in the CALCULATE phase, before
``TotalCalculator``, so that it works regardless of whether payment
reconciliation is enabled.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from opensteuerauszug.model.ech0196 import (
    Security,
    SecurityPayment,
    TaxStatement,
)

logger = logging.getLogger(__name__)


class WithholdingCapCalculator:
    """Cap Kursliste withholding to the broker's effective level."""

    def __init__(self, tolerance_chf: Decimal = Decimal("0.05")):
        self.tolerance_chf = tolerance_chf
        self.capped_securities: Dict[str, List[date]] = {}

    def calculate(self, tax_statement: TaxStatement) -> TaxStatement:
        if not tax_statement.listOfSecurities or not tax_statement.listOfSecurities.depot:
            return tax_statement

        for depot in tax_statement.listOfSecurities.depot:
            for security in depot.security:
                self._apply_withholding_cap(security)

        return tax_statement

    # ------------------------------------------------------------------

    def _apply_withholding_cap(self, security: Security) -> None:
        broker_payments = security.broker_payments or [
            p for p in security.payment if not p.kursliste
        ]
        kursliste_payments = [p for p in security.payment if p.kursliste]

        if not broker_payments or not kursliste_payments:
            return

        # Only consider Kursliste payments that carry withholding.
        wht_payments = [
            p for p in kursliste_payments
            if (p.withHoldingTaxClaim or Decimal("0")) + (p.nonRecoverableTaxAmount or Decimal("0")) > Decimal("0")
        ]
        if not wht_payments:
            return

        # Aggregate broker withholding by payment date.
        broker_wht_by_date: Dict[date, _BrokerWhtAgg] = defaultdict(_BrokerWhtAgg)
        for p in broker_payments:
            agg = broker_wht_by_date[p.paymentDate]
            self._accumulate_broker_wht(agg, p)

        # Collect Kursliste exchange rates by date.
        kurs_rate_by_date: Dict[date, Optional[Decimal]] = {}
        for p in kursliste_payments:
            if p.paymentDate not in kurs_rate_by_date and p.exchangeRate is not None:
                kurs_rate_by_date[p.paymentDate] = p.exchangeRate

        for kl_payment in wht_payments:
            d = kl_payment.paymentDate
            broker_agg = broker_wht_by_date.get(d)
            if broker_agg is None or broker_agg.currency is None:
                continue

            rate = kurs_rate_by_date.get(d)
            if rate is None:
                continue

            # Convert broker WHT to CHF, avoiding double conversion when
            # the amount is already in CHF (withHoldingTaxClaim path).
            if broker_agg.currency == "CHF":
                broker_wht_chf = broker_agg.total
            else:
                broker_wht_chf = broker_agg.total * rate

            # Clamp at zero to avoid negative withholding claims.
            broker_wht_chf = max(Decimal("0"), broker_wht_chf)

            # Kursliste WHT may use withHoldingTaxClaim or nonRecoverableTaxAmount.
            kurs_wht_chf = (
                (kl_payment.withHoldingTaxClaim or Decimal("0"))
                + (kl_payment.nonRecoverableTaxAmount or Decimal("0"))
            )

            # No cap needed when broker WHT is at or above kursliste.
            if broker_wht_chf >= kurs_wht_chf - self.tolerance_chf:
                continue

            # A cap is needed. Check for multiple WHT payments on the same
            # date — we can only error now that we know a cap would apply.
            same_date_wht = [p for p in wht_payments if p.paymentDate == d]
            if len(same_date_wht) > 1:
                raise ValueError(
                    f"Multiple Kursliste payments with withholding on the same "
                    f"date for {security.securityName} on {d}. "
                    f"Cannot apply withholding cap."
                )

            # Decide whether this is a full reversal (≈0) or partial.
            if broker_wht_chf <= self.tolerance_chf:
                # Full reversal – move everything to grossRevenueB (no WHT).
                self._apply_full_reversal(security, kl_payment, kurs_wht_chf, d)
            elif kl_payment.nonRecoverableTaxAmount is not None and kl_payment.nonRecoverableTaxAmount > Decimal("0"):
                # Partial cap is supported for nonRecoverableTaxAmount.
                self._apply_partial_cap(security, kl_payment, kurs_wht_chf, broker_wht_chf, d)
            else:
                # Fractional withHoldingTaxClaim is not supported.
                raise ValueError(
                    f"Fractional withholding cap not supported for "
                    f"{security.securityName} on {d}: broker WHT "
                    f"{broker_wht_chf:.2f} CHF is neither ≈0 nor ≈equal to "
                    f"Kursliste {kurs_wht_chf:.2f} CHF. Please check the "
                    f"corrections flex data."
                )

    def _apply_full_reversal(
        self,
        security: Security,
        kl_payment: SecurityPayment,
        original_wht_chf: Decimal,
        d: date,
    ) -> None:
        """Zero out WHT and move all gross revenue to the B column."""
        old_a = kl_payment.grossRevenueA or Decimal("0")
        old_b = kl_payment.grossRevenueB or Decimal("0")
        total_gross = (old_a + old_b).quantize(Decimal("0.01"))

        # Store original values for reconciliation reporting.
        kl_payment.withholding_capped = True
        kl_payment.withholding_capped_original_wht_chf = original_wht_chf

        # Zero the WHT fields that were set.
        if kl_payment.withHoldingTaxClaim is not None:
            kl_payment.withHoldingTaxClaim = Decimal("0.00")
        if kl_payment.nonRecoverableTaxAmount is not None:
            kl_payment.nonRecoverableTaxAmount = Decimal("0.00")

        # Move everything to grossRevenueB (no WHT).
        kl_payment.grossRevenueA = Decimal("0.00")
        kl_payment.grossRevenueB = total_gross
        # Only clear (Q) sign specifically.
        if kl_payment.sign == "(Q)":
            kl_payment.sign = None

        self._track(security.securityName, d)

        logger.info(
            "Capped withholding for %s on %s: Kursliste %.2f CHF → 0.00 CHF "
            "(full reversal)",
            security.securityName,
            d,
            original_wht_chf,
        )

    def _apply_partial_cap(
        self,
        security: Security,
        kl_payment: SecurityPayment,
        original_wht_chf: Decimal,
        broker_wht_chf: Decimal,
        d: date,
    ) -> None:
        """Cap nonRecoverableTaxAmount to the broker's effective level."""
        capped_wht = broker_wht_chf.quantize(Decimal("0.01"))
        surplus_chf = (original_wht_chf - capped_wht).quantize(Decimal("0.01"))

        old_a = kl_payment.grossRevenueA or Decimal("0")
        old_b = kl_payment.grossRevenueB or Decimal("0")

        # Store original values for reconciliation reporting.
        kl_payment.withholding_capped = True
        kl_payment.withholding_capped_original_wht_chf = original_wht_chf

        kl_payment.nonRecoverableTaxAmount = capped_wht
        kl_payment.grossRevenueA = (old_a - surplus_chf).quantize(Decimal("0.01"))
        kl_payment.grossRevenueB = (old_b + surplus_chf).quantize(Decimal("0.01"))
        # Only clear (Q) sign specifically.
        if kl_payment.sign == "(Q)":
            kl_payment.sign = None

        self._track(security.securityName, d)

        logger.info(
            "Capped withholding for %s on %s: Kursliste %.2f CHF → broker %.2f CHF "
            "(partial cap on nonRecoverableTaxAmount)",
            security.securityName,
            d,
            original_wht_chf,
            capped_wht,
        )

    def _track(self, sec_name: str, d: date) -> None:
        self.capped_securities.setdefault(sec_name, []).append(d)

    @staticmethod
    def _accumulate_broker_wht(agg: _BrokerWhtAgg, payment: SecurityPayment) -> None:
        """Sum broker withholding for a single payment into *agg*."""
        wht_claim = payment.withHoldingTaxClaim
        non_recov = payment.nonRecoverableTaxAmountOriginal

        if wht_claim is not None and wht_claim != 0:
            agg.total += wht_claim
            agg.currency = "CHF"
        elif non_recov is not None and non_recov != 0:
            agg.total += non_recov
            agg.currency = payment.amountCurrency


class _BrokerWhtAgg:
    """Accumulator for broker withholding on a single date."""

    __slots__ = ("total", "currency")

    def __init__(self) -> None:
        self.total: Decimal = Decimal("0")
        self.currency: Optional[str] = None
