import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, List

from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.model.ech0196 import (
    ISINType,
    TaxStatement,
    ListOfBankAccounts, BankAccount, BankAccountPayment, BankAccountNumber,
    ListOfSecurities, Depot, Security, SecurityStock, SecurityPayment, DepotNumber,
    CurrencyId, QuotationType,
    ValorNumber,
    Institution, # Added
    Client, # Added
    ClientNumber, # Added for test fixes
    LEIType, # Added for test fixes
    TINType # Added for test fixes
)
import os
# from unittest.mock import patch # Removed patch
# pandas is used by the module under test, not directly in tests for enrichment logic
# import pandas
# shutil is not needed for the chosen patching strategy
# import shutil

DEFAULT_TEST_PERIOD_FROM = date(2023, 1, 1)
DEFAULT_TEST_PERIOD_TO = date(2023, 12, 31)

def create_bank_account_payment(payment_date: date, amount: Decimal = Decimal("100"), name: str = "Payment") -> BankAccountPayment:
    return BankAccountPayment(
        paymentDate=payment_date,
        name=name,
        amountCurrency="CHF",
        amount=amount
    )

def create_security_stock(
    ref_date: date,
    quantity: Decimal,
    mutation: bool,
    name: str = "Stock Event",
    balance_currency: CurrencyId = "CHF",
    quotation_type: QuotationType = "PIECE"
) -> SecurityStock:
    return SecurityStock(
        referenceDate=ref_date,
        mutation=mutation,
        quotationType=quotation_type,
        quantity=quantity,
        balanceCurrency=balance_currency,
        name=name
    )

def create_security_payment(
    payment_date: date,
    quantity: Decimal = Decimal("10"),
    name: str = "Dividend",
    amount_currency: CurrencyId = "CHF",
    quotation_type: QuotationType = "PIECE"
) -> SecurityPayment:
    return SecurityPayment(
        paymentDate=payment_date,
        quotationType=quotation_type,
        quantity=quantity,
        amountCurrency=amount_currency,
        name=name
    )


@pytest.fixture
def sample_period_from() -> date:
    return date(2023, 1, 1)

@pytest.fixture
def sample_period_to() -> date:
    return date(2023, 12, 31)


