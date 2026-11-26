"""Morgan Stanley (MSSB) importer.

Reads the exports from Morgan Stanley StockPlan Connect and turns them into a TaxStatement.
Point it at a folder holding any subset of these, as loose CSV files or as the zip archives
MSSB downloads them in; reports are recognised by their content, not their file name:

* Activity report: "Releases Report.csv" (GSU vests, net shares deposited after tax
  withholding) and "Withdrawals Report.csv" (sales, share transfers out, cash withdrawals).
* "Your Alphabet Stock Statement": the USD fair market value of every vest, matched to the
  releases by order number ("Purno").
* Vested share holdings: "Holdings Report.csv" + "Quote History.csv". The holdings report
  does not state its date, so the date is taken from the quote history downloaded with it
  (same zip archive or folder), after checking that the holdings' market values match those
  quotes. Typically one snapshot at the start and one at the end of the tax year.
* "Unvested Shares As At Date" is recognised but not used: unvested GSUs are not listed.

Prices in the releases and withdrawals reports are in USD when prefixed with "$". Otherwise
MSSB has converted them to the account's display currency at the exchange rate of the day
the report was run, which is useless for historical values. That rate is recovered from the
stock statement (release price / USD fair market value) and undone.

Balances come from the holdings snapshots where available and are carried forwards and
backwards with the activity. Without any snapshot they are reconstructed by walking the
activity from zero; when the activity removes more shares than it adds, the smallest opening
balance that keeps the position non-negative is assumed and a critical warning is added.

The exports contain no dividend, withholding tax or interest records. A critical warning on
the statement asks the taxpayer to verify the dividends taken from the Kursliste.

Data that cannot be interpreted safely raises ParsingError; data that is usable but needs
the taxpayer's attention adds a critical warning to the statement.
"""

import csv
import datetime
import logging
import os
import re
import statistics
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Callable, Dict, List, Optional, Tuple

from opensteuerauszug.config.models import MssbAccountSettings
from opensteuerauszug.importers.common import (
    CashAccountEntry,
    PositionHints,
    SecurityNameRegistry,
    SecurityPositionData,
    augment_list_of_bank_accounts,
    augment_list_of_securities,
    build_client,
    parse_swiss_canton,
    resolve_first_last_name,
)
from opensteuerauszug.importers.common.settlement import settlement_date
from opensteuerauszug.model.critical_warning import CriticalWarning, CriticalWarningCategory
from opensteuerauszug.model.ech0196 import (
    Institution,
    SecurityStock,
    TaxStatement,
)
from opensteuerauszug.model.position import SecurityPosition

logger = logging.getLogger(__name__)

BROKER_NAME = "Morgan Stanley"
WITHDRAWALS_REPORT_FILENAME = "Withdrawals Report.csv"
RELEASES_REPORT_FILENAME = "Releases Report.csv"
HOLDINGS_REPORT_FILENAME = "Holdings Report.csv"
QUOTE_HISTORY_FILENAME = "Quote History.csv"
DATE_FORMAT = "%d-%b-%Y"


class ReleaseColumn(StrEnum):
    VEST_DATE = "Vest Date"
    ORDER_NUMBER = "Order Number"
    PLAN = "Plan"
    TYPE = "Type"
    STATUS = "Status"
    PRICE = "Price"
    QUANTITY = "Quantity"
    NET_CASH_PROCEEDS = "Net Cash Proceeds"
    NET_SHARE_PROCEEDS = "Net Share Proceeds"
    TAX_PAYMENT_METHOD = "Tax Payment Method"


class WithdrawalColumn(StrEnum):
    EXECUTION_DATE = "Execution Date"
    ORDER_NUMBER = "Order Number"
    PLAN = "Plan"
    TYPE = "Type"
    ORDER_STATUS = "Order Status"
    PRICE = "Price"
    QUANTITY = "Quantity"
    NET_AMOUNT = "Net Amount"
    NET_SHARE_PROCEEDS = "Net Share Proceeds"
    TAX_PAYMENT_METHOD = "Tax Payment Method"


class StockStatementColumn(StrEnum):
    PURNO = "Purno"
    VESTING_DATE = "Vesting Date"
    GSUS_VESTED = "GSUs Vested"
    SHARES_DEPOSITED = "Shares Deposited"
    FAIR_MARKET_VALUE = "Fair Market Value"
    CURRENCY = "Currency"
    AWARD_NUMBER = "Award Number"


class HoldingsColumn(StrEnum):
    FUND_NAME = "Fund Name"
    NUMBER_OF_SHARES = "Number of Shares"
    MARKET_VALUE = "Market Value"


class QuoteColumn(StrEnum):
    FUND = "Fund"
    QUOTE_DATE = "Quote Date"
    PRICE = "Price"


class UnvestedColumn(StrEnum):
    AWARD_NAME = "Award Name"
    GRANT_NUMBER = "Employee Grant Number"
    VESTING_DATE = "Vesting Date"
    TOTAL_QUANTITY = "Total Quantity"


COLUMNS_RELEASE = [c.value for c in ReleaseColumn]
COLUMNS_WITHDRAWAL = [c.value for c in WithdrawalColumn]
COLUMNS_STOCK_STATEMENT = [c.value for c in StockStatementColumn]
COLUMNS_HOLDINGS = [c.value for c in HoldingsColumn]
COLUMNS_QUOTE = [c.value for c in QuoteColumn]
COLUMNS_UNVESTED = [c.value for c in UnvestedColumn]


class ReportKind(StrEnum):
    RELEASES = "releases"
    WITHDRAWALS = "withdrawals"
    STOCK_STATEMENT = "stock statement"
    HOLDINGS = "holdings"
    QUOTES = "quote history"
    UNVESTED = "unvested shares"
    # Duplicates of data in the reports above, or not used.
    WIRES = "withdrawal wires"
    NET_SHARES = "releases net shares"


IGNORED_KINDS = {ReportKind.WIRES, ReportKind.NET_SHARES, ReportKind.UNVESTED}
# Reports that must not be provided more than once.
UNIQUE_KINDS = {ReportKind.RELEASES, ReportKind.WITHDRAWALS, ReportKind.STOCK_STATEMENT}

KNOWN_FILENAMES = {
    RELEASES_REPORT_FILENAME: ReportKind.RELEASES,
    WITHDRAWALS_REPORT_FILENAME: ReportKind.WITHDRAWALS,
    HOLDINGS_REPORT_FILENAME: ReportKind.HOLDINGS,
    QUOTE_HISTORY_FILENAME: ReportKind.QUOTES,
}

CASH_PLAN = "Cash"
CASH_FUND_PREFIX = "Cash - "

