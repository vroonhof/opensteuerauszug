#!/usr/bin/env python3
"""Build the standalone single-file web app (opensteuerauszug.html).

The web app runs the full OpenSteuerAuszug pipeline in the browser via
Pyodide (CPython compiled to WebAssembly).  This script produces a single,
downloadable HTML file:

  * builds a wheel of this repository,
  * builds wheels for the git-pinned dependencies (ibflex2, pdf417gen)
    which are not available on PyPI,
  * embeds those wheels (base64) plus the default security identifiers CSV
    into ``web/app_template.html``,
  * embeds the list of regular PyPI dependencies, which the page installs
    at load time via micropip (binary packages such as lxml and Pillow come
    from the Pyodide distribution).

Usage:
    python scripts/build_web_app.py [--output dist/web/opensteuerauszug.html]

Requires network access (PyPI + GitHub) to build the wheels.
"""

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib  # Python >= 3.11
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "web" / "app_template.html"
IDENTIFIERS_CSV = REPO_ROOT / "data" / "security_identifiers.csv"
BUNDLE_PLACEHOLDER = "__OSA_BUNDLE_JSON__"

# Dependencies that must not be sent to micropip.  ``micropip`` itself is
# provided by Pyodide and installed separately by the page.
_SKIP_REQUIREMENTS: set = set()


def collect_dependencies(pyproject_path: Path) -> tuple:
    """Split [project.dependencies] into PyPI requirements and git URLs.

    Returns ``(pypi_requirements, git_requirements, project_version)``.
    """
    with open(pyproject_path, "rb") as fh:
        pyproject = tomllib.load(fh)
    project = pyproject["project"]
    pypi_reqs = []
    git_reqs = []
    for dep in project["dependencies"]:
        requirement = dep.split("#", 1)[0].strip()
        if not requirement or requirement in _SKIP_REQUIREMENTS:
            continue
        if "@ git+" in requirement:
            git_reqs.append(requirement)
        else:
            pypi_reqs.append(requirement)
    return pypi_reqs, git_reqs, project.get("version", "0.0.0")


def build_wheels(requirements: list, wheel_dir: Path) -> list:
    """Build wheels (without dependencies) for the given requirements.

    ``requirements`` may contain local directory paths or PEP 508 strings
    (including direct git references).  Returns the built wheel paths.
    """
    wheel_dir.mkdir(parents=True, exist_ok=True)
    before = set(wheel_dir.glob("*.whl"))
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheel_dir),
        *requirements,
    ]
    subprocess.run(cmd, check=True)
    built = sorted(set(wheel_dir.glob("*.whl")) - before) or sorted(wheel_dir.glob("*.whl"))
    if not built:
        raise RuntimeError(f"pip wheel produced no wheels for {requirements}")
    return built


def make_bundle(
    wheel_paths: list,
    pypi_requirements: list,
    version: str,
    identifiers_csv: Path = IDENTIFIERS_CSV,
) -> dict:
    """Assemble the JSON bundle embedded into the HTML page."""
    wheels = []
    for path in wheel_paths:
        data = Path(path).read_bytes()
        wheels.append(
            {
                "name": Path(path).name,
                "data": base64.b64encode(data).decode("ascii"),
            }
        )
    bundle = {
        "version": version,
        "builtAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requirements": pypi_requirements,
        "wheels": wheels,
        "identifiersCsv": (
            base64.b64encode(identifiers_csv.read_bytes()).decode("ascii")
            if identifiers_csv.is_file()
            else ""
        ),
    }
    return bundle


def render_html(template_text: str, bundle: dict) -> str:
    """Inject the bundle JSON into the template."""
    if BUNDLE_PLACEHOLDER not in template_text:
        raise ValueError(f"template does not contain the {BUNDLE_PLACEHOLDER} placeholder")
    # "<" is escaped so the JSON can never terminate the surrounding
    # <script> block (e.g. via "</script>" inside a string).
    bundle_json = json.dumps(bundle, separators=(",", ":")).replace("<", "\\u003c")
    return template_text.replace(BUNDLE_PLACEHOLDER, bundle_json, 1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "dist" / "web" / "opensteuerauszug.html",
        help="Path of the generated single-file HTML app.",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=TEMPLATE_PATH,
        help="Template HTML file (default: web/app_template.html).",
    )
    parser.add_argument(
        "--wheel-dir",
        type=Path,
        default=None,
        help="Reuse/build wheels in this directory instead of a temp dir.",
    )
    args = parser.parse_args(argv)

    pypi_reqs, git_reqs, version = collect_dependencies(REPO_ROOT / "pyproject.toml")
    print(f"PyPI requirements ({len(pypi_reqs)}): {', '.join(pypi_reqs)}")
    print(f"Git requirements ({len(git_reqs)}): {', '.join(git_reqs)}")

    with tempfile.TemporaryDirectory() as tmp:
        wheel_dir = args.wheel_dir or Path(tmp) / "wheels"
        print("Building application wheel…")
        wheel_paths = build_wheels([str(REPO_ROOT)], wheel_dir)
        for req in git_reqs:
            print(f"Building wheel for {req}…")
            wheel_paths.extend(build_wheels([req], wheel_dir))
        # De-duplicate while keeping order (pip may rebuild into same dir).
        seen = set()
        unique_wheels = []
        for path in wheel_paths:
            if path.name not in seen:
                seen.add(path.name)
                unique_wheels.append(path)

        bundle = make_bundle(unique_wheels, pypi_reqs, version)
        html = render_html(args.template.read_text(encoding="utf-8"), bundle)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(html, encoding="utf-8")

    total_kib = args.output.stat().st_size / 1024
    print(f"\nEmbedded wheels: {', '.join(w.name for w in unique_wheels)}")
    print(f"Wrote {args.output} ({total_kib:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
