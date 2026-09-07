# Tax-Relevant Decisions in the Code

This document is a structural review of the codebase that inventories every
**tax-relevant decision** embedded in the code — any place where the code
chooses how a number, classification, date, or rate that affects the final
tax statement is computed, defaulted, rounded, dropped, or guessed — and
classifies how defensively each decision behaves when it meets unknown or
unexpected input.

Line numbers refer to the state of the tree at commit `c6fcf2f` (June 2026).
They will drift; the file + short description should remain findable.

## Defensive-posture legend

| Posture | Meaning |
|---|---|
| **DEFENSIVE** | Raises an error, records a critical warning that the user must see, or refuses to proceed on unknown input. |
| **WARNS** | Logs/prints a warning but continues with a guess or by dropping data. |
| **SILENT** | Silently defaults, guesses, drops, or ignores — no signal at all. |

Items marked **SILENT** or **WARNS** in bold-risk rows are the ones to fix
first: they can change declared income/wealth or tax credits without the
user noticing.

## How errors are signalled today (architecture)

There are four signalling channels, in decreasing order of strength:

1. **Hard exceptions** (`ValueError`, `NotImplementedError`, `RuntimeError`)
   abort the run (CLI catches and exits 1, `steuerauszug.py:1068-1080`).
   Used for: bonds, unknown Kursliste signs, missing exchange rates, unknown
   DeGiro/Fidelity transaction types, missing Kursliste year, period
   coverage gaps (Schwab), XSD validation failure, negative balances.
2. **Critical warnings** (`model/critical_warning.py`): a typed list on the
   `TaxStatement` (`MISSING_KURSLISTE`, `STOCK_SPLIT_MISMATCH`,
   `UNMAPPED_SYMBOL`, `PREVIOUS_YEAR_EXDATE`, `OTHER`). **Never fatal** and
   **never serialized into the XML/barcode** (excluded fields,
   `model/ech0196.py:1906-1908`) — they appear only as a banner + warnings
   page on the PDF. The tax office sees nothing.
3. **VERIFY-mode `CalculationError` accumulation** (`calculate/base.py:19-27,121`):
   mismatches between declared and recomputed values are collected, printed
   with a `Known:`/`Error:` prefix (filtered by `util/known_issues.py`), and
   are **never fatal**. VERIFY is not even a default phase.
4. **Log lines / bare `print`** — much of `core/` (Kursliste DB reader,
   manager, flag provider) prints warnings to stdout instead of using the
   logging system; these are the weakest and most easily lost signals.

Two additional systemic weaknesses of the signalling itself:

- **`assert`-based guards** (IBKR `ibkr_importer.py:888-890`, Fidelity
  `fidelity_importer.py:641`, Schwab `transaction_extractor.py:871-878`,
  withholding cap `withholding_cap_calculator.py:181`) disappear under
  `python -O`.
- **Negative-result caching**: `KurslisteAccessor` memoizes every lookup
  with unbounded `lru_cache` (`core/kursliste_accessor.py:40,112,...`), so a
  swallowed `sqlite3.Error` in the DB reader (which returns `None`/`[]`,
  `core/kursliste_db_reader.py:169-191`) is cached for the rest of the run
  as "not in Kursliste".

## Pipeline overview

Declared phase list (`steuerauszug.py:93-99`) is `IMPORT, VALIDATE,
CALCULATE, RECONCILE_PAYMENTS, RENDER`, but actual execution order is fixed
by code order:

```
IMPORT → CALCULATE → [VERIFY] → RECONCILE_PAYMENTS → VALIDATE (XSD) → RENDER
```

Calculate sub-pipeline (`steuerauszug.py:696-806`): `CleanupCalculator` →
one of `Minimal`/`Kursliste`/`FillIn` tax value calculator (OVERWRITE mode)
→ `WithholdingCapCalculator` (default on, `--use-broker-withholding=cap`) →
`TotalCalculator` (OVERWRITE).

Pipeline-level decisions worth highlighting:

| # | Decision | Location | Posture |
|---|---|---|---|
| P1 | **RENDER runs `TotalCalculator(mode=FILL)` *after* XSD validation**, so render-time-filled totals are never schema-validated. | steuerauszug.py:983-986 | SILENT |
| P2 | VERIFY is opt-in (the `verify` command) and its errors are advisory only — printed, never fatal, exit code 0. | steuerauszug.py:877-909, 1083 | WARNS |
| P3 | XSD validation is **skipped with only a warning (returns True)** if `specs/eCH-0196-2-2.xsd` is not found relative to CWD. | model/ech0196.py:1816-1830 | WARNS |
| P4 | `--phases` allows any subset, e.g. render without validate; `--no-payment-reconciliation`, `--no-strict-consistency`, `--no-filter-to-period` each disable a safety net. | steuerauszug.py:118-123, 160-169, 200-204 | SILENT (bypass) |
| P5 | Default `--use-broker-withholding=cap` silently adjusts Kursliste withholding down to broker-evidenced levels (see WithholdingCapCalculator). | steuerauszug.py:210-214, 782-791 | SILENT |
| P6 | Importer `NONE`/unimplemented importers produce an **empty but renderable** TaxStatement. | steuerauszug.py:644-666 | SILENT |
| P7 | Missing Kursliste data for the tax year is fatal (`ensure_year_available`). | steuerauszug.py:724-732; core/kursliste_manager.py:231-255 | DEFENSIVE |
| P8 | IBKR import globally enables `ibflex` unknown-attribute tolerance — new (possibly tax-relevant) Flex attributes are ignored rather than failing. | steuerauszug.py:591-599 | SILENT |
| P9 | `--corrections-flex` imports only WHTAX cash rows with settleDate inside the period (1042-S corrections); other correction types ignored. | steuerauszug.py:205-209; ibkr_importer.py:304-397 | SILENT |
| P10 | Experimental importers (Fidelity, DeGiro) refused unless enabled in config. | steuerauszug.py:324-329 | DEFENSIVE |
| P11 | Any exception in any phase: stack trace, optional debug dump, exit 1. | steuerauszug.py:1068-1080 | DEFENSIVE |

---

# Highlight: where we do NOT fail defensively

These are the findings where unknown/unexpected input silently changes the
tax statement. Everything here deserves either a hard error, a critical
warning, or at minimum a logged warning + reconciliation-report entry.

## Tier 1 — silent income/credit loss or misstatement

