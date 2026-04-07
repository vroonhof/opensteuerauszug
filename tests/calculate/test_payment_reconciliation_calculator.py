from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.calculate.payment_reconciliation_calculator import (
    PaymentReconciliationCalculator,
)
from opensteuerauszug.model.ech0196 import (
    Depot,
    DepotNumber,
    ISINType,
    ListOfSecurities,
    Security,
    SecurityPayment,
    PaymentTypeOriginal,
    TaxStatement,
)


def test_non_chf_withholding_is_compared_via_original_currency_and_marked_match():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="NL",
                            currency="EUR",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="ASML",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 2, 19),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="EUR",
                                    amount=Decimal("10"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueB=Decimal("10"),
                                    nonRecoverableTaxAmount=Decimal("1.13"),
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 2, 19),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="EUR",
                                    amount=Decimal("10"),
                                    name="Dividend",
                                    broker_label_original="Dividends",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 2, 19),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="EUR",
                                    amount=Decimal("-1.13"),
                                    name="Withholding",
                                    broker_label_original="Withholding Tax",
                                    nonRecoverableTaxAmountOriginal=Decimal("1.13"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)

    assert result.payment_reconciliation_report is not None
    assert len(result.payment_reconciliation_report.rows) == 1
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "match"
    assert row.matched is True


def test_accumulating_fund_without_broker_cashflow_is_expected():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="IE",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="FUND",
                            securityName="Accum ETF",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 7, 1),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="USD",
                                    amount=Decimal("1"),
                                    exchangeRate=Decimal("0.9"),
                                    grossRevenueB=Decimal("0.9"),
                                    name="Taxable Income from Accumulating Fund",
                                    kursliste=True,
                                    payment_type_original=PaymentTypeOriginal.FUND_ACCUMULATION,
                                )
                            ],
                            broker_payments=[],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)

    assert result.payment_reconciliation_report is not None
    assert len(result.payment_reconciliation_report.rows) == 1
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "expected"
    assert row.matched is True


def test_mixed_cash_and_noncash_same_date_allows_broker_cash_below_kursliste_total():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="FUND",
                            securityName="VT",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="USD",
                                    amount=Decimal("1200"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueB=Decimal("1200"),
                                    kursliste=True,
                                    payment_type_original=PaymentTypeOriginal.FUND_ACCUMULATION,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("900"),
                                    name="Dividend",
                                )
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "match"
    assert row.matched is True


def test_broker_above_kursliste_without_allowlist_is_mismatch():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="GOOG",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="USD",
                                    amount=Decimal("100"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueB=Decimal("100"),
                                    withHoldingTaxClaim=Decimal("10"),
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("120"),
                                    name="Dividend",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("-12"),
                                    name="Withholding",
                                    nonRecoverableTaxAmountOriginal=Decimal("12"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "mismatch"


def test_per_share_fx_rounding_within_tolerance_is_match():
    """Small differences caused by per-share FX rounding (Kursliste rounds
    per-share CHF, then multiplies by quantity) should be within tolerance.
    Real-world example: 272 shares × USD 1.26, exchange rate ~0.8819."""
    exchange_rate = Decimal("0.88177")
    broker_div_usd = Decimal("342.72")  # 272 * 1.26
    broker_wht_usd = Decimal("51.41")
    # Kursliste rounds per-share: round(1.26 * 0.88177, 3) = 1.111 → 272 * 1.111 = 302.192
    kl_div_chf = Decimal("302.192")
    kl_wht_chf = Decimal("45.3288")
    # broker_div_chf = 342.72 * 0.88177 ≈ 302.199 → delta ≈ 0.207 CHF (0.07%)

    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="KIMBERLY-CLARK CORP",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 4, 2),
                                    quotationType="PIECE",
                                    quantity=Decimal("272"),
                                    amountCurrency="USD",
                                    amount=broker_div_usd,
                                    exchangeRate=exchange_rate,
                                    grossRevenueB=kl_div_chf,
                                    withHoldingTaxClaim=kl_wht_chf,
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 4, 2),
                                    quotationType="PIECE",
                                    quantity=Decimal("-272"),
                                    amountCurrency="USD",
                                    amount=broker_div_usd,
                                    name="Dividend",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 4, 2),
                                    quotationType="PIECE",
                                    quantity=Decimal("-272"),
                                    amountCurrency="USD",
                                    amount=-broker_wht_usd,
                                    name="Withholding Tax",
                                    nonRecoverableTaxAmountOriginal=broker_wht_usd,
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "match"
    assert row.matched is True


