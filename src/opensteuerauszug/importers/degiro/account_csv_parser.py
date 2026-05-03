"""Parse Degiro Account.csv into DegiroRow dataclass instances.

Account.csv is exported in reverse-chronological order.  The header row is:

    Date,Time,Value date,Product,ISIN,Description,FX,Change,,Balance,,Order Id

The "Change" and "Balance" column-pairs each occupy two CSV columns: the
named header holds the currency code while the unnamed following column
holds the amount.  We override DictReader fieldnames to expose them as
Change_currency/Change_amount and Balance_currency/Balance_amount.
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Optional

from opensteuerauszug.importers.common.parsing import to_decimal


ACCOUNT_CSV_FIELDNAMES = [
    "Date", "Time", "Value date", "Product", "ISIN",
    "Description", "FX", "Change_currency", "Change_amount",
    "Balance_currency", "Balance_amount", "Order Id",
]


@dataclass
class DegiroRow:
    date: date
    time: str
    value_date: date
    product: str
    isin: str
    description: str
    fx_rate: Optional[Decimal]
    change_currency: str
    change_amount: Decimal
    balance_currency: str
    balance_amount: Decimal
    order_id: str
    raw_row: int


class DegiroRowKind(Enum):
    BUY_SELL = auto()
    DIVIDEND = auto()
    DIVIDEND_TAX = auto()
    FX_CREDIT = auto()
    FX_DEBIT = auto()
    FEE_TRANSACTION = auto()
    FEE_CONNECTION = auto()
    CORPORATE_CASH = auto()
    DELISTING = auto()
    DEPOSIT = auto()
    FLATEX_INTEREST = auto()
    CASH_SWEEP_IN = auto()
    CASH_SWEEP_OUT = auto()
    DEGIRO_SWEEP = auto()
    UNKNOWN = auto()


def classify_row(row: DegiroRow) -> DegiroRowKind:
    """Return the semantic kind of *row* based on its description field."""
    desc = row.description
    if desc.startswith("Buy ") or desc.startswith("Sell "):
        return DegiroRowKind.BUY_SELL
    if desc == "Dividend Tax":
        return DegiroRowKind.DIVIDEND_TAX
    if desc == "Dividend":
        return DegiroRowKind.DIVIDEND
    if desc == "FX Credit":
        return DegiroRowKind.FX_CREDIT
    if desc == "FX Debit":
        return DegiroRowKind.FX_DEBIT
    if desc.startswith("DEGIRO Transaction"):
        return DegiroRowKind.FEE_TRANSACTION
    if desc.startswith("DEGIRO Exchange Connection Fee"):
        return DegiroRowKind.FEE_CONNECTION
    if desc.startswith("Corporate Action Cash Settlement"):
        return DegiroRowKind.CORPORATE_CASH
    if desc.startswith("DELISTING:"):
        return DegiroRowKind.DELISTING
    if desc.startswith("Deposit"):
        return DegiroRowKind.DEPOSIT
    if "Flatex Interest" in desc or "flatex Interest" in desc:
        return DegiroRowKind.FLATEX_INTEREST
    if desc.startswith("Transfer from"):
        return DegiroRowKind.CASH_SWEEP_IN
    if desc.startswith("Transfer to"):
        return DegiroRowKind.CASH_SWEEP_OUT
    if desc == "Degiro Cash Sweep Transfer":
        return DegiroRowKind.DEGIRO_SWEEP
    return DegiroRowKind.UNKNOWN


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%d-%m-%Y").date()


def load_account_csv(path: str) -> list[DegiroRow]:
    """Load Account.csv; returns rows in their original reverse-chronological order."""
    rows: list[DegiroRow] = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, fieldnames=ACCOUNT_CSV_FIELDNAMES)
        next(reader)  # skip the actual CSV header row
        for row_num, raw in enumerate(reader, start=2):
            date_str = raw.get("Date", "").strip()
            if not date_str:
                continue
            vd_str = raw.get("Value date", "").strip()
            fx_str = raw.get("FX", "").strip()
            fx_rate = (
                to_decimal(fx_str, "FX", f"row {row_num}") if fx_str else None
            )
            change_str = raw.get("Change_amount", "").strip()
            change_amount = (
                to_decimal(change_str, "Change_amount", f"row {row_num}")
                if change_str
                else Decimal("0")
            )
            balance_str = raw.get("Balance_amount", "").strip()
            balance_amount = (
                to_decimal(balance_str, "Balance_amount", f"row {row_num}")
                if balance_str
                else Decimal("0")
            )
            rows.append(
                DegiroRow(
                    date=_parse_date(date_str),
                    time=raw.get("Time", "").strip(),
                    value_date=(
                        _parse_date(vd_str) if vd_str else _parse_date(date_str)
                    ),
                    product=raw.get("Product", "").strip(),
                    isin=raw.get("ISIN", "").strip(),
                    description=raw.get("Description", "").strip(),
                    fx_rate=fx_rate,
                    change_currency=raw.get("Change_currency", "").strip(),
                    change_amount=change_amount,
                    balance_currency=raw.get("Balance_currency", "").strip(),
                    balance_amount=balance_amount,
                    order_id=raw.get("Order Id", "").strip(),
                    raw_row=row_num,
                )
            )
    return rows
