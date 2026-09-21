"""Phase-6 tests: SG-specific sheets (Wertschriftenverzeichnis + DA-1).

Exercises the two tax-office-facing sheets and their impact on the
dashboard KPI tiles. The tab order is also re-asserted here because phase 6
inserts the SG sheets between Wertschriften and Kauf_Verkauf.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from opensteuerauszug.render.tax_overview.data import (
    DA1Claim,
    TaxOverviewData,
    VerzeichnisLine,
)
from opensteuerauszug.render.tax_overview.design import StyleName
from opensteuerauszug.render.tax_overview.render import render_workbook
from opensteuerauszug.render.tax_overview.waterfall import build_waterfall

D = Decimal


@pytest.fixture
def data_with_sg() -> TaxOverviewData:
    verzeichnis = [
        VerzeichnisLine(
            form_field="Z1 Reihe 1",
            investment_type="Aktie",
            isin="US0378331005",
            description="Apple Inc.",
            quantity=D("10"),
            market_value_chf=D("1890"),
            income_gross_chf=D("22.50"),
            verrechnungssteuer_chf=D("0"),
            auslaendische_quellensteuer_chf=D("3.38"),
        ),
        VerzeichnisLine(
            form_field="Z1 Reihe 2",
            investment_type="Aktie",
            isin="CH0012032048",
            description="Roche Holding AG",
            quantity=D("5"),
            market_value_chf=D("1250"),
            income_gross_chf=D("45.00"),
            verrechnungssteuer_chf=D("15.75"),
            auslaendische_quellensteuer_chf=D("0"),
        ),
    ]
    claims = [
        DA1Claim(
            isin="US0378331005",
            symbol="AAPL",
            description="Apple Inc. dividend",
            source_country="US",
            gross_chf=D("22.50"),
            withholding_tax_chf=D("3.38"),
            withholding_rate=D("0.15"),
            treaty_rate_ceiling=D("0.15"),
            recoverable_chf=D("3.38"),
        ),
        DA1Claim(
            isin="DE0007164600",
            symbol="SAP",
            description="SAP SE dividend",
            source_country="DE",
            gross_chf=D("100.00"),
            withholding_tax_chf=D("26.375"),  # DE domestic
            withholding_rate=D("0.26375"),
            treaty_rate_ceiling=D("0.15"),
            recoverable_chf=D("15.00"),  # capped at treaty ceiling
        ),
    ]
    return TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=False,
        opening_value_chf=D("100000"),
        closing_value_chf=D("115000"),
        waterfall=build_waterfall(
            opening=D("100000"), closing=D("115000"), inflows=[], outflows=[]
        ),
        verzeichnis_lines=verzeichnis,
        da1_claims=claims,
    )


# ---------------------------------------------------------------------------
# Tab order & sheet presence
# ---------------------------------------------------------------------------


def test_sg_sheets_sit_between_wertschriften_and_kauf_verkauf(
    data_with_sg: TaxOverviewData,
) -> None:
    wb = render_workbook(data_with_sg)
    assert wb.sheetnames == [
        "Übersicht",
        "Wertschriften",
        "SG_Verzeichnis",
        "DA1_Hilfstabelle",
        "Kauf_Verkauf",
        "Dividenden",
        "Zinsen",
        "Gebühren",
        "FX_Kurse",
    ]


# ---------------------------------------------------------------------------
# SG_Verzeichnis
# ---------------------------------------------------------------------------


def test_verzeichnis_has_one_row_per_line_with_all_columns(
    data_with_sg: TaxOverviewData,
) -> None:
    wb = render_workbook(data_with_sg)
    ws = wb["SG_Verzeichnis"]
    assert ws.cell(row=1, column=1).value == "SG-Formular"
    assert ws.cell(row=1, column=1).style == StyleName.HEADER
    assert ws.max_row == 3  # 2 lines + header

    # First row (Apple)
    assert ws.cell(row=2, column=1).value == "Z1 Reihe 1"
    assert ws.cell(row=2, column=3).value == "US0378331005"
    assert ws.cell(row=2, column=6).value == D("1890")
    assert ws.cell(row=2, column=8).value == D("0")  # no VSt on US stock
    assert ws.cell(row=2, column=9).value == D("3.38")

    # Second row (Roche — CH-source, has Verrechnungssteuer, no foreign WHT)
    assert ws.cell(row=3, column=8).value == D("15.75")
    assert ws.cell(row=3, column=9).value == D("0")


def test_verzeichnis_chf_columns_use_chf_style(
    data_with_sg: TaxOverviewData,
) -> None:
    wb = render_workbook(data_with_sg)
    ws = wb["SG_Verzeichnis"]
    # Columns 6, 7, 8, 9 are all CHF amounts.
    for col in (6, 7, 8, 9):
        assert ws.cell(row=2, column=col).style == StyleName.BODY_CHF


# ---------------------------------------------------------------------------
# DA1_Hilfstabelle
# ---------------------------------------------------------------------------


def test_da1_sheet_records_country_rates_and_recoverable(
    data_with_sg: TaxOverviewData,
) -> None:
    wb = render_workbook(data_with_sg)
    ws = wb["DA1_Hilfstabelle"]
    # Apple row: US, treaty 15%, full recovery
    assert ws.cell(row=2, column=4).value == "US"
    assert ws.cell(row=2, column=7).value == D("0.15")
    assert ws.cell(row=2, column=8).value == D("0.15")
    assert ws.cell(row=2, column=9).value == D("3.38")

    # SAP row: DE, actual 26.375%, treaty 15% → capped
    assert ws.cell(row=3, column=4).value == "DE"
    assert ws.cell(row=3, column=7).value == D("0.26375")
    assert ws.cell(row=3, column=8).value == D("0.15")
    assert ws.cell(row=3, column=9).value == D("15.00")


def test_da1_sheet_percent_columns_use_percent_style(
    data_with_sg: TaxOverviewData,
) -> None:
    wb = render_workbook(data_with_sg)
    ws = wb["DA1_Hilfstabelle"]
    assert ws.cell(row=2, column=7).style == StyleName.BODY_PERCENT
    assert ws.cell(row=2, column=8).style == StyleName.BODY_PERCENT


def test_da1_treaty_ceiling_may_be_blank() -> None:
    claim = DA1Claim(
        isin=None,
        symbol="UNKWN",
        description="Obscure security",
        source_country="ZZ",
        gross_chf=D("10"),
        withholding_tax_chf=D("2"),
        withholding_rate=D("0.20"),
        treaty_rate_ceiling=None,
        recoverable_chf=D("0"),
    )
    data = TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=False,
        opening_value_chf=D("0"),
        closing_value_chf=D("0"),
        waterfall=build_waterfall(opening=D("0"), closing=D("0")),
        da1_claims=[claim],
    )
    wb = render_workbook(data)
    ws = wb["DA1_Hilfstabelle"]
    # Ceiling cell is empty, not 0 — 0 would misleadingly imply "no treaty".
    assert ws.cell(row=2, column=8).value is None


# ---------------------------------------------------------------------------
# Übersicht integration: DA-1 total tile
# ---------------------------------------------------------------------------


def test_uebersicht_shows_da1_recoverable_total(
    data_with_sg: TaxOverviewData,
) -> None:
    wb = render_workbook(data_with_sg)
    ws = wb["Übersicht"]
    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    assert "DA-1 rückforderbar (CHF)" in labels
    # 3.38 + 15.00 = 18.38
    assert data_with_sg.total_da1_recoverable_chf() == D("18.38")
    # Find the DA-1 row and check the value column.
    for r in range(1, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == "DA-1 rückforderbar (CHF)":
            assert ws.cell(row=r, column=2).value == D("18.38")
            return
    pytest.fail("DA-1 KPI tile not rendered")


# ---------------------------------------------------------------------------
# Empty SG sections still produce header-only sheets
# ---------------------------------------------------------------------------


def test_empty_sg_sections_produce_header_only_sheets() -> None:
    minimal = TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=False,
        opening_value_chf=D("0"),
        closing_value_chf=D("0"),
        waterfall=build_waterfall(opening=D("0"), closing=D("0")),
    )
    wb = render_workbook(minimal)
    assert wb["SG_Verzeichnis"].max_row == 1
    assert wb["DA1_Hilfstabelle"].max_row == 1
