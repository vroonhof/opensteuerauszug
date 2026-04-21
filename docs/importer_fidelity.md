# Fidelity Importer Guide

This guide explains how to prepare your data from Fidelity for use with OpenSteuerAuszug. 

## Overview

All data files should be downloaded in a single directory. The software will detect the file types automatically. You provide the directory on the commandline.

In general, we are trying to obtain
   * The monthly statement for the final month of the tax period.
        * Any single statement will work except for the final cash value in your account, which is not currently properly calculated.
        * You can use any number of monthly statements where the positions at the end of the month will be used by the PositonReconciler
          * however: the cash value in the account is determined by the statement with the latest date.
   * transaction data that overlaps the tax year and the dates of the position statements.

The importer will infer the beginning and end of year positions from these. The Fidelity importer does not calculate the end of period cash values in your account, this is taken directly from the statement with the latest date in the title.

## Equity Awards
Currently not-supported

# Defined Actions
In my statements I have seen the following 'actions' which are identified from the Description string:

"Buy", "Cash In Lieu (ignored for tax statement)", "Credit Interest", "Dividend", "NRA Tax Adj", "Reinvest Dividend", "Sale", "Reverse Stock Split", "Tax Withholding", "Transfer"

## Required Inputs
You will need to download data for your accounts separately. 

### 1. Preparation
**a) Positions File (CSV)**
*   **How to obtain**:
    1. From the Fidelity home page choose your account from the left hand menu.
    1. Then choose 'Documents 
    1. From there you can download monthly statements in CSV format.
    2. The filename will be {Statementmddyyyy.csv} where {m} is not padded. The statement date is taken from the file name
*   **Format Details for Developers**:
    *   The CSV file contains 2 tables, a summary, and a statement of positions. The importer is designed to handle this.
    *   positons in the Symbol/CUISP column can be skipped is added to ```python SYMBOLS_TO_IGNORE = ['Subtotal of Core Account','QPIQQ','QPIFQ','Core Account','Subtotal of Stocks']```
    *   Example structure (simplified):
        ```csv
        Account Type,Account,Beginning mkt Value,Change in Investment,Ending mkt Value,Short Balance,Ending Net Value,Dividends This Period,Dividends Year to Date,Interest This Year,Interest Year to Date,Total This Period,Total Year to Date
        Account Name,A12345678,3000.00,100.00,3100.00,,3200.00,10.00,50.00,2.00,15.00,12.00,65.00
 

        Symbol/CUSIP,Description,Quantity,Price,Beginning Value,Ending Value,Cost Basis
 

        A12345678
        Stocks 
        VT,VANGUARD INTL EQUITY INDEX FDS TT WRLD ST ETF ,100.00000,10.00000,3000.00,3100.00,3000.00
        Subtotal of Stocks,,,,,3100.00,3000.00,,,, 

        A12345678
        Core Account 
        QPIFQ,FDIC INSURED DEPOSIT  AT TRUIST BANK NOT COVERED BY SIPC q,0.50000,1.00000,0.50,0.50,not applicable
        QPIQQ,FDIC INSURED DEPOSIT AT WELLS FARGO BK NOT COVERED BY SIPC q,0.10000,1.00000,0.50,0.50,not applicable
        Subtotal of Core Account,,,,,1.00,,,,,
       
        ```

In principle, you only need the statement for the last month of your tax period.  This is where we get positions, and the cash value in the account from. The annual statement is only available as a PDF and is not used. 

**b) Transactions File (CSV)**
*   **How to obtain**:
    1. From the Fidelity home page choose your account from the left hand menu.
    1. Then choose 'Activity & Orders'
    1. From the drop-down menu which is initially set to '30 days' choose custom and apply the dates required
    1. Use the download button (next to the printer symbol) to download the transactions in CSV format.

