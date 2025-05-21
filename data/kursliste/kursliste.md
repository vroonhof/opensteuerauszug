# Kursliste Directory

This directory contains XML files for the Swiss tax authority's "Kursliste" (exchange rate and securities price list), which is required for accurate tax value calculations in OpenSteuerauszug.

## How to Download and Install Kursliste Files

1. Visit the official ICTax website XML download: [https://www.ictax.admin.ch/extern/de.html#/xml](https://www.ictax.admin.ch/extern/de.html#/xml)

2. Find "Kursliste Initial" file and download the latest version in V2.0+ format.

3. Unzip the downloaded file.

4. Place the extracted XML files directly in this directory (`data/kursliste/`).

## Example Directory Structure After Setup

```
data/
├── kursliste/
│   ├── kursliste.md            # This documentation file
│   ├── kursliste_2023.xml      # Kursliste data for tax year 2023
│   └── kursliste_2024.xml      # Kursliste data for tax year 2024
```

## Important Notes

- OpenSteuerauszug requires Kursliste files for any tax years you are processing.
- The Kursliste XML files are quite large (often several hundred MB) and contain all the official exchange rates and security prices for a tax year.
- We don't support delta updates. Just download the a new initial file.

## Automatic Updates

In a future version of OpenSteuerauszug, we may support automatic downloading and updating of Kursliste files. For now, please follow the manual process described above.