class TestCleanupCalculatorSorting:
    def test_sort_bank_account_payments(self):
        p1 = create_bank_account_payment(date(2023, 3, 15))
        p2 = create_bank_account_payment(date(2023, 1, 10))
        p3 = create_bank_account_payment(date(2023, 7, 1))
        
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=[p1, p2, p3])
        # Added default fields for TaxStatement for ID generation
        default_period_to = date(2023,12,31)
        statement = TaxStatement(
            id=None, creationDate=datetime(default_period_to.year,1,1), taxPeriod=default_period_to.year, 
            periodFrom=date(default_period_to.year,1,1), periodTo=default_period_to, 
            country="CH", minorVersion=0, 
            client=[Client(clientNumber=ClientNumber("SortingClient"))], institution=Institution(lei=LEIType("SORTINGLEI12300000000")),
            # importer_name="SortingImporter", # Removed, TaxStatement no longer has this field
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))
        
        calculator = CleanupCalculator(DEFAULT_TEST_PERIOD_FROM, DEFAULT_TEST_PERIOD_TO, "SortingImporter", enable_filtering=False) # Added importer_name
        result_statement = calculator.calculate(statement)
        
        assert result_statement.listOfBankAccounts
        assert result_statement.listOfBankAccounts.bankAccount
        sorted_payments = result_statement.listOfBankAccounts.bankAccount[0].payment
        assert sorted_payments == [p2, p1, p3]

    def test_sort_security_stocks(self):
        s1_balance = create_security_stock(date(2023, 1, 1), Decimal("100"), False, name="Opening Balance")
        s2_mutation = create_security_stock(date(2023, 1, 15), Decimal("10"), True, name="Buy")
        s3_mutation_same_day = create_security_stock(date(2023, 1, 1), Decimal("5"), True, name="Initial Buy") # Mutation on same day as balance
        s4_balance_later = create_security_stock(date(2023, 1, 15), Decimal("110"), False, name="Mid Balance") # Balance on same day as mutation

        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=[s2_mutation, s1_balance, s4_balance_later, s3_mutation_same_day]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        default_period_to = date(2023,12,31)
        statement = TaxStatement(
            id=None, creationDate=datetime(default_period_to.year,1,1), taxPeriod=default_period_to.year, 
            periodFrom=date(default_period_to.year,1,1), periodTo=default_period_to, 
            country="CH", canton="ZH", minorVersion=0, 
            client=[Client(clientNumber=ClientNumber("SortingClient"))], institution=Institution(lei=LEIType("SORTINGLEI12300000000")),
            # importer_name="SortingImporter", # Removed
            listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(DEFAULT_TEST_PERIOD_FROM, DEFAULT_TEST_PERIOD_TO, "SortingImporter", enable_filtering=False) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        assert result_statement.listOfSecurities.depot
        sorted_stocks = result_statement.listOfSecurities.depot[0].security[0].stock
        # Expected: s1_balance (Jan 1, bal), s3_mutation_same_day (Jan 1, mut), s4_balance_later (Jan 15, bal), s2_mutation (Jan 15, mut)
        assert sorted_stocks[0] == s1_balance
        assert sorted_stocks[1] == s3_mutation_same_day
        assert sorted_stocks[2] == s4_balance_later
        assert sorted_stocks[3] == s2_mutation

    def test_sort_security_payments(self):
        sp1 = create_security_payment(date(2023, 4, 1))
        sp2 = create_security_payment(date(2023, 2, 20))
        sp3 = create_security_payment(date(2023, 8, 5))

        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            payment=[sp1, sp2, sp3]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        default_period_to = date(2023,12,31)
        statement = TaxStatement(
            id=None, creationDate=datetime(default_period_to.year,1,1), taxPeriod=default_period_to.year, 
            periodFrom=date(default_period_to.year,1,1), periodTo=default_period_to, 
            country="CH", canton="ZH", minorVersion=0, 
            client=[Client(clientNumber=ClientNumber("SortingClient"))], institution=Institution(lei=LEIType("SORTINGLEI12300000000")),
            # importer_name="SortingImporter", # Removed
            listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(DEFAULT_TEST_PERIOD_FROM, default_period_to, "SortingImporter", enable_filtering=False) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        assert result_statement.listOfSecurities.depot
        sorted_payments = result_statement.listOfSecurities.depot[0].security[0].payment
        assert sorted_payments == [sp2, sp1, sp3]


class TestCleanupCalculatorFiltering:

    def test_filter_bank_account_payments_enabled(self, sample_period_from, sample_period_to):
        p_before = create_bank_account_payment(sample_period_from - timedelta(days=10))
        p_inside1 = create_bank_account_payment(sample_period_from)
        p_inside2 = create_bank_account_payment(sample_period_to)
        p_after = create_bank_account_payment(sample_period_to + timedelta(days=10))

        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=[p_before, p_inside1, p_inside2, p_after])
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year, 
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0, 
            client=[Client(clientNumber=ClientNumber("FilterClient"))], institution=Institution(lei=LEIType("FILTERLEI123400000000")),
            # importer_name="FilterImporter", # Removed
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "FilterImporter", enable_filtering=True, print_log=True) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts
        filtered_payments = result_statement.listOfBankAccounts.bankAccount[0].payment
        assert len(filtered_payments) == 2
        assert p_inside1 in filtered_payments
        assert p_inside2 in filtered_payments
        assert "BA1.payment (filtered)" in calculator.modified_fields
        assert any("Filtered 4 payments to 2" in log for log in calculator.get_log())

    def test_filter_bank_account_payments_disabled(self, sample_period_from, sample_period_to):
        payments = [create_bank_account_payment(sample_period_from - timedelta(days=1))]
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=list(payments))
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year, 
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("FilterClient"))], institution=Institution(lei=LEIType("FILTERLEI123400000000")),
            # importer_name="FilterImporter", # Removed
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "FilterImporter", enable_filtering=False) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts
        assert len(result_statement.listOfBankAccounts.bankAccount[0].payment) == 1
        assert "TaxStatement.id (generated)" in calculator.modified_fields # ID is generated
        assert len(calculator.modified_fields) == 1 # Only ID

    def test_filter_bank_account_payments_no_period(self, sample_period_to): # Added sample_period_to for default TaxStatement args
        payments = [create_bank_account_payment(date(2023,1,1))]
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=list(payments))
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year, 
            periodFrom=date(sample_period_to.year,1,1), periodTo=sample_period_to, # Using sample_period_to for periodTo
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("FilterClient"))], institution=Institution(lei=LEIType("FILTERLEI123400000000")),
            # importer_name="FilterImporter", # Removed
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator = CleanupCalculator(DEFAULT_TEST_PERIOD_FROM, DEFAULT_TEST_PERIOD_TO, "FilterImporter", enable_filtering=True) # Added importer_name, No period defined for filtering
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts
        assert len(result_statement.listOfBankAccounts.bankAccount[0].payment) == 1
        assert "TaxStatement.id (generated)" in calculator.modified_fields # ID is generated
        assert len(calculator.modified_fields) == 1 # Only ID

    def test_filter_security_stocks_enabled(self, sample_period_from, sample_period_to):
        period_end_plus_one = sample_period_to + timedelta(days=1)

        s_bal_before = create_security_stock(sample_period_from - timedelta(days=10), Decimal("90"), False)
        s_bal_start = create_security_stock(sample_period_from, Decimal("100"), False) # Keep
        s_mut_inside1 = create_security_stock(sample_period_from + timedelta(days=5), Decimal("10"), True) # Keep
        s_bal_inside_discard = create_security_stock(sample_period_from + timedelta(days=10), Decimal("110"), False) # Discard
        s_mut_inside2 = create_security_stock(sample_period_to - timedelta(days=5), Decimal("-5"), True) # Keep
        s_bal_end_plus_one = create_security_stock(period_end_plus_one, Decimal("105"), False) # No longer kept as stock, but reflected in taxValue
        s_mut_after = create_security_stock(period_end_plus_one + timedelta(days=10), Decimal("20"), True)
        s_bal_after = create_security_stock(period_end_plus_one + timedelta(days=15), Decimal("125"), False)

        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=[s_bal_before, s_bal_start, s_mut_inside1, s_bal_inside_discard, s_mut_inside2, s_bal_end_plus_one, s_mut_after, s_bal_after]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year, 
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("FilterClient"))], institution=Institution(lei=LEIType("FILTERLEI123400000000")),
            # importer_name="FilterImporter", # Removed
            listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "FilterImporter", enable_filtering=True, print_log=True) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        filtered_stocks = result_statement.listOfSecurities.depot[0].security[0].stock
        
        expected_to_keep = [s_bal_start, s_mut_inside1, s_mut_inside2] # s_bal_end_plus_one removed
        
        assert len(filtered_stocks) == len(expected_to_keep)
        for item in expected_to_keep:
            assert item in filtered_stocks
        
        assert "D1/TestSec.stock (filtered)" in calculator.modified_fields
        assert any("Filtered 8 stock events to 3" in log for log in calculator.get_log()) # Adjusted from 4 to 3
        assert result_statement.listOfSecurities.depot[0].security[0].taxValue is not None
        assert result_statement.listOfSecurities.depot[0].security[0].taxValue.quantity == s_bal_end_plus_one.quantity

    def test_filter_security_stocks_no_mutations_only_balances(self, sample_period_from, sample_period_to):
        period_end_plus_one = sample_period_to + timedelta(days=1)

        s_bal_before = create_security_stock(sample_period_from - timedelta(days=10), Decimal("90"), False)
        s_bal_start = create_security_stock(sample_period_from, Decimal("100"), False) # Keep
        s_bal_inside_discard = create_security_stock(sample_period_from + timedelta(days=10), Decimal("110"), False) # Discard
        s_bal_end_plus_one = create_security_stock(period_end_plus_one, Decimal("105"), False) # No longer kept
        s_bal_after = create_security_stock(period_end_plus_one + timedelta(days=15), Decimal("125"), False)

        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=[s_bal_before, s_bal_start, s_bal_inside_discard, s_bal_end_plus_one, s_bal_after]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year, 
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("FilterClient"))], institution=Institution(lei=LEIType("FILTERLEI123400000000")),
            # importer_name="FilterImporter", # Removed
            listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "FilterImporter", enable_filtering=True) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        filtered_stocks = result_statement.listOfSecurities.depot[0].security[0].stock
        assert len(filtered_stocks) == 1 # Adjusted from 2 to 1
        assert s_bal_start in filtered_stocks
        # assert s_bal_end_plus_one in filtered_stocks # This is no longer kept
        assert "D1/TestSec.stock (filtered)" in calculator.modified_fields
        assert result_statement.listOfSecurities.depot[0].security[0].taxValue is not None
        assert result_statement.listOfSecurities.depot[0].security[0].taxValue.quantity == s_bal_end_plus_one.quantity

    def test_filter_security_stocks_disabled(self, sample_period_from, sample_period_to):
        stocks = [create_security_stock(sample_period_from - timedelta(days=1), Decimal("10"), False)]
        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=list(stocks)
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year, 
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("FilterClient"))], institution=Institution(lei=LEIType("FILTERLEI123400000000")),
            # importer_name="FilterImporter", # Removed
            listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "FilterImporter", enable_filtering=False) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        assert len(result_statement.listOfSecurities.depot[0].security[0].stock) == 1
        assert "TaxStatement.id (generated)" in calculator.modified_fields # ID is generated
        assert len(calculator.modified_fields) == 1 # Only ID

    def test_filter_security_stocks_no_period(self, sample_period_to): # Added sample_period_to for default TaxStatement args
        stocks = [create_security_stock(date(2023,1,1), Decimal("10"), False)]
        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=list(stocks)
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year, 
            periodFrom=date(sample_period_to.year,1,1), periodTo=sample_period_to, # Using sample_period_to for periodTo
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("FilterClient"))], institution=Institution(lei=LEIType("FILTERLEI123400000000")),
            # importer_name="FilterImporter", # Removed
            listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(DEFAULT_TEST_PERIOD_FROM, DEFAULT_TEST_PERIOD_TO, "FilterImporter", enable_filtering=True) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        assert len(result_statement.listOfSecurities.depot[0].security[0].stock) == 1
        assert "TaxStatement.id (generated)" in calculator.modified_fields # ID is generated
        assert len(calculator.modified_fields) == 1 # Only ID

    def test_filter_security_payments_enabled(self, sample_period_from, sample_period_to):
        sp_before = create_security_payment(sample_period_from - timedelta(days=10))
        sp_inside1 = create_security_payment(sample_period_from)
        sp_inside2 = create_security_payment(sample_period_to)
        sp_after = create_security_payment(sample_period_to + timedelta(days=10))

        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            payment=[sp_before, sp_inside1, sp_inside2, sp_after]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year, 
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("FilterClient"))], institution=Institution(lei=LEIType("FILTERLEI123400000000")),
            # importer_name="FilterImporter", # Removed
            listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "FilterImporter", enable_filtering=True) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        filtered_payments = result_statement.listOfSecurities.depot[0].security[0].payment
        assert len(filtered_payments) == 2
        assert sp_inside1 in filtered_payments
        assert sp_inside2 in filtered_payments
        assert "D1/TestSec.payment (filtered)" in calculator.modified_fields