| # | Finding | Location |
|---|---|---|
| H1 | **Schwab: unknown action on a cash position with an amount is silently booked as a bare cash-balance mutation** — a new income label (interest, fee rebate, …) without a symbol produces no taxable payment and no warning. This is the single weakest unknown-input path of all importers. | importers/schwab/transaction_extractor.py:862-869 |
| H2 | **DeGiro: recognized-but-unprocessed row kinds are skipped at DEBUG level**, including `FLATEX_INTEREST` (taxable interest — dropped entirely), unmatched `DIVIDEND_TAX` rows (withholding lost), and all fees. Only genuinely UNKNOWN kinds raise. | importers/degiro/degiro_importer.py:248-251 |
| H3 | **IBKR: security-less `WHTAX` becomes a plain `BankAccountPayment`** which has no withholding fields — the tax-claim character of the amount is lost. | importers/ibkr/ibkr_importer.py:963-979 |
| H4 | **Fidelity: `Cash In Lieu` is in `ACTIONS_TO_IGNORE`** and dropped at DEBUG; payment-in-lieu from securities lending is generally taxable. (Schwab treats Cash In Lieu as income-neutral by explicit commented policy, transaction_extractor.py:761-774.) | importers/fidelity/fidelity_importer.py:92, 562-564 |
| H5 | **XML Kursliste path ignores currency denomination** — the real `rate.denomination` lookup is commented out and hardcoded to 1 for year-end, monthly, and daily rates. Per-100/per-1000 quoted currencies convert at 100-1000× the true rate. The SQLite path honors denomination, so **XML and DB backends can disagree by orders of magnitude**, and DB-load failure silently falls back to XML (kursliste_manager.py:148-156). | core/kursliste_accessor.py:75-76, 93-94, 104-105 |
| H6 | **WithholdingCapCalculator full reversal on absent broker WHT**: if the importer recorded WHT in an unrecognized field, broker WHT reads as 0 and *real* Kursliste withholding is fully reversed — income A moved to B, 35%/DA-1 claims zeroed — with only an info log. One-directional trust in broker data. | calculate/withholding_cap_calculator.py:94-109, 149-184 |
| H7 | **Missing data collapses to zero in totals**: `taxValue.value=None` contributes 0 to wealth; `None` revenue/withholding fields are skipped in accumulation. A position that failed valuation upstream silently reduces declared wealth. | calculate/total.py:83-87, 96-110, 235-251, 329-338 |
| H8 | **Zero-quantity payments are skipped** and position synthesis uses `assume_zero_if_no_balances=True` — an un-anchored position (no balance checkpoint) generates **no income at all** for its Kursliste payments, with no signal. | calculate/kursliste_tax_value_calculator.py:639-652; calculate/cleanup.py:763-803 |
| H9 | **No DA-1 rate found ⇒ silently no foreign tax credit**; non-STANDARD payment types (gratis, accumulation) never get DA-1 evaluation at all. | calculate/kursliste_tax_value_calculator.py:828-857 |
| H10 | **Lenient XML model parsing demotes malformed known attributes to `unknown_attrs`** — a malformed Decimal in a tax amount disappears from the typed model (None for calculations) while round-tripping in serialized XML. | model/ech0196.py:392, 517-541 |
| H11 | **Cleanup reclassifies every negative bank payment as debit interest** on a liability account — a dividend reversal or fee correction is misclassified and removed from income, info log only. | calculate/cleanup.py:424-518 |
| H12 | **Render formatters swallow all exceptions and print `0` / `0.00` / blank** (bare `except`). A formatting error on a summary figure renders as zero. Renderer also recomputes DA-1 country subtotals and cost totals itself, and substitutes `Decimal('0')` for missing summary fields. | render/render.py:109-130, 133-152, 2005-2054, 2683-2696 |

## Tier 2 — silent wrong-value substitution / wrong rate or date

| # | Finding | Location |
|---|---|---|
| H13 | DB rate fallback chain (daily → monthly → **year-end**) applies a year-end rate to a mid-year payment with no signal; XML path uses a *different* order (monthly before daily), so backends pick different rates for the same date. | core/kursliste_db_reader.py:296-368; core/kursliste_accessor.py:71-107 |
| H14 | `get_security_price` falls through from a missing daily price to the **year-end** price for mid-year valuation requests; `taxValue` (possibly foreign-currency) substitutes for `taxValueCHF` without conversion. | core/kursliste_manager.py:288-315 |
| H15 | Ambiguous Kursliste matches resolve arbitrarily: first match for valor/ISIN (XML list order; `LIMIT 1` without `ORDER BY` in DB), first valid DA-1 candidate. | core/kursliste_accessor.py:126-128, 252-253; core/kursliste_db_reader.py:204-254; model/kursliste.py:1126-1175 |
| H16 | Kursliste file year inferred from **first 4-digit number in the filename**; for SQLite this is the only year source — a mis-named DB silently serves the wrong year. A re-bucketed XML (filename/content year mismatch) can be silently never loaded. | core/kursliste_manager.py:32-45, 163-176 |
| H17 | SQLite errors and blob/validation failures make securities look absent (`None`/`[]` + stdout print), then get cached by `lru_cache`. "Not found" and "error" are systematically conflated. | core/kursliste_db_reader.py:139-191; core/kursliste_accessor.py:40 |
| H18 | Year-boundary conventions are encoded in multiple places and fail silently when importer dating differs: closing tax value = balance dated exactly `period_to + 1` (cleanup.py:659-683), opening = balance dated exactly `period_from` (cleanup.py:687-720), balances are start-of-day (ech0196.py:1530-1532, position_reconciler.py:164-171). | calculate/cleanup.py; core/position_reconciler.py |
| H19 | Schwab positions CSV: unparseable quantity or cash value silently becomes `Decimal('0')` — a corrupt checkpoint becomes an authoritative zero balance. | importers/schwab/position_extractor.py:69-79 |
| H20 | Fidelity cash balance fabricated as `Ending Net Value − Ending mkt Value` with each missing component silently defaulting to 0 — can produce a negative fabricated balance. Opening-balance clamp `max(closing − Σmut, 0)` can hide a missing opening position. | importers/fidelity/fidelity_importer.py:849-882, 759-770 |
| H21 | Shared postprocess synthesizes opening balance as `closing − sum(ALL mutations)` including out-of-period mutations; payments are never date-filtered in postprocess. Only Schwab filters to the period at import; IBKR/Fidelity/DeGiro trust the export window. | importers/common/postprocess.py:160-167, 253 |
| H22 | Schwab JSON dedup is by **date coverage, not transaction identity** — overlapping files with different contents for the same dates lose the second file's rows silently. | importers/schwab/schwab_importer.py:341-417 |
| H23 | IBKR OpenPositions snapshot is dated `period_to + 1` regardless of the Flex `reportDate` (deliberately ignored) — a mismatched export window silently produces a wrong period-end checkpoint. | importers/ibkr/ibkr_importer.py:604-615 |
| H24 | Withholding-tax currency convention: negative CHF amount ⇒ recoverable Swiss `withHoldingTaxClaim`, negative non-CHF ⇒ `nonRecoverableTaxAmountOriginal`; positive CHF reversals land asymmetrically in the non-recoverable field. CHF-denominated *foreign* WHT would be misclassified as a Swiss claim. | importers/common/payments.py:35-41 |
| H25 | Unknown file extensions in the Schwab importer are skipped with `pass` — no log at all. | importers/schwab/schwab_importer.py:459-461 |
| H26 | Flag-override config parsed with `configparser` (INI), not TOML — valid TOML can be silently mangled or dropped; a CSV without a `flags` column loads nothing, silently. These overrides change a security's WHT/DA-1 sign. | core/flag_override_provider.py:26-29, 38-43 |
| H27 | `CashPosition.currentCy` defaults to `"USD"` — a cash position created without a currency silently converts at USD rates. | model/position.py:38 |
| H28 | Kursliste model defaults steer classification when attributes are absent: `withHoldingTax=False`, `paymentType=STANDARD`, `validity=DEFINITIVE`, `denomination=1`, `CapitalContribution.currency="CHF"`. Constraint validation on `Percent`/`ValorNumber` is disabled (pydantic-xml workaround). | model/kursliste.py:251-264, 432-439, 549-552, 885-904 |
| H29 | Default Kursliste parse **denylist strips whole element classes** (bonds, derivatives, coins, …) to save memory — securities of denied types look like "missing from Kursliste" even though the data existed in the file. | model/kursliste.py:976-998, 1100-1115 |

## Tier 3 — weak signalling / suppression mechanisms

| # | Finding | Location |
|---|---|---|
| H30 | Critical warnings and the payment-reconciliation report are excluded from XML/barcode; the only carrier is the PDF. No warning is ever fatal. | model/ech0196.py:1890-1911; model/critical_warning.py |
| H31 | `util/known_issues.py` converts VERIFY errors to `Known:` labels via hand-curated, institution-keyed tolerances (UBS &lt;0.005, True Wealth 2% FX deviation, a hard-coded ISIN+date carve-out, global "additionalWithHoldingTaxUSA assumed 0"). Affects operator perception only, but the carve-outs are broad and silent. | util/known_issues.py:29-145 |
| H32 | PaymentReconciliation: noncash (accumulating fund) events have **all** amount verification disabled; over-withholding flagged only for a hard-coded treaty-country list; capped payments auto-accepted; PREVIOUS_YEAR_EXDATE warnings are deleted on a (tolerance-based) match. | calculate/payment_reconciliation_calculator.py:48-60, 111-150, 212-215, 318-319 |
| H33 | Stock-split mismatches (broker vs. Kursliste ratio, by date heuristics incl. next-business-day, weekends-only) produce only a critical warning; subsequent dividend quantities may be mis-scaled. | calculate/kursliste_tax_value_calculator.py:291-433 |
| H34 | Most `core/` warnings go to stdout via `print`, not `logging`. | core/kursliste_db_reader.py, core/kursliste_manager.py, core/flag_override_provider.py |
| H35 | 1D barcode generation failure returns `None` and the page is silently rendered without its required Code128. | render/onedee.py:29-76; render/render.py:435-439 |

