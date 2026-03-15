"""
Swissquote CSV importer for opensteuerauszug.

Supports the German-language CSV export from Swissquote (Sprache: Deutsch).

Column layout (tab- or semicolon-separated, as exported by Swissquote DE):
    Datum | Auftrag # | Transaktionen | Symbol | Name | ISIN | Anzahl |
    Stückpreis | Kosten | Aufgelaufene Zinsen | Nettobetrag |
    Währung Nettobetrag | Nettobetrag in der Währung des Kontos | Saldo | Währung

Assumption: single-currency CHF account — 'Währung Nettobetrag' always equals
'Währung', so 'Nettobetrag in der Währung des Kontos' is redundant and ignored.

Usage (once registered in steuerauszug.py):
    python -m opensteuerauszug.steuerauszug \
        --importer swissquote transactions_2024.csv \
        --output steuerauszug_2024.pdf \
        --xml-output steuerauszug_2024.xml \
        --year 2024
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column name constants  (exact German strings from the Swissquote export)
# ---------------------------------------------------------------------------

COL_DATE             = "Datum"
COL_ORDER_NR         = "Auftrag #"
COL_TRANSACTION      = "Transaktionen"
COL_SYMBOL           = "Symbol"
COL_NAME             = "Name"
COL_ISIN             = "ISIN"
COL_QUANTITY         = "Anzahl"
COL_UNIT_PRICE       = "Stückpreis"
COL_COSTS            = "Kosten"
COL_ACCRUED_INTEREST = "Aufgelaufene Zinsen"
COL_NET_AMOUNT       = "Nettobetrag"
COL_NET_CURRENCY     = "Währung Nettobetrag"   # present but always == COL_CURRENCY
# "Nettobetrag in der Währung des Kontos" always equals COL_NET_AMOUNT for
# single-currency accounts — we read past it without storing.
COL_BALANCE          = "Saldo"
COL_CURRENCY         = "Währung"               # account currency (CHF)

# ---------------------------------------------------------------------------
# Transaction type mapping  (exact German label -> internal canonical name)
#
# Confirmed Swissquote DE labels:
#   Auszahlung              – cash withdrawal to bank account
#   Berichtigung Börsengeb. – exchange-fee correction / rebate
#   Capital Gain            – capital-gain distribution (fund)
#   Depotgebühren           – annual / quarterly custody fee
#   Dividende               – ordinary cash dividend
#   Forex-Belastung         – FX conversion debit
#   Kauf                    – buy / purchase
#   Twint                   – TWINT cash deposit or payment
#   Stockdividende          – stock dividend (shares paid instead of cash)
#   Spesen Steueraszug      – fee charged for producing the Steuerauszug
#   Rückzahlung             – bond / structured-product redemption at maturity
#   Verkauf                 – sell
#   Wertpapierleihe         – securities-lending income
#   Zahlung                 – generic payment / cash movement
#   Zinsen auf Belastungen  – debit interest (margin / overdraft)
#   Zinsen auf Einlagen     – credit interest on cash balance
# ---------------------------------------------------------------------------

TRANSACTION_TYPE_MAP: dict[str, str] = {
    # ── Trades ────────────────────────────────────────────────────────────
    "Kauf":                    "buy",
    "Verkauf":                 "sell",

    # ── Income from securities ────────────────────────────────────────────
    "Dividende":               "dividend",
    "Stockdividende":          "stock_dividend",
    "Capital Gain":            "capital_gain_distribution",
    "Wertpapierleihe":         "securities_lending_income",

    # ── Interest ──────────────────────────────────────────────────────────
    "Zinsen auf Einlagen":     "credit_interest",    # positive: income
    "Zinsen auf Belastungen":  "debit_interest",     # negative: cost (margin)

    # ── Tax / withholding  (add Verrechnungssteuer / Quellensteuer here   ─
    # ─  if they appear in your export)                                    ─
    "Verrechnungssteuer":      "withholding_tax",
    "Quellensteuer":           "withholding_tax",

    # ── Bond / product redemption ─────────────────────────────────────────
    "Rückzahlung":             "redemption",

    # ── Fees & corrections ────────────────────────────────────────────────
    "Depotgebühren":           "custody_fee",
    "Berichtigung Börsengeb.": "exchange_fee_correction",
    "Spesen Steueraszug":      "tax_statement_fee",

    # ── FX ────────────────────────────────────────────────────────────────
    "Forex-Belastung":         "fx_debit",

    # ── Cash movements ────────────────────────────────────────────────────
    "Auszahlung":              "withdrawal",
    "Twint":                   "twint_payment",
    "Zahlung":                 "payment",
}

# ── Groupings used by the dataclass and eCH-0196 builder ─────────────────

# Rows tied to a specific security (typically carry ISIN / quantity)
SECURITY_TRANSACTION_TYPES = {
    "buy",
    "sell",
    "dividend",
    "stock_dividend",
    "capital_gain_distribution",
    "securities_lending_income",
    "withholding_tax",
    "redemption",
}

# Rows that are purely cash / account-level entries (no security)
CASH_TRANSACTION_TYPES = {
    "credit_interest",
    "debit_interest",
    "custody_fee",
    "exchange_fee_correction",
    "tax_statement_fee",
    "fx_debit",
    "withdrawal",
    "twint_payment",
    "payment",
}

# Income types relevant for the Steuerauszug (taxable receipts)
INCOME_TRANSACTION_TYPES = {
    "dividend",
    "stock_dividend",
    "capital_gain_distribution",
    "securities_lending_income",
    "credit_interest",
}

# Known Swissquote date formats (tried in order)
_DATE_FORMATS = ("%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d")


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class SwissquoteTransaction:
    """One row from the Swissquote CSV, fully parsed."""

    raw_date:             str
    date:                 date
    order_nr:             str
    transaction_type_raw: str
    transaction_type:     str      # canonical internal name (see TRANSACTION_TYPE_MAP)
    symbol:               str
    name:                 str
    isin:                 str
    quantity:             Decimal  # 0 for cash/fee rows
    unit_price:           Decimal  # 0 for cash/fee rows
    costs:                Decimal  # brokerage commission
    accrued_interest:     Decimal  # bonds only; usually 0
    net_amount:           Decimal  # signed CHF amount (negative = debit)
    currency:             str      # "CHF" for single-currency accounts
    balance:              Decimal  # running account balance after this row

    is_security_row: bool = field(init=False)
    is_cash_row:     bool = field(init=False)
    is_income_row:   bool = field(init=False)

    def __post_init__(self):
        self.is_security_row = self.transaction_type in SECURITY_TRANSACTION_TYPES
        self.is_cash_row     = self.transaction_type in CASH_TRANSACTION_TYPES
        self.is_income_row   = self.transaction_type in INCOME_TRANSACTION_TYPES


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_decimal(value: str) -> Decimal:
    """
    Parse a Swissquote numeric string to Decimal.

    Handles:
      - empty / blank           ->  Decimal("0")
      - apostrophe thousands    ->  "1'234.56"  ->  Decimal("1234.56")
      - comma decimal (no dot)  ->  "1234,56"   ->  Decimal("1234.56")
      - European format         ->  "1.234,56"  ->  Decimal("1234.56")
    """
    if not value or not value.strip():
        return Decimal("0")
    s = value.strip().replace("'", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s and "." in s:
        if s.index(".") < s.index(","):          # European: "1.234,56"
            s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        logger.warning("Cannot parse numeric value %r -- using 0", value)
        return Decimal("0")


def _parse_date(value: str) -> date:
    """Try all known Swissquote date formats; raise ValueError if none match."""
    import datetime as _dt
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {value!r}")


def _detect_delimiter(filepath: Path) -> str:
    """Return tab or semicolon by counting occurrences in the first 4 KB."""
    with open(filepath, encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
    return "\t" if sample.count("\t") >= sample.count(";") else ";"


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def parse_swissquote_csv(filepath: Path) -> Iterator[SwissquoteTransaction]:
    """
    Parse a Swissquote German CSV export and yield SwissquoteTransaction
    objects one per row.  Rows with unrecognised transaction types are
    logged as WARNINGs and skipped — add the label to TRANSACTION_TYPE_MAP.
    """
    filepath  = Path(filepath)
    delimiter = _detect_delimiter(filepath)
    logger.info("Parsing Swissquote CSV: %s  (delimiter=%r)", filepath, delimiter)

    with open(filepath, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)

        for lineno, row in enumerate(reader, start=2):   # header = line 1

            raw_type      = (row.get(COL_TRANSACTION) or "").strip()
            internal_type = TRANSACTION_TYPE_MAP.get(raw_type)
            if internal_type is None:
                logger.warning(
                    "Line %d: unknown Transaktionen value %r -- skipping row. "
                    "Add it to TRANSACTION_TYPE_MAP if needed.",
                    lineno, raw_type,
                )
                continue

            raw_date = (row.get(COL_DATE) or "").strip()
            try:
                parsed_date = _parse_date(raw_date)
            except ValueError as exc:
                logger.warning("Line %d: %s -- skipping row", lineno, exc)
                continue

            yield SwissquoteTransaction(
                raw_date             = raw_date,
                date                 = parsed_date,
                order_nr             = (row.get(COL_ORDER_NR)         or "").strip(),
                transaction_type_raw = raw_type,
                transaction_type     = internal_type,
                symbol               = (row.get(COL_SYMBOL)           or "").strip(),
                name                 = (row.get(COL_NAME)             or "").strip(),
                isin                 = (row.get(COL_ISIN)             or "").strip(),
                quantity             = _parse_decimal(row.get(COL_QUANTITY,         "")),
                unit_price           = _parse_decimal(row.get(COL_UNIT_PRICE,       "")),
                costs                = _parse_decimal(row.get(COL_COSTS,            "")),
                accrued_interest     = _parse_decimal(row.get(COL_ACCRUED_INTEREST, "")),
                net_amount           = _parse_decimal(row.get(COL_NET_AMOUNT,       "")),
                currency             = (row.get(COL_CURRENCY) or "CHF").strip(),
                balance              = _parse_decimal(row.get(COL_BALANCE,          "")),
            )


# ---------------------------------------------------------------------------
# Dividend / withholding-tax pairing
# ---------------------------------------------------------------------------

def pair_dividends_and_taxes(
    transactions: list[SwissquoteTransaction],
) -> list[tuple[SwissquoteTransaction, Optional[SwissquoteTransaction]]]:
    """
    Swissquote emits dividend income and the corresponding withholding tax
    (Verrechnungssteuer / Quellensteuer) as two separate rows on the same
    date for the same ISIN.

    This pairs them so the eCH-0196 builder can emit a single dividend entry
    carrying both the gross amount and the withheld tax amount.

    Returns (primary_row, partner_or_None) tuples.
    Non-dividend rows are returned as (row, None).
    """
    paired:   list[tuple[SwissquoteTransaction, Optional[SwissquoteTransaction]]] = []
    consumed: set[int] = set()

    for i, tx in enumerate(transactions):
        if i in consumed:
            continue

        if tx.transaction_type in ("dividend", "stock_dividend",
                                   "capital_gain_distribution"):
            partner: Optional[SwissquoteTransaction] = None
            for j in range(max(0, i - 3), min(len(transactions), i + 4)):
                if j == i or j in consumed:
                    continue
                cand = transactions[j]
                if (cand.transaction_type == "withholding_tax"
                        and cand.isin == tx.isin
                        and abs((cand.date - tx.date).days) <= 1):
                    partner = cand
                    consumed.add(j)
                    break
            paired.append((tx, partner))
            consumed.add(i)

        elif tx.transaction_type == "withholding_tax" and i not in consumed:
            # Orphan tax row — no matching dividend found nearby
            logger.warning(
                "Orphaned withholding_tax row on %s for ISIN %s "
                "(no matching dividend/capital-gain within +/-1 day).",
                tx.date, tx.isin,
            )
            paired.append((tx, None))
            consumed.add(i)

        else:
            paired.append((tx, None))
            consumed.add(i)

    return paired


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_swissquote(filepath: str | Path) -> list[SwissquoteTransaction]:
    """
    Parse the Swissquote German CSV and return all transactions.

    Register in steuerauszug.py:

        from opensteuerauszug.importer_swissquote import load_swissquote
        IMPORTERS["swissquote"] = load_swissquote
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Swissquote CSV not found: {filepath}")

    txs = list(parse_swissquote_csv(filepath))

    logger.info(
        "Loaded %d transactions  "
        "(Kauf=%d  Verkauf=%d  Dividende=%d  Steuer=%d  Sonstiges=%d)",
        len(txs),
        sum(1 for t in txs if t.transaction_type == "buy"),
        sum(1 for t in txs if t.transaction_type == "sell"),
        sum(1 for t in txs if t.transaction_type in (
            "dividend", "stock_dividend", "capital_gain_distribution")),
        sum(1 for t in txs if t.transaction_type in ("withholding_tax",)),
        sum(1 for t in txs if t.transaction_type not in (
            "buy", "sell", "dividend", "stock_dividend",
            "capital_gain_distribution", "withholding_tax")),
    )

    return txs
