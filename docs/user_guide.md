# OpenSteuerAuszug User Guide

## Introduction

Welcome to OpenSteuerAuszug! This tool is designed to help you generate a Swiss tax statement (Steuerauszug) from transaction data provided by various banks and brokers, especially those that do not natively support the official eCH-0196 format. 

The primary goal is to simplify the process of preparing your tax return by automating the collection and import of relevant financial data into the tax preparation software (e.g. "PrivateTax" if you are in Zurich). i.e. to help you save effort typing and avoid copying mistakes. *You* are still responsible for making sure the correct information information lands in the tax return and that the calculated taxes are correct.

This guide will walk you through the necessary steps to use OpenSteuerAuszug effectively.

## Short Primer on Tax data and calculations

### What data are we aiming for

When you fill your tax return manually the key bits of information are

   * How much of a given security were you holding when income (or equivalent taxable events) was generated. This so income tax can be determined.
   * How much of a given security were you holding at the end (and the beginning) of year. This is so your wealth can be determined for wealth tax. Additionally this is used a a sanity check whether your wealth increase matches expectations.
   * Any income generated that cannot be computed from the other information (e.g. interests).

### How is it used and what is the 'Kursliste'

Most tax software, including PrivateTax as well as the software used by the tax office itself, can compute all the relevant tax information from here based on an official tax assessment called the [Kursliste](https://www.ictax.admin.ch/extern/en.html#/ratelist) or ICtax. In this language a security is called a "Valor" and all such securities have a "valornumber"/

Unfortunately there is no standardized way to import banking data in Swiss Tax software. Instead there the (e-)SteuerAuszug which in the modern shape is three things
   * An XML representation of the relevant transaction and valuation data encoded in fancy barcodes in a PDF (valornumber, transactions and positions)
   * A calculation of the estimated taxes based on this made by your Swiss bank.
   * a text rendering of the transaction info and these calculations for you to check and to allow for a paper based tax calculation workflow where most of the calculation is one by the bank's computer.

For a modern work flow only the first part is really necessary as the tax software can re-do all the computations, but for historic reasons and convenience we still have to do the rest. For this reason the main focus of this software is on the transaction data and *both the textual information and any income and valuation information should be taken as illustrative only*. The old "paper process" that trusts the calculations is specifically not supported.


## General Workflow

Using OpenSteuerAuszug to generate your Steuerauszug generally involves the following steps:

1.  **Preparation**:
    *   Obtain the official **Kursliste** (a list of securities and their tax values) from the Swiss Federal Tax Administration (ESTV/FTA). 
    *   Optionally, convert the Kursliste XML into an SQLite database for faster processing.
    *   Prepare your bank/broker statements in the required format.
    *   Please also keep all the normal human readable statements for validation and later referral.
    *   Configure OpenSteuerAuszug by creating and customizing a `config.toml` file with your personal details and account information.

2.  **Importing Data**:
    *   Use OpenSteuerAuszug to import your financial data from your bank or broker. Specific instructions for each supported institution are provided in separate documents (see section "Importing Data from Brokers").

3.  **Processing and Calculation**:
    *   OpenSteuerAuszug processes the imported data, reconciles positions, and calculates tax-relevant values based on your chosen method (Minimal or Kursliste-based).

4.  **Generating the PDF Steuerauszug**:
    *   The final output is a PDF document in the official eCH-0196 format, ready for use with your tax software.

5.  **Check the generated document**
    * Check that no errors or warnings were generated (e.g. about securities where information could not be found)
    * Check that all securities were included, correctly mapped to right Valor, that all all transactions are present and that end of your positions are correct.
    * Check that cash balances are correct.
    * Check that interest received is correctly represented (at a minimum check the end of year totals.)

    The generated document will have instructions for this as well.

5.  **Import into the Tax Software**

    * Your Tax software will have the ability to upload e-Steuerauszug instead of adding adding manual securities.
    * Remove any manual entries you may have used in previous years.
    * **Recalculate the tax information using the tax software**. Most tax software offers the ability to recompute tax values based on the latest Kursliste, accept that option.

## Features

### Payment Reconciliation

OpenSteuerAuszug includes a powerful **Payment Reconciliation** feature (enabled by default). 

When you run the tool with Kursliste data, it automatically compares the dividends and withholding taxes reported by your broker against the official values expected from the Kursliste for each security.

*   **Discrepancy Reporting**: It identifies cases where the broker's reported income or withholding tax differs from the Kursliste.
*   **DA-1 Confidence**: The reconciliation tables are particularly useful for building confidence that foreign withholding tax (e.g., US withholding on dividends) has actually occurred and matches the expected rates. This is essential when claiming tax credits via the **DA-1 form** in your Swiss tax return.
*   **Detailed Tables**: The generated PDF includes reconciliation tables showing these comparisons, making it easy to spot missing dividends or incorrect tax withholdings.
*   **Automatic Match Detection**: It accounts for common scenarios like accumulating funds (where no cash flow is expected) and small rounding differences.

You can explicitly control this feature using:
*   `--payment-reconciliation`: (Default) Enables the reconciliation phase and reports.
*   `--no-payment-reconciliation`: Skips the reconciliation step.

### Appending Additional Documents

Often, you may want to include additional supporting documents (e.g., the original broker statement, US 1042-S forms, or other tax forms) in the same PDF as your Steuerauszug for archiving or submission purposes.

OpenSteuerAuszug provides command-line options to prepend or append existing PDF files to the generated tax statement:

*   `--pre-amble <file.pdf>`: Adds the specified PDF **before** the main tax statement.
*   `--post-amble <file.pdf>`: Adds the specified PDF **after** the main tax statement.

You can specify these options multiple times to add multiple files. The files will be added in the order they appear on the command line.

**Note:** This feature performs a "naive concatenation." The added pages are attached exactly as they are; no page numbers, barcodes, or headers/footers are added or modified on these external documents.

Example:
```bash
python -m opensteuerauszug.steuerauszug input.xml --importer ibkr \
  --post-amble 1042-S_form.pdf \
  --post-amble broker_statement.pdf \
  -o final_tax_statement.pdf
```

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

You need to obtain the official Kursliste XML file for the relevant tax year. This is usually available for download from the [ESTV website](https://www.ictax.admin.ch/extern/en.html#/xml). Always down the latest file marked "Initial" in the latest format, V2.0 at this time). 

After unzipping, the file is typically named something like `kursliste_JJJJ.xml` (e.g., `kursliste_2023.xml`).

### Storing the Kursliste

Place the downloaded Kursliste XML file(s) into the `data/kursliste/` directory within your OpenSteuerAuszug project. The application will automatically detect files in this location.

For more detailed information on naming conventions and how OpenSteuerAuszug manages these files, please refer to the [Kursliste Data Management Guide](data/kursliste/kursliste.md).

### Converting Kursliste XML to SQLite (Recommended)

For significantly improved performance, especially with large Kursliste files or frequent use, it is **highly recommended** to convert the Kursliste XML file into an SQLite database. OpenSteuerAuszug includes a script for this purpose.

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
2.  **Configuration File (`config.toml`)**: This file tells OpenSteuerAuszug your personal details (name, canton for tax purposes), information about your financial institutions, and specific settings for each account. You can copy `config.template.toml` to `config.toml`. The file is optional.
3.  **Kursliste**: As described in the "Preparing the Kursliste" section, ensure you have the relevant Kursliste (preferably as an SQLite file in `data/kursliste/`) for the tax year you are processing.

### Configuring OpenSteuerAuszug (`config.toml`)

The `config.toml` file is optional. It allows tailoring OpenSteuerAuszug to your needs, for example if you want to correct or extend broker exported data. To set it up:

1. Copy the template: `cp config.template.toml config.toml`
2. Edit the file with your personal information

The configuration uses a hierarchical structure:

*   `[general]` settings apply globally (e.g., your name, canton).
*   `[brokers.<BrokerName>]` settings apply to a specific financial institution.
*   `[brokers.<BrokerName>.accounts.<AccountName>]` settings apply to a specific account, including the **mandatory `account_number`**.

For detailed instructions on how to structure your `config.toml` file, what settings are available, and examples, please refer to the [Configuration Guide](config.md).

**Note:** The `config.toml` file is ignored by git to protect your personal data. If it's not present, the application will still run but may require configuration settings via command-line arguments.

### Importing Data from Brokers

OpenSteuerAuszug uses specific importers for each supported bank or broker. These importers know how to read the particular statement formats provided by the institution.

Currently supported brokers and their specific guides:

*   **[Charles Schwab](importer_schwab.md)**: For brokerage and equity award accounts.
*   **[Interactive Brokers (IBKR)](importer_ibkr.md)**: For brokerage accounts.

Please refer to the documentation for your specific broker by clicking the links above to understand what files to download, their formats, and any specific configurations required in `config.toml`.

The full workflow happens on your computer using data you manually download which avoids authorization issues.

### Calculation Options

As stated above, the modern tax return flow does not need any of the textual content and any calculable tax information can and should be be recomputed in the main tax return software.

OpenSteuerAuszug offers different ways to what to do the to calculate the tax values of your securities in the generated files.:

1.  **Minimal Calculation**:
    *   **What it does**: This option focuses on accurately reporting the securities you held, their quantities. It sometimes does minimal computations to make the XML valid. However, it generally does **not** fill in the official tax values from the Kursliste for each security. Instead, it only provides the necessary identification (ISIN, Valor number) for your tax software to look up these values itself. Some basic valuations might be done (e.g., for cash interest).
    *   **Advantages**:
        *   Relies on your official tax software (e.g., Private Tax, Dr. Tax, eTax) to perform the definitive tax value lookups using the Kursliste data they have integrated. This software will have been formally audited.
        *   The generated PDF and tax values are clearly wrong so there potentially less confusion about the informational calculations done by this software.

2.  **Kursliste-Based Calculation**:
    *   **What it does**: This option actively uses the provided Kursliste (XML or SQLite) to look up each security and populate its official end-of-year tax value, as well as any taxable income components (e.g., portion of dividend subject to tax).
    *   **Advantages**:
        *   Provides a more complete Steuerauszug where tax values are pre-filled. This can be useful for cross-verification or if your tax software has issues importing detailed positions.
        *   The generated PDF is closer to what a Swiss bank would provide.
        *   Can help identify discrepancies if your own understanding of a security's value differs from the official Kursliste.
    * Missing securities (or perhaps incorrect values) can be added easily to the kursliste by contacting the ESTV (e.g. by e-mail). Recompute the Steuerauszug with the newly published Kursliste.
    * The Kursliste gets refreshed frequently (even long after the March 31st deadline), always use the latest version.

The choice between these options might depend on your tax software, your confidence in the Kursliste data you provide to OpenSteuerAuszug, and your personal preference for detail in the generated document. You typically configure the desired calculation strategy within your `config.toml` or via command-line options when running the tool.

Remember the calculations in this software are not formally audited.
*You* are responsible for the final values in the tax software in any setting.

#### Advanced Options

Neither of the the following options is currently complete and should not be used.

* In the future a mode will be provided to sanity check the kursliste calculations against reported income and tax withholding with the bank, however this currently must be done manually.

*   **"Fill-in" Calculation**:
    *   This is an advanced calculation method. It attempts to derive tax values for securities that might not be directly found in the Kursliste by computing it purely on broker provided data. However this involves lots of assumptions and judgement about swiss tax rules that cannot be automated and needs substantial auditing. I left it in the code mostly for tax nerds.
    * The correct way to handle missing information in the Kursliste is to ask it to be added. This can be done with a simple e-mail to ESTV. (or even by API but this software does not implement it yet.)
 

### Running the software

One all the data is setup the Steuerauszug can be generated with

```console
python -m opensteuerauszug.steuerauszug {broker data location} --importer {schwab|ibkr} --tax-year {tax year} -o {output filename.pdf} 
```

for minimal mode

```console
python -m opensteuerauszug.steuerauszug {broker data location} --importer {schwab|ibkr} --tax-calculation-level minimal --tax-year {tax year} -o {output filename.pdf} 
```

If doing active development it is best to place any real tax data including the generated output outside of the source tree or in the `/private` directory. 

---


## Verifying an Existing Steuerauszug

See [docs/verify_existing.md](verify_existing.md) for instructions on verifying or recalculating an existing Steuerauszug (eCH-0196 XML) with OpenSteuerAuszug.

---
---

## Limitations

While OpenSteuerAuszug aims to be comprehensive, there are certain limitations to be aware of:

*   **Complex Financial Instruments**: At the moment the software supports simple equities (Shares and Funds) and cash holdings. Derivatives, fees, liabilities, bonds, currencies for investment and other complex investments including those 'Differenzbesteuerung' are not supported.
*   **Swiss Brokers or non-standard withholding**: Currently for import it targets the use cases the author has. US brokers, W8-BEN in place.
*   **Corporate Actions**: While common corporate actions (e.g., stock splits, simple dividends) are generally handled, very complex or unusual ones (e.g., mergers with mixed cash/stock offers, spin-offs with non-standard terms) might not be interpreted correctly automatically and could require manual adjustments in your tax software.
*   **Broker Data Quality**: The accuracy of the generated Steuerauszug heavily depends on the quality and completeness of the data provided by your bank/broker. If their export files are missing information or contain errors, OpenSteuerAuszug may not be able to compensate.
*   **Kursliste Gaps**: If a security is not listed in the official Kursliste, OpenSteuerAuszug may not be able to assign an official tax value (unless using the "fill-in" method, which has its own caveats).
*   **Specific Tax Scenarios**: This tool is designed for common tax scenarios for individuals in Switzerland. Highly specialized tax situations may not be covered.
*   **Not a Tax Advisor**: OpenSteuerAuszug is a software tool, not a tax advisor. It does not provide tax advice.

Always review the generated documents carefully and consult with a qualified tax professional if you have complex financial affairs or are unsure about any aspect of your tax return.


### Limitations of the E-Steuerauszug format

The  E-Steuerauszug format was designed with swiss
financial institutes in mind and assume authority,
this does not always fit what we are trying to do.

For more detail see [Technical notes](technical_notes.md).

---

## Verification and User Liability

As stated in the [Disclaimer](#disclaimer-and-user-responsibility), it is crucial to understand your role:

*   **Verify Thoroughly**: Before submitting anything to the tax authorities, meticulously check all figures, positions, income, and totals on the Steuerauszug generated by this tool. Compare it against your own records and understanding.
*   **Cross-Reference**: If possible, compare the output with any summaries or tax reports your broker might provide, even if they are not in the official Swiss format.
*   **Ultimate Responsibility**: **You, the taxpayer, are solely and ultimately responsible for the accuracy and completeness of your tax return.** OpenSteuerAuszug is a tool to assist you in preparing the Steuerauszug, but it does not absolve you of your legal obligations. Any errors or omissions in your tax filing are your responsibility.

Use this tool as an aid to simplify data aggregation and formatting, not as a substitute for careful review and due diligence.

---

## Open Questions

### Testing and real world usage status

As of the writing this software 
* produces valid XML for the authors recent tax years,
* agrees with e-Steuerauszug from the authors' Bank.
* the output has been imported once in a test session with ZH PrivateTax

but because the author wisely decided to finish their tax return before embarking on this madness it has not yet been used in a real tax return. In particular it is unknown how the tax authorities will react.

### Next Steps / Open Issues

* Recruit more testers fro real world data use.
* Implement plausibility checks, in particular for tax withholding.
* produce more automated test scenarios.
* See if this can be deployed as a standalone web pages with WASM.
* Cleanup helper scripts and provide clean pipx executable package



### Specific issues

*(This section is a placeholder for planned features, improvements, or known issues that are being tracked.)*


TODO: List common issues and refer to github


## Notes / Insights

* The [ECH-0196](https://www.ech.ch/de/ech/ech-0196/2.2.0) standard refers to a bundle of sample software that disappeared form the internet. The author has not been able to locate a copy to cross validate.
* Similarly there is a contact email address (eSteuerauszug.support@ssk.ewv-ete.ch) to notify of new "banks" using the e-Steuerauszug and for clarifying questions. The author has not been able to get a response.