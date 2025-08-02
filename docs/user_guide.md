# OpenSteuerAuszug User Guide

## Introduction

Welcome to OpenSteuerAuszug! This tool is designed to help you generate a Swiss tax statement (Steuerauszug) from transaction data provided by various banks and brokers, especially those that do not natively support the official eCH-0196 format. The primary goal is to simplify the process of preparing your tax return by automating the collection and formatting of relevant financial data.

This guide will walk you through the necessary steps to use OpenSteuerAuszug effectively.

## General Workflow

Using OpenSteuerAuszug to generate your Steuerauszug generally involves the following steps:

1.  **Preparation**:
    *   Obtain the official **Kursliste** (a list of securities and their tax values) from the Swiss Federal Tax Administration (ESTV/FTA).
    *   Optionally, convert the Kursliste XML into an SQLite database for faster processing.
    *   Prepare your bank/broker statements in the required format.
    *   Configure OpenSteuerAuszug by creating and customizing a `config.toml` file with your personal details and account information.

2.  **Importing Data**:
    *   Use OpenSteuerAuszug to import your financial data from your bank or broker. Specific instructions for each supported institution are provided in separate documents (see section "Importing Data from Brokers").

3.  **Processing and Calculation**:
    *   OpenSteuerAuszug processes the imported data, reconciles positions, and calculates tax-relevant values based on your chosen method (Minimal or Kursliste-based).

4.  **Generating the PDF Steuerauszug**:
    *   The final output is a PDF document in the official eCH-0196 format, ready for use with your tax software or for submission with your tax return. It also includes a 2D barcode for easy import by tax authorities/software.

## Disclaimer and User Responsibility

**Important**: OpenSteuerAuszug is provided "as is" without any formal audit or warranty. While it aims to be accurate, it is your responsibility as the taxpayer to:

*   **Verify all data**: Carefully review the generated Steuerauszug for completeness and accuracy before submitting it with your tax return.
*   **Ensure correctness**: The main focus of this tool is to correctly process core transaction and interest data. Tax value calculations are provided on a best-effort basis for informational purposes. Your primary tax software should be capable of performing its own calculations based on the raw data provided in the Steuerauszug.
*   **Understand limitations**: Be aware of the tool's limitations (see section "Limitations").

**You, the user, are ultimately liable for the contents of your tax return.** This tool is an aid, not a replacement for due diligence.

---

## Preparing the Kursliste

The **Kursliste** is an official list published annually by the Swiss Federal Tax Administration (Eidgenössische Steuerverwaltung, ESTV). It contains securities (stocks, bonds, funds, etc.) and their corresponding tax values, exchange rates, and other relevant information needed for your Swiss tax return. OpenSteuerAuszug uses this data to determine the correct tax values for the securities in your portfolio.

### Obtaining the Kursliste

You need to obtain the official Kursliste XML file for the relevant tax year. This is usually available for download from the ESTV website. Search for "Kursliste ESTV" or "listes des cours ICTA" to find the download page for the desired year.

The file is typically named something like `kursliste_JJJJ.xml` (e.g., `kursliste_2023.xml`).

### Storing the Kursliste

Place the downloaded Kursliste XML file(s) into the `data/kursliste/` directory within your OpenSteuerAuszug project. The application will automatically detect files in this location.

For more detailed information on naming conventions and how OpenSteuerAuszug manages these files, please refer to the [Kursliste Data Management Guide](data/kursliste/kursliste.md).

### Converting Kursliste XML to SQLite (Recommended)

For significantly improved performance, especially with large Kursliste files or frequent use, it is **highly recommended** to convert the Kursliste XML file into an SQLite database. OpenSteuerAuszug includes a script for this purpose.

**Why convert?**
*   **Speed**: Reading from and querying an SQLite database is much faster than parsing large XML files repeatedly.
*   **Efficiency**: The `KurslisteManager` will automatically prioritize SQLite files if both XML and SQLite versions for the same year are present.

**How to convert:**
1.  Navigate to the root directory of the OpenSteuerAuszug project in your terminal.
2.  Run the conversion script:
    ```bash
    python scripts/convert_kursliste_to_sqlite.py path/to/your/downloaded/kursliste_YYYY.xml data/kursliste/kursliste_YYYY.sqlite
    ```
    Replace `path/to/your/downloaded/kursliste_YYYY.xml` with the actual path to the XML file you downloaded from ESTV, and `kursliste_YYYY.sqlite` with the desired output name (keeping the year consistent).

    **Example:**
    ```bash
    python scripts/convert_kursliste_to_sqlite.py ~/Downloads/kursliste_2023.xml data/kursliste/kursliste_2023.sqlite
    ```
3.  Ensure the generated `.sqlite` file is in the `data/kursliste/` directory.

The application will then use this SQLite database for faster access to Kursliste data. For more technical details on the conversion process and database structure, see the [Kursliste Data Management Guide](data/kursliste/kursliste.md).

