"""Tests for critical warnings rendering in the PDF output."""

import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from opensteuerauszug.model.critical_warning import (
    CriticalWarning,
    CriticalWarningCategory,
)
from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Institution,
    Client,
    ClientNumber,
)
from opensteuerauszug.render.render import (
    create_critical_warnings_flowables,
    create_critical_warnings_hint,
    render_tax_statement,
)
from opensteuerauszug.util.styles import get_custom_styles


@pytest.fixture
def sample_warnings():
    return [
        CriticalWarning(
            category=CriticalWarningCategory.MISSING_KURSLISTE,
            message="Security AAPL (US0378331005) was not found in the Kursliste.",
            source="KurslisteTaxValueCalculator",
            identifier="US0378331005",
        ),
        CriticalWarning(
            category=CriticalWarningCategory.UNMAPPED_SYMBOL,
            message="Symbol 'GOOG' could not be mapped to an ISIN or Valor number.",
            source="CleanupCalculator",
            identifier="GOOG",
        ),
    ]


@pytest.fixture
def tax_statement_with_warnings(sample_warnings):
    ts = TaxStatement(
        minorVersion=2,
        id="test-warnings-001",
        creationDate=datetime(2024, 3, 15, 10, 0, 0),
        taxPeriod=2024,
        periodFrom=date(2024, 1, 1),
        periodTo=date(2024, 12, 31),
        country="CH",
        canton="ZH",
        totalTaxValue=Decimal("0"),
        totalGrossRevenueA=Decimal("0"),
        totalGrossRevenueB=Decimal("0"),
        totalWithHoldingTaxClaim=Decimal("0"),
        institution=Institution(name="Test Broker"),
        client=[Client(clientNumber=ClientNumber("12345"), firstName="Test", lastName="User")],
    )
    ts.critical_warnings = sample_warnings
    return ts


def test_critical_warnings_flowables_empty_when_no_warnings():
    styles = get_custom_styles()
    result = create_critical_warnings_flowables([], styles, 720)
    assert result == []


def test_critical_warnings_flowables_returns_flowables(sample_warnings):
    styles = get_custom_styles()
    result = create_critical_warnings_flowables(sample_warnings, styles, 720)
    assert len(result) > 0, "Should produce flowables when warnings exist"


def test_critical_warnings_hint_empty_when_no_warnings():
    styles = get_custom_styles()
    result = create_critical_warnings_hint([], styles)
    assert result == []


def test_critical_warnings_hint_returns_flowables(sample_warnings):
    styles = get_custom_styles()
    result = create_critical_warnings_hint(sample_warnings, styles)
    assert len(result) > 0, "Should produce flowables when warnings exist"


def test_render_pdf_with_critical_warnings(tax_statement_with_warnings):
    """Rendering a tax statement with critical warnings does not crash."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        render_tax_statement(
            tax_statement_with_warnings,
            output_path,
        )
        assert output_path.exists()
        assert output_path.stat().st_size > 0
    finally:
        output_path.unlink(missing_ok=True)


def test_render_pdf_without_critical_warnings():
    """Rendering a tax statement without warnings still works fine."""
    ts = TaxStatement(
        minorVersion=2,
        id="test-no-warnings",
        creationDate=datetime(2024, 3, 15, 10, 0, 0),
        taxPeriod=2024,
        periodFrom=date(2024, 1, 1),
        periodTo=date(2024, 12, 31),
        country="CH",
        canton="ZH",
        totalTaxValue=Decimal("0"),
        totalGrossRevenueA=Decimal("0"),
        totalGrossRevenueB=Decimal("0"),
        totalWithHoldingTaxClaim=Decimal("0"),
        institution=Institution(name="Test Broker"),
        client=[Client(clientNumber=ClientNumber("12345"), firstName="Test", lastName="User")],
    )
    assert ts.critical_warnings == []

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        render_tax_statement(ts, output_path)
        assert output_path.exists()
    finally:
        output_path.unlink(missing_ok=True)


def test_tax_statement_critical_warnings_default_empty():
    """TaxStatement.critical_warnings defaults to an empty list."""
    ts = TaxStatement(minorVersion=2)
    assert ts.critical_warnings == []


def test_tax_statement_critical_warnings_excluded_from_xml():
    """critical_warnings must not appear in the XML serialization."""
    ts = TaxStatement(
        minorVersion=2,
        id="test-excl",
        creationDate=datetime(2024, 1, 1),
        taxPeriod=2024,
        periodFrom=date(2024, 1, 1),
        periodTo=date(2024, 12, 31),
        country="CH",
        canton="ZH",
        totalTaxValue=Decimal("0"),
        totalGrossRevenueA=Decimal("0"),
        totalGrossRevenueB=Decimal("0"),
        totalWithHoldingTaxClaim=Decimal("0"),
    )
    ts.critical_warnings.append(
        CriticalWarning(
            category=CriticalWarningCategory.OTHER,
            message="test",
            source="test",
        )
    )
    xml_bytes = ts.to_xml_bytes()
    assert b"critical_warnings" not in xml_bytes
    assert b"CriticalWarning" not in xml_bytes
