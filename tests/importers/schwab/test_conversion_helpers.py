import pytest
from opensteuerauszug.importers.schwab.schwab_importer import (
    convert_security_positions_to_list_of_securities,
    convert_cash_positions_to_list_of_bank_accounts,
    create_tax_statement_from_positions
)
from opensteuerauszug.model.position import SecurityPosition, CashPosition
from opensteuerauszug.model.ech0196 import SecurityStock, SecurityPayment, CurrencyId
from datetime import date
from decimal import Decimal


def test_convert_security_positions_to_list_of_securities():
    pos = SecurityPosition(depot="D1", symbol="AAPL")
    stock = SecurityStock(
        referenceDate=date(2024, 1, 1),
        mutation=False,
        quotationType="PIECE",
        quantity=Decimal(10),
        balanceCurrency='USD'
    )
    result = convert_security_positions_to_list_of_securities([(pos, [stock], None)])
    assert result.depot[0].depotNumber == "D1"
    assert result.depot[0].security[0].securityName == "AAPL"
    assert result.depot[0].security[0].stock[0].quantity == 10


def test_convert_cash_positions_to_list_of_bank_accounts():
    pos = CashPosition(depot="D2", currentCy="USD")
    stock = SecurityStock(
        referenceDate=date(2024, 1, 2),
        mutation=False,
        quotationType="PIECE",
        quantity=Decimal(1000),
        balanceCurrency='USD'
    )
    result = convert_cash_positions_to_list_of_bank_accounts([(pos, [stock])])
    assert len(result.bankAccount) == 1
    assert result.bankAccount[0].bankAccountNumber == "D2"
    assert result.bankAccount[0].bankAccountCurrency == "USD"


def test_create_tax_statement_from_positions():
    sec_pos = SecurityPosition(depot="D1", symbol="AAPL")
    sec_stock = SecurityStock(
        referenceDate=date(2024, 1, 1),
        mutation=False,
        quotationType="PIECE",
        quantity=Decimal(10),
        balanceCurrency='USD'
    )
    cash_pos = CashPosition(depot="D2", currentCy="USD")
    cash_stock = SecurityStock(
        referenceDate=date(2024, 1, 2),
        mutation=False,
        quotationType="PIECE",
        quantity=Decimal(1000),
        balanceCurrency='USD'
    )
    tax_statement = create_tax_statement_from_positions(
        [(sec_pos, [sec_stock], None)],
        [(cash_pos, [cash_stock])],
        period_from=date(2024, 1, 1),
        period_to=date(2024, 12, 31),
        tax_period=2024
    )
    assert tax_statement.minorVersion == 1
    assert tax_statement.periodFrom == date(2024, 1, 1)
    assert tax_statement.periodTo == date(2024, 12, 31)
    assert tax_statement.taxPeriod == 2024
    assert tax_statement.listOfSecurities is not None
    assert tax_statement.listOfBankAccounts is not None