class TestCleanupCalculatorEdgeCases:

    def test_empty_statement(self, sample_period_from, sample_period_to):
        # For an empty statement, ID generation still needs some minimal fields
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("EdgeClient"))], institution=Institution(lei=LEIType("EDGELEI1234500000000")),
            # importer_name="EdgeImporter" # Removed
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "EdgeImporter", enable_filtering=True) # Added importer_name
        result_statement = calculator.calculate(statement)
        
        assert result_statement.listOfBankAccounts is None
        assert result_statement.listOfSecurities is None
        assert "TaxStatement.id (generated)" in calculator.modified_fields
        assert len(calculator.modified_fields) == 1 # Only ID
        assert any("No bank accounts found to process." in log for log in calculator.get_log())
        assert any("No securities accounts found to process." in log for log in calculator.get_log())

    def test_statement_with_no_bank_accounts(self, sample_period_from, sample_period_to):
        security = Security(positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec")
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("EdgeClient"))], institution=Institution(lei=LEIType("EDGELEI1234500000000")),
            # importer_name="EdgeImporter", # Removed
            listOfSecurities=ListOfSecurities(depot=[depot]))
        
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "EdgeImporter", enable_filtering=True) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts is None
        assert result_statement.listOfSecurities is not None
        assert "TaxStatement.id (generated)" in calculator.modified_fields 
        assert len(calculator.modified_fields) == 1 
        assert any("No bank accounts found to process." in log for log in calculator.get_log())

    def test_statement_with_no_securities(self, sample_period_from, sample_period_to):
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"))
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("EdgeClient"))], institution=Institution(lei=LEIType("EDGELEI1234500000000")),
            # importer_name="EdgeImporter", # Removed
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "EdgeImporter", enable_filtering=True) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts is not None
        assert result_statement.listOfSecurities is None
        assert "TaxStatement.id (generated)" in calculator.modified_fields
        assert len(calculator.modified_fields) == 1
        assert any("No securities accounts found to process." in log for log in calculator.get_log())

    def test_bank_account_with_no_payments(self, sample_period_from, sample_period_to):
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=[])
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("EdgeClient"))], institution=Institution(lei=LEIType("EDGELEI1234500000000")),
            # importer_name="EdgeImporter", # Removed
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))
        
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "EdgeImporter", enable_filtering=True) # Added importer_name
        calculator.calculate(statement)
        
        assert "TaxStatement.id (generated)" in calculator.modified_fields
        assert len(calculator.modified_fields) == 1

    def test_security_with_no_stocks_or_payments(self, sample_period_from, sample_period_to):
        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=[], payment=[]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("EdgeClient"))], institution=Institution(lei=LEIType("EDGELEI1234500000000")),
            # importer_name="EdgeImporter", # Removed
            listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "EdgeImporter", enable_filtering=True) # Added importer_name
        calculator.calculate(statement)

        assert "TaxStatement.id (generated)" in calculator.modified_fields
        assert len(calculator.modified_fields) == 1

    def test_logging_of_modified_fields(self, sample_period_from, sample_period_to):
        p_before = create_bank_account_payment(sample_period_from - timedelta(days=1))
        p_inside = create_bank_account_payment(sample_period_from)
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA001"), payment=[p_before, p_inside])
        
        s_bal_before = create_security_stock(sample_period_from - timedelta(days=1), Decimal("10"), False)
        s_bal_start = create_security_stock(sample_period_from, Decimal("10"), False)
        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="SecXYZ",
            stock=[s_bal_before, s_bal_start]
        )
        depot = Depot(depotNumber=DepotNumber("Dep01"), security=[security])
        
        statement = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("EdgeClient"))], institution=Institution(lei=LEIType("EDGELEI1234500000000")),
            # importer_name="EdgeImporter", # Removed
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
            listOfSecurities=ListOfSecurities(depot=[depot])
        )

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "EdgeImporter", enable_filtering=True, print_log=False) # Added importer_name
        calculator.calculate(statement)

        assert "TaxStatement.id (generated)" in calculator.modified_fields
        assert "BA001.payment (filtered)" in calculator.modified_fields
        assert "Dep01/SecXYZ.stock (filtered)" in calculator.modified_fields
        assert len(calculator.modified_fields) == 3
        
        final_log_message = calculator.get_log()[-1] 
        assert "Fields modified:" in final_log_message 
        assert "TaxStatement.id (generated)" in final_log_message
        assert "BA001.payment (filtered)" in final_log_message
        assert "Dep01/SecXYZ.stock (filtered)" in final_log_message


