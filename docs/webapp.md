# Standalone Web App

OpenSteuerAuszug can run as a **single HTML file in your browser** — no
Python installation needed. The page contains the full processing pipeline
and walks you through generating your Steuerauszug step by step.

> **Note:** the browser wizard itself (the UI around the same underlying
> pipeline as the CLI) is mostly AI-coded and has seen much less real-world
> testing. If you're comfortable installing the CLI, prefer that; use the
> web app for convenience, but double-check its output carefully.

## Privacy model

Your broker statements, personal details and the generated Steuerauszug
**never leave your computer**. Everything runs locally in the page. The only
network traffic is fetching the (public, open-source) code the page needs to
run, the first time you open it — after that it's cached by your browser.

## Getting the app

Simply open **<https://vroonhof.github.io/opensteuerauszug/>** in a modern
browser (Chrome/Edge/Firefox) — that's the app, always built from the latest
`main` branch. Everything still runs locally in the page.

If you prefer a local copy (e.g. for offline use), download
[`opensteuerauszug.html`](https://vroonhof.github.io/opensteuerauszug/opensteuerauszug.html)
from the same site (right-click → *Save link as…*), save it anywhere, and
open it from disk. An internet connection is needed on first load either
way.

Unreleased builds from pull requests are available as *Web app* workflow
artifacts on the
[GitHub Actions page](https://github.com/vroonhof/opensteuerauszug/actions/workflows/web-app.yml).

## Using the wizard

The page guides you through six steps:

1. **Welcome** — read the disclaimer; the engine starts loading in the
   background (progress in the bar at the bottom).
2. **Your details** — name, canton, tax year, document language, broker and
   calculation level. Schwab and Fidelity additionally need your account
   number(s). Everything is remembered on this device. Under *Advanced* you
   can inspect or hand-edit the generated `config.toml` (see the
   [configuration guide](config.md)).
3. **Kursliste** — add the official ESTV Kursliste for your tax year
   (`kursliste_YYYY.xml` from [ictax.admin.ch](https://www.ictax.admin.ch/extern/en.html#/xml),
   or the much faster `kursliste_YYYY.sqlite` produced by
   `opensteuerauszug kursliste download`). The file is cached in the browser
   so you only add it once per tax year.
4. **Broker files** — add your broker export(s); the required files per
   broker are described in the importer guides (see the
   [user guide](user_guide.md)). Optionally attach PDFs to prepend/append.
5. **Generate** — runs import → validate → calculate → reconcile → render
   right in the page, with the full processing log shown live.
6. **Download** — save the PDF Steuerauszug (and the eCH-0196 XML), review
   the verification checklist, and import the PDF into your tax software.

All the caveats of the CLI apply unchanged — **verify the generated
statement before filing** (see the [user guide](user_guide.md)).

## Trade-offs compared to the CLI

- **You have to fetch the Kursliste yourself.** The CLI's
  `opensteuerauszug kursliste download` command talks directly to the ESTV
  API; a web page can't do that due to standard browser security
  restrictions (CORS). Download the Kursliste manually from
  [ictax.admin.ch](https://www.ictax.admin.ch/extern/en.html#/xml) and add
  it in the Kursliste step instead.
- Processing a large Kursliste **XML** in the browser is slow (minutes) and
  memory-hungry; prefer the SQLite form for regular use.
- The `verify` workflow for existing statements is not exposed in the UI.
- Very large portfolios may hit browser memory limits.

For build instructions, self-hosting options, and other implementation
details, see the [Technical Notes](technical_notes.md#standalone-web-app).
