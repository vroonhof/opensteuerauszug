"""Integration tests for the Degiro importer.

These tests run against sample data discovered via the standard sample-discovery
mechanism (tests/samples/import/degiro/, private/samples/import/degiro/, or
EXTRA_SAMPLE_DIR/import/degiro/).  See design/testing.md for details.
"""

import os
import re
from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.importers.degiro._number import normalize_number
from opensteuerauszug.importers.degiro.degiro_importer import (
    DegiroImporter,
    _TRADE_RE,
)
from tests.utils.samples import get_sample_dirs

SAMPLE_DIRS = get_sample_dirs("import/degiro", extensions=[".csv"])

PERIOD_FROM = date(2023, 1, 1)
PERIOD_TO = date(2023, 12, 31)


def _detect_tax_year(sample_dir: str) -> int:
    """Detect the tax year from filenames in the sample directory."""
    for filename in os.listdir(sample_dir):
        match = re.search(r"_(20[2-3]\d)\b", filename)
        if match:
            return int(match.group(1))
    return 2023  # Default fallback for DEGIRO samples


@pytest.mark.parametrize("sample_dir", SAMPLE_DIRS)
@pytest.mark.integration
def test_degiro_import_integration(sample_dir):
    """Import each discovered sample directory and verify basic structure."""
    tax_year = _detect_tax_year(sample_dir)
    period_from = date(tax_year, 1, 1)
    period_to = date(tax_year, 12, 31)

    importer = DegiroImporter(
        period_from=period_from,
        period_to=period_to,
        account_settings_list=[],
    )
    statement = importer.import_dir(sample_dir)

    assert statement is not None, f"TaxStatement should not be None for {sample_dir}"
    assert statement.periodFrom == period_from
    assert statement.periodTo == period_to
    assert statement.taxPeriod == tax_year
    assert statement.institution is not None
    assert statement.institution.name == "DEGIRO"

    if statement.listOfSecurities:
        assert statement.listOfSecurities.depot
        for depot in statement.listOfSecurities.depot:
            assert depot.depotNumber is not None
            for security in depot.security:
                assert security.securityName is not None
                assert security.currency is not None
                assert isinstance(security.currency, str) and len(security.currency) == 3

    if statement.listOfBankAccounts:
        assert statement.listOfBankAccounts.bankAccount
        for ba in statement.listOfBankAccounts.bankAccount:
            assert ba.bankAccountNumber is not None
            assert ba.bankAccountCurrency is not None
            assert isinstance(ba.bankAccountCurrency, str) and len(ba.bankAccountCurrency) == 3


# ---------------------------------------------------------------------------
# Non-sample tests
# ---------------------------------------------------------------------------


def test_import_dir_raises_on_missing_files(tmp_path):
    importer = DegiroImporter(
        period_from=PERIOD_FROM,
        period_to=PERIOD_TO,
        account_settings_list=[],
    )
    with pytest.raises(FileNotFoundError):
        importer.import_dir(str(tmp_path))


def test_dividend_and_withholding_tax_become_separate_payments(tmp_path):
    """A dividend and its matching tax row must not be merged into one payment.

    payment_reconciliation_calculator._accumulate_broker() treats any payment
    carrying withholding fields as tax-only and returns before accounting for
    its dividend amount, so a merged payment would make the dividend vanish
    from broker-side reconciliation (matching IBKR/Fidelity's convention of
    one payment per cash event fixes this).
    """
    account_csv = tmp_path / "Account.csv"
    account_csv.write_text(
        "Date,Time,Value date,Product,ISIN,Description,FX,Change,,Balance,,Order Id\n"
        "19-04-2025,08:37,16-04-2025,COCA-COLA CO,US1912161007,Dividend,,USD,0.24,USD,0.24,\n"
        "19-04-2025,08:40,16-04-2025,COCA-COLA CO,US1912161007,Dividend Tax,,USD,-0.04,USD,0.20,\n",
        encoding="utf-8",
    )
    portfolio_csv = tmp_path / "Portfolio.csv"
    portfolio_csv.write_text(
        "Product,Symbol/ISIN,Amount,Closing,Local value,,Value in CHF\n"
        "COCA-COLA CO,US1912161007,10,60.00,USD,600.00,540.00\n",
        encoding="utf-8",
    )
    importer = DegiroImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )

    statement = importer.import_files(str(account_csv), str(portfolio_csv))

    depot = statement.listOfSecurities.depot[0]
    security = depot.security[0]
    assert len(security.payment) == 2

    dividend_payment = next(p for p in security.payment if p.broker_label_original == "Dividend")
    tax_payment = next(p for p in security.payment if p.broker_label_original == "Dividend Tax")

    assert dividend_payment.amount == Decimal("0.24")
    assert dividend_payment.withHoldingTaxClaim is None
    assert dividend_payment.nonRecoverableTaxAmountOriginal is None

    assert tax_payment.nonRecoverableTaxAmountOriginal == Decimal("0.04")


