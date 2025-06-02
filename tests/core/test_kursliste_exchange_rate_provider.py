import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.core.kursliste_accessor import KurslisteAccessor # Added import
from opensteuerauszug.model.kursliste import Kursliste, ExchangeRateYearEnd, ExchangeRateMonthly, ExchangeRate

# Define a consistent tax year for tests that need it for the accessor
TEST_TAX_YEAR = 2023

class TestKurslisteExchangeRateProvider(unittest.TestCase):

    def setUp(self):
        self.kursliste_manager_mock = MagicMock() # Mock KurslisteManager
        self.kursliste_mock = MagicMock(spec=Kursliste) # Mock Kursliste (for XML data path)

        # Default behavior: manager returns a KurslisteAccessor wrapping the mock Kursliste
        # The accessor is configured for TEST_TAX_YEAR.
        # Note: Some tests might override this return_value for specific scenarios.
        mock_accessor = KurslisteAccessor([self.kursliste_mock], tax_year=TEST_TAX_YEAR)
        self.kursliste_manager_mock.get_kurslisten_for_year.return_value = mock_accessor

        # Initialize exchange rate lists to empty to prevent test interference
        # These are attributes of the self.kursliste_mock, which is inside the accessor.
        self.kursliste_mock.year = TEST_TAX_YEAR # Ensure the mock Kursliste has the correct year
        self.kursliste_mock.exchangeRatesYearEnd = []
        self.kursliste_mock.exchangeRatesMonthly = []
        self.kursliste_mock.exchangeRates = []

        self.provider = KurslisteExchangeRateProvider(self.kursliste_manager_mock)

    def test_get_exchange_rate_for_chf(self):
        self.assertEqual(Decimal("1"), self.provider.get_exchange_rate("CHF", date(2023, 7, 15)))
        # Verify manager was not even called for CHF
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_not_called()

    def test_get_exchange_rate_year_end_found_value(self):
        test_year = 2023
        test_currency = "USD"
        expected_rate = Decimal("0.901")
        self.kursliste_mock.exchangeRatesYearEnd = [
            ExchangeRateYearEnd(currency=test_currency, year=test_year, value=expected_rate, valueMiddle=None)
        ]
        
        rate = self.provider.get_exchange_rate(test_currency, date(test_year, 12, 31))
        self.assertEqual(expected_rate, rate)
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_called_once_with(test_year)

    def test_get_exchange_rate_year_end_found_value_middle(self):
        test_year = 2023
        test_currency = "EUR"
        expected_rate_middle = Decimal("1.055")
        self.kursliste_mock.exchangeRatesYearEnd = [
            ExchangeRateYearEnd(currency=test_currency, year=test_year, value=None, valueMiddle=expected_rate_middle)
        ]
        
        rate = self.provider.get_exchange_rate(test_currency, date(test_year, 12, 31))
        self.assertEqual(expected_rate_middle, rate)
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_called_once_with(test_year)

    def test_get_exchange_rate_monthly_found(self):
        test_year = 2023
        test_month_str = "11"
        test_currency = "USD"
        expected_rate = Decimal("0.910")
        
        self.kursliste_mock.exchangeRatesMonthly = [
            ExchangeRateMonthly(currency=test_currency, year=test_year, month=test_month_str, value=expected_rate)
        ]
        # Ensure year-end is empty for this test or doesn't match
        self.kursliste_mock.exchangeRatesYearEnd = [] 
        
        rate = self.provider.get_exchange_rate(test_currency, date(test_year, 11, 15))
        self.assertEqual(expected_rate, rate)
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_called_once_with(test_year)

    def test_get_exchange_rate_daily_found(self):
        test_year = 2023
        test_date = date(test_year, 11, 15)
        test_currency = "USD"
        expected_rate = Decimal("0.915")

        self.kursliste_mock.exchangeRates = [
            ExchangeRate(currency=test_currency, date=test_date, value=expected_rate)
        ]
        # Ensure year-end and monthly are empty or don't match
        self.kursliste_mock.exchangeRatesYearEnd = []
        self.kursliste_mock.exchangeRatesMonthly = []

        rate = self.provider.get_exchange_rate(test_currency, test_date)
        self.assertEqual(expected_rate, rate)
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_called_once_with(test_year)

    def test_get_exchange_rate_priority_year_end_over_monthly(self):
        test_year = 2023
        test_currency = "USD"
        rate_year_end = Decimal("0.900")
        rate_monthly = Decimal("0.920")

        self.kursliste_mock.exchangeRatesYearEnd = [
            ExchangeRateYearEnd(currency=test_currency, year=test_year, value=rate_year_end, valueMiddle=None)
        ]
        self.kursliste_mock.exchangeRatesMonthly = [
            ExchangeRateMonthly(currency=test_currency, year=test_year, month="12", value=rate_monthly)
        ]
        
        rate = self.provider.get_exchange_rate(test_currency, date(test_year, 12, 31))
        self.assertEqual(rate_year_end, rate)
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_called_once_with(test_year)

    def test_get_exchange_rate_priority_monthly_over_daily(self):
        test_year = 2023
        test_month_str = "11"
        test_day = 15
        test_currency = "USD"
        rate_monthly = Decimal("0.920")
        rate_daily = Decimal("0.925")

        self.kursliste_mock.exchangeRatesMonthly = [
            ExchangeRateMonthly(currency=test_currency, year=test_year, month=test_month_str, value=rate_monthly)
        ]
        self.kursliste_mock.exchangeRates = [
            ExchangeRate(currency=test_currency, date=date(test_year, int(test_month_str), test_day), value=rate_daily)
        ]
        # Ensure year-end is empty
        self.kursliste_mock.exchangeRatesYearEnd = []

        rate = self.provider.get_exchange_rate(test_currency, date(test_year, int(test_month_str), test_day))
        self.assertEqual(rate_monthly, rate)
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_called_once_with(test_year)

    def test_get_exchange_rate_currency_not_found(self):
        test_year = 2023
        # All lists are empty by default from setUp for this mock
        
        with self.assertRaisesRegex(ValueError, "Exchange rate for XYZ on 2023-10-10 not found in Kursliste for tax year 2023."):
            self.provider.get_exchange_rate("XYZ", date(test_year, 10, 10))
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_called_once_with(test_year)

    def test_get_exchange_rate_kursliste_for_year_not_found(self):
        test_year = 2024 # A year for which the manager will return None (or an empty accessor)
        # Configure mock manager to return None when get_kurslisten_for_year is called with test_year
        self.kursliste_manager_mock.get_kurslisten_for_year.return_value = None 
        
        # The provider should raise ValueError if accessor is None.
        # The error message comes from KurslisteExchangeRateProvider itself.
        with self.assertRaisesRegex(ValueError, f"Exchange rate for USD on {test_year}-01-15 not found in any Kursliste source for tax year {test_year}."):
            self.provider.get_exchange_rate("USD", date(test_year, 1, 15))
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_called_once_with(test_year)

    def test_get_exchange_rate_uses_correct_kursliste_instance(self):
        # This test's premise changes slightly. The Accessor gets a list of Kursliste objects.
        # The Accessor's internal logic will iterate. We need to ensure the mock data is set up
        # on the Kursliste objects that the Accessor will receive.
        test_year = TEST_TAX_YEAR # Use the consistent tax year
        test_currency = "GBP"
        expected_rate = Decimal("1.15")

        kursliste_mock1 = MagicMock(spec=Kursliste)
        kursliste_mock1.year = test_year
        kursliste_mock1.exchangeRatesYearEnd = []
        kursliste_mock1.exchangeRatesMonthly = []
        kursliste_mock1.exchangeRates = [] 

        kursliste_mock2 = MagicMock(spec=Kursliste)
        kursliste_mock2.year = test_year
        kursliste_mock2.exchangeRatesYearEnd = []
        kursliste_mock2.exchangeRatesMonthly = []
        kursliste_mock2.exchangeRates = [
            ExchangeRate(currency=test_currency, date=date(test_year, 5, 20), value=expected_rate)
        ]
        
        # Configure the mock manager to return an accessor that contains both mocks
        mock_accessor_with_multiple_kl = KurslisteAccessor([kursliste_mock1, kursliste_mock2], tax_year=test_year)
        self.kursliste_manager_mock.get_kurslisten_for_year.return_value = mock_accessor_with_multiple_kl
        
        rate = self.provider.get_exchange_rate(test_currency, date(test_year, 5, 20))
        self.assertEqual(expected_rate, rate)
        self.kursliste_manager_mock.get_kurslisten_for_year.assert_called_once_with(test_year)

if __name__ == '__main__':
    unittest.main()
