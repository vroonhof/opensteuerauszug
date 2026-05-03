"""Integration tests for the Degiro importer.

These tests run against the sample data in degiro_data/ at the repo root.
"""

import os
from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.importers.degiro.degiro_importer import DegiroImporter

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
DEGIRO_SAMPLE_DIR = os.path.join(REPO_ROOT, "degiro_data")


def _sample_available() -> bool:
    return (
        os.path.isfile(os.path.join(DEGIRO_SAMPLE_DIR, "Account.csv"))
        and os.path.isfile(os.path.join(DEGIRO_SAMPLE_DIR, "Portfolio.csv"))
    )


PERIOD_FROM = date(2023, 1, 1)
PERIOD_TO = date(2023, 12, 31)


@pytest.fixture(scope="module")
def statement():
    if not _sample_available():
        pytest.skip("degiro_data/ sample files not found")
    importer = DegiroImporter(
        period_from=PERIOD_FROM,
        period_to=PERIOD_TO,
        account_settings_list=[],
    )
    return importer.import_dir(DEGIRO_SAMPLE_DIR)


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

def test_statement_not_none(statement):
    assert statement is not None


def test_statement_period(statement):
    assert statement.periodFrom == PERIOD_FROM
    assert statement.periodTo == PERIOD_TO
    assert statement.taxPeriod == 2023


def test_statement_institution(statement):
    assert statement.institution is not None
    assert statement.institution.name == "DEGIRO"


# ---------------------------------------------------------------------------
# Securities
# ---------------------------------------------------------------------------

def test_has_securities(statement):
    assert statement.listOfSecurities is not None
    assert statement.listOfSecurities.depot
    assert len(statement.listOfSecurities.depot) > 0


def _all_securities(statement):
    secs = []
    for depot in statement.listOfSecurities.depot:
        secs.extend(depot.security)
    return secs


def _isin_set(statement) -> set:
    return {s.isin for s in _all_securities(statement) if s.isin}


def test_portfolio_securities_present(statement):
    """All ISINs from Portfolio.csv that were not delisted should appear."""
    expected = {
        "US0079031078",  # AMD
        "US34959E1091",  # Fortinet
        "US88160R1014",  # Tesla
        "IE00BK5BQT80",  # Vanguard FTSE All-World
        "IE00B3XXRP09",  # Vanguard S&P 500
        "IE00BKM4GZ66",  # iShares MSCI EM IMI
        "IE00B4L5Y983",  # iShares Core MSCI World
        "IE00B3WJKG14",  # iShares S&P 500 Info Tech
    }
    present = _isin_set(statement)
    missing = expected - present
    assert not missing, f"Missing ISINs: {missing}"


def test_activision_blizzard_present(statement):
    """Activision (delisted) must appear even though it's absent from Portfolio.csv."""
    assert "US00507V1098" in _isin_set(statement)


def test_security_categories(statement):
    """ETFs and UCITS funds must be FUND; pure equities must be SHARE."""
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    # ETFs / UCITS
    for isin in ["IE00BK5BQT80", "IE00B3XXRP09", "IE00BKM4GZ66", "IE00B4L5Y983"]:
        assert by_isin[isin].securityCategory == "FUND", (
            f"{isin} should be FUND"
        )
    # US stocks
    for isin in ["US0079031078", "US34959E1091", "US88160R1014"]:
        assert by_isin[isin].securityCategory == "SHARE", (
            f"{isin} should be SHARE"
        )


def test_country_derived_from_isin(statement):
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    assert by_isin["IE00B3XXRP09"].country == "IE"
    assert by_isin["US00507V1098"].country == "US"


# ---------------------------------------------------------------------------
# Trades / mutations
# ---------------------------------------------------------------------------

def test_ishares_em_imi_partial_fills_aggregated(statement):
    """Two partial fills of 107+112 = 219 shares should be combined."""
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    em_imi = by_isin["IE00BKM4GZ66"]
    mutations = [st for st in em_imi.stock if st.mutation]
    total_qty = sum(st.quantity for st in mutations)
    assert total_qty == Decimal("219"), (
        f"Expected net buy of 219, got {total_qty}"
    )


def test_activision_delisting_mutation(statement):
    """Activision delisting should produce a negative-qty mutation."""
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    act = by_isin["US00507V1098"]
    mutations = [st for st in act.stock if st.mutation]
    sell_mutations = [st for st in mutations if st.quantity < 0]
    assert sell_mutations, "No negative mutation found for Activision delisting"
    assert any(st.quantity == Decimal("-10") for st in sell_mutations)


