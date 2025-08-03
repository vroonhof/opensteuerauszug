# Interactive Brokers (IBKR) Importer Guide

This guide explains how to prepare your data from [Interactive Brokers (IBKR)](https://www.interactivebrokers.com/) for use with OpenSteuerAuszug.

## Required Input: Flex Query XML File

OpenSteuerAuszug processes IBKR data using [**Flex Query XML files**](https://www.ibkrguides.com/orgportal/performanceandstatements/activityflex.htm). You need to configure a Flex Query in your IBKR Account Management that includes specific sections and fields covering the entire tax year.

### How to Obtain the Flex Query XML:

1.  **Log in** to your IBKR Account Management portal.
2.  Navigate to **"Performance & Reports" > "Flex Queries"**.
3.  (onetime) **Create a new Flex Query** or modify an existing one.
    *   Give your query a descriptive name (e.g., "Annual Tax Report").
    *   Select the **XML format**.
    *   Ensure the following sections are included in your query configuration. The importer relies on specific fields within these sections (see below).
4. [**Run the Flex Query**](https://www.ibkrguides.com/orgportal/performanceandstatements/runflex.htm). Select a *custom date range* that goes from *Jan 1st to Dec 31st in the relevant year*. For some reason the convenient "Last Calendar Year" option is missing from this drop down/

### Essential Flex Query Sections and Fields:

Unfortunately these is no simple way to programmatically set the configuration. However it only needs to be done once and **it should be ok to select all sections and all fields**, so try that first.

The importer uses the `ibflex` library to parse the XML, this can be quite sensitive to Interactive Brokers adding new fields, in that case you can unselect the problematic fields or patch `ibflex`. I provide a vendored fork at https://github.com/vroonhof/ibflex

 Below are the key sections and some of the critical fields expected (I recommend selecting all fields by default to avoid fiddling with the UI):

1.  **Account Information (`AccountInformation`)**:
    *   Provides account holder details.
    *   Fields used: `accountId`, `name`, `firstName`, `lastName`, `accountHolderName`.

2.  **Trades (`Trades`)**:
    *   Details all buy and sell transactions.
    *   Critical fields per trade: `tradeDate`, `settleDateTarget`, `symbol`, `description`, `assetCategory` (STK, OPT, FUT, BOND, ETF, FUND are processed), `conid` (Contract ID), `isin`, `quantity`, `tradePrice`, `tradeMoney`, `currency`, `buySell`, `ibCommission`.

3.  **Open Positions (`OpenPositions`)**:
    *   Snapshot of securities held, typically at the end of the report period.
    *   Critical fields per position: `reportDate`, `symbol`, `description`, `assetCategory`, `conid`, `isin`, `position` (quantity), `currency`.

4.  **Transfers (`Transfers`)**:
    *   Records securities transferred in or out of the account.
    *   Critical fields per transfer: `date` (or `dateTime`), `symbol`, `description`, `conid`, `isin`, `quantity`, `direction` ("IN" or "OUT"), `currency`, `type`, `account`.
    *   *Note: Cash transfers are generally ignored by this section in the importer.*

5.  **Cash Transactions (`CashTransactions`)**:
    *   Details all cash movements including dividends, interest, fees.
    *   Critical fields per transaction: `dateTime` (or `tradeDate`), `description`, `amount`, `currency`, `conid` (if linked to a security), `isin`, `symbol`, `type` (e.g., "Dividends", "Withholding Tax", "Interest", "Fees", "Deposits/Withdrawals").
    *   *Note: "Deposits/Withdrawals" are generally ignored. "Fees" and "BrokerInterestPaid" are logged but not currently used to populate specific cost/liability sections in the Steuerauszug.* "BrokerInterestReceived" is processed as income.

6.  **Cash Report (`CashReport`)**:
    *   Summarizes cash balances for each currency held.
    *   Critical fields per currency entry: `currency` (code), `endingCash` (or `balance` if `reportDate` aligns with period end).
    *   *Note: Entries for "BASE_SUMMARY" currency are ignored.*

4.  **Save and Run the Query**:
    *   Save your Flex Query configuration.
    *   Run the query for the desired period.
5.  **Download the XML File**:
    *   Once the report is generated, download the XML file. This is the file you will provide to OpenSteuerAuszug.

It is crucial that the Flex Query covers the **entire tax year** and is in **XML format**. Missing sections or fields can lead to an incomplete or inaccurate Steuerauszug.

## Configuration (`config.toml`)

Because Interactive Brokers specifies relatively complete data in its exports, this importer currently requires no specific configuration.

## Running Opensteuerauszug

```console
python -m opensteuerauszug.steuerauszug --importer ibkr <flex query xml file> ...
```

## Importer Specifics & Known Quirks

*   **Flex Query Customization**: It's crucial that your Flex Query includes all necessary data fields. Missing fields might lead to incomplete or inaccurate Steuerauszug generation. *(Provide a link to a sample recommended Flex Query configuration if possible)*
*   **Multi-Currency**: IBKR accounts often involve multiple currencies. Ensure your reports include currency information for all transactions and balances. OpenSteuerAuszug will handle currency conversions based on the Kursliste.
*   **Corporate Actions**: Complex corporate actions might require manual review or adjustments. *(Clarify how these are handled)*
*   **Fees**: Ensure all relevant fees (transaction fees, custody fees if applicable) are included in your reports.

## Troubleshooting

*   **Missing Data**: If the generated Steuerauszug seems incomplete, double-check that your IBKR reports cover the full tax year and include all necessary sections/fields.
*   **Incorrect Values**: Verify that the currency and amounts in your reports are correctly interpreted.

---
Return to [User Guide](user_guide.md)
