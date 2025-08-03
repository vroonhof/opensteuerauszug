# Charles Schwab Importer Guide

This guide explains how to prepare your data from Charles Schwab for use with OpenSteuerAuszug. 


Unfortunately Schwab has put its real export data behind a developer only API where it is only available online via Oauth and even the documentation requires agreeing to scary legalese. Manual export has some silly limitations like. Therefor we make do with what we can have, you may need to download multiple files in different formats.

## Overview

All data files are downloaded in a single directory. The software will detect the file types automatically. You provide the directory on the commandline.

In general we are trying to obtain
   * At least one position statements (typically today)
   * transaction data that overlaps the tax year and the dates of the position statements.

The importer will infer the beginning and end of year positions from these.

## Required Inputs

You will need to download data for your Brokerage accounts and any Equity Awards accounts separately. 

### 1. Brokerage Accounts

**a) Positions File (CSV)**

*   **How to obtain**:
    1.  Log in to your Charles Schwab account.
    2.  Navigate to your brokerage account view.
    3.  Look for an option to download or export your positions. This is typically sadly only available for the current date.
    4.  Choose **CSV format** for the download.
*   **Format Details**:
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
*   **Format Details**:
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

This needs to be repeated for each equity in the equity awards account. These are treated as separate "depots" for the Steuerauszug.

**a) Transactions File (JSON)**

*   **How to obtain**:
    1.  Log in to your Schwab Equity Awards portal.
    2.  Go to the transaction history for your equity awards.
    3.  Export the transactions, selecting **JSON format**.
    4.  Ensure the date range covers the entire tax year.
*   **Format Details**:
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
*   **End of year statements**: Schwab currently does not provide a machine-readable positions file for Equity Awards. However the PDF version of the final quarter statement is simple enough so the software can parse it. Please download the PDF and put it in the data directory. It has a header named `Account Statement` and a section with heading `Account Summary: SYMBOL`.  If this is insufficient, you may need to use the [Manual Positions Fallback CSV](#3-manual-positions-fallback-csv-optional).

### 3. Manual Positions Fallback CSV (Optional)

If you cannot obtain accurate position files, or if you need to provide initial balances or supplement data for accounts where automated extraction is difficult, or you would like to provide extra data points for the internal consistency check, you can use a manually created CSV file.

*   **CSV Format**:
    *   Must have a header row. Column order matters.
    *   Case-insensitive headers (leading/trailing spaces ignored).
    *   **Columns**:
        1.  `Depot`: Account identifier.
            *   If "AWARDS" (case-insensitive), it's treated as an Equity Awards account.
            *   If the last three characters are digits (e.g., "Schwab123"), "123" is used as the identifier.
            *   Otherwise, the raw string is used (a warning may be logged).
        2.  `Date`: Position date in `YYYY-MM-DD` format (e.g., `2023-12-31`). This represents the balance at the **beginning** of this day. For year-end 2023 positions, use `2024-01-01`. 
        3.  `Symbol`: Ticker symbol. Use "CASH" (case-insensitive) for cash positions.
        4.  `Quantity`: Number of shares/units or cash amount.
*   **Example CSV**:
    ```csv
    Depot,Date,Symbol,Quantity
    AWARDS,2024-01-01,AAPL,100.5
    Schwab789,2024-01-01,CASH,5000.75
    MyBroker123,2024-01-01,GOOG,20.0
    ```
*   **Currency**: Currently defaults to "USD" for positions from this fallback CSV. All Cash is USD.
*   **Usage**: Place this CSV file the data directory. Rows with errors will be skipped with a warning.

### 4. Recommended: Human readable statements

For verification and to respond to tax office inquiries it is good to also keep the official schwab statements as PDFs. The software will ignore them so they can be kept together in the same files.

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
  account_number = "1234-5678" # Last 3-4 digits will be used to matched the anonymized account number.
  # This account_number must match the digits identified from the transaction JSON filename.

  [brokers.schwab.accounts.equity_awards]
  account_number = "AWARDS" # Or another unique identifier if your Equity Awards JSON doesn't have a number in filename
  # Ensure this matches how you identify this account, possibly through the 'Depot' in fallback CSV if used.
```

The `account_number` in `config.toml` is used to link the transaction files (and fallback CSV data) to the correct account. For brokerage accounts, this should match the trailing digits from the transaction JSON filename and header data. For "AWARDS", it can be a symbolic name.

### Mapping symbols to Kursliste/Valor

Schwab provides only symbols for equities, no ISINS or other identifiers. You need to provide a (reusable) mapping in `data/security_identifiers.csv`.

TODO: elaborate.

## Running Opensteuerauszug

```console
python -m opensteuerauszug.steuerauszug --importer schwab <path to data directory> ...
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

---
Return to [User Guide](user_guide.md)
