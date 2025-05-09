import unittest
from unittest.mock import patch, MagicMock
import decimal
from datetime import date

from opensteuerauszug.importers.schwab.statement_extractor import StatementExtractor
from opensteuerauszug.model.position import SecurityPosition, CashPosition
from opensteuerauszug.model.ech0196 import SecurityStock

class TestStatementExtractorPositions(unittest.TestCase):

    def _create_mock_extractor(self, extracted_data):
        mock_extractor = MagicMock(spec=StatementExtractor)
        mock_extractor.extract_data.return_value = extracted_data
        # Bind the real _next_business_day method to the mock instance
        mock_extractor._next_business_day = StatementExtractor._next_business_day.__get__(mock_extractor, StatementExtractor)

        # Need to bind the method to the mock instance for it to work correctly within extract_positions
        mock_extractor.extract_positions = StatementExtractor.extract_positions.__get__(mock_extractor, StatementExtractor)
        return mock_extractor

    def test_extract_positions_uses_opening_and_closing_values(self):
        # Mock data returned by extract_data
        mock_data = {
            'start_date': date(2023, 1, 1),
            'end_date': date(2023, 1, 31),
            'symbol': 'AAPL',
            'opening_shares': decimal.Decimal('10'),
            'closing_shares': decimal.Decimal('15'),
            'opening_cash': decimal.Decimal('1000.00'),
            'closing_cash': decimal.Decimal('1500.00'),
            'closing_price': decimal.Decimal('150.00'), # Not directly tested here but needed
            'closing_value': decimal.Decimal('2250.00') # Not directly tested here but needed
        }

        extractor = self._create_mock_extractor(mock_data)
        results = extractor.extract_positions()

        self.assertIsNotNone(results, "extract_positions should return results")
        positions, open_date, close_date_plus1, depot = results

        self.assertEqual(open_date, date(2023, 1, 1))
        self.assertEqual(close_date_plus1, date(2023, 2, 1)) # 31st Jan is Tue, next biz day is 1st Feb
        self.assertEqual(depot, 'AWARDS')
        self.assertEqual(len(positions), 4, "Should have 2 security (open/close) and 2 cash (open/close) positions")

        security_positions = [p for p, s in positions if isinstance(p, SecurityPosition)]
        cash_positions = [p for p, s in positions if isinstance(p, CashPosition)]
        
        self.assertEqual(len(security_positions), 2)
        self.assertEqual(len(cash_positions), 2)

        # Check Security Positions
        found_security_open = False
        found_security_close = False
        for pos_obj, stock_obj in positions:
            if isinstance(pos_obj, SecurityPosition):
                self.assertEqual(pos_obj.symbol, 'AAPL')
                if stock_obj.referenceDate == date(2023, 1, 1):
                    self.assertEqual(stock_obj.quantity, decimal.Decimal('10'), "Opening shares mismatch")
                    found_security_open = True
                elif stock_obj.referenceDate == date(2023, 2, 1):
                    self.assertEqual(stock_obj.quantity, decimal.Decimal('15'), "Closing shares mismatch")
                    found_security_close = True
        
        self.assertTrue(found_security_open, "Opening security position not found or matched")
        self.assertTrue(found_security_close, "Closing security position not found or matched")

        # Check Cash Positions
        found_cash_open = False
        found_cash_close = False
        for pos_obj, stock_obj in positions:
            if isinstance(pos_obj, CashPosition):
                self.assertEqual(pos_obj.currentCy, 'USD')
                if stock_obj.referenceDate == date(2023, 1, 1):
                    self.assertEqual(stock_obj.quantity, decimal.Decimal('1000.00'), "Opening cash quantity mismatch")
                    self.assertEqual(stock_obj.balance, decimal.Decimal('1000.00'), "Opening cash balance mismatch")
                    found_cash_open = True
                elif stock_obj.referenceDate == date(2023, 2, 1):
                    self.assertEqual(stock_obj.quantity, decimal.Decimal('1500.00'), "Closing cash quantity mismatch")
                    self.assertEqual(stock_obj.balance, decimal.Decimal('1500.00'), "Closing cash balance mismatch")
                    found_cash_close = True

        self.assertTrue(found_cash_open, "Opening cash position not found or matched")
        self.assertTrue(found_cash_close, "Closing cash position not found or matched")

    def test_extract_positions_handles_missing_opening_values(self):
        # Mock data with missing opening values
        mock_data_missing_open = {
            'start_date': date(2023, 3, 1),
            'end_date': date(2023, 3, 31),
            'symbol': 'GOOG',
            'opening_shares': None, # Missing
            'closing_shares': decimal.Decimal('20'),
            'opening_cash': None,   # Missing
            'closing_cash': decimal.Decimal('2000.00'),
            'closing_price': decimal.Decimal('100.00'),
            'closing_value': decimal.Decimal('2000.00')
        }
        extractor_missing = self._create_mock_extractor(mock_data_missing_open)
        results_missing = extractor_missing.extract_positions()

        self.assertIsNotNone(results_missing)
        positions_missing, open_date_missing, close_date_plus1_missing, _ = results_missing

        # Expected dates for assertions
        expected_open_date = date(2023, 3, 1)
        # March 31 2023 is a Friday, so next business day is April 3 2023
        expected_close_date_plus1 = date(2023, 4, 3) 

        self.assertEqual(open_date_missing, expected_open_date)
        self.assertEqual(close_date_plus1_missing, expected_close_date_plus1)

        # Since opening_shares and opening_cash are None, only closing positions should exist.
        # So, 1 for closing security and 1 for closing cash.
        self.assertEqual(len(positions_missing), 2, "Should only have closing security and closing cash positions")

        has_opening_security_position = any(
            isinstance(p, SecurityPosition) and s.referenceDate == expected_open_date
            for p, s in positions_missing
        )
        self.assertFalse(has_opening_security_position, "No opening security position should be created if opening_shares is None")

        has_opening_cash_position = any(
            isinstance(p, CashPosition) and s.referenceDate == expected_open_date
            for p, s in positions_missing
        )
        self.assertFalse(has_opening_cash_position, "No opening cash position should be created if opening_cash is None")

        # Check that closing positions are still created correctly
        has_closing_security_position = any(
            isinstance(p, SecurityPosition) and s.referenceDate == expected_close_date_plus1 and s.quantity == decimal.Decimal('20')
            for p, s in positions_missing
        )
        self.assertTrue(has_closing_security_position, "Closing security position not found or incorrect")

        has_closing_cash_position = any(
            isinstance(p, CashPosition) and s.referenceDate == expected_close_date_plus1 and s.quantity == decimal.Decimal('2000.00')
            for p, s in positions_missing
        )
        self.assertTrue(has_closing_cash_position, "Closing cash position not found or incorrect")

if __name__ == '__main__':
    unittest.main() 