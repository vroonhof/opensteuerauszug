# Descriptions of Schwab statement formats we support

Sadly Schwab no longer provides a single sensible export format to clients to download
(things like ofx are hidden by developper access with scary T&Cs and require online access),
Oath...  ec

Instead we make do witt what we have. We require the user download multiple files and they are all in differnt formats.

## Brokerage Account

### Positions

The positions are downloadable for the current date in CSV format. Unfortunately the seems to be no way to get a positions statement for a past date (the site refers to statements which are only quarterly and only in PDF)

The format is somewhat ugly as the headers are not even at the top and a the moment looks like

```csv
"Positions for account Individual ...123 as of 12:33 PM ET, 2025/05/04","","","","","","","","","","","","","","","",""
"","","","","","","","","","","","","","","","",""
"Symbol","Description","Qty (Quantity)","Price","Price Chng $ (Price Change $)","Price Chng % (Price Change %)","Mkt Val (Market Value)","Day Chng $ (Day Change $)","Day Chng % (Day Change %)","Cost Basis","Gain $ (Gain/Loss $)","Gain % (Gain/Loss %)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Security Type"
"SCHB","SCHWAB US BROAD MARKET ETF","9,999.99","$99.99","$0.99","99.99%","$9099.99","$99.99","99.99%","99099.99","$9099.99","99.99%","--","Yes","--","99.099%","ETFs & Closed End Funds"
...
       
```

### Transactions

Transactions data for a few date ranges is available in several formats. Though the XML format is described as containing more precision for offline
processing, there is hardly much more info and no published schema.

Unfortunately the account information is only available in the filenames which looks like this

```
Individual_XXX178_Transactions_20250309-115444.json
```
where 178 here are the last 3 digits of the account.

So we use the JSON import which looks like this for the brokerage account

```json
{
  "FromDate": "01/01/2024",
  "ToDate": "12/31/2024",
  "TotalTransactionsAmount": "$9,999.99",
  "BrokerageTransactions": [
    {
      "Date": "12/30/2024",
      "Action": "Credit Interest",
      "Symbol": "",
      "Description": "SCHWAB1 INT 11/27-12/29",
      "Quantity": "",
      "Price": "",
      "Fees & Comm": "",
      "Amount": "$9.99"
    },
    ...
  ]
}
```

'Amount' is filled for all transactions affecting the cash balance and the 'Quantity' for everything that affects a non-cash position with a given 'Symbol'. For "Sale" transactions, the 'Quantity' in the JSON is typically a positive number representing the number of shares sold. The extractor handles this by recording a negative quantity internally.



## Equity Awards

### Positions

For Equity Awards there is no machine readable positions format that we know of, so instead we require the user download the PDF transactions. Each company or company share type in Equity awards gets its own transaction statement with just one stock and a potential cash balance.

Because I am too scared to sent your tax data to a remote LLM we resort to old school regex for now.

### Transactions

The transactions format in JSON is similar to that of the Brokerage statement but recognizably different

```json
{
  "FromDate": "01/01/2024",
  "ToDate": "12/31/2024",
  "Transactions": [
    {
      "Date": "12/30/2024",
      "Action": "Deposit",
      "Symbol": "GOOG",
      "Quantity": "99.99",
      "Description": "RS",
      "FeesAndCommissions": null,
      "DisbursementElection": null,
      "Amount": null,
      "TransactionDetails": [
        {
          "Details": {
            "AwardDate": "03/06/2024",
            "AwardId": "C1233560",
            "VestDate": "12/25/2024",
            "VestFairMarketValue": "$197.57"
          }
        }
      ]
    },
    ...
  ]
}
```

'TransactionDetails' can be an empty list but seems always present. 

Unlike for statements all award positions share a single transactions statements.

# Shared Formats

As you can see above the items in the transaction lists are essentially
the same. In my statements I have seen the following Action types

```json
      "Action": "Buy",
      "Action": "Cash In Lieu",
      "Action": "Credit Interest",
      "Action": "Deposit",
      "Action": "Dividend",
      "Action": "Journal",
      "Action": "NRA Tax Adj",
      "Action": "Reinvest Dividend",
      "Action": "Reinvest Shares",
      "Action": "Sale",
      "Action": "Stock Split",
      "Action": "Tax Withholding",
      "Action": "Transfer",

## Manually Provided Positions (Fallback CSV)

If the primary position extractors fail or if you need to manually add known positions (e.g., for accounts where automated extraction is not supported or for initial balances), you can use a CSV file with the following format. This file is processed by the `FallbackPositionExtractor`.

The CSV file must have a header row. Header matching is case-insensitive and ignores leading/trailing spaces. Required columns are `Depot`, `Date`, `Symbol`, `Quantity`; `Currency` is optional.

1.  **Depot**:
    *   Identifies the sub-account the row belongs to.
    *   **All digits** (e.g. `123`): the last digits of a regular Schwab brokerage account number, used as-is. The canonical Schwab depot identifier is the last three digits.
    *   **Ticker-shaped value** (e.g. `GOOG`, `BRK.B`): an Equity Awards sub-account associated with that stock. Internally this maps to depot `AWARDS` with the value as the cash sub-account identifier (or as the security symbol).
    *   The literal value `AWARDS` is rejected; supply the actual equity award symbol instead. Mixed alphanumeric values (e.g. `SCHWABACC789`) are rejected.
2.  **Date**:
    *   Position date in `YYYY-MM-DD` format (e.g., `2023-01-15`).
    *   The quantity is the balance at the **start** of this day. For year-end 2023 positions use `2024-01-01`.
3.  **Symbol**:
    *   Ticker symbol for a security position.
    *   **Leave empty** to declare a cash position in the depot.
    *   The legacy `CASH` and `CASH <id>` shapes are no longer accepted.
4.  **Quantity**:
    *   Number of shares/units for a security, or the cash amount, as of the start of the date.
5.  **Currency** (optional):
    *   ISO currency code applied to the row. Defaults to `USD` when omitted or blank.

**Example CSV:**
```csv
Depot,Date,Symbol,Quantity,Currency
789,2024-01-01,AAPL,100.5,USD
789,2024-01-01,,5000.75,USD
GOOG,2024-01-01,GOOG,20.0,USD
GOOG,2024-01-01,,250.00,USD
```

Rows with missing required headers, incorrect column counts, invalid date formats, non-numeric quantities, unsupported depot values, or legacy CASH shapes will be skipped with a logged warning.
```
