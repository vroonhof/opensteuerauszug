import csv
import re
from typing import List, Dict, Optional, Tuple
from decimal import Decimal, InvalidOperation
from datetime import datetime, date, timedelta
from opensteuerauszug.model.position import Position, CashPosition, SecurityPosition
from opensteuerauszug.model.ech0196 import SecurityStock, CurrencyId

class PositionExtractor:
    """
    Extracts position data from Schwab CSV files in the expected format.
    """
    def __init__(self, filename: str):
        self.filename = filename

    def extract_positions(self) -> Optional[Tuple[List[Tuple[Position, SecurityStock]], date, str]]:
        """
        Extracts positions and returns a tuple: (positions, statement_date, depot)
        positions: List of (Position, SecurityStock)
        statement_date: The day after the statement date
        depot: The partial account number
        """
        with open(self.filename, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        return self._extract_positions_from_string(content)

    def _extract_positions_from_string(self, content: str) -> Optional[Tuple[List[Tuple[Position, SecurityStock]], date, str]]:
        lines = content.splitlines()
        if not lines or not lines[0].startswith('"Positions for account'):
            # Not the expected format
            return None
        # Extract account number and date from the first line
        m = re.match(r'"Positions for account [^ ]+ \.\.\.(\d+) as of [^,]+, (\d{4}/\d{2}/\d{2})"', lines[0])
        if not m:
            return None
        partial_account_number = m.group(1)
        date_str = m.group(2)
        try:
            parsed_date = datetime.strptime(date_str, "%Y/%m/%d").date()
        except Exception:
            return None
        # The convention in the tax statements is that balance values are taken at the START of the day.
        ref_date = parsed_date + timedelta(days=1)
        # Find the header row (should be the third line)
        for i, line in enumerate(lines):
            if line.startswith('"Symbol"'):
                header_idx = i
                break
        else:
            return None
        reader = csv.DictReader(lines[header_idx:], skipinitialspace=True)
        positions: List[Tuple[Position, SecurityStock]] = []
        for row in reader:
            symbol = row.get('Symbol', '').strip()
            security_type = row.get('Security Type', '').strip() or row.get('Security Type', '').strip()
            qty_str = row.get('Qty (Quantity)', '').replace(',', '').strip()
            mkt_val_str = row.get('Mkt Val (Market Value)', '').replace(',', '').replace('$', '').strip()
            description = row.get('Description', '').strip() if 'Description' in row else None
            try:
                quantity = Decimal(qty_str) if qty_str else Decimal('0')
            except InvalidOperation:
                quantity = Decimal('0')
            depot = partial_account_number
            if symbol == 'Cash & Cash Investments':
                # Cash position
                try:
                    amount = Decimal(mkt_val_str)
                except InvalidOperation:
                    amount = Decimal('0')
                pos = CashPosition(depot=depot, currentCy='USD')
                stock = SecurityStock(
                    referenceDate=ref_date,
                    mutation=False,
                    quotationType='PIECE',
                    quantity=amount,
                    balanceCurrency='USD',
                    balance=amount
                )
                positions.append((pos, stock))
            elif symbol and ' ' not in symbol and security_type:
                # Security position
                pos = SecurityPosition(
                    depot=depot,
                    symbol=symbol,
                    securityType=security_type,
                    description=description
                    # Would have been nice if Schwab gave us this.
                    # isin=row.get('ISIN')
                )
                stock = SecurityStock(
                    referenceDate=ref_date,
                    mutation=False,
                    quotationType='PIECE',
                    quantity=quantity,
                    balanceCurrency='USD'
                )
                positions.append((pos, stock))
            # else: skip rows that don't match expected security/cash
        return positions, ref_date, partial_account_number

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <positions_csv_file>")
        sys.exit(1)
    filename = sys.argv[1]
    extractor = PositionExtractor(filename)
    result = extractor.extract_positions()
    if result is not None:
        import pprint
        pprint.pprint(result)
    else:
        print("File is not a valid Schwab positions CSV or could not extract positions.") 