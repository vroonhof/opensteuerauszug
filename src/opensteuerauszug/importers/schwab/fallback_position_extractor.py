import csv
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from opensteuerauszug.model.ech0196 import SecurityStock
from opensteuerauszug.model.position import CashPosition, Position, SecurityPosition

logger = logging.getLogger(__name__)

_TRAILING_DIGITS = re.compile(r"(\d+)$")


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

        # Explicit equity-awards format: "AWARDS <SYMBOL>" (e.g. "AWARDS GOOG").
        if upper.startswith("AWARDS "):
            awards_symbol = upper[7:].strip()
            if awards_symbol:
                return "AWARDS", awards_symbol
            print(
                f"FallbackPositionExtractor: Depot '{raw_depot}' in row {row_num} of {self.filename} "
                "has 'AWARDS' but no symbol. Use 'AWARDS <SYMBOL>' (e.g. 'AWARDS GOOG'). Skipping row."
            )
            return None

        if upper == "AWARDS":
            print(
                f"FallbackPositionExtractor: Depot 'AWARDS' in row {row_num} of {self.filename} is no longer supported. "
                "Use 'AWARDS <SYMBOL>' (e.g. 'AWARDS GOOG') to identify an equity-awards sub-account. "
                "Skipping row."
            )
            return None

        # Old-style brokerage identifiers end with digits, e.g. "XXX178" or "Schwab789".
        # Extract trailing digits and use the last three as the depot ID.
        m = _TRAILING_DIGITS.search(normalized)
        if m:
            suffix = m.group(1)
            depot_id = suffix[-3:] if len(suffix) > 3 else suffix
            print(
                f"FallbackPositionExtractor: Depot '{raw_depot}' in row {row_num} of {self.filename} uses the old format. "
                f"Please update the Depot column to just '{depot_id}'. Using '{depot_id}' for now."
            )
            return depot_id, None

        print(
            f"FallbackPositionExtractor: Depot '{raw_depot}' in row {row_num} of {self.filename} is not a valid account suffix "
            "(all digits, e.g. '178') or an equity-awards entry ('AWARDS GOOG'). Skipping row."
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

                if symbol_str.startswith("CASH "):
                    print(
                        f"FallbackPositionExtractor: Symbol '{symbol_str}' in row {row_num} of {self.filename} uses the legacy CASH format. "
                        "Use 'CASH' (without suffix) in the Symbol column to declare a cash position; for AWARDS sub-accounts put the equity "
                        "award symbol in the Depot column. Skipping row."
                    )
                    continue

                if not symbol_str:
                    print(
                        f"FallbackPositionExtractor: Empty Symbol in row {row_num} of {self.filename}. "
                        "Use 'CASH' in the Symbol column to declare a cash position. Skipping row."
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
                if symbol_str == "CASH":
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