def test_broker_above_kursliste_with_allowlisted_h_sign_is_match():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="IBM",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="USD",
                                    amount=Decimal("100"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueB=Decimal("100"),
                                    withHoldingTaxClaim=Decimal("10"),
                                    sign="(H)",
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("120"),
                                    name="Dividend",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("-12"),
                                    name="Withholding",
                                    nonRecoverableTaxAmountOriginal=Decimal("12"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "match"

def test_broker_above_kursliste_with_allowlisted_sign_is_match():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="MSFT",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="USD",
                                    amount=Decimal("100"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueB=Decimal("100"),
                                    withHoldingTaxClaim=Decimal("10"),
                                    sign="KEP",
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("120"),
                                    name="Dividend",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("-12"),
                                    name="Withholding",
                                    nonRecoverableTaxAmountOriginal=Decimal("12"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "match"


def test_broker_above_kursliste_with_allowlisted_broker_keyword_is_match():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="CH",
                            currency="CHF",
                            quotationType="PIECE",
                            securityCategory="FUND",
                            securityName="CHSPI",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 7, 17),
                                    quotationType="PIECE",
                                    quantity=Decimal("100"),
                                    amountCurrency="CHF",
                                    amount=Decimal("44"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueA=Decimal("44"),
                                    withHoldingTaxClaim=Decimal("15.40"),
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 7, 17),
                                    quotationType="PIECE",
                                    quantity=Decimal("-100"),
                                    amountCurrency="CHF",
                                    amount=Decimal("44"),
                                    name="Ordinary Dividend",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 7, 17),
                                    quotationType="PIECE",
                                    quantity=Decimal("-100"),
                                    amountCurrency="CHF",
                                    amount=Decimal("40"),
                                    name="Return of Capital",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 7, 17),
                                    quotationType="PIECE",
                                    quantity=Decimal("-100"),
                                    amountCurrency="CHF",
                                    amount=Decimal("-15.40"),
                                    name="Withholding",
                                    nonRecoverableTaxAmountOriginal=Decimal("15.40"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "match"


def test_broker_withholding_above_kursliste_is_match_for_germany():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="DE",
                            currency="EUR",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="SIXT SE",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="EUR",
                                    amount=Decimal("100"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueB=Decimal("100"),
                                    withHoldingTaxClaim=Decimal("10"),
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="EUR",
                                    amount=Decimal("100"),
                                    name="Dividend",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="EUR",
                                    amount=Decimal("-12"),
                                    name="Withholding",
                                    nonRecoverableTaxAmountOriginal=Decimal("12"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "match"
    assert row.matched is True


def test_broker_withholding_above_kursliste_is_mismatch_for_treaty_security():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="AAPL",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="USD",
                                    amount=Decimal("100"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueB=Decimal("100"),
                                    withHoldingTaxClaim=Decimal("10"),
                                    additionalWithHoldingTaxUSA=Decimal("0"),
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("100"),
                                    name="Dividend",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("-12"),
                                    name="Withholding",
                                    nonRecoverableTaxAmountOriginal=Decimal("12"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "mismatch"
    assert row.matched is False


def test_negligible_kursliste_values_allow_missing_broker_entry():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="SMALL",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 24),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="USD",
                                    amount=Decimal("0.001"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueB=Decimal("0.009"),
                                    withHoldingTaxClaim=Decimal("0.000"),
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "match"
    assert row.matched is True


def test_explicit_zero_kursliste_entry_with_broker_cash_is_mismatch_without_allowlist():
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="VT",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("1"),
                                    amountCurrency="USD",
                                    amount=Decimal("0"),
                                    exchangeRate=Decimal("1"),
                                    grossRevenueB=Decimal("0"),
                                    withHoldingTaxClaim=Decimal("0"),
                                    kursliste=True,
                                )
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 12, 23),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("25"),
                                    name="Dividend",
                                )
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    result = PaymentReconciliationCalculator().calculate(statement)
    row = result.payment_reconciliation_report.rows[0]
    assert row.status == "mismatch"
    assert row.matched is False


# --------------------------------------------------------------------------- #
#  Issue #308: Withholding-tax cap for (Q)-signed payments
# --------------------------------------------------------------------------- #

def _make_bnd_statement(broker_wht_amounts, kurs_wht_chf, kurs_gross_a_chf,
                         exchange_rate=Decimal("0.90")):
    """Helper: build a TaxStatement for BND with given broker WHT amounts
    and a single Kursliste payment with sign (Q)."""
    broker_payments = []
    for amt in broker_wht_amounts:
        p = SecurityPayment(
            paymentDate=date(2025, 11, 5),
            quotationType="PIECE",
            quantity=Decimal("-1"),
            amountCurrency="USD",
        )
        if amt < 0:
            p.nonRecoverableTaxAmountOriginal = abs(amt)
        elif amt > 0:
            # Refund
            p.nonRecoverableTaxAmountOriginal = -amt
        else:
            p.amount = Decimal("0")
        broker_payments.append(p)

    return TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="FUND",
                            securityName="VANGUARD TOTAL BOND MARKET (BND)",
                            isin=ISINType("US9219378356"),
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("254"),
                                    amountCurrency="USD",
                                    exchangeRate=exchange_rate,
                                    grossRevenueA=kurs_gross_a_chf,
                                    grossRevenueB=Decimal("0"),
                                    withHoldingTaxClaim=kurs_wht_chf,
                                    kursliste=True,
                                    sign="(Q)",
                                ),
                            ],
                            broker_payments=broker_payments,
                        )
                    ],
                )
            ]
        ),
    )