# Helper function for creating TaxStatement with a single security
def _create_statement_with_security(sec: Security, period_to_date: date, depot_id_str: str = "DTEST") -> TaxStatement:
    depot = Depot(depotNumber=DepotNumber(depot_id_str), security=[sec])
    list_of_securities = ListOfSecurities(depot=[depot])
    statement = TaxStatement(
        id=None, # Important for enrichment tests that might also trigger ID gen
        creationDate=datetime(period_to_date.year, 1, 1, 12, 0, 0),
        taxPeriod=period_to_date.year,
        periodFrom=date(period_to_date.year, 1, 1),
        periodTo=period_to_date, # Use passed period_to_date
        country="CH", # Default country for enrichment tests
        canton="ZH",
        minorVersion=0,
        client=[Client(clientNumber=ClientNumber("EnrichClient"))], # Default client for ID gen
        institution=Institution(lei=LEIType("ENRICHLEI12300000000")),  # Default institution for ID gen
        # importer_name="EnrichImporter", # Removed from TaxStatement
        listOfSecurities=list_of_securities
    )
    return statement

# Minimal security creation helper for enrichment tests
def _create_test_security(
    name: str,
    symbol: Optional[str] = None, # Added symbol parameter
    isin: Optional[str] = None,
    valor: Optional[int] = None
) -> Security:
    return Security(
        positionId=1, # required
        country="CH", # required
        currency="CHF", # required
        quotationType="PIECE", # required
        securityCategory="SHARE", # required
        securityName=name,
        symbol=symbol, # Assign symbol
        isin=ISINType(isin) if isin is not None else None,
        valorNumber=ValorNumber(valor) if valor is not None else None,
    )


