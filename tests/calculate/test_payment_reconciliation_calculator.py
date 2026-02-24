from datetime import date
from decimal import Decimal

from opensteuerauszug.calculate.payment_reconciliation_calculator import (
    PaymentReconciliationCalculator,
)
from opensteuerauszug.model.ech0196 import (
    Depot,
    DepotNumber,
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