def test_activision_opening_balance(statement):
    """Activision had 10 shares at start of period (bought prior to 2023)."""
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    act = by_isin["US00507V1098"]
    # Opening balance stock (mutation=False at period_from)
    opening = [st for st in act.stock if not st.mutation and st.referenceDate == PERIOD_FROM]
    assert opening, "No opening balance stock for Activision"
    assert opening[0].quantity == Decimal("10")


def test_activision_closing_balance_zero(statement):
    """Activision was delisted so closing balance must be zero."""
    end_plus_one = date(2024, 1, 1)
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    act = by_isin["US00507V1098"]
    closing = [st for st in act.stock if not st.mutation and st.referenceDate == end_plus_one]
    assert closing, "No closing balance stock for Activision"
    assert closing[0].quantity == Decimal("0")


# ---------------------------------------------------------------------------
# Payments / dividends
# ---------------------------------------------------------------------------

def test_vanguard_sp500_dividends(statement):
    """Vanguard S&P 500 should have 3 dividend payments in 2023."""
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    vsp = by_isin["IE00B3XXRP09"]
    divs = [p for p in vsp.payment if p.broker_label_original == "Dividend"]
    assert len(divs) == 3


def test_activision_dividend_present(statement):
    """Activision should have a dividend payment."""
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    act = by_isin["US00507V1098"]
    divs = [p for p in act.payment if p.broker_label_original == "Dividend"]
    assert len(divs) == 1
    assert divs[0].amount == Decimal("9.90")
    assert divs[0].amountCurrency == "USD"


def test_activision_withholding_tax(statement):
    """Activision's dividend should carry nonRecoverableTaxAmountOriginal from Dividend Tax row."""
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    act = by_isin["US00507V1098"]
    divs = [p for p in act.payment if p.broker_label_original == "Dividend"]
    assert divs[0].nonRecoverableTaxAmountOriginal == Decimal("1.49")


def test_activision_corporate_cash(statement):
    """Activision corporate action cash settlement should appear as a payment."""
    by_isin = {s.isin: s for s in _all_securities(statement) if s.isin}
    act = by_isin["US00507V1098"]
    corporate = [
        p for p in act.payment
        if p.broker_label_original == "Corporate Action Cash Settlement"
    ]
    assert len(corporate) == 1
    assert corporate[0].amount == Decimal("950.00")


# ---------------------------------------------------------------------------
# Cash / bank accounts
# ---------------------------------------------------------------------------

def test_has_bank_accounts(statement):
    assert statement.listOfBankAccounts is not None
    ba_list = statement.listOfBankAccounts.bankAccount
    assert ba_list and len(ba_list) > 0


def test_cash_closing_balance(statement):
    ba_list = statement.listOfBankAccounts.bankAccount
    chf_accounts = [b for b in ba_list if b.bankAccountCurrency == "CHF"]
    assert chf_accounts, "No CHF bank account found"
    tax_val = chf_accounts[0].taxValue
    assert tax_val is not None
    assert tax_val.balance == Decimal("895.08")


# ---------------------------------------------------------------------------
# Import from explicit files
# ---------------------------------------------------------------------------

def test_import_files_equivalent_to_import_dir():
    """import_files() and import_dir() should yield identical results."""
    if not _sample_available():
        pytest.skip("degiro_data/ sample files not found")
    importer = DegiroImporter(
        period_from=PERIOD_FROM,
        period_to=PERIOD_TO,
        account_settings_list=[],
    )
    account_csv = os.path.join(DEGIRO_SAMPLE_DIR, "Account.csv")
    portfolio_csv = os.path.join(DEGIRO_SAMPLE_DIR, "Portfolio.csv")
    s1 = importer.import_files(account_csv, portfolio_csv)
    s2 = importer.import_dir(DEGIRO_SAMPLE_DIR)
    assert (s1.listOfSecurities is None) == (s2.listOfSecurities is None)
    if s1.listOfSecurities:
        assert len(list(_all_securities(s1))) == len(list(_all_securities(s2)))


def test_import_dir_raises_on_missing_files(tmp_path):
    importer = DegiroImporter(
        period_from=PERIOD_FROM,
        period_to=PERIOD_TO,
        account_settings_list=[],
    )
    with pytest.raises(FileNotFoundError):
        importer.import_dir(str(tmp_path))
