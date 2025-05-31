"""
Test that verifies the bugfix for SecurityTaxValue.referenceDate in CleanupCalculator.

This test ensures that when creating SecurityTaxValue from end-of-period balances,
the referenceDate is correctly set to the period end date (self.period_to) rather
than the candidate's date (which is period_end_plus_one).

The bug was in cleanup.py line 262 where:
- WRONG: referenceDate=candidate.referenceDate (period_end_plus_one)
- FIXED: referenceDate=self.period_to (actual period end)

Without the fix, this test would fail because the SecurityTaxValue would have
referenceDate=2024-01-01 instead of the correct referenceDate=2023-12-31.
"""

import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal

from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.model.ech0196 import (
    TaxStatement, Security, SecurityStock, SecurityTaxValue, Depot, ListOfSecurities,
    Institution, Client, LEIType, ClientNumber, ValorNumber, ISINType, CurrencyId, DepotNumber
)


class TestCleanupTaxValueReferenceDate:
    """Test SecurityTaxValue reference date handling in CleanupCalculator."""
    
    def test_tax_value_reference_date_from_end_of_period_balance(self):
        """
        Test that SecurityTaxValue.referenceDate is set to period_to when created from 
        end-of-period balance, not to the balance's date (period_end_plus_one).
        
        This test would FAIL without the bugfix because the referenceDate would be
        incorrectly set to 2024-01-01 (candidate.referenceDate) instead of the 
        correct 2023-12-31 (self.period_to).
        """
        # Define test period
        period_from = date(2023, 1, 1)
        period_to = date(2023, 12, 31)
        period_end_plus_one = period_to + timedelta(days=1)  # 2024-01-01
        
        # Create a security with a balance after the period end
        # This represents the end-of-period balance that should be used for tax value
        end_balance_stock = SecurityStock(
            referenceDate=period_end_plus_one,  # 2024-01-01 (day after period end)
            mutation=False,  # This is a balance, not a transaction
            quotationType="PIECE",
            quantity=Decimal("100"),
            balanceCurrency="CHF",
            name="End of Period Balance",
            unitPrice=Decimal("50.00"),
            balance=Decimal("5000.00")
        )
        
        # Create security without initial taxValue (will be set by cleanup)
        security = Security(
            positionId=1,
            valorNumber=ValorNumber(123456),
            isin=ISINType("CH0001234567"),
            name="Test Security",
            country="CH",
            currency="CHF",
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName="Test Security",
            stock=[end_balance_stock]
            # Note: taxValue is None initially - will be set by CleanupCalculator
        )
        
        # Create depot and statement
        depot = Depot(
            depotNumber=DepotNumber("TEST_DEPOT"),
            security=[security]
        )
        
        statement = TaxStatement(
            id="test-statement",
            creationDate=datetime(2023, 1, 1),
            taxPeriod=2023,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="ZH",
            minorVersion=2,
            listOfSecurities=ListOfSecurities(depot=[depot])
        )
        
        # Run cleanup calculator
        calculator = CleanupCalculator(
            period_from=period_from,
            period_to=period_to,
            importer_name="TestImporter",
            enable_filtering=False
        )
        
        result_statement = calculator.calculate(statement)
        
        # Verify that the cleanup calculator created a SecurityTaxValue
        result_security = result_statement.listOfSecurities.depot[0].security[0]
        assert result_security.taxValue is not None, "SecurityTaxValue should be created by cleanup"
        
        # THIS IS THE CRITICAL TEST: referenceDate should be period_to, NOT period_end_plus_one
        assert result_security.taxValue.referenceDate == period_to, (
            f"SecurityTaxValue.referenceDate should be {period_to} (period end), "
            f"but was {result_security.taxValue.referenceDate}. "
            f"This indicates the bug where referenceDate was set to candidate.referenceDate "
            f"({period_end_plus_one}) instead of self.period_to ({period_to})."
        )
        
        # Verify other fields are correctly copied from the balance
        assert result_security.taxValue.quantity == Decimal("100")
        assert result_security.taxValue.quotationType == "PIECE"
        assert result_security.taxValue.balanceCurrency == "CHF"
        assert result_security.taxValue.balance == Decimal("5000.00")
        assert result_security.taxValue.unitPrice == Decimal("50.00")

    def test_tax_value_not_created_when_no_end_of_period_balance(self):
        """
        Test that SecurityTaxValue is not created when there's no balance at period_end_plus_one.
        This serves as a control test to ensure our main test is actually testing the right scenario.
        """
        period_from = date(2023, 1, 1)
        period_to = date(2023, 12, 31)
        
        # Create a security with only a transaction during the period (no end balance)
        transaction_stock = SecurityStock(
            referenceDate=date(2023, 6, 15),  # Some date during the period
            mutation=True,  # This is a transaction, not a balance
            quotationType="PIECE",
            quantity=Decimal("50"),
            balanceCurrency="CHF",
            name="Mid-period Transaction",
            unitPrice=Decimal("45.00"),
            balance=Decimal("2250.00")
        )
        
        security = Security(
            positionId=1,
            valorNumber=ValorNumber(123456),
            isin=ISINType("CH0001234567"),
            name="Test Security",
            country="CH",
            currency="CHF",
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName="Test Security",
            stock=[transaction_stock]
        )
        
        depot = Depot(
            depotNumber=DepotNumber("TEST_DEPOT"),
            security=[security]
        )
        
        statement = TaxStatement(
            id="test-statement",
            creationDate=datetime(2023, 1, 1),
            taxPeriod=2023,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="ZH",
            minorVersion=2,
            listOfSecurities=ListOfSecurities(depot=[depot])
        )
        
        calculator = CleanupCalculator(
            period_from=period_from,
            period_to=period_to,
            importer_name="TestImporter",
            enable_filtering=False
        )
        
        result_statement = calculator.calculate(statement)
        
        # Verify that no SecurityTaxValue was created
        result_security = result_statement.listOfSecurities.depot[0].security[0]
        assert result_security.taxValue is None, (
            "SecurityTaxValue should not be created when there's no end-of-period balance"
        )

    def test_tax_value_not_created_when_balance_is_mutation(self):
        """
        Test that SecurityTaxValue is not created when the stock at period_end_plus_one
        is a mutation (transaction) rather than a balance.
        """
        period_from = date(2023, 1, 1)
        period_to = date(2023, 12, 31)
        period_end_plus_one = period_to + timedelta(days=1)
        
        # Create a transaction on period_end_plus_one (mutation=True)
        # This should NOT trigger tax value creation
        transaction_after_period = SecurityStock(
            referenceDate=period_end_plus_one,
            mutation=True,  # This is a transaction, not a balance
            quotationType="PIECE",
            quantity=Decimal("25"),
            balanceCurrency="CHF",
            name="Transaction After Period",
            unitPrice=Decimal("52.00"),
            balance=Decimal("1300.00")
        )
        
        security = Security(
            positionId=1,
            valorNumber=ValorNumber(123456),
            isin=ISINType("CH0001234567"),
            name="Test Security",
            country="CH",
            currency="CHF",
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName="Test Security",
            stock=[transaction_after_period]
        )
        
        depot = Depot(
            depotNumber=DepotNumber("TEST_DEPOT"),
            security=[security]
        )
        
        statement = TaxStatement(
            id="test-statement",
            creationDate=datetime(2023, 1, 1),
            taxPeriod=2023,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="ZH",
            minorVersion=2,
            listOfSecurities=ListOfSecurities(depot=[depot])
        )
        
        calculator = CleanupCalculator(
            period_from=period_from,
            period_to=period_to,
            importer_name="TestImporter",
            enable_filtering=False
        )
        
        result_statement = calculator.calculate(statement)
        
        # Verify that no SecurityTaxValue was created because the stock entry is a mutation
        result_security = result_statement.listOfSecurities.depot[0].security[0]
        assert result_security.taxValue is None, (
            "SecurityTaxValue should not be created when the stock at period_end_plus_one "
            "is a mutation (transaction) rather than a balance"
        )

    def test_tax_value_created_only_for_first_balance_after_period_end(self):
        """
        Test that only the first balance after the period end is used for tax value creation,
        even if there are multiple stock entries after the period end.
        """
        period_from = date(2023, 1, 1)
        period_to = date(2023, 12, 31)
        period_end_plus_one = period_to + timedelta(days=1)
        
        # Create first balance on period_end_plus_one (should be used)
        first_balance = SecurityStock(
            referenceDate=period_end_plus_one,
            mutation=False,
            quotationType="PIECE",
            quantity=Decimal("100"),
            balanceCurrency="CHF",
            name="First Balance After Period",
            unitPrice=Decimal("50.00"),
            balance=Decimal("5000.00")
        )
        
        # Create second balance later (should be ignored)
        second_balance = SecurityStock(
            referenceDate=date(2024, 1, 5),
            mutation=False,
            quotationType="PIECE",
            quantity=Decimal("150"),
            balanceCurrency="CHF",
            name="Later Balance",
            unitPrice=Decimal("55.00"),
            balance=Decimal("8250.00")
        )
        
        security = Security(
            positionId=1,
            valorNumber=ValorNumber(123456),
            isin=ISINType("CH0001234567"),
            name="Test Security",
            country="CH",
            currency="CHF",
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName="Test Security",
            stock=[first_balance, second_balance]
        )
        
        depot = Depot(
            depotNumber=DepotNumber("TEST_DEPOT"),
            security=[security]
        )
        
        statement = TaxStatement(
            id="test-statement",
            creationDate=datetime(2023, 1, 1),
            taxPeriod=2023,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="ZH",
            minorVersion=2,
            listOfSecurities=ListOfSecurities(depot=[depot])
        )
        
        calculator = CleanupCalculator(
            period_from=period_from,
            period_to=period_to,
            importer_name="TestImporter",
            enable_filtering=False
        )
        
        result_statement = calculator.calculate(statement)
        
        # Verify that SecurityTaxValue was created
        result_security = result_statement.listOfSecurities.depot[0].security[0]
        assert result_security.taxValue is not None
        
        # Verify it uses the first balance, not the second
        assert result_security.taxValue.referenceDate == period_to  # The bug fix
        assert result_security.taxValue.quantity == Decimal("100")  # From first balance
        assert result_security.taxValue.unitPrice == Decimal("50.00")  # From first balance
        assert result_security.taxValue.balance == Decimal("5000.00")  # From first balance
        
        # Should NOT have values from the second balance
        assert result_security.taxValue.quantity != Decimal("150")
        assert result_security.taxValue.unitPrice != Decimal("55.00")
        assert result_security.taxValue.balance != Decimal("8250.00")