@pytest.mark.parametrize("additional_usd_balance", [None, "25.50", "-25.50", "-200.00"])
def test_cash_balances_are_aggregated_into_one_account_per_currency(
    tmp_path, additional_usd_balance
):
    account_csv = tmp_path / "Account.csv"
    account_csv.write_text(
        "Date,Time,Value date,Product,ISIN,Description,FX,Change,,Balance,,Order Id\n",
        encoding="utf-8",
    )
    portfolio_csv = tmp_path / "Portfolio.csv"
    portfolio_csv.write_text(
        "Product,Symbol/ISIN,Amount,Closing,Local value,,Value in CHF\n"
        "CASH & CASH FUND & FTX CASH (CHF),,,,CHF,500.00,500.00\n"
        "CASH & CASH FUND & FTX CASH (USD),,,,USD,200.00,180.00\n"
        + (
            f"CASH & CASH FUND & FTX CASH (USD),,,,USD,{additional_usd_balance},0.00\n"
            if additional_usd_balance is not None
            else ""
        ),
        encoding="utf-8",
    )
    importer = DegiroImporter(
        period_from=PERIOD_FROM,
        period_to=PERIOD_TO,
        account_settings_list=[],
    )

    statement = importer.import_files(str(account_csv), str(portfolio_csv))

    assert statement.listOfBankAccounts is not None
    accounts = statement.listOfBankAccounts.bankAccount
    assert len(accounts) == 2
    assert len({account.bankAccountNumber for account in accounts}) == 2
    balances = {}
    for account in accounts:
        assert account.taxValue is not None
        balances[account.bankAccountCurrency] = account.taxValue.balance
    assert balances == {
        "CHF": Decimal("500.00"),
        "USD": Decimal("200.00") + Decimal(additional_usd_balance or "0"),
    }


# fmt: off
@pytest.mark.parametrize("desc,action,qty,price,currency", [
    ("Buy 60 iShares@20.08 EUR (IE00B3WJKG14)", "Buy", "60", "20.08", "EUR"),
    ("Sell 10 Vanguard@71.00 EUR (IE00B3XXRP09)", "Sell", "10", "71.00", "EUR"),
    ("Acquisto 80 iShares@8.306 EUR (IE00BYXPXL17)", "Acquisto", "80", "8.306", "EUR"),
    ("Vendita 120 iShares@20.279 EUR (IE00B1FZS350)", "Vendita", "120", "20.279", "EUR"),
    ("Acquisto 1'000 iShares@7.707 EUR (IE00BF4RFH31)", "Acquisto", "1'000", "7.707", "EUR"),
    ("Acquisto 1'094 iShares@5.7985 EUR (IE00BJK55C48)", "Acquisto", "1'094", "5.7985", "EUR"),
    # French
    ("Achat 60 iShares@20.08 EUR (IE00B3WJKG14)", "Achat", "60", "20.08", "EUR"),
    ("Vente 10 Vanguard@71.00 EUR (IE00B3XXRP09)", "Vente", "10", "71.00", "EUR"),
    # German
    ("Kauf 60 iShares@20.08 EUR (IE00B3WJKG14)", "Kauf", "60", "20.08", "EUR"),
    ("Verkauf 10 Vanguard@71.00 EUR (IE00B3XXRP09)", "Verkauf", "10", "71.00", "EUR"),
    ("Kauf 1.000 iShares@20,08 EUR (IE00B3WJKG14)", "Kauf", "1.000", "20,08", "EUR"),
    # German "zu je" variant (no inline product name)
    ("Kauf 3 zu je 64,91 EUR (IE00B8FHGS14)", "Kauf", "3", "64,91", "EUR"),
    ("Verkauf 20 zu je 3,95 EUR (DE000BY5LZ46)", "Verkauf", "20", "3,95", "EUR"),
    ("Verkauf 50 zu je 5 EUR (DE000PK5UFA4)", "Verkauf", "50", "5", "EUR"),
    # Swiss-locale typographic apostrophe and fund-merger legs
    ("Kauf 1’105 zu je 14.2055 EUR (LU1781541179)", "Kauf", "1’105", "14.2055", "EUR"),
    ("FUSION: Verkauf 1’105 zu je 14.2055 EUR (LU1781541179)", "Verkauf", "1’105", "14.2055", "EUR"),
    ("FUSION: Kauf 160 zu je 98.1 EUR (IE000BI8OT95)", "Kauf", "160", "98.1", "EUR"),
])
# fmt: on
def test_trade_re_matches(desc, action, qty, price, currency):
    m = _TRADE_RE.match(desc)
    assert m is not None, f"_TRADE_RE should match {desc!r}"
    assert m.group(1) == action
    assert m.group(2) == qty
    assert m.group(4) == price
    assert m.group(5) == currency


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("60", "60"),
        ("1'000", "1000"),
        ("1'000.50", "1000.50"),
        ("20.08", "20.08"),
        ("1.000,50", "1000.50"),
        ("20,08", "20.08"),
        ("1’105", "1105"),
        ("1’105.50", "1105.50"),
        ("12’345,67", "12345.67"),
    ],
)
def test_normalize_number(raw, expected):
    assert normalize_number(raw) == expected