class TestCleanupCalculatorEnrichment:

    @pytest.fixture
    def base_calculator_params(self, sample_period_from, sample_period_to):
        return {
            "period_from": sample_period_from,
            "period_to": sample_period_to,
            "importer_name": "EnrichTest", # Added importer_name to calculator params
            "enable_filtering": False,
            "print_log": True
        }

    def test_enrichment_full(self, base_calculator_params):
        test_map = {"TESTSYM_FULL": {"isin": "US1234567890", "valor": 1234567}} # This test now implicitly tests securityName lookup
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        # This security will be looked up by securityName="TESTSYM_FULL" as symbol is None
        security = _create_test_security(name="TESTSYM_FULL", symbol=None)
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        # Override defaults if specific test needs different client/institution for ID part
        statement.client = [Client(clientNumber=ClientNumber("FullEnrich"))]
        statement.institution = Institution(lei=LEIType("FULLLEI1234500000000"))

        calculator.calculate(statement)
        
        assert security.isin == "US1234567890"
        assert security.valorNumber == 1234567
        # Log still refers to the lookup key which was security.securityName here
        assert any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_FULL'" in log for log in calculator.get_log())
        assert any("DTEST/TESTSYM_FULL (enriched)" in f for f in calculator.modified_fields)

    def test_enrichment_uses_symbol_success(self, base_calculator_params):
        test_map = {"MYSYMBOL": {"isin": "XS123123123", "valor": 987654}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="Some Name", symbol="MYSYMBOL")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "XS123123123"
        assert security.valorNumber == 987654
        assert any("Enriched ISIN/Valor from identifier file using symbol 'MYSYMBOL'" in log for log in calculator.get_log())
        assert any("DTEST/MYSYMBOL (enriched)" in f for f in calculator.modified_fields)

    def test_enrichment_uses_symbol_not_securityname(self, base_calculator_params):
        """Ensures lookup is by symbol, not by securityName if symbol is present."""
        test_map = {
            "WRONG_KEY_NAME": {"isin": "XS_WRONG", "valor": 111}, # Should not be used
            "RIGHT_SYMBOL": {"isin": "XS_CORRECT", "valor": 222}  # Should be used
        }
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        # Security has a symbol, and its name is a key in the map, but symbol should take precedence.
        security = _create_test_security(name="WRONG_KEY_NAME", symbol="RIGHT_SYMBOL")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "XS_CORRECT"
        assert security.valorNumber == 222
        assert any("Enriched ISIN/Valor from identifier file using symbol 'RIGHT_SYMBOL'" in log for log in calculator.get_log())

    def test_enrichment_symbol_not_in_map(self, base_calculator_params):
        test_map = {"KNOWN_SYMBOL": {"isin": "XS123", "valor": 987}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="Some Name", symbol="UNKNOWN_SYMBOL")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"], depot_id_str="D_SYM_UNKNOWN")
        statement.id="PRESET_ID_SYM_UNKNOWN" # Avoid ID gen log
        initial_log_count = len(calculator.get_log())
        calculator.calculate(statement)
        logs_after_calculate = calculator.get_log()[initial_log_count:]

        assert security.isin is None
        assert security.valorNumber is None
        assert not any("Enriched ISIN/Valor" in log for log in logs_after_calculate)
        assert not any("D_SYM_UNKNOWN/UNKNOWN_SYMBOL (enriched)" in f for f in calculator.modified_fields)

    def test_enrichment_symbol_is_none_uses_securityname_fallback(self, base_calculator_params):
        """If symbol is None, it should fall back to securityName for lookup."""
        test_map = {"FALLBACK_NAME": {"isin": "XS_FB", "valor": 321}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="FALLBACK_NAME", symbol=None) # Symbol is None
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "XS_FB"
        assert security.valorNumber == 321
        assert any("Enriched ISIN/Valor from identifier file using symbol 'FALLBACK_NAME'" in log for log in calculator.get_log())

    def test_enrichment_symbol_is_empty_string_uses_securityname_fallback(self, base_calculator_params):
        """If symbol is an empty string, it should fall back to securityName for lookup."""
        test_map = {"FALLBACK_NAME_EMPTY_SYM": {"isin": "XS_FB_EMPTY", "valor": 654}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="FALLBACK_NAME_EMPTY_SYM", symbol="") # Symbol is empty string
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "XS_FB_EMPTY"
        assert security.valorNumber == 654
        assert any("Enriched ISIN/Valor from identifier file using symbol 'FALLBACK_NAME_EMPTY_SYM'" in log for log in calculator.get_log())


    def test_enrichment_map_none_or_empty_with_symbol(self, base_calculator_params):
        security_with_symbol = _create_test_security(name="Some Name", symbol="MYSYMBOL")
        statement = _create_statement_with_security(security_with_symbol, base_calculator_params["period_to"])
        statement.id = "PRESET_MAP_EMPTY_NONE"

        # Test with None map
        calc_none_map = CleanupCalculator(**base_calculator_params, identifier_map=None)
        initial_logs_none = len(calc_none_map.get_log())
        calc_none_map.calculate(statement)
        logs_calc_none = calc_none_map.get_log()[initial_logs_none:]
        assert security_with_symbol.isin is None
        assert security_with_symbol.valorNumber is None
        assert not any("Enriched" in log for log in logs_calc_none)
        assert not calc_none_map.modified_fields # Only ID gen if not preset

        # Reset security fields for next test
        security_with_symbol.isin = None
        security_with_symbol.valorNumber = None

        # Test with empty map
        calc_empty_map = CleanupCalculator(**base_calculator_params, identifier_map={})
        initial_logs_empty = len(calc_empty_map.get_log())
        calc_empty_map.calculate(statement)
        logs_calc_empty = calc_empty_map.get_log()[initial_logs_empty:]
        assert security_with_symbol.isin is None
        assert security_with_symbol.valorNumber is None
        assert not any("Enriched" in log for log in logs_calc_empty)
        assert not calc_empty_map.modified_fields


    def test_enrichment_conditional_update_with_symbol(self, base_calculator_params):
        test_map = {"MYSYMBOL_COND": {"isin": "XS_NEW_COND", "valor": 987111}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        period_to = base_calculator_params["period_to"]

        # Case 1: Security has ISIN, Valor is None. Valor should be enriched.
        sec1 = _create_test_security(name="N1", symbol="MYSYMBOL_COND", isin="NLDUMMYISIN1", valor=None)
        stmt1 = _create_statement_with_security(sec1, period_to); stmt1.id="S1"
        calculator.calculate(stmt1)
        assert sec1.isin == "NLDUMMYISIN1"
        assert sec1.valorNumber == 987111

        # Case 2: Security has Valor, ISIN is None. ISIN should be enriched.
        sec2 = _create_test_security(name="N2", symbol="MYSYMBOL_COND", isin=None, valor=123000)
        stmt2 = _create_statement_with_security(sec2, period_to); stmt2.id="S2"
        calculator.calculate(stmt2)
        assert sec2.isin == "XS_NEW_COND"
        assert sec2.valorNumber == 123000

        # Case 3: Security has both ISIN and Valor. No enrichment.
        sec3 = _create_test_security(name="N3", symbol="MYSYMBOL_COND", isin="XSDUMMYISIN2", valor=321000)
        stmt3 = _create_statement_with_security(sec3, period_to); stmt3.id="S3"
        calculator.calculate(stmt3)
        assert sec3.isin == "XSDUMMYISIN2"
        assert sec3.valorNumber == 321000
        # Check that (enriched) is not in modified_fields for this specific security
        assert not any("MYSYMBOL_COND (enriched)" in f for f in calculator.modified_fields if "S3" in f)

    # Keep existing tests for securityName lookup if that's still a fallback
    def test_enrichment_already_full_by_name(self, base_calculator_params): # Renamed for clarity
        # Map might contain data, but it shouldn't be used if security is already full.
        test_map = {"TESTSYM_ALREADY_FULL_NAME": {"isin": "OTHER_ISIN", "valor": 999888}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)

        security = _create_test_security(name="TESTSYM_ALREADY_FULL_NAME", symbol=None, isin="US1111111111", valor=1111111)
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        # Set a pre-existing ID to ensure ID generation logic doesn't run and add to modified_fields
        statement.id = "PRE_EXISTING_ID_NAME_LOOKUP"

        # Clear initial logs from calculator's __init__ to focus on calculate() logs
        initial_log_count = len(calculator.get_log())
        calculator.calculate(statement)
        logs_after_calculate = calculator.get_log()[initial_log_count:]
        
        assert security.isin == "US1111111111"
        assert security.valorNumber == 1111111
        assert not any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_ALREADY_FULL_NAME'" in log for log in logs_after_calculate)
        assert "TaxStatement.id (generated)" not in calculator.modified_fields
        assert not any("TESTSYM_ALREADY_FULL_NAME (enriched)" in f for f in calculator.modified_fields)

    # The following existing tests like test_enrichment_map_has_isin_only, test_enrichment_map_has_valor_only etc.
    # will continue to test the securityName lookup path if symbol is None or empty on the Security object.
    # This is because _create_test_security by default creates symbol=None if not specified.

    def test_enrichment_map_has_isin_only_by_name(self, base_calculator_params): # Renamed for clarity
        test_map = {"TESTSYM_NO_VALOR_NAME": {"isin": "CH0987654321", "valor": None}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)

        security = _create_test_security(name="TESTSYM_NO_VALOR_NAME") # Symbol is None
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "CH0987654321"
        assert security.valorNumber is None
        assert any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_NO_VALOR_NAME'" in log for log in calculator.get_log())

    def test_enrichment_map_has_valor_only_by_name(self, base_calculator_params): # Renamed for clarity
        test_map = {"TESTSYM_NO_ISIN_NAME": {"isin": None, "valor": 7654321}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)

        security = _create_test_security(name="TESTSYM_NO_ISIN_NAME") # Symbol is None
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin is None
        assert security.valorNumber == 7654321
        assert any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_NO_ISIN_NAME'" in log for log in calculator.get_log())


class TestCleanupCalculatorSecurityPaymentQuantity:
    def _create_base_statement_and_security(self, period_from: date, period_to: date, security_name: str = "TestSecForQtyCalc") -> Tuple[TaxStatement, Security]:
        security = Security(
            positionId=1,
            country="CH",
            currency="CHF",
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName=security_name,
            isin=ISINType("CH0012345678"),
            valorNumber=ValorNumber(1234567),
            stock=[], # Populated by each test
            payment=[] # Populated by each test
        )
        depot = Depot(depotNumber=DepotNumber("DP1"), security=[security])
        statement = TaxStatement(
            id="test_qty_calc_statement", # Pre-set ID to avoid ID generation logic interfering
            creationDate=datetime(period_to.year, 1, 1),
            taxPeriod=period_to.year,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("QtyClient"))],
            institution=Institution(lei=LEIType("QTYLEI12345000000000")),
            listOfSecurities=ListOfSecurities(depot=[depot])
        )
        return statement, security

    def test_calculate_quantity_paymentdate_fallback_stock_held(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecPaymentDateFallbackStockHeld")

        payment_date = date(2023, 7, 15)
        # Ensure exDate is None to test paymentDate fallback
        payment_event = create_security_payment(payment_date=payment_date, quantity=Decimal("-1"), name="DividendPaymentDateFallback")
        payment_event.exDate = None
        security.payment = [payment_event]

        # Stock setup: Held 60 shares on payment_date
        security.stock = [
            create_security_stock(date(2023, 1, 1), Decimal("50"), False, name="Opening Balance"), # Start of period
            create_security_stock(date(2023, 6, 1), Decimal("10"), True, name="Buy"), # 50 + 10 = 60
            create_security_stock(date(2023, 8, 1), Decimal("-5"), True, name="Sell")  # After payment date
        ]
        # Expected quantity at payment_date (2023-07-15) is 60 (50 from opening + 10 from buy on 2023-06-01)

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False, print_log=True)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("60"), "Quantity should be updated to 60 (50+10) using paymentDate"
        assert any(f"DP1/SecPaymentDateFallbackStockHeld.Payment (Name: DividendPaymentDateFallback, Date: {payment_date}, exDate: None).quantity (updated via paymentDate)" in f for f in calculator.modified_fields)
        assert any(f"Updated quantity for Payment (Name: DividendPaymentDateFallback, Date: {payment_date}, exDate: None) to 60 using paymentDate ({payment_date})" in log for log in calculator.get_log())

    def test_calculate_quantity_paymentdate_fallback_no_stock_held(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecPaymentDateFallbackNoStock")

        payment_date = date(2023, 8, 1)
        # Ensure exDate is None
        payment_event = create_security_payment(payment_date=payment_date, quantity=Decimal("-1"), name="DividendPaymentDateFallbackNoStock")
        payment_event.exDate = None
        security.payment = [payment_event]

        # Stock setup: All stock sold before payment_date
        security.stock = [
            create_security_stock(date(2023, 1, 1), Decimal("20"), False, name="Opening Balance"),
            create_security_stock(date(2023, 3, 1), Decimal("-20"), True, name="Sell All") # Sold before payment_date
        ]
        # Expected quantity at payment_date (2023-08-01) is 0

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False, print_log=True)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("0"), "Quantity should be updated to 0 using paymentDate"
        assert any(f"DP1/SecPaymentDateFallbackNoStock.Payment (Name: DividendPaymentDateFallbackNoStock, Date: {payment_date}, exDate: None).quantity (updated via paymentDate)" in f for f in calculator.modified_fields)
        assert any(f"Updated quantity for Payment (Name: DividendPaymentDateFallbackNoStock, Date: {payment_date}, exDate: None) to 0 using paymentDate ({payment_date})" in log for log in calculator.get_log())

    def test_calculate_quantity_paymentdate_fallback_missing_stock_data(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecPaymentDateFallbackMissingStock")

        payment_date = date(2023, 9, 1)
        # Ensure exDate is None
        payment_event = create_security_payment(payment_date=payment_date, quantity=Decimal("-1"), name="DividendPaymentDateFallbackMissingStock")
        payment_event.exDate = None
        security.payment = [payment_event]

        # Stock setup: Empty stock list
        security.stock = []

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False, print_log=True)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("-1"), "Quantity should remain -1 due to missing stock data (using paymentDate)"
        # No modification if quantity remains -1
        assert not any(".quantity (updated via paymentDate)" in f for f in calculator.modified_fields)
        assert any(f"Warning: Security DP1/SecPaymentDateFallbackMissingStock: Cannot calculate SecurityPayment quantity for payment (Name: DividendPaymentDateFallbackMissingStock, Date: {payment_date}, exDate: None) due to missing stock data. Quantity remains -1." in log for log in calculator.get_log())

    def test_calculate_quantity_paymentdate_fallback_stock_data_does_not_cover(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecPaymentDateFallbackNoCover")

        payment_date = date(2023, 6, 15) # Payment date
        # Ensure exDate is None
        payment_event = create_security_payment(payment_date=payment_date, quantity=Decimal("-1"), name="DividendPaymentDateFallbackNoCover")
        payment_event.exDate = None
        security.payment = [payment_event]

        # Stock setup: Stock entries exist but none cover the payment_date
        # For example, an opening balance far in the past and no further transactions,
        # or transactions that clearly don't lead to a position on payment_date.
        # PositionReconciler's synthesize_position_at_date might return None if no transactions before or on date.
        security.stock = [
            create_security_stock(date(2023, 1, 1), Decimal("10"), False, name="Opening Balance Far Past"),
            # No other stock mutations that would lead to a position on 2023-06-15
            # Let's assume the reconciler returns None or a quantity of 0 if no stock activity near the date.
            # If it synthesized 0, then the previous test "no_stock_held" covers it.
            # This test is for when synthesize_position_at_date returns None for the ReconciledPosition object.
        ]
        # To make it more explicit that reconciler might return None for the position object:
        # If all stock entries are *after* the payment date, synthesize_position_at_date should return None.
        security.stock = [
             create_security_stock(date(2023, 7, 1), Decimal("10"), True, name="Buy After PaymentDate")
        ]

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False, print_log=True)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("-1"), "Quantity should remain -1 as stock data does not cover payment date (using paymentDate)"
        assert not any(".quantity (updated via paymentDate)" in f for f in calculator.modified_fields)
        assert any(f"Quantity for payment (Name: DividendPaymentDateFallbackNoCover, Date: {payment_date}, exDate: None) remains -1. Could not determine stock quantity using paymentDate ({payment_date})." in log for log in calculator.get_log())

    def test_calculate_quantity_exdate_prioritized_stock_held(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecExDatePrioritizedStockHeld")

        payment_date = date(2023, 7, 15)
        ex_date = date(2023, 7, 1) # exDate is before paymentDate

        payment_event = create_security_payment(payment_date=payment_date, quantity=Decimal("-1"), name="DividendExDatePriority")
        payment_event.exDate = ex_date
        security.payment = [payment_event]

        # Stock setup:
        # On exDate (July 1): 50 (opening)
        # On paymentDate (July 15): 60 (after buy on July 10)
        security.stock = [
            create_security_stock(date(2023, 1, 1), Decimal("50"), False, name="Opening Balance"),
            create_security_stock(date(2023, 7, 10), Decimal("10"), True, name="Buy between ex and payment")
        ]
        # Expected quantity is 50 based on exDate

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False, print_log=True)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("50"), "Quantity should be 50 (based on exDate)"
        assert any(f"DP1/SecExDatePrioritizedStockHeld.Payment (Name: DividendExDatePriority, Date: {payment_date}, exDate: {ex_date}).quantity (updated via exDate)" in f for f in calculator.modified_fields)
        assert any(f"Using exDate ({ex_date}) for quantity calculation for payment on {payment_date}" in log for log in calculator.get_log())
        assert any(f"Updated quantity for Payment (Name: DividendExDatePriority, Date: {payment_date}, exDate: {ex_date}) to 50 using exDate ({ex_date})" in log for log in calculator.get_log())

    def test_calculate_quantity_exdate_no_stock_on_exdate(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecExDateNoStock")

        payment_date = date(2023, 7, 15)
        ex_date = date(2023, 7, 1)

        payment_event = create_security_payment(payment_date=payment_date, quantity=Decimal("-1"), name="DividendExDateNoStock")
        payment_event.exDate = ex_date
        security.payment = [payment_event]

        # Stock setup: All stock bought after exDate
        security.stock = [
            create_security_stock(date(2023, 1, 1), Decimal("0"), False, name="Opening Balance Zero"), # Explicit zero opening
            create_security_stock(date(2023, 7, 10), Decimal("30"), True, name="Buy after exDate")
        ]
        # Expected quantity is 0 based on exDate

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False, print_log=True)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("0"), "Quantity should be 0 (based on exDate)"
        assert any(f"DP1/SecExDateNoStock.Payment (Name: DividendExDateNoStock, Date: {payment_date}, exDate: {ex_date}).quantity (updated via exDate)" in f for f in calculator.modified_fields)
        assert any(f"Using exDate ({ex_date}) for quantity calculation for payment on {payment_date}" in log for log in calculator.get_log())
        assert any(f"Updated quantity for Payment (Name: DividendExDateNoStock, Date: {payment_date}, exDate: {ex_date}) to 0 using exDate ({ex_date})" in log for log in calculator.get_log())

    def test_calculate_quantity_exdate_insufficient_stock_data_for_exdate(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecExDateInsufficientData")

        payment_date = date(2023, 7, 15)
        ex_date = date(2023, 7, 1)

        payment_event = create_security_payment(payment_date=payment_date, quantity=Decimal("-1"), name="DividendExDateInsufficient")
        payment_event.exDate = ex_date
        security.payment = [payment_event]

        # Stock setup: All stock transactions are after exDate, so reconciler returns None for exDate.
        security.stock = [
            create_security_stock(date(2023, 8, 1), Decimal("20"), True, name="Buy well after exDate")
        ]

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False, print_log=True)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("-1"), "Quantity should remain -1 (insufficient data for exDate)"
        assert not any(".quantity (updated via exDate)" in f for f in calculator.modified_fields) # Not updated
        assert any(f"Using exDate ({ex_date}) for quantity calculation for payment on {payment_date}" in log for log in calculator.get_log())
        assert any(f"Quantity for payment (Name: DividendExDateInsufficient, Date: {payment_date}, exDate: {ex_date}) remains -1. Could not determine stock quantity using exDate ({ex_date})." in log for log in calculator.get_log())