---

# Full inventory by subsystem

## 1. Importers

### 1.1 Common helpers (`importers/common/`)

| Decision | Location | Posture |
|---|---|---|
| Decimal parsing refuses None/garbage with field+context in the error. | common/parsing.py:23-31 | DEFENSIVE |
| WHT sign/currency convention (see H24). | common/payments.py:35-41 | SILENT |
| `build_security_payment` emits **untyped** payments (no grossRevenueA/B); classification deferred to calculators. Used by IBKR/Fidelity/DeGiro. | common/payments.py:44-76 | SILENT (by design) |
| Same-day/same-order/same-sign fills merged with quantity-weighted price; a `None` unit price silently adopts the other fill's price. | common/stock_aggregation.py:27-48 | SILENT |
| Canton parsed from `"CH-ZH"`-style strings; unrecognized → None (omitted). | common/client.py:67-90 | SILENT |
| Display name priority snapshot &gt; trade &gt; transfer &gt; cash-tx; fallback description → symbol. | common/security_name.py:41-59 | SILENT (display only) |
| Currency/quotation per security from first balance stock, else first stock, else first payment; raises if none. Multi-currency stock lists take the first currency silently. | common/postprocess.py:105-126 | DEFENSIVE / SILENT |
| Raw mutation/balance consistency: raises under `strict_consistency`, else warns (DeGiro passes False). | common/postprocess.py:141-152 | DEFENSIVE / WARNS |
| Opening balance synthesized as `closing − sum(ALL mutations)` (H21). | common/postprocess.py:160-167 | SILENT |
| Synthetic opening balance skipped when zero; closing always written. | common/postprocess.py:277-294 | SILENT |
| `skip_if_zero` hint drops a security (rights issues) — attached payments go with it. | common/postprocess.py:270-275 | WARNS |
| Payments sorted but never period-filtered in postprocess (H21). | common/postprocess.py:253 | SILENT |
| Cash bucket with payments but no closing balance raises. | common/postprocess.py:364-402 | DEFENSIVE |
| `BankAccountTaxValue.referenceDate` is always `periodTo` regardless of when the broker reported the balance. | common/postprocess.py:410-414 | SILENT |

### 1.2 Schwab (`importers/schwab/`)

Transaction classification is an exact-string `if/elif` chain over a
`KNOWN_ACTIONS` whitelist (transaction_extractor.py:13-63).

| Decision | Location | Posture |
|---|---|---|
| Known-but-unhandled action → raise; unknown action on a security → raise; unknown position type → raise; **unknown action on cash with amount → silent capital movement (H1)**; known action producing no record → raise; amount/cash-leg match enforced by `assert`. | transaction_extractor.py:856-888 | DEFENSIVE except H1 |
| Missing `Action` → raise. | transaction_extractor.py:181-183 | DEFENSIVE |
| Missing/unparseable `Date` → row dropped with a `print`. | transaction_extractor.py:342-366 | WARNS |
| `"as of"` dates: posting date used; as-of only logged/labelled. | transaction_extractor.py:351-380, 617-619 | SILENT |
| Currency hardcoded USD for all transactions and cash. | transaction_extractor.py:178, 390 | SILENT |
| Unparseable money values → `None` + print, flow into missing-amount logic. | transaction_extractor.py:313-322 | WARNS |
| Buy/Reinvest: cash from `Amount` (fallback −qty×price), `requires_settlement=True`; **fees not folded in (TODO)**. | transaction_extractor.py:412-439 | SILENT (fees) |
| Sale: broker-side negative quantity raises; proceeds settlement-dated; fees ignored. | transaction_extractor.py:441-478 | DEFENSIVE |
| Stock Plan Activity = vesting shares in, no cash assumed (taxes via separate rows). | transaction_extractor.py:480-492 | SILENT |
| Lapse rows dropped to avoid double counting with linked brokerage; qty mismatch only warns. If awards do not auto-transfer, vested shares are missing. | transaction_extractor.py:494-526 | WARNS |
| Credit Interest → `grossRevenueB` payment on the cash account + inflow; AWARDS interest without symbol goes to the unspecific cash bucket with a print. | transaction_extractor.py:528-543, 243-265 | DEFENSIVE-ish / WARNS |
| Dividend family → `grossRevenueB` (Schwab reports gross; WHT in separate rows); non-zero Quantity ignored with print; **amount ≤ 0 raises** (a negative Div Adjustment clawback cannot be represented). | transaction_extractor.py:546-578 | DEFENSIVE |
| Cap-gain distributions deliberately **not** income ("tax-free for private investors") — cash only. | transaction_extractor.py:580-591 | SILENT (policy) |
| Bond Interest → `grossRevenueB` on the CUSIP security; ≤0 raises. | transaction_extractor.py:593-612 | DEFENSIVE |
| Stock Split → pure quantity mutation at posting date. | transaction_extractor.py:614-629 | SILENT |
| Spin-off with cash component → `NotImplementedError`; non-positive qty raises. | transaction_extractor.py:631-651 | DEFENSIVE |
| Award Deposit priced at Vest FMV; no cash leg assumed. | transaction_extractor.py:653-684 | SILENT |
| Withholding family (6 labels incl. `IRS Withhold Adj`, `Foreign Tax Paid`) all → `nonRecoverableTax*`; positives are refunds; zero raises. US backup withholding and foreign WHT share one treatment (TODO in code). | transaction_extractor.py:686-722 | DEFENSIVE on data / SILENT policy |
| Cash Merger / Full Redemption: strict shape checks both directions (cash row qty must be 0, Adj row must carry qty and no amount). | transaction_extractor.py:724-759 | DEFENSIVE |
| Cash In Lieu income-neutral by policy (commented-out payment code); settlement flag inconsistency vs. helper comment. | transaction_extractor.py:761-774, 395-397 | SILENT (policy) |
| Journals: sign-guessing cash leg ("If qty &gt; 0 (in), cash is out?"); AWARDS `Journal` quantity sign-inverted. | transaction_extractor.py:781-810 | SILENT |
| Pure cash actions (`Wire Transfer`, `MoneyLink`, `Misc Cash Entry`, `Service Fee`, `Adjustment`, …) → bare cash mutations; no fee/income recognition. | transaction_extractor.py:812-831 | SILENT |
| Share Transfer always treated as outbound (`−abs(qty)`); inbound transfers get the wrong sign, caught only by reconciliation. | transaction_extractor.py:833-848 | SILENT |
| Depot ID from filename heuristics; fallback `"UNKNOWN_BROKERAGE_DEPOT"` with print. | transaction_extractor.py:140-167 | WARNS |
| Security identity is symbol-only (no ISIN/CUSIP); symbol-less rows → generic USD cash position. | transaction_extractor.py:185-222 | SILENT |
| Trade cash re-dated to T+1 NYSE settlement; T+1 applied even to pre-May-2024 years (conservative default); post-period settlements → synthetic "(Unsettled)" account. | schwab_importer.py:67-122, 562-583, 687-709 | SILENT (principled) |
| Unknown file extensions skipped with `pass` — no log (H25). | schwab_importer.py:459-461 | SILENT |
| CSV: primary extractor → fallback extractor → "Skipped file" print. | schwab_importer.py:420-458 | WARNS |
| Overlapping JSON exports deduped by date-range coverage, not transaction identity (H22); payments attached to first surviving stock tuple. | schwab_importer.py:341-417 | SILENT |
| **Tax-period coverage gate raises** if the period is not fully covered or no statement date falls in/one-day-after the covered range. | schwab_importer.py:472-491 | DEFENSIVE |
| Stocks/payments outside the covered range dropped with printed WARNING. | schwab_importer.py:501-521 | WARNS |
| Date exactly range-end+1 accepted (statement end+1 convention). | schwab_importer.py:249-259 | SILENT |
| All Schwab securities hinted `SHARE` / country `US`. | schwab_importer.py:607-610 | SILENT |
| `assume_zero_if_no_balances=True`, same-day aggregation off (awards walked from zero, grant text preserved). | schwab_importer.py:611-622 | SILENT (documented) |
| Cash closing synthesized at period end+1; consistency raises under strict flag, else warns. | schwab_importer.py:645-665 | DEFENSIVE / WARNS |
| SecurityPayment→BankAccountPayment conversion drops `grossRevenueB` (model has no such field). | schwab_importer.py:667-675 | SILENT |
| Awards cash with no configured account → `"UNKNOWN"` with warning; ambiguous account suffix → first match with warning. | schwab_importer.py:186-192, 137-147 | WARNS |
| Positions CSV: unparseable quantity/cash value → `Decimal('0')` (H19); non-matching rows silently skipped; balances dated statement date+1 (start-of-day); USD hardcoded; wrong header → None (fallback extractor). | position_extractor.py:33-108 | SILENT / DEFENSIVE |
| Fallback manual CSV: every malformed row printed + dropped; broad per-row `except Exception`; blank currency → USD. | fallback_position_extractor.py:109-246 | WARNS / SILENT |
| Award statement PDFs: regex extraction, per-field warnings, abort to None if key fields missing; brokerage PDFs deliberately ignored with NOTE; closing balances dated next *weekday* (holidays not skipped, unlike trade settlement); shares×price≈value check exists but only in `main()`, not the import path. | statement_extractor.py:74-389 | WARNS / SILENT |

