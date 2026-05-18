import csv
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from opensteuerauszug.model.ech0196 import SecurityStock
from opensteuerauszug.model.position import CashPosition, Position, SecurityPosition

logger = logging.getLogger(__name__)

# Accepts typical ticker shapes like GOOG, BRK.B, BF-B. Pure digits are handled
# separately and indicate a brokerage account suffix instead.
_AWARDS_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,7}$")


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
            with open(
                self.filename, "r", encoding="utf-8-sig"
            ) as f:  # utf-8-sig to handle potential BOM
                return f.read()
        except FileNotFoundError:
            logger.error(f"File not found: {self.filename}")
            return None
        except IOError as e:
            logger.error(f"Error reading file {self.filename}: {e}")
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
            if not data_rows:  # Check if there are any data rows after the header
                print(
                    f"FallbackPositionExtractor: CSV file {self.filename} has a header but no data rows."
                )
                # Depending on requirements, you might still want to return (header, [])
                # For now, let's consider it a case where no positions can be extracted.
                # If processing an empty data set is valid, this could return (header, [])
            return header, data_rows
        except StopIteration:  # next(reader) failed, meaning the CSV was empty or had no header
            print(
                f"FallbackPositionExtractor: CSV file {self.filename} is empty or has no header row."
            )
            return None
        except csv.Error as e:
            print(f"FallbackPositionExtractor: Error parsing CSV data from {self.filename}: {e}")
            return None

    def _resolve_depot(self, raw_depot: str, row_num: int) -> Optional[Tuple[str, Optional[str]]]:
        """Resolve the Depot column into ``(depot, awards_sub_account)``.

        Returns ``None`` if the value is unusable and the row should be skipped.

        - All-digit values denote a brokerage account suffix; the depot is the
          value as-is and there is no AWARDS sub-account.
        - Symbol-shaped values (e.g. ``GOOG``, ``BRK.B``) denote an Equity
          Awards sub-account; depot becomes ``"AWARDS"`` and the symbol is
          carried as the sub-account identifier.
        - The literal ``AWARDS`` and the legacy ``CASH <suffix>`` shapes are
          rejected with a migration message.
        """
        normalized = raw_depot.strip()
        if not normalized:
            print(
                f"FallbackPositionExtractor: Empty Depot in row {row_num} of {self.filename}. Skipping row."
            )
            return None

        if normalized.isdigit():
            return normalized, None

        upper = normalized.upper()
        if upper == "AWARDS":
            print(
                f"FallbackPositionExtractor: Depot 'AWARDS' in row {row_num} of {self.filename} is no longer supported. "
                "Use the equity award symbol (e.g. 'GOOG') in the Depot column to identify the AWARDS sub-account. "
                "Skipping row."
            )
            return None

        if _AWARDS_SYMBOL_PATTERN.match(upper):
            return "AWARDS", upper

        print(
            f"FallbackPositionExtractor: Depot '{raw_depot}' in row {row_num} of {self.filename} is not a valid account suffix "
            "(all digits) or an equity award symbol (e.g. 'GOOG'). Skipping row."
        )
        return None

    def _process_csv_data(
        self, header: List[str], data_rows: List[List[str]]
    ) -> Optional[List[Tuple[Position, SecurityStock]]]:
        """
        Processes the parsed CSV header and data rows.
        Expected header (case-insensitive): [Depot, Date, Symbol, Quantity].
        ``Currency`` is an optional column; when absent or blank, USD is used.
        """
        required_headers = {
            "depot": "Depot",
            "date": "Date",
            "symbol": "Symbol",
            "quantity": "Quantity",
        }
        header_lower_to_original = {h.lower().strip(): h for h in header}

        col_indices: dict[str, int] = {}
        missing_headers: list[str] = []
        for key, expected_name in required_headers.items():
            if key not in header_lower_to_original:
                missing_headers.append(expected_name)
            else:
                col_indices[key] = header.index(header_lower_to_original[key])

        if missing_headers:
            print(
                f"FallbackPositionExtractor: Missing required header(s) in {self.filename}. Expected: {list(required_headers.values())}. Missing: {missing_headers}. Found headers: {header}"
            )
            return None

        if "currency" in header_lower_to_original:
            col_indices["currency"] = header.index(header_lower_to_original["currency"])

        results: List[Tuple[Position, SecurityStock]] = []

        default_currency = "USD"

        for i, row in enumerate(data_rows):
            row_num = i + 1
            if len(row) != len(header):
                print(
                    f"FallbackPositionExtractor: Row {row_num} in {self.filename} has incorrect number of columns. Expected {len(header)}, got {len(row)}. Skipping."
                )
                continue

            try:
                raw_depot = row[col_indices["depot"]]
                date_str = row[col_indices["date"]].strip()
                symbol_str = row[col_indices["symbol"]].strip().upper()
                quantity_str = row[col_indices["quantity"]].strip()
                currency = default_currency
                if "currency" in col_indices:
                    raw_currency = row[col_indices["currency"]].strip().upper()
                    if raw_currency:
                        currency = raw_currency

                if symbol_str == "CASH" or symbol_str.startswith("CASH "):
                    print(
                        f"FallbackPositionExtractor: Symbol '{symbol_str}' in row {row_num} of {self.filename} uses the legacy CASH format. "
                        "Leave the Symbol column empty to declare a cash position; for AWARDS sub-accounts put the equity award symbol "
                        "in the Depot column. Skipping row."
                    )
                    continue

                depot_info = self._resolve_depot(raw_depot, row_num)
                if depot_info is None:
                    continue
                processed_depot, awards_sub_account = depot_info

                try:
                    entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    print(
                        f"FallbackPositionExtractor: Invalid date format '{date_str}' in row {row_num} of {self.filename}. Expected YYYY-MM-DD. Skipping row."
                    )
                    continue

                try:
                    quantity_val = Decimal(quantity_str)
                except InvalidOperation:
                    print(
                        f"FallbackPositionExtractor: Invalid quantity format '{quantity_str}' in row {row_num} of {self.filename}. Skipping row."
                    )
                    continue

                pos: Position
                if not symbol_str:
                    pos = CashPosition(
                        depot=processed_depot,
                        currentCy=currency,
                        cash_account_id=awards_sub_account,
                    )
                    stock_name = "Manual Cash Position from CSV"
                else:
                    pos = SecurityPosition(
                        depot=processed_depot, symbol=symbol_str, description=None
                    )
                    stock_name = f"Manual Security Position for {symbol_str} from CSV"

                stock = SecurityStock(
                    referenceDate=entry_date,
                    mutation=False,
                    quantity=quantity_val,
                    balanceCurrency=currency,
                    quotationType="PIECE",
                    name=stock_name,
                )
                results.append((pos, stock))
            except Exception as e:
                print(
                    f"FallbackPositionExtractor: Unexpected error processing row {row_num} in {self.filename}: {e}. Skipping row."
                )
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
