import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Tuple

from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.model.ech0196 import (
    ISINType,
    TaxStatement,
    ListOfBankAccounts, BankAccount, BankAccountPayment, BankAccountNumber,
    BankAccountTaxValue,
    ListOfSecurities, Depot, Security, SecurityStock, SecurityPayment, DepotNumber,
    CurrencyId, QuotationType,
    ValorNumber,
    Institution,
    Client,
    ClientNumber,
    LEIType,
    TINType,
    LiabilityAccount,
    LiabilityAccountTaxValue,
    ListOfLiabilities,
    BankAccountName,
    CountryIdISO2Type
)
from opensteuerauszug.core.constants import UNINITIALIZED_QUANTITY # Added
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
            canton="ZH",
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

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "FilterImporter", enable_filtering=True)
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts
        filtered_payments = result_statement.listOfBankAccounts.bankAccount[0].payment
        assert len(filtered_payments) == 2
        assert p_inside1 in filtered_payments
        assert p_inside2 in filtered_payments
        assert "BA1.payment (filtered)" in calculator.modified_fields

    def test_filter_bank_account_payments_disabled(self, sample_period_from, sample_period_to):
        payments = [create_bank_account_payment(sample_period_from - timedelta(days=1))]
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=list(payments))
        statement = TaxStatement(
            canton="ZH",
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

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "FilterImporter", enable_filtering=True) # Added importer_name
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        filtered_stocks = result_statement.listOfSecurities.depot[0].security[0].stock
        
        expected_to_keep = [s_bal_start, s_mut_inside1, s_mut_inside2] # s_bal_end_plus_one removed
        
        assert len(filtered_stocks) == len(expected_to_keep)
        for item in expected_to_keep:
            assert item in filtered_stocks
        
        assert "D1/TestSec.stock (filtered)" in calculator.modified_fields
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


