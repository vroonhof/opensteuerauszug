from typing import List, Optional, Tuple
from datetime import date, datetime # Added datetime
import csv # Added for CSV parsing
from decimal import Decimal, InvalidOperation # Added for Decimal
from opensteuerauszug.model.position import Position
from opensteuerauszug.model.ech0196 import SecurityStock, QuotationType, CurrencyId

class FallbackPositionExtractor:
    """
    Fallback extractor for Schwab CSV files if the primary PositionExtractor fails.
    This is a stub implementation and will always return None.
    """
    def __init__(self, filename: str):
        self.filename = filename

    def _read_file_content(self) -> Optional[str]:
        """Reads the content of the file."""
        try:
            with open(self.filename, 'r', encoding='utf-8-sig') as f: # utf-8-sig to handle potential BOM
                return f.read()
        except FileNotFoundError:
            print(f"FallbackPositionExtractor: File not found: {self.filename}")
            return None
        except IOError as e:
            print(f"FallbackPositionExtractor: Error reading file {self.filename}: {e}")
            return None

    def _parse_csv_string(self, file_content: str) -> Optional[Tuple[List[str], List[List[str]]]]:
        """Parses the CSV string, expecting a header row."""
        if not file_content.strip():
            print(f"FallbackPositionExtractor: File content is empty for {self.filename}")
            return None
        try:
            reader = csv.reader(file_content.splitlines())
            header = next(reader)
            data_rows = list(reader)
            if not data_rows: # Check if there are any data rows after the header
                print(f"FallbackPositionExtractor: CSV file {self.filename} has a header but no data rows.")
                # Depending on requirements, you might still want to return (header, [])
                # For now, let's consider it a case where no positions can be extracted.
                # If processing an empty data set is valid, this could return (header, [])
            return header, data_rows
        except StopIteration: # next(reader) failed, meaning the CSV was empty or had no header
            print(f"FallbackPositionExtractor: CSV file {self.filename} is empty or has no header row.")
            return None
        except csv.Error as e:
            print(f"FallbackPositionExtractor: Error parsing CSV data from {self.filename}: {e}")
            return None

    def _process_csv_data(self, header: List[str], data_rows: List[List[str]]) -> Optional[List[Tuple[Position, SecurityStock]]]:
        """
        Processes the parsed CSV header and data rows.
        Expected header (case-insensitive): [Depot, Date, Symbol, Quantity].
        """
        expected_headers_map = {
            "depot": "Depot",
            "date": "Date",
            "symbol": "Symbol",
            "quantity": "Quantity"
        }
        header_lower_to_original = {h.lower().strip(): h for h in header}
        
        col_indices = {}
        missing_headers = []
        for key, expected_name in expected_headers_map.items():
            if key not in header_lower_to_original:
                missing_headers.append(expected_name)
            else:
                col_indices[key] = header.index(header_lower_to_original[key])

        if missing_headers:
            print(f"FallbackPositionExtractor: Missing required header(s) in {self.filename}. Expected: {list(expected_headers_map.values())}. Missing: {missing_headers}. Found headers: {header}")
            return None

        results: List[Tuple[Position, SecurityStock]] = []

        for i, row in enumerate(data_rows):
            if len(row) != len(header):
                print(f"FallbackPositionExtractor: Row {i+1} in {self.filename} has incorrect number of columns. Expected {len(header)}, got {len(row)}. Skipping.")
                continue

            try:
                raw_depot = row[col_indices["depot"]].strip()
                date_str = row[col_indices["date"]].strip()
                symbol_str = row[col_indices["symbol"]].strip().upper()
                quantity_str = row[col_indices["quantity"]].strip()

                if not symbol_str:
                    print(f"FallbackPositionExtractor: Empty symbol in row {i+1} of {self.filename}. Skipping row.")
                    continue

                processed_depot: str
                if raw_depot.upper() == "AWARDS":
                    processed_depot = "AWARDS"
                else:
                    if len(raw_depot) >= 3 and raw_depot[-3:].isdigit():
                        processed_depot = raw_depot[-3:]
                    else:
                        print(f"FallbackPositionExtractor: Depot '{raw_depot}' in row {i+1} of {self.filename} is not 'AWARDS' and does not end in 3 digits. Using raw value '{raw_depot}'.")
                        processed_depot = raw_depot
                
                try:
                    entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    print(f"FallbackPositionExtractor: Invalid date format '{date_str}' in row {i+1} of {self.filename}. Expected YYYY-MM-DD. Skipping row.")
                    continue

                try:
                    quantity_val = Decimal(quantity_str)
                except InvalidOperation:
                    print(f"FallbackPositionExtractor: Invalid quantity format '{quantity_str}' in row {i+1} of {self.filename}. Skipping row.")
                    continue

                pos: Position
                stock: SecurityStock
                # Default currency for SecurityStock.balanceCurrency and CashPosition.currentCy
                # This CSV format does not specify currency, so defaulting to USD.
                default_currency = "USD"

                if symbol_str == "CASH":
                    from opensteuerauszug.model.position import CashPosition # Local import
                    pos = CashPosition(depot=processed_depot, currentCy=default_currency, cash_account_id=None)
                    stock_name = "Manual Cash Position from CSV"
                else:
                    from opensteuerauszug.model.position import SecurityPosition # Local import
                    pos = SecurityPosition(depot=processed_depot, symbol=symbol_str, description=None)
                    stock_name = f"Manual Security Position for {symbol_str} from CSV"
                
                stock = SecurityStock(
                    referenceDate=entry_date, mutation=False, quantity=quantity_val,
                    balanceCurrency=default_currency, quotationType="PIECE", name=stock_name
                )
                results.append((pos, stock))
            except Exception as e:
                print(f"FallbackPositionExtractor: Unexpected error processing row {i+1} in {self.filename}: {e}. Skipping row.")
                continue
        
        return results if results else None

    def extract_positions(self) -> Optional[List[Tuple[Position, SecurityStock]]]:
        """
        Reads, parses, and processes a CSV file to extract positions.
        """
        file_content = self._read_file_content()
        if file_content is None:
            return None

        parsed_data = self._parse_csv_string(file_content)
        if parsed_data is None:
            return None

        header, data_rows = parsed_data
        return self._process_csv_data(header, data_rows)