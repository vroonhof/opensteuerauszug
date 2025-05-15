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

'Amount' is filled for all transactions affecting the cash balance and the 'Quantiy' for everything that affects a non-cash postion with a given 'Symbol'. For "Sale" transactions, the 'Quantity' in the JSON is typically a positive number representing the number of shares sold. The extractor handles this by recording a negative quantity internally.



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

The CSV file must have a header row, and the column order matters. The expected headers are (case-insensitive and leading/trailing spaces are ignored):

1.  **Depot**:
    *   The identifier for the depot.
    *   If the value is "AWARDS" (case-insensitive), it will be used as is.
    *   Otherwise, if the depot string is 3 characters or longer and the last three characters are digits, those three digits will be used as the depot identifier.
    *   If neither of the above conditions is met, the raw string provided will be used as the depot identifier, and a warning will be logged.
2.  **Date**:
    *   The date of the position.
    *   Must be in `YYYY-MM-DD` format (e.g., `2023-01-15`).
    *   The quantity provided is considered the balance at the **start** of this specified day.
    *   For example, to report year-end positions for the year 2023, the date should be `2024-01-01`.
3.  **Symbol**:
    *   The ticker symbol for the security.
    *   If the value is "CASH" (case-insensitive), a `CashPosition` will be created.
    *   For any other value, a `SecurityPosition` will be created.
4.  **Quantity**:
    *   The number of shares or units for a security, or the amount for a cash position, as of the **start** of the specified 'Date'.
    *   This should be a numerical value (e.g., `100.50`, `5000`).

**Example CSV:**
```csv
Depot,Date,Symbol,Quantity
AWARDS,2023-01-15,AAPL,100.5
SCHWABACC789,2023-03-10,CASH,5000.75
MYACCOUNT123,2023-06-01,GOOG,20.0
SHORTDEPOT,2023-12-31,MSFT,50
```

Rows with missing required headers, incorrect column counts, invalid date formats, non-numeric quantities, or empty symbols will be skipped with a logged warning. The currency for these manually added positions is currently defaulted to "USD".
```
