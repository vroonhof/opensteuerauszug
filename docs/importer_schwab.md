# Charles Schwab Importer Guide

This guide explains how to prepare your data from Charles Schwab for use with OpenSteuerAuszug. 


Unfortunately Schwab has put its real export data behind a developer only API where it is only available online via Oauth and even the documentation requires agreeing to scary legalese. Manual export has some silly limitations like not being able to specify a target date for some dumps. Therefore we make do with what we can have, you may need to download multiple files in different formats.

## Overview

All data files should be downloaded in a single directory. The software will detect the file types automatically. You provide the directory on the commandline.

In general we are trying to obtain
   * At least one position statement (typically today), but more is better.
   * transaction data that overlaps the tax year and the dates of the position statements.

The importer will infer the beginning and end of year positions from these.

## Required Inputs

You will need to download data for your Brokerage accounts and any Equity Awards accounts separately. 

### 1. Brokerage Accounts

**a) Positions File (CSV)**

*   **How to obtain**:
    1.  Log in to your Charles Schwab account.
    2.  Navigate to your brokerage account view.
    3.  Look for an option to download or export your positions. This is typically &mdash; sadly &mdash; only available for the current date.
    4.  Choose **CSV format** for the download.
*   **Format Details for Developers**:
    *   The CSV file has a few header lines before the actual data. The importer is designed to handle this.
    *   Key columns used: `Symbol`, `Description`, `Qty (Quantity)`, `Cost Basis`.
    *   Example structure (simplified):
        ```csv
        "Positions for account Individual ...123 as of ...","","","..."
        "","","","..."
        "Symbol","Description","Qty (Quantity)","Price","Cost Basis","..."
        "SCHB","SCHWAB US BROAD MARKET ETF","100.00","$50.00","..."
        ```
* Note that the account number is truncated, we will fix this later in the config file.
*   **Important**: Schwab typically only allows downloading positions for the *current day*. If you cannot get an exact year-end position file, the system may rely more heavily on transaction data to reconstruct positions, or you might need to use the [Manual Positions Fallback CSV](#3-manual-positions-fallback-csv-optional).

**b) Transactions File (JSON)**

*   **How to obtain**:
    1.  Log in to your Charles Schwab account.
    2.  Navigate to your brokerage account's transaction history or activity page.
    3.  Select the option to export or download transactions.
    4.  Choose the **JSON format**.
    5.  Ensure you select the correct date range covering 
        * the entire tax year (e.g., January 1st to December 31st).
        * at least one, but ideally all of the dates you have position data for.
*   **Format Details for Developers**:
    *   The filename usually contains the last 3 digits of your account number (e.g., `Individual_XXX123_Transactions_YYYYMMDD-HHMMSS.json`). The importer uses these digits to associate the file with the correct account configured in `config.toml`.
    *   Key fields used: `Date`, `Action`, `Symbol`, `Description`, `Quantity`, `Amount`.
    *   Example structure (simplified):
        ```json
        {
          "FromDate": "01/01/2023",
          "ToDate": "12/31/2023",
          "BrokerageTransactions": [
            {
              "Date": "12/30/2023",
              "Action": "Credit Interest",
              "Symbol": "",
              "Description": "SCHWAB1 INT ...",
              "Quantity": "",
              "Amount": "$9.99"
            },
            {
              "Date": "11/15/2023",
              "Action": "Buy",
              "Symbol": "XYZ",
              "Description": "XYZ CORP",
              "Quantity": "10.0", // Note: For "Sale", quantity is positive in JSON
              "Price": "$100.00",
              "Amount": "-$1000.00" // Includes fees
            }
          ]
        }
        ```

### 2. Equity Awards Accounts (e.g., Stock Options, RSUs)

Some Schwab Equity Awards setups keep each award security in the awards area until it is sold or transferred. For those accounts, repeat the export for each equity in the equity awards account; the importer treats them as separate "depots" for the Steuerauszug.

Other setups vest/lapse RSUs directly into the main brokerage/trading account. In that case the vested shares appear in the regular brokerage transactions, usually as `Stock Plan Activity`, and there is no separate end-of-year award position to import. You do not need to look for per-stock Equity Awards statement PDFs for those securities. The Equity Awards transaction export is also redundant for those vested shares, because the corresponding `Lapse` rows only describe the award-side release and the importer ignores them to avoid double counting the deposit in the brokerage account.

**a) Transactions File (JSON)**

*   **How to obtain**:
    1.  Log in to your Schwab Equity Awards portal.
    2.  Go to the transaction history for your equity awards.
    3.  Export the transactions, selecting **JSON format**.
    4.  Ensure the date range covers the entire tax year.
*   **Format Details for Developers**:
    *   The JSON structure is slightly different from the brokerage account, containing a `Transactions` array (note the pluralization difference).
    *   Key fields used: `Date`, `Action`, `Symbol`, `Description`, `Quantity`, `TransactionDetails` (which can include `VestFairMarketValue`).
    *   Example structure (simplified):
        ```json
        {
          "FromDate": "01/01/2023",
          "ToDate": "12/31/2023",
          "Transactions": [
            {
              "Date": "12/20/2023",
              "Action": "Deposit",
              "Symbol": "XYZ",
              "Quantity": "50.0",
              "Description": "RS (Restricted Stock Release)",
              "TransactionDetails": [ { "Details": { "VestFairMarketValue": "$150.00" } } ]
            }
          ]
        }
        ```
