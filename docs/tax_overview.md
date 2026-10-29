# Tax Overview Mode — Human-Readable Dashboard (xlsx / HTML / PDF)

The standard `steuerauszug` command produces an eCH-0196 PDF that tax
software can import directly. The **tax-overview** subcommand is a
different kind of artifact: a three-format dashboard (xlsx + html + pdf)
designed for humans — the cantonal tax clerk, your own review, and a
preparer's self-check. It works for any canton (`--canton ZH`, `--canton
BE`, …); the one canton-specific piece is the `SG_Verzeichnis` sheet,
which maps rows onto Kanton St. Gallen's Wertschriftenverzeichnis form —
other cantons' forms are broadly similar, and further cantonal mapping
sheets are welcome.

It reads the same broker input as the standard mode, re-runs the FIFO
and CHF conversion pipeline, and emits:

- `tax_overview_<year>.xlsx` — the full workbook (9 visible sheets)
- `tax_overview_<year>.html` — a single self-contained HTML dashboard
- `tax_overview_<year>.pdf` — a one-page executive cover

All three share one palette, one set of number formats, and one
`TaxOverviewData` source of truth — so the three views cannot disagree
on any figure.

## When to use this mode

Use the tax-overview mode when you want:

- A dashboard a human can read without opening tax software.
- A Wertschriftenverzeichnis mapping sheet (Kanton SG column layout) you
  can copy-paste directly into the canton's form.
- An auditable waterfall that reconciles opening value + inflows −
  outflows = closing value within ±CHF 1.
- A DA-1 Hilfstabelle listing every foreign withholding-tax line the
  taxpayer can reclaim, with the treaty-rate ceiling applied.
- (Preparer only) A hidden ESTV Kreisschreiben Nr. 36 self-check for
  gewerbsmässiger Wertschriftenhandel.

Use the standard eCH-0196 mode (no `tax-overview` subcommand) when you
want the barcoded PDF that tax software actually imports. The two modes
are complementary — many users run both.

## CLI usage

```bash
steuerauszug tax-overview \
  --input data/ibkr_2025.xml \
  --broker ibkr \
  --year 2025 \
  --canton ZH \
  --output-dir out/
```

`--canton` overrides the config's `general.canton`; when neither is set,
the canton from the importer data applies (e.g. IBKR's
`stateResidentialAddress`) — the same resolution as the standard mode.

The mode makes no network calls by default. Pass `--online-sectors` to
let the Performance tab classify uncached sectors via `yfinance` (if
installed); this sends ticker symbols to Yahoo Finance and caches
results in `data/cache/sector_lookup.json`. Otherwise uncached sectors
show as "Unbekannt".

By default all three formats are generated. Narrow with `--formats`:

```bash
steuerauszug tax-overview \
  --input data/ibkr_2025.xml \
  --broker ibkr \
  --year 2025 \
  --output-dir out/ \
  --formats xlsx,pdf
```

### `--preparer-mode`

Pass `--preparer-mode` to include KS 36 content. Without it, the KS 36
sheets, HTML section, and PDF summary line are **dropped entirely** —
even if the upstream pipeline populated them — so you can safely hand a
non-preparer export to a third party (tax clerk, family member) without
exposing the preparer's self-check.

```bash
steuerauszug tax-overview \
  --input data/ibkr_2025.xml \
  --broker ibkr \
  --year 2025 \
  --preparer-mode \
  --output-dir out/
```

The KS 36 sheets in the workbook (`_KS36_Criteria`, `_KS36_Evidence`)
are further marked with `sheet_state = "hidden"` so they do not appear
in the default Excel view — a preparer has to deliberately unhide them.

## Workbook sheets

Left-to-right tab order:

| # | Sheet | Purpose |
|---|-------|---------|
| 1 | `Übersicht` | KPI tiles + Vermögenszuwachs waterfall |
| 2 | `Wertschriften` | Year-end holdings with Kursliste Steuerwert per share |
| 3 | `SG_Verzeichnis` | One row per line of the Kanton SG Wertschriftenverzeichnis form |
| 4 | `DA1_Hilfstabelle` | DA-1 foreign withholding-tax reclaim rows (treaty ceiling applied) |
| 5 | `Kauf_Verkauf` | Reconstructed orders and FIFO lot closes |
| 6 | `Dividenden` | Dividend events with local + CHF columns |
| 7 | `Zinsen` | Interest events with local + CHF columns |
| 8 | `Gebühren` | Non-commission fees (platform, data, wire, …) |
| 9 | `FX_Kurse` | Every FX rate resolved from the Kursliste (audit trail) |

Preparer-mode only (hidden):

| # | Sheet | Purpose |
|---|-------|---------|
| 10 | `_KS36_Criteria` | 5-criterion ESTV self-check with traffic-light status |
| 11 | `_KS36_Evidence` | Supporting evidence rows keyed to the criteria |

## Reading the waterfall

The `Übersicht` sheet closes with the Vermögenszuwachs waterfall:

```
Opening value              CHF 100'000.00     (from Kursliste Steuerwert)
+ Deposits                 CHF  10'000.00
+ Dividends                CHF   5'200.00
+ Interest                 CHF     150.00
+ Realized gains           CHF   3'800.00
− Withdrawals              CHF   2'000.00
− Fees                     CHF     420.00
− Withholding tax          CHF     780.00
= Derived closing          CHF 115'950.00
  Closing value            CHF 115'951.00     (from eCH-0196 XML)
  Differenz (residual)     CHF       1.00     (within ±CHF 1 tolerance ✓)
