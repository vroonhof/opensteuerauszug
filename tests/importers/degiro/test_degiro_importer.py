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

from opensteuerauszug.importers.degiro.degiro_importer import (
    DegiroImporter,
    _TRADE_RE,
    _normalize_number,
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
])
def test_trade_re_matches(desc, action, qty, price, currency):
    m = _TRADE_RE.match(desc)
    assert m is not None, f"_TRADE_RE should match {desc!r}"
    assert m.group(1) == action
    assert m.group(2) == qty
    assert m.group(4) == price
    assert m.group(5) == currency


@pytest.mark.parametrize("raw,expected", [
    ("60", "60"),
    ("1'000", "1000"),
    ("1'000.50", "1000.50"),
    ("20.08", "20.08"),
    ("1.000,50", "1000.50"),
    ("20,08", "20.08"),
])
def test_normalize_number(raw, expected):
    assert _normalize_number(raw) == expected