*   **End of year statements**: Schwab currently does not provide a machine-readable positions file for Equity Awards. If your awards remain in a separate awards depot at year end, download the PDF version of the final quarter statement and put it in the data directory. It has a header named `Account Statement` and a section with heading `Account Summary: SYMBOL`. If your RSUs vest directly into the main brokerage account, Schwab may not provide these per-stock awards PDFs; use the regular brokerage statement/transactions instead. If this is insufficient, you may need to use the [Manual Positions Fallback CSV](#3-manual-positions-fallback-csv-optional).

### 3. Manual Positions Fallback CSV (Optional)

If you cannot obtain accurate position files, or if you need to provide initial balances or supplement data for accounts where automated extraction is difficult, or you would like to provide extra data points for the internal consistency check, you can use a manually created CSV file.

*   **CSV Format**:
    *   Must have a header row. Header order does not matter; matching is case-insensitive and ignores leading/trailing spaces.
    *   **Required columns**: `Depot`, `Date`, `Symbol`, `Quantity`. An optional `Currency` column may be added (defaults to `USD` when absent or blank).
    *   **Columns**:
        1.  `Depot`: Identifies which sub-account the row belongs to.
            *   **All digits** (e.g. `123`): the last digits of a regular Schwab brokerage account number. Use just the digits; the canonical Schwab depot ID is the last three.
            *   **Ticker-shaped value** (e.g. `GOOG`, `BRK.B`): an Equity Awards sub-account tied to that stock. Internally this maps to the `AWARDS` depot with the symbol as the sub-account identifier. The literal value `AWARDS` is **not** accepted — use the actual equity award symbol instead.
        2.  `Date`: Position date in `YYYY-MM-DD` format. The quantity is the balance at the **start** of this day. For year-end 2023 positions, use `2024-01-01`.
        3.  `Symbol`: Ticker symbol for security positions. Use `CASH` to declare a cash position. The legacy `CASH <id>` (with suffix) value is no longer accepted.
        4.  `Quantity`: Number of shares/units for a security, or the cash amount for a cash position.
        5.  `Currency` (optional): ISO currency code for the row. Defaults to `USD`.
*   **Example CSV**:
    ```csv
    Depot,Date,Symbol,Quantity,Currency
    789,2024-01-01,AAPL,100.5,USD
    789,2024-01-01,CASH,5000.75,USD
    GOOG,2024-01-01,GOOG,20.0,USD
    GOOG,2024-01-01,CASH,250.00,USD
    ```
*   **Usage**: Place this CSV file in the data directory. Rows with errors will be skipped with a logged warning.

### 4. Recommended: Human readable statements

For verification and to respond to tax office inquiries it is good to also keep the official schwab statements as PDFs. The software will ignore them so they can be kept together in the same folder.

## Configuration 

### (`config.toml`)

Because 'privacy' Schwab doesn't tell you your own account numbers in the exported files.

In your `config.toml`, configure your Schwab accounts. There is a subsection for each account, the name of the section does not matter.:

```toml
# Example for Schwab accounts
[brokers.schwab]
  # Broker-level settings, e.g.
  # default_currency = "USD" # If applicable

  [brokers.schwab.accounts.brokerage_main]
  account_number = "1234-5678" # Last 3-4 digits will be used to match the anonymized account number.
  # This account_number must match the digits identified from the transaction JSON filename.

  [brokers.schwab.accounts.equity_awards]
  account_number = "AWARDS" # Or another unique identifier if your Equity Awards JSON doesn't have a number in filename
  # Ensure this matches how you identify this account, possibly through the 'Depot' in fallback CSV if used.
```

The `account_number` in `config.toml` is used to link the transaction files (and fallback CSV data) to the correct account. For brokerage accounts, this should match the trailing digits from the transaction JSON filename and header data. For "AWARDS", it can be a symbolic name.

### Mapping symbols to Kursliste/Valor

Schwab provides only symbols for equities, no ISINs or other identifiers. You need to provide a (reusable) mapping in `data/security_identifiers.csv`.

See the [Configuration Guide](config.md#security-identifier-enrichment) for how to do this.

## Running Opensteuerauszug

```console
opensteuerauszug process --importer schwab <path to data directory> ...
```


## Importer Specifics & Known Quirks

*   **Brittle Conventions** because Schwab provides a a bunch of partial solutions for manual inputs, this has been tested mostly only with the authors' real world data.
*  **End of year positions are inferred**: Because typically you won't have position data at the tax valuation date, stock and cash positions are inferred. Therefor please double check extra carefully. Ideally would have position information at the beginning and end of the range to allow for consistency checking.

## Troubleshooting

*   **Mismatched Account Numbers**: Ensure the `account_number` in `config.toml` correctly corresponds to the account identifiers from filenames or your fallback CSV `Depot` column.
*   **Incomplete Data**: If data seems missing, verify:
    *   Transaction files cover the full tax year.
    *   Positions file (if used) is for the correct date.
    *   All relevant files for all your accounts are provided.
*   **Date Formatting**: For manual CSV, ensure dates are strictly `YYYY-MM-DD`.

## Possible future work

* There is slowly emerging ecosystems of wrapper libraries that handles oauth and calls the Schwab API. Though we prefer processing offline downloaded files this may lead to an alternative implementation. Example libraries: [schwab-py](https://github.com/alexgolec/schwab-py) and [schwabdev](https://github.com/tylerebowers/Schwabdev).

---
Return to [User Guide](user_guide.md)