```

If the residual is outside ±CHF 1, something is missing: usually an
undetected income event, a fee paid outside the brokerage, or an FX
leg that rounded differently than the Kursliste. The PDF cover surfaces
the residual in red when it breaches tolerance, so you see it immediately.

Opening and closing values must come from the ESTV Kursliste
`Steuerwert` (the official annual per-ISIN tax value), **not** the
broker's mark-to-market. The tax authority will use the Kursliste
value, so your waterfall has to reconcile against that same reference
to avoid a spurious residual.

## Copy-pasting into the SG Wertschriftenverzeichnis

The `SG_Verzeichnis` sheet has one row per Kanton SG form line, with
these columns ready to paste:

- `form_field` — the canton's line number (e.g. "A 1", "B 3")
- `investment_type` — Aktie / Obligation / Fonds / Sonstige
- `isin`, `description`, `quantity`
- `market_value_chf`
- `income_gross_chf`
- `verrechnungssteuer_chf` (Swiss withholding tax reclaim)
- `auslaendische_quellensteuer_chf` (foreign withholding tax)

The sheet writer never computes these — the upstream pipeline consolidates
dividends + interest + end-of-year value per ISIN and then the mapping
step assigns a form field. The workbook shows the result, not the logic.

## DA-1 Hilfstabelle

The `DA1_Hilfstabelle` sheet lists every foreign withholding-tax line
that qualifies for DA-1 reclaim:

- `withholding_rate` — the actual rate applied by the source country
- `treaty_rate_ceiling` — what the DBA allows (blank if no treaty applies)
- `recoverable_chf` — what the pipeline has already capped; this equals
  `withholding_tax_chf` when the actual rate is at or below the ceiling,
  otherwise it is capped to the ceiling

The sheet does not recompute — it shows the figure the pipeline decided.
If a rate exceeds its treaty ceiling, the cap is visible in the column
juxtaposition.

## Third-party safety invariants

These rules are locked by tests and will remain true across versions:

1. **KS 36 content never appears in non-preparer exports.** Even if the
   pipeline populates `ks36_criteria` / `ks36_evidence`, a non-preparer
   render drops them entirely from the workbook, the HTML, and the PDF.
2. **Traffic-light fills are reserved for KS 36.** The `ampel-green`,
   `ampel-amber`, and `ampel-red` styles (CSS classes in the HTML;
   `KS36_GREEN/AMBER/RED` NamedStyles in the workbook) may only appear
   on the hidden KS 36 sheets / preparer-only HTML section. No visible
   sheet is allowed to apply them.
3. **No external assets in the HTML.** `<link>`, `<script>`, and
   `http(s)://` URLs are prohibited — the HTML is a single self-contained
   document.
4. **Exactly one page in the PDF cover.** The cover is an executive
   summary, not a replacement for the xlsx.

## Swiss number and date formats

Across all three outputs:

- CHF amounts: `CHF 12'345.67` (apostrophe thousands separator, dot decimal)
- Plain numbers: `1'234.5678`
- Percentages: `15.0%`
- Dates: `28.03.2025`

The xlsx uses Excel custom format strings that render these in any
Swiss-locale install. The HTML and PDF use helpers in
`opensteuerauszug.render.tax_overview.html` (`format_chf`,
`format_number`, `format_percent`, `format_date`) that return the same
strings verbatim.

## Sample output

The repository ships a single synthetic sample dashboard —
[sample_dashboard.html](samples/tax_overview/sample_dashboard.html) —
built from a fixture with no personal data (two public securities,
Apple Inc. and Novartis AG, at public ISINs; synthetic prices and
quantities). Open it in any browser to see the rendered HTML.

The xlsx and PDF variants, and a preparer-mode HTML showing the KS 36
section, are **not** committed (tax artifacts are treated as sensitive
even when synthetic). Regenerate them locally:

```bash
python scripts/generate_tax_overview_samples.py
```

The script writes taxpayer-mode and preparer-mode variants of all three
formats to `docs/samples/tax_overview/`; only the canonical
`sample_dashboard.html` is tracked, everything else is gitignored.

## Troubleshooting

**Waterfall residual > ±CHF 1.** Open the `Kauf_Verkauf`, `Dividenden`,
and `Gebühren` sheets and look for the smallest line that would close
the gap. A common cause is dividend withholding being charged in the
local currency but settled in CHF on a different date — the FX leg
resolves differently from the Kursliste daily rate. The `FX_Kurse` sheet
is the audit trail.

**Missing Kursliste Steuerwert for a security.** The `Wertschriften`
sheet leaves `price_closing_chf` blank and falls back to the broker's
mark-to-market for `market_value_chf`. The warning is logged upstream
(same logging path as the standard eCH-0196 mode). This usually happens
for OTC or recently-delisted securities.

**HTML opens with wrong layout.** The HTML is self-contained. If the
layout is broken, the browser is probably rendering a truncated file —
check the `<main>` tag is closed and `</html>` is present. The generator
never writes partial output.

## Limitations

- **Long-only.** Short positions raise `FifoError` — the FIFO tracker is
  deliberately scoped to long holdings because the SG dashboard does
  not handle short-sale proceeds. Portfolios with shorts must use the
  standard eCH-0196 mode only.
- **One broker per run.** The CLI takes one `--input` file and one
  `--broker` flag. For a mixed IBKR + Schwab year, run the command
  twice and combine the outputs by hand.
- **PDF cover uses Helvetica.** The HTML and xlsx use Inter / Source
  Serif (or Calibri, in Excel); the PDF cover falls back to the PDF
  standard font family so it renders without font embedding. This is
  intentional: the cover must open on any reader without assets.
- **No bilingual rendering.** Labels are German. The standard mode has
  multilingual templates; the dashboard is German-only for now because
  the primary audience is German-speaking cantonal tax offices.
