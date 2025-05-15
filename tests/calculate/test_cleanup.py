import pytest
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, List

from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    ListOfBankAccounts, BankAccount, BankAccountPayment, BankAccountNumber,
    ListOfSecurities, Depot, Security, SecurityStock, SecurityPayment, DepotNumber,
    CurrencyId, QuotationType
)


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
        statement = TaxStatement(minorVersion=2, listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))
        
        calculator = CleanupCalculator(None, None, enable_filtering=False)
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
        statement = TaxStatement(minorVersion=2, listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(None, None, enable_filtering=False)
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
        statement = TaxStatement(minorVersion=2, listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(None, None, enable_filtering=False)
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
        statement = TaxStatement(minorVersion=2, listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True, print_log=True)
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
        statement = TaxStatement(minorVersion=2, listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=False)
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts
        assert len(result_statement.listOfBankAccounts.bankAccount[0].payment) == 1
        assert not calculator.modified_fields

    def test_filter_bank_account_payments_no_period(self):
        payments = [create_bank_account_payment(date(2023,1,1))]
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=list(payments))
        statement = TaxStatement(minorVersion=2, listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator = CleanupCalculator(None, None, enable_filtering=True) # No period defined
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts
        assert len(result_statement.listOfBankAccounts.bankAccount[0].payment) == 1
        assert not calculator.modified_fields
        assert any("Payment filtering skipped (tax period not fully defined)" in log for log in calculator.get_log())

    def test_filter_security_stocks_enabled(self, sample_period_from, sample_period_to):
        period_end_plus_one = sample_period_to + timedelta(days=1)

        s_bal_before = create_security_stock(sample_period_from - timedelta(days=10), Decimal("90"), False)
        s_bal_start = create_security_stock(sample_period_from, Decimal("100"), False) # Keep
        s_mut_inside1 = create_security_stock(sample_period_from + timedelta(days=5), Decimal("10"), True) # Keep
        s_bal_inside_discard = create_security_stock(sample_period_from + timedelta(days=10), Decimal("110"), False) # Discard
        s_mut_inside2 = create_security_stock(sample_period_to - timedelta(days=5), Decimal("-5"), True) # Keep
        s_bal_end_plus_one = create_security_stock(period_end_plus_one, Decimal("105"), False) # Keep
        s_mut_after = create_security_stock(period_end_plus_one + timedelta(days=10), Decimal("20"), True)
        s_bal_after = create_security_stock(period_end_plus_one + timedelta(days=15), Decimal("125"), False)

        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=[s_bal_before, s_bal_start, s_mut_inside1, s_bal_inside_discard, s_mut_inside2, s_bal_end_plus_one, s_mut_after, s_bal_after]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(minorVersion=2, listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True, print_log=True)
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        filtered_stocks = result_statement.listOfSecurities.depot[0].security[0].stock
        
        expected_to_keep = [s_bal_start, s_mut_inside1, s_mut_inside2, s_bal_end_plus_one]
        
        assert len(filtered_stocks) == len(expected_to_keep)
        for item in expected_to_keep:
            assert item in filtered_stocks
        
        assert "D1/TestSec.stock (filtered)" in calculator.modified_fields
        assert any("Filtered 8 stock events to 4" in log for log in calculator.get_log())

    def test_filter_security_stocks_no_mutations_only_balances(self, sample_period_from, sample_period_to):
        period_end_plus_one = sample_period_to + timedelta(days=1)

        s_bal_before = create_security_stock(sample_period_from - timedelta(days=10), Decimal("90"), False)
        s_bal_start = create_security_stock(sample_period_from, Decimal("100"), False) # Keep
        s_bal_inside_discard = create_security_stock(sample_period_from + timedelta(days=10), Decimal("110"), False) # Discard
        s_bal_end_plus_one = create_security_stock(period_end_plus_one, Decimal("105"), False) # Keep
        s_bal_after = create_security_stock(period_end_plus_one + timedelta(days=15), Decimal("125"), False)

        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=[s_bal_before, s_bal_start, s_bal_inside_discard, s_bal_end_plus_one, s_bal_after]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(minorVersion=2, listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True)
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        filtered_stocks = result_statement.listOfSecurities.depot[0].security[0].stock
        assert len(filtered_stocks) == 2
        assert s_bal_start in filtered_stocks
        assert s_bal_end_plus_one in filtered_stocks
        assert "D1/TestSec.stock (filtered)" in calculator.modified_fields

    def test_filter_security_stocks_disabled(self, sample_period_from, sample_period_to):
        stocks = [create_security_stock(sample_period_from - timedelta(days=1), Decimal("10"), False)]
        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=list(stocks)
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(minorVersion=2, listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=False)
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        assert len(result_statement.listOfSecurities.depot[0].security[0].stock) == 1
        assert not calculator.modified_fields

    def test_filter_security_stocks_no_period(self):
        stocks = [create_security_stock(date(2023,1,1), Decimal("10"), False)]
        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=list(stocks)
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(minorVersion=2, listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(None, None, enable_filtering=True)
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        assert len(result_statement.listOfSecurities.depot[0].security[0].stock) == 1
        assert not calculator.modified_fields
        assert any("Stock event filtering skipped (tax period not fully defined)" in log for log in calculator.get_log())

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
        statement = TaxStatement(minorVersion=2, listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True)
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfSecurities
        filtered_payments = result_statement.listOfSecurities.depot[0].security[0].payment
        assert len(filtered_payments) == 2
        assert sp_inside1 in filtered_payments
        assert sp_inside2 in filtered_payments
        assert "D1/TestSec.payment (filtered)" in calculator.modified_fields


class TestCleanupCalculatorEdgeCases:

    def test_empty_statement(self, sample_period_from, sample_period_to):
        statement = TaxStatement(minorVersion=2)
        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True)
        result_statement = calculator.calculate(statement)
        
        assert result_statement.listOfBankAccounts is None
        assert result_statement.listOfSecurities is None
        assert not calculator.modified_fields
        assert any("No bank accounts found to process." in log for log in calculator.get_log())
        assert any("No securities accounts found to process." in log for log in calculator.get_log())

    def test_statement_with_no_bank_accounts(self, sample_period_from, sample_period_to):
        security = Security(positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec")
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(minorVersion=2, listOfSecurities=ListOfSecurities(depot=[depot]))
        
        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True)
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts is None
        assert result_statement.listOfSecurities is not None
        assert not calculator.modified_fields # No filtering happened on securities as they had no data
        assert any("No bank accounts found to process." in log for log in calculator.get_log())

    def test_statement_with_no_securities(self, sample_period_from, sample_period_to):
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"))
        statement = TaxStatement(minorVersion=2, listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True)
        result_statement = calculator.calculate(statement)

        assert result_statement.listOfBankAccounts is not None
        assert result_statement.listOfSecurities is None
        assert not calculator.modified_fields # No filtering happened on bank accounts as they had no data
        assert any("No securities accounts found to process." in log for log in calculator.get_log())

    def test_bank_account_with_no_payments(self, sample_period_from, sample_period_to):
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=[])
        statement = TaxStatement(minorVersion=2, listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))
        
        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True)
        calculator.calculate(statement)
        
        assert not calculator.modified_fields

    def test_security_with_no_stocks_or_payments(self, sample_period_from, sample_period_to):
        security = Security(
            positionId=1, country="CH", currency="CHF", quotationType="PIECE", securityCategory="SHARE", securityName="TestSec",
            stock=[], payment=[]
        )
        depot = Depot(depotNumber=DepotNumber("D1"), security=[security])
        statement = TaxStatement(minorVersion=2, listOfSecurities=ListOfSecurities(depot=[depot]))

        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True)
        calculator.calculate(statement)

        assert not calculator.modified_fields

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
            minorVersion=2,
            listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]),
            listOfSecurities=ListOfSecurities(depot=[depot])
        )

        calculator = CleanupCalculator(sample_period_from, sample_period_to, enable_filtering=True, print_log=False)
        calculator.calculate(statement)

        assert "BA001.payment (filtered)" in calculator.modified_fields
        assert "Dep01/SecXYZ.stock (filtered)" in calculator.modified_fields
        assert len(calculator.modified_fields) == 2
        
        final_log_message = calculator.get_log()[-1] # Last message should be the summary
        assert "Fields modified by filtering: BA001.payment (filtered), Dep01/SecXYZ.stock (filtered)" in final_log_message

    def test_no_filtering_if_period_not_fully_defined(self):
        p1 = create_bank_account_payment(date(2023,1,1))
        bank_account = BankAccount(bankAccountNumber=BankAccountNumber("BA1"), payment=[p1])
        statement = TaxStatement(minorVersion=2, listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account]))

        # Test with only period_from
        calculator_from_only = CleanupCalculator(date(2023,1,1), None, enable_filtering=True)
        res_from_only = calculator_from_only.calculate(statement)
        assert res_from_only.listOfBankAccounts
        assert len(res_from_only.listOfBankAccounts.bankAccount[0].payment) == 1
        assert not calculator_from_only.modified_fields
        assert any("Payment filtering skipped (tax period not fully defined)" in log for log in calculator_from_only.get_log())

        # Test with only period_to
        calculator_to_only = CleanupCalculator(None, date(2023,12,31), enable_filtering=True)
        res_to_only = calculator_to_only.calculate(statement)
        assert res_to_only.listOfBankAccounts
        assert len(res_to_only.listOfBankAccounts.bankAccount[0].payment) == 1
        assert not calculator_to_only.modified_fields
        assert any("Payment filtering skipped (tax period not fully defined)" in log for log in calculator_to_only.get_log())