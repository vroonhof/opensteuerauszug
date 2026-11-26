"""Tests for Morgan Stanley parser."""

from __future__ import annotations

import csv
import datetime
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from opensteuerauszug.config.models import MssbAccountSettings
from opensteuerauszug.importers.mssb.mssb_importer import (
    COLUMNS_RELEASE,
    COLUMNS_WITHDRAWAL,
    HOLDINGS_REPORT_FILENAME,
    QUOTE_HISTORY_FILENAME,
    RELEASES_REPORT_FILENAME,
    WITHDRAWALS_REPORT_FILENAME,
    MssbImporter,
    ParsingError,
)


def _write_csv(file_path: Path, rows: list[list[str]]) -> None:
    """Write rows to a CSV file."""
    with file_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


@pytest.fixture
def importer_settings():
    return [
        MssbAccountSettings(
            account_number="MSSB-TEST",
            broker_name="mssb",
            account_name_alias="mssb",
            full_name="Test User",
        )
    ]


def test_read_mssb_transactions_empty_file(tmp_path: Path, importer_settings) -> None:
    """Ensure parser fails fast when the CSV file has no content."""
    empty_file = tmp_path / WITHDRAWALS_REPORT_FILENAME
    empty_file.write_text("", encoding="utf-8")

    importer = MssbImporter(
        datetime.date(2023, 1, 1), datetime.date(2023, 12, 31), importer_settings
    )
    with pytest.raises(ParsingError) as exc:
        importer.import_dir(str(tmp_path))

    assert "CSV doesn't have a header" in str(exc.value)