### 1.3 IBKR (`importers/ibkr/ibkr_importer.py`)

| Decision | Location | Posture |
|---|---|---|
| `_get_required_field` raises on missing/empty for nearly every consumed attribute. | :82-111 | DEFENSIVE |
| Pseudo/summary rows (`accountId == '-'`/SUMMARY) skipped. | :56-73, 461-469 | SILENT (by design) |
| Non-XML inputs warned+skipped; parse errors raise (`RuntimeError`). | :209-242 | WARNS / DEFENSIVE |
| No FlexStatements → **empty TaxStatement with a warning**. | :424-437 | WARNS |
| FX (CASH) trades skipped — "neutral to the portfolio"; cash effects rely wholly on CashReport balances. | :524-527 | SILENT |
| Trades/positions in unhandled asset categories (warrants, crypto, CFDs) skipped with warning — whole positions vanish. | :529-534, 633-639 | WARNS |
| Trade date used for security mutations; `settleDateTarget` fetched but unused. | :481-482, 588-597 | SILENT |
| Options: price × contract multiplier; zero-price option trades require `transactionType`+`closePrice` (raise) and label expiration vs. assignment heuristically. | :113-127, 562-586 | DEFENSIVE |
| `ibCommission` parsed but never applied — gross trade prices. | :518-522 | SILENT |
| Security identity = conid as symbol + optional ISIN; valor never set. | :487-489, 536-542 | SILENT |
| OpenPositions `reportDate` deliberately ignored; balance dated `period_to + 1` (H23). | :604-615 | SILENT |
| Transfers: CASH transfers silently skipped; direction-vs-sign mismatch raises unless CANCEL. | :699-739 | SILENT / DEFENSIVE |
| Corporate actions → bare quantity mutation at reportDate; CA's own cash/proceeds fields ignored (cash only via separate CashTransaction). | :771-849 | SILENT |
| Rights issues flagged; `ignore_rights_issues` config drops zero-balance rights. | :836-838, 1002-1019 | SILENT (config) |
| Cash tx: missing `type` raises; FEES/ADVISORFEES skipped with warning (no costs section); **any other type with conid → untyped SecurityPayment pass-through** (DIVIDEND, PAYMENTINLIEU→securitiesLending, WHTAX→withholding fields, everything else only `broker_label_original`); `assert` blocks interest on non-BOND securities; unknown conid synthesizes a position from the cash row; security-less: DEPOSITWITHDRAW skipped, BROKERINTPAID only "DEBIT INT" variants kept (others warned+dropped), BROKERINTRCVD → bank payment, **WHTAX → plain BankAccountPayment (H3)**, all other types raise. | :851-979 | mixed — see H3 |
| Cash tx date = `dateTime.date()` (pay date), fallback tradeDate. | :856-861 | SILENT |
| No period filtering of trades/cash transactions — trusts the Flex export window (H21). | — | SILENT |
| Corrections files: only WHTAX with settleDate in period; rows without settleDate/conid/type silently skipped; corrections for unknown securities warned+skipped. | :304-397 | SILENT / WARNS |
| Asset-category map STK→SHARE, BOND→BOND, OPT/FOP→OPTION, FUT→OTHER, ETF/FUND→FUND; unknown raises; cash-tx-only positions default ("STK", None)→SHARE. | :41-49, 1008-1012 | DEFENSIVE / SILENT |
| Country from `issuerCountryCode`, first source wins (conflicts warned), default `"US"` (DA-1 relevant). | :135-163, 1017 | WARNS / SILENT |
| CashReport: closing from `endingCash`, else `balance` only if `reportDate == period_to`, else the currency bucket is silently dropped. | :1052-1075 | SILENT |
| Canton/client from the first statement's AccountInformation only (joint accounts TODO). | :1104-1126 | SILENT |

### 1.4 DeGiro (`importers/degiro/`)

| Decision | Location | Posture |
|---|---|---|
| Row classification by literal description matching (EN/IT/FR/DE); no match → UNKNOWN. | account_csv_parser.py:74-168 | (see next) |
| **UNKNOWN row kinds raise `NotImplementedError`** ("may be tax-relevant; please report"). Strongest unknown-row posture of all importers. | degiro_importer.py:242-247 | DEFENSIVE |
| **Recognized-but-unprocessed kinds skipped at DEBUG** — incl. `FLATEX_INTEREST` (taxable interest lost), unmatched `DIVIDEND_TAX` (withholding lost), all fees (H2). | degiro_importer.py:248-251 | SILENT |
| Dividend↔tax matching by `(value_date, isin)` with `pop(0)` — same-day multi-dividend tax rows can swap; extra tax rows dropped. | degiro_importer.py:194-197, 417-421 | SILENT |
| Trades parsed from human-readable description via regex; non-matching descriptions dropped with warning. | degiro_importer.py:344-359 | WARNS |
| Sell detection by localized keyword list (4 languages). | degiro_importer.py:365-366 | SILENT |
| Rows missing a valid ISIN (incl. dividends) warned and skipped — income understated. | degiro_importer.py:223-239, 369-372 | WARNS |
| Same-order siblings (FX legs, fees) marked consumed, never processed. | degiro_importer.py:379-384 | SILENT (by design) |
| `strict_consistency=False` hardcoded — reconciliation inconsistencies only warn. | degiro_importer.py:308-315 | WARNS |
| Settlement (`Value date`) used as referenceDate throughout. | degiro_importer.py:386-414 | SILENT (convention) |
| Corporate-action cash → untyped SecurityPayment. | degiro_importer.py:459-476 | SILENT |
| Delisting modeled as forced sell of regex-parsed quantity at stated (often 0) price. | degiro_importer.py:425-457 | WARNS / SILENT |
| Closing balances from Portfolio.csv at period_to+1; non-ISIN rows skipped at debug; securities without checkpoints get explicit zero close, currency guessed (default USD). | degiro_importer.py:154-190, 253-269 | SILENT |
| Category from name substring (ETF/UCITS→FUND else SHARE); country from ISIN prefix (default US). | degiro_importer.py:99-106, 301-306 | SILENT |
| Cash: single closing balance from portfolio cash row (default CHF), country NL, `payments=[]`; no cash row → no bank account at all. | degiro_importer.py:154-160, 317-328 | SILENT |
| Account.csv assumed reverse-chronological, reversed wholesale. | degiro_importer.py:145-147 | SILENT |
| Parsers: empty `Date` rows skipped; missing Value date → booking date; missing amounts → 0; fixed `%d-%m-%Y` (raises on garbage); empty-ISIN portfolio row treated as the cash row. | account_csv_parser.py:182-204; portfolio_csv_parser.py:49-84 | SILENT / DEFENSIVE |

### 1.5 Fidelity (`importers/fidelity/fidelity_importer.py`)

