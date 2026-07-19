#!/usr/bin/env python3
"""Build the standalone single-file web app (opensteuerauszug.html).

The web app runs the full OpenSteuerAuszug pipeline in the browser via
Pyodide (CPython compiled to WebAssembly).  This script produces a single,
downloadable HTML file:

  * builds a wheel of this repository,
  * builds wheels for the git-pinned dependencies (ibflex2, pdf417gen)
    which are not available on PyPI,
  * resolves the full runtime dependency closure against the *current
    environment* (the tested venv) and downloads the exact ``name==version``
    pure-Python wheels, so the page installs precisely the code that the
    test suite ran against — the browser never contacts PyPI,
  * embeds all those wheels (base64) plus the default security identifiers
    CSV into ``web/app_template.html``.

Binary packages (lxml, Pillow, pydantic-core, …) cannot be embedded; they
come from the Pyodide distribution, whose versions are frozen by the
``PYODIDE_VERSION`` pin in the template.  The script fetches the matching
``pyodide-lock.json`` to decide which packages those are.

Usage:
    python scripts/build_web_app.py [--output dist/web/opensteuerauszug.html]

Must run inside the locked project environment (``uv sync --locked --extra dev``).
Requires network access (PyPI + GitHub + Pyodide CDN).
"""

import argparse
import base64
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

try:
    import tomllib  # Python >= 3.11
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "web" / "app_template.html"
IDENTIFIERS_CSV = REPO_ROOT / "data" / "security_identifiers.csv"
BUNDLE_PLACEHOLDER = "__OSA_BUNDLE_JSON__"


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
        if not requirement:
            continue
        if "@ git+" in requirement:
            git_reqs.append(requirement)
        else:
            pypi_reqs.append(requirement)
    return pypi_reqs, git_reqs, project.get("version", "0.0.0")


def read_pyodide_version(template_text: str) -> str:
    """Extract the Pyodide version pinned in the page template."""
    match = re.search(r'const PYODIDE_VERSION = "([^"]+)"', template_text)
    if not match:
        raise ValueError("template does not define PYODIDE_VERSION")
    return match.group(1)


def fetch_pyodide_distribution(version: str) -> dict:
    """Map canonical package name -> lockfile key for the Pyodide distribution.

    These packages (binary builds like lxml/Pillow among them) are served from
    the version-pinned Pyodide CDN, so they are excluded from the embedded
    wheel set.
    """
    url = f"https://cdn.jsdelivr.net/pyodide/v{version}/full/pyodide-lock.json"
    with urllib.request.urlopen(url) as resp:
        lock = json.load(resp)
    return {canonicalize_name(name): name for name in lock["packages"]}


def resolve_locked_closure(root_reqs: list, skip_names: set, pyodide_dist: dict) -> tuple:
    """Walk the runtime dependency closure of the *installed* environment.

    Returns ``(locked, dist_used)`` where ``locked`` maps canonical package
    name to the exact installed version (to be embedded as a wheel) and
    ``dist_used`` lists the Pyodide-distribution package names the page must
    load at runtime.  Markers are evaluated for the build environment; the
    browser smoke test is the safety net for emscripten-only divergence.
    """
    env: dict = dict(default_environment())
    locked: dict = {}
    dist_used: set = set()
    queue = [Requirement(r) for r in root_reqs]
    seen = set()
    while queue:
        req = queue.pop()
        name = canonicalize_name(req.name)
        if name in skip_names:
            continue
        key = (name, frozenset(req.extras))
        if key in seen:
            continue
        seen.add(key)
        if name in pyodide_dist:
            dist_used.add(pyodide_dist[name])
            continue  # transitive deps come from the Pyodide lockfile
        try:
            dist = importlib.metadata.distribution(req.name)
        except importlib.metadata.PackageNotFoundError:
            raise SystemExit(
                f"'{req.name}' is not installed here — run this script inside "
                "the locked project environment (uv sync --locked --extra dev)."
            )
        if req.specifier and not req.specifier.contains(dist.version, prereleases=True):
            raise SystemExit(
                f"installed {req.name} {dist.version} does not satisfy '{req}'; "
                "fix the venv before building."
            )
        locked[name] = dist.version
        for dep_str in dist.requires or []:
            dep = Requirement(dep_str)
            if dep.marker is not None:
                extras = req.extras or {""}
                if not any(dep.marker.evaluate({**env, "extra": e}) for e in extras):
                    continue
            queue.append(dep)
    return locked, sorted(dist_used)


