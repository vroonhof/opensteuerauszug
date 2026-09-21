"""Phase-10 tests: docs and sample-generation smoke tests.

Keep the committed sample generator honest: its fixture must always
produce valid outputs in all three formats, and the documented
preparer-mode filename variant must exist. This runs the script without
writing to disk — we just import the generator and execute it on a temp
directory.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_tax_overview_samples.py"


@pytest.fixture
def sample_module(monkeypatch, tmp_path):
    """Load the generator script with SAMPLE_DIR redirected to a tmp path."""
    spec = importlib.util.spec_from_file_location("_sample_gen", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_sample_gen"] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SAMPLE_DIR", tmp_path)
    yield module
    sys.modules.pop("_sample_gen", None)


def test_generator_produces_both_variants_in_all_three_formats(sample_module, tmp_path) -> None:
    sample_module.main()
    expected = {
        "sample_dashboard_taxpayer.html",
        "sample_dashboard_taxpayer.xlsx",
        "sample_dashboard_taxpayer.pdf",
        "sample_dashboard_preparer.html",
        "sample_dashboard_preparer.xlsx",
        "sample_dashboard_preparer.pdf",
    }
    actual = {p.name for p in tmp_path.iterdir()}
    assert expected <= actual


def test_taxpayer_html_has_no_ks36_content(sample_module, tmp_path) -> None:
    sample_module.main()
    html = (tmp_path / "sample_dashboard_taxpayer.html").read_text(encoding="utf-8")
    assert "KS 36" not in html
    assert "Vorbereiter" not in html
    assert 'class="ampel-' not in html


def test_preparer_html_contains_ks36_section(sample_module, tmp_path) -> None:
    sample_module.main()
    html = (tmp_path / "sample_dashboard_preparer.html").read_text(encoding="utf-8")
    assert 'id="ks36"' in html
    assert "Vorbereiter-Modus" in html


def test_documented_page_exists() -> None:
    """The phase-10 deliverable: docs/tax_overview.md must ship."""
    doc = REPO_ROOT / "docs" / "tax_overview.md"
    assert doc.exists()
    content = doc.read_text(encoding="utf-8")
    # Headings a reader relies on.
    for heading in (
        "## When to use this mode",
        "## CLI usage",
        "## Workbook sheets",
        "## Third-party safety invariants",
        "## Sample output",
    ):
        assert heading in content, f"missing heading: {heading}"
