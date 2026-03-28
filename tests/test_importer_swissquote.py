"""
Tests for importer_swissquote.py

Place this file in tests/ inside the opensteuerauszug repo.
Run with:  pytest tests/test_importer_swissquote.py -v
"""

from __future__ import annotations

import textwrap
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from opensteuerauszug.importer_swissquote import (
    TRANSACTION_TYPE_MAP,
    SwissquoteTransaction,
    _parse_decimal,
    _parse_date,
    load_swissquote,
    pair_dividends_and_taxes,
    parse_swissquote_csv,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HEADER = (
    "Datum\tAuftrag #\tTransaktionen\tSymbol\tName\tISIN\t"
    "Anzahl\tStückpreis\tKosten\tAufgelaufene Zinsen\tNettobetrag\t"
    "Währung Nettobetrag\tNettobetrag in der Währung des Kontos\tSaldo\tWährung"
)

def _make_csv(rows: list[str]) -> str:
    return HEADER + "\n" + "\n".join(rows) + "\n"

def _row(date="15-01-2024", order="1001", typ="Kauf", symbol="VWRL",
         name="Vanguard FTSE All-World", isin="IE00B3RBWM25",
         qty="10", price="105.20", costs="9.00", accrued="0.00",
         net="-1061.00", net_ccy="CHF", net_acct="-1061.00",
         balance="5000.00", ccy="CHF") -> str:
    return "\t".join([date, order, typ, symbol, name, isin,
                      qty, price, costs, accrued, net,
                      net_ccy, net_acct, balance, ccy])


# ---------------------------------------------------------------------------
# Full sample CSV covering all confirmed transaction types
# ---------------------------------------------------------------------------

SAMPLE_CSV = _make_csv([
    _row("15-01-2024", "1001", "Kauf",    net="-1061.00", balance="5000.00"),
    _row("20-03-2024", "1002", "Dividende", qty="", price="", net="14.29",  balance="5014.29"),
    _row("20-03-2024", "1003", "Verrechnungssteuer", qty="", price="", net="-5.00", balance="5009.29"),
    _row("01-06-2024", "1004", "Verkauf",  qty="5", price="110.00", net="541.00", balance="5550.29"),
    _row("15-06-2024", "1005", "Stockdividende",  qty="1", price="105.00", net="105.00", balance="5655.29"),
    _row("30-06-2024", "1006", "Capital Gain",    qty="", price="", net="8.50",  balance="5663.79"),
    _row("30-06-2024", "1007", "Wertpapierleihe", qty="", price="", net="1.20",  balance="5664.99"),
    _row("31-07-2024", "1008", "Zinsen auf Einlagen",  symbol="", name="", isin="", qty="", price="", net="0.50",  balance="5665.49"),
    _row("31-07-2024", "1009", "Zinsen auf Belastungen", symbol="", name="", isin="", qty="", price="", net="-0.10", balance="5665.39"),
    _row("31-08-2024", "1010", "Rückzahlung",    net="1000.00", balance="6665.39"),
    _row("01-09-2024", "1011", "Forex-Belastung", symbol="", name="", isin="", qty="", price="", net="-2.50", balance="6662.89"),
    _row("30-09-2024", "",     "Depotgebühren",  symbol="", name="", isin="", qty="", price="", costs="50.00", net="-50.00", balance="6612.89"),
    _row("01-10-2024", "1012", "Berichtigung Börsengeb.", symbol="", name="", isin="", qty="", price="", net="1.00", balance="6613.89"),
    _row("15-10-2024", "1013", "Spesen Steueraszug", symbol="", name="", isin="", qty="", price="", net="-25.00", balance="6588.89"),
    _row("20-11-2024", "1014", "Auszahlung", symbol="", name="", isin="", qty="", price="", net="-500.00", balance="6088.89"),
    _row("25-11-2024", "1015", "Twint",     symbol="", name="", isin="", qty="", price="", net="100.00", balance="6188.89"),
    _row("01-12-2024", "1016", "Zahlung",   symbol="", name="", isin="", qty="", price="", net="-10.00", balance="6178.89"),
])

@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    p = tmp_path / "swissquote_2024.csv"
    p.write_text(SAMPLE_CSV, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _parse_decimal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1'234.56", Decimal("1234.56")),
    ("1234.56",  Decimal("1234.56")),
    ("1234,56",  Decimal("1234.56")),
    ("1.234,56", Decimal("1234.56")),
    ("-9.00",    Decimal("-9.00")),
    ("",         Decimal("0")),
    ("   ",      Decimal("0")),
    ("0.00",     Decimal("0.00")),
])
def test_parse_decimal(raw, expected):
    assert _parse_decimal(raw) == expected


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("15-01-2024", date(2024, 1, 15)),
    ("2024-01-15", date(2024, 1, 15)),
    ("15.01.2024", date(2024, 1, 15)),
])
def test_parse_date_formats(raw, expected):
    assert _parse_date(raw) == expected


def test_parse_date_invalid():
    with pytest.raises(ValueError):
        _parse_date("not-a-date")


