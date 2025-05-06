import os
import tempfile
import pytest
from opensteuerauszug.importers.schwab.position_extractor import PositionExtractor
from opensteuerauszug.model.position import SecurityPosition
from opensteuerauszug.model.ech0196 import SecurityStock, CurrencyId

SAMPLE_CSV = (
    '"Positions for account Individual ...178 as of 12:33 PM ET, 2025/05/04","","","","","","","","","","","","","","","",""\n'
    '"","","","","","","","","","","","","","","","",""\n'
    '"Symbol","Description","Qty (Quantity)","Price","Price Chng $ (Price Change $)","Price Chng % (Price Change %)","Mkt Val (Market Value)","Day Chng $ (Day Change $)","Day Chng % (Day Change %)","Cost Basis","Gain $ (Gain/Loss $)","Gain % (Gain/Loss %)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Security Type"\n'
    'AAPL,"Apple Inc.",10,150.00,1.00,0.67,1500.00,10.00,0.67,1000.00,500.00,50.00,,,Yes,10.0,Stock\n'
    'GOOG,"Alphabet Inc.",5,2800.00,10.00,0.36,14000.00,50.00,0.36,12000.00,2000.00,16.67,,,No,90.0,Stock\n'
)

BAD_CSV = 'Not a Schwab positions file\nSymbol,Description\nAAPL,Apple Inc.'

def test_extract_positions_valid():
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as tmp:
        tmp.write(SAMPLE_CSV)
        tmp.flush()
        extractor = PositionExtractor(tmp.name)
        result = extractor.extract_positions()
    os.unlink(tmp.name)
    assert result is not None
    positions, statement_date, depot = result
    assert len(positions) == 2
    (pos1, stock1), (pos2, stock2) = positions
    assert depot == '178'
    assert pos1.depot == '178'
    assert pos2.depot == '178'
    assert isinstance(pos1, SecurityPosition)
    assert isinstance(pos2, SecurityPosition)
    assert pos1.symbol == 'AAPL'
    assert pos2.symbol == 'GOOG'
    assert str(statement_date) == '2025-05-05'
    assert stock1.referenceDate == statement_date
    assert stock2.referenceDate == statement_date
    assert stock1.quotationType == 'PIECE'
    assert stock2.quotationType == 'PIECE'
    assert stock1.quantity == 10
    assert stock2.quantity == 5
    assert stock1.balanceCurrency == CurrencyId('USD')
    assert stock2.balanceCurrency == CurrencyId('USD')

def test_extract_positions_invalid():
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as tmp:
        tmp.write(BAD_CSV)
        tmp.flush()
        extractor = PositionExtractor(tmp.name)
        result = extractor.extract_positions()
    os.unlink(tmp.name)
    assert result is None 