"""Phase-7 tests: hidden KS 36 sheets + preparer-mode gating.

The spec treats KS36 content as preparer-only: third-party exports must
never carry these sheets, and the visible workbook must never use
traffic-light fills. These tests lock both rules in.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.render.tax_overview.data import (
    KS36Criterion,
    KS36Evidence,
    TaxOverviewData,
)
from opensteuerauszug.render.tax_overview.design import StyleName
from opensteuerauszug.render.tax_overview.render import render_workbook
from opensteuerauszug.render.tax_overview.waterfall import build_waterfall

D = Decimal


def _criteria_sample() -> list[KS36Criterion]:
    return [
        KS36Criterion(
            code="holding_period",
            label="Haltedauer < 6 Monate (Anteil)",
            observed_value=D("0.35"),
            threshold=D("0.50"),
            unit="ratio",
            triggered=False,
            status="green",
            note="35 % der geschlossenen Lots unter 6 Monaten gehalten",
        ),
        KS36Criterion(
            code="volume_ratio",
            label="Umsatz / Portfolio-Durchschnitt",
            observed_value=D("6.20"),
            threshold=D("5.00"),
            unit="ratio",
            triggered=True,
            status="red",
            note="Umsatz 6.2× Portfolio → Schwelle überschritten",
        ),
        KS36Criterion(
            code="gains_income_ratio",
            label="Realisierte Gewinne / Nettoeinkommen",
            observed_value=D("0.45"),
            threshold=D("0.50"),
            unit="ratio",
            triggered=False,
            status="amber",
        ),
        KS36Criterion(
            code="leverage",
            label="Margin / Portfolio",
            observed_value=D("0.00"),
            threshold=D("0.00"),
            unit="ratio",
            triggered=False,
            status="green",
        ),
        KS36Criterion(
            code="derivatives",
            label="Derivate nicht zu Sicherungszwecken",
            observed_value=D("2"),
            threshold=D("0"),
            unit="count",
            triggered=True,
            status="amber",
            note="Zwei naked Puts geschrieben",
        ),
    ]


def _evidence_sample() -> list[KS36Evidence]:
    return [
        KS36Evidence(
            criterion_code="holding_period",
            category="short_held_close",
            description="AAPL 10 Aktien, gehalten 14 Tage",
            value_chf=D("298"),
            evidence_date=date(2025, 3, 28),
        ),
        KS36Evidence(
            criterion_code="derivatives",
            category="option_trade",
            description="AAPL naked put 180 strike",
            value_chf=D("45"),
            evidence_date=date(2025, 6, 1),
        ),
    ]


def _preparer_data() -> TaxOverviewData:
    return TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=True,
        opening_value_chf=D("100000"),
        closing_value_chf=D("115000"),
        waterfall=build_waterfall(opening=D("100000"), closing=D("115000")),
        ks36_criteria=_criteria_sample(),
        ks36_evidence=_evidence_sample(),
    )


def _non_preparer_data() -> TaxOverviewData:
    return TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=False,
        opening_value_chf=D("100000"),
        closing_value_chf=D("115000"),
        waterfall=build_waterfall(opening=D("100000"), closing=D("115000")),
        # Even if the caller populates KS36 data, the render must drop it
        # when preparer_mode is False (third-party safety).
        ks36_criteria=_criteria_sample(),
        ks36_evidence=_evidence_sample(),
    )


# ---------------------------------------------------------------------------
# Preparer-mode gating
# ---------------------------------------------------------------------------


def test_non_preparer_export_has_no_ks36_sheets_even_with_ks36_data() -> None:
    wb = render_workbook(_non_preparer_data())
    assert not any(name.startswith("_KS36") for name in wb.sheetnames)


def test_preparer_mode_adds_both_ks36_sheets() -> None:
    wb = render_workbook(_preparer_data())
    assert "_KS36_Criteria" in wb.sheetnames
    assert "_KS36_Evidence" in wb.sheetnames


def test_ks36_sheets_are_hidden_when_added() -> None:
    wb = render_workbook(_preparer_data())
    assert wb["_KS36_Criteria"].sheet_state == "hidden"
    assert wb["_KS36_Evidence"].sheet_state == "hidden"


def test_visible_sheets_are_unaffected_by_preparer_mode() -> None:
    """Toggling preparer mode must not re-order or alter the visible sheets."""
    wb_on = render_workbook(_preparer_data())
    wb_off = render_workbook(_non_preparer_data())
    visible_on = [n for n in wb_on.sheetnames if not n.startswith("_KS36")]
    assert visible_on == wb_off.sheetnames


# ---------------------------------------------------------------------------
# Criteria sheet content & traffic-light styling
# ---------------------------------------------------------------------------


def test_criteria_sheet_has_one_row_per_criterion() -> None:
    wb = render_workbook(_preparer_data())
    ws = wb["_KS36_Criteria"]
    assert ws.cell(row=1, column=1).value == "Kriterium"
    # 5 criteria + header
    assert ws.max_row == 6


def test_status_cell_uses_ks36_named_styles() -> None:
    wb = render_workbook(_preparer_data())
    ws = wb["_KS36_Criteria"]
    # Row 2 = holding_period, status=green
    assert ws.cell(row=2, column=5).value == "green"
    assert ws.cell(row=2, column=5).style == StyleName.KS36_GREEN
    # Row 3 = volume_ratio, red
    assert ws.cell(row=3, column=5).style == StyleName.KS36_RED
    # Row 4 = gains_income_ratio, amber
    assert ws.cell(row=4, column=5).style == StyleName.KS36_AMBER


def test_criterion_note_column_preserves_rationale() -> None:
    wb = render_workbook(_preparer_data())
    ws = wb["_KS36_Criteria"]
    assert ws.cell(row=3, column=6).value.startswith("Umsatz 6.2× Portfolio")


# ---------------------------------------------------------------------------
# Evidence sheet
# ---------------------------------------------------------------------------


def test_evidence_sheet_lists_each_evidence_row() -> None:
    wb = render_workbook(_preparer_data())
    ws = wb["_KS36_Evidence"]
    assert ws.max_row == 3  # 2 rows + header
    assert ws.cell(row=2, column=1).value == "holding_period"
    assert ws.cell(row=2, column=2).value == "short_held_close"
    assert ws.cell(row=2, column=4).value == D("298")
    assert ws.cell(row=2, column=5).value == date(2025, 3, 28)


# ---------------------------------------------------------------------------
# Spec invariant: traffic-light fills only on hidden KS36 sheets
# ---------------------------------------------------------------------------


def test_ampel_styles_never_appear_on_visible_sheets() -> None:
    """Every visible sheet must stay free of KS36_GREEN/AMBER/RED cells."""
    wb = render_workbook(_preparer_data())
    ampel_styles = {
        StyleName.KS36_GREEN,
        StyleName.KS36_AMBER,
        StyleName.KS36_RED,
    }
    for name in wb.sheetnames:
        if name.startswith("_KS36"):
            continue
        ws = wb[name]
        for row in ws.iter_rows():
            for cell in row:
                assert cell.style not in ampel_styles, (
                    f"Ampel style leaked onto visible sheet {name!r} "
                    f"at {cell.coordinate}: {cell.style}"
                )


# ---------------------------------------------------------------------------
# Empty KS36 data still creates hidden sheets (header only)
# ---------------------------------------------------------------------------


def test_preparer_mode_with_no_ks36_data_still_creates_hidden_sheets() -> None:
    data = TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=True,
        opening_value_chf=D("0"),
        closing_value_chf=D("0"),
        waterfall=build_waterfall(opening=D("0"), closing=D("0")),
    )
    wb = render_workbook(data)
    assert "_KS36_Criteria" in wb.sheetnames
    assert wb["_KS36_Criteria"].sheet_state == "hidden"
    assert wb["_KS36_Criteria"].max_row == 1  # header only