# ---------------------------------------------------------------------------
# All 16 confirmed transaction type labels are in the map
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label", [
    "Auszahlung",
    "Berichtigung Börsengeb.",
    "Capital Gain",
    "Depotgebühren",
    "Dividende",
    "Forex-Belastung",
    "Kauf",
    "Twint",
    "Stockdividende",
    "Spesen Steueraszug",
    "Rückzahlung",
    "Verkauf",
    "Wertpapierleihe",
    "Zahlung",
    "Zinsen auf Belastungen",
    "Zinsen auf Einlagen",
])
def test_all_confirmed_labels_mapped(label):
    assert label in TRANSACTION_TYPE_MAP, (
        f"{label!r} is not in TRANSACTION_TYPE_MAP"
    )


# ---------------------------------------------------------------------------
# Row count and type mapping
# ---------------------------------------------------------------------------

def test_parse_returns_correct_count(sample_csv):
    rows = list(parse_swissquote_csv(sample_csv))
    assert len(rows) == 17


@pytest.mark.parametrize("idx,expected_type", [
    (0,  "buy"),
    (1,  "dividend"),
    (2,  "withholding_tax"),
    (3,  "sell"),
    (4,  "stock_dividend"),
    (5,  "capital_gain_distribution"),
    (6,  "securities_lending_income"),
    (7,  "credit_interest"),
    (8,  "debit_interest"),
    (9,  "redemption"),
    (10, "fx_debit"),
    (11, "custody_fee"),
    (12, "exchange_fee_correction"),
    (13, "tax_statement_fee"),
    (14, "withdrawal"),
    (15, "twint_payment"),
    (16, "payment"),
])
def test_transaction_types(sample_csv, idx, expected_type):
    rows = list(parse_swissquote_csv(sample_csv))
    assert rows[idx].transaction_type == expected_type


# ---------------------------------------------------------------------------
# Specific field values
# ---------------------------------------------------------------------------

def test_buy_fields(sample_csv):
    rows = list(parse_swissquote_csv(sample_csv))
    buy = rows[0]
    assert buy.isin == "IE00B3RBWM25"
    assert buy.symbol == "VWRL"
    assert buy.date == date(2024, 1, 15)
    assert buy.quantity == Decimal("10")
    assert buy.unit_price == Decimal("105.20")
    assert buy.costs == Decimal("9.00")
    assert buy.net_amount == Decimal("-1061.00")
    assert buy.currency == "CHF"
    assert buy.is_security_row
    assert not buy.is_cash_row
    assert not buy.is_income_row


def test_dividend_is_income(sample_csv):
    rows = list(parse_swissquote_csv(sample_csv))
    assert rows[1].is_income_row
    assert rows[1].is_security_row


def test_credit_interest_is_income(sample_csv):
    rows = list(parse_swissquote_csv(sample_csv))
    credit = rows[7]
    assert credit.is_income_row
    assert credit.is_cash_row


def test_debit_interest_is_not_income(sample_csv):
    rows = list(parse_swissquote_csv(sample_csv))
    debit = rows[8]
    assert not debit.is_income_row
    assert debit.is_cash_row


def test_custody_fee_is_cash(sample_csv):
    rows = list(parse_swissquote_csv(sample_csv))
    fee = rows[11]
    assert fee.is_cash_row
    assert not fee.is_security_row
    assert fee.isin == ""


def test_unknown_type_is_skipped(tmp_path):
    p = tmp_path / "unknown.csv"
    p.write_text(_make_csv([_row(typ="UnbekannterTyp")]), encoding="utf-8")
    assert list(parse_swissquote_csv(p)) == []


# ---------------------------------------------------------------------------
# Dividend / withholding-tax pairing
# ---------------------------------------------------------------------------

def test_dividend_paired_with_withholding_tax(sample_csv):
    rows  = list(parse_swissquote_csv(sample_csv))
    pairs = pair_dividends_and_taxes(rows)
    div_pair = next(p for p in pairs if p[0].transaction_type == "dividend")
    assert div_pair[1] is not None
    assert div_pair[1].transaction_type == "withholding_tax"
    assert div_pair[1].isin == div_pair[0].isin


def test_capital_gain_pairing_without_tax(sample_csv):
    # Capital Gain row in the sample has no accompanying withholding_tax row
    rows  = list(parse_swissquote_csv(sample_csv))
    pairs = pair_dividends_and_taxes(rows)
    cg_pair = next(p for p in pairs
                   if p[0].transaction_type == "capital_gain_distribution")
    assert cg_pair[1] is None


def test_buy_has_no_partner(sample_csv):
    rows  = list(parse_swissquote_csv(sample_csv))
    pairs = pair_dividends_and_taxes(rows)
    buy_pair = next(p for p in pairs if p[0].transaction_type == "buy")
    assert buy_pair[1] is None


def test_pair_count(sample_csv):
    rows  = list(parse_swissquote_csv(sample_csv))
    pairs = pair_dividends_and_taxes(rows)
    # 17 input rows; dividend+tax consumed as 1 pair  ->  16 output pairs
    assert len(pairs) == 16


# ---------------------------------------------------------------------------
# load_swissquote  (integration)
# ---------------------------------------------------------------------------

def test_load_swissquote(sample_csv):
    result = load_swissquote(sample_csv)
    assert len(result) == 17
    assert all(isinstance(t, SwissquoteTransaction) for t in result)


def test_load_swissquote_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_swissquote(tmp_path / "nonexistent.csv")