def test_read_mssb_release_success(tmp_path: Path, importer_settings) -> None:
    """Parse a valid release report row and return a populated transaction."""
    release_file = tmp_path / RELEASES_REPORT_FILENAME
    rows = [
        COLUMNS_RELEASE,
        [
            "25-Mar-2023",
            "ORDER-1",
            "GSU Class C",
            "Release",
            "Complete",
            "$10.00",
            "3.000",
            "$0.00",
            "3",
            "Fractional Shares",
        ],
    ]
    _write_csv(release_file, rows)

    importer = MssbImporter(
        datetime.date(2023, 1, 1), datetime.date(2023, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    assert statement.listOfSecurities is not None
    assert len(statement.listOfSecurities.depot) == 1
    assert len(statement.listOfSecurities.depot[0].security) == 1
    position = statement.listOfSecurities.depot[0].security[0]

    # Check that GOOG (GSU Class C) was created
    assert position.symbol == "GOOG"
    mutations = [s for s in position.stock if s.mutation]
    assert len(mutations) == 1

    stock = mutations[0]
    assert stock.quantity == Decimal("3")
    assert stock.unitPrice == Decimal("10.00")
    assert stock.referenceDate == datetime.date(2023, 3, 25)


def test_read_mssb_withdrawal_skips_notice(tmp_path: Path, importer_settings) -> None:
    """Ensure withdrawal parser ignores trailing notice rows."""
    withdrawal_file = tmp_path / WITHDRAWALS_REPORT_FILENAME
    rows = [
        COLUMNS_WITHDRAWAL,
        [
            "02-Apr-2021",
            "ORDER-2",
            "Cash",
            "Sale",
            "Complete",
            "$1.00",
            "-4,218.95",
            "$4,218.95",
            "0",
            "N/A",
        ],
        [
            "Please note that any Alphabet share sales, transfers, or deposits that occurred on or prior to the July 15, 2022 stock split are reflected in pre-split. Any sales, transfers, or deposits that occurred after July 15, 2022 are in post-split values. For GSU vests, your activity is displayed in post-split values.",
        ],
    ]
    _write_csv(withdrawal_file, rows)

    importer = MssbImporter(
        datetime.date(2021, 1, 1), datetime.date(2021, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    assert statement.listOfBankAccounts is not None
    assert len(statement.listOfBankAccounts.bankAccount) == 1
    account = statement.listOfBankAccounts.bankAccount[0]
    assert account.bankAccountNumber == "MSSB-TEST-USD"

    # A cash withdrawal with no proceeds in the export implies cash held beforehand,
    # so the account ends at zero rather than going negative.
    assert account.taxValue is not None
    assert account.taxValue.balance == Decimal("0")


def test_read_mssb_withdrawal_invalid_decimal(tmp_path: Path, importer_settings) -> None:
    """Raise parsing error when numeric values cannot be parsed."""
    withdrawal_file = tmp_path / WITHDRAWALS_REPORT_FILENAME
    rows = [
        COLUMNS_WITHDRAWAL,
        [
            "09-Feb-2023",
            "ORDER-3",
            "GSU Class C",
            "Sale",
            "Complete",
            "$105.70",
            "bad",
            "$3,170.93",
            "0",
            "N/A",
        ],
    ]
    _write_csv(withdrawal_file, rows)

    importer = MssbImporter(
        datetime.date(2023, 1, 1), datetime.date(2023, 12, 31), importer_settings
    )
    with pytest.raises(ParsingError) as exc:
        importer.import_dir(str(tmp_path))

    message = str(exc.value)
    assert "row 0" in message
    assert "Invalid decimal in column 'Quantity'" in message


def test_read_mssb_release_invalid_header(tmp_path: Path, importer_settings) -> None:
    """Error when release report header differs from expected schema."""
    release_file = tmp_path / RELEASES_REPORT_FILENAME
    invalid_header = ["Vest date", *COLUMNS_RELEASE[1:]]
    _write_csv(release_file, [invalid_header])

    importer = MssbImporter(
        datetime.date(2023, 1, 1), datetime.date(2023, 12, 31), importer_settings
    )
    with pytest.raises(ParsingError) as exc:
        importer.import_dir(str(tmp_path))

    assert "CSV header mismatch" in str(exc.value)


def test_read_mssb_multiple_releases_aggregated(tmp_path: Path, importer_settings) -> None:
    """Ensure multiple releases on the same date are grouped and summed."""
    release_file = tmp_path / RELEASES_REPORT_FILENAME
    rows = [
        COLUMNS_RELEASE,
        [
            "25-Nov-2025",
            "RB-TEST-01",
            "GSU Class C",
            "Release",
            "Complete",
            "210.50",
            "8.250",
            "0.00",
            "7.812",
            "Fractional Shares",
        ],
        [
            "25-Nov-2025",
            "RB-TEST-02",
            "GSU Class C",
            "Release",
            "Complete",
            "210.50",
            "4.100",
            "0.00",
            "3.883",
            "Fractional Shares",
        ],
    ]
    _write_csv(release_file, rows)

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    assert statement.listOfSecurities is not None
    depot = statement.listOfSecurities.depot[0]
    position = depot.security[0]

    mutations = [s for s in position.stock if s.mutation]
    assert len(mutations) == 1
    assert mutations[0].quantity == Decimal("11.695")  # 7.812 + 3.883
    # Prices without "$" are in the display currency at an unknown rate.
    assert mutations[0].unitPrice is None
    assert mutations[0].referenceDate == datetime.date(2025, 11, 25)
    assert mutations[0].orderId == "RB-TEST-01,RB-TEST-02"


def test_read_mssb_withdrawal_no_cash_is_transfer_out(tmp_path: Path, importer_settings) -> None:
    """Ensure withdrawals with no cash proceeds are marked as Transfer Out with None unitPrice."""
    withdrawal_file = tmp_path / WITHDRAWALS_REPORT_FILENAME
    rows = [
        COLUMNS_WITHDRAWAL,
        [
            "11-Feb-2025",
            "ORDER-4",
            "GSU Class C",
            "Sale",
            "Complete",
            "185.40",
            "-250",
            "",
            "0",
            "N/A",
        ],
    ]
    _write_csv(withdrawal_file, rows)

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    assert statement.listOfSecurities is not None
    depot = statement.listOfSecurities.depot[0]
    position = depot.security[0]

    mutations = [s for s in position.stock if s.mutation]
    assert len(mutations) == 1
    assert mutations[0].name == "Transfer Out"
    assert mutations[0].unitPrice is None
    assert mutations[0].quantity == Decimal("-250")


def _balances(position) -> dict[datetime.date, Decimal]:
    return {s.referenceDate: s.quantity for s in position.stock if not s.mutation}


def test_sale_reduces_position_and_credits_cash(tmp_path: Path, importer_settings) -> None:
    """A sale is a negative mutation and its proceeds land in the cash account."""
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [
            COLUMNS_RELEASE,
            [
                "25-Mar-2023",
                "R-1",
                "GSU Class C",
                "Release",
                "Complete",
                "$100.00",
                "20",
                "$0.00",
                "10",
                "Fractional Shares",
            ],
        ],
    )
    _write_csv(
        tmp_path / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            [
                "03-Apr-2023",
                "S-1",
                "GSU Class C",
                "Sale",
                "Complete",
                "$110.00",
                "-4",
                "$439.95",
                "0",
                "N/A",
            ],
        ],
    )

    importer = MssbImporter(
        datetime.date(2023, 1, 1), datetime.date(2023, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    position = statement.listOfSecurities.depot[0].security[0]
    sale = [s for s in position.stock if s.mutation and s.name == "Sale"][0]
    assert sale.quantity == Decimal("-4")
    assert sale.unitPrice == Decimal("110.00")
    assert _balances(position)[datetime.date(2024, 1, 1)] == Decimal("6")

    account = statement.listOfBankAccounts.bankAccount[0]
    assert account.taxValue.balance == Decimal("439.95")


def test_withdrawal_before_split_is_adjusted(tmp_path: Path, importer_settings) -> None:
    """Withdrawals up to 15 July 2022 are reported pre-split and get scaled 20:1."""
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [
            COLUMNS_RELEASE,
            [
                "25-Jan-2022",
                "R-1",
                "GSU Class C",
                "Release",
                "Complete",
                "$140.00",
                "200",
                "$0.00",
                "100",
                "Fractional Shares",
            ],
        ],
    )
    _write_csv(
        tmp_path / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            [
                "01-Jul-2022",
                "S-1",
                "GSU Class C",
                "Sale",
                "Complete",
                "$2,200.00",
                "-2",
                "$4,400.00",
                "0",
                "N/A",
            ],
            [
                "20-Jul-2022",
                "S-2",
                "GSU Class C",
                "Sale",
                "Complete",
                "$115.00",
                "-10",
                "$1,150.00",
                "0",
                "N/A",
            ],
        ],
    )

    importer = MssbImporter(
        datetime.date(2022, 1, 1), datetime.date(2022, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    position = statement.listOfSecurities.depot[0].security[0]
    sales = {s.referenceDate: s for s in position.stock if s.mutation and s.name == "Sale"}
    assert sales[datetime.date(2022, 7, 1)].quantity == Decimal("-40")
    assert sales[datetime.date(2022, 7, 1)].unitPrice == Decimal("110")
    assert sales[datetime.date(2022, 7, 20)].quantity == Decimal("-10")
    assert sales[datetime.date(2022, 7, 20)].unitPrice == Decimal("115.00")
    assert _balances(position)[datetime.date(2023, 1, 1)] == Decimal("50")


def test_opening_balance_inferred_when_export_starts_mid_history(
    tmp_path: Path, importer_settings
) -> None:
    """A transfer out larger than the exported vests implies shares held before the export."""
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [
            COLUMNS_RELEASE,
            [
                "25-Jan-2025",
                "R-1",
                "GSU Class C",
                "Release",
                "Complete",
                "$200.00",
                "10",
                "$0.00",
                "5",
                "Fractional Shares",
            ],
            [
                "25-Feb-2025",
                "R-2",
                "GSU Class C",
                "Release",
                "Complete",
                "$180.00",
                "10",
                "$0.00",
                "6",
                "Fractional Shares",
            ],
        ],
    )
    _write_csv(
        tmp_path / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            [
                "11-Feb-2025",
                "T-1",
                "GSU Class C",
                "",
                "Complete",
                "$190.00",
                "-105",
                "",
                "0",
                "N/A",
            ],
        ],
    )

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    position = statement.listOfSecurities.depot[0].security[0]
    balances = _balances(position)
    assert balances[datetime.date(2025, 1, 1)] == Decimal("100")
    assert balances[datetime.date(2026, 1, 1)] == Decimal("6")
    # No cash account when the export has no cash activity.
    assert statement.listOfBankAccounts is None


@pytest.mark.parametrize(
    ("year", "opening", "closing"),
    [
        (2021, Decimal("0"), Decimal("172")),
        (2022, Decimal("172"), Decimal("172")),
        (2023, Decimal("172"), Decimal("163.201")),
    ],
)
def test_sample_export(year: int, opening: Decimal, closing: Decimal, importer_settings) -> None:
    """Run the anonymised sample export end to end for several tax years."""
    sample_dir = Path(__file__).parents[2] / "samples" / "import" / "mssb" / "basic"
    importer = MssbImporter(
        datetime.date(year, 1, 1), datetime.date(year, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(sample_dir))

    position = statement.listOfSecurities.depot[0].security[0]
    balances = _balances(position)
    # A zero opening balance is left out of the statement.
    assert balances.get(datetime.date(year, 1, 1), Decimal(0)) == opening
    assert balances[datetime.date(year + 1, 1, 1)] == closing


STOCK_STATEMENT_HEADER = [
    "Purno",
    "Jurisdiction",
    "Award Date",
    "Vesting Date",
    "GSUs Vested",
    "Shares Deposited",
    "Fair Market Value",
    "Amount Subject to Tax Withholding",
    "Local 1",
    "Total Tax Withheld at Broker",
    "FX Rate",
    "Currency",
    "Release Type",
    "Award Number",
]


def _write_stock_statement(directory: Path, vests: list[tuple[str, str, str, str, str]]) -> None:
    """Write a stock statement like MSSB's: title line, table, then free-text footnotes.

    Each vest is (purno, vesting date, gsus vested, shares deposited, fmv).
    """
    rows: list[list[str]] = [
        [
            "Alphabet, Inc. - GSUs (report run on 01-Oct-2026 for reporting period 01-Jan-2025 to 31-Dec-2025)"
        ],
        STOCK_STATEMENT_HEADER,
    ]
    for purno, date, vested, deposited, fmv in vests:
        rows.append(
            [
                purno,
                "Switzerland",
                "01-Mar-2023",
                date,
                vested,
                deposited,
                fmv,
                "$1.00",
                "$0.05",
                "$0.05",
                "0.8",
                "USD",
                "WCF",
                "C100",
            ]
        )
    rows.append([" 1. This is not an official tax document, 2. more text"])
    rows.append(
        ["9. The numbers on this statement reflect post-split values from stock split on 7/15/2022"]
    )
    _write_csv(directory / "Your Alphabet Stock Statement - Test, User.csv", rows)


def _write_holdings(
    directory: Path,
    holdings: list[tuple[str, str, str]],
    quote_date: str,
    quotes: list[tuple[str, str]],
) -> None:
    """Holdings rows are (fund, shares, market value in CHF); quotes are (fund, USD price)."""
    rows: list[list[str]] = [
        ["Alphabet, Inc. - Holdings Report (report run on 01-Oct-2026)"],
        [
            "Employee Number",
            "Savings Plan Name",
            "Fund Name",
            "Number of Shares",
            "Acquisition Value",
            "",
            "Market Value",
            "",
        ],
    ]
    for fund, shares, value in holdings:
        rows.append(
            [
                "1",
                "Alphabet, Inc. Long Share Savings Plan",
                fund,
                shares,
                value,
                "CHF",
                value,
                "CHF",
            ]
        )
    rows.append(["Market Value Definition = Market Price as at Selected Date * Total Held Shares"])
    _write_csv(directory / HOLDINGS_REPORT_FILENAME, rows)

    quote_rows: list[list[str]] = [["Quote History"], ["Fund", "Quote Date", "Price", ""]]
    for fund, price in quotes:
        quote_rows.append([fund, quote_date, price, "USD"])
    _write_csv(directory / QUOTE_HISTORY_FILENAME, quote_rows)


def _release_row(date: str, order: str, price: str, deposited: str) -> list[str]:
    return [
        date,
        order,
        "GSU Class C",
        "Release",
        "Complete",
        price,
        "99",
        "0.00",
        deposited,
        "Fractional Shares",
    ]


def test_stock_statement_gives_usd_prices_and_report_fx(tmp_path: Path, importer_settings) -> None:
    """Display-currency prices are replaced by the USD FMV, and the implied rate fixes sales."""
    # MSSB converted these at 0.8 CHF per USD.
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [
            COLUMNS_RELEASE,
            _release_row("25-Jan-2025", "RB1", "160.00", "10"),
            _release_row("25-Feb-2025", "RB2", "144.00", "10"),
        ],
    )
    _write_stock_statement(
        tmp_path,
        [
            ("RB1", "25-Jan-2025", "11.000000", "10", "$200.00"),
            ("RB2", "25-Feb-2025", "11.000000", "10", "$180.00"),
        ],
    )
    _write_csv(
        tmp_path / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            [
                "03-Mar-2025",
                "S-1",
                "GSU Class C",
                "Sale",
                "Complete",
                "136.00",
                "-5",
                "680.00",
                "0",
                "N/A",
            ],
        ],
    )

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    position = statement.listOfSecurities.depot[0].security[0]
    prices = {(s.referenceDate, s.name): s.unitPrice for s in position.stock if s.mutation}
    assert prices[(datetime.date(2025, 1, 25), "Release")] == Decimal("200.00")
    assert prices[(datetime.date(2025, 2, 25), "Release")] == Decimal("180.00")
    assert prices[(datetime.date(2025, 3, 3), "Sale")] == Decimal("170")
    assert statement.listOfBankAccounts.bankAccount[0].taxValue.balance == Decimal("850")


def test_non_usd_sale_without_stock_statement_fails(tmp_path: Path, importer_settings) -> None:
    """Sale proceeds in an unknown currency cannot be booked to the USD cash account."""
    _write_csv(
        tmp_path / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            [
                "03-Mar-2025",
                "S-1",
                "GSU Class C",
                "Sale",
                "Complete",
                "136.00",
                "-5",
                "680.00",
                "0",
                "N/A",
            ],
        ],
    )

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    with pytest.raises(ParsingError, match="stock statement"):
        importer.import_dir(str(tmp_path))