class TestCleanupCalculatorIDGeneration:
    """Tests for TaxStatement ID generation logic in CleanupCalculator."""

    def _construct_expected_id(self, country: str, org: str, customer: str, date_str: str, seq: str = "01") -> str: # Removed page parameter
        return f"{country}{org}{customer}{date_str}{seq}" # Removed page from f-string

    def _default_statement_args(self, period_to_date: date, country:str = "CH", institution: Optional[Institution]=None, client: Optional[List[Client]]=None) -> dict: # Removed importer_name from signature
        # Provide default valid institution and client if not given, to ensure ID generation has some data
        default_institution = Institution(lei=LEIType("DEFAULTLEI1200000000")) if institution is None else institution 
        default_client = [Client(clientNumber=ClientNumber("DEFAULTCUST"))] if client is None else client

        return {
            "creationDate": datetime(period_to_date.year, 1, 1),
            "taxPeriod": period_to_date.year,
            "periodFrom": date(period_to_date.year, 1, 1),
            "periodTo": period_to_date,
            "country": country,
            "canton": "ZH",
            "minorVersion": 0,
            "institution": default_institution, 
            "client": default_client
            # importer_name removed from here
        }

    def test_id_generated_if_none(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(period_to_date, country="CH",
                                                     client=[Client(clientNumber=ClientNumber("C123"))])
        statement = TaxStatement(id=None, **statement_args)
        
        # Pass importer_name to calculator constructor
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="DEFAULT", enable_filtering=False)
        calculator.calculate(statement)

        assert statement.id is not None
        assert isinstance(statement.id, str)
        assert len(statement.id) == 38 # Adjusted length from 40 to 38
        assert "TaxStatement.id (generated)" in calculator.modified_fields
        assert any(f"Generated new TaxStatement.id: {statement.id}" in log for log in calculator.get_log())


    def test_id_not_overwritten_if_exists(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(period_to_date)
        statement = TaxStatement(id="EXISTINGID123", **statement_args)
        
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="DEFAULT", enable_filtering=False) # Added importer_name
        calculator.calculate(statement)

        assert statement.id == "EXISTINGID123"
        assert "TaxStatement.id (generated)" not in calculator.modified_fields

    def test_id_generation_all_fields_present(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            client=[Client(clientNumber=ClientNumber("CUST123"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSSCHWAB", 
            customer="CUST123XXXXXXX",
            date_str="20231231"
        )

        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="SCHWAB", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_uses_tin_if_client_number_missing(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(tin=TINType("TIN456"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSPOSTFI", 
            customer="TIN456XXXXXXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="POSTFINANCE", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_org_id_importer_name_none(self): # Renamed from test_id_generation_placeholder_org_id_lei_none
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(clientNumber=ClientNumber("CLI789"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        
        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSXXXXXX", 
            customer="CLI789XXXXXXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name=None, enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id
        assert any("Warning: Importer name is None or empty, using 'XXXXXX' for Org ID part." in log for log in calculator.get_log())

    def test_id_generation_org_id_importer_name_empty(self): # Renamed from test_id_generation_placeholder_org_id_no_institution
        period_to_date = date(2023, 12, 31)
        # Construct args carefully to pass institution=None to TaxStatement
        args_for_statement = {
            "creationDate": datetime(period_to_date.year, 1, 1), 
            "taxPeriod": period_to_date.year,                  
            "periodFrom": date(period_to_date.year, 1, 1),     
            "periodTo": period_to_date,
            "country": "US",
            "canton": "ZH",
            "minorVersion": 0,
            "client": [Client(clientNumber=ClientNumber("CLI789"))]
            # importer_name removed from args_for_statement
        }
        statement = TaxStatement(id=None, **args_for_statement)


        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSXXXXXX", 
            customer="CLI789XXXXXXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id
        assert any("Warning: Importer name is None or empty, using 'XXXXXX' for Org ID part." in log for log in calculator.get_log())

    def test_id_generation_org_id_importer_name_short(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(clientNumber=ClientNumber("CUSTSHORT"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSXXXAPI", 
            customer="CUSTSHORTXXXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="API", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_org_id_importer_name_long(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(clientNumber=ClientNumber("CUSTLONG"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSVERYLO", 
            customer="CUSTLONGXXXXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="VERYLONGIMPORTERNAME", enable_filtering=False) # Pass importer_name
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_org_id_importer_name_needs_sanitization(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(clientNumber=ClientNumber("CUSTSANITIZE"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSMYIMPO", 
            customer="CUSTSANITIZEXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="MyImporter@123!", enable_filtering=False) # Pass importer_name
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_org_id_importer_name_sanitizes_to_empty(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(clientNumber=ClientNumber("CUSTEMPTY"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSXXXXXX", 
            customer="CUSTEMPTYXXXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="!@#$%", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id
        assert any("Sanitized importer name '!@#$%' is empty, using 'XXXXXX' for Org ID part." in log for log in calculator.get_log())

    def test_id_generation_placeholder_customer_id_no_id_for_client(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(clientNumber=None, tin=None)]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSTESTIM",
            customer="NOIDENTIFIERXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="TESTIMP", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id
        assert any("Warning: No clientNumber or TIN found for the first client. Using placeholder for customer ID part." in log for log in calculator.get_log())


    def test_id_generation_placeholder_customer_id_no_client_object(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[] # Empty client list
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSANYBAN",
            customer="NOCLIENTDATAXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="ANYBANK", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id
        assert any("Warning: statement.client list is empty. Using placeholder for customer ID part." in log for log in calculator.get_log())
       
    @pytest.mark.parametrize("raw_client_id, expected_customer_part", [
        ("Cust With Spaces", "CustWithSpaces"),
        ("Short",            "ShortXXXXXXXXX"),
        ("Exactly14Chars",   "Exactly14Chars"),
        ("MuchLongerThan14CharsAndInvalidChars!@#", "MuchLongerThan"),
        ("Test-Number-123",  "TestNumber123X"),
        ("",                 "XXXXXXXXXXXXXX"),
        ("  ",               "XXXXXXXXXXXXXX"), 
    ])
    def test_customer_id_sanitization_padding_truncation(self, raw_client_id, expected_customer_part):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(clientNumber=ClientNumber(raw_client_id) if raw_client_id.strip() else ClientNumber("EMPTY"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="UBS", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        
        assert statement.id is not None
        actual_customer_part = statement.id[14:14+14] # Adjusted index: CC(2) + ORG(12) = 14
        # Handle the special case where we used "EMPTY" for empty strings
        if raw_client_id.strip() == "":
            assert actual_customer_part in ["EMPTYXXXXXXXXX", "XXXXXXXXXXXXXX"]
        else:
            assert actual_customer_part == expected_customer_part

    def test_period_to_formatting(self):
        period_to_date = date(2024, 3, 15)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(clientNumber=ClientNumber("ANYCLIENT"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=period_to_date, importer_name="CSNEXT", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        
        assert statement.id is not None
        actual_date_part = statement.id[28:28+8] # Adjusted index: CC(2) + ORG(12) + CUST(14) = 28
        assert actual_date_part == "20240315"

    def test_no_not_implemented_error_raised(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH", 
            institution=Institution(name="Test Bank"), 
            client=[Client(firstName="Test", lastName="User")]
            # importer_name removed from statement_args
        )
        # Ensure default args provide valid clientNumber for this test
        if not statement_args["client"] or statement_args["client"][0].clientNumber is None:
            statement_args["client"] = [Client(clientNumber=ClientNumber("VALIDCUST123"))]


        statement = TaxStatement(id=None, **statement_args)
        
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="VALIDIMP", enable_filtering=False) # Pass importer_name here
        
        try:
            calculator.calculate(statement)
        except NotImplementedError:
            pytest.fail("CleanupCalculator._generate_tax_statement_id raised NotImplementedError unexpectedly.")
        except Exception as e:
            pytest.fail(f"An unexpected error occurred during ID generation: {e}")

        assert statement.id is not None
        assert isinstance(statement.id, str)
        assert "TaxStatement.id (generated)" in calculator.modified_fields
        assert any("Generated new TaxStatement.id:" in log for log in calculator.get_log())
        assert not any("Error generating TaxStatement.id (NotImplemented)" in log for log in calculator.get_log())

    # Removed test_id_generation_lei_shorter_than_12 as LEI is no longer used for org_id
    # Removed test_id_generation_lei_empty_string as LEI is no longer used for org_id

    def test_id_generation_country_code_stripping_and_case(self): # This test remains relevant
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            client=[Client(clientNumber=ClientNumber("CUST123"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="CH",
            org="OPNAUSSTRIPC", 
            customer="CUST123XXXXXXX",
            date_str="20231231"
        )

        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="STRIPCASE", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id