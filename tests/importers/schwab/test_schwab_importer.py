import unittest
from unittest.mock import MagicMock, patch
from datetime import date, datetime
from decimal import Decimal

from opensteuerauszug.importers.schwab.schwab_importer import SchwabImporter
from opensteuerauszug.importers.schwab.transaction_extractor import TransactionExtractor # Assuming path
from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    SecurityPayment,
    SecurityStock,
    CurrencyId,      # This is an Annotated[str, ...]
    QuotationType,   # This is a Literal["PIECE", "PERCENT"]
    DepotNumber,     # This is class DepotNumber(str)
    # Import other necessary eCH-0196 models if needed for constructing test data
)
from opensteuerauszug.model.position import SecurityPosition
# Assuming your models are Pydantic, otherwise adjust instantiation

class TestSchwabImporterProcessing(unittest.TestCase):

    def test_transaction_with_multiple_stock_items_does_not_duplicate_payments(self):
        """
        Tests that if TransactionExtractor returns a single transaction with multiple
        SecurityStock items but a single list of SecurityPayment items, these payments
        are not duplicated in the final TaxStatement for the security.
        """
        # 1. Setup mock data
        test_depot_str = "DP1"
        test_symbol = "TESTETF"
        period_from_date = date(2023, 1, 1)
        period_to_date = date(2023, 12, 31)

        # Mock SecurityPosition
        mock_position = SecurityPosition(depot=test_depot_str, symbol=test_symbol, type="security")

        # Mock SecurityStock items (multiple)
        mock_stock_item_1 = SecurityStock(
            referenceDate=period_from_date, 
            mutation=False,
            balanceCurrency="CHF", 
            quotationType="PIECE", 
            quantity=Decimal('10'),
            name="Test Stock Lot 1" # Optional: using name for description
            # Removed invalid fields like isin, valor, exchangeRateToCHF etc.
        )
        mock_stock_item_2 = SecurityStock(
            referenceDate=period_from_date,
            mutation=False,
            balanceCurrency="CHF", 
            quotationType="PIECE", 
            quantity=Decimal('20'),
            name="Test Stock Lot 2"
        )
        mock_stocks_list = [mock_stock_item_1, mock_stock_item_2]

        # Mock SecurityPayment items (a list of unique payments)
        # Ensure all required fields for SecurityPayment are present.
        # Required: paymentDate, quotationType, quantity, amountCurrency
        mock_payment_1 = SecurityPayment(
            name="Dividend Payment 1",
            paymentDate=date(2023, 6, 15),
            amountCurrency="CHF", 
            quotationType="PIECE", 
            quantity=Decimal('1'), # Example quantity for payment
            amount=Decimal("50.00"), # Optional, but good for testing
            grossRevenueB=Decimal("50.00") # Optional
        )
        mock_payment_2 = SecurityPayment(
            name="Interest Payment 1",
            paymentDate=date(2023, 7, 20),
            amountCurrency="CHF", 
            quotationType="PIECE", 
            quantity=Decimal('1'), # Example
            amount=Decimal("25.00"), # Optional
            grossRevenueB=Decimal("25.00") # Optional
        )
        mock_payments_list = [mock_payment_1, mock_payment_2]

        # Mock return value for TransactionExtractor.extract_transactions
        # (position, stocks, payments, depot, (start_date, end_date))
        mock_transaction_data = [
            (mock_position, mock_stocks_list, mock_payments_list, test_depot_str, (period_from_date, period_to_date))
        ]

        # 2. Patch TransactionExtractor
        with patch('opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor') as MockTransactionExtractor:
            # Configure the instance's extract_transactions method
            mock_extractor_instance = MockTransactionExtractor.return_value
            mock_extractor_instance.extract_transactions.return_value = mock_transaction_data

            # 3. Initialize SchwabImporter and run import
            importer = SchwabImporter(period_from=period_from_date, period_to=period_to_date)
            # We pass a dummy filename because TransactionExtractor is mocked
            tax_statement = importer.import_files(['dummy.json'])

            # 4. Assertions
            self.assertIsNotNone(tax_statement)
            self.assertIsNotNone(tax_statement.listOfSecurities, "listOfSecurities should not be None")
            
            # Explicit if check to help linter with type narrowing
            if tax_statement.listOfSecurities is not None:
                list_of_securities = tax_statement.listOfSecurities
                self.assertEqual(len(list_of_securities.depot), 1, "Should be one depot")
                
                depot_data = list_of_securities.depot[0]
                self.assertIsNotNone(depot_data.depotNumber, "Depot number should not be None")
                # DepotNumber is a str subclass, can be compared directly or cast to str
                self.assertEqual(depot_data.depotNumber, test_depot_str) 

                self.assertEqual(len(depot_data.security), 1, "Should be one security entry for TESTETF")

                security_entry = depot_data.security[0]
                self.assertEqual(security_entry.securityName, test_symbol)
                
                # Key Assertion: Check the number of payments
                self.assertIsNotNone(security_entry.payment, "Payments list should not be None")
                self.assertEqual(len(security_entry.payment), len(mock_payments_list),
                                 f"Expected {len(mock_payments_list)} payments, but got {len(security_entry.payment)}. Payments found: {security_entry.payment}")
            else:
                # This else block should not be reached if the assertIsNotNone above works
                self.fail("tax_statement.listOfSecurities was None after assertIsNotNone, which is unexpected.")


if __name__ == '__main__':
    unittest.main() 