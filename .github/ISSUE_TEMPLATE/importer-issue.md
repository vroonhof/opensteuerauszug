---
name: IBKR Importer issue report
about: Report a parsing/import issue with the IBKR importer.
title: "[importer] "
labels: [bug, importer]
---

## Helpful context

If you're comfortable sharing it, a minimal IBKR Flex XML that reproduces the problem makes it much easier to diagnose. We understand the data contains real financial information — only share what you're comfortable with.

You can use the ISIN filter script to strip the XML down to only the relevant securities and anonymize account details:

```bash
python scripts/filter_ibflex_xml.py \
  --input-file path/to/full_ibkr_flex.xml \
  --output-file path/to/minimal_repro.xml \
  --isins US0378331005
```

Use multiple ISINs when needed:

```bash
python scripts/filter_ibflex_xml.py \
  --input-file path/to/full_ibkr_flex.xml \
  --output-file path/to/minimal_repro.xml \
  --isins US0378331005 IE00B3XXRP09
```

This script:
- keeps only records linked to the specified ISINs,
- removes non-selected ISIN records,
- and anonymizes `AccountInformation` to only:
  `accountId`, `acctAlias`, `currency`, `stateResidentialAddress`
  (with anonymized values for `accountId`).

If you'd rather not attach XML, please include as much of the following as you can — any of it helps:

## Checklist

- [ ] I included the full error message/traceback.
- [ ] I listed the affected ISIN(s).
- [ ] I included the command used to run OpenSteuerAuszug.
- [ ] (Optional) I attached a minimal XML file generated with the filter script.
