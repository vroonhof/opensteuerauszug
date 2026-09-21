"""Phase-8 tests: self-contained HTML dashboard writer.

These lock the HTML writer's two hard invariants: Swiss number formatting
(``CHF 12'345.67`` with apostrophe thousands) and the KS 36 preparer-mode
gate (non-preparer exports must never contain KS36 content, traffic-light
classes, or the "Vorbereiter" marker).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from opensteuerauszug.render.tax_overview import (
    DA1Claim,
    FeeEvent,
    FXRateUsed,
    IncomeEvent,
    KS36Criterion,
    KS36Evidence,
    PositionSummary,
    TaxOverviewData,
    VerzeichnisLine,
    build_waterfall,
    format_chf,
    format_date,
    format_number,
    format_percent,
    render_html,
)
from opensteuerauszug.render.tax_overview.fifo import LotClose
from opensteuerauszug.render.tax_overview.orders import Order
from opensteuerauszug.render.tax_overview.waterfall import WaterfallLine

D = Decimal


# ---------------------------------------------------------------------------
# Swiss number formatting helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (D("0"), "CHF 0.00"),
        (D("1"), "CHF 1.00"),
        (D("999"), "CHF 999.00"),
        (D("1000"), "CHF 1'000.00"),
        (D("12345.67"), "CHF 12'345.67"),
        (D("1234567.89"), "CHF 1'234'567.89"),
        (D("-12345.67"), "-CHF 12'345.67"),
        (D("0.005"), "CHF 0.01"),  # ROUND_HALF_UP
    ],
)
def test_format_chf_uses_swiss_apostrophe_grouping(value: Decimal, expected: str) -> None:
    assert format_chf(value) == expected


def test_format_number_default_two_decimals() -> None:
    assert format_number(D("1234567.891")) == "1'234'567.89"


def test_format_number_zero_decimals() -> None:
    assert format_number(D("12345"), decimals=0) == "12'345"


def test_format_number_four_decimals_for_unit_prices() -> None:
    assert format_number(D("123.4567"), decimals=4) == "123.4567"


def test_format_percent_converts_fraction_to_percent() -> None:
    assert format_percent(D("0.15")) == "15.0%"
    assert format_percent(D("0.075")) == "7.5%"


def test_format_date_german_order() -> None:
    assert format_date(date(2025, 3, 28)) == "28.03.2025"
    assert format_date(None) == ""


# ---------------------------------------------------------------------------
# Document structure + CSS variables
# ---------------------------------------------------------------------------


def _minimal_data(*, preparer_mode: bool = False) -> TaxOverviewData:
    return TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=preparer_mode,
        opening_value_chf=D("100000"),
        closing_value_chf=D("115000"),
        waterfall=build_waterfall(
            opening=D("100000"),
            closing=D("115000"),
            inflows=[WaterfallLine("Dividenden", D("5000"), "inflow")],
            outflows=[WaterfallLine("Gebühren", D("200"), "outflow")],
        ),
    )


def _rich_data(*, preparer_mode: bool) -> TaxOverviewData:
    dt = datetime(2025, 4, 15, 14, 30, tzinfo=timezone.utc)
    data = _minimal_data(preparer_mode=preparer_mode)
    data.positions = [
        PositionSummary(
            isin="US0378331005",
            symbol="AAPL",
            description="Apple Inc.",
            quantity_closing=D("50"),
            currency="USD",
            price_closing_local=D("189.12"),
            price_closing_chf=D("165.22"),
            market_value_chf=D("8261.00"),
        ),
    ]
    data.orders = [
        Order(
            order_id="ib:12345",
            symbol="AAPL",
            side="BUY",
            total_quantity=D("50"),
            avg_price=D("150.0000"),
            total_money=D("7500"),
            total_commission=D("1.50"),
            currency="USD",
            earliest_fill_time=dt,
            latest_fill_time=dt,
            asset_category="STK",
            isin="US0378331005",
            conid="265598",
            fills=(),
            grouping_method="ib_order_id",
        ),
    ]
    data.lot_closes = [
        LotClose(
            lot_id="lot-1",
            symbol="AAPL",
            isin="US0378331005",
            currency="USD",
            opened_at=dt,
            closed_at=dt,
            quantity_closed=D("10"),
            cost_per_share=D("150"),
            proceeds_per_share=D("180"),
            opening_order_id="ib:11111",
            closing_order_id="ib:22222",
        ),
    ]
    data.dividends = [
        IncomeEvent(
            payment_date=date(2025, 5, 15),
            isin="US0378331005",
            symbol="AAPL",
            description="Apple Inc.",
            category="dividend",
            gross_local=D("12.00"),
            currency="USD",
            withholding_tax_local=D("1.80"),
            net_local=D("10.20"),
            gross_chf=D("10.50"),
            withholding_tax_chf=D("1.57"),
            net_chf=D("8.93"),
        ),
    ]
    data.interest = [
        IncomeEvent(
            payment_date=date(2025, 2, 1),
            isin=None,
            symbol="CASH",
            description="USD-Konto Zins",
            category="interest",
            gross_local=D("5.00"),
            currency="USD",
            withholding_tax_local=D("0"),
            net_local=D("5.00"),
            gross_chf=D("4.40"),
            withholding_tax_chf=D("0"),
            net_chf=D("4.40"),
        ),
    ]
    data.fees = [
        FeeEvent(
            fee_date=date(2025, 6, 1),
            kind="data",
            description="Market data fee",
            amount_local=D("10"),
            currency="USD",
            amount_chf=D("8.80"),
        ),
    ]
    data.fx_rates = [
        FXRateUsed(
            currency="USD", reference_date=date(2025, 12, 31), rate=D("0.9012"), source="kursliste"
        ),
    ]
    data.verzeichnis_lines = [
        VerzeichnisLine(
            form_field="A 1",
            investment_type="Aktie",
            isin="US0378331005",
            description="Apple Inc.",
            quantity=D("50"),
            market_value_chf=D("8261"),
            income_gross_chf=D("10.50"),
            verrechnungssteuer_chf=D("0"),
            auslaendische_quellensteuer_chf=D("1.57"),
        ),
    ]
    data.da1_claims = [
        DA1Claim(
            isin="US0378331005",
            symbol="AAPL",
            description="Apple Inc.",
            source_country="US",
            gross_chf=D("10.50"),
            withholding_tax_chf=D("1.57"),
            withholding_rate=D("0.15"),
            treaty_rate_ceiling=D("0.15"),
            recoverable_chf=D("1.57"),
        ),
    ]
    if preparer_mode:
        data.ks36_criteria = [
            KS36Criterion(
                code="holding_period",
                label="Haltedauer",
                observed_value=D("0.35"),
                threshold=D("0.50"),
                unit="ratio",
                triggered=False,
                status="green",
            ),
            KS36Criterion(
                code="volume_ratio",
                label="Umsatz",
                observed_value=D("6.20"),
                threshold=D("5.00"),
                unit="ratio",
                triggered=True,
                status="red",
                note="Schwelle überschritten",
            ),
        ]
        data.ks36_evidence = [
            KS36Evidence(
                criterion_code="holding_period",
                category="short_held_close",
                description="AAPL 10 Aktien 14 Tage",
                value_chf=D("298"),
                evidence_date=date(2025, 3, 28),
            ),
        ]
    return data


def test_html_has_doctype_and_swiss_lang() -> None:
    html = render_html(_minimal_data())
    assert html.startswith("<!doctype html>")
    assert '<html lang="de-CH">' in html


def test_html_title_includes_tax_year() -> None:
    html = render_html(_minimal_data())
    assert "<title>Steuer-Übersicht 2025</title>" in html


def test_html_embeds_css_variables_from_design_module() -> None:
    html = render_html(_minimal_data())
    # Every locked palette colour must appear as a CSS variable.
    assert "--color-ink:" in html
    assert "--color-primary:" in html
    assert "--color-paper-warm:" in html
    assert "--font-body:" in html


def test_html_is_self_contained_no_external_assets() -> None:
    """No external stylesheets, scripts, or image URLs."""
    html = render_html(_rich_data(preparer_mode=False))
    assert "<link" not in html
    assert "<script" not in html
    # http:// / https:// should not appear — everything inlined.
    assert "http://" not in html and "https://" not in html


def test_html_sections_appear_in_canonical_order() -> None:
    html = render_html(_rich_data(preparer_mode=False))
    expected_order = [
        'id="uebersicht"',
        'id="wertschriften"',
        'id="sg-verzeichnis"',
        'id="da1"',
        'id="kauf-verkauf"',
        'id="dividenden"',
        'id="zinsen"',
        'id="gebuehren"',
        'id="fx-kurse"',
    ]
    positions = [html.index(marker) for marker in expected_order]
    assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


def test_html_renders_kpi_tiles_with_chf_totals() -> None:
    html = render_html(_rich_data(preparer_mode=False))
    assert "Eröffnungswert" in html
    assert "Schlusswert" in html
    assert "Dividenden" in html
    assert "DA-1 rückforderbar" in html
    # Opening value should render as CHF 100'000.00 somewhere in the page.
    assert "CHF 100&#39;000.00" in html or "CHF 100'000.00" in html


def test_html_renders_waterfall_lines_including_residual() -> None:
    html = render_html(_minimal_data())
    assert "Opening value" in html
    assert "Dividenden" in html
    assert "Gebühren" in html
    assert "Closing value" in html
    assert "Differenz" in html


def test_html_renders_one_row_per_position() -> None:
    html = render_html(_rich_data(preparer_mode=False))
    assert "AAPL" in html
    assert "US0378331005" in html


def test_html_renders_dividends_and_interest_separately() -> None:
    html = render_html(_rich_data(preparer_mode=False))
    div_idx = html.index('id="dividenden"')
    int_idx = html.index('id="zinsen"')
    assert div_idx < int_idx
    # The dividend row (Apple) must live in the dividend section, not interest.
    apple_dividend_row = html.find("Apple Inc.", div_idx)
    assert div_idx < apple_dividend_row < int_idx


def test_html_escapes_untrusted_description_text() -> None:
    data = _minimal_data()
    data.positions = [
        PositionSummary(
            isin=None,
            symbol="X",
            description="<script>alert(1)</script>",
            quantity_closing=D("1"),
            currency="USD",
            price_closing_local=D("1"),
            price_closing_chf=D("1"),
            market_value_chf=D("1"),
        ),
    ]
    html = render_html(data)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# KS 36 preparer-mode gate (HTML equivalent of the xlsx hidden-sheet rule)
# ---------------------------------------------------------------------------


def test_non_preparer_html_has_no_ks36_section_even_with_ks36_data() -> None:
    data = _rich_data(preparer_mode=False)
    # Populate KS36 anyway; the render must drop it.
    data.ks36_criteria = [
        KS36Criterion(
            code="holding_period",
            label="Haltedauer",
            observed_value=D("0.35"),
            threshold=D("0.50"),
            unit="ratio",
            triggered=False,
            status="green",
        ),
    ]
    html = render_html(data)
    assert 'id="ks36"' not in html
    assert "KS 36" not in html
    assert "Vorbereiter" not in html


def test_non_preparer_html_never_uses_ampel_classes() -> None:
    """The HTML equivalent of the xlsx ampel-style invariant."""
    html = render_html(_rich_data(preparer_mode=False))
    for cls in ("ampel-green", "ampel-amber", "ampel-red"):
        # The CSS declaration is always present in <style>; what must never
        # appear in non-preparer output is the class *applied* to a cell.
        assert f'class="{cls}"' not in html
        assert f"class='{cls}'" not in html


def test_preparer_mode_renders_ks36_section_with_ampel_classes() -> None:
    html = render_html(_rich_data(preparer_mode=True))
    assert 'id="ks36"' in html
    assert "Vorbereiter-Modus" in html
    # Green (holding_period) and red (volume_ratio) both present as applied classes.
    assert 'class="ampel-green"' in html
    assert 'class="ampel-red"' in html


def test_preparer_mode_renders_ks36_evidence_rows() -> None:
    html = render_html(_rich_data(preparer_mode=True))
    ks36_idx = html.index('id="ks36"')
    assert "AAPL 10 Aktien 14 Tage" in html[ks36_idx:]
    assert "28.03.2025" in html[ks36_idx:]