def test_stock_statement_without_releases_report(tmp_path: Path, importer_settings) -> None:
    """The stock statement alone is enough to book the vests."""
    _write_stock_statement(
        tmp_path,
        [
            ("RB1", "25-Jan-2025", "11.000000", "10.5", "$200.00"),
            ("RB2", "25-Jan-2025", "6.000000", "5.5", "$200.00"),
        ],
    )

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    position = statement.listOfSecurities.depot[0].security[0]
    assert position.symbol == "GOOG"
    mutations = [s for s in position.stock if s.mutation]
    assert len(mutations) == 1
    assert mutations[0].quantity == Decimal("16.0")
    assert mutations[0].unitPrice == Decimal("200.00")
    assert _balances(position)[datetime.date(2026, 1, 1)] == Decimal("16.0")


def test_holdings_report_sets_opening_positions_and_cash(tmp_path: Path, importer_settings) -> None:
    """Holdings dated by the quote history replace the inferred opening balance."""
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [COLUMNS_RELEASE, _release_row("25-Jan-2025", "RB1", "$200.00", "5")],
    )
    _write_csv(
        tmp_path / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            [
                "11-Feb-2025",
                "T-1",
                "GSU Class C",
                "",
                "Complete",
                "$190.00",
                "-100",
                "",
                "0",
                "N/A",
            ],
        ],
    )
    # Market values are shares * USD quote * 0.9 CHF/USD for every fund.
    _write_holdings(
        tmp_path,
        [
            ("Cash - USD", "72.500000", "65.25"),
            ("GOOG - NASDAQ", "120.000000", "20,520.00"),
            ("GOOGL - NASDAQ", "0.820000", "139.38"),
        ],
        "01-Jan-2025",
        [("Cash - USD", "$1.00"), ("GOOGL - NASDAQ", "$188.86"), ("GOOG - NASDAQ", "$190.00")],
    )

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    securities = {s.symbol: s for s in statement.listOfSecurities.depot[0].security}
    assert _balances(securities["GOOG"])[datetime.date(2025, 1, 1)] == Decimal("120")
    assert _balances(securities["GOOG"])[datetime.date(2026, 1, 1)] == Decimal("25")
    assert _balances(securities["GOOGL"])[datetime.date(2025, 1, 1)] == Decimal("0.82")
    assert _balances(securities["GOOGL"])[datetime.date(2026, 1, 1)] == Decimal("0.82")
    assert statement.listOfBankAccounts.bankAccount[0].taxValue.balance == Decimal("72.50")


