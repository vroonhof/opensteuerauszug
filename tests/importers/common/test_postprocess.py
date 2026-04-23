from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.importers.common import (
    CashAccountEntry,
    PositionHints,
    SecurityNameRegistry,
    SecurityPositionData,
    augment_list_of_bank_accounts,
    augment_list_of_securities,
    fold_cash_payments,
)
from opensteuerauszug.model.ech0196 import (
    BankAccountPayment,
    SecurityStock,
    TaxStatement,
)
from opensteuerauszug.model.position import SecurityPosition


def _partial_statement() -> TaxStatement:
    return TaxStatement(
        minorVersion=1,
        periodFrom=date(2024, 1, 1),
        periodTo=date(2024, 12, 31),
        taxPeriod=2024,
    )


def _buy(symbol: str, *, on: date, qty: Decimal, price: Decimal) -> SecurityStock:
    return SecurityStock(
        referenceDate=on,
        mutation=True,
        quantity=qty,
        unitPrice=price,
        balanceCurrency="USD",
        quotationType="PIECE",
        name="buy",
    )


def test_augment_securities_synthesizes_opening_and_closing_balances():
    statement = _partial_statement()
    sec_pos = SecurityPosition(depot="D1", symbol="AAPL", description="Apple (AAPL)")
    trade = _buy("AAPL", on=date(2024, 3, 1), qty=Decimal("10"), price=Decimal("100"))
    # Closing balance snapshot provided by the caller at period_end + 1
    closing = SecurityStock(
        referenceDate=date(2025, 1, 1),
        mutation=False,
        quantity=Decimal("10"),
        balanceCurrency="USD",
        quotationType="PIECE",
        unitPrice=Decimal("100"),
    )

    positions = {sec_pos: SecurityPositionData(stocks=[trade, closing], payments=[])}
    registry = SecurityNameRegistry()
    registry.update(sec_pos, "Apple Inc. (AAPL)", 10)

    augment_list_of_securities(
        statement,
        positions,
        name_registry=registry,
        hints_for=lambda _: PositionHints(security_category="SHARE", country="US"),
    )

    assert statement.listOfSecurities is not None
    depot = statement.listOfSecurities.depot[0]
    assert depot.depotNumber == "D1"
    (security,) = depot.security
    assert security.securityName == "Apple Inc. (AAPL)"
    assert security.country == "US"
    assert security.securityCategory == "SHARE"
    # Synthesized opening balance at 2024-01-01 (qty 0 before the buy)
    # -> since opening qty is 0 we don't append; we only append closing.
    # Assert the closing boundary stock at 2025-01-01 is present.
    balance_dates = sorted(
        (s.referenceDate, s.mutation, s.quantity) for s in security.stock
    )
    assert (date(2025, 1, 1), False, Decimal("10")) in balance_dates


def test_augment_securities_raises_on_negative_balance_by_default():
    statement = _partial_statement()
    sec_pos = SecurityPosition(depot="D1", symbol="XYZ", description="XYZ")
    sell = SecurityStock(
        referenceDate=date(2024, 6, 1),
        mutation=True,
        quantity=Decimal("-5"),
        unitPrice=Decimal("10"),
        balanceCurrency="USD",
        quotationType="PIECE",
    )
    zero_close = SecurityStock(
        referenceDate=date(2025, 1, 1),
        mutation=False,
        quantity=Decimal("-5"),
        balanceCurrency="USD",
        quotationType="PIECE",
        unitPrice=Decimal("10"),
    )
    positions = {sec_pos: SecurityPositionData(stocks=[sell, zero_close], payments=[])}

    with pytest.raises(ValueError, match="Negative balance"):
        augment_list_of_securities(
            statement,
            positions,
            name_registry=SecurityNameRegistry(),
            hints_for=lambda _: PositionHints(),
        )