class TestCleanupCalculatorBankAccountDates:
    """Tests for clearing bank account openingDate/closingDate outside reporting window."""

    def test_opening_date_inside_period_is_kept(self, sample_period_from, sample_period_to):
        """openingDate within the reporting period should be preserved."""
        opening = date(2023, 5, 29)
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            openingDate=opening,
        )
        statement = TaxStatement(
            id="test_opening_kept", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.openingDate == opening
        assert not any("openingDate" in f for f in calculator.modified_fields)

    def test_opening_date_before_period_is_cleared(self, sample_period_from, sample_period_to):
        """openingDate before the reporting period should be cleared."""
        opening = date(2022, 6, 1)  # Before 2023-01-01
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            openingDate=opening,
        )
        statement = TaxStatement(
            id="test_opening_before", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.openingDate is None
        assert "BA1.openingDate (cleared)" in calculator.modified_fields

    def test_opening_date_after_period_is_cleared(self, sample_period_from, sample_period_to):
        """openingDate after the reporting period should be cleared."""
        opening = date(2024, 2, 1)  # After 2023-12-31
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            openingDate=opening,
        )
        statement = TaxStatement(
            id="test_opening_after", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.openingDate is None
        assert "BA1.openingDate (cleared)" in calculator.modified_fields

    def test_closing_date_inside_period_is_kept(self, sample_period_from, sample_period_to):
        """closingDate within the reporting period should be preserved."""
        closing = date(2023, 9, 15)
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            closingDate=closing,
        )
        statement = TaxStatement(
            id="test_closing_kept", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.closingDate == closing
        assert not any("closingDate" in f for f in calculator.modified_fields)

    def test_closing_date_before_period_is_cleared(self, sample_period_from, sample_period_to):
        """closingDate before the reporting period should be cleared."""
        closing = date(2022, 12, 31)  # Before 2023-01-01
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            closingDate=closing,
        )
        statement = TaxStatement(
            id="test_closing_before", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.closingDate is None
        assert "BA1.closingDate (cleared)" in calculator.modified_fields

    def test_closing_date_after_period_is_cleared(self, sample_period_from, sample_period_to):
        """closingDate after the reporting period should be cleared."""
        closing = date(2024, 1, 1)  # After 2023-12-31
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            closingDate=closing,
        )
        statement = TaxStatement(
            id="test_closing_after", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.closingDate is None
        assert "BA1.closingDate (cleared)" in calculator.modified_fields

    def test_both_dates_inside_period_are_kept(self, sample_period_from, sample_period_to):
        """Both openingDate and closingDate within the period should be preserved."""
        opening = date(2023, 3, 1)
        closing = date(2023, 9, 15)
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            openingDate=opening,
            closingDate=closing,
        )
        statement = TaxStatement(
            id="test_both_kept", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.openingDate == opening
        assert bank_account.closingDate == closing

    def test_both_dates_outside_period_are_cleared(self, sample_period_from, sample_period_to):
        """Both openingDate and closingDate outside the period should be cleared."""
        opening = date(2022, 1, 1)
        closing = date(2024, 6, 1)
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            openingDate=opening,
            closingDate=closing,
        )
        statement = TaxStatement(
            id="test_both_cleared", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.openingDate is None
        assert bank_account.closingDate is None
        assert "BA1.openingDate (cleared)" in calculator.modified_fields
        assert "BA1.closingDate (cleared)" in calculator.modified_fields

    def test_dates_on_period_boundaries_are_kept(self, sample_period_from, sample_period_to):
        """Dates exactly on period boundaries (first and last day) should be kept."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            openingDate=sample_period_from,  # 2023-01-01
            closingDate=sample_period_to,    # 2023-12-31
        )
        statement = TaxStatement(
            id="test_boundaries", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.openingDate == sample_period_from
        assert bank_account.closingDate == sample_period_to

    def test_none_dates_are_not_modified(self, sample_period_from, sample_period_to):
        """None dates should remain None and not trigger any modification."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BA1"),
            openingDate=None,
            closingDate=None,
        )
        statement = TaxStatement(
            id="test_none_dates", creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from, periodTo=sample_period_to,
            country="CH", canton="ZH", minorVersion=0,
            client=[Client(clientNumber=ClientNumber("DateClient"))],
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
        )
        calculator = CleanupCalculator(sample_period_from, sample_period_to, "DateTest", enable_filtering=False)
        calculator.calculate(statement)

        assert bank_account.openingDate is None
        assert bank_account.closingDate is None
        assert not any("openingDate" in f or "closingDate" in f for f in calculator.modified_fields)


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

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "EdgeImporter", enable_filtering=True) # Added importer_name
        calculator.calculate(statement)

        assert "TaxStatement.id (generated)" in calculator.modified_fields
        assert "BA001.payment (filtered)" in calculator.modified_fields
        assert "Dep01/SecXYZ.stock (filtered)" in calculator.modified_fields
        assert len(calculator.modified_fields) == 3        

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
        assert any("DTEST/TESTSYM_FULL (enriched)" in f for f in calculator.modified_fields)

    def test_enrichment_uses_symbol_success(self, base_calculator_params):
        test_map = {"MYSYMBOL": {"isin": "XS123123123", "valor": 987654}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="Some Name", symbol="MYSYMBOL")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "XS123123123"
        assert security.valorNumber == 987654
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

    def test_enrichment_symbol_not_in_map(self, base_calculator_params):
        test_map = {"KNOWN_SYMBOL": {"isin": "XS123", "valor": 987}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="Some Name", symbol="UNKNOWN_SYMBOL")
        statement = _create_statement_with_security(security, base_calculator_params["period_to"], depot_id_str="D_SYM_UNKNOWN")
        statement.id="PRESET_ID_SYM_UNKNOWN" # Avoid ID gen log
        calculator.calculate(statement)

        assert security.isin is None
        assert security.valorNumber is None

    def test_enrichment_symbol_is_none_uses_securityname_fallback(self, base_calculator_params):
        """If symbol is None, it should fall back to securityName for lookup."""
        test_map = {"FALLBACK_NAME": {"isin": "XS_FB", "valor": 321}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="FALLBACK_NAME", symbol=None) # Symbol is None
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "XS_FB"
        assert security.valorNumber == 321

    def test_enrichment_symbol_is_empty_string_uses_securityname_fallback(self, base_calculator_params):
        """If symbol is an empty string, it should fall back to securityName for lookup."""
        test_map = {"FALLBACK_NAME_EMPTY_SYM": {"isin": "XS_FB_EMPTY", "valor": 654}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)
        
        security = _create_test_security(name="FALLBACK_NAME_EMPTY_SYM", symbol="") # Symbol is empty string
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin == "XS_FB_EMPTY"
        assert security.valorNumber == 654


    def test_enrichment_map_none_or_empty_with_symbol(self, base_calculator_params):
        security_with_symbol = _create_test_security(name="Some Name", symbol="MYSYMBOL")
        statement = _create_statement_with_security(security_with_symbol, base_calculator_params["period_to"])
        statement.id = "PRESET_MAP_EMPTY_NONE"

        # Test with None map
        calc_none_map = CleanupCalculator(**base_calculator_params, identifier_map=None)
        calc_none_map.calculate(statement)
        assert security_with_symbol.isin is None
        assert security_with_symbol.valorNumber is None
        assert not calc_none_map.modified_fields # Only ID gen if not preset

        # Reset security fields for next test
        security_with_symbol.isin = None
        security_with_symbol.valorNumber = None

        # Test with empty map
        calc_empty_map = CleanupCalculator(**base_calculator_params, identifier_map={})
        calc_empty_map.calculate(statement)
        assert security_with_symbol.isin is None
        assert security_with_symbol.valorNumber is None
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
        calculator.calculate(statement)
        
        assert security.isin == "US1111111111"
        assert security.valorNumber == 1111111
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

    def test_enrichment_map_has_valor_only_by_name(self, base_calculator_params): # Renamed for clarity
        test_map = {"TESTSYM_NO_ISIN_NAME": {"isin": None, "valor": 7654321}}
        calculator = CleanupCalculator(**base_calculator_params, identifier_map=test_map)

        security = _create_test_security(name="TESTSYM_NO_ISIN_NAME") # Symbol is None
        statement = _create_statement_with_security(security, base_calculator_params["period_to"])
        calculator.calculate(statement)
        
        assert security.isin is None
        assert security.valorNumber == 7654321


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
        payment_event = create_security_payment(payment_date=payment_date, quantity=UNINITIALIZED_QUANTITY, name="DividendPaymentDateFallback")
        payment_event.exDate = None
        security.payment = [payment_event]

        # Stock setup: Held 60 shares on payment_date
        security.stock = [
            create_security_stock(date(2023, 1, 1), Decimal("50"), False, name="Opening Balance"), # Start of period
            create_security_stock(date(2023, 6, 1), Decimal("10"), True, name="Buy"), # 50 + 10 = 60
            create_security_stock(date(2023, 8, 1), Decimal("-5"), True, name="Sell")  # After payment date
        ]
        # Expected quantity at payment_date (2023-07-15) is 60 (50 from opening + 10 from buy on 2023-06-01)

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("60"), "Quantity should be updated to 60 (50+10) using paymentDate"

    def test_calculate_quantity_paymentdate_fallback_no_stock_held(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecPaymentDateFallbackNoStock")

        payment_date = date(2023, 8, 1)
        # Ensure exDate is None
        payment_event = create_security_payment(payment_date=payment_date, quantity=UNINITIALIZED_QUANTITY, name="DividendPaymentDateFallbackNoStock")
        payment_event.exDate = None
        security.payment = [payment_event]

        # Stock setup: All stock sold before payment_date
        security.stock = [
            create_security_stock(date(2023, 1, 1), Decimal("20"), False, name="Opening Balance"),
            create_security_stock(date(2023, 3, 1), Decimal("-20"), True, name="Sell All") # Sold before payment_date
        ]
        # Expected quantity at payment_date (2023-08-01) is 0

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("0"), "Quantity should be updated to 0 using paymentDate"

    def test_calculate_quantity_paymentdate_fallback_missing_stock_data(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecPaymentDateFallbackMissingStock")

        payment_date = date(2023, 9, 1)
        # Ensure exDate is None
        payment_event = create_security_payment(payment_date=payment_date, quantity=UNINITIALIZED_QUANTITY, name="DividendPaymentDateFallbackMissingStock")
        payment_event.exDate = None
        security.payment = [payment_event]

        # Stock setup: Empty stock list
        security.stock = [] # This will now trigger the new ValueError for missing stock data

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False)

        with pytest.raises(ValueError) as excinfo:
            calculator.calculate(statement)

        # This test now checks for the "Missing stock data" error, not "Could not determine"
        error_message = str(excinfo.value)
        assert "Missing stock data (Security.stock is None or empty)" in error_message
        assert f"for security '{security.isin}'" in error_message
        assert "which has payments requiring quantity calculation" in error_message
        assert security.payment[0].quantity == UNINITIALIZED_QUANTITY

    def test_calculate_quantity_paymentdate_fallback_stock_data_does_not_cover(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecPaymentDateFallbackNoCover")

        payment_date = date(2023, 6, 15) # Payment date
        # Ensure exDate is None
        payment_event = create_security_payment(payment_date=payment_date, quantity=UNINITIALIZED_QUANTITY, name="DividendPaymentDateFallbackNoCover")
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

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False)

        result_statement = calculator.calculate(statement)
        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("0"), f"Quantity should be 0, got {calculated_payment_result.quantity}"

    def test_calculate_quantity_exdate_prioritized_stock_held(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecExDatePrioritizedStockHeld")

        payment_date = date(2023, 7, 15)
        ex_date = date(2023, 7, 1) # exDate is before paymentDate

        payment_event = create_security_payment(payment_date=payment_date, quantity=UNINITIALIZED_QUANTITY, name="DividendExDatePriority")
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

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("50"), "Quantity should be 50 (based on exDate)"

    def test_calculate_quantity_exdate_no_stock_on_exdate(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecExDateNoStock")

        payment_date = date(2023, 7, 15)
        ex_date = date(2023, 7, 1)

        payment_event = create_security_payment(payment_date=payment_date, quantity=UNINITIALIZED_QUANTITY, name="DividendExDateNoStock")
        payment_event.exDate = ex_date
        security.payment = [payment_event]

        # Stock setup: All stock bought after exDate
        security.stock = [
            create_security_stock(date(2023, 1, 1), Decimal("0"), False, name="Opening Balance Zero"), # Explicit zero opening
            create_security_stock(date(2023, 7, 10), Decimal("30"), True, name="Buy after exDate")
        ]
        # Expected quantity is 0 based on exDate

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False)
        result_statement = calculator.calculate(statement)

        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("0"), "Quantity should be 0 (based on exDate)"

    def test_calculate_quantity_exdate_insufficient_stock_data_for_exdate(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(sample_period_from, sample_period_to, security_name="SecExDateInsufficientData")

        payment_date = date(2023, 7, 15)
        ex_date = date(2023, 7, 1)

        payment_event = create_security_payment(payment_date=payment_date, quantity=UNINITIALIZED_QUANTITY, name="DividendExDateInsufficient")
        payment_event.exDate = ex_date
        security.payment = [payment_event]

        # Stock setup: All stock transactions are after exDate, so reconciler returns None for exDate.
        security.stock = [
            create_security_stock(date(2023, 8, 1), Decimal("20"), True, name="Buy well after exDate")
        ]

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False)

        result_statement = calculator.calculate(statement)
        calculated_payment_result = result_statement.listOfSecurities.depot[0].security[0].payment[0]
        assert calculated_payment_result.quantity == Decimal("0"), f"Quantity should be 0, got {calculated_payment_result.quantity}"

    def test_calculate_quantity_raises_value_error_if_security_stock_missing(self, sample_period_from, sample_period_to):
        statement, security = self._create_base_statement_and_security(
            sample_period_from,
            sample_period_to,
            security_name="TestSecMissingStockOverall"
        )
        payment_event = create_security_payment(
            payment_date=date(2023, 6, 1),
            quantity=UNINITIALIZED_QUANTITY, # Needs calculation
            name="DividendMissingStockOverall"
        )
        security.payment = [payment_event]
        security.stock = [] # Explicitly empty

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "QtyCalcTestImporter", enable_filtering=False)

        with pytest.raises(ValueError) as excinfo:
            calculator.calculate(statement)

        error_message = str(excinfo.value)
        assert "Missing stock data (Security.stock is None or empty)" in error_message
        assert f"for security '{security.isin}'" in error_message # Check for actual name
        assert "which has payments requiring quantity calculation" in error_message
        assert security.payment[0].quantity == UNINITIALIZED_QUANTITY


class TestMoveNegativePaymentsToLiabilities:
    """Test cases for moving negative bank account payments to liability accounts."""

    def _create_test_statement(self, bank_payments: List[BankAccountPayment]) -> TaxStatement:
        """Helper to create a test statement with bank account payments."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("TEST-CHF"),
            bankAccountName=BankAccountName("Test Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=DEFAULT_TEST_PERIOD_TO,
                name="Test Balance",
                balanceCurrency=CurrencyId("CHF"),
                balance=Decimal("1000.00")
            ),
            payment=bank_payments
        )

        statement = TaxStatement(
            canton="ZH",
            id="TEST-ID",
            creationDate=datetime.now(),
            taxPeriod=DEFAULT_TEST_PERIOD_TO.year,
            periodFrom=DEFAULT_TEST_PERIOD_FROM,
            periodTo=DEFAULT_TEST_PERIOD_TO,
            country="CH",
            minorVersion=22,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )
        return statement

    def test_move_single_negative_payment_to_new_liability(self):
        """Test moving a single negative payment to a newly created liability account."""
        # Create bank account with one negative payment
        payments = [
            BankAccountPayment(
                paymentDate=date(2023, 6, 15),
                name="Interest Paid",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("-50.00")
            )
        ]

        statement = self._create_test_statement(payments)
        calculator = CleanupCalculator(
            period_from=DEFAULT_TEST_PERIOD_FROM,
            period_to=DEFAULT_TEST_PERIOD_TO,
            importer_name="TEST",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Check that negative payment was moved to liability
        assert result.listOfLiabilities is not None
        assert len(result.listOfLiabilities.liabilityAccount) == 1

        liability = result.listOfLiabilities.liabilityAccount[0]
        assert liability.bankAccountNumber == "TEST-CHF"
        assert len(liability.payment) == 1
        assert liability.payment[0].amount == Decimal("50.00")  # Stored as positive

        # Check that negative payment was removed from bank account
        assert len(result.listOfBankAccounts.bankAccount[0].payment) == 0

    def test_move_multiple_negative_payments_to_new_liability(self):
        """Test moving multiple negative payments to a newly created liability account."""
        payments = [
            BankAccountPayment(
                paymentDate=date(2023, 3, 10),
                name="Interest 1",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("-30.00")
            ),
            BankAccountPayment(
                paymentDate=date(2023, 9, 20),
                name="Interest 2",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("-25.50")
            )
        ]

        statement = self._create_test_statement(payments)
        calculator = CleanupCalculator(
            period_from=DEFAULT_TEST_PERIOD_FROM,
            period_to=DEFAULT_TEST_PERIOD_TO,
            importer_name="TEST",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Check that both negative payments were moved
        assert len(result.listOfLiabilities.liabilityAccount) == 1
        liability = result.listOfLiabilities.liabilityAccount[0]
        assert len(liability.payment) == 2
        assert liability.payment[0].amount == Decimal("30.00")
        assert liability.payment[1].amount == Decimal("25.50")

        # Bank account should have no payments
        assert len(result.listOfBankAccounts.bankAccount[0].payment) == 0

    def test_move_negative_payments_mixed_with_positive(self):
        """Test that only negative payments are moved, positive payments remain."""
        payments = [
            BankAccountPayment(
                paymentDate=date(2023, 2, 1),
                name="Positive Payment",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("100.00")
            ),
            BankAccountPayment(
                paymentDate=date(2023, 6, 15),
                name="Negative Payment",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("-40.00")
            ),
            BankAccountPayment(
                paymentDate=date(2023, 11, 30),
                name="Another Positive",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("75.50")
            )
        ]

        statement = self._create_test_statement(payments)
        calculator = CleanupCalculator(
            period_from=DEFAULT_TEST_PERIOD_FROM,
            period_to=DEFAULT_TEST_PERIOD_TO,
            importer_name="TEST",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Check liability account
        assert len(result.listOfLiabilities.liabilityAccount) == 1
        liability = result.listOfLiabilities.liabilityAccount[0]
        assert len(liability.payment) == 1
        assert liability.payment[0].amount == Decimal("40.00")

        # Check bank account still has positive payments
        bank_payments = result.listOfBankAccounts.bankAccount[0].payment
        assert len(bank_payments) == 2
        assert bank_payments[0].amount == Decimal("100.00")
        assert bank_payments[1].amount == Decimal("75.50")

    def test_append_negative_payments_to_existing_liability(self):
        """Test appending negative payments to an existing liability account."""
        # Create a statement with an existing liability from negative balance
        negative_balance_liability = LiabilityAccount(
            bankAccountNumber=BankAccountNumber("TEST-CHF"),
            bankAccountName=BankAccountName("Test Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=LiabilityAccountTaxValue(
                referenceDate=DEFAULT_TEST_PERIOD_TO,
                name="Negative Balance",
                balanceCurrency=CurrencyId("CHF"),
                balance=Decimal("500.00")
            ),
            totalTaxValue=Decimal("500.00"),
            totalGrossRevenueB=Decimal("0")
        )

        # Create bank account with negative payments
        payments = [
            BankAccountPayment(
                paymentDate=date(2023, 5, 15),
                name="Interest Payment",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("-60.00")
            )
        ]

        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("TEST-CHF"),
            bankAccountName=BankAccountName("Test Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=DEFAULT_TEST_PERIOD_TO,
                name="Balance",
                balanceCurrency=CurrencyId("CHF"),
                balance=Decimal("1000.00")
            ),
            payment=payments
        )

        statement = TaxStatement(
            canton="ZH",
            id="TEST-ID",
            creationDate=datetime.now(),
            taxPeriod=DEFAULT_TEST_PERIOD_TO.year,
            periodFrom=DEFAULT_TEST_PERIOD_FROM,
            periodTo=DEFAULT_TEST_PERIOD_TO,
            country="CH",
            minorVersion=22,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
            listOfLiabilities=ListOfLiabilities(liabilityAccount=[negative_balance_liability])
        )

        calculator = CleanupCalculator(
            period_from=DEFAULT_TEST_PERIOD_FROM,
            period_to=DEFAULT_TEST_PERIOD_TO,
            importer_name="TEST",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Check that negative payment was appended to existing liability
        assert len(result.listOfLiabilities.liabilityAccount) == 1
        liability = result.listOfLiabilities.liabilityAccount[0]
        assert len(liability.payment) == 1
        assert liability.payment[0].amount == Decimal("60.00")

    def test_no_negative_payments_no_liability_created(self):
        """Test that no liability account is created when all payments are positive."""
        payments = [
            BankAccountPayment(
                paymentDate=date(2023, 3, 1),
                name="Payment 1",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("100.00")
            ),
            BankAccountPayment(
                paymentDate=date(2023, 9, 1),
                name="Payment 2",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("200.00")
            )
        ]

        statement = self._create_test_statement(payments)
        calculator = CleanupCalculator(
            period_from=DEFAULT_TEST_PERIOD_FROM,
            period_to=DEFAULT_TEST_PERIOD_TO,
            importer_name="TEST",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Check that no liability account was created for negative payments
        # (might have liabilities from negative balances, but not from negative payments)
        if result.listOfLiabilities:
            # If liabilities exist, verify they're not from negative payments
            for liability in result.listOfLiabilities.liabilityAccount:
                # Liabilities from negative balances have taxValue.name = "Negative Balance"
                # or from negative payments have name = "Interest Payments"
                assert liability.taxValue.name != "Interest Payments"

        # Bank account should keep all positive payments
        assert len(result.listOfBankAccounts.bankAccount[0].payment) == 2

    def test_negative_payment_totals_calculated_correctly(self):
        """Test that totalGrossRevenueB is calculated correctly for negative payments."""
        payments = [
            BankAccountPayment(
                paymentDate=date(2023, 4, 10),
                name="Interest 1",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("-25.50")
            ),
            BankAccountPayment(
                paymentDate=date(2023, 8, 20),
                name="Interest 2",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("-34.75")
            )
        ]

        statement = self._create_test_statement(payments)
        calculator = CleanupCalculator(
            period_from=DEFAULT_TEST_PERIOD_FROM,
            period_to=DEFAULT_TEST_PERIOD_TO,
            importer_name="TEST",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        liability = result.listOfLiabilities.liabilityAccount[0]
        # totalGrossRevenueB should be sum of absolute amounts
        expected_total = Decimal("25.50") + Decimal("34.75")
        assert liability.totalGrossRevenueB == expected_total


class TestMergeLiabilityAccounts:
    """Test merging of liability accounts from negative balances and negative payments."""

    def test_negative_balance_and_payment_merged_to_single_liability(self):
        """Test that a bank account with both negative balance and negative payment creates a single merged liability."""
        # Create a bank account with negative balance and negative payment
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("MERGED001"),
            bankAccountName=BankAccountName("Merged Liability Account"),
            bankAccountCountry=CountryIdISO2Type("US"),
            bankAccountCurrency=CurrencyId("USD"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2025, 12, 31),
                name="Closing Balance",
                balanceCurrency="USD",
                balance=Decimal("-0.87"),
                value=Decimal("-0.87")
            ),
            payment=[
                BankAccountPayment(
                    paymentDate=date(2025, 11, 5),
                    name="USD DEBIT INT FOR OCT-2025",
                    amountCurrency=CurrencyId("USD"),
                    amount=Decimal("-2.01")
                )
            ]
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2025, 12, 31),
            taxPeriod=2025,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2025, 1, 1),
            period_to=date(2025, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Verify bank account balance was set to 0
        assert bank_account.taxValue.balance == Decimal("0")
        assert bank_account.taxValue.value == Decimal("0")

        # Verify all negative payments removed from bank account
        assert len(bank_account.payment) == 0

        # Verify only ONE liability account was created
        assert result.listOfLiabilities is not None
        assert len(result.listOfLiabilities.liabilityAccount) == 1

        liability = result.listOfLiabilities.liabilityAccount[0]

        # Verify liability has the balance from negative bank balance
        assert liability.taxValue.balance == Decimal("0.87")
        assert liability.taxValue.name == "Closing Balance"

        # Verify liability has the payment from negative bank payment
        assert len(liability.payment) == 1
        assert liability.payment[0].amount == Decimal("2.01")
        assert liability.payment[0].name == "USD DEBIT INT FOR OCT-2025"

        # Verify totals are calculated correctly
        # totalTaxValue should be from the balance
        assert liability.totalTaxValue == Decimal("0.87")
        # totalGrossRevenueB should be from the payment
        assert liability.totalGrossRevenueB == Decimal("2.01")

        # Verify account details match
        assert liability.bankAccountNumber == bank_account.bankAccountNumber
        assert liability.bankAccountCurrency == bank_account.bankAccountCurrency

    def test_multiple_negative_payments_with_negative_balance_merged(self):
        """Test that multiple negative payments and negative balance are all merged to single liability."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("MULTMERGE001"),
            bankAccountName=BankAccountName("Multi Merge Account"),
            bankAccountCountry=CountryIdISO2Type("US"),
            bankAccountCurrency=CurrencyId("EUR"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2025, 12, 31),
                name="Year End Balance",
                balanceCurrency="EUR",
                balance=Decimal("-5.50"),
                value=Decimal("-5.50")
            ),
            payment=[
                BankAccountPayment(
                    paymentDate=date(2025, 3, 10),
                    name="EUR DEBIT INT FOR FEB-2025",
                    amountCurrency=CurrencyId("EUR"),
                    amount=Decimal("-1.25")
                ),
                BankAccountPayment(
                    paymentDate=date(2025, 7, 15),
                    name="EUR DEBIT INT FOR JUN-2025",
                    amountCurrency=CurrencyId("EUR"),
                    amount=Decimal("-3.75")
                ),
                BankAccountPayment(
                    paymentDate=date(2025, 10, 20),
                    name="Positive Payment",
                    amountCurrency=CurrencyId("EUR"),
                    amount=Decimal("100.00")
                )
            ]
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2025, 12, 31),
            taxPeriod=2025,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2025, 1, 1),
            period_to=date(2025, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Verify only ONE liability account was created
        assert result.listOfLiabilities is not None
        assert len(result.listOfLiabilities.liabilityAccount) == 1

        liability = result.listOfLiabilities.liabilityAccount[0]

        # Verify liability has the balance
        assert liability.taxValue.balance == Decimal("5.50")

        # Verify liability has both negative payments (2 total)
        assert len(liability.payment) == 2
        payment_amounts = [p.amount for p in liability.payment]
        assert Decimal("1.25") in payment_amounts
        assert Decimal("3.75") in payment_amounts

        # Verify totalGrossRevenueB includes all payments
        expected_revenue = Decimal("1.25") + Decimal("3.75")
        assert liability.totalGrossRevenueB == expected_revenue

        # Verify positive payment stays in bank account
        assert len(bank_account.payment) == 1
        assert bank_account.payment[0].amount == Decimal("100.00")

    def test_negative_balance_processed_before_payments(self):
        """Test that negative balance creates liability first, then payments are appended."""
        # This test verifies the order of processing - important for the merge logic
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("ORDER001"),
            bankAccountName=BankAccountName("Order Test Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2025, 12, 31),
                name="Balance",
                balanceCurrency="CHF",
                balance=Decimal("-10.00"),
                value=Decimal("-10.00")
            ),
            payment=[
                BankAccountPayment(
                    paymentDate=date(2025, 6, 1),
                    name="CHF DEBIT INT FOR MAY-2025",
                    amountCurrency=CurrencyId("CHF"),
                    amount=Decimal("-2.50")
                )
            ]
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2025, 12, 31),
            taxPeriod=2025,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2025, 1, 1),
            period_to=date(2025, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Should have exactly one merged liability
        assert len(result.listOfLiabilities.liabilityAccount) == 1

        liability = result.listOfLiabilities.liabilityAccount[0]

        # Both balance and payment should be present
        assert liability.taxValue.balance == Decimal("10.00")
        assert len(liability.payment) == 1
        assert liability.payment[0].amount == Decimal("2.50")

    def test_multiple_currencies_create_separate_liabilities(self):
        """Test that negative balances/payments in different currencies create separate liabilities."""
        usd_account = BankAccount(
            bankAccountNumber=BankAccountNumber("MULTICURR-USD"),
            bankAccountName=BankAccountName("USD Account"),
            bankAccountCountry=CountryIdISO2Type("US"),
            bankAccountCurrency=CurrencyId("USD"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2025, 12, 31),
                name="Balance",
                balanceCurrency="USD",
                balance=Decimal("-1.00"),
                value=Decimal("-1.00")
            ),
            payment=[
                BankAccountPayment(
                    paymentDate=date(2025, 5, 1),
                    name="USD Interest",
                    amountCurrency=CurrencyId("USD"),
                    amount=Decimal("-0.50")
                )
            ]
        )

        eur_account = BankAccount(
            bankAccountNumber=BankAccountNumber("MULTICURR-EUR"),
            bankAccountName=BankAccountName("EUR Account"),
            bankAccountCountry=CountryIdISO2Type("US"),
            bankAccountCurrency=CurrencyId("EUR"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2025, 12, 31),
                name="Balance",
                balanceCurrency="EUR",
                balance=Decimal("-2.00"),
                value=Decimal("-2.00")
            ),
            payment=[
                BankAccountPayment(
                    paymentDate=date(2025, 5, 1),
                    name="EUR Interest",
                    amountCurrency=CurrencyId("EUR"),
                    amount=Decimal("-0.75")
                )
            ]
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2025, 12, 31),
            taxPeriod=2025,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[usd_account, eur_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2025, 1, 1),
            period_to=date(2025, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Should have 2 separate liability accounts (one per currency)
        assert len(result.listOfLiabilities.liabilityAccount) == 2

        # Verify USD liability
        usd_liability = next(
            (l for l in result.listOfLiabilities.liabilityAccount
             if l.bankAccountCurrency == CurrencyId("USD")),
            None
        )
        assert usd_liability is not None
        assert usd_liability.taxValue.balance == Decimal("1.00")
        assert len(usd_liability.payment) == 1
        assert usd_liability.payment[0].amount == Decimal("0.50")

        # Verify EUR liability
        eur_liability = next(
            (l for l in result.listOfLiabilities.liabilityAccount
             if l.bankAccountCurrency == CurrencyId("EUR")),
            None
        )
        assert eur_liability is not None
        assert eur_liability.taxValue.balance == Decimal("2.00")
        assert len(eur_liability.payment) == 1
        assert eur_liability.payment[0].amount == Decimal("0.75")

    def test_only_negative_balance_no_merge_needed(self):
        """Test that only negative balance (no payments) still works correctly."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("BALONLY001"),
            bankAccountName=BankAccountName("Balance Only Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2025, 12, 31),
                name="Balance",
                balanceCurrency="CHF",
                balance=Decimal("-15.00"),
                value=Decimal("-15.00")
            )
            # No payments
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2025, 12, 31),
            taxPeriod=2025,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2025, 1, 1),
            period_to=date(2025, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Should have exactly one liability
        assert len(result.listOfLiabilities.liabilityAccount) == 1

        liability = result.listOfLiabilities.liabilityAccount[0]
        assert liability.taxValue.balance == Decimal("15.00")
        assert liability.payment is None or len(liability.payment) == 0
        assert liability.totalGrossRevenueB == Decimal("0")

    def test_only_negative_payments_no_merge_needed(self):
        """Test that only negative payments (no negative balance) still works correctly."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("PAYONLY001"),
            bankAccountName=BankAccountName("Payment Only Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2025, 12, 31),
                name="Balance",
                balanceCurrency="CHF",
                balance=Decimal("100.00")  # Positive balance
            ),
            payment=[
                BankAccountPayment(
                    paymentDate=date(2025, 6, 1),
                    name="Interest Payment",
                    amountCurrency=CurrencyId("CHF"),
                    amount=Decimal("-5.00")
                )
            ]
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2025, 12, 31),
            taxPeriod=2025,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2025, 1, 1),
            period_to=date(2025, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Should have exactly one liability
        assert len(result.listOfLiabilities.liabilityAccount) == 1

        liability = result.listOfLiabilities.liabilityAccount[0]
        # No balance in taxValue (only from payments)
        assert liability.taxValue.balance == Decimal("0")
        assert liability.taxValue.name == "Interest Payments"
        assert len(liability.payment) == 1
        assert liability.payment[0].amount == Decimal("5.00")
        assert liability.totalGrossRevenueB == Decimal("5.00")
        assert liability.totalTaxValue == Decimal("0")

        # Bank account keeps positive balance
        assert bank_account.taxValue.balance == Decimal("100.00")


class TestNegativeBankAccountBalance:
    """Test handling of negative bank account balances."""

    def test_negative_bank_account_balance_converted_to_liability(self):
        """Test that a negative bank account balance is converted to a liability."""
        # Create a bank account with negative balance
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("NEGACC001"),
            bankAccountName=BankAccountName("Negative Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2023, 12, 31),
                balanceCurrency="CHF",
                balance=Decimal("-1500.50"),
                value=Decimal("-1500.50")
            )
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2023, 12, 31),
            taxPeriod=2023,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2023, 1, 1),
            period_to=date(2023, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Verify bank account balance was set to 0
        assert bank_account.taxValue.balance == Decimal("0")
        assert bank_account.taxValue.value == Decimal("0")

        # Verify liability was created
        assert result.listOfLiabilities is not None
        assert len(result.listOfLiabilities.liabilityAccount) == 1

        liability = result.listOfLiabilities.liabilityAccount[0]
        assert liability.taxValue.balance == Decimal("1500.50")
        assert liability.totalTaxValue == Decimal("1500.50")
        assert liability.bankAccountNumber == bank_account.bankAccountNumber
        assert bank_account.bankAccountName in liability.bankAccountName
        assert liability.bankAccountCountry == bank_account.bankAccountCountry
        assert liability.bankAccountCurrency == bank_account.bankAccountCurrency

    def test_positive_bank_account_not_converted(self):
        """Test that positive bank account balances are not converted to liabilities."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("POSACC001"),
            bankAccountName=BankAccountName("Positive Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2023, 12, 31),
                balanceCurrency="CHF",
                balance=Decimal("5000.00"),
                value=Decimal("5000.00")
            )
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2023, 12, 31),
            taxPeriod=2023,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2023, 1, 1),
            period_to=date(2023, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Verify bank account balance was NOT modified
        assert bank_account.taxValue.balance == Decimal("5000.00")
        assert bank_account.taxValue.value == Decimal("5000.00")

        # Verify no liability was created
        assert result.listOfLiabilities is None or len(result.listOfLiabilities.liabilityAccount) == 0

    def test_zero_bank_account_balance_not_converted(self):
        """Test that zero bank account balances are not converted to liabilities."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("ZEROACC001"),
            bankAccountName=BankAccountName("Zero Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2023, 12, 31),
                balanceCurrency="CHF",
                balance=Decimal("0.00"),
                value=Decimal("0.00")
            )
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2023, 12, 31),
            taxPeriod=2023,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2023, 1, 1),
            period_to=date(2023, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Verify bank account balance remains 0
        assert bank_account.taxValue.balance == Decimal("0.00")

        # Verify no liability was created
        assert result.listOfLiabilities is None or len(result.listOfLiabilities.liabilityAccount) == 0

    def test_multiple_bank_accounts_mixed_balances(self):
        """Test handling of multiple bank accounts with mixed positive/negative balances."""
        bank_accounts = [
            BankAccount(
                bankAccountNumber=BankAccountNumber("POS001"),
                bankAccountName=BankAccountName("Positive"),
                bankAccountCountry=CountryIdISO2Type("CH"),
                bankAccountCurrency=CurrencyId("CHF"),
                taxValue=BankAccountTaxValue(
                    referenceDate=date(2023, 12, 31),
                    balanceCurrency="CHF",
                    balance=Decimal("2000.00"),
                    value=Decimal("2000.00")
                )
            ),
            BankAccount(
                bankAccountNumber=BankAccountNumber("NEG001"),
                bankAccountName=BankAccountName("Negative"),
                bankAccountCountry=CountryIdISO2Type("CH"),
                bankAccountCurrency=CurrencyId("CHF"),
                taxValue=BankAccountTaxValue(
                    referenceDate=date(2023, 12, 31),
                    balanceCurrency="CHF",
                    balance=Decimal("-3000.25"),
                    value=Decimal("-3000.25")
                )
            ),
            BankAccount(
                bankAccountNumber=BankAccountNumber("ZERO001"),
                bankAccountName=BankAccountName("Zero"),
                bankAccountCountry=CountryIdISO2Type("CH"),
                bankAccountCurrency=CurrencyId("CHF"),
                taxValue=BankAccountTaxValue(
                    referenceDate=date(2023, 12, 31),
                    balanceCurrency="CHF",
                    balance=Decimal("0.00"),
                    value=Decimal("0.00")
                )
            ),
        ]

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2023, 12, 31),
            taxPeriod=2023,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=bank_accounts)
        )

        calculator = CleanupCalculator(
            period_from=date(2023, 1, 1),
            period_to=date(2023, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Verify positive account unchanged
        assert bank_accounts[0].taxValue.balance == Decimal("2000.00")

        # Verify negative account converted
        assert bank_accounts[1].taxValue.balance == Decimal("0")

        # Verify zero account unchanged
        assert bank_accounts[2].taxValue.balance == Decimal("0.00")

        # Verify only one liability created (from the negative account)
        assert result.listOfLiabilities is not None
        assert len(result.listOfLiabilities.liabilityAccount) == 1
        assert result.listOfLiabilities.liabilityAccount[0].bankAccountNumber == BankAccountNumber("NEG001")
        assert result.listOfLiabilities.liabilityAccount[0].taxValue.balance == Decimal("3000.25")

    def test_negative_balance_with_payments(self):
        """Test that negative balance conversion works with bank account payments."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("NEGPAY001"),
            bankAccountName=BankAccountName("Negative with Payments"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2023, 12, 31),
                balanceCurrency="CHF",
                balance=Decimal("-500.00"),
                value=Decimal("-500.00")
            ),
            payment=[
                BankAccountPayment(
                    paymentDate=date(2023, 6, 30),
                    name="Interest",
                    amountCurrency="CHF",
                    amount=Decimal("50.00"),
                    grossRevenueA=Decimal("50.00")
                )
            ]
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2023, 12, 31),
            taxPeriod=2023,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2023, 1, 1),
            period_to=date(2023, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Verify bank account balance was set to 0
        assert bank_account.taxValue.balance == Decimal("0")

        # Verify liability was created (but the payments are not copied over)
        assert result.listOfLiabilities is not None
        assert len(result.listOfLiabilities.liabilityAccount) == 1
        liability = result.listOfLiabilities.liabilityAccount[0]
        assert liability.taxValue.balance == Decimal("500.00")

        # Original bank account payments should remain unchanged
        assert len(bank_account.payment) == 1
        assert bank_account.payment[0].amount == Decimal("50.00")

    def test_negative_balance_preserves_account_dates(self):
        """Test that opening/closing dates are preserved when converting negative balance."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("NEGDATES001"),
            bankAccountName=BankAccountName("Negative with Dates"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            openingDate=date(2023, 1, 15),
            closingDate=date(2023, 11, 30),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2023, 12, 31),
                balanceCurrency="CHF",
                balance=Decimal("-1000.00"),
                value=Decimal("-1000.00")
            )
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2023, 12, 31),
            taxPeriod=2023,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2023, 1, 1),
            period_to=date(2023, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        result = calculator.calculate(statement)

        # Verify liability has the same dates as the original bank account
        liability = result.listOfLiabilities.liabilityAccount[0]
        assert liability.openingDate == date(2023, 1, 15)
        assert liability.closingDate == date(2023, 11, 30)

    def test_negative_balance_modified_fields_tracking(self):
        """Test that negative balance conversion is properly tracked in modified_fields."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("NEGTRACK001"),
            bankAccountName=BankAccountName("Tracked Negative"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            taxValue=BankAccountTaxValue(
                referenceDate=date(2023, 12, 31),
                balanceCurrency="CHF",
                balance=Decimal("-750.00"),
                value=Decimal("-750.00")
            )
        )

        statement = TaxStatement(
            minorVersion=22,
            canton="ZH",
            country="CH",
            periodTo=date(2023, 12, 31),
            taxPeriod=2023,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account])
        )

        calculator = CleanupCalculator(
            period_from=date(2023, 1, 1),
            period_to=date(2023, 12, 31),
            importer_name="TestImporter",
            enable_filtering=False
        )

        calculator.calculate(statement)

        # Verify modification tracking
        assert "NEGTRACK001.taxValue (converted to liability)" in calculator.modified_fields
        assert "NEGTRACK001.taxValue.balance (set to 0)" in calculator.modified_fields
        assert any("listOfLiabilities (added" in field for field in calculator.modified_fields)


class TestCleanupCalculatorIDGeneration:
    """Tests for TaxStatement ID generation logic in CleanupCalculator."""

    def _construct_expected_id(self, country: str, clearing: str, customer: str, date_str: str, seq: str = "01") -> str:
        """Helper to construct expected ID in 31-char format: CC + CCCCC + CCCCCCCCCCCCCC + YYYYMMDD + SS"""
        return f"{country}{clearing}{customer}{date_str}{seq}"

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
        assert len(statement.id) == 31 # Updated from 38 to 31
        assert "TaxStatement.id (generated)" in calculator.modified_fields


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
        # Create an institution with a specific name to get a predictable clearing number
        institution = Institution(name="SCHWAB")
        statement_args = self._default_statement_args(
            period_to_date,
            institution=institution,
            client=[Client(clientNumber=ClientNumber("CUST123"))]
        )
        statement = TaxStatement(id=None, **statement_args)

        # compute_org_nr will hash "SCHWAB" and produce a clearing number
        # For "SCHWAB", hash_organization_name produces "258", so clearing is "19258"
        expected_id = self._construct_expected_id(
            country="CH",
            clearing="19258", 
            customer="SCHWABCUST123X",
            date_str="20231231"
        )

        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="SCHWAB", enable_filtering=False)
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_uses_tin_if_client_number_missing(self):
        period_to_date = date(2023, 12, 31)
        institution = Institution(name="POSTFINANCE")
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            institution=institution,
            client=[Client(tin=TINType("TIN456"))]
        )
        statement = TaxStatement(id=None, **statement_args)

        # For "POSTFINANCE", hash produces "030", so clearing is "19030"
        expected_id = self._construct_expected_id(
            country="CH",
            clearing="19030", 
            customer="POSTFINANCETIN",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="POSTFINANCE", enable_filtering=False)
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_no_institution(self):
        period_to_date = date(2023, 12, 31)
        # Don't provide institution, so compute_org_nr returns default "19999"
        args_for_statement = {
            "creationDate": datetime(period_to_date.year, 1, 1),
            "taxPeriod": period_to_date.year,
            "periodFrom": date(period_to_date.year, 1, 1),
            "periodTo": period_to_date,
            "country": "CH",
            "canton": "ZH",
            "minorVersion": 0,
            "client": [Client(clientNumber=ClientNumber("CLI789"))]
        }
        statement = TaxStatement(id=None, **args_for_statement)
        
        expected_id = self._construct_expected_id(
            country="CH",
            clearing="19999",  # Default when no institution
            customer="CLI789XXXXXXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name=None, enable_filtering=False)
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_empty_institution_name(self):
        period_to_date = date(2023, 12, 31)
        # Provide institution with empty name, should get default "19999"
        institution = Institution(name="")
        args_for_statement = {
            "creationDate": datetime(period_to_date.year, 1, 1), 
            "taxPeriod": period_to_date.year,                  
            "periodFrom": date(period_to_date.year, 1, 1),     
            "periodTo": period_to_date,
            "country": "CH",
            "canton": "ZH",
            "minorVersion": 0,
            "institution": institution,
            "client": [Client(clientNumber=ClientNumber("CLI789"))]
        }
        statement = TaxStatement(id=None, **args_for_statement)

        expected_id = self._construct_expected_id(
            country="CH",
            clearing="19999",  # Default when institution name is empty
            customer="CLI789XXXXXXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="", enable_filtering=False)
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_institution_with_specific_name(self):
        """Test that different institution names produce different clearing numbers"""
        period_to_date = date(2023, 12, 31)
        institution = Institution(name="UBS")
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            institution=institution,
            client=[Client(clientNumber=ClientNumber("CUSTLONG"))]
        )
        statement = TaxStatement(id=None, **statement_args)
        
        # For "UBS", hash produces "545", so clearing is "19545"
        expected_id = self._construct_expected_id(
            country="CH",
            clearing="19545", 
            customer="UBSCUSTLONGXXX",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="UBS", enable_filtering=False)
        calculator.calculate(statement)
        assert statement.id == expected_id

    def test_id_generation_placeholder_customer_id_no_id_for_client(self):
        period_to_date = date(2023, 12, 31)
        institution = Institution(name="TESTIMP")
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            institution=institution,
            client=[Client(clientNumber=None, tin=None)]
        )
        statement = TaxStatement(id=None, **statement_args)

        # For "TESTIMP", hash produces "022", so clearing is "19022"
        expected_id = self._construct_expected_id(
            country="CH",
            clearing="19022",
            customer="TESTIMPNOIDENT",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="TESTIMP", enable_filtering=False)
        calculator.calculate(statement)
        assert statement.id == expected_id


    def test_id_generation_placeholder_customer_id_no_client_object(self):
        period_to_date = date(2023, 12, 31)
        institution = Institution(name="ANYBANK")
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            institution=institution,
            client=[]
        )
        statement = TaxStatement(id=None, **statement_args)

        # For "ANYBANK", hash produces "272", so clearing is "19272"
        expected_id = self._construct_expected_id(
            country="CH",
            clearing="19272",
            customer="ANYBANKNOCLIEN",
            date_str="20231231"
        )
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="ANYBANK", enable_filtering=False)
        calculator.calculate(statement)
        assert statement.id == expected_id
       
    @pytest.mark.parametrize("raw_client_id", [
        "Cust With Spaces",
        "Short",
        "Exactly14Chars",
        "MuchLongerThan14CharsAndInvalidChars!@#",
        "Test-Number-123",
        "",
        "  ",
    ])
    def test_customer_id_sanitization_padding_truncation(self, raw_client_id):
        period_to_date = date(2023, 12, 31)
        institution = Institution(name="UBS")
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            institution=institution,
            client=[Client(clientNumber=ClientNumber(raw_client_id) if raw_client_id.strip() else ClientNumber("EMPTY"))]
        )
        statement = TaxStatement(id=None, **statement_args)
        
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="UBS", enable_filtering=False)
        calculator.calculate(statement)
        
        assert statement.id is not None
        actual_customer_part = statement.id[7:7+14]  # CC(2) + Clearing(5) = 7
        # Build expected using importer prefix 'UBS' + sanitized client id (or 'EMPTY'), padded/truncated to 14
        import re
        importer_prefix = "UBS"
        base = raw_client_id if raw_client_id.strip() else "EMPTY"
        sanitized = re.sub(r"[^a-zA-Z0-9]", "", base)
        expected = (importer_prefix + sanitized)[:14].ljust(14, "X")
        assert actual_customer_part == expected

    def test_period_to_formatting(self):
        period_to_date = date(2024, 3, 15)
        institution = Institution(name="CSNEXT")
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            institution=institution,
            client=[Client(clientNumber=ClientNumber("ANYCLIENT"))]
        )
        statement = TaxStatement(id=None, **statement_args)

        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=period_to_date, importer_name="CSNEXT", enable_filtering=False)
        calculator.calculate(statement)
        
        assert statement.id is not None
        actual_date_part = statement.id[21:21+8]  # CC(2) + Clearing(5) + Customer(14) = 21
        assert actual_date_part == "20240315"

    def test_no_not_implemented_error_raised(self):
        period_to_date = date(2023, 12, 31)
        institution = Institution(name="Test Bank")
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            institution=institution,
            client=[Client(clientNumber=ClientNumber("VALIDCUST123"))]
        )
        statement = TaxStatement(id=None, **statement_args)
        
        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="VALIDIMP", enable_filtering=False)
        
        try:
            calculator.calculate(statement)
        except NotImplementedError:
            pytest.fail("CleanupCalculator._generate_tax_statement_id raised NotImplementedError unexpectedly.")
        except Exception as e:
            pytest.fail(f"An unexpected error occurred during ID generation: {e}")

        assert statement.id is not None
        assert isinstance(statement.id, str)
        assert "TaxStatement.id (generated)" in calculator.modified_fields

    def test_id_generation_country_code_stripping_and_case(self):
        period_to_date = date(2023, 12, 31)
        institution = Institution(name="STRIPCASE")
        statement_args = self._default_statement_args(
            period_to_date,
            country="CH",
            institution=institution,
            client=[Client(clientNumber=ClientNumber("CUST123"))]
        )
        statement = TaxStatement(id=None, **statement_args)

        # For "STRIPCASE", hash produces "159", so clearing is "19159"
        expected_id = self._construct_expected_id(
            country="CH",
            clearing="19159", 
            customer="STRIPCASECUST1",
            date_str="20231231"
        )

        calculator = CleanupCalculator(period_from=DEFAULT_TEST_PERIOD_FROM, period_to=DEFAULT_TEST_PERIOD_TO, importer_name="STRIPCASE", enable_filtering=False)
        calculator.calculate(statement)
        assert statement.id == expected_id


class TestCleanupCalculatorClosingBalanceQuantity:
    """Tests for SecurityTaxValue creation based on closing balance quantity."""

    def test_closing_balance_quantity_nonzero_creates_tax_value(self, sample_period_from, sample_period_to):
        """When closing balance quantity is non-zero, SecurityTaxValue should be created."""
        # Create stock with non-zero closing balance at period_end + 1 day
        closing_balance_date = sample_period_to + timedelta(days=1)
        closing_stock = create_security_stock(
            closing_balance_date,
            Decimal("100"),  # Non-zero quantity
            mutation=False,
            name="Closing Balance",
            balance_currency="CHF"
        )
        closing_stock.balance = Decimal("5000.00")
        closing_stock.unitPrice = Decimal("50.00")

        security = Security(
            positionId=1,
            country="CH",
            currency="CHF",
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName="TestSecurity",
            stock=[closing_stock]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None,
            creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from,
            periodTo=sample_period_to,
            country="CH",
            canton="ZH",
            minorVersion=0,
            client=[Client(clientNumber=ClientNumber("ClosingBalanceClient"))],
            institution=Institution(lei=LEIType("CLOSINGBALEI1234000000")),
            listOfSecurities=ListOfSecurities(depot=[depot])
        )

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "ClosingBalanceImporter", enable_filtering=False)
        result_statement = calculator.calculate(statement)

        # Verify taxValue was created
        result_security = result_statement.listOfSecurities.depot[0].security[0]
        assert result_security.taxValue is not None
        assert result_security.taxValue.quantity == Decimal("100")
        assert result_security.taxValue.balance == Decimal("5000.00")
        assert result_security.taxValue.referenceDate == sample_period_to

    def test_closing_balance_quantity_zero_no_tax_value(self, sample_period_from, sample_period_to):
        """When closing balance quantity is zero, SecurityTaxValue should NOT be created."""
        # Create stock with zero closing balance at period_end + 1 day
        closing_balance_date = sample_period_to + timedelta(days=1)
        closing_stock = create_security_stock(
            closing_balance_date,
            Decimal("0"),  # Zero quantity
            mutation=False,
            name="Zero Closing Balance",
            balance_currency="CHF"
        )
        closing_stock.balance = Decimal("0.00")
        closing_stock.unitPrice = Decimal("50.00")

        security = Security(
            positionId=1,
            country="CH",
            currency="CHF",
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName="TestSecurityZero",
            stock=[closing_stock]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None,
            creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from,
            periodTo=sample_period_to,
            country="CH",
            canton="ZH",
            minorVersion=0,
            client=[Client(clientNumber=ClientNumber("ZeroBalanceClient"))],
            institution=Institution(lei=LEIType("QTYLEI12345000000000")),
            listOfSecurities=ListOfSecurities(depot=[depot])
        )

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "ZeroBalanceImporter", enable_filtering=False)
        result_statement = calculator.calculate(statement)

        # Verify taxValue was NOT created
        result_security = result_statement.listOfSecurities.depot[0].security[0]
        assert result_security.taxValue is None

    def test_closing_balance_quantity_none_no_tax_value(self, sample_period_from, sample_period_to):
        """When closing balance quantity is None, SecurityTaxValue should NOT be created."""
        # Create stock with None quantity at period_end + 1 day
        closing_balance_date = sample_period_to + timedelta(days=1)
        closing_stock = create_security_stock(
            closing_balance_date,
            Decimal("50"),  # Will be overridden to None
            mutation=False,
            name="None Quantity Closing",
            balance_currency="CHF"
        )
        closing_stock.quantity = None  # Override with None
        closing_stock.balance = Decimal("0.00")

        security = Security(
            positionId=1,
            country="CH",
            currency="CHF",
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName="TestSecurityNone",
            stock=[closing_stock]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None,
            creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from,
            periodTo=sample_period_to,
            country="CH",
            canton="ZH",
            minorVersion=0,
            client=[Client(clientNumber=ClientNumber("NoneQtyClient"))],
            institution=Institution(lei=LEIType("QTYLEI12345000000000")),
            listOfSecurities=ListOfSecurities(depot=[depot])
        )

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "NoneQtyImporter", enable_filtering=False)
        result_statement = calculator.calculate(statement)

        # Verify taxValue was NOT created
        result_security = result_statement.listOfSecurities.depot[0].security[0]
        assert result_security.taxValue is None

    def test_closing_balance_quantity_positive_creates_tax_value(self, sample_period_from, sample_period_to):
        """When closing balance quantity is positive (non-zero), SecurityTaxValue should be created."""
        closing_balance_date = sample_period_to + timedelta(days=1)
        closing_stock = create_security_stock(
            closing_balance_date,
            Decimal("0.001"),  # Very small but non-zero quantity
            mutation=False,
            name="Fractional Closing",
            balance_currency="CHF"
        )
        closing_stock.balance = Decimal("0.05")
        closing_stock.unitPrice = Decimal("50.00")

        security = Security(
            positionId=1,
            country="CH",
            currency="CHF",
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName="FractionalSec",
            stock=[closing_stock]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(
            id=None,
            creationDate=datetime(sample_period_to.year, 1, 1),
            taxPeriod=sample_period_to.year,
            periodFrom=sample_period_from,
            periodTo=sample_period_to,
            country="CH",
            canton="ZH",
            minorVersion=0,
            client=[Client(clientNumber=ClientNumber("FractionalClient"))],
            institution=Institution(lei=LEIType("FRACTIONEI1234000000")),
            listOfSecurities=ListOfSecurities(depot=[depot])
        )

        calculator = CleanupCalculator(sample_period_from, sample_period_to, "FractionalImporter", enable_filtering=False)
        result_statement = calculator.calculate(statement)

        # Verify taxValue was created for non-zero quantity
        result_security = result_statement.listOfSecurities.depot[0].security[0]
        assert result_security.taxValue is not None
        assert result_security.taxValue.quantity == Decimal("0.001")

