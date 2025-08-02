# Charles Schwab Importer Guide

This guide explains how to prepare your data from Charles Schwab for use with OpenSteuerAuszug. Due to Schwab's current export limitations, you may need to download multiple files in different formats.

## Required Inputs

You will need to download data for your Brokerage accounts and any Equity Awards accounts separately.

### 1. Brokerage Accounts

**a) Positions File (CSV)**

*   **How to obtain**:
    1.  Log in to your Charles Schwab account.
    2.  Navigate to your brokerage account view.
    3.  Look for an option to download or export your positions. This is typically available for the current date.
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
*   **Important**: Schwab typically only allows downloading positions for the *current day*. For tax purposes (year-end positions), you should download this file as close as possible to your desired reporting date (e.g., end of the tax year or early January of the following year). If you cannot get an exact year-end position file, the system may rely more heavily on transaction data to reconstruct positions, or you might need to use the [Manual Positions Fallback CSV](#3-manual-positions-fallback-csv-optional).

**b) Transactions File (JSON)**

*   **How to obtain**:
    1.  Log in to your Charles Schwab account.
    2.  Navigate to your brokerage account's transaction history or activity page.
    3.  Select the option to export or download transactions.
    4.  Choose the **JSON format**.
    5.  Ensure you select the correct date range covering the entire tax year (e.g., January 1st to December 31st).
*   **Format Details**:
    *   The filename usually contains the last 3 digits of your account number (e.g., `Individual_XXX123_Transactions_YYYYMMDD-HHMMSS.json`). The importer uses these digits to associate the file with the correct account configured in `config.toml`.
    *   The JSON structure contains a `BrokerageTransactions` array.
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
*   **Positions for Equity Awards**: Schwab currently does not provide a machine-readable positions file for Equity Awards. OpenSteuerAuszug will typically determine positions based on the transaction history. If this is insufficient, you may need to use the [Manual Positions Fallback CSV](#3-manual-positions-fallback-csv-optional).

### 3. Manual Positions Fallback CSV (Optional)

If you cannot obtain accurate position files, or if you need to provide initial balances or supplement data for accounts where automated extraction is difficult, you can use a manually created CSV file.

*   **Processor**: `FallbackPositionExtractor`
*   **CSV Format**:
    *   Must have a header row. Column order matters.
    *   Case-insensitive headers (leading/trailing spaces ignored).
    *   **Columns**:
        1.  `Depot`: Account identifier.
            *   If "AWARDS" (case-insensitive), it's treated as an Equity Awards account.
            *   If the last three characters are digits (e.g., "Schwab123"), "123" is used as the identifier.
            *   Otherwise, the raw string is used (a warning may be logged).
        2.  `Date`: Position date in `YYYY-MM-DD` format (e.g., `2023-12-31`). This represents the balance at the **end** of this day. For year-end 2023 positions, use `2023-12-31`. *(Note: The internal `formats.md` said start of day for `YYYY-MM-DD` and `YYYY+1-01-01` for year-end. This user guide simplifies to end-of-day `YYYY-MM-DD` for clarity, assuming the extractor handles it appropriately or this is the more user-intuitive way. This might need internal alignment.)*
        3.  `Symbol`: Ticker symbol. Use "CASH" (case-insensitive) for cash positions.
        4.  `Quantity`: Number of shares/units or cash amount.
*   **Example CSV**:
    ```csv
    Depot,Date,Symbol,Quantity
    AWARDS,2023-12-31,AAPL,100.5
    Schwab789,2023-12-31,CASH,5000.75
    MyBroker123,2023-12-31,GOOG,20.0
    ```
*   **Currency**: Currently defaults to "USD" for positions from this fallback CSV.
*   **Usage**: Place this CSV file in a location OpenSteuerAuszug can access and provide the path when running the import. Rows with errors will be skipped with a warning.

## Configuration (`config.toml`)

In your `config.toml`, configure your Schwab accounts:

```toml
# Example for Schwab accounts
[brokers.schwab] # Or your preferred alias for Charles Schwab
  # Broker-level settings, e.g.
  # default_currency = "USD" # If applicable

  [brokers.schwab.accounts.brokerage_main]
  account_number = "123" # Last 3-4 digits of your brokerage account number from the JSON filename
  # This account_number must match the digits identified from the transaction JSON filename.

  [brokers.schwab.accounts.equity_awards]
  account_number = "AWARDS" # Or another unique identifier if your Equity Awards JSON doesn't have a number in filename
  # Ensure this matches how you identify this account, possibly through the 'Depot' in fallback CSV if used.
```

The `account_number` in `config.toml` is used to link the transaction files (and fallback CSV data) to the correct account. For brokerage accounts, this should match the trailing digits from the transaction JSON filename. For "AWARDS", it can be a symbolic name.

## Importer Specifics & Known Quirks

*   **Multiple Files**: You need to provide the relevant set of files (Positions CSV + Transactions JSON for brokerage; Transactions JSON for equity awards; optional Fallback CSV).
*   **Transaction `Action` Types**: The importer recognizes various `Action` types like "Buy", "Sale", "Dividend", "Credit Interest", "Deposit", "Stock Split", "Cash In Lieu", etc. "Sale" transactions in the JSON have positive quantities; the importer correctly interprets these as a reduction in holdings.
*   **Equity Awards Positions**: Since there's no direct positions download for equity awards, their state is primarily derived from transactions. Ensure your transaction history is complete.
*   **File Naming for Brokerage Transactions**: The importer relies on the last 3 digits in the brokerage transaction JSON filename (e.g., `...XXX123_Transactions_....json`) to map to the `account_number` in `config.toml`. Ensure these match.

## Troubleshooting

*   **Mismatched Account Numbers**: Ensure the `account_number` in `config.toml` correctly corresponds to the account identifiers from filenames or your fallback CSV `Depot` column.
*   **Incomplete Data**: If data seems missing, verify:
    *   Transaction files cover the full tax year.
    *   Positions file (if used) is for the correct date.
    *   All relevant files for all your accounts are provided.
*   **Date Formatting**: For manual CSV, ensure dates are strictly `YYYY-MM-DD`.

---
Return to [User Guide](user_guide.md)
