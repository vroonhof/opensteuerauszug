import base64
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def build_web_app():
    spec = importlib.util.spec_from_file_location(
        "build_web_app", PROJECT_ROOT / "scripts" / "build_web_app.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["build_web_app"] = module
    spec.loader.exec_module(module)
    return module


def _make_dummy_wheel(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("dummy/__init__.py", "")
    return path


def test_dependencies_are_split_into_pypi_and_git(build_web_app):
    pypi, git, version = build_web_app.collect_dependencies(PROJECT_ROOT / "pyproject.toml")
    assert version
    assert any(req.startswith("pydantic") for req in pypi)
    assert any(req.startswith("reportlab") for req in pypi)
    assert all("git+" not in req for req in pypi)
    joined = " ".join(git)
    assert "ibflex2" in joined and "pdf417gen" in joined
    # Inline TOML comments must not leak into requirement strings.
    assert all("#" not in req for req in pypi)


def test_bundle_embeds_wheels_and_identifiers(build_web_app, tmp_path):
    wheel = _make_dummy_wheel(tmp_path / "dummy-1.0-py3-none-any.whl")
    csv = tmp_path / "ids.csv"
    csv.write_text("isin,valor\n")
    bundle = build_web_app.make_bundle([wheel], ["pydantic>=2"], "1.2.3", identifiers_csv=csv)
    assert bundle["version"] == "1.2.3"
    assert bundle["requirements"] == ["pydantic>=2"]
    assert bundle["wheels"][0]["name"] == "dummy-1.0-py3-none-any.whl"
    assert base64.b64decode(bundle["wheels"][0]["data"]) == wheel.read_bytes()
    assert base64.b64decode(bundle["identifiersCsv"]) == b"isin,valor\n"


def test_rendered_html_contains_parseable_bundle_json(build_web_app, tmp_path):
    template = (PROJECT_ROOT / "web" / "app_template.html").read_text(encoding="utf-8")
    wheel = _make_dummy_wheel(tmp_path / "dummy-1.0-py3-none-any.whl")
    bundle = build_web_app.make_bundle(
        [wheel], ["pydantic>=2"], "1.2.3", identifiers_csv=tmp_path / "missing.csv"
    )
    # A hostile-looking string must not be able to close the <script> tag.
    bundle["requirements"].append("evil</script><script>")
    html = build_web_app.render_html(template, bundle)
    assert build_web_app.BUNDLE_PLACEHOLDER not in html
    assert "</script><script>alert" not in html
    start = html.index('<script type="application/json" id="osa-bundle">') + len(
        '<script type="application/json" id="osa-bundle">'
    )
    end = html.index("</script>", start)
    parsed = json.loads(html[start:end])
    assert parsed["version"] == "1.2.3"
    assert parsed["wheels"][0]["name"] == "dummy-1.0-py3-none-any.whl"
    assert "</script>" not in html[start:end]


def test_render_html_rejects_template_without_placeholder(build_web_app):
    with pytest.raises(ValueError):
        build_web_app.render_html("<html></html>", {"version": "1"})
