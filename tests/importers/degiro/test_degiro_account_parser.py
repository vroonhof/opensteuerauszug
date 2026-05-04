"""Unit tests for the Degiro Account.csv parser."""

from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.importers.degiro.account_csv_parser import (
    DegiroRow,
    DegiroRowKind,
    classify_row,
    load_account_csv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(**kwargs) -> DegiroRow:
    defaults = dict(
        date=date(2023, 3, 31),
        time="09:04",
        value_date=date(2023, 3, 31),
        product="",
        isin="",
        description="",
        fx_rate=None,
        change_currency="EUR",
        change_amount=Decimal("0"),
        balance_currency="EUR",
        balance_amount=Decimal("0"),
        order_id="",
        raw_row=1,
    )
    defaults.update(kwargs)
    return DegiroRow(**defaults)


# ---------------------------------------------------------------------------
# classify_row
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("description,expected", [
    ("Buy 60 iShares@20.08 EUR (IE00B3WJKG14)", DegiroRowKind.BUY_SELL),
    ("Sell 10 Activision@0 USD (US00507V1098)", DegiroRowKind.BUY_SELL),
    ("Dividend", DegiroRowKind.DIVIDEND),
    ("Dividend Tax", DegiroRowKind.DIVIDEND_TAX),
    ("FX Credit", DegiroRowKind.FX_CREDIT),
    ("FX Debit", DegiroRowKind.FX_DEBIT),
    ("DEGIRO Transaction and/or third party fees", DegiroRowKind.FEE_TRANSACTION),
    ("DEGIRO Exchange Connection Fee 2023 (Nasdaq - NDQ)", DegiroRowKind.FEE_CONNECTION),
    ("Corporate Action Cash Settlement Stock", DegiroRowKind.CORPORATE_CASH),
    ("Corporate Action Cash Settlement", DegiroRowKind.CORPORATE_CASH),
    ("DELISTING: Sell 10 Activision Blizzard Inc@0 USD (US00507V1098)", DegiroRowKind.DELISTING),
    ("Deposit", DegiroRowKind.DEPOSIT),
    ("Flatex Interest Income", DegiroRowKind.FLATEX_INTEREST),
    ("Transfer from your Cash Account at flatexDEGIRO Bank: 7 CHF", DegiroRowKind.CASH_SWEEP_IN),
    ("Transfer to your Cash Account at flatexDEGIRO Bank: 7 CHF", DegiroRowKind.CASH_SWEEP_OUT),
    ("Degiro Cash Sweep Transfer", DegiroRowKind.DEGIRO_SWEEP),
    ("Something completely unknown", DegiroRowKind.UNKNOWN),
])
def test_classify_row(description, expected):
    row = _make_row(description=description)
    assert classify_row(row) == expected


def test_classify_buy_requires_space():
    """'Buyback' should NOT be classified as BUY_SELL."""
    row = _make_row(description="Buyback program")
    assert classify_row(row) == DegiroRowKind.UNKNOWN


# ---------------------------------------------------------------------------
# load_account_csv – integration with sample file
# ---------------------------------------------------------------------------

SAMPLE_ACCOUNT_CSV = """\
Date,Time,Value date,Product,ISIN,Description,FX,Change,,Balance,,Order Id
29-12-2023,10:00,28-12-2023,,,FX Credit,,CHF,9.89,CHF,500.00,
28-12-2023,10:00,27-12-2023,VANGUARD S&P 500 UCITS ETF USD DIS,IE00B3XXRP09,Dividend,,USD,11.73,USD,11.73,
18-08-2023,10:00,17-08-2023,ACTIVISION BLIZZARD INC,US00507V1098,Dividend,,USD,9.90,USD,8.41,
18-08-2023,10:00,17-08-2023,ACTIVISION BLIZZARD INC,US00507V1098,Dividend Tax,,USD,-1.49,USD,-1.49,
16-10-2023,10:00,13-10-2023,ACTIVISION BLIZZARD INC,US00507V1098,DELISTING: Sell 10 Activision Blizzard Inc@0 USD (US00507V1098),,USD,0.00,USD,0.00,
31-03-2023,10:00,31-03-2023,ISHARES CORE MSCI EM IMI UCITS ETF USD,IE00BKM4GZ66,Buy 107 iShares Core MSCI EM IMI UCITS ETF USD Acc@25.00 EUR (IE00BKM4GZ66),,EUR,-2675.00,EUR,-4000.00,00000000-0000-0000-0000-000000000001
31-03-2023,10:00,31-03-2023,ISHARES CORE MSCI EM IMI UCITS ETF USD,IE00BKM4GZ66,Buy 112 iShares Core MSCI EM IMI UCITS ETF USD Acc@25.00 EUR (IE00BKM4GZ66),,EUR,-2800.00,EUR,-2800.00,00000000-0000-0000-0000-000000000001
28-03-2023,10:00,27-03-2023,,,Deposit,,CHF,10000.00,CHF,15000.00,
"""


def _write_temp_csv(tmp_path, content, filename="Account.csv"):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_load_account_csv_row_count(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_ACCOUNT_CSV)
    rows = load_account_csv(path)
    assert len(rows) == 8


def test_load_account_csv_dates(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_ACCOUNT_CSV)
    rows = load_account_csv(path)
    # First row (original order, reverse-chronological)
    assert rows[0].date == date(2023, 12, 29)
    assert rows[0].value_date == date(2023, 12, 28)


def test_load_account_csv_dividend_row(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_ACCOUNT_CSV)
    rows = load_account_csv(path)
    div = rows[1]  # second row is the dividend
    assert div.isin == "IE00B3XXRP09"
    assert div.change_currency == "USD"
    assert div.change_amount == Decimal("11.73")
    assert div.product == "VANGUARD S&P 500 UCITS ETF USD DIS"
    assert classify_row(div) == DegiroRowKind.DIVIDEND


def test_load_account_csv_dividend_tax_row(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_ACCOUNT_CSV)
    rows = load_account_csv(path)
    tax = rows[3]
    assert tax.isin == "US00507V1098"
    assert tax.change_amount == Decimal("-1.49")
    assert classify_row(tax) == DegiroRowKind.DIVIDEND_TAX


def test_load_account_csv_fx_rate(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_ACCOUNT_CSV)
    rows = load_account_csv(path)
    fx_row = rows[0]  # FX Credit row, no FX rate given
    assert fx_row.fx_rate is None


def test_load_account_csv_buy_rows_same_order(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_ACCOUNT_CSV)
    rows = load_account_csv(path)
    buy1, buy2 = rows[5], rows[6]
    assert buy1.order_id == buy2.order_id == "00000000-0000-0000-0000-000000000001"
    assert classify_row(buy1) == DegiroRowKind.BUY_SELL
    assert classify_row(buy2) == DegiroRowKind.BUY_SELL


def test_load_account_csv_empty_change(tmp_path):
    """Rows with no Change columns should parse to change_amount=0."""
    path = _write_temp_csv(tmp_path, SAMPLE_ACCOUNT_CSV)
    rows = load_account_csv(path)
    deposit = rows[7]
    assert classify_row(deposit) == DegiroRowKind.DEPOSIT
    assert deposit.change_amount == Decimal("10000.00")


def test_load_account_csv_raw_row_numbers(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_ACCOUNT_CSV)
    rows = load_account_csv(path)
    # raw_row starts at 2 (header is row 1)
    assert rows[0].raw_row == 2
    assert rows[1].raw_row == 3


def test_load_account_csv_skips_empty_date_lines(tmp_path):
    content = (
        "Date,Time,Value date,Product,ISIN,Description,FX,Change,,Balance,,Order Id\n"
        "29-12-2023,10:00,28-12-2023,,,FX Credit,,CHF,9.89,CHF,500.00,\n"
        "\n"  # empty line
        "28-12-2023,10:00,27-12-2023,VANGUARD S&P 500 UCITS ETF USD DIS,IE00B3XXRP09,Dividend,,USD,11.73,USD,11.73,\n"
    )
    path = _write_temp_csv(tmp_path, content)
    rows = load_account_csv(path)
    assert len(rows) == 2
