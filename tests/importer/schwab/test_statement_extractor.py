import pytest
from opensteuerauszug.importers.schwab.statement_extractor import StatementExtractor
from opensteuerauszug.model.position import SecurityPosition, CashPosition
from opensteuerauszug.model.ech0196 import SecurityStock, CurrencyId

class DummyStatementExtractor(StatementExtractor):
    def __init__(self, text_content, pdf_author="SCHWAB PDF"):
        self.pdf_path = None
        self.text_content = text_content
        self.pdf_author = pdf_author
        self.extracted_data = None

    # Override to skip file reading
    def __init_file__(self, *args, **kwargs):
        pass

def test_is_statement_true():
    text = """
    Account Statement\nAccount Summary: AAPL\nSome more text
    """
    extractor = DummyStatementExtractor(text)
    assert extractor.is_statement() is True

def test_is_statement_false_unrelated_text():
    text = "This is not a Schwab statement."
    extractor = DummyStatementExtractor(text)
    assert extractor.is_statement() is False

def test_extract_data_minimal():
    text = (
        "Account Statement\n"
        "Account Summary: AAPL\n"
        "For Period: 01/01/2024 - 12/31/2024\n"
        "Closing Price on 12/31/2024 : $100.00\n"
        "Stock Summary: Opening Closing Closing Share Price Closing Value\n"
        "10 10 $100.00 $1000.00\n"
        "Cash Summary: $500.00 $600.00 $600.00\n"
    )
    extractor = DummyStatementExtractor(text)
    data = extractor.extract_data()
    assert data is not None
    assert data['symbol'] == 'AAPL'
    assert str(data['start_date']) == '2024-01-01'
    assert str(data['end_date']) == '2024-12-31'
    assert data['closing_shares'] == 10
    assert data['closing_price'] == 100
    assert data['closing_value'] == 1000
    assert data['closing_cash'] == 600

def test_extract_positions_format():
    text = (
        "Account Statement\n"
        "Account Summary: AAPL\n"
        "For Period: 01/01/2024 - 12/31/2024\n"
        "Closing Price on 12/31/2024 : $100.00\n"
        "Stock Summary: Opening Closing Closing Share Price Closing Value\n"
        "10 10 $100.00 $1000.00\n"
        "Cash Summary: $500.00 $600.00 $600.00\n"
    )
    extractor = DummyStatementExtractor(text)
    result = extractor.extract_positions()
    assert result is not None
    positions, open_date, close_date_plus1, depot = result
    assert depot == 'AWARDS'
    assert str(open_date) == '2024-01-01'
    assert str(close_date_plus1) == '2025-01-01'
    # Should have 4 positions: security open, security close, cash open, cash close
    assert len(positions) == 4
    # Security positions
    sec_pos, sec_stock_open = positions[0]
    sec_pos2, sec_stock_close = positions[1]
    assert isinstance(sec_pos, SecurityPosition)
    assert sec_pos.symbol == 'AAPL'
    assert sec_stock_open.referenceDate == open_date
    assert sec_stock_close.referenceDate == close_date_plus1
    assert sec_stock_open.quantity == 10
    assert sec_stock_close.quantity == 10
    assert sec_stock_open.balanceCurrency == 'USD'
    assert sec_stock_close.balanceCurrency == 'USD'
    # Cash positions
    cash_pos, cash_stock_open = positions[2]
    cash_pos2, cash_stock_close = positions[3]
    assert isinstance(cash_pos, CashPosition)
    assert cash_stock_open.referenceDate == open_date
    assert cash_stock_close.referenceDate == close_date_plus1
    assert cash_stock_open.quantity == 600
    assert cash_stock_close.quantity == 600
    assert cash_stock_open.balanceCurrency == 'USD'
    assert cash_stock_close.balanceCurrency == 'USD'
    assert cash_stock_open.balance == 600
    assert cash_stock_close.balance == 600

def test_next_business_day_skips_weekend():
    text = (
        "Account Statement\n"
        "Account Summary: AAPL\n"
        "For Period: 01/01/2024 - 12/27/2024\n"  # 2024-12-27 is a Friday
        "Closing Price on 12/27/2024 : $100.00\n"
        "Stock Summary: Opening Closing Closing Share Price Closing Value\n"
        "10 10 $100.00 $1000.00\n"
        "Cash Summary: $500.00 $600.00 $600.00\n"
    )
    extractor = DummyStatementExtractor(text)
    result = extractor.extract_positions()
    assert result is not None
    positions, open_date, close_date_plus1, depot = result
    # 2024-12-27 is Friday, next business day is 2024-12-30 (Monday)
    assert str(close_date_plus1) == '2024-12-30' 