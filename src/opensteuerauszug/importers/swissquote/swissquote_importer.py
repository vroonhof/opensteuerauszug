"""
Swissquote CSV importer for opensteuerauszug.

Supports the German-language CSV export from Swissquote (Sprache: Deutsch).

Column layout (tab- or semicolon-separated, as exported by Swissquote DE):
    Datum | Auftrag # | Transaktionen | Symbol | Name | ISIN | Anzahl |
    Stückpreis | Kosten | Aufgelaufene Zinsen | Nettobetrag |
    Währung Nettobetrag | Nettobetrag in der Währung des Kontos | Saldo | Währung

Assumption: single-currency CHF account — 'Währung Nettobetrag' always equals
'Währung', so 'Nettobetrag in der Währung des Kontos' is redundant and ignored.

Usage:
    python -m opensteuerauszug.steuerauszug \
        --importer swissquote transactions_2024.csv \
        --tax-year 2024 \
        --output steuerauszug_2024.pdf \
        --xml-output steuerauszug_2024.xml
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

from opensteuerauszug.model.ech0196 import (
    BankAccount,
    BankAccountName,
    BankAccountNumber,
    BankAccountPayment,
    BankAccountTaxValue,
    Client,
    ClientNumber,
    Depot,
    DepotNumber,
    Institution,
    ISINType,
    ListOfBankAccounts,
    ListOfSecurities,
    Security,
    SecurityPayment,
    SecurityStock,
    TaxStatement,
)
from opensteuerauszug.config.models import SwissquoteAccountSettings, GeneralSettings
from opensteuerauszug.core.constants import UNINITIALIZED_QUANTITY

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
COL_NET_CURRENCY     = "Währung Nettobetrag"
# "Nettobetrag in der Währung des Kontos" always equals COL_NET_AMOUNT
# for single-currency CHF accounts — skipped.
COL_BALANCE          = "Saldo"
COL_CURRENCY         = "Währung"

# ---------------------------------------------------------------------------
# Transaction type mapping  (exact German label -> internal canonical name)
# ---------------------------------------------------------------------------

TRANSACTION_TYPE_MAP: dict[str, str] = {
    # Trades
    "Kauf":                      "buy",
    "Verkauf":                   "sell",
    # Income from securities
    "Dividende":                 "dividend",
    "Stockdividende":            "stock_dividend",
    "Capital Gain":              "capital_gain_distribution",
    "Wertpapierleihe":           "securities_lending_income",
    # Interest
    "Zinsen auf Einlagen":       "credit_interest",
    "Zinsen auf Belastungen":    "debit_interest",
    # Tax / withholding
    "Verrechnungssteuer":        "withholding_tax",
    "Quellensteuer":             "withholding_tax",
    # Bond / product redemption
    "Rückzahlung":               "redemption",
    # Fees & corrections
    "Depotgebühren":             "custody_fee",
    "Berichtigung Börsengeb.":   "exchange_fee_correction",
    "Spesen Steuerauszug":       "tax_statement_fee",
    # FX
    "Forex-Belastung":           "fx_debit",
    "Forex-Gutschrift":          "fx_credit",
    "Fx-Gutschrift Comp.":       "fx_credit",
    "Fx-Belastung Comp.":        "fx_debit",
    # Cash movements
    "Auszahlung":                "withdrawal",
    "Einzahlung":                "deposit",
    "Twint":                     "twint_payment",
    "Zahlung":                   "payment",
    # Corporate actions
    "Interne Titelumbuchung":    "corporate_action",
    "Reverse Split":             "corporate_action",
    "Fusion":                    "corporate_action",
    "Ausgabe von Anrechten":     "corporate_action",
    "Vorrechtszeichungsangebot": "corporate_action",
    # Crypto
    "Crypto Deposit":            "deposit",
}

SECURITY_TRANSACTION_TYPES = {
    "buy", "sell", "dividend", "stock_dividend",
    "capital_gain_distribution", "securities_lending_income",
    "withholding_tax", "redemption",
}

CASH_TRANSACTION_TYPES = {
    "credit_interest", "debit_interest", "custody_fee",
    "exchange_fee_correction", "tax_statement_fee",
    "fx_debit", "fx_credit", "withdrawal", "deposit",
    "twint_payment", "payment",
}

INCOME_TRANSACTION_TYPES = {
    "dividend", "stock_dividend", "capital_gain_distribution",
    "securities_lending_income", "credit_interest",
}

_DATE_FORMATS = (
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    "%d.%m.%Y", "%Y/%m/%d",
)

# ---------------------------------------------------------------------------
# Data class for a single parsed row
# ---------------------------------------------------------------------------

@dataclass
class SwissquoteTransaction:
    """One row from the Swissquote CSV, fully parsed."""

    raw_date:             str
    date:                 date
    order_nr:             str
    transaction_type_raw: str
    transaction_type:     str
    symbol:               str
    name:                 str
    isin:                 str
    quantity:             Decimal
    unit_price:           Decimal
    costs:                Decimal
    accrued_interest:     Decimal
    net_amount:           Decimal
    currency:             str
    balance:              Decimal

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
    if not value or not value.strip():
        return Decimal("0")
    s = value.strip().replace("'", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s and "." in s:
        if s.index(".") < s.index(","):
            s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        logger.warning("Cannot parse numeric value %r -- using 0", value)
        return Decimal("0")


def _parse_date(value: str) -> date:
    import datetime as _dt
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {value!r}")


def _detect_delimiter(filepath: Path) -> str:
    with open(filepath, encoding="cp1252") as fh:
        sample = fh.read(4096)
    return "\t" if sample.count("\t") >= sample.count(";") else ";"


# ---------------------------------------------------------------------------
# CSV parser (yields raw SwissquoteTransaction rows)
# ---------------------------------------------------------------------------

def parse_swissquote_csv(filepath: Path) -> Iterator[SwissquoteTransaction]:
    """
    Parse a Swissquote German CSV export and yield SwissquoteTransaction
    objects one per row.  Raises ValueError on unrecognised transaction
    types — add the label to TRANSACTION_TYPE_MAP in swissquote_importer.py
    to handle it.
    """
    filepath  = Path(filepath)
    delimiter = _detect_delimiter(filepath)
    logger.info("Parsing Swissquote CSV: %s  (delimiter=%r)", filepath, delimiter)

    with open(filepath, encoding="cp1252", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        for lineno, row in enumerate(reader, start=2):
            raw_type      = (row.get(COL_TRANSACTION) or "").strip()
            internal_type = TRANSACTION_TYPE_MAP.get(raw_type)
            if internal_type is None:
                raise ValueError(
                    f"Line {lineno}: unknown Transaktionen value {raw_type!r}. "
                    f"Add it to TRANSACTION_TYPE_MAP in swissquote_importer.py "
                    f"to handle this transaction type."
                )

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
# SwissquoteImporter class  (matches the IbkrImporter / SchwabImporter pattern)
# ---------------------------------------------------------------------------

class SwissquoteImporter:
    """
    Imports Swissquote German CSV exports and converts them to a TaxStatement.

    Called from steuerauszug.py as:
        importer = SwissquoteImporter(
            period_from=parsed_period_from,
            period_to=parsed_period_to,
            account_settings_list=all_swissquote_account_settings_models,
        )
        statement = importer.import_file(str(input_file))
    """

    def __init__(
        self,
        period_from: Optional[date] = None,
        period_to:   Optional[date] = None,
        account_settings_list: Optional[List[SwissquoteAccountSettings]] = None,
        general_settings: Optional[GeneralSettings] = None,
    ):
        self.period_from           = period_from
        self.period_to             = period_to
        self.account_settings_list = account_settings_list or []
        self.general_settings      = general_settings

        if self.account_settings_list:
            self._account_id = getattr(
                self.account_settings_list[0], "account_number", "SQ"
            )
        else:
            self._account_id = "SQ"

    def import_file(self, filename: str) -> TaxStatement:
        """
        Parse the Swissquote CSV and return a TaxStatement.

        Args:
            filename: Path to the Swissquote German CSV export.

        Returns:
            A TaxStatement populated with securities and bank account data.
        """
        filepath = Path(filename)
        if not filepath.exists():
            raise FileNotFoundError(f"Swissquote CSV not found: {filepath}")

        transactions = list(parse_swissquote_csv(filepath))

        logger.info(
            "Loaded %d transactions "
            "(Kauf=%d  Verkauf=%d  Dividende=%d  Steuer=%d  Sonstiges=%d)",
            len(transactions),
            sum(1 for t in transactions if t.transaction_type == "buy"),
            sum(1 for t in transactions if t.transaction_type == "sell"),
            sum(1 for t in transactions if t.transaction_type in (
                "dividend", "stock_dividend", "capital_gain_distribution")),
            sum(1 for t in transactions if t.transaction_type == "withholding_tax"),
            sum(1 for t in transactions if t.transaction_type not in (
                "buy", "sell", "dividend", "stock_dividend",
                "capital_gain_distribution", "withholding_tax")),
        )

        period_from, period_to = self._resolve_period(transactions)
        statement = self._build_tax_statement(transactions, period_from, period_to)
        return statement

    def _resolve_period(
        self, transactions: List[SwissquoteTransaction]
    ) -> tuple[date, date]:
        """Return (period_from, period_to), falling back to data range."""
        if self.period_from and self.period_to:
            return self.period_from, self.period_to

        if not transactions:
            today = date.today()
            return date(today.year, 1, 1), date(today.year, 12, 31)

        dates     = [t.date for t in transactions]
        data_from = self.period_from or min(dates)
        data_to   = self.period_to   or max(dates)
        logger.info(
            "Period not fully specified — using data range: %s to %s",
            data_from, data_to,
        )
        return data_from, data_to

    def _build_tax_statement(
        self,
        transactions: List[SwissquoteTransaction],
        period_from:  date,
        period_to:    date,
    ) -> TaxStatement:
        """Convert parsed transactions into a TaxStatement."""

        security_data: Dict[str, dict] = defaultdict(
            lambda: {"stocks": [], "payments": [], "name": "", "symbol": ""}
        )
        cash_data: Dict[str, dict] = defaultdict(
            lambda: {"payments": [], "closing_balance": Decimal("0")}
        )
        last_balance: Dict[str, Decimal] = {}

        for tx in transactions:
            last_balance[tx.currency] = tx.balance

            if tx.is_security_row and tx.isin:
                sd = security_data[tx.isin]
                if len(tx.name) > len(sd["name"]):
                    sd["name"]   = tx.name
                    sd["symbol"] = tx.symbol

                if tx.transaction_type in ("buy", "sell"):
                    sd["stocks"].append(SecurityStock(
                        referenceDate   = tx.date,
                        mutation        = True,
                        quantity        = tx.quantity if tx.transaction_type == "buy"
                                          else -tx.quantity,
                        unitPrice       = tx.unit_price if tx.unit_price else None,
                        name            = tx.transaction_type_raw,
                        orderId         = tx.order_nr or None,
                        balanceCurrency = tx.currency,
                        quotationType   = "PIECE",
                    ))

                elif tx.transaction_type == "redemption":
                    sd["stocks"].append(SecurityStock(
                        referenceDate   = tx.date,
                        mutation        = True,
                        quantity        = -tx.quantity if tx.quantity else Decimal("0"),
                        name            = tx.transaction_type_raw,
                        balanceCurrency = tx.currency,
                        quotationType   = "PIECE",
                    ))

                elif tx.transaction_type in (
                    "dividend", "stock_dividend", "capital_gain_distribution",
                    "securities_lending_income",
                ):
                    payment = SecurityPayment(
                        paymentDate          = tx.date,
                        name                 = tx.transaction_type_raw,
                        amountCurrency       = tx.currency,
                        amount               = tx.net_amount,
                        quotationType        = "PIECE",
                        quantity             = UNINITIALIZED_QUANTITY,
                        broker_label_original = tx.transaction_type_raw,
                    )
                    sd["payments"].append(payment)

                elif tx.transaction_type == "withholding_tax":
                    wht_amount = abs(tx.net_amount)
                    if sd["payments"]:
                        last_payment = sd["payments"][-1]
                        if tx.currency == "CHF":
                            last_payment.withHoldingTaxClaim = wht_amount
                        else:
                            last_payment.nonRecoverableTaxAmountOriginal = wht_amount
                    else:
                        logger.warning(
                            "Withholding tax on %s for ISIN %s has no "
                            "prior dividend payment to attach to.",
                            tx.date, tx.isin,
                        )
                        payment = SecurityPayment(
                            paymentDate    = tx.date,
                            name           = tx.transaction_type_raw,
                            amountCurrency = tx.currency,
                            amount         = Decimal("0"),
                            quotationType  = "PIECE",
                            quantity       = UNINITIALIZED_QUANTITY,
                        )
                        if tx.currency == "CHF":
                            payment.withHoldingTaxClaim = wht_amount
                        else:
                            payment.nonRecoverableTaxAmountOriginal = wht_amount
                        sd["payments"].append(payment)

            elif tx.is_cash_row:
                if tx.transaction_type in ("credit_interest", "debit_interest"):
                    cash_data[tx.currency]["payments"].append(
                        BankAccountPayment(
                            paymentDate    = tx.date,
                            name           = tx.transaction_type_raw,
                            amountCurrency = tx.currency,
                            amount         = tx.net_amount,
                        )
                    )
                else:
                    logger.debug(
                        "Skipping non-income cash row: %s %s %s",
                        tx.date, tx.transaction_type_raw, tx.net_amount,
                    )

        for currency, balance in last_balance.items():
            cash_data[currency]["closing_balance"] = balance

        end_plus_one = period_to + timedelta(days=1)
        securities: List[Security] = []
        pos_id = 0

        for isin, sd in security_data.items():
            pos_id += 1
            stocks: List[SecurityStock] = sd["stocks"]

            pre_period_qty = sum(
                (s.quantity for s in stocks
                 if s.mutation and s.referenceDate < period_from),
                Decimal("0"),
            )
            in_period_qty = sum(
                (s.quantity for s in stocks
                 if s.mutation and s.referenceDate >= period_from),
                Decimal("0"),
            )
            opening_qty = pre_period_qty
            closing_qty = pre_period_qty + in_period_qty

            stocks.append(SecurityStock(
                referenceDate   = period_from,
                mutation        = False,
                quantity        = opening_qty,
                balanceCurrency = "CHF",
                quotationType   = "PIECE",
                name            = "Opening balance",
            ))
            stocks.append(SecurityStock(
                referenceDate   = end_plus_one,
                mutation        = False,
                quantity        = closing_qty,
                balanceCurrency = "CHF",
                quotationType   = "PIECE",
                name            = "Closing balance",
            ))

            stocks_sorted   = sorted(stocks,          key=lambda s: (s.referenceDate, s.mutation))
            payments_sorted = sorted(sd["payments"],   key=lambda p: p.paymentDate)

            sec = Security(
                positionId       = pos_id,
                currency         = "CHF",
                quotationType    = "PIECE",
                securityCategory = "SHARE",
                securityName     = sd["name"] or sd["symbol"] or isin,
                isin             = ISINType(isin),
                valorNumber      = None,
                country          = "CH",
                stock            = stocks_sorted,
                payment          = payments_sorted,
            )
            securities.append(sec)

        depot = Depot(
            depotNumber = DepotNumber(self._account_id),
            security    = securities,
        ) if securities else None

        list_of_securities = ListOfSecurities(depot=[depot]) if depot else None

        bank_accounts: List[BankAccount] = []
        for currency, cd in cash_data.items():
            closing         = cd["closing_balance"]
            payments_sorted = sorted(cd["payments"], key=lambda p: p.paymentDate)
            ba = BankAccount(
                bankAccountName     = BankAccountName(f"{self._account_id} {currency}"),
                bankAccountNumber   = BankAccountNumber(f"{self._account_id}-{currency}"),
                bankAccountCountry  = "CH",
                bankAccountCurrency = currency,
                payment             = payments_sorted,
                taxValue            = BankAccountTaxValue(
                    referenceDate   = period_to,
                    name            = "Closing Balance",
                    balanceCurrency = currency,
                    balance         = closing,
                ),
            )
            bank_accounts.append(ba)

        list_of_bank_accounts = (
            ListOfBankAccounts(bankAccount=bank_accounts) if bank_accounts else None
        )

        statement = TaxStatement(
            minorVersion       = 1,
            periodFrom         = period_from,
            periodTo           = period_to,
            taxPeriod          = period_from.year,
            listOfSecurities   = list_of_securities,
            listOfBankAccounts = list_of_bank_accounts,
        )

        statement.institution = Institution(name="Swissquote Bank AG")

        client_last_name  = None
        client_first_name = None
        if self.general_settings:
            full_name = getattr(self.general_settings, "full_name", None)
            if full_name:
                parts = str(full_name).strip().split(None, 1)
                if len(parts) == 2:
                    client_first_name, client_last_name = parts
                else:
                    client_last_name = parts[0]

        if client_last_name:
            statement.client = [Client(
                clientNumber = ClientNumber(self._account_id),
                firstName    = client_first_name,
                lastName     = client_last_name,
            )]

        logger.info(
            "TaxStatement built: %d securities, %d bank accounts, "
            "period %s to %s",
            len(securities), len(bank_accounts), period_from, period_to,
        )
        return statement