# ---------------------------------------------------------------------------
# WithholdingCapCalculator tests
# ---------------------------------------------------------------------------

from opensteuerauszug.calculate.withholding_cap_calculator import WithholdingCapCalculator


def test_withholding_cap_full_reversal_zeros_withholding():
    """When broker fully reverses WHT (e.g. SGOV), withholding should be zero
    and sign (Q) cleared, with all income in grossRevenueB."""
    # SGOV: 100% interest-related → full reversal, net WHT = 0
    statement = _make_bnd_statement(
        broker_wht_amounts=[Decimal("-30.00"), Decimal("30.00")],
        kurs_wht_chf=Decimal("4.50"),
        kurs_gross_a_chf=Decimal("30.00"),
        exchange_rate=Decimal("0.90"),
    )

    calculator = WithholdingCapCalculator()
    result = calculator.calculate(statement)

    sec = result.listOfSecurities.depot[0].security[0]
    kl_payment = next(p for p in sec.payment if p.kursliste)

    # Full reversal → 0 CHF withholding
    assert kl_payment.withHoldingTaxClaim == Decimal("0.00")
    assert kl_payment.sign is None
    # All income moves to grossRevenueB (no WHT)
    assert kl_payment.grossRevenueA == Decimal("0.00")
    assert kl_payment.grossRevenueB == Decimal("30.00")
    # Capping metadata
    assert kl_payment.withholding_capped is True
    assert kl_payment.withholding_capped_original_wht_chf == Decimal("4.50")


def test_withholding_cap_no_change_when_broker_matches():
    """No cap should be applied when broker WHT matches Kursliste."""
    statement = _make_bnd_statement(
        broker_wht_amounts=[Decimal("-9.28")],
        kurs_wht_chf=Decimal("8.35"),
        kurs_gross_a_chf=Decimal("55.67"),
        exchange_rate=Decimal("0.90"),
    )

    calculator = WithholdingCapCalculator()
    result = calculator.calculate(statement)

    sec = result.listOfSecurities.depot[0].security[0]
    kl_payment = next(p for p in sec.payment if p.kursliste)

    # Broker WHT in CHF: 9.28 * 0.90 = 8.352, which is above 8.35
    # No cap should be applied
    assert kl_payment.withHoldingTaxClaim == Decimal("8.35")
    assert kl_payment.sign == "(Q)"
    assert kl_payment.withholding_capped is False


def test_withholding_cap_fractional_raises_error():
    """Fractional withholding (neither 0 nor equal to Kursliste) should
    raise an error."""
    # Broker: original -61.83, reversal +61.83, new -4.70 → net = 4.70 USD
    # At exchange rate 0.90 → 4.23 CHF – between 0 and 8.35
    statement = _make_bnd_statement(
        broker_wht_amounts=[Decimal("-61.83"), Decimal("61.83"), Decimal("-4.70")],
        kurs_wht_chf=Decimal("8.35"),
        kurs_gross_a_chf=Decimal("55.67"),
        exchange_rate=Decimal("0.90"),
    )

    calculator = WithholdingCapCalculator()
    with pytest.raises(ValueError, match="Fractional swiss withholding cap not supported"):
        calculator.calculate(statement)


