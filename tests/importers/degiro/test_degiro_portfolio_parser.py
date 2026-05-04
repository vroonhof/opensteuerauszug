"""Unit tests for the Degiro Portfolio.csv parser."""

from decimal import Decimal

from opensteuerauszug.importers.degiro.portfolio_csv_parser import (
    load_portfolio_csv,
)


SAMPLE_PORTFOLIO_CSV = """\
Product,Symbol/ISIN,Amount,Closing,Local value,,Value in CHF
CASH & CASH FUND & FTX CASH (CHF),,,,CHF,500.00,500.00
ADVANCED MICRO DEVICES INC,US0079031078,10,150.00,USD,1500.00,1350.00
VANGUARD FTSE ALL-WORLD UCITS - ...,IE00BK5BQT80,50,100.00,EUR,5000.00,4800.00
ISHARES CORE MSCI EM IMI UCITS E...,IE00BKM4GZ66,100,25.00,EUR,2500.00,2400.00
ISHARES CORE MSCI EM IMI UCITS E...,IE00BKM4GZ66,50,25.00,EUR,1250.00,1200.00
"""


def _write_temp_csv(tmp_path, content, filename="Portfolio.csv"):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_load_portfolio_csv_row_count(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_PORTFOLIO_CSV)
    entries = load_portfolio_csv(path)
    assert len(entries) == 5


def test_load_portfolio_csv_cash_row(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_PORTFOLIO_CSV)
    entries = load_portfolio_csv(path)
    cash = entries[0]
    assert cash.is_cash is True
    assert cash.isin == ""
    assert cash.local_currency == "CHF"
    assert cash.local_amount == Decimal("500.00")
    assert cash.value_chf == Decimal("500.00")


def test_load_portfolio_csv_security_row(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_PORTFOLIO_CSV)
    entries = load_portfolio_csv(path)
    amd = entries[1]
    assert amd.is_cash is False
    assert amd.isin == "US0079031078"
    assert amd.amount == Decimal("10")
    assert amd.closing_price == Decimal("150.00")
    assert amd.local_currency == "USD"
    assert amd.local_amount == Decimal("1500.00")
    assert amd.value_chf == Decimal("1350.00")


def test_load_portfolio_csv_etf_row(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_PORTFOLIO_CSV)
    entries = load_portfolio_csv(path)
    etf = entries[2]
    assert etf.isin == "IE00BK5BQT80"
    assert etf.local_currency == "EUR"
    assert etf.amount == Decimal("50")


def test_load_portfolio_csv_duplicate_isin_not_summed(tmp_path):
    """load_portfolio_csv does NOT merge duplicates; caller is responsible."""
    path = _write_temp_csv(tmp_path, SAMPLE_PORTFOLIO_CSV)
    entries = load_portfolio_csv(path)
    em_imi = [e for e in entries if e.isin == "IE00BKM4GZ66"]
    assert len(em_imi) == 2
    assert em_imi[0].amount == Decimal("100")
    assert em_imi[1].amount == Decimal("50")


def test_load_portfolio_csv_skips_blank_rows(tmp_path):
    content = (
        "Product,Symbol/ISIN,Amount,Closing,Local value,,Value in CHF\n"
        "CASH & CASH FUND & FTX CASH (CHF),,,,CHF,500.00,500.00\n"
        "\n"
        "ADVANCED MICRO DEVICES INC,US0079031078,10,150.00,USD,1500.00,1350.00\n"
    )
    path = _write_temp_csv(tmp_path, content)
    entries = load_portfolio_csv(path)
    assert len(entries) == 2


def test_load_portfolio_csv_no_closing_price_for_cash(tmp_path):
    path = _write_temp_csv(tmp_path, SAMPLE_PORTFOLIO_CSV)
    entries = load_portfolio_csv(path)
    cash = entries[0]
    assert cash.closing_price is None
