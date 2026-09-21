"""Phase-9 tests: single-page PDF cover writer.

The cover is a preparer-friendly executive summary. These tests lock the
two hard invariants: exactly one page, and third-party safety (no KS 36
reference when preparer_mode=False).
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from pypdf import PdfReader

from opensteuerauszug.render.tax_overview import (
    KS36Criterion,
    TaxOverviewData,
    build_waterfall,
    render_pdf_cover,
)
from opensteuerauszug.render.tax_overview.waterfall import WaterfallLine

D = Decimal


def _reconciled_data(**overrides) -> TaxOverviewData:
    base = dict(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=False,
        opening_value_chf=D("100000"),
        closing_value_chf=D("115000"),
        waterfall=build_waterfall(
            opening=D("100000"),
            closing=D("115000"),
            inflows=[WaterfallLine("Dividenden", D("15000"), "inflow")],
        ),
    )
    base.update(overrides)
    return TaxOverviewData(**base)


def _off_by_waterfall() -> TaxOverviewData:
    """Waterfall with a residual well beyond ±CHF 1 tolerance."""
    return TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=False,
        opening_value_chf=D("100000"),
        closing_value_chf=D("120000"),
        waterfall=build_waterfall(
            opening=D("100000"),
            closing=D("120000"),
            inflows=[WaterfallLine("Dividenden", D("5000"), "inflow")],
        ),
    )


def _text_of(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def _page_count(pdf_bytes: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_pdf_bytes_start_with_pdf_magic() -> None:
    pdf = render_pdf_cover(_reconciled_data())
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")


def test_pdf_has_exactly_one_page() -> None:
    assert _page_count(render_pdf_cover(_reconciled_data())) == 1


def test_pdf_minimum_data_still_renders_one_page() -> None:
    data = TaxOverviewData(
        tax_year=2025,
        broker="ibkr",
        preparer_mode=False,
        opening_value_chf=D("0"),
        closing_value_chf=D("0"),
        waterfall=build_waterfall(opening=D("0"), closing=D("0")),
    )
    pdf = render_pdf_cover(data)
    assert _page_count(pdf) == 1


def test_pdf_metadata_uses_tax_year_and_broker() -> None:
    reader = PdfReader(io.BytesIO(render_pdf_cover(_reconciled_data())))
    meta = reader.metadata or {}
    title = str(meta.get("/Title") or "")
    subject = str(meta.get("/Subject") or "")
    assert "2025" in title
    assert "ibkr" in subject


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


def test_pdf_contains_title_and_tax_year() -> None:
    text = _text_of(render_pdf_cover(_reconciled_data()))
    assert "Steuer-Übersicht" in text
    assert "2025" in text


def test_pdf_mentions_broker() -> None:
    text = _text_of(render_pdf_cover(_reconciled_data(broker="schwab")))
    assert "schwab" in text.lower()


def test_pdf_embeds_waterfall_opening_and_closing_labels() -> None:
    text = _text_of(render_pdf_cover(_reconciled_data()))
    assert "Opening value" in text
    assert "Closing value" in text
    assert "Vermögenszuwachs" in text


def test_pdf_shows_swiss_formatted_chf_figures() -> None:
    text = _text_of(render_pdf_cover(_reconciled_data()))
    # Opening 100'000.00 must appear in Swiss format.
    assert "100'000.00" in text


# ---------------------------------------------------------------------------
# Reconciliation marker
# ---------------------------------------------------------------------------


def test_pdf_reconciled_marker_when_within_tolerance() -> None:
    text = _text_of(render_pdf_cover(_reconciled_data()))
    assert "Abstimmung" in text
    assert "✓" in text


def test_pdf_flags_residual_when_outside_tolerance() -> None:
    text = _text_of(render_pdf_cover(_off_by_waterfall()))
    assert "ausserhalb Toleranz" in text
    # Residual is 120000 - (100000 + 5000) = 15000 CHF
    assert "15'000.00" in text


# ---------------------------------------------------------------------------
# KS 36 preparer-mode gate (third-party safety)
# ---------------------------------------------------------------------------


def test_non_preparer_pdf_contains_no_ks36_reference() -> None:
    data = _reconciled_data()
    # Populate KS36 data; the render must still omit it.
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
    text = _text_of(render_pdf_cover(data))
    assert "KS 36" not in text
    assert "Vorbereiter" not in text
    assert "Selbstprüfung" not in text


def test_preparer_mode_pdf_shows_ks36_summary_line() -> None:
    data = _reconciled_data(preparer_mode=True)
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
        ),
    ]
    text = _text_of(render_pdf_cover(data))
    assert "KS 36 Selbstprüfung" in text
    assert "Vorbereiter-Modus" in text
    assert "2 Kriterien" in text
    # Individual criterion *details* belong to the hidden xlsx sheet; the
    # cover shows only the aggregated traffic-light count.
    assert "1 grün" in text
    assert "1 rot" in text


def test_preparer_mode_pdf_has_still_one_page() -> None:
    data = _reconciled_data(preparer_mode=True)
    assert _page_count(render_pdf_cover(data)) == 1
