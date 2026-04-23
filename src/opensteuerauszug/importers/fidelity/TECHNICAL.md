# Fidelity Importer Technical Details

This document provides technical details about the Fidelity CSV file formats and the importer's internal logic. This information is primarily for developers or users who need to debug specific issues with their data.

## Positions File (CSV) Format

The positions CSV file, typically named `Statementmddyyyy.csv`, contains two main tables: an account summary and a list of positions.

### Example Structure (Simplified)

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

### Symbols to Ignore

The importer ignores certain entries in the `Symbol/CUSIP` column that represent subtotals or internal core account positions:
- `Subtotal of Core Account`
- `QPIQQ`
- `QPIFQ`
- `Core Account`
- `Subtotal of Stocks`

## Transactions File (CSV) Format

The transactions file contains activity for a specified date range.

### Example Structure

```csv
Run Date,Account,Account Number,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),Amount ($),Settlement Date
03/25/2025,"Account Name","A12345678","REINVESTMENT VANGUARD INTL EQUITY INDEX FDS TT WR... (VT) (Cash)",VT,"VANGUARD INTL EQUITY INDEX FDS TT WRLD ",Cash,118.9,0.535,,,,-63.64,
03/25/2025,"Account Name","A12345678","DIVIDEND RECEIVED VANGUARD INTL EQUITY INDEX FDS TT WR... (VT) (Cash)",VT,"VANGUARD INTL EQUITY INDEX FDS TT WRLD ",Cash,,0.000,,,,90.91,
03/25/2025,"Account Name","A12345678","NON-RESIDENT TAX VANGUARD INTL EQUITY INDEX FDS TT WR... (VT) (Cash)",VT,"VANGUARD INTL EQUITY INDEX FDS TT WRLD ",Cash,,0.000,,,,-27.27,
```

### Date Parsing Logic

The importer extracts the statement date from the filename (`Statementmddyyyy.csv`). For transactions, it primarily uses the `Run Date` column. However, for certain actions like dividends or interest, it may look for an "as of" date within the `Action` or `Description` string to match the appropriate tax period or exchange rate.

## Defined Actions

The following actions are identified and mapped to the internal model:

| CSV Action String | Internal Action |
|-------------------|-----------------|
| BOUGHT | buy |
| IN LIEU | Cash In Lieu (ignored for tax) |
| INTEREST EARNED | Credit Interest |
| DIRECT DEPOSIT | Deposit |
| DIVIDEND RECEIVED | dividend |
| ADJ NON-RESIDENT TAX | NRA Tax Adj |
| REINVESTMENT | buy (reinvested dividend) |
| SOLD | sell |
| Stock Plan Activity | Stock Plan Activity |
| SPLIT | stock_split |
| NON-RESIDENT TAX | Tax Withholding |
| TRANSFER OF ASSETS | transfer |
| Wire Transfer | Wire Transfer |
| DIRECT DEBIT | DIRECT DEBIT |
