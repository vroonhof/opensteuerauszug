from unittest.mock import patch, mock_open
from typing import List, Optional, Tuple, Any
from datetime import date
import csv
import pytest
import tempfile
import os
from decimal import Decimal
from io import StringIO
import contextlib

from opensteuerauszug.importers.schwab.fallback_position_extractor import FallbackPositionExtractor
from opensteuerauszug.model.position import Position, CashPosition, SecurityPosition
from opensteuerauszug.model.ech0196 import SecurityStock

@pytest.fixture
def managed_temp_csv_path(request):
    # request.param should be the content of the CSV
    content = request.param
    fd, path = tempfile.mkstemp(suffix=".csv", text=True)
    with os.fdopen(fd, "w", encoding='utf-8') as tmp:
        tmp.write(content)
    
    yield path  # Provide the path to the test
    
    os.remove(path) # Cleanup after the test

@patch("builtins.open", new_callable=mock_open, read_data="col1,col2\nval1,val2")
def test_read_file_content_success(mock_file):
    extractor = FallbackPositionExtractor("dummy_file.csv")
    content = extractor._read_file_content()
    assert content == "col1,col2\nval1,val2"
    mock_file.assert_called_once_with("dummy_file.csv", 'r', encoding='utf-8-sig')

@patch("builtins.open", side_effect=FileNotFoundError)
def test_read_file_content_file_not_found(mock_file):
    extractor = FallbackPositionExtractor("non_existent_file.csv")
    content = extractor._read_file_content()
    assert content is None

@patch("builtins.open", side_effect=IOError("Disk full"))
def test_read_file_content_io_error(mock_file):
    extractor = FallbackPositionExtractor("dummy_file.csv")
    content = extractor._read_file_content()
    assert content is None

def test_parse_csv_string_success():
    extractor = FallbackPositionExtractor("dummy.csv")
    csv_content = "Header1,Header2\nData1A,Data1B\nData2A,Data2B"
    expected_header = ["Header1", "Header2"]
    expected_data_rows = [["Data1A", "Data1B"], ["Data2A", "Data2B"]]
    
    parsed_data = extractor._parse_csv_string(csv_content)
    assert parsed_data is not None
    header, data_rows = parsed_data
    assert header == expected_header
    assert data_rows == expected_data_rows

def test_parse_csv_string_empty_content():
    extractor = FallbackPositionExtractor("dummy.csv")
    parsed_data = extractor._parse_csv_string("")
    assert parsed_data is None

def test_parse_csv_string_only_spaces():
    extractor = FallbackPositionExtractor("dummy.csv")
    parsed_data = extractor._parse_csv_string("   \n   ")
    assert parsed_data is None

def test_parse_csv_string_no_header():
    extractor = FallbackPositionExtractor("dummy.csv")
    # This case is handled by csv.reader raising StopIteration on next() if input is empty after splitlines
    # or if the first line is empty.
    # If the "CSV" is just one line of data without a clear header,
    # csv.reader will treat that line as the header.
    # If the file is truly empty or only newlines, next(reader) will fail.
    parsed_data = extractor._parse_csv_string("\n") # Effectively empty for csv.reader
    assert parsed_data is None

def test_parse_csv_string_header_only():
    extractor = FallbackPositionExtractor("dummy.csv")
    csv_content = "Header1,Header2"
    expected_header = ["Header1", "Header2"]
    # The current implementation considers header-only as valid for parsing,
    # but _process_csv_data would then get empty data_rows.
    # The print statement indicates it might be treated as "no positions".
    parsed_data = extractor._parse_csv_string(csv_content)
    assert parsed_data is not None
    header, data_rows = parsed_data
    assert header == expected_header
    assert data_rows == []