def _stocks_by_isin(statement):
    out = {}
    for depot in statement.listOfSecurities.depot:
        for sec in depot.security:
            out[sec.isin] = sorted(sec.stock, key=lambda st: (st.referenceDate, st.mutation))
    return out


def test_fund_merger_legs_and_swiss_locale_rows(tmp_path):
    """FUSION legs move units from the absorbed fund to the absorbing fund.

    Uses the Swiss-German export wording (typographic apostrophe, "Auszahlung
    von"/"Überweisung auf" cash-account sweeps), which previously aborted the
    import as unknown rows.
    """
    account_csv = tmp_path / "Account.csv"
    account_csv.write_text(
        "Datum,Uhrzeit,Valutadatum,Produkt,ISIN,Beschreibung,FX,Änderung,,Saldo,,Order-ID\n"
        '20-06-2025,08:00,20-06-2025,,,"Überweisung auf Ihr Geldkonto bei der flatexDEGIRO Bank: 760.97 CHF",,,,CHF,0.00,\n'
        "18-06-2025,07:00,18-06-2025,NEW WORLD ETF,IE000BI8OT95,FUSION: Kauf 160 zu je 98.1 EUR (IE000BI8OT95),,EUR,-15696.00,EUR,0.00,\n"
        "18-06-2025,07:00,18-06-2025,OLD WORLD ETF,LU1781541179,FUSION: Verkauf 1’105 zu je 14.2055 EUR (LU1781541179),,EUR,15697.08,EUR,15697.08,\n"
        '10-03-2025,08:00,10-03-2025,,,"Auszahlung von Ihrem Geldkonto bei der flatexDEGIRO Bank: 4.71 CHF",,,,CHF,4.71,\n',
        encoding="utf-8",
    )
    portfolio_csv = tmp_path / "Portfolio.csv"
    portfolio_csv.write_text(
        "Produkt,Symbol/ISIN,Anzahl,Schlußkurs,Wert,,Wert in CHF\n"
        "NEW WORLD ETF,IE000BI8OT95,160,100.00,EUR,16000.00,15000.00\n"
        "CASH & CASH FUND & FTX CASH (CHF),,,,CHF,1’000.00,1’000.00\n",
        encoding="utf-8",
    )
    importer = DegiroImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )

    statement = importer.import_files(str(account_csv), str(portfolio_csv))
    stocks = _stocks_by_isin(statement)

    old = stocks["LU1781541179"]
    assert [s.quantity for s in old if s.mutation] == [Decimal("-1105")]
    old_balances = [s for s in old if not s.mutation]
    assert old_balances[0].referenceDate == date(2025, 1, 1)
    assert old_balances[0].quantity == Decimal("1105")
    assert old_balances[-1].quantity == 0

    new = stocks["IE000BI8OT95"]
    assert [s.quantity for s in new if s.mutation] == [Decimal("160")]
    new_balances = [s for s in new if not s.mutation]
    # No holding before the merger date; 160 units at year-end.
    assert all(b.quantity == 0 for b in new_balances if b.referenceDate <= date(2025, 6, 18))
    assert new_balances[-1].referenceDate == date(2026, 1, 1)
    assert new_balances[-1].quantity == Decimal("160")

    cash = statement.listOfBankAccounts.bankAccount
    assert sum(a.taxValue.balance for a in cash) == Decimal("1000.00")


def test_unparseable_trade_row_fails_loudly(tmp_path):
    account_csv = tmp_path / "Account.csv"
    account_csv.write_text(
        "Date,Time,Value date,Product,ISIN,Description,FX,Change,,Balance,,Order Id\n"
        "18-06-2025,07:00,18-06-2025,X,LU1781541179,Kauf some garbage,,EUR,-1.00,EUR,0.00,\n",
        encoding="utf-8",
    )
    portfolio_csv = tmp_path / "Portfolio.csv"
    portfolio_csv.write_text(
        "Product,Symbol/ISIN,Amount,Closing,Local value,,Value in CHF\n", encoding="utf-8"
    )
    importer = DegiroImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )
    with pytest.raises(ValueError, match="cannot parse description"):
        importer.import_files(str(account_csv), str(portfolio_csv))
