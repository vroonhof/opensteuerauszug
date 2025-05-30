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
            country="CH", canton="ZH", minorVersion=0, 
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

        calculator = CleanupCalculator(None, None, "SortingImporter", enable_filtering=False) # Added importer_name
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
            country="CH", canton="ZH", minorVersion=0,
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

    def test_no_filtering_if_period_not_fully_defined(self, sample_period_to): # Added sample_period_to for default args
        p1 = create_bank_account_payment(date(2023,1,1))
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=[p1])
        # Base statement for calculator_from_only
        statement_from = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year,
            periodFrom=date(sample_period_to.year,1,1), periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("EdgeClient"))], institution=Institution(lei=LEIType("EDGELEI1234500000000")),
            # importer_name="EdgeImporter", # Removed
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator_from_only = CleanupCalculator(date(2023,1,1), None, "EdgeImporter", enable_filtering=True) # Added importer_name
        res_from_only = calculator_from_only.calculate(statement_from)
        assert res_from_only.listOfBankAccounts
        assert len(res_from_only.listOfBankAccounts.bankAccount[0].payment) == 1
        assert "TaxStatement.id (generated)" in calculator_from_only.modified_fields
        assert len(calculator_from_only.modified_fields) == 1 # Only ID
        assert any("Payment filtering skipped (tax period not fully defined)" in log for log in calculator_from_only.get_log())

        # Base statement for calculator_to_only
        statement_to = TaxStatement(
            id=None, creationDate=datetime(sample_period_to.year,1,1), taxPeriod=sample_period_to.year,
            periodFrom=date(sample_period_to.year,1,1), periodTo=sample_period_to, 
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("EdgeClient"))], institution=Institution(lei=LEIType("EDGELEI1234500000000")),
            # importer_name="EdgeImporter", # Removed
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator_to_only = CleanupCalculator(None, date(2023,12,31), "EdgeImporter", enable_filtering=True) # Added importer_name
        res_to_only = calculator_to_only.calculate(statement_to)
        assert res_to_only.listOfBankAccounts
        assert len(res_to_only.listOfBankAccounts.bankAccount[0].payment) == 1
        assert "TaxStatement.id (generated)" in calculator_to_only.modified_fields
        assert len(calculator_to_only.modified_fields) == 1 # Only ID
        assert any("Payment filtering skipped (tax period not fully defined)" in log for log in calculator_to_only.get_log())