---

## Generating a Steuerauszug

This is the primary use case for OpenSteuerAuszug: generating a PDF Steuerauszug from your bank/broker data.

### Necessary Inputs

To generate a Steuerauszug, you will need to provide the following:

1.  **Broker Statements**: These are the reports or data files you download from your bank or financial institution. The required format varies by broker. See the specific importer documentation (linked under "Importing Data from Brokers" below) for details on what files are needed and how to obtain them.
2.  **Configuration File (`config.toml`)**: This file tells OpenSteuerAuszug your personal details (name, canton for tax purposes), information about your financial institutions, and specific settings for each account. You must create this file in the root directory of the OpenSteuerAuszug project.
3.  **Kursliste**: As described in the "Preparing the Kursliste" section, ensure you have the relevant Kursliste (preferably as an SQLite file in `data/kursliste/`) for the tax year you are processing.

### Configuring OpenSteuerAuszug (`config.toml`)

The `config.toml` file is crucial for tailoring OpenSteuerAuszug to your needs. It uses a hierarchical structure:

*   `[general]` settings apply globally (e.g., your name, canton).
*   `[brokers.<BrokerName>]` settings apply to a specific financial institution.
*   `[brokers.<BrokerName>.accounts.<AccountName>]` settings apply to a specific account, including the **mandatory `account_number`**.

For detailed instructions on how to structure your `config.toml` file, what settings are available, and examples, please refer to the [Configuration Guide](config.md).

### Importing Data from Brokers

OpenSteuerAuszug uses specific importers for each supported bank or broker. These importers know how to read the particular statement formats provided by the institution.

Currently supported brokers and their specific guides:

*   **[Charles Schwab](importer_schwab.md)**: For brokerage and equity award accounts.
*   **[Interactive Brokers (IBKR)](importer_ibkr.md)**: For brokerage accounts.

Please refer to the documentation for your specific broker by clicking the links above to understand what files to download, their formats, and any specific configurations required in `config.toml`.

### Calculation Options

OpenSteuerAuszug offers different ways to calculate the tax values of your securities:

1.  **Minimal Calculation**:
    *   **What it does**: This option focuses on accurately reporting the securities you held, their quantities, and any income (dividends, interest). However, it generally does **not** fill in the official tax values from the Kursliste for each security. Instead, it provides the necessary identification (ISIN, Valor number) for your tax software to look up these values itself. Some basic valuations might be done (e.g., for cash).
    *   **Advantages**:
        *   Simpler and faster if your primary goal is just to get the transactions and holdings into your tax software.
        *   Relies on your official tax software (e.g., Private Tax, Dr. Tax, eTax) to perform the definitive tax value lookups using the Kursliste data they have integrated. This can be seen as more robust if you trust the tax software's data more.
        *   Less dependent on having a perfect and complete Kursliste available within OpenSteuerAuszug itself for every single security.

2.  **Kursliste-Based Calculation**:
    *   **What it does**: This option actively uses the provided Kursliste (XML or SQLite) to look up each security and populate its official end-of-year tax value, as well as any taxable income components (e.g., portion of dividend subject to tax).
    *   **Advantages**:
        *   Provides a more complete Steuerauszug where tax values are pre-filled. This can be useful for cross-verification or if your tax software has issues importing detailed positions.
        *   The generated PDF is closer to what a Swiss bank would provide.
        *   Can help identify discrepancies if your own understanding of a security's value differs from the official Kursliste.

The choice between these options might depend on your tax software, your confidence in the Kursliste data you provide to OpenSteuerAuszug, and your personal preference for detail in the generated document. You typically configure the desired calculation strategy within your `config.toml` or via command-line options when running the tool.

### Advanced Options

*   **"Fill-in" Calculation**:
    *   This is an advanced calculation method. It attempts to derive tax values for securities that might not be directly found in the Kursliste, potentially by using other provided data or estimation techniques.
    *   **Use Case**: This might be useful for less common securities or if there are gaps in the Kursliste. However, values derived this way should be treated with extra caution and verified carefully.
    *   It's generally recommended to rely on the "Minimal" or "Kursliste-Based" calculations unless you have a specific reason and understand the implications of this method.

---

## Verifying an Existing Steuerauszug

Besides generating new Steuerauszüge, OpenSteuerAuszug can also be used to verify or re-calculate an existing Steuerauszug that is already in the eCH-0196 XML format (e.g., one provided by a Swiss bank).

This can be useful for:

*   **Cross-checking**: Comparing the values calculated by OpenSteuerAuszug against those in an official document.
*   **Understanding calculations**: Seeing how OpenSteuerAuszug interprets the data from an existing XML.
*   **Testing**: This feature is also used internally to test the accuracy and compliance of OpenSteuerAuszug's calculation and rendering engine.