def test_holdings_report_rejected_when_quotes_do_not_match(
    tmp_path: Path, importer_settings
) -> None:
    """A quote history from another day cannot date the holdings report."""
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [COLUMNS_RELEASE, _release_row("25-Jan-2025", "RB1", "$200.00", "5")],
    )
    _write_holdings(
        tmp_path,
        [("GOOG - NASDAQ", "120.000000", "20,520.00"), ("GOOGL - NASDAQ", "0.820000", "200.00")],
        "01-Jan-2025",
        [("GOOGL - NASDAQ", "$188.86"), ("GOOG - NASDAQ", "$190.00")],
    )

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    with pytest.raises(ParsingError, match="do not match its quote history"):
        importer.import_dir(str(tmp_path))


def _zip_dir(source: Path, archive: Path) -> None:
    """Pack the files of ``source`` into ``archive`` (flat), like MSSB's downloads."""
    with zipfile.ZipFile(archive, "w") as zf:
        for f in sorted(source.iterdir()):
            zf.write(f, f.name)


START_HOLDINGS = (
    [
        ("Cash - USD", "50.000000", "45.00"),
        ("GOOG - NASDAQ", "120.000000", "20,520.00"),
    ],
    "01-Jan-2025",
    [("Cash - USD", "$1.00"), ("GOOG - NASDAQ", "$190.00")],
)
# 25 shares at $300 at 0.8 CHF/USD; cash grew by dividends not in any export.
END_HOLDINGS = (
    [
        ("Cash - USD", "80.000000", "64.00"),
        ("GOOG - NASDAQ", "25.000000", "6,000.00"),
    ],
    "31-Dec-2025",
    [("Cash - USD", "$1.00"), ("GOOG - NASDAQ", "$300.00")],
)


