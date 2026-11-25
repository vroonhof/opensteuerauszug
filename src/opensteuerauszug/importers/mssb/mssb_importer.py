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
* "Unvested Shares As At Date": the remaining vesting schedule, listed as a pro memoria
  position without tax value.

Prices in the releases and withdrawals reports are in USD when prefixed with "$". Otherwise
MSSB has converted them to the account's display currency at the exchange rate of the day
the report was run, which is useless for historical values. That rate is recovered from the
stock statement (release price / USD fair market value) and undone.

Balances come from the holdings snapshots where available and are carried forwards and
backwards with the activity. Without any snapshot they are reconstructed by walking the
activity from zero; when the activity removes more shares than it adds, the smallest opening
balance that keeps the position non-negative is assumed and a warning is logged.
"""

import csv
import datetime
import logging
import os
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
from opensteuerauszug.model.ech0196 import (
    Depot,
    DepotNumber,
    Institution,
    ListOfSecurities,
    Security,
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
    # Duplicates of data in the reports above.
    WIRES = "withdrawal wires"
    NET_SHARES = "releases net shares"


IGNORED_KINDS = {ReportKind.WIRES, ReportKind.NET_SHARES}

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
UNVESTED_SECURITY_NAME = "GSU Class C, unvested (pro memoria)"

# Alphabet's 20:1 split was distributed on 15 July 2022. MSSB's own notice in the
# withdrawals report says activity on or before that date is shown in pre-split values;
# GSU vests are always shown post-split, so only withdrawals are adjusted.
STOCK_SPLIT_INFO = [
    {"symbol": "GOOG", "last_pre_split_date": datetime.date(2022, 7, 15), "factor": 20},
    {"symbol": "GOOGL", "last_pre_split_date": datetime.date(2022, 7, 15), "factor": 20},
]

# Relative spread tolerated between exchange rates that should be identical.
FX_CONSISTENCY_TOLERANCE = Decimal("0.005")
# GSUs vest monthly; a schedule whose first vest is further out than this after the
# period end was probably exported as at a later date.
UNVESTED_MAX_GAP = timedelta(days=62)


class ParsingError(Exception):
    pass


def _parse_decimal(value: str, column: str) -> Decimal:
    cleaned = value.replace(",", "").replace("$", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation as err:
        raise ParsingError(f"Invalid decimal in column '{column}': {value!r}") from err


def _parse_date(value: str, column: str) -> datetime.date:
    try:
        return datetime.datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError as err:
        raise ParsingError(f"Invalid date in column '{column}': {value!r}") from err


def _looks_like_date(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        datetime.datetime.strptime(value.strip(), DATE_FORMAT)
    except ValueError:
        return False
    return True


def _is_usd(value: str) -> bool:
    return value.strip().startswith("$")


def _fund_symbol(fund_name: str) -> str:
    """'GOOG - NASDAQ' -> 'GOOG'."""
    return fund_name.split(" - ")[0].strip()


def _spread(values: List[Decimal]) -> Decimal:
    return (max(values) - min(values)) / min(values)


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


@dataclass
class _Vest:
    date: datetime.date
    quantity: Decimal
    fmv_usd: Decimal
    award_number: Optional[str]


@dataclass
class _Holding:
    fund_name: str
    quantity: Decimal
    market_value: Decimal


@dataclass
class _HoldingsGroup:
    label: str
    holdings: List[_Holding] = field(default_factory=list)
    quotes: Dict[str, Tuple[datetime.date, Decimal]] = field(default_factory=dict)


@dataclass
class _UnvestedTranche:
    vesting_date: datetime.date
    quantity: Decimal
    grant_number: Optional[str]


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

        # Raw records, resolved into stocks and cash events in _build_statement.
        self._releases: List[_Release] = []
        self._withdrawals: List[_Withdrawal] = []
        self._vests: Dict[str, _Vest] = {}
        self._holdings_groups: Dict[str, _HoldingsGroup] = {}
        self._unvested: List[_UnvestedTranche] = []
        self._unvested_label: Optional[str] = None

    def import_dir(self, directory: str) -> TaxStatement:
        paths = sorted(
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith((".csv", ".zip"))
            and os.path.isfile(os.path.join(directory, name))
        )
        if not paths:
            logger.warning("No MSSB reports (CSV or zip) found in %s.", directory)
        return self.import_files(*paths)

    def import_files(self, *files: str) -> TaxStatement:
        """Import CSV reports and zip archives of CSV reports."""
        found = set()
        for source in collect_sources(list(files)):
            kind = classify_report(source.name, source.text)
            if kind is None:
                logger.warning("Ignoring unrecognised MSSB file: %s", source.label)
                continue
            if kind in IGNORED_KINDS:
                logger.debug("Skipping %s (%s, duplicated elsewhere).", source.label, kind)
                continue
            logger.info("Reading %s as %s.", source.label, kind)
            found.add(kind)
            self._process_source(kind, source)

        for kind, advice in (
            (ReportKind.RELEASES, "vests are taken from the stock statement only"),
            (ReportKind.WITHDRAWALS, "sales and transfers out are unknown"),
            (ReportKind.HOLDINGS, "balances are reconstructed from the activity alone"),
            (ReportKind.UNVESTED, "no pro memoria entry for unvested shares"),
        ):
            if kind not in found:
                logger.info("No MSSB %s report provided: %s.", kind, advice)
        return self._build_statement()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def _process_source(self, kind: ReportKind, source: _Source) -> None:
        if kind == ReportKind.RELEASES:
            rows = self._read_rows(source, COLUMNS_RELEASE)
            self._process_rows(source, rows, self._process_release_row)
        elif kind == ReportKind.WITHDRAWALS:
            rows = self._read_rows(source, COLUMNS_WITHDRAWAL)
            self._process_rows(source, rows, self._process_withdrawal_row)
        elif kind == ReportKind.STOCK_STATEMENT:
            rows = self._read_rows(
                source, COLUMNS_STOCK_STATEMENT, header_marker=StockStatementColumn.PURNO
            )
            # The table is followed by free-text footnotes; vest rows are the ones with a date.
            rows = [r for r in rows if _looks_like_date(r.get(StockStatementColumn.VESTING_DATE))]
            self._process_rows(source, rows, self._process_stock_statement_row)
        elif kind == ReportKind.HOLDINGS:
            rows = self._read_rows(source, COLUMNS_HOLDINGS, header_marker=HoldingsColumn.FUND_NAME)
            rows = [
                r
                for r in rows
                if r.get(HoldingsColumn.FUND_NAME) and r.get(HoldingsColumn.NUMBER_OF_SHARES)
            ]
            group = self._holdings_group(source)
            if group.holdings:
                raise ParsingError(
                    f"{source.label}: more than one holdings report in the same folder or "
                    "archive; keep each one in the zip archive it was downloaded in."
                )
            self._process_rows(source, rows, lambda row: self._process_holdings_row(group, row))
        elif kind == ReportKind.QUOTES:
            rows = self._read_rows(source, COLUMNS_QUOTE, header_marker=QuoteColumn.FUND)
            group = self._holdings_group(source)
            self._process_rows(source, rows, lambda row: self._process_quote_row(group, row))
        elif kind == ReportKind.UNVESTED:
            rows = self._read_rows(
                source, COLUMNS_UNVESTED, header_marker=UnvestedColumn.GRANT_NUMBER
            )
            rows = [r for r in rows if _looks_like_date(r.get(UnvestedColumn.VESTING_DATE))]
            if self._unvested:
                raise ParsingError(f"{source.label}: more than one unvested shares report.")
            self._unvested_label = source.label
            self._process_rows(source, rows, self._process_unvested_row)

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
        self, source: _Source, rows: List[dict], handler: Callable[[dict], None]
    ) -> None:
        for idx, row in enumerate(rows):
            if self._is_blank(row) or self._is_notice(row):
                continue
            try:
                handler(row)
            except ParsingError as e:
                raise ParsingError(f"{source.label} row {idx}: {e}") from e

    # MSSB appends a free-text notice about the Alphabet stock split to the withdrawals
    # report. The csv module splits it on its commas, so it shows up as a bogus row.
    @staticmethod
    def _is_notice(row: dict) -> bool:
        row_str = ",".join([c for c in row.values() if isinstance(c, str) and c])
        return row_str.startswith("Please note")

    @staticmethod
    def _is_blank(row: dict) -> bool:
        return not any(isinstance(v, str) and v.strip() for v in row.values())

    def _process_release_row(self, row: dict) -> None:
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
        price = _parse_decimal(price_raw, ReleaseColumn.PRICE)
        net_cash = _parse_decimal(
            row[ReleaseColumn.NET_CASH_PROCEEDS] or "0", ReleaseColumn.NET_CASH_PROCEEDS
        )
        date = _parse_date(row[ReleaseColumn.VEST_DATE], ReleaseColumn.VEST_DATE)

        if net_cash != Decimal(0):
            raise ParsingError(
                f"Non-zero Net Cash Proceeds: {row[ReleaseColumn.NET_CASH_PROCEEDS]}"
            )

        if status == "Staged":
            logger.warning(
                "Release on %s (%s) is still 'Staged'; counting it as delivered.", date, plan
            )

        self._releases.append(
            _Release(
                date=date,
                symbol=KNOWN_SYMBOL_DICT[plan],
                quantity=quantity,
                price=price,
                price_is_usd=_is_usd(price_raw),
                order_id=row[ReleaseColumn.ORDER_NUMBER] or None,
            )
        )

    def _process_withdrawal_row(self, row: dict) -> None:
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
        if quantity > 0:
            raise ParsingError(f"Expected a negative withdrawal quantity, got {quantity}")
        price = _parse_decimal(price_raw, WithdrawalColumn.PRICE)
        net_amount_raw = row[WithdrawalColumn.NET_AMOUNT].strip()
        if plan == CASH_PLAN and not net_amount_raw:
            raise ParsingError("Net Amount is empty for Cash plan")
        amount = (
            _parse_decimal(net_amount_raw, WithdrawalColumn.NET_AMOUNT)
            if net_amount_raw
            else Decimal(0)
        )
        date = _parse_date(row[WithdrawalColumn.EXECUTION_DATE], WithdrawalColumn.EXECUTION_DATE)

        self._withdrawals.append(
            _Withdrawal(
                date=date,
                plan=plan,
                is_transfer=plan != CASH_PLAN and (tx_type == "" or amount == Decimal(0)),
                quantity=quantity,
                price=price,
                amount=amount,
                is_usd=_is_usd(price_raw),
                order_id=row[WithdrawalColumn.ORDER_NUMBER] or None,
            )
        )

    def _process_stock_statement_row(self, row: dict) -> None:
        currency = row[StockStatementColumn.CURRENCY].strip()
        if currency and currency != "USD":
            raise ParsingError(f"Unexpected currency: {currency}")
        purno = row[StockStatementColumn.PURNO].strip()
        if not purno:
            raise ParsingError("Purno is empty")
        self._vests[purno] = _Vest(
            date=_parse_date(
                row[StockStatementColumn.VESTING_DATE], StockStatementColumn.VESTING_DATE
            ),
            quantity=_parse_decimal(
                row[StockStatementColumn.SHARES_DEPOSITED], StockStatementColumn.SHARES_DEPOSITED
            ),
            fmv_usd=_parse_decimal(
                row[StockStatementColumn.FAIR_MARKET_VALUE], StockStatementColumn.FAIR_MARKET_VALUE
            ),
            award_number=row[StockStatementColumn.AWARD_NUMBER].strip() or None,
        )

    def _process_holdings_row(self, group: _HoldingsGroup, row: dict) -> None:
        group.holdings.append(
            _Holding(
                fund_name=row[HoldingsColumn.FUND_NAME].strip(),
                quantity=_parse_decimal(
                    row[HoldingsColumn.NUMBER_OF_SHARES], HoldingsColumn.NUMBER_OF_SHARES
                ),
                market_value=_parse_decimal(
                    row[HoldingsColumn.MARKET_VALUE], HoldingsColumn.MARKET_VALUE
                ),
            )
        )

    def _process_quote_row(self, group: _HoldingsGroup, row: dict) -> None:
        price_raw = row[QuoteColumn.PRICE]
        if not _is_usd(price_raw):
            raise ParsingError(f"Expected a USD price, got {price_raw!r}")
        group.quotes[row[QuoteColumn.FUND].strip()] = (
            _parse_date(row[QuoteColumn.QUOTE_DATE], QuoteColumn.QUOTE_DATE),
            _parse_decimal(price_raw, QuoteColumn.PRICE),
        )

    def _process_unvested_row(self, row: dict) -> None:
        award = row[UnvestedColumn.AWARD_NAME].strip()
        if award != "GSU":
            raise ParsingError(f"Unknown award type: {award}")
        self._unvested.append(
            _UnvestedTranche(
                vesting_date=_parse_date(
                    row[UnvestedColumn.VESTING_DATE], UnvestedColumn.VESTING_DATE
                ),
                quantity=_parse_decimal(
                    row[UnvestedColumn.TOTAL_QUANTITY], UnvestedColumn.TOTAL_QUANTITY
                ),
                grant_number=row[UnvestedColumn.GRANT_NUMBER].strip() or None,
            )
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
            logger.warning(
                "Release prices are not a constant multiple of the stock statement's USD fair "
                "market values; cannot recover the report exchange rate."
            )
            return None
        return Decimal(statistics.median(ratios))

    def _resolve_releases(self) -> None:
        release_orders = set()
        for release in self._releases:
            vest = self._vests.get(release.order_id) if release.order_id else None
            if vest is not None:
                release_orders.add(release.order_id)
                if vest.quantity != release.quantity or vest.date != release.date:
                    logger.warning(
                        "Release %s: releases report says %s shares on %s, stock statement "
                        "says %s on %s. Using the releases report.",
                        release.order_id,
                        release.quantity,
                        release.date,
                        vest.quantity,
                        vest.date,
                    )
                price: Optional[Decimal] = vest.fmv_usd
            elif release.price_is_usd:
                price = release.price
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
            r.price is not None and not r.price_is_usd and r.order_id not in self._vests
            for r in self._releases
        ):
            logger.warning(
                "Some release prices are in your MSSB display currency, not USD, and have no "
                "matching stock statement row. Their unit prices are left empty."
            )

        # The stock statement alone is enough to know what vested.
        for purno, vest in self._vests.items():
            if purno in release_orders:
                continue
            if self._releases:
                logger.warning(
                    "Vest %s on %s is in the stock statement but not in the releases report; "
                    "adding it as %s.",
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
                    price, amount = price / fx, amount / fx

            if w.plan == CASH_PLAN:
                self.cash_events.append((w.date, -amount))
                continue

            quantity = w.quantity
            symbol = KNOWN_SYMBOL_DICT[w.plan]
            for split in STOCK_SPLIT_INFO:
                if symbol == split["symbol"] and w.date <= split["last_pre_split_date"]:
                    quantity *= split["factor"]
                    if price is not None:
                        price /= split["factor"]

            if not w.is_transfer:
                # Sale proceeds are credited to the MSSB cash account.
                self.cash_events.append((w.date, amount))

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

    def _holdings_date(self, group: _HoldingsGroup) -> Optional[datetime.date]:
        """Date of a holdings snapshot, taken from the quote history downloaded with it."""
        if not group.quotes:
            logger.warning(
                "%s has no date of its own and no quote history was downloaded with it, so it "
                "is ignored. Keep each holdings report in its zip archive, together with its "
                "'%s'.",
                group.label,
                QUOTE_HISTORY_FILENAME,
            )
            return None

        dates = {date for date, _ in group.quotes.values()}
        if len(dates) != 1:
            logger.warning("Quote history for %s spans several dates; ignoring it.", group.label)
            return None

        # Market value / (shares * USD quote) is the display-currency rate and must be the
        # same for every fund if the holdings and quotes are for the same day.
        rates = []
        for holding in group.holdings:
            quote = group.quotes.get(holding.fund_name)
            if quote is None:
                logger.warning("No quote for '%s'; ignoring %s.", holding.fund_name, group.label)
                return None
            if holding.quantity and quote[1]:
                rates.append(holding.market_value / (holding.quantity * quote[1]))
        if rates and _spread(rates) > FX_CONSISTENCY_TOLERANCE:
            logger.warning(
                "Market values in %s do not match its quote history, so the two are probably "
                "for different dates; ignoring it.",
                group.label,
            )
            return None
        return dates.pop()

    def _snapshot_reference_date(self, as_of: datetime.date) -> datetime.date:
        """Holdings are as at the end of ``as_of``, i.e. the start of the next day.

        Balances are dated at the start of a day. With no activity on ``as_of`` itself the
        start of that day is equivalent, and is used when it is a period boundary (a
        snapshot "as at 1 January" then becomes the opening balance).
        """
        next_day = as_of + timedelta(days=1)
        activity_on_day = any(r.date == as_of for r in self._releases) or any(
            w.date == as_of for w in self._withdrawals
        )
        if not activity_on_day and as_of == self.period_from:
            return as_of
        return next_day

    def _resolve_holdings(self) -> None:
        symbols_seen: set = set()
        snapshot_dates = []
        for group in self._holdings_groups.values():
            if not group.holdings:
                continue
            as_of = self._holdings_date(group)
            if as_of is None:
                continue
            reference_date = self._snapshot_reference_date(as_of)
            snapshot_dates.append(reference_date)
            logger.info("Using MSSB holdings as at %s (%s).", as_of, group.label)

            for holding in group.holdings:
                if holding.fund_name.startswith(CASH_FUND_PREFIX):
                    currency = holding.fund_name[len(CASH_FUND_PREFIX) :].strip()
                    if currency != self.base_currency:
                        raise ParsingError(f"Unsupported cash currency in holdings: {currency}")
                    self.cash_anchors.append((reference_date, holding.quantity))
                    continue
                symbol = _fund_symbol(holding.fund_name)
                symbols_seen.add(symbol)
                self._add_stock(
                    symbol,
                    SecurityStock(
                        referenceDate=reference_date,
                        mutation=False,
                        quantity=holding.quantity,
                        balanceCurrency=self.base_currency,
                        quotationType="PIECE",
                        name="Holdings Report",
                    ),
                )

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
            logger.warning(
                "MSSB cash account: withdrawals exceed the proceeds in the export; assuming an "
                "opening cash balance of %s %s.",
                opening,
                self.base_currency,
            )
        return opening + sum((a for d, a in self.cash_events if d < target), Decimal(0))

    def _check_cash_anchors(self) -> None:
        anchors = sorted(self.cash_anchors)
        for (d1, v1), (d2, v2) in zip(anchors, anchors[1:]):
            expected = v1 + sum((a for d, a in self.cash_events if d1 <= d < d2), Decimal(0))
            if expected != v2:
                # Dividends are credited to cash but are not in any MSSB export.
                logger.info(
                    "MSSB cash grew by %s %s between the holdings snapshots without matching "
                    "sales or withdrawals (most likely dividends).",
                    v2 - expected,
                    self.base_currency,
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

        self._resolve_releases()
        self._resolve_withdrawals(self._report_fx_rate())
        self._resolve_holdings()

        def _hints_for(sec_pos: SecurityPosition) -> PositionHints:
            return PositionHints(security_category="SHARE", country="US")

        for sec_pos, data in self.processed_security_positions.items():
            stocks = _aggregate_mssb_stocks(data["stocks"])
            if any(not s.mutation for s in stocks):
                _check_against_balances(sec_pos.symbol, stocks)
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
            skip_opening_balance_when_zero=False,
        )
        self._add_unvested(statement)

        period_end_plus_one = self.period_to + timedelta(days=1)
        self._check_cash_anchors()
        cash_balance = self._cash_balance_at(period_end_plus_one)
        if cash_balance is not None:
            if cash_balance < 0:
                logger.warning(
                    "MSSB cash account ends the period at %s %s.", cash_balance, self.base_currency
                )
            if self.cash_anchors and not any(
                d == period_end_plus_one for d, _ in self.cash_anchors
            ):
                logger.warning(
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
            augment_list_of_bank_accounts(statement, [cash_entry])

        return statement

    def _with_inferred_opening(
        self, sec_pos: SecurityPosition, stocks: List[SecurityStock]
    ) -> List[SecurityStock]:
        opening = _infer_opening_balance([(s.referenceDate, s.quantity) for s in stocks])
        if not opening:
            return stocks
        first_date = min(stocks[0].referenceDate, self.period_from)
        logger.warning(
            "%s: the export removes more shares than it adds, so it does not start from an "
            "empty account. Assuming %s shares held before %s. Add the MSSB vested share "
            "holdings report to use the real figure.",
            sec_pos.symbol,
            opening,
            first_date,
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

    def _add_unvested(self, statement: TaxStatement) -> None:
        """List unvested GSUs at the period end as a pro memoria position without tax value.

        The report does not state its "as at" date. Every tranche vests after that date, so
        the report is taken to be as at the period end when its first vest falls shortly
        after it.
        """
        if not self._unvested:
            return
        first_vest = min(t.vesting_date for t in self._unvested)
        if first_vest <= self.period_to:
            logger.warning(
                "%s lists a vest on %s, within the tax period, so it is not as at %s; "
                "skipping the unvested shares. Export it as at the end of the tax year.",
                self._unvested_label,
                first_vest,
                self.period_to,
            )
            return
        if first_vest > self.period_to + UNVESTED_MAX_GAP:
            logger.warning(
                "%s starts with a vest on %s; it may be as at a later date than %s and miss "
                "earlier vests.",
                self._unvested_label,
                first_vest,
                self.period_to,
            )

        quantity = sum((t.quantity for t in self._unvested), Decimal(0))
        security = Security(
            positionId=1,
            country="US",
            currency=self.base_currency,
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName=UNVESTED_SECURITY_NAME,
            stock=[
                SecurityStock(
                    referenceDate=self.period_to + timedelta(days=1),
                    mutation=False,
                    quantity=quantity,
                    balanceCurrency=self.base_currency,
                    quotationType="PIECE",
                    name=f"Unvested GSUs, {len(self._unvested)} tranches until {max(t.vesting_date for t in self._unvested)}",
                )
            ],
            is_pro_memoria=True,
        )

        if statement.listOfSecurities is None:
            statement.listOfSecurities = ListOfSecurities(
                depot=[Depot(depotNumber=DepotNumber(self._depot_id), security=[])]
            )
        depots = statement.listOfSecurities.depot
        depot = next((d for d in depots if d.depotNumber == self._depot_id), depots[0])
        security.positionId = max((s.positionId for d in depots for s in d.security), default=0) + 1
        depot.security.append(security)


def _check_against_balances(symbol: Optional[str], stocks: List[SecurityStock]) -> None:
    """Warn when the activity does not connect the known balances."""
    balances = sorted((s for s in stocks if not s.mutation), key=lambda s: s.referenceDate)
    mutations = [s for s in stocks if s.mutation]

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
            logger.warning(
                "%s: the activity between the holdings on %s (%s) and %s (%s) adds up to %s; "
                "some activity is missing from the exports.",
                symbol,
                b1.referenceDate,
                b1.quantity,
                b2.referenceDate,
                b2.quantity,
                expected,
            )

    first, last = balances[0], balances[-1]
    running = last.quantity
    for m in sorted(mutations, key=lambda s: s.referenceDate):
        if m.referenceDate >= last.referenceDate:
            running += m.quantity
            if running < 0:
                logger.warning(
                    "%s: activity after the %s holdings takes the position negative on %s.",
                    symbol,
                    last.referenceDate,
                    m.referenceDate,
                )
                break
    running = first.quantity
    for m in sorted(mutations, key=lambda s: s.referenceDate, reverse=True):
        if m.referenceDate < first.referenceDate:
            running -= m.quantity
            if running < 0:
                logger.warning(
                    "%s: activity before the %s holdings implies a negative position before " "%s.",
                    symbol,
                    first.referenceDate,
                    m.referenceDate,
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