def test_parse_csv_string_malformed_csv():
    extractor = FallbackPositionExtractor("dummy.csv")
    # Example of malformed CSV that might cause csv.Error
    # This specific example might not trigger csv.Error with Python's default reader,
    # as it's quite lenient. A more complex scenario or a stricter dialect might be needed.
    # For now, we assume csv.Error can be raised.
    csv_content = 'Header1,Header2\n"Val1,"Val2' # Unclosed quote
    with patch('csv.reader', side_effect=csv.Error("Test CSV error")):
        parsed_data = extractor._parse_csv_string(csv_content)
        assert parsed_data is None

@patch.object(FallbackPositionExtractor, '_read_file_content')
@patch.object(FallbackPositionExtractor, '_parse_csv_string')
@patch.object(FallbackPositionExtractor, '_process_csv_data')
def test_extract_positions_successful_flow(mock_process, mock_parse, mock_read):
    extractor = FallbackPositionExtractor("dummy.csv")
    mock_read.return_value = "csv,content"
    mock_parse.return_value = (["header"], [["data"]])
    
    # Create dummy Position and SecurityStock for the mock return
    dummy_pos = SecurityPosition(depot="D1", symbol="S1")
    dummy_stock = SecurityStock(referenceDate=date(2023,1,1), mutation=False, quantity=Decimal(10), balanceCurrency="USD", quotationType="PIECE", name="Dummy")
    expected_result = [(dummy_pos, dummy_stock)]
    mock_process.return_value = expected_result

    result = extractor.extract_positions()

    mock_read.assert_called_once()
    mock_parse.assert_called_once_with("csv,content")
    mock_process.assert_called_once_with(["header"], [["data"]])
    assert result == expected_result

@patch.object(FallbackPositionExtractor, '_read_file_content', return_value=None)
@patch.object(FallbackPositionExtractor, '_parse_csv_string')
@patch.object(FallbackPositionExtractor, '_process_csv_data')
def test_extract_positions_read_fails(mock_process, mock_parse, mock_read):
    extractor = FallbackPositionExtractor("dummy.csv")
    result = extractor.extract_positions()
    mock_read.assert_called_once()
    mock_parse.assert_not_called()
    mock_process.assert_not_called()
    assert result is None

@patch.object(FallbackPositionExtractor, '_read_file_content')
@patch.object(FallbackPositionExtractor, '_parse_csv_string', return_value=None)
@patch.object(FallbackPositionExtractor, '_process_csv_data')
def test_extract_positions_parse_fails(mock_process, mock_parse, mock_read):
    extractor = FallbackPositionExtractor("dummy.csv")
    mock_read.return_value = "some,content" # Simulate successful read
    
    result = extractor.extract_positions()

    mock_read.assert_called_once()
    mock_parse.assert_called_once_with("some,content")
    mock_process.assert_not_called()
    assert result is None

# --- New comprehensive tests for FallbackPositionExtractor ---

def test_extract_positions_file_not_found():
    extractor = FallbackPositionExtractor("non_existent_file.csv")
    with contextlib.redirect_stdout(StringIO()): # Suppress print
        results = extractor.extract_positions()
    assert results is None