### Workflow

1.  **Input**: You will need the existing Steuerauszug in its **XML format** (eCH-0196). PDF versions cannot be directly processed for verification. Many tax software or e-banking portals allow exporting the Steuerauszug data as XML.
2.  **Kursliste**: Have the relevant Kursliste (XML or SQLite in `data/kursliste/`) for the tax year of the Steuerauszug you are verifying. This allows OpenSteuerAuszug to perform its own lookup of tax values.
3.  **Configuration**: Your `config.toml` should be set up, although fewer parameters might be strictly necessary compared to generating a new statement from raw broker data. The tool might extract some metadata from the XML itself.
4.  **Execution**: Run OpenSteuerAuszug with a command or option that specifies you want to verify an existing XML file.
    *(Specific command-line usage or API calls for this mode should be detailed here once known. For example: `python -m opensteuerauszug --verify-xml path/to/your/existing_steuerauszug.xml ...`)*
5.  **Output**:
    *   The tool will typically parse the input XML, recalculate values based on its own logic and the provided Kursliste.
    *   It may then output a comparison, a new PDF generated from the input XML's data (allowing visual comparison), or log any discrepancies found.
    *   *(The exact output format and comparison method should be documented based on the tool's capabilities.)*

### Key Aspects of Verification

*   **Data Source**: The primary source of data is the content of the input XML file.
*   **Recalculation**: Tax values, totals, and summaries are recalculated.
*   **Comparison**: Differences in calculated values versus the values present in the input XML are the main focus.

This feature helps increase confidence in both your existing documents and in OpenSteuerAuszug's processing capabilities.

---

## Limitations

While OpenSteuerAuszug aims to be comprehensive, there are certain limitations to be aware of:

*   **Complex Financial Instruments**: Highly complex derivatives, structured products, or certain types of bonds might not be fully supported or may require manual data supplementation.
*   **Corporate Actions**: While common corporate actions (e.g., stock splits, simple dividends) are generally handled, very complex or unusual ones (e.g., mergers with mixed cash/stock offers, spin-offs with non-standard terms) might not be interpreted correctly automatically and could require manual adjustments in your tax software.
*   **Broker Data Quality**: The accuracy of the generated Steuerauszug heavily depends on the quality and completeness of the data provided by your bank/broker. If their export files are missing information or contain errors, OpenSteuerAuszug may not be able to compensate.
*   **Kursliste Gaps**: If a security is not listed in the official Kursliste, OpenSteuerAuszug may not be able to assign an official tax value (unless using the "fill-in" method, which has its own caveats).
*   **Specific Tax Scenarios**: This tool is designed for common tax scenarios for individuals in Switzerland. Highly specialized tax situations may not be covered.
*   **Not a Tax Advisor**: OpenSteuerAuszug is a software tool, not a tax advisor. It does not provide tax advice.

Always review the generated documents carefully and consult with a qualified tax professional if you have complex financial affairs or are unsure about any aspect of your tax return.

---

## Verification and User Liability

As stated in the [Disclaimer](#disclaimer-and-user-responsibility), it is crucial to understand your role:

*   **Verify Thoroughly**: Before submitting anything to the tax authorities, meticulously check all figures, positions, income, and totals on the Steuerauszug generated by this tool. Compare it against your own records and understanding.
*   **Cross-Reference**: If possible, compare the output with any summaries or tax reports your broker might provide, even if they are not in the official Swiss format.
*   **Ultimate Responsibility**: **You, the taxpayer, are solely and ultimately responsible for the accuracy and completeness of your tax return.** OpenSteuerAuszug is a tool to assist you in preparing the Steuerauszug, but it does not absolve you of your legal obligations. Any errors or omissions in your tax filing are your responsibility.

Use this tool as an aid to simplify data aggregation and formatting, not as a substitute for careful review and due diligence.

---

## Open Questions

*(This section is a placeholder for questions identified during development or by users that need clarification or further investigation.)*

*   How are specific types of fees (e.g., custody vs. transaction) best represented if not explicitly detailed in broker reports?
*   What is the best practice for handling securities denominated in currencies with no direct end-of-year rate in the Kursliste?

---

## Next Steps / Open Issues

*(This section is a placeholder for planned features, improvements, or known issues that are being tracked.)*

*   Issue #XX: Improve handling of specific corporate action type Y.
*   Feature #YY: Add support for Broker Z.
*   Enhancement #ZZ: Provide more detailed comparison output in verification mode.

---

## Notes / Insights

*(This section is a placeholder for any interesting observations, learnings, or insights gained during the development or use of OpenSteuerAuszug that might be useful for users or future developers.)*

*   Insight: The XML schema for eCH-0196 has specific constraints on field lengths (e.g., security names) that require careful handling of data from brokers.
*   Note: The naming convention for Kursliste files in `data/kursliste/` is important for automatic detection.
