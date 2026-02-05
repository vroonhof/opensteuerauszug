# Domain Notes

- The **eCH-0196** standard is the Swiss XML format for electronic tax statements. The XSD schemas are in `specs/`.
- Security names must be truncated to 60 characters (eCH-0196 limit) even though the Kursliste allows 120.
- The software is **not** the actual broker/bank; it generates statements from broker data. Organization identifiers use workarounds (e.g., prefixed with "OPNAUS") since the format assumes a Swiss financial institution.
- Tax values in the generated output are **informational only** — the official tax software should recalculate from Kursliste data.
- The **Kursliste** is the official Swiss tax valuation list published by the ESTV. It can be loaded from XML or SQLite. The `KurslisteManager` in `core/` handles access.
- Each broker has its own subpackage under `importers/`. See `docs/importer_schwab.md` and `docs/importer_ibkr.md` for broker-specific details.
