"""Parse Degiro Portfolio.csv into PortfolioEntry dataclass instances.

Portfolio.csv header is:

    Product,Symbol/ISIN,Amount,Closing,Local value,,Value in CHF

Like Account.csv, the "Local value" column is a currency-code header and the
unnamed column following it holds the numeric amount.  We override DictReader
fieldnames accordingly.
"""

import csv
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from opensteuerauszug.importers.common.parsing import to_decimal


PORTFOLIO_CSV_FIELDNAMES = [
    "Product", "Symbol_ISIN", "Amount", "Closing",
    "Local_currency", "Local_amount", "Value_CHF",
]


@dataclass
class PortfolioEntry:
    product: str
    isin: str
    amount: Decimal
    closing_price: Optional[Decimal]
    local_currency: str
    local_amount: Decimal
    value_chf: Decimal
    is_cash: bool = False


def load_portfolio_csv(path: str) -> list[PortfolioEntry]:
    """Load Portfolio.csv; returns one entry per row (duplicates not aggregated)."""
    entries: list[PortfolioEntry] = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, fieldnames=PORTFOLIO_CSV_FIELDNAMES)
        next(reader)  # skip the actual CSV header row
        for row_num, raw in enumerate(reader, start=2):
            product = raw.get("Product", "").strip()
            if not product:
                continue
            isin = raw.get("Symbol_ISIN", "").strip()
            amount_str = raw.get("Amount", "").strip()
            amount = (
                to_decimal(amount_str, "Amount", f"row {row_num}")
                if amount_str
                else Decimal("0")
            )
            closing_str = raw.get("Closing", "").strip()
            closing_price = (
                to_decimal(closing_str, "Closing", f"row {row_num}")
                if closing_str
                else None
            )
            local_currency = raw.get("Local_currency", "").strip()
            local_amount_str = raw.get("Local_amount", "").strip()
            local_amount = (
                to_decimal(local_amount_str, "Local_amount", f"row {row_num}")
                if local_amount_str
                else Decimal("0")
            )
            value_chf_str = raw.get("Value_CHF", "").strip()
            value_chf = (
                to_decimal(value_chf_str, "Value_CHF", f"row {row_num}")
                if value_chf_str
                else Decimal("0")
            )
            entries.append(
                PortfolioEntry(
                    product=product,
                    isin=isin,
                    amount=amount,
                    closing_price=closing_price,
                    local_currency=local_currency,
                    local_amount=local_amount,
                    value_chf=value_chf,
                    is_cash=not isin,
                )
            )
    return entries