KNOWN_SYMBOL_DICT = {
    "GSU Class A": "GOOGL",
    "GSU Class C": "GOOG",
    CASH_PLAN: "USD",
}
SYMBOL_DESCRIPTION = {
    symbol: plan for plan, symbol in KNOWN_SYMBOL_DICT.items() if plan != CASH_PLAN
}
# GSUs have been granted in Class C shares only since the 2022 split.
DEFAULT_GSU_SYMBOL = "GOOG"
KNOWN_SECURITY_SYMBOLS = set(SYMBOL_DESCRIPTION)
IMPORTER_SOURCE = "MssbImporter"


# Alphabet's 20:1 split was distributed on 15 July 2022. MSSB's own notice in the
# withdrawals report says activity on or before that date is shown in pre-split values;
# GSU vests are always shown post-split, so only withdrawals are adjusted.
@dataclass(frozen=True)
class StockSplit:
    symbol: str
    last_pre_split_date: datetime.date
    factor: int


STOCK_SPLIT_INFO = [
    StockSplit(symbol="GOOG", last_pre_split_date=datetime.date(2022, 7, 15), factor=20),
    StockSplit(symbol="GOOGL", last_pre_split_date=datetime.date(2022, 7, 15), factor=20),
]

# Relative spread tolerated between exchange rates that should be identical.
FX_CONSISTENCY_TOLERANCE = Decimal("0.005")
# US number format: optional sign and "$", comma thousands separators, "." decimals.
_US_NUMBER = re.compile(r"^-?\$?-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")


class ParsingError(Exception):
    pass