Transactions Can be downloaded for up to a year (they say 365 days).
*   **The Transactions CSV is formatted like this**:
       ```csv
       Run Date,Account,Account Number,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),Amount ($),Settlement Date
       03/25/2025,"Account Name","A12345678","REINVESTMENT VANGUARD INTL EQUITY INDEX FDS TT WR... (VT) (Cash)",VT,"VANGUARD INTL EQUITY INDEX FDS TT WRLD ",Cash,118.9,0.535,,,,-63.64,
       03/25/2025,"Account Name","A12345678","DIVIDEND RECEIVED VANGUARD INTL EQUITY INDEX FDS TT WR... (VT) (Cash)",VT,"VANGUARD INTL EQUITY INDEX FDS TT WRLD ",Cash,,0.000,,,,90.91,
       03/25/2025,"Account Name","A12345678","NON-RESIDENT TAX VANGUARD INTL EQUITY INDEX FDS TT WR... (VT) (Cash)",VT,"VANGUARD INTL EQUITY INDEX FDS TT WRLD ",Cash,,0.000,,,,-27.27,



       "The data and information in this spreadsheet is provided to you solely for your use and is not for distribution. The spreadsheet is provided for"
       "informational purposes only, and is not intended to provide advice, nor should it be construed as an offer to sell, a solicitation of an offer to buy or a"
       "recommendation for any security or insurance product by Fidelity or any third party. Data and information shown is based on information known to Fidelity as of the date it was"
       "exported and is subject to change. It should not be used in place of your account statements or trade confirmations and is not intended for tax reporting"
       "purposes. For more information on the data included in this spreadsheet, including any limitations thereof, go to Fidelity.com."

       "Brokerage services are provided by Fidelity Brokerage Services LLC (FBS), 900 Salem Street, Smithfield, RI 02917. Custody and other services provided by National"
       "Financial Services LLC (NFS). Both are Fidelity Investment companies and members SIPC, NYSE. Insurance products at Fidelity are distributed by"
       "Fidelity Insurance Agency, Inc., and, for certain products, by Fidelity Brokerage Services, Member NYSE, SIPC."

       Date downloaded 01/01/2026 11:59 am
       ```
However... sometimes the date we need is in the description (something handled correctly by the importer) or sometimes,
seen for a reverse split there is no symbol, in which case the best solution is to edit the CSV directly.
Rows with missing required headers, incorrect column counts, invalid date formats, non-numeric quantities, or empty symbols will be skipped with a logged warning.

## Configuration 

### (`config.toml`)

Fidelity doesn't your name or address in the exported files. So you should provide your name and canton.
This will be picked up from the general section, but can also be specified specifically for your Fidelity account.
account_number is required by the AccountSettingsBase

In your `config.toml`, configure your Fidelity accounts. There is a subsection for each account, the name of the section does not matter.:

```toml
# Example for Fidelity accounts
[brokers.fidelity]
  # Broker-level settings, e.g.
  # default_currency = "USD" # If applicable

  [brokers.fidelity.accounts.default_fidelity_account]
  full_name = "Regular Person" 
  canton = "ZH"
  account_number = "A12345678"

```

### Mapping symbols to Kursliste/Valor

Fidelity provides only symbols for equities, no ISINs or other identifiers for US based stocks.
For Stocks in other countries ISIN's are provided in the Description field of the monthly statement but the importer ignores these.
You need to provide a (reusable) mapping in `data/security_identifiers.csv`.

See the [Configuration Guide](config.md#security-identifier-enrichment) for how to do this.

## Running Opensteuerauszug

```console
opensteuerauszug process --importer fidelity \
  --tax-year <year> \
  -o <outputpdf.pdf> <path to data directory> ...
```

## Importer Specifics & Known Quirks

*   **Brittle conventions**: because Fidelity provides a bunch of partial solutions for manual inputs, this has been tested mostly only with the authors' real world data.
*   **Missing symbols**:  for the inverse stock split I added the symbols in by hand -- they were listed in the Description
*   **Incorrect dates**:  For some items to match the kusliste date we need is in the description (something handled correctly by the importer), but watch out for this!
## Troubleshooting

*   **Mismatched Account Numbers**: Ensure the `account_number` in `config.toml` correctly corresponds to the account identifiers in your CSV files
*   **Incomplete Data**: If data seems missing, verify:
    *   Transaction files cover the full tax year.
    *   Positions file (if used) is for the correct date.
    *   All relevant files for all your accounts are provided.


---
Return to [User Guide](user_guide.md)
