# Importer Design: Shared Structure Based on the Refactored IBKR Importer

## Purpose

This document describes the recommended structure for broker importers,
using the refactored IBKR importer as the reference implementation. The
goal is to keep new importers consistent, easy to review, and able to
reuse shared logic from `opensteuerauszug.importers.common`.

Use this as a design guideline when adding a new importer or refactoring an existing one.

## Why this structure

Most broker imports perform the same high-level tasks:

1. Parse one or more broker source files.
2. Normalize broker-specific rows into a common internal model.
3. Accumulate per-security mutations and payments.
4. Build final `TaxStatement` output models.

The recent IBKR refactor extracted repeated logic into shared helpers so
importers no longer need to reimplement common primitives (name
resolution, payment construction, decimal parsing, mutation aggregation,
and accumulator types).

## Recommended module layout

For a new broker importer under `src/opensteuerauszug/importers/<broker>/`, prefer this shape:

- `__init__.py`
- `<broker>_importer.py` (main orchestration)
- Optional broker-specific extractor/parser modules (if the input format is complex)
- Optional `TECHNICAL.md` for format notes and known quirks

Keep reusable cross-broker logic out of broker modules and in
`src/opensteuerauszug/importers/common/`.

## Core architecture pattern

### 1. Thin importer class, explicit orchestration

Use one importer class that owns:

- `period_from`, `period_to`
- account settings list for that broker
- optional render language

The public entrypoint should typically be `import_files(...) -> TaxStatement`.

Inside `import_files`, keep flow explicit and sequential:

1. Parse input files.
2. Initialize accumulators.
3. Iterate broker rows by section.
4. Append normalized model records into accumulators.
5. Apply post-processing (aggregation, reconciliation, cleanup).
6. Build and return `TaxStatement`.

Avoid inheritance hierarchies for importer behavior. Prefer small pure
helper functions plus composition.

### 2. Standard accumulator shapes

Use shared `TypedDict`s from `importers.common.types`:

- `SecurityPositionData`: `stocks` + `payments` per security
- `CashPositionData`: `stocks` + `payments` per cash bucket

These should back `defaultdict` accumulators during import.

### 3. Common helpers to reuse

Use these shared helpers where applicable:

- `to_decimal(...)` (`common.parsing`): consistent decimal conversion and error context
- `aggregate_mutations(...)` (`common.stock_aggregation`): collapse same-order mutation runs
- `build_security_payment(...)` (`common.payments`): standard `SecurityPayment` construction
- `apply_withholding_tax_fields(...)` (`common.payments`): consistent withholding semantics
- `SecurityNameRegistry` (`common.security_name`): best-name-wins resolution by priority
- `resolve_first_last_name(...)`, `parse_swiss_canton(...)`, `build_client(...)` (`common.client`)

When a new importer needs shared logic that is not broker-specific, add
it to `importers.common` instead of copying code into a broker module.

The common post-processing direction introduced in PR #368 should be
treated as the default for new importers: keep broker extraction code
focused on parsing/normalization, and route reusable post-processing
behavior through shared helpers in `importers.common` wherever possible.

## Suggested import pipeline

### Parse phase

- Parse only supported files; ignore or warn on unsupported types.
- Fail fast on missing required inputs.
- Keep parser exceptions wrapped with broker-specific context.

### Normalize phase

Convert broker rows into common concepts:

- Security identity (`depot`, `symbol`/broker id, optional ISIN/valor, description)
- Mutations (`SecurityStock` with date, quantity, price/currency, mutation flag)
- Payments (`SecurityPayment` and/or `BankAccountPayment`)

Normalize corner cases close to where they are parsed (for example,
broker enum variants, timestamp formats, sign conventions).

### Accumulate phase

- Key per-security data by `SecurityPosition`.
- Keep all row-derived events in arrival order.
- Record best display names with explicit priorities using `SecurityNameRegistry`.

### Post-process phase

At minimum, evaluate these post-processing steps:

- Apply the shared/common post-processing helpers first (as introduced
  with PR #368), then layer only broker-specific post-processing on top.
- Aggregate partial fills with `aggregate_mutations`.
- Reconcile position history where needed (for example with `PositionReconciler`).
- Apply importer-specific cleanup or validation.

### Build output phase

Construct final eCH-0196 model objects:

- `ListOfSecurities`
- `ListOfBankAccounts`
- `Client` (if authoritative fields are available)

Ensure missing optional data stays `None` rather than synthetic placeholders.

## Error-handling conventions

- Raise clear `ValueError` for invalid row content (missing required
  fields, invalid decimals, impossible states).
- Use contextual messages (`field`, `section`, security identifier, account id).
- Log warnings for recoverable inconsistencies and skip only the affected row.
- Keep importer behavior deterministic: same input should always produce
  the same output and warnings.

## Naming and priority strategy

Use explicit source priorities for security names (example convention used by IBKR):

- 10: end-of-period position snapshots
- 8: trade rows
- 5: transfer rows
- 0: payment descriptions/fallbacks

This prevents lower-quality labels from overwriting better names when
the same security appears in multiple sections.

## What should stay broker-specific

Even with shared helpers, the following usually remains broker-specific:

- File format parsing and schema quirks
- Broker action/type classification
- Asset-category mapping to eCH categories
- Broker-only corrections logic (for example follow-up files)

Keep these rules local to the broker importer module(s).

## Minimal checklist for a new importer

- [ ] Importer class with `import_files(...) -> TaxStatement`
- [ ] Uses `common.types` accumulators
- [ ] Uses `to_decimal` for numeric parsing
- [ ] Uses `build_security_payment` / `apply_withholding_tax_fields` when applicable
- [ ] Uses `SecurityNameRegistry` for display-name resolution
- [ ] Aggregates mutations via `aggregate_mutations` where relevant
- [ ] Builds `Client` via shared client helpers when data exists
- [ ] Clear warnings/errors with row-level context
- [ ] Unit tests cover parsing, normalization, and output invariants
- [ ] Integration test auto-discovers sample files via the
  external-sample pattern in `design/testing.md`
- [ ] Include at least one anonymized sample under `tests/samples/import/<importer>/` when possible

## Refactoring guidance for existing importers

When refactoring an existing importer toward this structure:

1. Move truly shared logic into `importers.common` first.
2. Replace local duplicated code with shared helper calls.
3. Keep behavior identical while extracting (add regression tests before changing behavior).
4. Only then simplify broker-specific flow.

This reduces regression risk and makes cross-importer behavior more consistent.
