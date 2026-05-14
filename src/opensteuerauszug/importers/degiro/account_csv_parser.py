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
    "Date",
    "Time",
    "Value date",
    "Product",
    "ISIN",
    "Description",
    "FX",
    "Change_currency",
    "Change_amount",
    "Balance_currency",
    "Balance_amount",
    "Order Id",
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


# Exact-match descriptions → row kind (all supported languages).
_EXACT_MATCH: dict[str, DegiroRowKind] = {
    # EN              IT                          FR                          DE
    "Dividend Tax": DegiroRowKind.DIVIDEND_TAX,
    "Imposta sui dividendi": DegiroRowKind.DIVIDEND_TAX,
    "Impôt sur les dividendes": DegiroRowKind.DIVIDEND_TAX,
    "Dividendensteuer": DegiroRowKind.DIVIDEND_TAX,
    "Dividend": DegiroRowKind.DIVIDEND,
    "Dividendo": DegiroRowKind.DIVIDEND,
    "Dividende": DegiroRowKind.DIVIDEND,
    "FX Credit": DegiroRowKind.FX_CREDIT,
    "Credito FX": DegiroRowKind.FX_CREDIT,
    "Crédit FX": DegiroRowKind.FX_CREDIT,
    "FX-Gutschrift": DegiroRowKind.FX_CREDIT,
    "FX Debit": DegiroRowKind.FX_DEBIT,
    "Prelievo FX": DegiroRowKind.FX_DEBIT,
    "Débit FX": DegiroRowKind.FX_DEBIT,
    "FX-Belastung": DegiroRowKind.FX_DEBIT,
    "Deposit": DegiroRowKind.DEPOSIT,
    "Deposito": DegiroRowKind.DEPOSIT,
    "Dépôt": DegiroRowKind.DEPOSIT,
    "Einzahlung": DegiroRowKind.DEPOSIT,
    "Degiro Cash Sweep Transfer": DegiroRowKind.DEGIRO_SWEEP,
}

# Prefix-match descriptions → row kind (case-sensitive).
_PREFIX_MATCH: list[tuple[str, DegiroRowKind]] = [
    # BUY_SELL
    ("Buy ", DegiroRowKind.BUY_SELL),
    ("Sell ", DegiroRowKind.BUY_SELL),
    ("Acquisto ", DegiroRowKind.BUY_SELL),
    ("Vendita ", DegiroRowKind.BUY_SELL),
    ("Achat ", DegiroRowKind.BUY_SELL),
    ("Vente ", DegiroRowKind.BUY_SELL),
    ("Kauf ", DegiroRowKind.BUY_SELL),
    ("Verkauf ", DegiroRowKind.BUY_SELL),
    # CORPORATE_CASH
    ("Corporate Action Cash Settlement", DegiroRowKind.CORPORATE_CASH),
    # DELISTING
    ("DELISTING:", DegiroRowKind.DELISTING),
    # CASH_SWEEP
    ("Transfer from", DegiroRowKind.CASH_SWEEP_IN),
    ("Überweisung von", DegiroRowKind.CASH_SWEEP_IN),
    ("Transfer to", DegiroRowKind.CASH_SWEEP_OUT),
    ("Überweisung an", DegiroRowKind.CASH_SWEEP_OUT),
]

# Prefix-match descriptions → row kind (case-insensitive).
# Degiro is inconsistent with capitalization across locales, e.g.
# "DEGIRO costi di transazione" vs "DEGIRO Costi di connessione".
_PREFIX_MATCH_NOCASE: list[tuple[str, DegiroRowKind]] = [
    # FEE_TRANSACTION
    ("degiro transaction", DegiroRowKind.FEE_TRANSACTION),
    ("degiro costi di transazione", DegiroRowKind.FEE_TRANSACTION),
    ("degiro frais de transaction", DegiroRowKind.FEE_TRANSACTION),
    ("degiro transaktionsgebühren", DegiroRowKind.FEE_TRANSACTION),
    # FEE_CONNECTION
    ("degiro exchange connection fee", DegiroRowKind.FEE_CONNECTION),
    ("degiro costi di connessione", DegiroRowKind.FEE_CONNECTION),
    ("degiro frais de connexion", DegiroRowKind.FEE_CONNECTION),
    ("degiro börsengebühren", DegiroRowKind.FEE_CONNECTION),
    ("degiro anschlussgebühren", DegiroRowKind.FEE_CONNECTION),
]

# Substring-match descriptions → row kind (case-insensitive).
_CONTAINS_MATCH: list[tuple[str, DegiroRowKind]] = [
    ("flatex interest", DegiroRowKind.FLATEX_INTEREST),
]


def classify_row(row: DegiroRow) -> DegiroRowKind:
    """Return the semantic kind of *row* based on its description field.

    Degiro exports descriptions in the user's account language.
    Supported: English, Italian, French, German.
    """
    desc = row.description

    kind = _EXACT_MATCH.get(desc)
    if kind is not None:
        return kind

    for prefix, kind in _PREFIX_MATCH:
        if desc.startswith(prefix):
            return kind

    desc_lower = desc.lower()
    for prefix, kind in _PREFIX_MATCH_NOCASE:
        if desc_lower.startswith(prefix):
            return kind

    for substr, kind in _CONTAINS_MATCH:
        if substr in desc_lower:
            return kind

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
            fx_rate = to_decimal(fx_str, "FX", f"row {row_num}") if fx_str else None
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
                    value_date=(_parse_date(vd_str) if vd_str else _parse_date(date_str)),
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