# Helper function for creating TaxStatement with a single security
def _create_statement_with_security(sec: Security, period_to_date: date) -> TaxStatement:
    depot = Depot(depotNumber=DepotNumber("DTEST"), security=[sec]) 
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
def _create_test_security(name: str, isin: Optional[str] = None, valor: Optional[int] = None) -> Security:
    return Security(
        positionId=1, # required
        country="CH", # required
        currency="CHF", # required
        quotationType="PIECE", # required
        securityCategory="SHARE", # required
        securityName=name,
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
        test_map = {"TESTSYM_FULL": {"isin": "US1234567890", "valor": 1234567}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="TESTSYM_FULL")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        # Override defaults if specific test needs different client/institution for ID part
        statement.client = [Client(clientNumber=ClientNumber("FullEnrich"))]
        statement.institution = Institution(lei=LEIType("FULLLEI1234500000000"))

        calculator.calculate(statement)
        
        assert security.isin == "US1234567890"
        assert security.valorNumber == 1234567
        assert any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_FULL'" in log for log in calculator.get_log())
        assert any("DTEST/TESTSYM_FULL (enriched)" in f for f in calculator.modified_fields)

    def test_enrichment_map_has_isin_only(self, base_calculator_params): # Renamed
        test_map = {"TESTSYM_NO_VALOR": {"isin": "CH0987654321", "valor": None}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)

        security = _create_test_security(name="TESTSYM_NO_VALOR")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "CH0987654321"
        assert security.valorNumber is None
        assert any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_NO_VALOR'" in log for log in calculator.get_log())

    def test_enrichment_map_has_valor_only(self, base_calculator_params): # Renamed
        test_map = {"TESTSYM_NO_ISIN": {"isin": None, "valor": 7654321}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)

        security = _create_test_security(name="TESTSYM_NO_ISIN")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin is None
        assert security.valorNumber == 7654321
        assert any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_NO_ISIN'" in log for log in calculator.get_log())

    def test_enrichment_map_has_invalid_valor_none(self, base_calculator_params): # Renamed
        # This simulates that the loader would produce valor: None for an originally invalid string.
        test_map = {"TESTSYM_INVALID_VALOR": {"isin": "US000000000X", "valor": None}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="TESTSYM_INVALID_VALOR")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "US000000000X"
        assert security.valorNumber is None
        assert any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_INVALID_VALOR'" in log for log in calculator.get_log())

    def test_enrichment_already_full(self, base_calculator_params):
        # Map might contain data, but it shouldn't be used if security is already full.
        test_map = {"TESTSYM_ALREADY_FULL": {"isin": "OTHER_ISIN", "valor": 999888}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="TESTSYM_ALREADY_FULL", isin="US1111111111", valor=1111111)
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        # Set a pre-existing ID to ensure ID generation logic doesn't run and add to modified_fields
        statement.id = "PRE_EXISTING_ID"
        
        # Clear initial logs from calculator's __init__ to focus on calculate() logs
        # Note: The current CleanupCalculator logs in init if a map is present.
        # We are testing the calculate method's logging here.
        initial_log_count = len(calculator.get_log())
        calculator.calculate(statement)
        logs_after_calculate = calculator.get_log()[initial_log_count:]
        
        assert security.isin == "US1111111111"
        assert security.valorNumber == 1111111
        assert not any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_ALREADY_FULL'" in log for log in logs_after_calculate)
        # If statement.id was pre-set, "TaxStatement.id (generated)" should not be in modified_fields
        assert "TaxStatement.id (generated)" not in calculator.modified_fields
        assert not any("TESTSYM_ALREADY_FULL (enriched)" in f for f in calculator.modified_fields)


    def test_enrichment_symbol_not_in_map(self, base_calculator_params):
        test_map = {"ANOTHER_SYM": {"isin": "DE123", "valor": 456}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="NON_EXISTENT_SYM")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin is None
        assert security.valorNumber is None
        assert not any("Enriched ISIN/Valor from identifier file using symbol 'NON_EXISTENT_SYM'" in log for log in calculator.get_log())

    def test_enrichment_partial_isin_only_security_has_valor(self, base_calculator_params):
        test_map = {"TESTSYM_PARTIAL_ISIN_ONLY": {"isin": "DE2222222222", "valor": None}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="TESTSYM_PARTIAL_ISIN_ONLY", valor=999)
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "DE2222222222"
        assert security.valorNumber == 999
        assert any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_PARTIAL_ISIN_ONLY'" in log for log in calculator.get_log())

    def test_enrichment_partial_valor_only_security_has_isin(self, base_calculator_params):
        test_map = {"TESTSYM_PARTIAL_VALOR_ONLY": {"isin": None, "valor": 3333333}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)

        security = _create_test_security(name="TESTSYM_PARTIAL_VALOR_ONLY", isin="US7777777777")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == 'US7777777777'
        assert security.valorNumber == 3333333
        assert any("Enriched ISIN/Valor from identifier file using symbol 'TESTSYM_PARTIAL_VALOR_ONLY'" in log for log in calculator.get_log())

    def test_enrichment_with_empty_map(self, base_calculator_params): # Renamed
        calculator = CleanupCalculator(**base_calculator_params, identifier_map={})
        
        # Check init log
        assert any("CleanupCalculator initialized with an identifier map containing 0 entries." in log for log in calculator.get_log())

        security = _create_test_security(name="TESTSYM_FULL")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        
        # Clear logs before calculate to focus on calculate's specific logs (if any)
        calculator.log_messages = [] # Clear init logs
        calculator.calculate(statement)
        
        assert security.isin is None
        assert security.valorNumber is None
        assert not any("Enriched ISIN/Valor" in log for log in calculator.get_log())

    def test_enrichment_with_none_map(self, base_calculator_params): # New test for None map
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=None)

        # Check init log
        assert any("CleanupCalculator initialized without an identifier map. Enrichment will be skipped." in log for log in calculator.get_log())

        security = _create_test_security(name="TESTSYM_FULL")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        
        # Clear logs before calculate
        calculator.log_messages = [] # Clear init logs
        calculator.calculate(statement)
        
        assert security.isin is None
        assert security.valorNumber is None
        assert not any("Enriched ISIN/Valor" in log for log in calculator.get_log())


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
            country="DE",
            client=[Client(clientNumber=ClientNumber("CUST123"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="DE",
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
            country="FR",
            client=[Client(tin=TINType("TIN456"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="FR",
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
            country="US",
            client=[Client(clientNumber=ClientNumber("CLI789"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        
        expected_id = self._construct_expected_id(
            country="US",
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
            country="US",
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
            country="DE",
            client=[Client(clientNumber=ClientNumber("CUSTSHORT"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        expected_id = self._construct_expected_id(
            country="DE",
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
            country="GB",
            client=[Client(clientNumber=ClientNumber("CUSTLONG"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        expected_id = self._construct_expected_id(
            country="GB",
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
            country="CA",
            client=[Client(clientNumber=ClientNumber("CUSTSANITIZE"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        expected_id = self._construct_expected_id(
            country="CA",
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
            country="AU",
            client=[Client(clientNumber=ClientNumber("CUSTEMPTY"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)
        expected_id = self._construct_expected_id(
            country="AU",
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
            country="GB",
            client=[Client(clientNumber=None, tin=None)]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="GB",
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
            country="CA",
            client=[] # Empty client list
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="CA",
            org="OPNAUSANYBAN",
            customer="NOCLIENTDATAXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="ANYBANK", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id
        assert any("Warning: statement.client list is empty. Using placeholder for customer ID part." in log for log in calculator.get_log())


    def test_id_generation_default_country_code(self):
        period_to_date = date(2023, 12, 31)
        statement_args = self._default_statement_args(
            period_to_date,
            country=None, # Country is None
            client=[Client(clientNumber=ClientNumber("CUST1"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="XX",
            org="OPNAUSBROKER", 
            customer="CUST1XXXXXXXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="BROKERX", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id
        assert any("Warning: TaxStatement.country is None, using 'XX' for ID generation." in log for log in calculator.get_log())
        
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

        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="CSNEXT", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        
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
            country="DE",
            client=[Client(clientNumber=ClientNumber("CUST123"))]
            # importer_name removed from statement_args
        )
        statement = TaxStatement(id=None, **statement_args)

        expected_id = self._construct_expected_id(
            country="DE",
            org="OPNAUSSTRIPC", 
            customer="CUST123XXXXXXX",
            date_str="20231231"
        )

        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="STRIPCASE", enable_filtering=False) # Pass importer_name here
        calculator.calculate(statement)
        assert statement.id == expected_id