| Decision | Location | Posture |
|---|---|---|
| Action classification by ordered substring search over 14 phrases; first match wins (insertion-order dependent, e.g. "ADJ NON-RESIDENT TAX" before "NON-RESIDENT TAX"). | :47-81, 534-544 | SILENT (fragile) |
| **Unmatched action → raise.** | :545-548 | DEFENSIVE |
| `Cash In Lieu` ignored at DEBUG (H4); the securities-lending branch for it is dead code. | :92, 562-564, 388 | SILENT |
| Date = Run Date with "as of" override; parse failure → warning + `None` date flowing downstream. | :167-181 | WARNS |
| `Quantity` required for every transaction (raise). | :556-560 | DEFENSIVE |
| Trades without usable symbol warned+skipped; transfer/split unit price = Amount/Quantity (ZeroDivision risk); commission key check uses wrong column name so commissions are effectively never read. | :566-594 | WARNS / SILENT |
| Negative-quantity split relabeled reverse split. | :613-614 | SILENT |
| Asset category from statement map else SHARE; non-SHARE/FUND coerced to SHARE with warning. | :600-610, 728-733 | WARNS |
| Symbol-bearing cash rows → untyped SecurityPayment (classification deferred); `assert` blocks Credit Interest on securities. | :639-678 | SILENT / assert |
| Symbol-less rows: DIRECT DEBIT/Deposit skipped at DEBUG; everything else (incl. Wire Transfer) becomes a BankAccountPayment. | :679-693 | SILENT |
| **No period filtering anywhere** — all rows land in the statement (H21). | :527-693 | SILENT |
| Statement rows: 'unavailable' values, subtotal/core-account symbols skipped; empty symbol (delisted) warned+skipped — closing checkpoint lost; symbols ≥ 6 chars raise `NotImplementedError`; ETF/INDEX substring → FUND. | :84-136, 459-524 | mixed |
| Statement date from filename; parse failure → `''` → later raise. | :300-311, 447 | WARNS→DEFENSIVE |
| Closing balance at statement date+1; period close synthesized at period_to+1. | :447-457, 754-756 | SILENT |
| Opening = `max(closing − Σmutations, 0)` clamp (H20); negative open/close raises. | :759-770 | SILENT / DEFENSIVE |
| Cash balance = Ending Net − Ending mkt with 0-defaults (H20); newest statement wins; payments without any statement balance raise. | :849-927 | SILENT / DEFENSIVE |
| Country `"US"` and currency USD hardcoded for securities and bank accounts. | :407, 821, 936 | SILENT |
| No statements parsed → warning + empty TaxStatement (transactions discarded). | :408-421 | WARNS |
| Per-file broad `except` re-raised as RuntimeError; routing by filename substring, else warned+skipped. | :289-331 | DEFENSIVE / WARNS |

## 2. Core (`core/`)

### 2.1 Constants and providers

| Decision | Location | Posture |
|---|---|---|
| Swiss withholding tax rate hardcoded 35%, no year/jurisdiction qualification. | constants.py:8 | SILENT |
| `UNINITIALIZED_QUANTITY = Decimal("-1")` sentinel — arithmetically legal value for "unknown". | constants.py:6 | SILENT |
| `DummyExchangeRateProvider` returns fixed 0.5 for every non-CHF currency (stdout print only). Must never be wired into a real run. | exchange_rate_provider.py:40-58 | WARNS |
| CHF hardcoded 1:1 (case-sensitive comparison; `"chf"` would miss). | exchange_rate_provider.py:50-51; kursliste_exchange_rate_provider.py:16-17 | SILENT |
| Kursliste tax year derived solely from `reference_date.year` — adjacent-year dates use a different Kursliste edition if loaded. | kursliste_exchange_rate_provider.py:19-21 | SILENT |
| **Missing exchange rate raises `ValueError`.** | kursliste_exchange_rate_provider.py:29-32 | DEFENSIVE |

### 2.2 KurslisteAccessor (XML/DB façade)

| Decision | Location | Posture |
|---|---|---|
| All lookups memoized with unbounded `lru_cache`; misses (incl. error-produced `None`s) cached for the run (H17). | kursliste_accessor.py:40, 112-255 | SILENT |
| XML: year-end rate used only when date is exactly Dec 31; else monthly average, then daily — inverse tier order vs. DB (H13). | kursliste_accessor.py:71-107 | SILENT |
| XML: year-end `value` falls back to `valueMiddle`. | kursliste_accessor.py:77-82 | SILENT |
| **XML: denomination hardcoded 1, real lookup commented out (H5).** | kursliste_accessor.py:75-76, 93-94, 104-105 | SILENT |
| Year matching uses `reference_date.year`; mismatches fall through to None. | kursliste_accessor.py:68-90 | SILENT |
| Non-Kursliste data sources return None/[] silently. | kursliste_accessor.py:110-271 | SILENT |
| Ambiguous valor/ISIN → first match (H15). | kursliste_accessor.py:126-146 | SILENT |
| Lookups consider only instances with `year == tax_year`; others skipped silently. | kursliste_accessor.py:122-162 | SILENT |
| DA-1: specific rate preferred, silent fallback to general group rate; unset validFrom/validTo = always valid; multiple candidates → first wins. | kursliste_accessor.py:220-253 | SILENT |

### 2.3 KurslisteDBReader (SQLite)

| Decision | Location | Posture |
|---|---|---|
| Unknown blob format assumed legacy JSON (debug log). | kursliste_db_reader.py:105-117 | SILENT |
| All SQL errors swallowed → None/[] + stdout print (H17). | kursliste_db_reader.py:169-191 | WARNS |
| Blob deserialization failures drop the record (print). | kursliste_db_reader.py:139-149, 230-273 | WARNS |
| Security types not in `_SECURITY_TYPE_MAP` cannot deserialize → dropped (print). New ESTV types vanish. | kursliste_db_reader.py:54-90, 159-164 | WARNS |
| Dead first `_SECURITY_TYPE_MAP` definition shadowed by the explicit one — edit trap. | kursliste_db_reader.py:39-53 | (latent) |
| `LIMIT 1` without ORDER BY for valor/ISIN — arbitrary row on ambiguity (H15); valor compared as string. | kursliste_db_reader.py:204-254 | SILENT |
| Rate tiers: Dec-31 preference, then daily → monthly → **year-end fallback** (H13); each step unlogged. | kursliste_db_reader.py:296-368 | SILENT |
| Denomination honored; falsy (NULL/0) → 1. | kursliste_db_reader.py:303-364 | SILENT |
| Unparseable rate values → print + fall through to next coarser tier. | kursliste_db_reader.py:307-368 | WARNS |
| Duplicate rate rows resolved by `ORDER BY id DESC LIMIT 1`. | kursliste_db_reader.py:290-339 | SILENT |
| `tax_year` for rate queries assumed = `reference_date.year` (comment admits assumption). | kursliste_db_reader.py:299-357 | SILENT |
| Queries on a closed connection return None/[] — use-after-close looks like "not in Kursliste". | kursliste_db_reader.py:171-183 | SILENT |

### 2.4 KurslisteManager

| Decision | Location | Posture |
|---|---|---|
| Tax year inferred from first 4-digit number in the filename (H16); for SQLite the only year source. | kursliste_manager.py:32-45 | SILENT |
| XML content-year extraction failure → warning; file with no derivable year dropped with no message. | kursliste_manager.py:47-74, 111 | WARNS / SILENT |
| SQLite silently prioritized over XML for the same year. | kursliste_manager.py:125-156 | SILENT |
| DB load failure → print + fallback to XML (which has different numerics, H5/H13). | kursliste_manager.py:148-156 | WARNS |
| Multiple SQLite files: `kursliste_YYYY.sqlite` preferred, else first glob-ordered. | kursliste_manager.py:133-141 | SILENT |
| Filename/content year mismatch: re-bucketed file may never load if its true year was already processed (H16). | kursliste_manager.py:163-176, 118-119 | WARNS (lossy) |
| Per-file XML parse errors printed, file skipped; partially-loaded year indistinguishable from full. | kursliste_manager.py:179-182 | WARNS |
| `ensure_year_available` raises with available-years list — but opt-in; `get_kurslisten_for_year` returns None silently. | kursliste_manager.py:231-255, 210-220 | DEFENSIVE / SILENT |
| `get_security_price`: every miss → None, no logging; missing daily price falls through to **year-end** price (H14); `taxValue` substitutes for `taxValueCHF` un-converted; percent-quoted (bond) prices unsupported → None; first usable year-end entry wins. | kursliste_manager.py:275-317 | SILENT |
| `get_security_payments`: `deleted` payments filtered (correct); all misses → []; ISIN-only lookup (no valor fallback). | kursliste_manager.py:319-330 | SILENT |