@pytest.mark.parametrize("managed_temp_csv_path", [""], indirect=True)
def test_extract_positions_empty_csv_file(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    with contextlib.redirect_stdout(StringIO()): # Suppress print
        results = extractor.extract_positions()
    assert results is None

@pytest.mark.parametrize("managed_temp_csv_path", ["Depot,Date,Symbol,Quantity\n"], indirect=True)
def test_extract_positions_csv_with_only_header(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    with contextlib.redirect_stdout(StringIO()): # Suppress print
        results = extractor.extract_positions()
    assert results is None # No data rows means no positions

@pytest.mark.parametrize("managed_temp_csv_path", ["Depot,Date,Quantity\nACC123,2023-01-01,100\n"], indirect=True)
def test_extract_positions_missing_required_header(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    log_capture = StringIO()
    with contextlib.redirect_stdout(log_capture):
        results = extractor.extract_positions()
    assert results is None
    assert "Missing required header(s)" in log_capture.getvalue()
    assert "Symbol" in log_capture.getvalue()

@pytest.mark.parametrize("managed_temp_csv_path", ["Depot,Date,Symbol,Quantity\nAWARDS,2023-01-15,AAPL,100.5\n"], indirect=True)
def test_extract_positions_valid_csv_awards_security(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    results = extractor.extract_positions()

    assert results is not None
    assert len(results) == 1

    pos, stock = results[0]
    assert isinstance(pos, SecurityPosition)
    assert pos.depot == "AWARDS"
    assert pos.symbol == "AAPL"
    assert pos.description is None

    assert isinstance(stock, SecurityStock)
    assert stock.referenceDate == date(2023, 1, 15)
    assert stock.quantity == Decimal("100.5")
    assert stock.mutation is False
    assert stock.balanceCurrency == "USD"
    assert stock.quotationType == "PIECE"
    assert stock.name == "Manual Security Position for AAPL from CSV"

@pytest.mark.parametrize("managed_temp_csv_path", ["Depot,Date,Symbol,Quantity\nSCHWABACC789,2023-03-10,CASH,5000.75\n"], indirect=True)
def test_extract_positions_valid_csv_numeric_depot_cash(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    results = extractor.extract_positions()

    assert results is not None
    assert len(results) == 1

    pos, stock = results[0]
    assert isinstance(pos, CashPosition)
    assert pos.depot == "789" # Last 3 digits
    assert pos.currentCy == "USD"
    assert pos.cash_account_id is None

    assert isinstance(stock, SecurityStock)
    assert stock.referenceDate == date(2023, 3, 10)
    assert stock.quantity == Decimal("5000.75")
    assert stock.mutation is False
    assert stock.balanceCurrency == "USD"
    assert stock.quotationType == "PIECE"
    assert stock.name == "Manual Cash Position from CSV"

@pytest.mark.parametrize("managed_temp_csv_path", ["Depot,Date,Symbol,Quantity\nXY,2023-03-10,MSFT,50\n"], indirect=True)
def test_extract_positions_valid_csv_depot_less_than_3_chars_not_awards(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    log_capture = StringIO()
    with contextlib.redirect_stdout(log_capture):
        results = extractor.extract_positions()
    
    assert f"Depot 'XY' in row 1 of {managed_temp_csv_path}" in log_capture.getvalue()
    assert "is not 'AWARDS' and does not end in 3 digits. Using raw value 'XY'" in log_capture.getvalue()

    assert results is not None
    assert len(results) == 1
    pos, _ = results[0]
    assert pos.depot == "XY"

@pytest.mark.parametrize("managed_temp_csv_path", ["Depot,Date,Symbol,Quantity\nMYACCOUNT,2023-03-10,GOOG,20\n"], indirect=True)
def test_extract_positions_valid_csv_depot_non_numeric_suffix_not_awards(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    log_capture = StringIO()
    with contextlib.redirect_stdout(log_capture):
        results = extractor.extract_positions()

    assert f"Depot 'MYACCOUNT' in row 1 of {managed_temp_csv_path}" in log_capture.getvalue()
    assert "is not 'AWARDS' and does not end in 3 digits. Using raw value 'MYACCOUNT'" in log_capture.getvalue()
    
    assert results is not None
    assert len(results) == 1
    pos, _ = results[0]
    assert pos.depot == "MYACCOUNT"

@pytest.mark.parametrize("managed_temp_csv_path", ["  dEpOt  , daTE,   SYMbol   ,   QuAnTiTy   \nAWARDS,2023-01-15,CSCO,75\n"], indirect=True)
def test_extract_positions_header_case_insensitivity_and_spacing(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    results = extractor.extract_positions()

    assert results is not None
    assert len(results) == 1
    pos, stock = results[0]
    assert isinstance(pos, SecurityPosition) # Narrow type
    assert pos.depot == "AWARDS"
    assert pos.symbol == "CSCO"
    assert stock.quantity == Decimal("75")

@pytest.mark.parametrize("managed_temp_csv_path", [(
            "Depot,Date,Symbol,Quantity\n"
            "AWARDS,2023-01-01,GOOD,10\n"
            "AWARDS,2023/02/02,BAD_DATE,20\n" # Invalid date format
            "AWARDS,invalid,BAD_DATE2,25\n"   # Invalid date format
            "AWARDS,2023-03-03,GOOD2,30\n"
        )], indirect=True)
def test_extract_positions_malformed_date_skips_row(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    log_capture = StringIO()
    with contextlib.redirect_stdout(log_capture):
        results = extractor.extract_positions()

    assert results is not None
    assert len(results) == 2
    pos0 = results[0][0]
    assert isinstance(pos0, SecurityPosition) # Narrow type
    pos1 = results[1][0]
    assert isinstance(pos1, SecurityPosition) # Narrow type
    assert pos0 == "GOOD"
    assert pos1 == "GOOD2"
    assert "Invalid date format '2023/02/02'" in log_capture.getvalue()
    assert "Invalid date format 'invalid'" in log_capture.getvalue()

@pytest.mark.parametrize("managed_temp_csv_path", [(
            "Depot,Date,Symbol,Quantity\n"
            "AWARDS,2023-01-01,GOOD,10\n"
            "AWARDS,2023-02-02,BAD_QTY,twenty\n" # Invalid quantity
            "AWARDS,2023-03-03,GOOD2,30\n"
        )], indirect=True)
def test_extract_positions_malformed_quantity_skips_row(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    log_capture = StringIO()
    with contextlib.redirect_stdout(log_capture):
        results = extractor.extract_positions()

    assert results is not None
    assert len(results) == 2
    pos0 = results[0][0]
    assert isinstance(pos0, SecurityPosition) # Narrow type
    assert pos0.symbol == "GOOD"
    pos1 = results[1][0]
    assert isinstance(pos1, SecurityPosition) # Narrow type
    assert pos1.symbol == "GOOD2"
    assert "Invalid quantity format 'twenty'" in log_capture.getvalue()

@pytest.mark.parametrize("managed_temp_csv_path", [(
            "Depot,Date,Symbol,Quantity\n"
            "AWARDS,2023-01-01,GOOD,10\n"
            "AWARDS,2023-02-02,TOO_FEW\n" # Too few columns
            "AWARDS,2023-03-03,GOOD2,30,EXTRA_COL\n" # Too many columns
            "AWARDS,2023-04-04,GOOD3,40\n"
        )], indirect=True)
def test_extract_positions_incorrect_column_count_skips_row(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    log_capture = StringIO()
    with contextlib.redirect_stdout(log_capture):
        results = extractor.extract_positions()

    assert results is not None
    assert len(results) == 2
    pos0 = results[0][0]
    assert isinstance(pos0, SecurityPosition) # Narrow type
    assert pos0.symbol == "GOOD"
    pos1 = results[1][0]
    assert isinstance(pos1, SecurityPosition) # Narrow type
    assert pos1.symbol == "GOOD3"
    assert f"Row 2 in {managed_temp_csv_path}" in log_capture.getvalue()
    assert "has incorrect number of columns" in log_capture.getvalue()
    assert f"Row 3 in {managed_temp_csv_path}" in log_capture.getvalue()

@pytest.mark.parametrize("managed_temp_csv_path", [(
            "Depot,Date,Symbol,Quantity\n"
            "AWARDS,2023-01-01,GOOD,10\n"
            "AWARDS,2023-02-02,,20\n" # Empty symbol
            "AWARDS,2023-03-03,GOOD2,30\n"
        )], indirect=True)
def test_extract_positions_empty_symbol_skips_row(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    log_capture = StringIO()
    with contextlib.redirect_stdout(log_capture):
        results = extractor.extract_positions()

    assert results is not None
    assert len(results) == 2
    pos0 = results[0][0]
    assert isinstance(pos0, SecurityPosition) # Narrow type
    assert pos0.symbol == "GOOD"
    pos1 = results[1][0]
    assert isinstance(pos1, SecurityPosition) # Narrow type
    assert pos1.symbol == "GOOD2"
    assert f"Empty symbol in row 2 of {managed_temp_csv_path}" in log_capture.getvalue()

@pytest.mark.parametrize("managed_temp_csv_path", [(
            "Depot,Date,Symbol,Quantity\n"
            "AWARDS,2023-01-01,AAPL,10\n"
            "ACC123,2023-01-15,CASH,1000.00\n"
            "AWARDS,2023-02-01,MSFT,25.5\n"
        )], indirect=True)
def test_extract_positions_multiple_valid_entries(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    results = extractor.extract_positions()

    assert results is not None
    assert len(results) == 3

    # Check first entry (AAPL)
    pos1, stock1 = results[0]
    assert isinstance(pos1, SecurityPosition)
    assert pos1.depot == "AWARDS"
    assert pos1.symbol == "AAPL"
    assert stock1.quantity == Decimal("10")
    assert stock1.referenceDate == date(2023,1,1)

    # Check second entry (CASH)
    pos2, stock2 = results[1]
    assert isinstance(pos2, CashPosition)
    assert pos2.depot == "123"
    assert stock2.quantity == Decimal("1000.00")
    assert stock2.referenceDate == date(2023,1,15)

    # Check third entry (MSFT)
    pos3, stock3 = results[2]
    assert isinstance(pos3, SecurityPosition)
    assert pos3.depot == "AWARDS"
    assert pos3.symbol == "MSFT"
    assert stock3.quantity == Decimal("25.5")
    assert stock3.referenceDate == date(2023,2,1)

@pytest.mark.parametrize("managed_temp_csv_path", [
    # UTF-8 BOM is \xef\xbb\xbf
    b'\xef\xbb\xbfDepot,Date,Symbol,Quantity\nAWARDS,2023-01-15,AAPL,100.5\n'.decode('utf-8') # Decode normally, extractor uses utf-8-sig
    ], indirect=True)
def test_extract_positions_utf8_bom_handling(managed_temp_csv_path):
    # Note: The managed_temp_csv_path fixture writes with 'utf-8'.
    # The FallbackPositionExtractor reads with 'utf-8-sig', which handles the BOM.
    # To test this properly, the BOM must be part of the string written to the file.
    # The decode('utf-8') above is to ensure the string itself contains the BOM if it was part of the bytes.
    # A better way to ensure BOM is to write bytes directly if the fixture allowed.
    # For this setup, we rely on the string param containing the BOM characters if needed.
    # The current parametrization writes the string as is. If the string starts with BOM char, it's written.

    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    results = extractor.extract_positions()

    assert results is not None
    assert len(results) == 1
    pos, stock = results[0]
    assert isinstance(pos, SecurityPosition) # Narrow type for Pylance and assert expectation
    assert pos.symbol == "AAPL"
    assert stock.quantity == Decimal("100.5")

@pytest.mark.parametrize("managed_temp_csv_path", [(
            "Depot,Date,Symbol,Quantity\n"
            "AWARDS,bad-date,SYM1,10\n"
            "AWARDS,2023-02-02,SYM2,bad-qty\n"
        )], indirect=True)
def test_extract_positions_all_rows_invalid(managed_temp_csv_path):
    extractor = FallbackPositionExtractor(managed_temp_csv_path)
    log_capture = StringIO()
    with contextlib.redirect_stdout(log_capture):
        results = extractor.extract_positions()
    
    assert results is None
    assert "Invalid date format 'bad-date'" in log_capture.getvalue()
    assert "Invalid quantity format 'bad-qty'" in log_capture.getvalue()
