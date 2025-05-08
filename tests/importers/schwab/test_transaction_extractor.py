import pytest
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Tuple, Any, Dict

from opensteuerauszug.importers.schwab.transaction_extractor import TransactionExtractor, KNOWN_ACTIONS
from opensteuerauszug.model.position import Position, SecurityPosition, CashPosition
from opensteuerauszug.model.ech0196 import SecurityStock, SecurityPayment, CurrencyId

# Helper to create a TransactionExtractor instance with a dummy filename
def create_extractor(filename_for_depot_test: str = "Individual_XXX123_Transactions_20240101-000000.json") -> TransactionExtractor:
    return TransactionExtractor(filename_for_depot_test)

# Helper to run extraction and perform common checks
def run_extraction_test(extractor: TransactionExtractor, data: dict, expected_count: int) -> Optional[List[Tuple[Position, List[SecurityStock], Optional[List[SecurityPayment]], str, Tuple[date, date]]]]:
    result = extractor._extract_transactions_from_dict(data)
    if expected_count == 0:
        assert result is None or len(result) == 0
        return result
    
    assert result is not None
    assert len(result) == expected_count
    return result

# Helper function to find a specific position type in the results
def find_position(results: List[Tuple[Position, List[SecurityStock], Optional[List[SecurityPayment]], str, Tuple[date, date]]], 
                  position_type: type, symbol: Optional[str] = None) -> Optional[Tuple[Position, List[SecurityStock], Optional[List[SecurityPayment]]]]:
    for pos, stocks, payments, _, _ in results:
        # Check specifically for CashPosition first if that's the target type
        if position_type == CashPosition and isinstance(pos, CashPosition):
            return (pos, stocks, payments)
        # Check for SecurityPosition if that's the target type
        elif position_type == SecurityPosition and isinstance(pos, SecurityPosition):
            # If looking for a specific symbol, check it
            if symbol is not None:
                if pos.symbol == symbol:
                    return (pos, stocks, payments)
            else: # If no specific symbol requested, return the first SecurityPosition found
                 return (pos, stocks, payments) 
    return None