### 2.5 Identifier / flag overrides

| Decision | Location | Posture |
|---|---|---|
| Missing `security_identifiers.csv` → debug log, no enrichment. | identifier_loader.py:37-41 | SILENT |
| Wrong/extra header invalidates the whole file (error log, empty map) — conflicts with FlagOverrideProvider's required `flags` column (H26). | identifier_loader.py:55-60 | WARNS |
| Bad rows skipped/partially used with warnings; duplicate symbols last-wins with warning; case-sensitive symbol matching. | identifier_loader.py:63-97 | WARNS / SILENT |
| CSV flags: no `flags` column → nothing loads, nothing logged (H26); empty isin/flags rows skipped silently; missing file accepted; other errors stdout-print. | flag_override_provider.py:26-34 | SILENT / WARNS |
| `config.toml` parsed with configparser, not TOML (H26); config overrides silently take precedence over CSV. | flag_override_provider.py:38-43 | SILENT |
| `get_flag` returns None for unknown ISINs — "no override" vs. "load failed" indistinguishable. | flag_override_provider.py:50-52 | SILENT |

### 2.6 PositionReconciler, security classification, organisation

| Decision | Location | Posture |
|---|---|---|
| Exact (no-epsilon) quantity reconciliation; mismatch logs ERROR, raises only with `raise_on_error=True` — caller decides whether to proceed. | position_reconciler.py:128-133, 155-160 | DEFENSIVE / WARNS |
| On mismatch, running quantity resets to broker-reported balance ("trust the statement"), masking later independent inconsistencies. | position_reconciler.py:138 | WARNS |
| No starting balance: hard failure by default; `assume_zero_if_no_balances=True` assumes 0 and requires ending at 0 (self-checking). | position_reconciler.py:78-91, 142-149 | DEFENSIVE / WARNS |
| Out-of-order events abort consistency check. | position_reconciler.py:109-114 | DEFENSIVE |
| Synthesis is **start-of-day** semantics; balance on target_date is the start-of-day anchor (H18). | position_reconciler.py:164-231, 314-327 | SILENT (convention) |
| Backward synthesis un-applies mutations from the next future balance; mutation-only synthesis from zero has no end-at-zero self-check; synthesized currency from anchor event (possibly None). | position_reconciler.py:245-334 | SILENT |
| Security tax classification DA1 &gt; A &gt; B: any payment with nonRecoverableTax/additionalWHT-USA &gt; 0 makes the whole security DA1; A if any grossRevenueA or zero-revenue+country=="CH"; **catch-all default B** — a Swiss security with unpopulated grossRevenueA lands on list B (forfeits VSt presentation). `None` and `0` equivalent. | security.py:21-94 | SILENT |
| Org number fabricated as `19`+3-digit name hash in the unused SNB 19000 range; nameless → `'19999'`; explicit override strictly validated. | organisation.py:24-83 | SILENT / DEFENSIVE |

## 3. Calculate (`calculate/`)

### 3.1 Base machinery

| Decision | Location | Posture |
|---|---|---|
| VERIFY records `CalculationError`s (never raises); existing `None` passes VERIFY silently. | base.py:119-121 | WARNS |
| FILL treats None/empty as missing but keeps any non-empty wrong value. | base.py:124-129 | SILENT |
| Exact-equality numeric comparison via `Decimal(str(v))`; conversion failure counts as mismatch (safe direction). | base.py:113-156 | SILENT (conservative) |
| Visitor skips `unknown_attrs`/underscore fields — data demoted by lenient parsing (H10) is never verified. | base.py:79 | SILENT |

### 3.2 CleanupCalculator

| Decision | Location | Posture |
|---|---|---|
| Negative non-mutation security balances (shorts) → raise. | cleanup.py:79-109 | DEFENSIVE |
| Statement ID placeholders (`XX`, `NOIDENTIFIER`) when client data missing. | cleanup.py:121-173 | WARNS |
| `taxPeriod = period_to.year`, `country="CH"`, `minorVersion=22` stamped unconditionally; importer period overwritten by config. | cleanup.py:198-204 | SILENT |
| Invalid configured canton: logged + skipped (importer canton wins); missing canton entirely → raise. | cleanup.py:210-232 | WARNS / DEFENSIVE |
| `NotImplementedError` during ID generation swallowed → statement without ID. | cleanup.py:300-301 | SILENT |
| Account opening/closing dates outside the period cleared. | cleanup.py:316-339 | SILENT |
| Negative bank balance → liability account; CHF value falls back to the *unconverted* foreign balance when `value` missing. | cleanup.py:342-386 | SILENT |
| Bank payments outside the period filtered (year-boundary risk if broker dates use another convention). | cleanup.py:400-414 | SILENT |
| **Every negative bank payment reclassified as debit interest** on a liability (H11); liability currency defaults CHF / country CH. | cleanup.py:424-518 | SILENT |
| Identifier enrichment by symbol/name from user CSV; `valorNumber==0` treated as missing; wrong CSV row silently binds the wrong Kursliste identity. | cleanup.py:572-621 | SILENT |
| Still-unidentified symbol → `UNMAPPED_SYMBOL` critical warning, processing continues. | cleanup.py:626-643 | WARNS |
| Year-end taxValue from the first non-mutation balance dated exactly `period_to + 1` (H18); zero quantity → taxValue None. | cleanup.py:659-683 | SILENT |
| Period filtering keeps only in-period mutations and the balance dated exactly `period_from` (H18). | cleanup.py:687-720 | SILENT |
| Payment with missing quantity and no stock history → raise; quantity synthesized at exDate-else-paymentDate with `assume_zero_if_no_balances=True` (H8); synthesis failure → raise. | cleanup.py:729-813 | DEFENSIVE / SILENT |

### 3.3 MinimalTaxValueCalculator

| Decision | Location | Posture |
|---|---|---|
| CHF conversion at the item's own reference/payment date; CHF short-circuits at rate 1. | minimal_tax_value.py:58-87 | SILENT |
| Bank A/B classification solely by `bankAccountCountry == "CH"`; undetermined context with revenue → raise. | minimal_tax_value.py:104-114, 175-179 | SILENT / DEFENSIVE |
| Missing referenceDate/balanceCurrency → raise. | minimal_tax_value.py:123-142 | DEFENSIVE |
| **Type-A bank income assumed gross with full 35% WHT claim** (quantized 0.01 half-up); B gets zero claim; only positive revenue classified. | minimal_tax_value.py:160-183 | SILENT |
| Liability payments always `grossRevenueB`. | minimal_tax_value.py:224-226 | SILENT |
| Broker payments snapshotted once into `broker_payments` (ordering-sensitive). | minimal_tax_value.py:241-244 | SILENT |
| SecurityTaxValue: missing inputs raise; `undefined=True` set on every minimal-path value (honest "not officially determined" flag). | minimal_tax_value.py:252-291 | DEFENSIVE / SILENT |
| US securities: absent `additionalWithHoldingTaxUSA` defaulted to 0. | minimal_tax_value.py:297-314 | SILENT |
| `setKurslistePayments`: OVERWRITE replaces broker payments with Kursliste ones; `keep_existing_payments` merges (debug feature — would double count if totaled). | minimal_tax_value.py:324-362 | SILENT |
| VERIFY payment matching by paymentDate with positional pairing of leftovers; internal fields ignored. | minimal_tax_value.py:364-423 | WARNS |

### 3.4 KurslisteTaxValueCalculator