def download_locked_wheels(locked: dict, wheel_dir: Path) -> list:
    """Download the exact ``name==version`` pure-Python wheels from PyPI.

    Anything without a universal (``none-any``) wheel cannot run in the
    browser unless the Pyodide distribution provides it, so that is a build
    error rather than something to paper over.
    """
    wheel_dir.mkdir(parents=True, exist_ok=True)
    before = set(wheel_dir.glob("*.whl"))
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--no-deps",
        "--only-binary",
        ":all:",
        "--implementation",
        "py",
        "--abi",
        "none",
        "--platform",
        "any",
        "--dest",
        str(wheel_dir),
        *[f"{name}=={version}" for name, version in sorted(locked.items())],
    ]
    subprocess.run(cmd, check=True)
    wheels = sorted(set(wheel_dir.glob("*.whl")) - before) or sorted(wheel_dir.glob("*.whl"))
    bad = [w.name for w in wheels if not w.name.endswith("-none-any.whl")]
    if bad:
        raise RuntimeError(f"not universal pure-Python wheels: {', '.join(bad)}")
    return wheels


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
    pyodide_packages: list,
    lock: dict,
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
        # Packages loaded from the version-pinned Pyodide distribution.
        "pyodidePackages": pyodide_packages,
        # Informational: the exact versions embedded as wheels.
        "lock": {name: lock[name] for name in sorted(lock)},
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

    template_text = args.template.read_text(encoding="utf-8")
    pyodide_version = read_pyodide_version(template_text)
    print(f"Pyodide distribution: v{pyodide_version}")
    pyodide_dist = fetch_pyodide_distribution(pyodide_version)

    pypi_reqs, git_reqs, version = collect_dependencies(REPO_ROOT / "pyproject.toml")
    skip_names = {canonicalize_name(Requirement(req).name) for req in git_reqs}
    skip_names.add(canonicalize_name("opensteuerauszug"))
    locked, dist_used = resolve_locked_closure(pypi_reqs, skip_names, pyodide_dist)
    print(f"From Pyodide distribution ({len(dist_used)}): {', '.join(dist_used)}")
    locked_desc = ", ".join(f"{n}=={v}" for n, v in sorted(locked.items()))
    print(f"Locked PyPI wheels ({len(locked)}): {locked_desc}")
    print(f"Git requirements ({len(git_reqs)}): {', '.join(git_reqs)}")

    with tempfile.TemporaryDirectory() as tmp:
        wheel_dir = args.wheel_dir or Path(tmp) / "wheels"
        print("Building application wheel…")
        wheel_paths = build_wheels([str(REPO_ROOT)], wheel_dir)
        for req in git_reqs:
            print(f"Building wheel for {req}…")
            wheel_paths.extend(build_wheels([req], wheel_dir))
        print("Downloading locked dependency wheels…")
        wheel_paths.extend(download_locked_wheels(locked, wheel_dir))
        # De-duplicate while keeping order (pip may rebuild into same dir).
        seen = set()
        unique_wheels = []
        for path in wheel_paths:
            if path.name not in seen:
                seen.add(path.name)
                unique_wheels.append(path)

        bundle = make_bundle(unique_wheels, dist_used, locked, version)
        html = render_html(template_text, bundle)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(html, encoding="utf-8")

    total_kib = args.output.stat().st_size / 1024
    print(f"\nEmbedded wheels: {', '.join(w.name for w in unique_wheels)}")
    print(f"Wrote {args.output} ({total_kib:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