def test_augment_securities_allow_negative_balance_warns(caplog):
    statement = _partial_statement()
    sec_pos = SecurityPosition(depot="D1", symbol="OPT1", description="OPT1")
    sell = SecurityStock(
        referenceDate=date(2024, 6, 1),
        mutation=True,
        quantity=Decimal("-1"),
        unitPrice=Decimal("1"),
        balanceCurrency="USD",
        quotationType="PIECE",
    )
    close = SecurityStock(
        referenceDate=date(2025, 1, 1),
        mutation=False,
        quantity=Decimal("-1"),
        balanceCurrency="USD",
        quotationType="PIECE",
        unitPrice=Decimal("1"),
    )
    positions = {sec_pos: SecurityPositionData(stocks=[sell, close], payments=[])}

    with caplog.at_level("WARNING"):
        augment_list_of_securities(
            statement,
            positions,
            name_registry=SecurityNameRegistry(),
            hints_for=lambda _: PositionHints(
                allow_negative_opening=True, allow_negative_balance=True
            ),
        )

    assert "Negative balance" in caplog.text
    assert statement.listOfSecurities is not None


def test_augment_securities_skip_if_zero():
    statement = _partial_statement()
    sec_pos = SecurityPosition(depot="D1", symbol="ZERO", description="ZERO")
    stock = SecurityStock(
        referenceDate=date(2025, 1, 1),
        mutation=False,
        quantity=Decimal("0"),
        balanceCurrency="USD",
        quotationType="PIECE",
        unitPrice=Decimal("1"),
    )
    positions = {sec_pos: SecurityPositionData(stocks=[stock], payments=[])}

    augment_list_of_securities(
        statement,
        positions,
        name_registry=SecurityNameRegistry(),
        hints_for=lambda _: PositionHints(skip_if_zero=True),
    )
    assert statement.listOfSecurities is None


def test_fold_cash_payments_joins_on_account_and_currency():
    seed = [
        CashAccountEntry(
            account_id="A1",
            currency="USD",
            closing_balance=Decimal("100"),
        )
    ]
    pay = BankAccountPayment(
        paymentDate=date(2024, 2, 1),
        name="interest",
        amountCurrency="USD",
        amount=Decimal("1"),
    )
    processed = {("A1", "USD", "MAIN"): {"stocks": [], "payments": [pay]}}

    merged = fold_cash_payments(seed, processed)
    (entry,) = merged
    assert entry.closing_balance == Decimal("100")
    assert entry.payments == [pay]


def test_fold_cash_payments_creates_orphan_entries_without_balance():
    pay = BankAccountPayment(
        paymentDate=date(2024, 2, 1),
        name="interest",
        amountCurrency="EUR",
        amount=Decimal("1"),
    )
    processed = {("A1", "EUR", "MAIN"): {"stocks": [], "payments": [pay]}}

    merged = fold_cash_payments([], processed)
    (entry,) = merged
    assert entry.currency == "EUR"
    assert entry.closing_balance is None
    assert entry.payments == [pay]


def test_augment_bank_accounts_requires_closing_balance():
    statement = _partial_statement()
    entry = CashAccountEntry(
        account_id="A1", currency="USD", closing_balance=None, payments=[]
    )
    with pytest.raises(ValueError, match="No closing cash balance"):
        augment_list_of_bank_accounts(statement, [entry])


def test_augment_bank_accounts_builds_list():
    statement = _partial_statement()
    pay = BankAccountPayment(
        paymentDate=date(2024, 2, 1),
        name="interest",
        amountCurrency="USD",
        amount=Decimal("1"),
    )
    entry = CashAccountEntry(
        account_id="A1",
        currency="USD",
        closing_balance=Decimal("100"),
        payments=[pay],
        number="A1-USD",
    )
    augment_list_of_bank_accounts(statement, [entry])

    assert statement.listOfBankAccounts is not None
    (ba,) = statement.listOfBankAccounts.bankAccount
    assert ba.bankAccountName == "A1 USD"
    assert ba.bankAccountNumber == "A1-USD"
    assert ba.bankAccountCurrency == "USD"
    assert ba.taxValue.balance == Decimal("100")
    assert ba.payment == [pay]


def test_augment_bank_accounts_leaves_number_unset_when_none():
    statement = _partial_statement()
    entry = CashAccountEntry(
        account_id="Equity Awards GOOG",
        currency="USD",
        closing_balance=Decimal("0"),
        name="Equity Awards GOOG",
        number=None,
    )
    augment_list_of_bank_accounts(statement, [entry])

    (ba,) = statement.listOfBankAccounts.bankAccount
    assert ba.bankAccountName == "Equity Awards GOOG"
    assert ba.bankAccountNumber is None