| Decision | Location | Posture |
|---|---|---|
| **Bonds categorically unsupported → raise** (issue #262). | kursliste_tax_value_calculator.py:170-173 | DEFENSIVE |
| No kursliste manager → silent fallback to broker-value path. | :178-180 | SILENT |
| Lookup year from taxValue.referenceDate, else last stock entry. | :182-199 | SILENT |
| Identification valor-first, ISIN-second; valor backfilled from Kursliste. | :201-219 | SILENT |
| Not found in Kursliste → `MISSING_KURSLISTE` critical warning; suppressed for rights issues and zero-balance options. | :132-147, 227-251 | WARNS / SILENT |
| Kursliste year-end price overrides broker price (value=price×qty, CHF, rate=1, kursliste=True). | :255-274 | SILENT (by design) |
| Zero-balance option not in Kursliste → taxValue 0. | :275-285 | SILENT |
| Stock split validation by expected ratio with date heuristics (primary/alt/next-business-day, weekends only); all mismatch paths → `STOCK_SPLIT_MISMATCH` critical warning, continue (H33). Cross-ISIN splits likewise. | :291-534 | WARNS |
| `deleted` Kursliste payments excluded; payments without paymentDate skipped; `capitalGain` payments skipped (private-investor assumption). | :559, 592-598 | SILENT |
| Quantity at exDate-else-paymentDate via reconciler (`assume_zero...=True`); None → raise; **zero quantity → payment skipped (H8)**. | :600, 639-652 | DEFENSIVE / SILENT |
| Multiple payment variants (cash vs. stock dividend) → `NotImplementedError`. | :604-614 | DEFENSIVE |
| Previous-year ex-date → critical warning, computed off opening position; warning later auto-dismissed on reconciliation match. | :617-637 | WARNS |
| **Unknown Kursliste sign types → raise** (whitelist at :53-74); `KEP`/`(KG)`/`(KR)` skipped as non-taxable capital. | :689-706 | DEFENSIVE / SILENT |
| Kursliste `undefined` payments emitted with quantity but no amounts. | :730-747 | SILENT (flag carried) |
| Missing `paymentValueCHF` on a defined payment → raise; **ESTV's CHF conversion used, not payment-date market rate**. | :749-760 | DEFENSIVE / SILENT |
| **Negative dividend (short over record date) zeroed** — logger.warning only; potential crash if exDate None on that path. | :762-769 | WARNS |
| Missing exchangeRate: CHF→1; non-CHF with nonzero CHF value → raise. | :771-779 | DEFENSIVE |
| User flag override replaces the Kursliste sign per ISIN (typo silently changes income category). | :798-807 | SILENT |
| **A/B split driven solely by Kursliste `withHoldingTax` flag**; A ⇒ 35% claim quantized 0.01. | :813-826 | SILENT (by design) |
| DA-1 credit only for STANDARD payment types; `(Q)` forces SHARE treatment, `(Z)` suppresses; no rate found ⇒ silently no credit (H9); `additionalWithHoldingTaxUSA=0` unconditionally. | :828-857 | SILENT |
| Sign `(V)` (stock distribution) with DA-1 → `NotImplementedError`. | :859-862 | DEFENSIVE |

### 3.5 FillInTaxValueCalculator

| Decision | Location | Posture |
|---|---|---|
| No Kursliste manager → no-op (broker payments stand). | fill_in_tax_value_calculator.py:45-51 | SILENT |
| Kursliste-known securities/payments left untouched. | :57-59 | SILENT |
| Broker payments classified by country only: CH→grossRevenueA (**no 35% claim computed — potential VSt under-claim**), non-CH→grossRevenueB (no DA-1 logic on this path); amounts assumed gross. | :61-78 | SILENT |
| Unknown country with revenue → raise; missing amountCurrency/paymentDate → raise; zero amounts skipped. | :70-86 | DEFENSIVE |

### 3.6 PaymentReconciliationCalculator (verification layer)

| Decision | Location | Posture |
|---|---|---|
| Tolerances 0.05 CHF absolute / 0.1% relative — differences inside are "matched". | payment_reconciliation_calculator.py:77-85, 321-326 | SILENT |
| Evidence from `broker_payments` snapshot else non-Kursliste payments; nothing to compare if both gone. | :153-156 | SILENT |
| Both sides aggregated per paymentDate — offsetting same-day errors cancel. | :161-174 | SILENT |
| Broker amounts converted at the Kursliste rate of that date (biases toward matching). | :186-196, 363-364 | SILENT |
| Withholding detection: `withHoldingTaxClaim`≠0 else `nonRecoverableTaxAmountOriginal`≠0, else counts as dividend cash. | :333-354 | SILENT |
| Capped payments auto-accepted; noncash events: all amount verification disabled (H32). | :202-215, 318-319, 375-378 | SILENT |
| Return-of-capital signs/keywords allowlist broker-above-Kursliste differences; free-text keyword matching can misfire. | :62-75, 219-239 | SILENT |
| Over-withholding flagged only for hard-coded treaty countries (GB, NL, LU, US, CA, JP, FR, IE, SG, HK, AU). | :48-60, 234-238 | SILENT |
| US 2× WHT → "check W8-BEN" note. | :245-256 | WARNS |
| Mismatch rows are report-only — nothing blocks output. | :263-273 | WARNS |
| PREVIOUS_YEAR_EXDATE warnings deleted on reconciliation match. | :111-150 | SILENT |

### 3.7 TotalCalculator

| Decision | Location | Posture |
|---|---|---|
| None taxValue/revenue/WHT fields contribute 0 to totals (H7). | total.py:83-110, 235-251, 329-338 | SILENT |
| Rounding: `round_accounting` (DIN 1333 half-up; 3dp &lt; 100, 2dp ≥ 100) at (sub)total level; grand totals re-round rounded subtotals when `round_sub_total=True` (config flag changes reported numbers with no record). | total.py:16-39, 200-218, 253-284; util/__init__.py:6-34 | SILENT (configurable) |
| Security totals written only when payments exist — stale imported totals survive FILL. | total.py:95-123 | SILENT |
| DA1/A/B routing per security via `determine_security_type` — one DA-1 dividend routes the security's full taxValue and revenue-B to the DA-1 annex; DA-1 total ignores revenue-A of DA1 securities. | total.py:135-145, 211-218 | SILENT |
| Bank accounts summarized A/B by `acc_revenue_a &gt; 0` (inconsistent with the security country rule). | total.py:279-284 | SILENT |
| `totalGrossRevenueIUP`/`Conversion` hardcoded 0. | total.py:187-198 | SILENT |
| Summary fields (svTaxValueA/B, steuerwert_ab, da1TaxValue, …) assigned directly, bypassing VERIFY. | total.py:376-395 | SILENT |

### 3.8 WithholdingCapCalculator

| Decision | Location | Posture |
|---|---|---|
| One-directional trust: broker net WHT caps (never raises) Kursliste WHT — motivated by IBKR 1042-S reclassification. | docstring, :117 | SILENT |
| Broker WHT detection via two fields only; unrecognized booking → broker WHT = 0 → **full reversal of real withholding (H6)**. | :94-101, 220-231 | SILENT |
| 0.05 CHF tolerances; foreign WHT converted at Kursliste rate, no rate ⇒ cap skipped (safe direction); negative aggregate clamped to 0. | :41-42, 83-109 | SILENT |
| Multiple same-date Kursliste WHT payments when capping → raise; fractional Swiss WHT cap → raise. | :120-128, 141-147 | DEFENSIVE |
| Full reversal moves grossRevenueA→B, zeroes WHT fields, clears `(Q)`, stores originals in `withholding_capped*` (the only reclassification with an audit trail); bare `assert` that B was previously empty. | :149-184 | SILENT / assert |
| Partial cap only for `nonRecoverableTaxAmount`; lump-sum credit/percent not recomputed → DA-1 internal inconsistency possible. | :186-215 | SILENT |

## 4. Model (`model/`)

| Decision | Location | Posture |
|---|---|---|
| Lenient XML parsing default: unknown attrs stashed in `unknown_attrs` (H10); unknown elements round-tripped verbatim but invisible to typed code; invalid Literal enums dropped. | ech0196.py:392, 517-541, 685-698, 843-852 | WARNS |
| Bool serialization: True→"1", False omitted when defaulted; bool parsing accepts only 'true'/'1'(/'yes'). | ech0196.py:556-563, 507-508 | SILENT |
| Decimal serialization `normalize()`+"f" — full precision, cosmetic zero-stripping only. | ech0196.py:567-569 | SILENT (benign) |
| `PositiveDecimal` rejects negatives. | ech0196.py:289-295 | DEFENSIVE |
| `securityName` truncated to 60 chars with middle ellipsis (eCH limit vs. Kursliste 120). | ech0196.py:1635-1663 | SILENT (documented) |
| `country` defaults "CH"; `canton` deliberately has no default (deferred to XSD failure). | ech0196.py:1781-1786 | SILENT / DEFENSIVE |
| DA1 summary fields default `Decimal('0')` (PDF shows 0 if never computed). | ech0196.py:1899-1902 | SILENT |
| `required_for_output` walk (e.g. payment quantity) raises in `validate_model()`. | ech0196.py:394-423, 1455-1458, 1820-1826 | DEFENSIVE |
| XSD missing → skip validation with warning (H30/P3); present+invalid → raise. | ech0196.py:1816-1876 | WARNS / DEFENSIVE |
| Internal evidence (broker originals, capped metadata, critical warnings, reconciliation report, summary totals) excluded from XML/barcode (H30). | ech0196.py:1511-1519, 1622-1630, 1890-1911 | SILENT |
| `SecurityStock` balances are start-of-referenceDate (H18). | ech0196.py:1530-1532 | SILENT (convention) |
| Critical warnings: typed, PDF-only, never fatal (H30). | critical_warning.py:1-41 | WARNS (by design) |
| Reconciliation rows default `status="mismatch"`/`matched=False` (fail-safe), but missing Kursliste amounts default to 0 CHF. | payment_reconciliation.py:15-25 | SILENT (mostly safe) |
| `CashPosition.currentCy` defaults "USD" (H27); position identity = (depot, valor, isin, symbol); symbol validator rejects empties/spaces; `security_type` unvalidated. | position.py:38, 80-100 | SILENT / DEFENSIVE |
| Kursliste model: constraint validation disabled on Percent/ValorNumber; classification-steering defaults (H28); default parse denylist (H29); v2.0 namespace silently rewritten to v2.2; file-level parse errors raise; `find_security_by_*` first-match. | kursliste.py:251-264, 432-439, 549-552, 885-904, 976-998, 1050-1076, 1116-1175 | SILENT / DEFENSIVE |

## 5. Util and config

| Decision | Location | Posture |
|---|---|---|
| `round_accounting`: ROUND_HALF_UP, 3dp below 100 / 2dp at-or-above (single rounding authority for totals and rendering). | util/__init__.py:6-34 | core spec decision |
| Stock sort: (referenceDate, mutation) — balances before mutations same-day; payments by paymentDate, stable. | util/sorting.py:7-37 | SILENT (convention) |
| Date coverage: adjacent ranges (gap ≤ 1 day) merge as continuous; inclusive endpoints; invalid ranges raise. Schwab uses this as a fatal gate. | util/date_coverage.py:15-52 | DEFENSIVE (where used) |
| `security_tax_value_to_stock`: Dec-31 tax value → Jan-1 opening balance (start-of-day bridge). | util/converters.py:7-30 | SILENT (convention) |
| Known-issues suppression table (H31): kursliste-flag mismatches, payment-name diffs, undefined-payment absences, `additionalWHT-USA` expected-0, UBS &lt;0.005/0.01 tolerances, True Wealth 2% FX + CHF-fund whitelist + one hard-coded ISIN/date carve-out, universal &lt;0.01 revenue tolerance. Affects VERIFY display only. | util/known_issues.py:29-145 | SILENT (suppression) |
| Config: canton default None (may come from broker data); `keep_existing_payments=False` (Kursliste replaces broker payments by default); reconciliation tolerance 0.05; missing config file → warning + defaults; TOML floats as Decimal; failed `--set` overrides logged+skipped; per-account load failures skip the account (its assets vanish from a multi-account import); path resolution arg → XDG → CWD (environment decides which Kursliste files are used). | config/models.py:11-14, 73-76, 113-126; config/loader.py:35-47, 74-133, 197-227, 323-343; config/paths.py:26-93 | mixed — mostly WARNS/SILENT |

## 6. Render (`render/`)

| Decision | Location | Posture |
|---|---|---|
| Summary amounts displayed integer-rounded (second rounding vs. XML); detail 2dp; **all formatters bare-except to '0'/'0.00'/blank (H12)**. | render.py:109-130 | SILENT |
| `format_currency` renders blank for None **and exact zero** (zero vs. missing indistinguishable); rate 1 rendered blank. | render.py:133-165 | SILENT |
| Quantities display-quantized to an inferred per-security template (default 4dp). | render.py:168-191, 2130-2152 | SILENT |
| Rows sorted by `exDate or paymentDate` while displaying paymentDate. | render.py:2135-2164 | SILENT |
| Render-time recomputation: brutto-gesamt and steuerwert_ab fallbacks with `or Decimal('0')`; DA-1 country subtotals summed in the renderer from unrounded values; cost totals summed in the renderer (H12). | render.py:2683-2696, 2005-2054, 1170-1186 | SILENT |
| A/B/DA-1 page classification recomputed at render via `determine_security_type` — exists only in presentation, not XML. | render.py:1984-1996 | SILENT |
| Hard failure on payments with `quantity=None` and on PERCENT-quoted stocks (consistent with bond refusal). | render.py:2136-2140, 2219-2221 | DEFENSIVE |
| 2D PDF417 barcode = complete `to_xml_bytes()` zlib-compressed; stale pdf417gen fork detected and raises. | render.py:1504-1610 | DEFENSIVE |
| 1D Code128: metadata only; generation failure → None → page silently lacks its barcode (H35). | onedee.py:29-76; render.py:435-439 | SILENT |
| Barcode org_nr from `statement.id[2:7]`, else fabricated SNB-range number (warning). | render.py:2618-2626; core/organisation.py:53-74 | WARNS |
| Markdown instruction sections silently dropped if version markers are missing (text only, not figures). | markdown_renderer.py:44-89 | SILENT |

---

# Cross-cutting themes and recommendations

1. **Unknown-transaction posture is inconsistent across importers.** DeGiro
   and Fidelity raise on unknown types; IBKR raises only for security-less
   unknown cash types; Schwab silently absorbs unknown cash actions (H1).
   Recommendation: every importer should either raise or emit a critical
   warning for any row it cannot positively classify; "recognized but
   skipped" kinds (H2) should be whitelisted explicitly with a documented
   tax rationale, not fall into a default `else`.
2. **Two divergent gross-revenue strategies.** Schwab classifies income at
   import (`grossRevenueB`); IBKR/Fidelity/DeGiro emit untyped payments and
   defer to calculators. A downstream classification gap affects three
   importers at once (see FillIn's no-VSt-claim path, §3.5).
3. **Missing data collapses to zero** throughout totals, payment synthesis,
   and rendering (H7, H8, H12). `None` should be distinguished from `0` at
   the totals layer, and unresolved positions should produce critical
   warnings rather than vanish.
4. **The Kursliste XML and SQLite backends disagree numerically** (H5, H13)
   and failure silently switches backends (kursliste_manager.py:148-156).
   The denomination bug in the XML path is the single highest-leverage fix.
5. **"Not found" is conflated with "error"** across the Kursliste layer
   (H17), then memoized. Errors should raise; absence should be an explicit
   typed result.
6. **Signalling**: replace stdout `print` with `logging` in `core/`,
   replace `assert` guards with real exceptions, and consider failing the
   run (or requiring an explicit `--force`) when critical warnings exist,
   since they never reach the XML/barcode (H30).
7. **Year-boundary conventions** (start-of-day balances, `period_to + 1`
   closing, exact `period_from` opening) are encoded in at least four
   places (H18); they should be centralized and asserted at import time.
8. **Costs/fees are ignored by all importers** (Schwab TODO, IBKR FEES
   skip, DeGiro consumed siblings, Fidelity dead commission check). This is
   a consistent policy but is undocumented to the user; deductible custody
   costs simply never appear.
