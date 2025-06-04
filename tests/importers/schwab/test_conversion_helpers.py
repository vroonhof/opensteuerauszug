import pytest
from opensteuerauszug.importers.schwab.schwab_importer import (
    convert_security_positions_to_list_of_securities,
    convert_cash_positions_to_list_of_bank_accounts,
    create_tax_statement_from_positions
)
from opensteuerauszug.model.position import SecurityPosition, CashPosition
from opensteuerauszug.model.ech0196 import SecurityStock, SecurityPayment, CurrencyId, BankAccountTaxValue
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
    result = convert_security_positions_to_list_of_securities([(pos, [stock], None)], [])
    assert result.depot[0].depotNumber == "...D1"
    assert result.depot[0].security[0].securityName == "AAPL"
    assert result.depot[0].security[0].stock[0].quantity == 10


def test_convert_cash_positions_to_list_of_bank_accounts():
    period_to_date = date(2024, 12, 30) # End of period for this specific test
    pos = CashPosition(depot="D2", currentCy="USD")
    stock = SecurityStock(
        referenceDate=date(2024, 12, 31), # Stock at start of next day (period_to_date + 1)
        mutation=False,
        quotationType="PIECE",
        quantity=Decimal(1000),
        balanceCurrency='USD'
    )
    # The tuple now needs three elements: (position, stocks, payments)
    # And the function needs period_to
    result = convert_cash_positions_to_list_of_bank_accounts(
        [(pos, [stock], None)],
        period_to=period_to_date,
        account_settings_list=[]
    )
    assert len(result.bankAccount) == 1
    assert result.bankAccount[0].bankAccountNumber == "USD Account ...D2"
    assert result.bankAccount[0].bankAccountCurrency == "USD"
    assert result.bankAccount[0].taxValue is not None
    assert isinstance(result.bankAccount[0].taxValue, BankAccountTaxValue)
    assert result.bankAccount[0].taxValue.referenceDate == period_to_date
    assert result.bankAccount[0].taxValue.name == "Closing Balance"
    assert result.bankAccount[0].taxValue.balance == Decimal(1000)
    assert result.bankAccount[0].taxValue.balanceCurrency == "USD"


def test_create_tax_statement_from_positions():
    test_period_from = date(2024, 1, 1)
    test_period_to = date(2024, 12, 31)
    test_tax_period = 2024

    sec_pos = SecurityPosition(depot="D1", symbol="AAPL")
    sec_stock = SecurityStock(
        referenceDate=date(2024, 1, 1),
        mutation=False,
        quotationType="PIECE",
        quantity=Decimal(10),
        balanceCurrency='USD'
    )
    cash_pos = CashPosition(depot="D2", currentCy="USD")
    # Cash stock representing the balance at the end of test_period_to
    # Its referenceDate should be test_period_to + 1 day
    cash_stock = SecurityStock(
        referenceDate=date(2025, 1, 1), # test_period_to + 1 day
        mutation=False,
        quotationType="PIECE",
        quantity=Decimal(1000),
        balanceCurrency='USD'
    )
    # The cash_tuples element now needs three items: (position, stocks, payments)
    tax_statement = create_tax_statement_from_positions(
        [(sec_pos, [sec_stock], None)],
        [(cash_pos, [cash_stock], None)], # Added None for payments
        period_from=test_period_from,
        period_to=test_period_to,
        tax_period=test_tax_period,
        account_settings_list=[]
    )
    assert tax_statement.minorVersion == 1
    assert tax_statement.periodFrom == test_period_from
    assert tax_statement.periodTo == test_period_to
    assert tax_statement.taxPeriod == test_tax_period
    assert tax_statement.listOfSecurities is not None
    assert tax_statement.listOfBankAccounts is not None
    assert len(tax_statement.listOfBankAccounts.bankAccount) == 1
    bank_account = tax_statement.listOfBankAccounts.bankAccount[0]
    assert bank_account.taxValue is not None
    assert isinstance(bank_account.taxValue, BankAccountTaxValue)
    assert bank_account.taxValue.referenceDate == test_period_to
    assert bank_account.taxValue.name == "Closing Balance"
    assert bank_account.taxValue.balance == Decimal(1000)
    assert bank_account.taxValue.balanceCurrency == "USD"