def _write_activity(directory: Path) -> None:
    _write_csv(
        directory / RELEASES_REPORT_FILENAME,
        [COLUMNS_RELEASE, _release_row("25-Jan-2025", "RB1", "$200.00", "5")],
    )
    _write_csv(
        directory / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            [
                "11-Feb-2025",
                "T-1",
                "GSU Class C",
                "",
                "Complete",
                "$190.00",
                "-100",
                "",
                "0",
                "N/A",
            ],
        ],
    )


def _make_archives(tmp_path: Path, *, start: bool, end: bool) -> Path:
    """Build an input folder of zip archives the way MSSB delivers them."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name, holdings in (
        ("01", START_HOLDINGS if start else None),
        ("12", END_HOLDINGS if end else None),
    ):
        if holdings is None:
            continue
        staging = tmp_path / f"holdings-{name}"
        staging.mkdir()
        _write_holdings(staging, *holdings)
        _zip_dir(staging, inputs / f"Vested Share Holdings.{name}.zip")
    staging = tmp_path / "activity"
    staging.mkdir()
    _write_activity(staging)
    _zip_dir(staging, inputs / "MSSB Activity Report - Test, User.zip")
    return inputs


def test_zipped_reports_with_start_and_end_holdings(tmp_path: Path, importer_settings) -> None:
    """Holdings reports with identical file names stay paired with their own quote history."""
    inputs = _make_archives(tmp_path, start=True, end=True)

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(inputs))

    position = statement.listOfSecurities.depot[0].security[0]
    balances = _balances(position)
    assert balances[datetime.date(2025, 1, 1)] == Decimal("120")
    assert balances[datetime.date(2026, 1, 1)] == Decimal("25")
    assert datetime.date(2025, 1, 2) not in balances
    # Year-end cash comes straight from the end-of-year holdings.
    assert statement.listOfBankAccounts.bankAccount[0].taxValue.balance == Decimal("80")


def test_only_end_of_year_holdings_infers_opening(tmp_path: Path, importer_settings) -> None:
    """With only the year-end snapshot, the opening position is walked back from it."""
    inputs = _make_archives(tmp_path, start=False, end=True)

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(inputs))

    position = statement.listOfSecurities.depot[0].security[0]
    balances = _balances(position)
    assert balances[datetime.date(2025, 1, 1)] == Decimal("120")
    assert balances[datetime.date(2026, 1, 1)] == Decimal("25")
    assert statement.listOfBankAccounts.bankAccount[0].taxValue.balance == Decimal("80")


def test_inconsistent_snapshots_are_reported(tmp_path: Path, importer_settings, caplog) -> None:
    """Activity that does not connect the two snapshots is flagged."""
    inputs = _make_archives(tmp_path, start=True, end=False)
    staging = tmp_path / "holdings-12"
    staging.mkdir()
    holdings, date, quotes = END_HOLDINGS
    _write_holdings(
        staging, [holdings[0], ("GOOG - NASDAQ", "30.000000", "7,200.00")], date, quotes
    )
    _zip_dir(staging, inputs / "Vested Share Holdings.12.zip")

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(inputs))

    assert "some activity is missing" in caplog.text
    assert any("some activity is missing" in w.message for w in statement.critical_warnings)


def test_unrecognised_and_duplicate_reports_are_skipped(tmp_path: Path, importer_settings) -> None:
    """Wire and net-shares reports duplicate other data; unknown files are ignored."""
    _write_activity(tmp_path)
    _write_csv(
        tmp_path / "Withdrawal Wire Report.csv",
        [
            [
                "Date",
                "Order Number",
                "Symbol",
                "Type",
                "Order Status",
                "Price",
                "Quantity",
                "Net Cash Proceeds",
                "Net Share Proceeds",
                "Tax Payment Method",
            ],
            ["12-Feb-2025", "W-1", "GSU Class C", "Wire", "Complete", "", "0.000", "", "0", "N/A"],
        ],
    )
    _write_csv(
        tmp_path / "Unvested Shares As At Date.csv",
        [
            ["Alphabet, Inc. - Restricted Shares Vesting (report run on 02-Oct-2026)"],
            ["Plan Name", "Award Name", "Employee Grant Number", "Vesting Date", "Total Quantity"],
            ["2021 Stock Plan", "GSU", "C1", "25-Jan-2026", "9.500000"],
        ],
    )
    (tmp_path / "notes.csv").write_text("something,else\n1,2\n", encoding="utf-8")

    importer = MssbImporter(
        datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), importer_settings
    )
    statement = importer.import_dir(str(tmp_path))

    assert len(statement.listOfSecurities.depot[0].security) == 1


def _withdrawal_row(
    date: str, order: str, plan: str, tx_type: str, price: str, quantity: str, amount: str
) -> list[str]:
    return [date, order, plan, tx_type, "Complete", price, quantity, amount, "0", "N/A"]


def _import(tmp_path: Path, settings, year: int = 2025):
    importer = MssbImporter(datetime.date(year, 1, 1), datetime.date(year, 12, 31), settings)
    return importer.import_dir(str(tmp_path))


def _warnings(statement) -> list[str]:
    return [w.message for w in statement.critical_warnings]


def test_extracted_holdings_in_sub_folders(tmp_path: Path, importer_settings) -> None:
    """Extracted holdings reports in one sub-folder per date are read like zip archives."""
    _write_activity(tmp_path)
    for name, holdings in (("start", START_HOLDINGS), ("end", END_HOLDINGS)):
        folder = tmp_path / name
        folder.mkdir()
        _write_holdings(folder, *holdings)

    statement = _import(tmp_path, importer_settings)

    balances = _balances(statement.listOfSecurities.depot[0].security[0])
    assert balances[datetime.date(2025, 1, 1)] == Decimal("120")
    assert balances[datetime.date(2026, 1, 1)] == Decimal("25")
    assert statement.listOfBankAccounts.bankAccount[0].taxValue.balance == Decimal("80")


def test_activity_report_provided_twice_is_rejected(tmp_path: Path, importer_settings) -> None:
    """The zip archive next to its extracted files would count every vest twice."""
    inputs = _make_archives(tmp_path, start=False, end=False)
    _write_activity(inputs)

    with pytest.raises(ParsingError, match="twice"):
        _import(inputs, importer_settings)


def test_two_holdings_snapshots_for_the_same_date_are_rejected(
    tmp_path: Path, importer_settings
) -> None:
    inputs = _make_archives(tmp_path, start=True, end=False)
    staging = tmp_path / "holdings-copy"
    staging.mkdir()
    _write_holdings(staging, *START_HOLDINGS)
    _zip_dir(staging, inputs / "Vested Share Holdings.copy.zip")

    with pytest.raises(ParsingError, match="keep only one"):
        _import(inputs, importer_settings)


def test_empty_directory_is_rejected(tmp_path: Path, importer_settings) -> None:
    with pytest.raises(ParsingError, match="No MSSB reports"):
        _import(tmp_path, importer_settings)


def test_more_than_one_account_is_rejected() -> None:
    settings = [
        MssbAccountSettings(
            account_number=f"MSSB-{i}",
            broker_name="mssb",
            account_name_alias=f"a{i}",
            full_name="Test User",
        )
        for i in range(2)
    ]
    with pytest.raises(ParsingError, match="Only one MSSB account"):
        MssbImporter(datetime.date(2025, 1, 1), datetime.date(2025, 12, 31), settings)


def test_decimal_comma_is_rejected(tmp_path: Path, importer_settings) -> None:
    """'160,50' must not be read as 16050."""
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [COLUMNS_RELEASE, _release_row("25-Jan-2025", "RB1", "$160,50", "5")],
    )
    with pytest.raises(ParsingError, match="Invalid decimal in column 'Price'"):
        _import(tmp_path, importer_settings)


def test_stock_statement_row_with_bad_date_is_not_skipped(
    tmp_path: Path, importer_settings
) -> None:
    """Only free-text notes are skipped; a data row with a malformed date is an error."""
    _write_stock_statement(tmp_path, [("RB1", "2025-01-25", "10", "5", "$190.00")])
    with pytest.raises(ParsingError, match="Invalid date"):
        _import(tmp_path, importer_settings)


def test_duplicate_purno_is_rejected(tmp_path: Path, importer_settings) -> None:
    vest = ("RB1", "25-Jan-2025", "10", "5", "$190.00")
    _write_stock_statement(tmp_path, [vest, vest])
    with pytest.raises(ParsingError, match="appears twice"):
        _import(tmp_path, importer_settings)


def test_release_mismatching_stock_statement_is_rejected(tmp_path: Path, importer_settings) -> None:
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [COLUMNS_RELEASE, _release_row("25-Jan-2025", "RB1", "$190.00", "5")],
    )
    _write_stock_statement(tmp_path, [("RB1", "25-Jan-2025", "10", "6", "$190.00")])
    with pytest.raises(ParsingError, match="stock statement says 6"):
        _import(tmp_path, importer_settings)


def test_single_priced_holding_cannot_be_verified(tmp_path: Path, importer_settings) -> None:
    """With one fund the market value check cannot tell whether the quotes match."""
    _write_activity(tmp_path)
    _write_holdings(
        tmp_path,
        [("GOOG - NASDAQ", "120.000000", "20,520.00")],
        "01-Jan-2025",
        [("GOOG - NASDAQ", "$190.00")],
    )

    statement = _import(tmp_path, importer_settings)

    assert any("cannot be verified" in w for w in _warnings(statement))


def test_unknown_fund_in_holdings_is_rejected(tmp_path: Path, importer_settings) -> None:
    _write_activity(tmp_path)
    _write_holdings(
        tmp_path,
        [("ACME - NYSE", "10.000000", "900.00"), ("GOOG - NASDAQ", "120.000000", "20,520.00")],
        "01-Jan-2025",
        [("ACME - NYSE", "$100.00"), ("GOOG - NASDAQ", "$190.00")],
    )
    with pytest.raises(ParsingError, match="Unknown fund"):
        _import(tmp_path, importer_settings)


def test_holdings_without_quote_history_are_rejected(tmp_path: Path, importer_settings) -> None:
    _write_activity(tmp_path)
    _write_holdings(tmp_path, *START_HOLDINGS)
    (tmp_path / QUOTE_HISTORY_FILENAME).unlink()
    with pytest.raises(ParsingError, match="no quote history"):
        _import(tmp_path, importer_settings)


def test_snapshot_without_cash_line_means_no_cash(tmp_path: Path, importer_settings) -> None:
    """Cash missing from the year-end holdings is zero, not carried forward."""
    inputs = _make_archives(tmp_path, start=True, end=False)
    staging = tmp_path / "holdings-12"
    staging.mkdir()
    _write_holdings(staging, [END_HOLDINGS[0][1]], END_HOLDINGS[1], END_HOLDINGS[2])
    _zip_dir(staging, inputs / "Vested Share Holdings.12.zip")

    statement = _import(inputs, importer_settings)

    assert statement.listOfBankAccounts.bankAccount[0].taxValue.balance == Decimal("0")
    assert any("cash shrank by 50" in w for w in _warnings(statement))


def test_cash_withdrawal_uses_quantity_and_flags_fees(tmp_path: Path, importer_settings) -> None:
    """The USD quantity leaves the cash account; a smaller net amount is a fee."""
    _write_csv(
        tmp_path / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            _withdrawal_row(
                "10-Feb-2025", "S-1", "GSU Class C", "Sale", "$200.00", "-10", "$2,000.00"
            ),
            _withdrawal_row(
                "12-Feb-2025", "W-1", "Cash", "Sale", "$1.00", "-2,000.00", "$1,975.00"
            ),
        ],
    )

    statement = _import(tmp_path, importer_settings)

    assert statement.listOfBankAccounts.bankAccount[0].taxValue.balance == Decimal("0")
    assert any("probably a fee" in w for w in _warnings(statement))


def test_untyped_withdrawal_with_proceeds_is_rejected(tmp_path: Path, importer_settings) -> None:
    _write_csv(
        tmp_path / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            _withdrawal_row("10-Feb-2025", "T-1", "GSU Class C", "", "$200.00", "-10", "$2,000.00"),
        ],
    )
    with pytest.raises(ParsingError, match="without a type has a Net Amount"):
        _import(tmp_path, importer_settings)


def test_sale_and_transfer_on_the_same_day_stay_apart(tmp_path: Path, importer_settings) -> None:
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [COLUMNS_RELEASE, _release_row("25-Jan-2025", "RB1", "$200.00", "30")],
    )
    _write_csv(
        tmp_path / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            _withdrawal_row(
                "10-Feb-2025", "S-1", "GSU Class C", "Sale", "$200.00", "-10", "$2,000.00"
            ),
            _withdrawal_row("10-Feb-2025", "T-1", "GSU Class C", "", "$200.00", "-10", ""),
        ],
    )

    statement = _import(tmp_path, importer_settings)

    position = statement.listOfSecurities.depot[0].security[0]
    names = sorted(s.name for s in position.stock if s.mutation and s.quantity < 0)
    assert names == ["Sale", "Transfer Out"]


def test_staged_release_and_missing_dividends_are_critical_warnings(
    tmp_path: Path, importer_settings
) -> None:
    row = _release_row("25-Jan-2025", "RB1", "$200.00", "5")
    row[4] = "Staged"
    _write_csv(tmp_path / RELEASES_REPORT_FILENAME, [COLUMNS_RELEASE, row])

    statement = _import(tmp_path, importer_settings)

    messages = _warnings(statement)
    assert any("'Staged'" in w for w in messages)
    assert any("no dividend, withholding tax or interest records" in w for w in messages)
    assert any("No MSSB withdrawals report" in w for w in messages)
    assert all(w.source == "MssbImporter" for w in statement.critical_warnings)


def test_release_with_more_net_shares_than_vested_is_rejected(
    tmp_path: Path, importer_settings
) -> None:
    row = _release_row("25-Jan-2025", "RB1", "$200.00", "5")
    row[6] = "4"
    _write_csv(tmp_path / RELEASES_REPORT_FILENAME, [COLUMNS_RELEASE, row])
    with pytest.raises(ParsingError, match="exceed the vested Quantity"):
        _import(tmp_path, importer_settings)


def test_split_year_is_flagged(tmp_path: Path, importer_settings) -> None:
    _write_csv(
        tmp_path / RELEASES_REPORT_FILENAME,
        [COLUMNS_RELEASE, _release_row("25-Mar-2022", "RB1", "$140.00", "20")],
    )
    statement = _import(tmp_path, importer_settings, year=2022)
    assert any("stock split of July 2022" in w for w in _warnings(statement))


def _accounts(statement) -> dict[str, Decimal]:
    return {
        a.bankAccountNumber: a.taxValue.balance for a in statement.listOfBankAccounts.bankAccount
    }


def _write_year_end_sales(directory: Path) -> None:
    _write_csv(
        directory / RELEASES_REPORT_FILENAME,
        [COLUMNS_RELEASE, _release_row("25-Jan-2025", "RB1", "$200.00", "30")],
    )
    _write_csv(
        directory / WITHDRAWALS_REPORT_FILENAME,
        [
            COLUMNS_WITHDRAWAL,
            # Settles on 31 Dec (T+1).
            _withdrawal_row(
                "30-Dec-2025", "S-1", "GSU Class C", "Sale", "$300.00", "-1", "$300.00"
            ),
            # 1 Jan is a NYSE holiday, so this settles on 2 Jan 2026.
            _withdrawal_row(
                "31-Dec-2025", "S-2", "GSU Class C", "Sale", "$300.00", "-2", "$600.00"
            ),
        ],
    )


def test_sale_settling_after_year_end_is_unsettled(tmp_path: Path, importer_settings) -> None:
    _write_year_end_sales(tmp_path)

    statement = _import(tmp_path, importer_settings)

    assert _accounts(statement) == {
        "MSSB-TEST-USD": Decimal("300"),
        "MSSB-TEST-USD-UNSETTLED": Decimal("600"),
    }
    position = statement.listOfSecurities.depot[0].security[0]
    assert _balances(position)[datetime.date(2026, 1, 1)] == Decimal("27")


def test_year_end_snapshot_including_unsettled_proceeds_is_corrected(
    tmp_path: Path, importer_settings
) -> None:
    """With a start snapshot to compare against, double-counted proceeds are taken out."""
    _write_year_end_sales(tmp_path)
    # Market values are at 0.8 CHF/USD. The year-end cash of 900 includes the 600 of
    # proceeds that only settle on 2 January.
    for name, holdings, date, price in (
        ("start", [("Cash - USD", "0.000000", "0.00")], "01-Jan-2025", "$190.00"),
        (
            "end",
            [("Cash - USD", "900.000000", "720.00"), ("GOOG - NASDAQ", "27.000000", "6,480.00")],
            "31-Dec-2025",
            "$300.00",
        ),
    ):
        folder = tmp_path / name
        folder.mkdir()
        _write_holdings(folder, holdings, date, [("Cash - USD", "$1.00"), ("GOOG - NASDAQ", price)])

    statement = _import(tmp_path, importer_settings)

    assert _accounts(statement) == {
        "MSSB-TEST-USD": Decimal("300"),
        "MSSB-TEST-USD-UNSETTLED": Decimal("600"),
    }
    assert not any("cash shrank" in w or "cash grew" in w for w in _warnings(statement))


def test_year_end_snapshot_alone_flags_unsettled_proceeds(
    tmp_path: Path, importer_settings
) -> None:
    _write_year_end_sales(tmp_path)
    _write_holdings(
        tmp_path,
        [("Cash - USD", "300.000000", "240.00"), ("GOOG - NASDAQ", "27.000000", "6,480.00")],
        "31-Dec-2025",
        [("Cash - USD", "$1.00"), ("GOOG - NASDAQ", "$300.00")],
    )

    statement = _import(tmp_path, importer_settings)

    assert _accounts(statement)["MSSB-TEST-USD"] == Decimal("300")
    assert any("does not already include them" in w for w in _warnings(statement))