def _parse_decimal(value: str, column: str) -> Decimal:
    stripped = value.strip()
    if not _US_NUMBER.match(stripped):
        raise ParsingError(f"Invalid decimal in column '{column}': {value!r}")
    cleaned = stripped.replace(",", "").replace("$", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as err:
        raise ParsingError(f"Invalid decimal in column '{column}': {value!r}") from err


def _parse_date(value: str, column: str) -> datetime.date:
    try:
        return datetime.datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError as err:
        raise ParsingError(f"Invalid date in column '{column}': {value!r}") from err


def _is_usd(value: str) -> bool:
    return value.strip().lstrip("-").startswith("$")


def _fund_symbol(fund_name: str) -> str:
    """'GOOG - NASDAQ' -> 'GOOG'."""
    return fund_name.split(" - ")[0].strip()


def _spread(values: List[Decimal]) -> Decimal:
    lowest = min(values)
    if lowest <= 0:
        raise ParsingError(f"Expected positive values, got {lowest}")
    return (max(values) - lowest) / lowest


@dataclass
class _Source:
    """The text of one CSV report, wherever it came from."""

    label: str  # for messages, e.g. "Vested Share Holdings.12.zip/Holdings Report.csv"
    name: str  # base file name
    text: str
    # Holdings reports are dated by the quote history in the same group (zip or folder).
    group: str


@dataclass
class _Release:
    date: datetime.date
    symbol: str
    quantity: Decimal
    price: Optional[Decimal]
    price_is_usd: bool
    order_id: Optional[str]
    group: str


@dataclass
class _Withdrawal:
    date: datetime.date
    plan: str
    is_transfer: bool
    quantity: Decimal
    price: Decimal
    amount: Decimal
    is_usd: bool
    order_id: Optional[str]
    group: str


@dataclass
class _Vest:
    date: datetime.date
    quantity: Decimal
    fmv_usd: Decimal


@dataclass
class _Holding:
    fund_name: str
    quantity: Decimal
    market_value: Decimal
    currency: str


@dataclass
class _HoldingsGroup:
    label: str
    holdings: List[_Holding] = field(default_factory=list)
    quotes: Dict[str, Tuple[datetime.date, Decimal]] = field(default_factory=dict)


def classify_report(name: str, text: str) -> Optional[ReportKind]:
    """Recognise an MSSB report by its title line and column header."""
    lines = [line for line in text.splitlines()[:3] if line.strip()]
    rows = [next(csv.reader([line]), []) for line in lines]
    first = rows[0] if rows else []
    title = first[0] if first else ""
    headers = [set(c.strip() for c in row) for row in rows]

    def has(*columns: str) -> bool:
        return any(set(columns) <= h for h in headers)

    if title.strip() == "Quote History" or has(*COLUMNS_QUOTE):
        return ReportKind.QUOTES
    if "Holdings Report" in title or has(*COLUMNS_HOLDINGS):
        return ReportKind.HOLDINGS
    if "Restricted Shares Vesting" in title or has(*COLUMNS_UNVESTED):
        return ReportKind.UNVESTED
    if has(StockStatementColumn.PURNO, StockStatementColumn.FAIR_MARKET_VALUE):
        return ReportKind.STOCK_STATEMENT
    if has(ReleaseColumn.VEST_DATE, ReleaseColumn.NET_SHARE_PROCEEDS):
        return ReportKind.RELEASES
    if has(WithdrawalColumn.EXECUTION_DATE, WithdrawalColumn.NET_AMOUNT):
        return ReportKind.WITHDRAWALS
    if has("Date", "Symbol", "Net Cash Proceeds"):
        return ReportKind.WIRES
    if has("Date", "Plan", "Order Status", "Net Share Proceeds"):
        return ReportKind.NET_SHARES
    if "Stock Statement" in name:
        return ReportKind.STOCK_STATEMENT
    return KNOWN_FILENAMES.get(name)


def _decode(data: bytes) -> str:
    # utf-8-sig tolerates the BOM some MSSB exports start with.
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def collect_sources(paths: List[str]) -> List[_Source]:
    """Read CSV files and the CSV members of zip archives."""
    sources: List[_Source] = []
    for path in paths:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for member in sorted(archive.namelist()):
                    if member.endswith("/") or not member.lower().endswith(".csv"):
                        continue
                    sources.append(
                        _Source(
                            label=f"{os.path.basename(path)}/{member}",
                            name=os.path.basename(member),
                            text=_decode(archive.read(member)),
                            group=path,
                        )
                    )
        else:
            with open(path, "rb") as f:
                data = f.read()
            sources.append(
                _Source(
                    label=os.path.basename(path),
                    name=os.path.basename(path),
                    text=_decode(data),
                    group=os.path.dirname(os.path.abspath(path)),
                )
            )
    return sources


class MssbImporter:
    """Import Morgan Stanley CSV reports for a given tax period."""

    def __init__(
        self,
        period_from: datetime.date,
        period_to: datetime.date,
        account_settings_list: List[MssbAccountSettings],
    ) -> None:
        if len(account_settings_list) > 1:
            raise ParsingError(
                "Only one MSSB account is supported per run, but "
                f"{len(account_settings_list)} are configured. Run the importer once per account "
                "with --account."
            )
        self.period_from = period_from
        self.period_to = period_to
        self.account_settings_list = account_settings_list
        self._depot_id = (
            account_settings_list[0].account_number if account_settings_list else "MSSB"
        )
        self.base_currency = "USD"

        self.name_registry = SecurityNameRegistry()
        self.processed_security_positions: Dict[SecurityPosition, SecurityPositionData] = (
            defaultdict(lambda: SecurityPositionData({"stocks": [], "payments": []}))
        )
        # Dated cash movements on the MSSB cash account: sale proceeds in, withdrawals out.
        self.cash_events: List[Tuple[datetime.date, Decimal]] = []
        # Known cash balances at the start of a date, from holdings snapshots.
        self.cash_anchors: List[Tuple[datetime.date, Decimal]] = []
        # Sale proceeds traded within the period that settle after it (T+1).
        self.unsettled_proceeds: List[Tuple[datetime.date, Decimal]] = []
        self.critical_warnings: List[CriticalWarning] = []

        # Raw records, resolved into stocks and cash events in _build_statement.
        self._releases: List[_Release] = []
        self._withdrawals: List[_Withdrawal] = []
        self._vests: Dict[str, _Vest] = {}
        self._holdings_groups: Dict[str, _HoldingsGroup] = {}
        # Where each report came from, to reject duplicates and mixed downloads.
        self._sources_by_kind: Dict[ReportKind, List[_Source]] = defaultdict(list)

    def _warn(self, message: str, *args: object, identifier: Optional[str] = None) -> None:
        """Log a warning and add it to the statement as a critical warning."""
        text = message % args if args else message
        logger.warning(text)
        self.critical_warnings.append(
            CriticalWarning(
                category=CriticalWarningCategory.OTHER,
                message=text,
                source=IMPORTER_SOURCE,
                identifier=identifier,
            )
        )

    def import_dir(self, directory: str) -> TaxStatement:
        """Import every CSV report and zip archive in ``directory`` and its sub-folders.

        Each sub-folder (like each zip archive) is a group: a holdings report is dated by
        the quote history in the same group.
        """
        paths = []
        for root, dirs, files in os.walk(directory):
            dirs.sort()
            paths.extend(
                os.path.join(root, name)
                for name in sorted(files)
                if name.lower().endswith((".csv", ".zip"))
            )
        if not paths:
            raise ParsingError(f"No MSSB reports (CSV or zip) found in {directory}.")
        return self.import_files(*paths)

    def import_files(self, *files: str) -> TaxStatement:
        """Import CSV reports and zip archives of CSV reports."""
        for source in collect_sources(list(files)):
            kind = classify_report(source.name, source.text)
            if kind is None:
                logger.warning("Ignoring unrecognised MSSB file: %s", source.label)
                continue
            if kind in IGNORED_KINDS:
                logger.info(
                    "Skipping %s (%s: duplicated elsewhere or not used).", source.label, kind
                )
                continue
            if kind in UNIQUE_KINDS and self._sources_by_kind[kind]:
                raise ParsingError(
                    f"Found the MSSB {kind} report twice: "
                    f"{self._sources_by_kind[kind][0].label} and {source.label}. "
                    "Keep only one copy (for example either the zip archive or the extracted "
                    "files) so that no activity is counted twice."
                )
            logger.info("Reading %s as %s.", source.label, kind)
            self._sources_by_kind[kind].append(source)
            self._process_source(kind, source)

        found = set(self._sources_by_kind)
        if not found & {ReportKind.RELEASES, ReportKind.WITHDRAWALS, ReportKind.STOCK_STATEMENT}:
            raise ParsingError(
                "No MSSB activity found: provide at least the releases and withdrawals reports."
            )
        for kind, consequence in (
            (ReportKind.RELEASES, "vests are taken from the stock statement only"),
            (ReportKind.WITHDRAWALS, "sales and transfers out are not included"),
        ):
            if kind not in found:
                self._warn("No MSSB %s report was provided: %s.", kind, consequence)
        if ReportKind.HOLDINGS not in found:
            logger.info(
                "No MSSB holdings report provided: balances are reconstructed from the activity."
            )
        return self._build_statement()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def _process_source(self, kind: ReportKind, source: _Source) -> None:
        if kind == ReportKind.RELEASES:
            rows = self._read_rows(source, COLUMNS_RELEASE)
            self._process_rows(
                source,
                rows,
                lambda row: self._process_release_row(source, row),
                ReleaseColumn.VEST_DATE,
            )
        elif kind == ReportKind.WITHDRAWALS:
            rows = self._read_rows(source, COLUMNS_WITHDRAWAL)
            self._process_rows(
                source,
                rows,
                lambda row: self._process_withdrawal_row(source, row),
                WithdrawalColumn.EXECUTION_DATE,
            )
        elif kind == ReportKind.STOCK_STATEMENT:
            rows = self._read_rows(
                source, COLUMNS_STOCK_STATEMENT, header_marker=StockStatementColumn.PURNO
            )
            self._process_rows(
                source, rows, self._process_stock_statement_row, StockStatementColumn.VESTING_DATE
            )
        elif kind == ReportKind.HOLDINGS:
            rows = self._read_rows(source, COLUMNS_HOLDINGS, header_marker=HoldingsColumn.FUND_NAME)
            group = self._holdings_group(source)
            if group.holdings:
                raise ParsingError(
                    f"{source.label}: more than one holdings report in the same folder or "
                    "archive; keep each one in the zip archive it was downloaded in."
                )
            self._process_rows(
                source,
                rows,
                lambda row: self._process_holdings_row(group, row),
                HoldingsColumn.NUMBER_OF_SHARES,
            )
            if not group.holdings:
                raise ParsingError(f"{source.label}: the holdings report has no holdings.")
        elif kind == ReportKind.QUOTES:
            rows = self._read_rows(source, COLUMNS_QUOTE, header_marker=QuoteColumn.FUND)
            group = self._holdings_group(source)
            if group.quotes:
                raise ParsingError(
                    f"{source.label}: more than one quote history in the same folder or archive."
                )
            self._process_rows(
                source,
                rows,
                lambda row: self._process_quote_row(group, row),
                QuoteColumn.QUOTE_DATE,
            )

    def _holdings_group(self, source: _Source) -> _HoldingsGroup:
        if source.group not in self._holdings_groups:
            self._holdings_groups[source.group] = _HoldingsGroup(label=source.label)
        return self._holdings_groups[source.group]

    def _read_rows(
        self, source: _Source, expected_columns: List[str], header_marker: Optional[str] = None
    ) -> List[dict]:
        """Read a CSV into dicts.

        ``header_marker`` names a column of the header line, for reports that start with a
        title line before the header.
        """
        lines = source.text.splitlines()

        if header_marker is not None:
            for start, line in enumerate(lines):
                if header_marker in [c.strip() for c in next(csv.reader([line]), [])]:
                    lines = lines[start:]
                    break

        reader = csv.DictReader(lines)
        if not reader.fieldnames:
            raise ParsingError(f"{source.label}: CSV doesn't have a header")
        fieldnames = [name.strip() for name in reader.fieldnames]
        missing = set(expected_columns) - set(fieldnames)
        if missing:
            raise ParsingError(f"CSV header mismatch in {source.label}: missing {sorted(missing)}")
        reader.fieldnames = fieldnames
        return list(reader)

    def _process_rows(
        self,
        source: _Source,
        rows: List[dict],
        handler: Callable[[dict], None],
        value_column: str,
    ) -> None:
        for idx, row in enumerate(rows):
            if self._is_blank(row):
                continue
            if self._is_free_text(row, value_column):
                logger.debug("%s row %d: skipping note: %s", source.label, idx, self._text(row))
                continue
            try:
                handler(row)
            except ParsingError as e:
                raise ParsingError(f"{source.label} row {idx}: {e}") from e

    @staticmethod
    def _text(row: dict) -> str:
        values: List[str] = []
        for v in row.values():
            if isinstance(v, list):
                values.extend(v)
            elif isinstance(v, str):
                values.append(v)
        return ",".join(v for v in values if v)

    # MSSB appends free-text notes to several reports (the stock split notice, footnotes,
    # definitions). The csv module splits them on their commas, so they show up as rows
    # whose first cell is a sentence. A row is only taken as a note when, in addition, its
    # ``value_column`` (a date or number in every data row) holds no date or number, so a
    # data row with a malformed value is still reported as an error.
    @staticmethod
    def _is_free_text(row: dict, value_column: str) -> bool:
        first = next(iter(row.values()), None)
        if not isinstance(first, str) or " " not in first.strip():
            return False
        value = row.get(value_column)
        if not isinstance(value, str) or not value.strip():
            return True
        value = value.strip()
        if _US_NUMBER.match(value):
            return False
        try:
            datetime.datetime.strptime(value, DATE_FORMAT)
        except ValueError:
            return True
        return False

    @staticmethod
    def _is_blank(row: dict) -> bool:
        return not any(isinstance(v, str) and v.strip() for v in row.values())

    def _process_release_row(self, source: _Source, row: dict) -> None:
        plan = row[ReleaseColumn.PLAN]

        if row[ReleaseColumn.TYPE] != "Release":
            raise ParsingError(f"Unknown type: {row[ReleaseColumn.TYPE]}")

        status = row[ReleaseColumn.STATUS]
        if status not in {"Complete", "Staged"}:
            raise ParsingError(f"Unknown status: {status}")

        price_raw = row[ReleaseColumn.PRICE]
        if not price_raw:
            raise ParsingError("Price is empty")

        if plan not in KNOWN_SYMBOL_DICT or plan == CASH_PLAN:
            raise ParsingError(f"Unknown plan: {plan}")

        # Net Share Proceeds is what lands in the account after shares withheld for tax.
        quantity = _parse_decimal(
            row[ReleaseColumn.NET_SHARE_PROCEEDS], ReleaseColumn.NET_SHARE_PROCEEDS
        )
        vested = _parse_decimal(row[ReleaseColumn.QUANTITY], ReleaseColumn.QUANTITY)
        price = _parse_decimal(price_raw, ReleaseColumn.PRICE)
        net_cash = _parse_decimal(
            row[ReleaseColumn.NET_CASH_PROCEEDS] or "0", ReleaseColumn.NET_CASH_PROCEEDS
        )
        date = _parse_date(row[ReleaseColumn.VEST_DATE], ReleaseColumn.VEST_DATE)

        if quantity <= 0:
            raise ParsingError(f"Expected positive Net Share Proceeds, got {quantity}")
        if vested < quantity:
            raise ParsingError(
                f"Net Share Proceeds ({quantity}) exceed the vested Quantity ({vested})"
            )
        if price <= 0:
            raise ParsingError(f"Expected a positive price, got {price}")
        if net_cash != Decimal(0):
            raise ParsingError(
                f"Non-zero Net Cash Proceeds: {row[ReleaseColumn.NET_CASH_PROCEEDS]}"
            )

        if status == "Staged":
            self._warn(
                "MSSB release on %s (%s) is still 'Staged'; it is counted as delivered. Check "
                "that the shares arrived.",
                date,
                plan,
            )

        self._releases.append(
            _Release(
                date=date,
                symbol=KNOWN_SYMBOL_DICT[plan],
                quantity=quantity,
                price=price,
                price_is_usd=_is_usd(price_raw),
                order_id=row[ReleaseColumn.ORDER_NUMBER] or None,
                group=source.group,
            )
        )

    def _process_withdrawal_row(self, source: _Source, row: dict) -> None:
        plan = row[WithdrawalColumn.PLAN]
        # An empty type is a share transfer to another broker.
        tx_type = row[WithdrawalColumn.TYPE]

        if tx_type not in {"Sale", ""}:
            raise ParsingError(f"Unknown type: {tx_type}")

        if row[WithdrawalColumn.ORDER_STATUS] != "Complete":
            raise ParsingError(f"Unknown status: {row[WithdrawalColumn.ORDER_STATUS]}")

        price_raw = row[WithdrawalColumn.PRICE]
        if not price_raw:
            raise ParsingError("Price is empty")

        if plan not in KNOWN_SYMBOL_DICT:
            raise ParsingError(f"Unknown plan: {plan}")

        # Withdrawals are reported with a negative quantity, which is also the eCH sign
        # convention for a disposal.
        quantity = _parse_decimal(row[WithdrawalColumn.QUANTITY], WithdrawalColumn.QUANTITY)
        if quantity >= 0:
            raise ParsingError(f"Expected a negative withdrawal quantity, got {quantity}")
        price = _parse_decimal(price_raw, WithdrawalColumn.PRICE)
        if price < 0:
            raise ParsingError(f"Expected a non-negative price, got {price}")
        net_amount_raw = row[WithdrawalColumn.NET_AMOUNT].strip()
        if plan == CASH_PLAN and not net_amount_raw:
            raise ParsingError("Net Amount is empty for Cash plan")
        amount = (
            _parse_decimal(net_amount_raw, WithdrawalColumn.NET_AMOUNT)
            if net_amount_raw
            else Decimal(0)
        )
        if amount < 0:
            raise ParsingError(f"Expected a non-negative Net Amount, got {amount}")
        net_shares_raw = row[WithdrawalColumn.NET_SHARE_PROCEEDS].strip()
        if net_shares_raw and _parse_decimal(
            net_shares_raw, WithdrawalColumn.NET_SHARE_PROCEEDS
        ) != Decimal(0):
            raise ParsingError(f"Unexpected Net Share Proceeds on a withdrawal: {net_shares_raw}")
        date = _parse_date(row[WithdrawalColumn.EXECUTION_DATE], WithdrawalColumn.EXECUTION_DATE)

        is_transfer = False
        if plan != CASH_PLAN:
            if tx_type == "":
                if amount != Decimal(0):
                    raise ParsingError(
                        f"Withdrawal without a type has a Net Amount ({net_amount_raw}); "
                        "expected a share transfer without proceeds."
                    )
                is_transfer = True
            elif amount == Decimal(0):
                self._warn(
                    "MSSB sale of %s %s on %s has no Net Amount; it is treated as a transfer "
                    "out without proceeds.",
                    -quantity,
                    plan,
                    date,
                )
                is_transfer = True

        self._withdrawals.append(
            _Withdrawal(
                date=date,
                plan=plan,
                is_transfer=is_transfer,
                quantity=quantity,
                price=price,
                amount=amount,
                is_usd=_is_usd(price_raw),
                order_id=row[WithdrawalColumn.ORDER_NUMBER] or None,
                group=source.group,
            )
        )

    def _process_stock_statement_row(self, row: dict) -> None:
        currency = row[StockStatementColumn.CURRENCY].strip()
        if currency != "USD":
            raise ParsingError(f"Unexpected currency: {currency!r}")
        purno = row[StockStatementColumn.PURNO].strip()
        if not purno:
            raise ParsingError("Purno is empty")
        if purno in self._vests:
            raise ParsingError(f"Purno {purno} appears twice")
        fmv_raw = row[StockStatementColumn.FAIR_MARKET_VALUE]
        if not _is_usd(fmv_raw):
            raise ParsingError(f"Expected a USD fair market value, got {fmv_raw!r}")
        fmv = _parse_decimal(fmv_raw, StockStatementColumn.FAIR_MARKET_VALUE)
        if fmv <= 0:
            raise ParsingError(f"Expected a positive fair market value, got {fmv}")
        self._vests[purno] = _Vest(
            date=_parse_date(
                row[StockStatementColumn.VESTING_DATE], StockStatementColumn.VESTING_DATE
            ),
            quantity=_parse_decimal(
                row[StockStatementColumn.SHARES_DEPOSITED], StockStatementColumn.SHARES_DEPOSITED
            ),
            fmv_usd=fmv,
        )

    def _process_holdings_row(self, group: _HoldingsGroup, row: dict) -> None:
        fund_name = row[HoldingsColumn.FUND_NAME].strip()
        if not fund_name.startswith(CASH_FUND_PREFIX) and (
            _fund_symbol(fund_name) not in KNOWN_SECURITY_SYMBOLS
        ):
            raise ParsingError(f"Unknown fund: {fund_name!r}")
        if any(h.fund_name == fund_name for h in group.holdings):
            raise ParsingError(f"Fund {fund_name!r} is listed twice")
        quantity = _parse_decimal(
            row[HoldingsColumn.NUMBER_OF_SHARES], HoldingsColumn.NUMBER_OF_SHARES
        )
        market_value = _parse_decimal(row[HoldingsColumn.MARKET_VALUE], HoldingsColumn.MARKET_VALUE)
        if quantity < 0 or market_value < 0:
            raise ParsingError(f"Negative holding for {fund_name!r}")
        group.holdings.append(
            _Holding(
                fund_name=fund_name,
                quantity=quantity,
                market_value=market_value,
                # The unnamed column after Market Value holds its currency.
                currency=(row.get("") or "").strip(),
            )
        )

    def _process_quote_row(self, group: _HoldingsGroup, row: dict) -> None:
        price_raw = row[QuoteColumn.PRICE]
        if not _is_usd(price_raw):
            raise ParsingError(f"Expected a USD price, got {price_raw!r}")
        fund = row[QuoteColumn.FUND].strip()
        if fund in group.quotes:
            raise ParsingError(f"Fund {fund!r} is quoted twice")
        group.quotes[fund] = (
            _parse_date(row[QuoteColumn.QUOTE_DATE], QuoteColumn.QUOTE_DATE),
            _parse_decimal(price_raw, QuoteColumn.PRICE),
        )

    # ------------------------------------------------------------------
    # Resolving
    # ------------------------------------------------------------------

    def _make_sec_pos(self, symbol: str) -> SecurityPosition:
        description = SYMBOL_DESCRIPTION.get(symbol, symbol)
        sec_pos = SecurityPosition(depot=self._depot_id, symbol=symbol, description=description)
        self.name_registry.update(sec_pos, description, 5)
        return sec_pos

    def _add_stock(self, symbol: str, stock: SecurityStock) -> None:
        self.processed_security_positions[self._make_sec_pos(symbol)]["stocks"].append(stock)

    def _report_fx_rate(self) -> Optional[Decimal]:
        """Display-currency units per USD that MSSB used for non-USD report prices."""
        ratios = [
            r.price / self._vests[r.order_id].fmv_usd
            for r in self._releases
            if not r.price_is_usd and r.price and r.order_id in self._vests
        ]
        if not ratios:
            return None
        if _spread(ratios) > FX_CONSISTENCY_TOLERANCE:
            self._warn(
                "MSSB release prices are not a constant multiple of the stock statement's USD "
                "fair market values; the report exchange rate cannot be recovered."
            )
            return None
        return Decimal(statistics.median(ratios))

    def _resolve_releases(self, fx: Optional[Decimal]) -> None:
        release_orders = set()
        for release in self._releases:
            vest = self._vests.get(release.order_id) if release.order_id else None
            price: Optional[Decimal]
            if vest is not None:
                release_orders.add(release.order_id)
                if vest.quantity != release.quantity or vest.date != release.date:
                    raise ParsingError(
                        f"Release {release.order_id}: the releases report says "
                        f"{release.quantity} shares on {release.date}, the stock statement says "
                        f"{vest.quantity} on {vest.date}. Check that both reports are complete "
                        "and from the same account."
                    )
                price = vest.fmv_usd
            elif release.price_is_usd:
                price = release.price
            elif fx is not None and release.price is not None:
                price = release.price / fx
            else:
                price = None

            self._add_stock(
                release.symbol,
                SecurityStock(
                    referenceDate=release.date,
                    mutation=True,
                    quantity=release.quantity,
                    unitPrice=price,
                    balanceCurrency=self.base_currency,
                    quotationType="PIECE",
                    orderId=release.order_id,
                    name="Release",
                ),
            )

        if any(
            not r.price_is_usd and r.order_id not in self._vests and fx is None
            for r in self._releases
        ):
            self._warn(
                "Some MSSB release prices are in your display currency, not USD, and the "
                "exchange rate cannot be recovered. Their unit prices are left empty; add the "
                "stock statement export to fill them."
            )

        # The stock statement alone is enough to know what vested.
        for purno, vest in self._vests.items():
            if purno in release_orders:
                continue
            if self._releases:
                self._warn(
                    "MSSB vest %s on %s is in the stock statement but not in the releases "
                    "report; adding it as %s.",
                    purno,
                    vest.date,
                    DEFAULT_GSU_SYMBOL,
                )
            self._add_stock(
                DEFAULT_GSU_SYMBOL,
                SecurityStock(
                    referenceDate=vest.date,
                    mutation=True,
                    quantity=vest.quantity,
                    unitPrice=vest.fmv_usd,
                    balanceCurrency=self.base_currency,
                    quotationType="PIECE",
                    orderId=purno,
                    name="Release",
                ),
            )

    def _resolve_withdrawals(self, fx: Optional[Decimal]) -> None:
        release_groups = {r.group for r in self._releases if not r.price_is_usd}
        for w in self._withdrawals:
            price, amount = w.price, w.amount
            if not w.is_usd:
                if fx is None:
                    if not w.is_transfer:
                        raise ParsingError(
                            f"Withdrawal on {w.date} is not in USD, and the exchange rate MSSB "
                            "used cannot be recovered. Add the stock statement export so the "
                            "rate can be derived."
                        )
                    price = None
                else:
                    if w.group not in release_groups:
                        raise ParsingError(
                            f"Withdrawal on {w.date} is not in USD, and the exchange rate was "
                            "recovered from a releases report of another download. Download "
                            "the releases and withdrawals reports together."
                        )
                    price, amount = price / fx, amount / fx

            if w.plan == CASH_PLAN:
                # Cash is quoted per USD, so the quantity is the USD amount that left the
                # account, whatever the display currency. A smaller Net Amount means fees.
                withdrawn = -w.quantity
                if abs(withdrawn - amount) > Decimal("0.01"):
                    self._warn(
                        "MSSB cash withdrawal on %s: %s %s left the account, but the net amount "
                        "is %s; the difference is probably a fee.",
                        w.date,
                        withdrawn,
                        self.base_currency,
                        amount.quantize(Decimal("0.01")),
                    )
                self.cash_events.append((w.date, w.quantity))
                continue

            quantity = w.quantity
            symbol = KNOWN_SYMBOL_DICT[w.plan]
            for split in STOCK_SPLIT_INFO:
                if symbol == split.symbol and w.date <= split.last_pre_split_date:
                    quantity *= split.factor
                    if price is not None:
                        price /= split.factor

            if not w.is_transfer:
                # Sale proceeds reach the MSSB cash account on the settlement date (T+1).
                settle = settlement_date(w.date)
                self.cash_events.append((settle, amount))
                if w.date <= self.period_to < settle:
                    self.unsettled_proceeds.append((w.date, amount))

            self._add_stock(
                symbol,
                SecurityStock(
                    referenceDate=w.date,
                    mutation=True,
                    quantity=quantity,
                    unitPrice=None if w.is_transfer else price,
                    balanceCurrency=self.base_currency,
                    quotationType="PIECE",
                    orderId=w.order_id,
                    name="Transfer Out" if w.is_transfer else "Sale",
                ),
            )

    def _holdings_date(self, group: _HoldingsGroup) -> datetime.date:
        """Date of a holdings snapshot, taken from the quote history downloaded with it."""
        if not group.quotes:
            raise ParsingError(
                f"{group.label} has no date of its own and no quote history was downloaded "
                "with it. Keep each holdings report in its zip archive (or sub-folder), "
                f"together with its '{QUOTE_HISTORY_FILENAME}'."
            )

        dates = {date for date, _ in group.quotes.values()}
        if len(dates) != 1:
            raise ParsingError(
                f"The quote history for {group.label} spans several dates "
                f"({', '.join(str(d) for d in sorted(dates))}), so it cannot date the holdings."
            )
        as_of = dates.pop()

        # Market value / (shares * USD quote) is the display-currency rate and must be the
        # same for every fund (and 1 for USD) if the holdings and quotes are for the same day.
        rates = []
        rate_currencies = []
        for holding in group.holdings:
            quote = group.quotes.get(holding.fund_name)
            if quote is None:
                raise ParsingError(
                    f"{group.label}: no quote for '{holding.fund_name}' in its quote history."
                )
            if holding.quantity and quote[1]:
                rate = holding.market_value / (holding.quantity * quote[1])
                if rate <= 0:
                    raise ParsingError(
                        f"{group.label}: market value of '{holding.fund_name}' is zero."
                    )
                if holding.currency == "USD" and abs(rate - 1) > FX_CONSISTENCY_TOLERANCE:
                    raise ParsingError(
                        f"{group.label}: market value of '{holding.fund_name}' does not match "
                        "its quote, so the holdings and quotes are for different dates."
                    )
                rates.append(rate)
                rate_currencies.append(holding.currency)
        if len(rates) > 1 and _spread(rates) > FX_CONSISTENCY_TOLERANCE:
            raise ParsingError(
                f"Market values in {group.label} do not match its quote history, so the two "
                "are probably for different dates."
            )
        if len(rates) == 1 and rate_currencies[0] != "USD":
            self._warn(
                "The MSSB holdings in %s have a single priced fund, so it cannot be verified "
                "that they are as at %s, the date of the quote history next to them.",
                group.label,
                as_of,
            )
        return as_of

    def _snapshot_reference_date(self, as_of: datetime.date) -> datetime.date:
        """Holdings are as at the end of ``as_of``, i.e. the start of the next day.

        Balances are dated at the start of a day. With no activity on ``as_of`` itself the
        start of that day is equivalent, and is used when it is a period boundary (a
        snapshot "as at 1 January" then becomes the opening balance).
        """
        next_day = as_of + timedelta(days=1)
        activity_on_day = (
            any(r.date == as_of for r in self._releases)
            or any(w.date == as_of for w in self._withdrawals)
            or any(v.date == as_of for v in self._vests.values())
        )
        if not activity_on_day and as_of == self.period_from:
            return as_of
        return next_day

    def _resolve_holdings(self) -> None:
        snapshot_dates: Dict[datetime.date, str] = {}
        for group in self._holdings_groups.values():
            if not group.holdings:
                if group.quotes:
                    logger.warning("Ignoring %s: no holdings report next to it.", group.label)
                continue
            as_of = self._holdings_date(group)
            for split in STOCK_SPLIT_INFO:
                if as_of <= split.last_pre_split_date:
                    raise ParsingError(
                        f"{group.label} is as at {as_of}, before the {split.symbol} stock split "
                        "on 15 July 2022; holdings before the split are not supported."
                    )
            reference_date = self._snapshot_reference_date(as_of)
            if reference_date in snapshot_dates:
                raise ParsingError(
                    f"{group.label} and {snapshot_dates[reference_date]} are both holdings as "
                    f"at {as_of}; keep only one."
                )
            snapshot_dates[reference_date] = group.label
            logger.info("Using MSSB holdings as at %s (%s).", as_of, group.label)

            cash_seen = False
            for holding in group.holdings:
                if holding.fund_name.startswith(CASH_FUND_PREFIX):
                    currency = holding.fund_name[len(CASH_FUND_PREFIX) :].strip()
                    if currency != self.base_currency:
                        raise ParsingError(f"Unsupported cash currency in holdings: {currency}")
                    self.cash_anchors.append((reference_date, holding.quantity))
                    cash_seen = True
                    continue
                self._add_stock(
                    _fund_symbol(holding.fund_name),
                    SecurityStock(
                        referenceDate=reference_date,
                        mutation=False,
                        quantity=holding.quantity,
                        balanceCurrency=self.base_currency,
                        quotationType="PIECE",
                        name="Holdings Report",
                    ),
                )
            if not cash_seen:
                # No cash line in a snapshot means no cash at that date.
                self.cash_anchors.append((reference_date, Decimal(0)))

        # A position missing from a snapshot was zero at that date.
        for sec_pos, data in self.processed_security_positions.items():
            for reference_date in snapshot_dates:
                if not any(
                    not s.mutation and s.referenceDate == reference_date for s in data["stocks"]
                ):
                    data["stocks"].append(
                        SecurityStock(
                            referenceDate=reference_date,
                            mutation=False,
                            quantity=Decimal(0),
                            balanceCurrency=self.base_currency,
                            quotationType="PIECE",
                            name="Holdings Report",
                        )
                    )

    def _cash_balance_at(self, target: datetime.date) -> Optional[Decimal]:
        """Cash balance at the start of ``target``."""
        if self.cash_anchors:
            before = [a for a in self.cash_anchors if a[0] <= target]
            if before:
                anchor_date, anchor = max(before)
                return anchor + sum(
                    (a for d, a in self.cash_events if anchor_date <= d < target), Decimal(0)
                )
            anchor_date, anchor = min(self.cash_anchors)
            return anchor - sum(
                (a for d, a in self.cash_events if target <= d < anchor_date), Decimal(0)
            )

        if not self.cash_events:
            return None
        opening = _infer_opening_balance(self.cash_events)
        if opening:
            self._warn(
                "MSSB cash account: withdrawals exceed the proceeds in the export; assuming an "
                "opening cash balance of %s %s. Add the vested share holdings reports to use "
                "the real figure.",
                opening,
                self.base_currency,
            )
        return opening + sum((a for d, a in self.cash_events if d < target), Decimal(0))

    def _reconcile_unsettled_with_snapshot(
        self, period_end_plus_one: datetime.date, unsettled: Decimal
    ) -> None:
        """Make a year-end cash snapshot exclude sale proceeds that settle after the period.

        Whether MSSB's holdings report already counts proceeds of a trade that has not
        settled yet is not documented. When an earlier snapshot is available, the year-end
        cash is compared with the settled cash computed from it: if it matches settled
        cash plus the unsettled proceeds, the proceeds are taken out of the snapshot so
        they are not counted twice.
        """
        end = [a for a in self.cash_anchors if a[0] == period_end_plus_one]
        if not end:
            return
        snapshot = end[0][1]
        earlier = [a for a in self.cash_anchors if a[0] < period_end_plus_one]
        if not earlier:
            self._warn(
                "MSSB sale proceeds of %s %s settle after %s and are reported as unsettled. "
                "Check that the year-end cash in the holdings report (%s %s) does not already "
                "include them.",
                unsettled,
                self.base_currency,
                self.period_to,
                snapshot,
                self.base_currency,
            )
            return
        anchor_date, anchor = max(earlier)
        settled = anchor + sum(
            (a for d, a in self.cash_events if anchor_date <= d < period_end_plus_one),
            Decimal(0),
        )
        if abs(snapshot - settled - unsettled) < abs(snapshot - settled):
            logger.info(
                "The MSSB year-end cash (%s %s) includes %s %s of unsettled sale proceeds; "
                "they are reported separately.",
                snapshot,
                self.base_currency,
                unsettled,
                self.base_currency,
            )
            self.cash_anchors = [
                (d, v - unsettled if d == period_end_plus_one else v) for d, v in self.cash_anchors
            ]

    def _check_cash_anchors(self) -> None:
        anchors = sorted(self.cash_anchors)
        for (d1, v1), (d2, v2) in zip(anchors, anchors[1:]):
            expected = v1 + sum((a for d, a in self.cash_events if d1 <= d < d2), Decimal(0))
            difference = v2 - expected
            if difference > 0:
                # Dividends and interest are credited to cash but are not in any MSSB export.
                logger.info(
                    "MSSB cash grew by %s %s between the holdings snapshots on %s and %s "
                    "without matching sales (most likely dividends or interest).",
                    difference,
                    self.base_currency,
                    d1,
                    d2,
                )
            elif difference < 0:
                self._warn(
                    "MSSB cash shrank by %s %s between the holdings snapshots on %s and %s "
                    "without matching withdrawals; some activity or fees are missing from the "
                    "exports.",
                    -difference,
                    self.base_currency,
                    d1,
                    d2,
                )

    def _build_statement(self) -> TaxStatement:
        statement = TaxStatement(
            minorVersion=1,
            periodFrom=self.period_from,
            periodTo=self.period_to,
            taxPeriod=self.period_from.year,
            listOfSecurities=None,
            listOfBankAccounts=None,
        )
        statement.institution = Institution(name=BROKER_NAME)

        settings = self.account_settings_list[0] if self.account_settings_list else None
        if settings:
            first_name, last_name = resolve_first_last_name(
                full_name=getattr(settings, "full_name", None)
            )
            canton = parse_swiss_canton(getattr(settings, "canton", None))
            if canton:
                statement.canton = canton
            client_obj = build_client(
                client_number=settings.account_number,
                first_name=first_name,
                last_name=last_name,
            )
            if client_obj is not None:
                statement.client = [client_obj]

        fx = self._report_fx_rate()
        self._resolve_releases(fx)
        self._resolve_withdrawals(fx)
        self._resolve_holdings()

        for split in STOCK_SPLIT_INFO:
            if self.period_from <= split.last_pre_split_date < self.period_to and any(
                p.symbol == split.symbol for p in self.processed_security_positions
            ):
                self._warn(
                    "The %s 20:1 stock split of July 2022 falls in this period. All %s "
                    "quantities are shown in post-split shares and the split itself is not "
                    "listed as a mutation; check the result carefully.",
                    split.symbol,
                    split.symbol,
                    identifier=split.symbol,
                )

        def _hints_for(sec_pos: SecurityPosition) -> PositionHints:
            return PositionHints(security_category="SHARE", country="US")

        for sec_pos, data in self.processed_security_positions.items():
            stocks = _aggregate_mssb_stocks(data["stocks"])
            if any(not s.mutation for s in stocks):
                _check_against_balances(sec_pos.symbol, stocks, self._warn)
            else:
                stocks = self._with_inferred_opening(sec_pos, stocks)
            data["stocks"] = stocks

        augment_list_of_securities(
            statement,
            self.processed_security_positions,
            name_registry=self.name_registry,
            hints_for=_hints_for,
            strict_consistency=False,
            assume_zero_if_no_balances=True,
            # Same-day mutations are already merged by _aggregate_mssb_stocks, which keeps
            # sales and transfers apart.
            aggregate_same_day_mutations=False,
        )

        period_end_plus_one = self.period_to + timedelta(days=1)
        unsettled = sum((a for _, a in self.unsettled_proceeds), Decimal(0))
        if unsettled:
            self._reconcile_unsettled_with_snapshot(period_end_plus_one, unsettled)
        self._check_cash_anchors()
        cash_balance = self._cash_balance_at(period_end_plus_one)
        if cash_balance is not None:
            if cash_balance < 0:
                self._warn(
                    "MSSB cash account ends the period at %s %s; some activity is missing.",
                    cash_balance,
                    self.base_currency,
                )
            if self.cash_anchors and not any(
                d == period_end_plus_one for d, _ in self.cash_anchors
            ):
                self._warn(
                    "MSSB cash at the period end is carried from a holdings snapshot on another "
                    "date. Dividends credited to cash are not in the MSSB exports; add the "
                    "vested share holdings report for the end of the tax year to get it exact."
                )
            cash_entry = CashAccountEntry(
                account_id=self._depot_id,
                currency=self.base_currency,
                closing_balance=cash_balance,
                payments=[],
                country="US",
                name=f"{self._depot_id} {self.base_currency}",
                number=f"{self._depot_id}-{self.base_currency}",
            )
            cash_entries = [cash_entry]
            if unsettled:
                dates = ", ".join(str(d) for d, _ in self.unsettled_proceeds)
                logger.info(
                    "MSSB sale proceeds of %s %s (sold on %s) settle after %s; reported as a "
                    "separate unsettled account.",
                    unsettled,
                    self.base_currency,
                    dates,
                    self.period_to,
                )
                cash_entries.append(
                    CashAccountEntry(
                        account_id=f"{self._depot_id} (Unsettled)",
                        currency=self.base_currency,
                        closing_balance=unsettled,
                        payments=[],
                        country="US",
                        name=f"{self._depot_id} {self.base_currency} (Unsettled)",
                        number=f"{self._depot_id}-{self.base_currency}-UNSETTLED",
                    )
                )
            augment_list_of_bank_accounts(statement, cash_entries)

        if self.processed_security_positions:
            self._warn(
                "The MSSB exports contain no dividend, withholding tax or interest records. "
                "Dividends are taken from the Kursliste, assuming 15% US withholding (a valid "
                "W-8BEN). Check them against your Form 1042-S and MSSB statements."
            )

        statement.critical_warnings.extend(self.critical_warnings)
        return statement

    def _with_inferred_opening(
        self, sec_pos: SecurityPosition, stocks: List[SecurityStock]
    ) -> List[SecurityStock]:
        opening = _infer_opening_balance([(s.referenceDate, s.quantity) for s in stocks])
        if not opening:
            return stocks
        first_date = min(stocks[0].referenceDate, self.period_from)
        self._warn(
            "%s: the MSSB export removes more shares than it adds, so it does not start from "
            "an empty account. Assuming %s shares held before %s. Add the MSSB vested share "
            "holdings report to use the real figure.",
            sec_pos.symbol,
            opening,
            first_date,
            identifier=sec_pos.symbol,
        )
        return [
            SecurityStock(
                referenceDate=first_date,
                mutation=False,
                quantity=opening,
                balanceCurrency=self.base_currency,
                quotationType="PIECE",
            )
        ] + stocks


def _check_against_balances(
    symbol: Optional[str],
    stocks: List[SecurityStock],
    warn: Callable[..., None],
) -> None:
    """Warn when the activity does not connect the known balances."""
    balances = sorted((s for s in stocks if not s.mutation), key=lambda s: s.referenceDate)
    # Same-day additions before removals, as in _infer_opening_balance.
    mutations = sorted(
        (s for s in stocks if s.mutation), key=lambda s: (s.referenceDate, s.quantity < 0)
    )

    for b1, b2 in zip(balances, balances[1:]):
        expected = b1.quantity + sum(
            (
                m.quantity
                for m in mutations
                if b1.referenceDate <= m.referenceDate < b2.referenceDate
            ),
            Decimal(0),
        )
        if expected != b2.quantity:
            warn(
                "%s: the MSSB activity between the holdings on %s (%s) and %s (%s) adds up to "
                "%s; some activity is missing from the exports.",
                symbol,
                b1.referenceDate,
                b1.quantity,
                b2.referenceDate,
                b2.quantity,
                expected,
                identifier=symbol,
            )

    first, last = balances[0], balances[-1]
    running = last.quantity
    for m in mutations:
        if m.referenceDate >= last.referenceDate:
            running += m.quantity
            if running < 0:
                warn(
                    "%s: MSSB activity after the %s holdings takes the position negative on %s.",
                    symbol,
                    last.referenceDate,
                    m.referenceDate,
                    identifier=symbol,
                )
                break
    running = first.quantity
    for m in reversed(mutations):
        if m.referenceDate < first.referenceDate:
            running -= m.quantity
            if running < 0:
                warn(
                    "%s: MSSB activity before the %s holdings implies a negative position "
                    "before %s.",
                    symbol,
                    first.referenceDate,
                    m.referenceDate,
                    identifier=symbol,
                )
                break


def _infer_opening_balance(events: List[Tuple[datetime.date, Decimal]]) -> Decimal:
    """Smallest opening balance that keeps the running balance non-negative.

    Same-day additions are applied before removals, since a vest and a sale on the
    same day can appear in either order in the exports.
    """
    running = Decimal(0)
    lowest = Decimal(0)
    for _, amount in sorted(events, key=lambda e: (e[0], e[1] < 0)):
        running += amount
        lowest = min(lowest, running)
    return -lowest


def _aggregate_mssb_stocks(stocks: List[SecurityStock]) -> List[SecurityStock]:
    """Collapse same-day, same-type mutations with the same price into one entry.

    Several grants usually vest on the same day, each with its own order number.
    """
    grouped_mutations: Dict[tuple, SecurityStock] = {}
    other_entries = []

    for stock in stocks:
        if not stock.mutation:
            other_entries.append(stock)
            continue

        key = (stock.referenceDate, stock.name, stock.unitPrice, stock.balanceCurrency)
        if key not in grouped_mutations:
            grouped_mutations[key] = SecurityStock(
                referenceDate=stock.referenceDate,
                mutation=True,
                quantity=stock.quantity,
                unitPrice=stock.unitPrice,
                name=stock.name,
                orderId=stock.orderId,
                balanceCurrency=stock.balanceCurrency,
                quotationType=stock.quotationType,
            )
        else:
            existing = grouped_mutations[key]
            existing.quantity += stock.quantity
            if existing.orderId and stock.orderId and stock.orderId != existing.orderId:
                existing.orderId = f"{existing.orderId},{stock.orderId}"
            elif stock.orderId:
                existing.orderId = stock.orderId

    result = list(grouped_mutations.values()) + other_entries
    result.sort(key=lambda s: (s.referenceDate, s.mutation))
    return result
