"""Generate synthetic tax-overview sample outputs for local inspection.

Synthetic fixture — no personal data, no real broker statement. Running
this script writes the xlsx, html, and pdf samples for both taxpayer
and preparer modes to ``docs/samples/tax_overview/`` from one
:class:`TaxOverviewData` so all three formats describe the same
portfolio.

Outputs are **gitignored**: this script is a local preview tool, not a
way to ship artifacts. Tax artifacts are treated as sensitive even when
synthetic, per repo policy.

Invoke from the repo root::

    python scripts/generate_tax_overview_samples.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

# Make sure the src layout is importable when run from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from opensteuerauszug.render.tax_overview import (  # noqa: E402
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
    render_html,
    render_pdf_cover,
    render_workbook,
)
from opensteuerauszug.render.tax_overview.fifo import LotClose  # noqa: E402
from opensteuerauszug.render.tax_overview.orders import Order  # noqa: E402
from opensteuerauszug.render.tax_overview.waterfall import WaterfallLine  # noqa: E402

D = Decimal

SAMPLE_DIR = REPO_ROOT / "docs" / "samples" / "tax_overview"


def _sample_data(*, preparer_mode: bool) -> TaxOverviewData:
    """Synthetic 2025 portfolio: one US equity, one CH equity, USD cash interest."""
    dt = lambda m, d: datetime(2025, m, d, 14, 30, tzinfo=timezone.utc)  # noqa: E731

    waterfall = build_waterfall(
        opening=D("100000"),
        closing=D("115950"),
        inflows=[
            WaterfallLine("Einzahlungen", D("10000"), "inflow"),
            WaterfallLine("Dividenden (brutto)", D("5200"), "inflow"),
            WaterfallLine("Zinsen", D("150"), "inflow"),
            WaterfallLine("Realisierte Gewinne", D("3800"), "inflow"),
        ],
        outflows=[
            WaterfallLine("Auszahlungen", D("2000"), "outflow"),
            WaterfallLine("Gebühren", D("420"), "outflow"),
            WaterfallLine("Quellensteuer", D("780"), "outflow"),
        ],
    )

    data = TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=preparer_mode,
        opening_value_chf=D("100000"),
        closing_value_chf=D("115950"),
        waterfall=waterfall,
    )

    data.positions = [
        PositionSummary(
            isin="US0378331005",
            symbol="AAPL",
            description="Apple Inc.",
            quantity_closing=D("60"),
            currency="USD",
            price_closing_local=D("189.12"),
            price_closing_chf=D("170.42"),
            market_value_chf=D("10225.20"),
        ),
        PositionSummary(
            isin="CH0012005267",
            symbol="NOVN",
            description="Novartis AG",
            quantity_closing=D("120"),
            currency="CHF",
            price_closing_local=D("88.54"),
            price_closing_chf=D("88.54"),
            market_value_chf=D("10624.80"),
        ),
    ]

    data.orders = [
        Order(
            order_id="ib:100001",
            symbol="AAPL",
            side="BUY",
            total_quantity=D("60"),
            avg_price=D("150.0000"),
            total_money=D("9000"),
            total_commission=D("1.50"),
            currency="USD",
            earliest_fill_time=dt(2, 4),
            latest_fill_time=dt(2, 4),
            asset_category="STK",
            isin="US0378331005",
            conid="265598",
            fills=(),
            grouping_method="ib_order_id",
        ),
        Order(
            order_id="ib:100002",
            symbol="NOVN",
            side="BUY",
            total_quantity=D("120"),
            avg_price=D("82.00"),
            total_money=D("9840"),
            total_commission=D("3.50"),
            currency="CHF",
            earliest_fill_time=dt(3, 18),
            latest_fill_time=dt(3, 18),
            asset_category="STK",
            isin="CH0012005267",
            conid="12345",
            fills=(),
            grouping_method="ib_order_id",
        ),
    ]

    data.lot_closes = [
        LotClose(
            lot_id="lot-aapl-1",
            symbol="AAPL",
            isin="US0378331005",
            currency="USD",
            opened_at=dt(2, 4),
            closed_at=dt(11, 12),
            quantity_closed=D("20"),
            cost_per_share=D("150"),
            proceeds_per_share=D("178.50"),
            opening_order_id="ib:100001",
            closing_order_id="ib:100050",
        ),
    ]

    data.dividends = [
        IncomeEvent(
            payment_date=date(2025, 5, 15),
            isin="US0378331005",
            symbol="AAPL",
            description="Apple Inc. dividend",
            category="dividend",
            gross_local=D("14.40"),
            currency="USD",
            withholding_tax_local=D("2.16"),
            net_local=D("12.24"),
            gross_chf=D("12.60"),
            withholding_tax_chf=D("1.89"),
            net_chf=D("10.71"),
        ),
        IncomeEvent(
            payment_date=date(2025, 3, 10),
            isin="CH0012005267",
            symbol="NOVN",
            description="Novartis AG dividend",
            category="dividend",
            gross_local=D("360.00"),
            currency="CHF",
            withholding_tax_local=D("126.00"),
            net_local=D("234.00"),
            gross_chf=D("360.00"),
            withholding_tax_chf=D("126.00"),
            net_chf=D("234.00"),
        ),
    ]

    data.interest = [
        IncomeEvent(
            payment_date=date(2025, 6, 30),
            isin=None,
            symbol="CASH",
            description="USD-Konto Zinsen H1",
            category="interest",
            gross_local=D("75.00"),
            currency="USD",
            withholding_tax_local=D("0"),
            net_local=D("75.00"),
            gross_chf=D("67.50"),
            withholding_tax_chf=D("0"),
            net_chf=D("67.50"),
        ),
        IncomeEvent(
            payment_date=date(2025, 12, 31),
            isin=None,
            symbol="CASH",
            description="USD-Konto Zinsen H2",
            category="interest",
            gross_local=D("82.50"),
            currency="USD",
            withholding_tax_local=D("0"),
            net_local=D("82.50"),
            gross_chf=D("82.50"),
            withholding_tax_chf=D("0"),
            net_chf=D("82.50"),
        ),
    ]

    data.fees = [
        FeeEvent(
            fee_date=date(2025, 1, 31),
            kind="data",
            description="IBKR market data",
            amount_local=D("10.00"),
            currency="USD",
            amount_chf=D("9.00"),
        ),
        FeeEvent(
            fee_date=date(2025, 7, 31),
            kind="platform",
            description="Platform fee",
            amount_local=D("20.00"),
            currency="USD",
            amount_chf=D("17.60"),
        ),
    ]

    data.fx_rates = [
        FXRateUsed(
            currency="USD", reference_date=date(2025, 3, 10), rate=D("0.9000"), source="kursliste"
        ),
        FXRateUsed(
            currency="USD", reference_date=date(2025, 5, 15), rate=D("0.8750"), source="kursliste"
        ),
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
            quantity=D("60"),
            market_value_chf=D("10225.20"),
            income_gross_chf=D("12.60"),
            verrechnungssteuer_chf=D("0"),
            auslaendische_quellensteuer_chf=D("1.89"),
        ),
        VerzeichnisLine(
            form_field="A 2",
            investment_type="Aktie",
            isin="CH0012005267",
            description="Novartis AG",
            quantity=D("120"),
            market_value_chf=D("10624.80"),
            income_gross_chf=D("360.00"),
            verrechnungssteuer_chf=D("126.00"),
            auslaendische_quellensteuer_chf=D("0"),
        ),
    ]

    data.da1_claims = [
        DA1Claim(
            isin="US0378331005",
            symbol="AAPL",
            description="Apple Inc.",
            source_country="US",
            gross_chf=D("12.60"),
            withholding_tax_chf=D("1.89"),
            withholding_rate=D("0.15"),
            treaty_rate_ceiling=D("0.15"),
            recoverable_chf=D("1.89"),
        ),
    ]

    if preparer_mode:
        data.ks36_criteria = [
            KS36Criterion(
                code="holding_period",
                label="Haltedauer < 6 Monate (Anteil)",
                observed_value=D("0.28"),
                threshold=D("0.50"),
                unit="ratio",
                triggered=False,
                status="green",
            ),
            KS36Criterion(
                code="volume_ratio",
                label="Umsatz / Portfolio-Durchschnitt",
                observed_value=D("1.40"),
                threshold=D("5.00"),
                unit="ratio",
                triggered=False,
                status="green",
            ),
            KS36Criterion(
                code="gains_income_ratio",
                label="Realisierte Gewinne / Einkommen",
                observed_value=D("0.12"),
                threshold=D("0.50"),
                unit="ratio",
                triggered=False,
                status="green",
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
                observed_value=D("0"),
                threshold=D("0"),
                unit="count",
                triggered=False,
                status="green",
            ),
        ]
        data.ks36_evidence = [
            KS36Evidence(
                criterion_code="holding_period",
                category="short_held_close",
                description="AAPL 20 Aktien, gehalten 9 Monate",
                value_chf=D("3000"),
                evidence_date=date(2025, 11, 12),
            ),
        ]

    return data


def _write_outputs(data: TaxOverviewData, label: str) -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    html = render_html(data)
    (SAMPLE_DIR / f"sample_dashboard_{label}.html").write_text(html, encoding="utf-8")

    wb = render_workbook(data)
    wb.save(SAMPLE_DIR / f"sample_dashboard_{label}.xlsx")

    (SAMPLE_DIR / f"sample_dashboard_{label}.pdf").write_bytes(render_pdf_cover(data))


def main() -> None:
    _write_outputs(_sample_data(preparer_mode=False), "taxpayer")
    _write_outputs(_sample_data(preparer_mode=True), "preparer")
    print(f"Wrote samples to {SAMPLE_DIR}")


if __name__ == "__main__":
    main()