class TestSchwabTransactionExtractor:

    def test_empty_data(self):
        extractor = create_extractor()
        assert extractor._extract_transactions_from_dict({}) is None

    def test_missing_dates(self):
        extractor = create_extractor()
        data = {"BrokerageTransactions": []} # Missing FromDate, ToDate
        assert extractor._extract_transactions_from_dict(data) is None

    def test_invalid_date_format(self):
        extractor = create_extractor()
        data = {"FromDate": "01-01-2024", "ToDate": "12/31/2024", "BrokerageTransactions": []}
        assert extractor._extract_transactions_from_dict(data) is None
        data = {"FromDate": "01/01/2024", "ToDate": "31/12/2024", "BrokerageTransactions": []}
        assert extractor._extract_transactions_from_dict(data) is None

    def test_date_range_extraction(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024",
            "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "06/15/2024", "Action": "Credit Interest", "Amount": "$1.23", "Description": "Interest"
            }]
        }
        expected_start_date = date(2024, 1, 1)
        expected_end_date = date(2024, 12, 31)
        
        processed_result = run_extraction_test(extractor, data, 1)
        assert processed_result is not None
        assert len(processed_result) == 1
        pos, stocks, payments, depot, date_range = processed_result[0]
        assert date_range == (expected_start_date, expected_end_date)
        assert isinstance(pos, CashPosition)
        assert stocks is not None and len(stocks) == 1
        assert payments is not None and len(payments) == 1

    def test_depot_brokerage_extraction_normal(self):
        extractor = create_extractor(filename_for_depot_test="Individual_XXX123_Transactions_20240101.json")
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{"Date": "01/10/2024", "Action": "Credit Interest", "Amount": "10.00"}]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        pos, stocks, payments, depot, _ = result[0]
        assert isinstance(pos, CashPosition)
        assert depot == "123"

    def test_depot_brokerage_extraction_short_numeric(self):
        extractor = create_extractor(filename_for_depot_test="Account_Y99_Transactions_20240101.json")
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{"Date": "01/10/2024", "Action": "Credit Interest", "Amount": "10.00"}]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        assert result[0][3] == "99" # Uses the full numeric part if less than 3 digits

    def test_depot_brokerage_extraction_alphanumeric_suffix(self):
        extractor = create_extractor(filename_for_depot_test="Trust_ABC789_Transactions_20240101.json")
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{"Date": "01/10/2024", "Action": "Credit Interest", "Amount": "10.00"}]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        assert result[0][3] == "789"

    def test_depot_brokerage_extraction_no_digits_fallback(self):
        # Test fallback when no digits are in the guessed account part
        extractor = create_extractor(filename_for_depot_test="MyCustomAccount_Transactions_20240101.json")
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{"Date": "01/10/2024", "Action": "Credit Interest", "Amount": "10.00"}]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        assert result[0][3] == "MyCustomAccount"

    def test_depot_awards(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "Transactions": [{
                "Date": "01/10/2024", "Action": "Deposit", "Symbol": "GOOG", 
                "Quantity": "10", "Description": "Vesting", 
                "TransactionDetails": [{
                    "Details": {"VestFairMarketValue": "$100.00"}
                }]
            }]
        }
        result = run_extraction_test(extractor, data, 2) # GOOG + Cash
        assert result is not None
        goog_pos_data = find_position(result, SecurityPosition, symbol="GOOG")
        cash_pos_data = find_position(result, CashPosition)
        assert goog_pos_data is not None
        assert cash_pos_data is not None
        goog_pos, goog_stocks, goog_payments = goog_pos_data
        cash_pos, cash_stocks, cash_payments = cash_pos_data

        assert goog_pos.depot == "AWARDS"
        assert cash_pos.depot == "AWARDS"
        assert not cash_stocks
        assert cash_payments is None

    def test_unknown_action(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{"Date": "01/10/2024", "Action": "UNKNOWN ACTION", "Amount": "10.00"}]
        }
        with pytest.raises(ValueError) as excinfo:
            extractor._extract_transactions_from_dict(data)
        assert "Unknown action 'UNKNOWN ACTION'" in str(excinfo.value)

    def test_no_transactions_key(self):
        extractor = create_extractor()
        data = {"FromDate": "01/01/2024", "ToDate": "12/31/2024"} # No transaction list
        assert extractor._extract_transactions_from_dict(data) is None

    def test_empty_transaction_list_brokerage(self):
        extractor = create_extractor()
        data = {"FromDate": "01/01/2024", "ToDate": "12/31/2024", "BrokerageTransactions": []}
        assert extractor._extract_transactions_from_dict(data) is None # Returns None because processed_transactions is empty

    def test_empty_transaction_list_awards(self):
        extractor = create_extractor()
        data = {"FromDate": "01/01/2024", "ToDate": "12/31/2024", "Transactions": []}
        assert extractor._extract_transactions_from_dict(data) is None

    # --- Action-specific tests ---

    def test_action_buy(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "03/15/2024", "Action": "Buy", "Symbol": "MSFT", 
                "Description": "MICROSOFT CORP", "Quantity": "10.5", "Price": "300.00", 
                "Amount": "$3,150.00" # This amount might or might not include fees in real data
            }]
        }
        result = run_extraction_test(extractor, data, 2) # Expect MSFT + Cash
        assert result is not None
        msft_data = find_position(result, SecurityPosition, "MSFT")
        cash_data = find_position(result, CashPosition)
        assert msft_data is not None
        assert cash_data is not None
        
        pos, stocks, payments = msft_data
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "MSFT"
        assert pos.depot == "123"
        assert payments is None
        assert len(stocks) == 1
        stock = stocks[0]
        assert stock.referenceDate == date(2024, 3, 15)
        assert stock.mutation is True
        assert stock.quotationType == "PIECE"
        assert stock.quantity == Decimal("10.5")
        assert stock.unitPrice == Decimal("300.00")
        assert stock.balance == Decimal("3150.00")
        assert stock.name is not None
        assert "Buy: MICROSOFT CORP" in stock.name

        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is None
        assert cash_stocks is not None
        assert len(cash_stocks) == 1
        cash_stock_entry = cash_stocks[0]
        assert cash_stock_entry.referenceDate == date(2024, 3, 15)
        assert cash_stock_entry.mutation is True
        assert cash_stock_entry.quantity == Decimal("-3150.00")
        assert cash_stock_entry.balance == Decimal("-3150.00")
        assert cash_stock_entry.name == "Cash out for Buy MSFT"

    def test_action_sale_negative_qty(self, capsys):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "04/20/2024", "Action": "Sale", "Symbol": "AAPL", 
                "Description": "APPLE INC", "Quantity": "-5", "Price": "170.00", 
                "Amount": "$850.00" 
            }]
        }
        result = run_extraction_test(extractor, data, 2) # Expect AAPL + Cash
        assert result is not None
        aapl_data = find_position(result, SecurityPosition, "AAPL")
        cash_data = find_position(result, CashPosition)
        assert aapl_data is not None
        assert cash_data is not None

        pos, stocks, payments = aapl_data
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "AAPL"
        assert payments is None
        assert len(stocks) == 1
        stock = stocks[0]
        assert stock.mutation is True
        assert stock.quantity == Decimal("-5")
        assert stock.unitPrice == Decimal("170.00")
        assert stock.balance == Decimal("850.00") # Proceeds
        assert stock.name is not None
        assert "Sale: APPLE INC" in stock.name
        
        # Check that the warning was printed
        captured = capsys.readouterr()
        assert "Warning: Received negative quantity (-5) for 'Sale' action for symbol AAPL." in captured.out

        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is None
        assert cash_stocks is not None
        assert len(cash_stocks) == 1
        cash_stock_entry = cash_stocks[0]
        assert cash_stock_entry.referenceDate == date(2024, 4, 20)
        assert cash_stock_entry.mutation is True
        assert cash_stock_entry.quantity == Decimal("850.00")
        assert cash_stock_entry.balance == Decimal("850.00")
        assert cash_stock_entry.name == "Cash in for Sale AAPL"

    def test_action_sale_positive_qty(self): # If Schwab data sometimes uses positive Qty for sale
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "04/21/2024", "Action": "Sale", "Symbol": "NVDA", 
                "Description": "NVIDIA CORP", "Quantity": "2", "Price": "900.00", 
                "Amount": "$1,800.00" 
            }]
        }
        result = run_extraction_test(extractor, data, 2) # Expect NVDA + Cash
        assert result is not None
        nvda_data = find_position(result, SecurityPosition, "NVDA")
        cash_data = find_position(result, CashPosition)
        assert nvda_data is not None
        assert cash_data is not None

        pos, stocks, payments = nvda_data
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "NVDA"
        assert payments is None
        assert len(stocks) == 1
        stock = stocks[0]
        assert stock.mutation is True
        assert stock.quantity == Decimal("-2") # Should be converted to negative
        assert stock.unitPrice == Decimal("900.00")
        assert stock.balance == Decimal("1800.00")
        assert stock.name is not None
        assert "Sale: NVIDIA CORP" in stock.name

        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is None
        assert cash_stocks is not None
        assert len(cash_stocks) == 1
        cash_stock_entry = cash_stocks[0]
        assert cash_stock_entry.referenceDate == date(2024, 4, 21)
        assert cash_stock_entry.mutation is True
        assert cash_stock_entry.quantity == Decimal("1800.00")
        assert cash_stock_entry.balance == Decimal("1800.00")
        assert cash_stock_entry.name == "Cash in for Sale NVDA"

    def test_action_credit_interest(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "06/30/2024", "Action": "Credit Interest", 
                "Description": "SCHWAB BANK INTEREST", "Amount": "$12.34"
            }]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        cash_data = find_position(result, CashPosition)
        assert cash_data is not None

        pos, stocks, payments = cash_data
        assert isinstance(pos, CashPosition)
        
        # Check payment
        assert payments is not None
        assert len(payments) == 1
        payment = payments[0]
        assert payment.paymentDate == date(2024, 6, 30)
        assert payment.amount == Decimal("12.34")
        assert payment.grossRevenueB == Decimal("12.34")
        assert payment.name is not None
        assert "Credit Interest: SCHWAB BANK INTEREST" in payment.name
        
        # Check stock mutation
        assert stocks is not None
        assert len(stocks) == 1
        stock = stocks[0]
        assert stock.referenceDate == date(2024, 6, 30)
        assert stock.mutation is True
        assert stock.quantity == Decimal("12.34")
        assert stock.balance == Decimal("12.34")
        assert stock.name == "Cash in for Credit Interest"

    def test_action_dividend(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "09/15/2024", "Action": "Dividend", "Symbol": "JNJ",
                "Description": "JOHNSON & JOHNSON DIVIDEND", "Quantity": "100", # Shares that received dividend
                "Amount": "$150.75" 
            }]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        jnj_data = find_position(result, SecurityPosition, "JNJ")
        cash_data = find_position(result, CashPosition) # Should not exist or be empty
        assert jnj_data is not None
        assert cash_data is None # No separate cash position generated

        pos, stocks, payments = jnj_data
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "JNJ"
        assert not stocks
        assert payments is not None
        assert len(payments) == 1 # Only the dividend payment
        payment = payments[0]
        assert payment.paymentDate == date(2024, 9, 15)
        assert payment.grossRevenueB == Decimal("150.75")
        assert payment.name is not None
        assert "Dividend: JOHNSON & JOHNSON DIVIDEND" in payment.name

    def test_action_reinvest_dividend(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "07/01/2024", "Action": "Reinvest Dividend", "Symbol": "SPY",
                "Description": "SPDR S&P 500 ETF TRUST DIV REINV", 
                "Quantity": "1.2345", "Price": "450.10", # Price of shares bought
                "Amount": "$555.65" # Total dividend amount reinvested
            }]
        }
        result = run_extraction_test(extractor, data, 2) # Expect SPY + Cash
        assert result is not None
        spy_data = find_position(result, SecurityPosition, "SPY")
        cash_data = find_position(result, CashPosition)
        assert spy_data is not None
        assert cash_data is not None

        pos, stocks, payments = spy_data
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "SPY"
        assert payments is not None
        assert len(payments) == 1 # The dividend payment
        payment = payments[0]
        assert payment.grossRevenueB == Decimal("555.65")
        assert payment.name is not None
        assert "Reinvest Dividend (Payment)" in payment.name

        assert stocks is not None
        assert len(stocks) == 1 # The acquisition stock
        stock = stocks[0]
        assert stock.mutation is True
        assert stock.quantity == Decimal("1.2345")
        assert stock.unitPrice == Decimal("450.10") 
        assert stock.balance == Decimal("555.65") 
        assert stock.name is not None
        assert "Reinvest Dividend (Acquisition)" in stock.name
        
        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is None
        assert cash_stocks is not None
        assert len(cash_stocks) == 1 # Only the balancing cash out for acquisition
        cash_payment = cash_payments[0]
        assert cash_payment.paymentDate == date(2024, 7, 1)
        assert cash_payment.amount == Decimal("-555.65") # Cash outflow for acquisition
        # Note: Name check depends on brittle logic, let's be flexible
        assert cash_payment.name is not None and "Cash movement for Reinvest Dividend (Acquisition) SPY" in cash_payment.name 

    def test_action_stock_split(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "08/01/2024", "Action": "Stock Split", "Symbol": "AMZN",
                "Description": "AMAZON.COM INC 20 FOR 1 FORWARD STOCK SPLIT", 
                "Quantity": "190" 
            }]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        pos, stocks, payments, depot, _ = result[0]
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "AMZN"
        assert payments is None
        assert len(stocks) == 1
        stock = stocks[0]
        assert stock.referenceDate == date(2024, 8, 1)
        assert stock.mutation is True
        assert stock.quantity == Decimal("190")
        assert stock.unitPrice is None
        assert stock.balance is None
        assert stock.name is not None
        assert "Stock Split: AMAZON.COM INC 20 FOR 1 FORWARD STOCK SPLIT" in stock.name

    def test_action_deposit_awards(self):
        extractor = create_extractor() 
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "Transactions": [{ 
                "Date": "03/06/2024", "Action": "Deposit", "Symbol": "GOOGL",
                "Quantity": "25.0", "Description": "RS (Restricted Stock)",
                "TransactionDetails": [{
                    "Details": {
                        "AwardDate": "01/15/2023", "AwardId": "AWD123",
                        "VestDate": "03/06/2024", "VestFairMarketValue": "$130.50"
                    }
                }]
            }]
        }
        result = run_extraction_test(extractor, data, 2) # GOOGL + Cash
        assert result is not None
        googl_data = find_position(result, SecurityPosition, "GOOGL")
        cash_data = find_position(result, CashPosition)
        assert googl_data is not None
        assert cash_data is not None

        pos, stocks, payments = googl_data
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "GOOGL"
        assert pos.depot == "AWARDS"
        assert payments is None
        assert len(stocks) == 1
        stock = stocks[0]
        assert stock.referenceDate == date(2024, 3, 6)
        assert stock.mutation is True
        assert stock.quantity == Decimal("25.0")
        assert stock.unitPrice == Decimal("130.50")
        assert stock.balance == Decimal("3262.50") 
        assert stock.name is not None
        assert "Deposit: RS (Restricted Stock) (Award ID: AWD123, Award Date: 01/15/2023, Vest Date: 03/06/2024, FMV: $130.50)" in stock.name

        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_pos.depot == "AWARDS"
        assert not cash_stocks
        assert cash_payments is not None
        assert len(cash_payments) == 1
        cash_payment = cash_payments[0]
        assert cash_payment.amount == Decimal("-3262.50") # Cash out corresponding to FMV
        assert cash_payment.name == "Cash movement for Deposit GOOGL"

    def test_action_tax_withholding(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "09/15/2024", "Action": "Tax Withholding", "Symbol": "JNJ", 
                "Description": "NONRES TAX WITHHELD", 
                "Amount": "$-22.50" 
            }]
        }
        result = run_extraction_test(extractor, data, 2) # JNJ + Cash
        assert result is not None
        jnj_data = find_position(result, SecurityPosition, "JNJ")
        cash_data = find_position(result, CashPosition)
        assert jnj_data is not None
        assert cash_data is not None
        
        pos, stocks, payments = jnj_data
        assert isinstance(pos, SecurityPosition) 
        assert pos.symbol == "JNJ"
        assert not stocks
        assert payments is not None
        assert len(payments) == 1 # The tax payment itself
        payment = payments[0]
        assert payment.amount == Decimal("-22.50")
        assert payment.nonRecoverableTax == Decimal("22.50")
        assert payment.grossRevenueB is None
        assert payment.name is not None
        assert "Tax Withholding: NONRES TAX WITHHELD" in payment.name

        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is None
        assert cash_stocks is not None
        assert len(cash_stocks) == 1
        cash_stock_entry = cash_stocks[0]
        assert cash_stock_entry.referenceDate == date(2024, 9, 15)
        assert cash_stock_entry.quantity == Decimal("-22.50")
        assert cash_stock_entry.balance == Decimal("-22.50")
        assert cash_stock_entry.name == "Cash flow for Tax Withholding JNJ"

    def test_action_nra_tax_adj_positive(self): 
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "10/01/2024", "Action": "NRA Tax Adj", "Symbol": "MSFT",
                "Description": "TAX ADJUSTMENT RECEIVED", 
                "Amount": "$5.00" 
            }]
        }
        result = run_extraction_test(extractor, data, 2) # MSFT + Cash
        assert result is not None
        msft_data = find_position(result, SecurityPosition, "MSFT")
        cash_data = find_position(result, CashPosition)
        assert msft_data is not None
        assert cash_data is not None

        pos, stocks, payments = msft_data
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "MSFT"
        assert not stocks
        assert payments is not None
        assert len(payments) == 1
        payment = payments[0]
        assert payment.amount == Decimal("5.00")
        assert payment.grossRevenueB == Decimal("5.00") 
        assert payment.name is not None
        assert "NRA Tax Adj: TAX ADJUSTMENT RECEIVED" in payment.name
        
        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is None
        assert cash_stocks is not None
        assert len(cash_stocks) == 1
        cash_stock_entry = cash_stocks[0]
        assert cash_stock_entry.referenceDate == date(2024, 10, 1)
        assert cash_stock_entry.quantity == Decimal("5.00")
        assert cash_stock_entry.balance == Decimal("5.00")
        assert cash_stock_entry.name == "Cash flow for NRA Tax Adj MSFT"

    def test_action_cash_in_lieu(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "08/01/2024", "Action": "Cash In Lieu", "Symbol": "AMZN",
                "Description": "CASH IN LIEU OF FRACTIONAL SHARES", 
                "Amount": "$50.25" 
            }]
        }
        result = run_extraction_test(extractor, data, 2) # AMZN + Cash
        assert result is not None
        amzn_data = find_position(result, SecurityPosition, "AMZN")
        cash_data = find_position(result, CashPosition)
        assert amzn_data is not None
        assert cash_data is not None
        
        pos, stocks, payments = amzn_data
        assert isinstance(pos, SecurityPosition) 
        assert pos.symbol == "AMZN"
        assert not stocks 
        assert payments is not None
        assert len(payments) == 1
        payment = payments[0]
        assert payment.amount == Decimal("50.25")
        assert payment.grossRevenueB == Decimal("50.25")
        assert payment.name is not None
        assert "Cash In Lieu: CASH IN LIEU OF FRACTIONAL SHARES" in payment.name

        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is None
        assert cash_stocks is not None
        assert len(cash_stocks) == 1
        cash_stock_entry = cash_stocks[0]
        assert cash_stock_entry.referenceDate == date(2024, 8, 1)
        assert cash_stock_entry.quantity == Decimal("50.25")
        assert cash_stock_entry.balance == Decimal("50.25")
        assert cash_stock_entry.name == "Cash in for Cash In Lieu AMZN"

    def test_action_journal_security(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "11/05/2024", "Action": "Journal", "Symbol": "GOOG",
                "Description": "JOURNALED SHARES IN", "Quantity": "10"
            }]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        pos, stocks, payments, depot, _ = result[0]
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "GOOG"
        assert payments is None
        assert len(stocks) == 1
        stock = stocks[0]
        assert stock.referenceDate == date(2024, 11, 5)
        assert stock.mutation is True
        assert stock.quantity == Decimal("10")
        assert stock.name is not None
        assert stock.name == "Journal (Shares): JOURNALED SHARES IN"

    def test_action_journal_cash(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "11/06/2024", "Action": "Journal", 
                "Description": "INTERNAL TRANSFER OF FUNDS", "Amount": "$-500.00"
            }]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        pos, stocks, payments, depot, _ = result[0]
        assert isinstance(pos, CashPosition)
        assert not stocks
        assert payments is not None
        assert len(payments) == 1
        payment = payments[0]
        assert payment.paymentDate == date(2024, 11, 6)
        assert payment.amount == Decimal("-500.00")
        assert payment.name is not None
        assert payment.name == "Journal (Cash): INTERNAL TRANSFER OF FUNDS"
        assert payment.grossRevenueA is None
        assert payment.grossRevenueB is None

    def test_action_transfer_security_out(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "12/01/2024", "Action": "Transfer", "Symbol": "TSLA",
                "Description": "TRANSFER OF ASSETS TO OTHER ACCOUNT", 
                "Quantity": "-5.0", "Price": "200.00", "Amount": "$1000.00" 
            }]
        }
        result = run_extraction_test(extractor, data, 2) # TSLA + Cash
        assert result is not None
        tsla_data = find_position(result, SecurityPosition, "TSLA")
        cash_data = find_position(result, CashPosition)
        assert tsla_data is not None
        assert cash_data is not None

        pos, stocks, payments = tsla_data
        assert isinstance(pos, SecurityPosition)
        assert payments is None
        assert len(stocks) == 1
        stock = stocks[0]
        assert stock.quantity == Decimal("-5.0")
        assert stock.balance == Decimal("1000.00") 
        assert stock.name is not None
        assert "Transfer (Shares): TRANSFER OF ASSETS TO OTHER ACCOUNT" in stock.name

        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is None
        assert cash_stocks is not None
        assert len(cash_stocks) == 1
        cash_stock_entry = cash_stocks[0]
        assert cash_stock_entry.referenceDate == date(2024, 12, 1)
        assert cash_stock_entry.quantity == Decimal("1000.00")
        assert cash_stock_entry.balance == Decimal("1000.00")
        assert cash_stock_entry.name == "Cash flow for Transfer TSLA"

    def test_action_transfer_cash_in(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [{
                "Date": "12/02/2024", "Action": "Transfer",
                "Description": "FUNDS RECEIVED VIA WIRE", "Amount": "$5000.00"
            }]
        }
        result = run_extraction_test(extractor, data, 1)
        assert result is not None
        cash_data = find_position(result, CashPosition)
        assert cash_data is not None
        pos, stocks, payments = cash_data
        assert isinstance(pos, CashPosition)
        assert payments is None
        assert stocks is not None
        assert len(stocks) == 1
        stock = stocks[0]
        assert stock.quantity == Decimal("5000.00")
        assert stock.name == "Cash Transfer: FUNDS RECEIVED VIA WIRE"

    def test_multiple_transactions_same_symbol(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [
                {"Date": "03/15/2024", "Action": "Buy", "Symbol": "MSFT", "Quantity": "10", "Price": "300", "Amount": "$3000"},
                {"Date": "09/15/2024", "Action": "Dividend", "Symbol": "MSFT", "Amount": "$50"},
                {"Date": "10/01/2024", "Action": "Sale", "Symbol": "MSFT", "Quantity": "-5", "Price": "320", "Amount": "$1600"}
            ]
        }
        result = run_extraction_test(extractor, data, 2) # MSFT + Cash
        assert result is not None
        msft_data = find_position(result, SecurityPosition, "MSFT")
        cash_data = find_position(result, CashPosition)
        assert msft_data is not None
        assert cash_data is not None
        
        pos, stocks, payments = msft_data
        assert isinstance(pos, SecurityPosition)
        assert pos.symbol == "MSFT"
        assert len(stocks) == 2 
        assert payments is not None
        assert len(payments) == 1 

        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is None
        assert cash_stocks is not None
        assert len(cash_stocks) == 2 
        cash_stock_qtys = sorted([s.quantity for s in cash_stocks])
        assert cash_stock_qtys == [Decimal("-3000.00"), Decimal("1600.00")]

    def test_multiple_positions_cash_and_security_with_synthesis(self):
        extractor = create_extractor()
        data = {
            "FromDate": "01/01/2024", "ToDate": "12/31/2024",
            "BrokerageTransactions": [
                {"Date": "03/15/2024", "Action": "Buy", "Symbol": "MSFT", "Quantity": "10", "Price": "300", "Amount": "$3000"},
                {"Date": "06/30/2024", "Action": "Credit Interest", "Amount": "12.34"}
            ]
        }
        result = run_extraction_test(extractor, data, 2) 
        assert result is not None
        
        msft_data = find_position(result, SecurityPosition, "MSFT")
        cash_data = find_position(result, CashPosition)
        assert msft_data is not None
        assert cash_data is not None

        msft_pos, msft_stocks, msft_payments = msft_data
        assert len(msft_stocks) == 1 # The buy
        assert msft_payments is None

        cash_pos, cash_stocks, cash_payments = cash_data
        assert isinstance(cash_pos, CashPosition)
        assert cash_payments is not None
        assert len(cash_payments) == 1
        assert cash_payments[0].grossRevenueB == Decimal("12.34")
        
        assert cash_stocks is not None
        assert len(cash_stocks) == 2 
        cash_stock_qtys = sorted([s.quantity for s in cash_stocks])
        assert cash_stock_qtys == [Decimal("-3000.00"), Decimal("12.34")] 