def test_withholding_cap_multiple_wht_same_date_raises_error_when_cap_needed():
    """Multiple Kursliste payments with WHT on the same date should raise an
    error only when a cap would actually be applied (broker < kursliste)."""
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="FUND",
                            securityName="TEST FUND",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("100"),
                                    amountCurrency="USD",
                                    exchangeRate=Decimal("0.90"),
                                    grossRevenueA=Decimal("10.00"),
                                    withHoldingTaxClaim=Decimal("1.50"),
                                    kursliste=True,
                                    sign="(Q)",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("100"),
                                    amountCurrency="USD",
                                    exchangeRate=Decimal("0.90"),
                                    grossRevenueA=Decimal("5.00"),
                                    withHoldingTaxClaim=Decimal("0.75"),
                                    kursliste=True,
                                    sign="(Q)",
                                ),
                            ],
                            broker_payments=[
                                # Broker WHT is 0 → cap needed → error
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    nonRecoverableTaxAmountOriginal=Decimal("1.00"),
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    nonRecoverableTaxAmountOriginal=Decimal("-1.00"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    calculator = WithholdingCapCalculator()
    with pytest.raises(ValueError, match="Multiple.*same date"):
        calculator.calculate(statement)


def test_withholding_cap_multiple_wht_same_date_ok_when_no_cap_needed():
    """Multiple Kursliste payments with WHT on the same date should NOT error
    when broker WHT is at or above kursliste (no cap needed)."""
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="FUND",
                            securityName="TEST FUND",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("100"),
                                    amountCurrency="USD",
                                    exchangeRate=Decimal("0.90"),
                                    grossRevenueA=Decimal("10.00"),
                                    withHoldingTaxClaim=Decimal("1.50"),
                                    kursliste=True,
                                    sign="(Q)",
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("100"),
                                    amountCurrency="USD",
                                    exchangeRate=Decimal("0.90"),
                                    grossRevenueA=Decimal("5.00"),
                                    withHoldingTaxClaim=Decimal("0.75"),
                                    kursliste=True,
                                    sign="(Q)",
                                ),
                            ],
                            broker_payments=[
                                # Broker WHT is high → no cap needed → no error
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    nonRecoverableTaxAmountOriginal=Decimal("10.00"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    calculator = WithholdingCapCalculator()
    # Should not raise — broker is above kursliste, no cap needed
    result = calculator.calculate(statement)
    sec = result.listOfSecurities.depot[0].security[0]
    # Both payments should be unchanged
    for p in sec.payment:
        assert p.withholding_capped is False


def test_withholding_cap_reconciliation_shows_capped_status():
    """After WithholdingCapCalculator runs, reconciliation should report
    'capped' status with original Kursliste values."""
    statement = _make_bnd_statement(
        broker_wht_amounts=[Decimal("-30.00"), Decimal("30.00")],
        kurs_wht_chf=Decimal("4.50"),
        kurs_gross_a_chf=Decimal("30.00"),
        exchange_rate=Decimal("0.90"),
    )

    # First run cap calculator
    cap_calc = WithholdingCapCalculator()
    statement = cap_calc.calculate(statement)

    # Then run reconciliation
    recon_calc = PaymentReconciliationCalculator()
    statement = recon_calc.calculate(statement)

    report = statement.payment_reconciliation_report
    assert report is not None
    assert report.capped_count == 1

    capped_rows = [r for r in report.rows if r.status == "capped"]
    assert len(capped_rows) == 1
    assert "0.00 CHF" in capped_rows[0].note


def test_withholding_cap_applies_to_payments_without_q_sign():
    """Cap should apply to all Kursliste payments with WHT, not just (Q)."""
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="FUND",
                            securityName="TEST NO-Q FUND",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 6, 15),
                                    quotationType="PIECE",
                                    quantity=Decimal("100"),
                                    amountCurrency="USD",
                                    exchangeRate=Decimal("0.90"),
                                    grossRevenueA=Decimal("20.00"),
                                    grossRevenueB=Decimal("0"),
                                    withHoldingTaxClaim=Decimal("3.00"),
                                    kursliste=True,
                                    sign=None,  # No (Q) sign
                                ),
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 6, 15),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    nonRecoverableTaxAmountOriginal=Decimal("5.00"),
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 6, 15),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    nonRecoverableTaxAmountOriginal=Decimal("-5.00"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    calculator = WithholdingCapCalculator()
    result = calculator.calculate(statement)

    sec = result.listOfSecurities.depot[0].security[0]
    kl_payment = next(p for p in sec.payment if p.kursliste)

    assert kl_payment.withHoldingTaxClaim == Decimal("0.00")
    assert kl_payment.grossRevenueA == Decimal("0.00")
    assert kl_payment.grossRevenueB == Decimal("20.00")
    assert kl_payment.withholding_capped is True


def test_withholding_cap_partial_for_non_recoverable_tax():
    """Partial cap should be supported when the WHT uses nonRecoverableTaxAmount
    (foreign securities)."""
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="FUND",
                            securityName="BND PARTIAL",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("254"),
                                    amountCurrency="USD",
                                    exchangeRate=Decimal("0.90"),
                                    grossRevenueA=0,
                                    grossRevenueB=Decimal("55.67"),
                                    nonRecoverableTaxAmount=Decimal("8.35"),
                                    kursliste=True,
                                    sign="(Q)",
                                ),
                            ],
                            broker_payments=[
                                # Net broker WHT: -61.83 + 61.83 - 4.70 = -4.70 USD
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    nonRecoverableTaxAmountOriginal=Decimal("61.83"),
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    nonRecoverableTaxAmountOriginal=Decimal("-61.83"),
                                ),
                                SecurityPayment(
                                    paymentDate=date(2025, 11, 5),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    nonRecoverableTaxAmountOriginal=Decimal("4.70"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    calculator = WithholdingCapCalculator()
    result = calculator.calculate(statement)

    sec = result.listOfSecurities.depot[0].security[0]
    kl_payment = next(p for p in sec.payment if p.kursliste)

    # Broker WHT: 4.70 * 0.90 = 4.23 CHF
    assert kl_payment.nonRecoverableTaxAmount == Decimal("4.23")
    assert kl_payment.withholding_capped is True
    assert kl_payment.withholding_capped_original_wht_chf == Decimal("8.35")
    # (Q) sign should be cleared
    assert kl_payment.sign is None

def test_withholding_cap_only_clears_q_sign():
    """Full reversal should only clear (Q) sign, not other signs."""
    statement = _make_bnd_statement(
        broker_wht_amounts=[Decimal("-30.00"), Decimal("30.00")],
        kurs_wht_chf=Decimal("4.50"),
        kurs_gross_a_chf=Decimal("30.00"),
        exchange_rate=Decimal("0.90"),
    )
    # Change sign to something other than (Q)
    sec = statement.listOfSecurities.depot[0].security[0]
    kl_payment = next(p for p in sec.payment if p.kursliste)
    kl_payment.sign = "(H)"

    calculator = WithholdingCapCalculator()
    result = calculator.calculate(statement)

    sec = result.listOfSecurities.depot[0].security[0]
    kl_payment = next(p for p in sec.payment if p.kursliste)

    # WHT should be zeroed
    assert kl_payment.withHoldingTaxClaim == Decimal("0.00")
    assert kl_payment.withholding_capped is True
    # (H) sign should NOT be cleared
    assert kl_payment.sign == "(H)"


def test_withholding_cap_zeros_when_broker_has_no_wht_entries():
    """When broker has dividend payments on a date but no Withholding Tax entries
    (e.g. Payment In Lieu with no tax deducted), nonRecoverableTaxAmount should
    be capped at 0 (full reversal)."""
    statement = TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="LU",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="ARCELORMITTAL-NY REGISTERED",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 6, 11),
                                    quotationType="PIECE",
                                    quantity=Decimal("950"),
                                    amountCurrency="USD",
                                    exchangeRate=Decimal("0.90"),
                                    grossRevenueA=Decimal("0"),
                                    grossRevenueB=Decimal("55.00"),
                                    nonRecoverableTaxAmount=Decimal("8.25"),
                                    kursliste=True,
                                    sign="(Q)",
                                ),
                            ],
                            broker_payments=[
                                # Dividend payment but NO Withholding Tax entry
                                SecurityPayment(
                                    paymentDate=date(2025, 6, 11),
                                    quotationType="PIECE",
                                    quantity=Decimal("-1"),
                                    amountCurrency="USD",
                                    amount=Decimal("261.25"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    calculator = WithholdingCapCalculator()
    result = calculator.calculate(statement)

    sec = result.listOfSecurities.depot[0].security[0]
    kl_payment = next(p for p in sec.payment if p.kursliste)

    assert kl_payment.nonRecoverableTaxAmount == Decimal("0.00")
    assert kl_payment.withholding_capped is True
    assert kl_payment.withholding_capped_original_wht_chf == Decimal("8.25")
    assert kl_payment.sign is None

