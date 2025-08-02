# Interactive Brokers (IBKR) Importer Guide

This guide explains how to prepare your data from Interactive Brokers (IBKR) for use with OpenSteuerAuszug.

## Required Input: Flex Query XML File

OpenSteuerAuszug processes IBKR data using **Flex Query XML files**. You need to configure a Flex Query in your IBKR Account Management that includes specific sections and fields covering the entire tax year.

### How to Obtain the Flex Query XML:

1.  **Log in** to your IBKR Account Management portal.
2.  Navigate to **"Performance & Reports" > "Flex Queries"**.
3.  **Create a new Flex Query** or modify an existing one.
    *   Give your query a descriptive name (e.g., "Annual Tax Report").
    *   Select the **XML format**.
    *   Choose the **period** (e.g., "Last Calendar Year" or a custom date range covering your full tax year).
    *   Ensure the following sections are included in your query configuration. The importer relies on specific fields within these sections:

### Essential Flex Query Sections and Fields:

The importer uses the `ibflex` library to parse the XML. Below are the key sections and some of the critical fields expected:

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

In your `config.toml` file, you'll need to set up a section for your IBKR account(s). This tells OpenSteuerAuszug which account ID from the Flex Query XML corresponds to your settings.

```toml
# Example for an IBKR account
[brokers.ibkr] # Or any other alias you prefer for IBKR
  # Broker-level settings if any (e.g., specific processing flags)

  [brokers.ibkr.accounts.main_account] # Your alias for this IBKR account
  account_number = "U1234567" # Your actual IBKR account number
  # Account-specific settings if any
```

Ensure the `account_number` in your `config.toml` matches the account number in your IBKR statements.

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
