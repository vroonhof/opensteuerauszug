from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from opensteuerauszug.model.ech0196 import (
    PaymentTypeOriginal,
    Security,
    SecurityPayment,
    TaxStatement,
)
from opensteuerauszug.model.payment_reconciliation import (
    PaymentReconciliationReport,
    PaymentReconciliationRow,
)


@dataclass
class _BrokerAgg:
    dividend: Decimal = Decimal("0")
    dividend_currency: Optional[str] = None
    withholding: Decimal = Decimal("0")
    withholding_currency: Optional[str] = None
    withholding_entry_text: Optional[str] = None


@dataclass
class _KurslisteAgg:
    dividend_chf: Decimal = Decimal("0")
    withholding_chf: Decimal = Decimal("0")
    exchange_rate: Optional[Decimal] = None
    noncash: bool = False


class PaymentReconciliationCalculator:
    def __init__(self, tolerance_chf: Decimal = Decimal("0.05")):
        self.tolerance_chf = tolerance_chf

    def calculate(self, tax_statement: TaxStatement) -> TaxStatement:
        report = PaymentReconciliationReport()

        if not tax_statement.listOfSecurities or not tax_statement.listOfSecurities.depot:
            tax_statement.payment_reconciliation_report = report
            return tax_statement

        for depot in tax_statement.listOfSecurities.depot:
            for security in depot.security:
                rows = self._reconcile_security(security)
                report.rows.extend(rows)

        for row in report.rows:
            if row.status == "match":
                report.match_count += 1
            elif row.status == "expected":
                report.expected_missing_count += 1
            else:
                report.mismatch_count += 1

        tax_statement.payment_reconciliation_report = report
        return tax_statement

    def _reconcile_security(self, security: Security) -> List[PaymentReconciliationRow]:
        broker_payments = security.broker_payments or [p for p in security.payment if not p.kursliste]
        kursliste_payments = [p for p in security.payment if p.kursliste]

        broker_by_date: Dict[date, _BrokerAgg] = defaultdict(_BrokerAgg)
        kurs_by_date: Dict[date, _KurslisteAgg] = defaultdict(_KurslisteAgg)

        for payment in broker_payments:
            key_date = payment.paymentDate
            agg = broker_by_date[key_date]
            self._accumulate_broker(agg, payment)

        for payment in kursliste_payments:
            key_date = payment.paymentDate
            agg = kurs_by_date[key_date]
            self._accumulate_kursliste(agg, payment)

        all_dates = sorted(set(broker_by_date.keys()) | set(kurs_by_date.keys()))
        rows: List[PaymentReconciliationRow] = []
        security_label = security.securityName
        country = security.country

        for d in all_dates:
            broker = broker_by_date.get(d, _BrokerAgg())
            kurs = kurs_by_date.get(d, _KurslisteAgg())

            has_broker = d in broker_by_date
            has_kurs = d in kurs_by_date

            broker_div_chf = None
            broker_with_chf = None
            if kurs.exchange_rate is not None:
                if broker.dividend_currency is not None:
                    broker_div_chf = broker.dividend * kurs.exchange_rate
                if broker.withholding_currency is not None:
                    broker_with_chf = broker.withholding * kurs.exchange_rate

            matched = False
            status = "mismatch"
            note = None

            if has_kurs and not has_broker and kurs.noncash:
                status = "expected"
                note = "Accumulating fund payment expected to be absent in broker cash flow."
                matched = True
            elif has_kurs and has_broker:
                div_ok = self._component_matches(
                    kurs_value_chf=kurs.dividend_chf,
                    broker_value_chf=broker_div_chf,
                    allow_bidirectional_on_noncash=kurs.noncash,
                )
                w_ok = self._component_matches(
                    kurs_value_chf=kurs.withholding_chf,
                    broker_value_chf=broker_with_chf,
                    allow_bidirectional_on_noncash=kurs.noncash,
                )
                if not div_ok:
                    note = "Broker dividend is below Kursliste value beyond tolerance."
                elif not w_ok:
                    note = "Broker withholding is below Kursliste value beyond tolerance."
                matched = div_ok and w_ok
                status = "match" if matched else "mismatch"
            elif not has_kurs and has_broker:
                note = "Broker payment has no Kursliste entry."
            elif has_kurs and not has_broker:
                if (
                    abs(kurs.dividend_chf) < Decimal("0.01")
                    and abs(kurs.withholding_chf) < Decimal("0.01")
                ):
                    status = "match"
                    matched = True
                    note = "Kursliste amounts are negligible; missing broker entry accepted."
                else:
                    note = "Kursliste payment has no broker evidence."
            else:
                status = "match"
                matched = True

            rows.append(
                PaymentReconciliationRow(
                    country=country,
                    security=security_label,
                    payment_date=d,
                    kursliste_dividend_chf=kurs.dividend_chf,
                    kursliste_withholding_chf=kurs.withholding_chf,
                    broker_dividend_amount=broker.dividend if broker.dividend_currency else None,
                    broker_dividend_currency=broker.dividend_currency,
                    broker_withholding_amount=broker.withholding if broker.withholding_currency else None,
                    broker_withholding_currency=broker.withholding_currency,
                    broker_withholding_entry_text=broker.withholding_entry_text,
                    exchange_rate=kurs.exchange_rate,
                    accumulating=kurs.noncash,
                    matched=matched,
                    status=status,
                    note=note,
                )
            )

        return rows

    def _component_matches(
        self,
        kurs_value_chf: Decimal,
        broker_value_chf: Optional[Decimal],
        allow_bidirectional_on_noncash: bool,
    ) -> bool:
        if broker_value_chf is None:
            return abs(kurs_value_chf) < Decimal("0.01")

        if allow_bidirectional_on_noncash:
            return True

        # For now, accept cases where the broker side is larger than Kursliste.
        # Mismatch is only when the broker side is materially lower.
        return broker_value_chf + self.tolerance_chf >= kurs_value_chf

    def _accumulate_broker(self, agg: _BrokerAgg, payment: SecurityPayment) -> None:
        non_recoverable_original = payment.nonRecoverableTaxAmountOriginal
        withholding_claim = payment.withHoldingTaxClaim

        if withholding_claim is not None and withholding_claim != 0:
            agg.withholding += withholding_claim
            agg.withholding_currency = "CHF"
            agg.withholding_entry_text = payment.name or payment.broker_label_original
            return

        if non_recoverable_original is not None and non_recoverable_original != 0:
            agg.withholding += non_recoverable_original
            agg.withholding_currency = payment.amountCurrency
            agg.withholding_entry_text = payment.name or payment.broker_label_original
            return

        amount = payment.amount or Decimal("0")
        agg.dividend += amount
        agg.dividend_currency = payment.amountCurrency

    def _accumulate_kursliste(self, agg: _KurslisteAgg, payment: SecurityPayment) -> None:
        agg.dividend_chf += (payment.grossRevenueA or Decimal("0")) + (payment.grossRevenueB or Decimal("0"))
        agg.withholding_chf += (
            (payment.withHoldingTaxClaim or Decimal("0"))
            + (payment.nonRecoverableTaxAmount or Decimal("0"))
        )
        if agg.exchange_rate is None and payment.exchangeRate is not None:
            agg.exchange_rate = payment.exchangeRate
        payment_type = payment.payment_type_original
        if payment_type is not None and payment_type != PaymentTypeOriginal.STANDARD:
            agg.noncash = True
