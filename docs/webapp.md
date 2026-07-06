# Standalone Web App

OpenSteuerAuszug can run as a **single HTML file in your browser** — no
Python installation needed. The page embeds the full processing pipeline
(compiled to WebAssembly via [Pyodide](https://pyodide.org)) and walks you
through generating your Steuerauszug step by step.

## Privacy model

Your broker statements, personal details and the generated Steuerauszug
**never leave your computer**. The page makes exactly two kinds of network
requests, both for public open-source code:

1. The Pyodide Python runtime from the jsDelivr CDN (~15 MB, once, then
   cached by the browser).
2. The Python library dependencies from PyPI (cached likewise).

The OpenSteuerAuszug code itself is embedded inside the HTML file. Settings
are stored in the browser's local storage, and the (public, non-personal)
Kursliste file is cached in IndexedDB so you only add it once per tax year.

## Getting the app

Download `opensteuerauszug.html` from the *Web app* workflow artifact on the
[GitHub Actions page](https://github.com/vroonhof/opensteuerauszug/actions/workflows/web-app.yml)
(or build it yourself, see below), save it anywhere, and open it in a modern
browser (Chrome/Edge/Firefox; an internet connection is needed on first load
to fetch the runtime).

## Using the wizard

The page guides you through six steps:

1. **Welcome** — read the disclaimer; the Python engine starts loading in
   the background (progress in the bar at the bottom).
2. **Your details** — name, canton, tax year, document language, broker and
   calculation level. Schwab and Fidelity additionally need your account
   number(s). Everything is remembered on this device. Under *Advanced* you
   can inspect or hand-edit the generated `config.toml` (see the
   [configuration guide](config.md)).
3. **Kursliste** — add the official ESTV Kursliste for your tax year
   (`kursliste_YYYY.xml` from [ictax.admin.ch](https://www.ictax.admin.ch/extern/en.html#/xml),
   or the much faster `kursliste_YYYY.sqlite` produced by
   `opensteuerauszug kursliste download`). The file is cached in the browser.
4. **Broker files** — add your broker export(s); the required files per
   broker are described in the importer guides (see the
   [user guide](user_guide.md)). Optionally attach PDFs to prepend/append.
5. **Generate** — runs import → validate → calculate → reconcile → render
   right in the page, with the full processing log shown live.
6. **Download** — save the PDF Steuerauszug (and the eCH-0196 XML), review
   the verification checklist, and import the PDF into your tax software.

All the caveats of the CLI apply unchanged — **verify the generated
statement before filing** (see the [user guide](user_guide.md)).

## Limitations compared to the CLI

- Processing a large Kursliste **XML** in the browser is slow (minutes) and
  memory-hungry; prefer the SQLite form for regular use.
- The `verify` workflow for existing statements and the Kursliste download
  command are not exposed in the UI.
- Very large portfolios may hit browser memory limits.

## Building it yourself

```bash
python scripts/build_web_app.py            # writes dist/web/opensteuerauszug.html
```

The script builds a wheel of this repository plus the git-pinned
dependencies (`ibflex2`, `pdf417gen`), embeds them base64-encoded into
`web/app_template.html`, and records the PyPI dependency list which the page
installs at load time via micropip (binary packages such as `lxml` and
`Pillow` come prebuilt from the Pyodide distribution). Building requires
network access to PyPI and GitHub.

### Self-hosting / offline Pyodide

By default the page loads Pyodide from jsDelivr. To use a self-hosted copy,
either open the page with `?pyodide=https://your.host/pyodide/v0.29.4/full/`
or set the base URL under *Advanced: runtime options* on the welcome step.

## Development notes

- The UI lives in `web/app_template.html` (plain HTML/CSS/JS, no build
  tooling). The Python side entry point is
  `src/opensteuerauszug/util/web_runner.py`, which is covered by the normal
  pytest suite (`tests/util/test_web_runner.py`).
- `web/dev/e2e_smoke.mjs` drives the whole wizard in headless Chromium
  against a mock Pyodide runtime (`web/dev/mock_pyodide.js`):

  ```bash
  python scripts/build_web_app.py
  npm install playwright && npx playwright install chromium
  node web/dev/e2e_smoke.mjs dist/web/opensteuerauszug.html
  ```

- CI builds and smoke-tests the app via `.github/workflows/web-app.yml` and
  uploads the HTML as an artifact.
