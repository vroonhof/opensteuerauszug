"""Shared SecurityPayment construction helpers.

Both the IBKR and Fidelity importers build a ``SecurityPayment`` from a
small, fixed set of inputs: a date, a description, a currency, an
amount, and a pair of flags (is this a withholding-tax event? is this a
payment-in-lieu / securities-lending event?).

The *classification* — whether a given broker row is a withholding event
— differs per importer (ibflex enum vs Fidelity string), so we accept
it as two booleans and let each importer decide.  No inheritance
required.
"""

from datetime import date
from decimal import Decimal

from opensteuerauszug.model.ech0196 import SecurityPayment


def apply_withholding_tax_fields(
    payment: SecurityPayment,
    amount: Decimal,
    currency: str,
) -> None:
    """Populate the withholding-tax fields of *payment* from *amount*.

    The sign and currency convention is preserved across importers:
      * amount < 0 in CHF         → ``withHoldingTaxClaim = |amount|``
      * amount < 0 in non-CHF     → ``nonRecoverableTaxAmountOriginal = |amount|``
      * amount > 0 (reversal)     → ``nonRecoverableTaxAmountOriginal = -amount``

    Callers must only invoke this when they have already classified the
    row as a withholding event.
    """
    if amount < 0:
        if currency == "CHF":
            payment.withHoldingTaxClaim = abs(amount)
        else:
            payment.nonRecoverableTaxAmountOriginal = abs(amount)
    elif amount > 0:
        payment.nonRecoverableTaxAmountOriginal = -amount


def build_security_payment(
    *,
    payment_date: date,
    description: str,
    currency: str,
    amount: Decimal,
    broker_label: str,
    is_withholding: bool = False,
    is_securities_lending: bool = False,
) -> SecurityPayment:
    """Build a ``SecurityPayment`` and apply the common post-processing.

    ``is_withholding`` triggers :func:`apply_withholding_tax_fields`.
    ``is_securities_lending`` sets ``securitiesLending=True`` (used by
    IBKR ``PAYMENTINLIEU`` and Fidelity ``Cash In Lieu``).

    ``broker_label`` is stored on ``SecurityPayment.broker_label_original``
    for later traceability / reconciliation.
    """
    payment = SecurityPayment(
        paymentDate=payment_date,
        name=description,
        amountCurrency=currency,
        amount=amount,
        quotationType="PIECE",
        quantity=None,
        broker_label_original=broker_label,
    )
    if is_securities_lending:
        payment.securitiesLending = True
    if is_withholding:
        apply_withholding_tax_fields(payment, amount, currency)
    return payment
