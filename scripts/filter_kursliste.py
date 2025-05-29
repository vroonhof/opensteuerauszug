import argparse
import logging
import sys
import lxml.etree as ET # Added lxml.etree import
from pydantic import ValidationError # Added ValidationError import

from opensteuerauszug.model.kursliste import (
    Kursliste, Share, Fund, Bond,
    ExchangeRate, ExchangeRateMonthly, ExchangeRateYearEnd,
    PaymentShare, PaymentFund, PaymentBond, Daily, Yearend,
    DefinitionCurrency, Country, Institution,
    Canton, Sector, ShortCut, Sign, Da1Rate, MediumTermBond
)
from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Security as Ech0196Security,
    BankAccount as Ech0196BankAccount,
    LiabilityAccount as Ech0196LiabilityAccount,
    Expense as Ech0196Expense
)
# Removed standalone to_xml import and its self-check.
# We will use the instance method output_kursliste_obj.to_xml()


# New function to parse tax statements
def parse_tax_statements(file_paths: list[str]) -> tuple[set[int], set[str]]:
    collected_valor_numbers = set()
    collected_currencies = set()

    logging.info(f"Starting to parse {len(file_paths)} tax statement file(s).")

    for file_path in file_paths:
        logging.info(f"Parsing tax statement file: {file_path}")
        try:
            tax_statement_data = TaxStatement.from_xml_file(file_path)
            logging.debug(f"Successfully loaded tax statement: {file_path}")

            # Extract Valor Numbers
            if tax_statement_data.listOfSecurities and tax_statement_data.listOfSecurities.depot:
                for depot in tax_statement_data.listOfSecurities.depot:
                    if depot.security: # depot.security is Optional[list[Security]]
                        for sec in depot.security: # sec is Ech0196Security
                            if sec.valorNumber is not None:
                                collected_valor_numbers.add(sec.valorNumber)
                                logging.debug(f"Collected valor number {sec.valorNumber} from {file_path}")

            # Extract Currencies
            # From BankAccounts
            if tax_statement_data.listOfBankAccounts and tax_statement_data.listOfBankAccounts.bankAccount:
                for acc in tax_statement_data.listOfBankAccounts.bankAccount: # acc is Ech0196BankAccount
                    if acc.bankAccountCurrency: collected_currencies.add(acc.bankAccountCurrency)
                    if acc.taxValue and acc.taxValue.balanceCurrency: collected_currencies.add(acc.taxValue.balanceCurrency)
                    if acc.payment: # acc.payment is Optional[list[PaymentType]]
                        for payment in acc.payment:
                            if payment.amountCurrency: collected_currencies.add(payment.amountCurrency)
            
            # From LiabilityAccounts
            if tax_statement_data.listOfLiabilities and tax_statement_data.listOfLiabilities.liabilityAccount:
                for lia in tax_statement_data.listOfLiabilities.liabilityAccount: # lia is Ech0196LiabilityAccount
                    if lia.bankAccountCurrency: collected_currencies.add(lia.bankAccountCurrency)
                    if lia.taxValue and lia.taxValue.balanceCurrency: collected_currencies.add(lia.taxValue.balanceCurrency)
                    if lia.payment: # lia.payment is Optional[list[PaymentType]]
                        for payment in lia.payment:
                            if payment.amountCurrency: collected_currencies.add(payment.amountCurrency)

            # From Expenses
            if tax_statement_data.listOfExpenses and tax_statement_data.listOfExpenses.expense:
                for exp in tax_statement_data.listOfExpenses.expense: # exp is Ech0196Expense
                    if exp.amountCurrency: collected_currencies.add(exp.amountCurrency)

            # From Securities (again, for currencies)
            if tax_statement_data.listOfSecurities and tax_statement_data.listOfSecurities.depot:
                for depot in tax_statement_data.listOfSecurities.depot:
                    if depot.security:
                        for sec in depot.security: # sec is Ech0196Security
                            if sec.currency: collected_currencies.add(sec.currency)
                            if sec.taxValue and sec.taxValue.balanceCurrency: collected_currencies.add(sec.taxValue.balanceCurrency)
                            if sec.payment: # sec.payment is Optional[list[PaymentType]]
                                for payment in sec.payment:
                                    if payment.amountCurrency: collected_currencies.add(payment.amountCurrency)
                            if sec.stock: # sec.stock is Optional[list[StockMovementType]]
                                for stock_item in sec.stock:
                                    if stock_item.balanceCurrency: collected_currencies.add(stock_item.balanceCurrency)
            
            logging.info(f"Successfully parsed and extracted data from: {file_path}")

        except FileNotFoundError:
            logging.error(f"Tax statement file not found: {file_path}. Skipping.")
        except Exception as e: # Catching generic Exception for other parsing errors from from_xml_file
            logging.error(f"Error parsing tax statement file {file_path}: {e}. Skipping.", exc_info=True)
        
    logging.info(f"Finished parsing all tax statement files. Found {len(collected_valor_numbers)} unique valor numbers and {len(collected_currencies)} unique currencies.")
    return collected_valor_numbers, collected_currencies


def main():
    parser = argparse.ArgumentParser(description="Filters a Kursliste XML file.")
    parser.add_argument("--input-file", required=True, help="Path to the large Kursliste XML file.")
    parser.add_argument("--output-file", required=True, help="Path for the filtered Kursliste XML output.")
    parser.add_argument("--valor-numbers", required=False, help="A comma-separated string of valor numbers to keep (e.g., \"12345,67890\").") # Changed to not required
    parser.add_argument("--tax-statement-files", nargs='+', help="Paths to one or more eCH-0196 Tax Statement XML files.", default=[]) # Added new argument
    parser.add_argument("--include-bonds", action='store_true', help="If specified, also include bonds with matching valor numbers.")
    parser.add_argument("--target-currency", default="CHF", help="The main currency for which exchange rates should be prioritized.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level.")

    args = parser.parse_args()

    # Set up logging
    numeric_level = getattr(logging, args.log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {args.log_level}")
    logging.basicConfig(level=numeric_level)

    logging.info("Parsed arguments:")
    logging.info(f"  Input file: {args.input_file}")
    logging.info(f"  Output file: {args.output_file}")
    logging.info(f"  Valor numbers: {args.valor_numbers if args.valor_numbers else 'Not provided'}")
    if args.tax_statement_files:
        logging.info(f"  Tax statement files: {args.tax_statement_files}")
    else:
        logging.info("  Tax statement files: Not provided")
    logging.info(f"  Include bonds: {args.include_bonds}")
    logging.info(f"  Target currency: {args.target_currency}")
    logging.info(f"  Log level: {args.log_level}")

    # Ensure that either valor_numbers or tax_statement_files is provided
    if not args.valor_numbers and not args.tax_statement_files:
        logging.error("Error: Either --valor-numbers or --tax-statement-files must be provided.")
        return 1 # Exit with an error code
    
    # Parse Tax Statements if provided
    tax_statement_valors = set()
    tax_statement_currencies = set()
    if args.tax_statement_files:
        logging.info("Processing tax statement files...")
        tax_statement_valors, tax_statement_currencies = parse_tax_statements(args.tax_statement_files)
        logging.info(f"Valors from tax statements: {tax_statement_valors if tax_statement_valors else 'None'}")
        logging.info(f"Currencies from tax statements: {tax_statement_currencies if tax_statement_currencies else 'None'}")
    else:
        logging.info("No tax statement files provided to parse.")

    try:
        # 1. Parse Valor Numbers from Command Line
        cmd_line_valor_numbers = set()
        if args.valor_numbers:
            logging.info(f"Parsing command-line valor numbers: {args.valor_numbers}")
            raw_cmd_valors = args.valor_numbers.split(',')
            valor_errors_cmd = False
            for v_str in raw_cmd_valors:
                try:
                    cmd_line_valor_numbers.add(int(v_str.strip()))
                except ValueError:
                    logging.error(f"Invalid valor number format from command line: '{v_str}'. Must be an integer.")
                    valor_errors_cmd = True
            if valor_errors_cmd:
                logging.error("Errors encountered while parsing command-line valor numbers. Exiting.")
                return 1
            logging.info(f"Successfully parsed command-line valor numbers: {cmd_line_valor_numbers}")
        else:
            logging.info("No command-line valor numbers provided.")

        # 2. Parse Valor Numbers and Currencies from Tax Statements
        # tax_statement_valors and tax_statement_currencies are already initialized and populated if files are given.
        # This part of the code (calling parse_tax_statements) is already above the try-except block.
        # So, tax_statement_valors and tax_statement_currencies are available here.
        
        # 3. Consolidate Valor Numbers
        valor_numbers_to_keep = cmd_line_valor_numbers.union(tax_statement_valors)
        logging.info(f"Consolidated valor numbers for filtering (from command line and tax statements): {valor_numbers_to_keep if valor_numbers_to_keep else 'None'}")

        # 4. Consolidate Initial Relevant Currencies
        relevant_currencies = set()
        if args.target_currency:
            relevant_currencies.add(args.target_currency)
            logging.debug(f"Added target_currency '{args.target_currency}' to initial relevant_currencies.")
        
        relevant_currencies.update(tax_statement_currencies)
        logging.info(f"Initial set of relevant currencies (target_currency + tax statement currencies): {relevant_currencies if relevant_currencies else 'None'}")
        
        # Proceed with Kursliste XML loading and processing only if there are valor numbers to filter by
        if not valor_numbers_to_keep:
            logging.warning("No valor numbers to filter by (neither from command line nor tax statements). Output will be empty of securities.")
            # Depending on desired behavior, could exit or produce an empty Kursliste structure.
            # Current script structure will produce an empty Kursliste for securities/rates if this set is empty.

        # Load and Parse Kursliste XML
        logging.info(f"Loading Kursliste XML from {args.input_file}...")
        try:
            # Use Kursliste.from_xml_file to parse the input XML file
            # Pass denylist=None to ensure all elements are loaded from the source Kursliste.
            kursliste_data = Kursliste.from_xml_file(args.input_file, denylist=None)
            logging.info(f"Successfully parsed Kursliste XML from {args.input_file}")
            logging.info(f"Kursliste date: {kursliste_data.creationDate}, Year: {kursliste_data.year}")
        except ET.XMLSyntaxError as e:
            logging.error(f"XML Syntax Error parsing Kursliste file {args.input_file}: {e}")
            return 1 # Exit with error
        except ValidationError as e:
            logging.error(f"Pydantic validation error parsing Kursliste {args.input_file}: {e}")
            return 1 # Exit with error
        except FileNotFoundError: # Already caught by the outer try-except, but good to be specific if desired
            logging.error(f"Error: Kursliste input file not found at {args.input_file}")
            return 1
        except Exception as e: # Catch other potential errors from from_xml_file
            logging.error(f"An unexpected error occurred while parsing Kursliste {args.input_file}: {e}", exc_info=True)
            return 1


        # Initialize filtered lists (using the consolidated valor_numbers_to_keep)
        filtered_shares = []
        filtered_funds = []
        filtered_bonds = []

        # 3. Filter Shares
        if kursliste_data.shares:
            logging.info(f"Processing {len(kursliste_data.shares)} shares from input...")
            for share in kursliste_data.shares:
                if share.valorNumber and share.valorNumber in valor_numbers_to_keep: # Use consolidated set
                    filtered_shares.append(share)
                    logging.info(f"Kept Share - Valor: {share.valorNumber}, Name: {share.securityName}")
        else:
            logging.info("No shares found in the input Kursliste.")

        # 4. Filter Funds
        if kursliste_data.funds:
            logging.info(f"Processing {len(kursliste_data.funds)} funds from input...")
            for fund in kursliste_data.funds:
                if fund.valorNumber and fund.valorNumber in valor_numbers_to_keep: # Use consolidated set
                    filtered_funds.append(fund)
                    logging.info(f"Kept Fund - Valor: {fund.valorNumber}, Name: {fund.securityName}")
        else:
            logging.info("No funds found in the input Kursliste.")

        # 5. Filter Bonds (Conditional)
        if args.include_bonds:
            if kursliste_data.bonds:
                logging.info(f"Processing {len(kursliste_data.bonds)} bonds from input (include_bonds is True)...")
                for bond in kursliste_data.bonds:
                    if bond.valorNumber and bond.valorNumber in valor_numbers_to_keep: # Use consolidated set
                        filtered_bonds.append(bond)
                        logging.info(f"Kept Bond - Valor: {bond.valorNumber}, Name: {bond.securityName}")
            else:
                logging.info("No bonds found in the input Kursliste (include_bonds is True).")
        else:
            logging.info("Skipping bond filtering as --include-bonds is False.")
            
        # 6. Log Summary of Security Filtering
        logging.info(f"Security Filtering Summary: Kept {len(filtered_shares)} shares, {len(filtered_funds)} funds, {len(filtered_bonds)} bonds.")

        # 7. Identify Relevant Currencies (Continued)
        # The 'relevant_currencies' set was initialized before Kursliste parsing using target_currency and tax_statement_currencies.
        # Now, it will be expanded with currencies from the filtered securities.
        logging.debug(f"Relevant currencies before expanding with filtered securities: {relevant_currencies}")

        # Process Shares to expand relevant_currencies
        for share in filtered_shares:
            if share.currency: relevant_currencies.add(share.currency)
            if share.payment:
                for payment in share.payment:
                    if payment.currency: relevant_currencies.add(payment.currency)
        
        # Process Funds to expand relevant_currencies
        for fund in filtered_funds:
            if fund.currency: relevant_currencies.add(fund.currency)
            if fund.payment:
                for payment in fund.payment:
                    if payment.currency: relevant_currencies.add(payment.currency)

        # Process Bonds to expand relevant_currencies
        for bond in filtered_bonds:
            if bond.currency: relevant_currencies.add(bond.currency)
            if bond.payment:
                for payment in bond.payment:
                    if payment.currency: relevant_currencies.add(payment.currency)

        logging.info(f"Final set of relevant currencies (after processing filtered securities): {relevant_currencies if relevant_currencies else 'None'}")

        # 8. Filter ExchangeRate Objects (Daily Rates)
        filtered_exchange_rates = []
        if kursliste_data.exchangeRates:
            logging.info(f"Processing {len(kursliste_data.exchangeRates)} daily exchange rates...")
            for rate in kursliste_data.exchangeRates:
                if rate.currency in relevant_currencies:
                    filtered_exchange_rates.append(rate)
            logging.info(f"Kept {len(filtered_exchange_rates)} daily exchange rates.")
        else:
            logging.info("No daily exchange rates (exchangeRates) found in input.")

        # 9. Filter ExchangeRateMonthly Objects
        filtered_exchange_rates_monthly = []
        if kursliste_data.exchangeRatesMonthly:
            logging.info(f"Processing {len(kursliste_data.exchangeRatesMonthly)} monthly exchange rates...")
            for rate in kursliste_data.exchangeRatesMonthly:
                if rate.currency in relevant_currencies:
                    filtered_exchange_rates_monthly.append(rate)
            logging.info(f"Kept {len(filtered_exchange_rates_monthly)} monthly exchange rates.")
        else:
            logging.info("No monthly exchange rates (exchangeRatesMonthly) found in input.")

        # 10. Filter ExchangeRateYearEnd Objects
        filtered_exchange_rates_year_end = []
        if kursliste_data.exchangeRatesYearEnd:
            logging.info(f"Processing {len(kursliste_data.exchangeRatesYearEnd)} year-end exchange rates...")
            for rate in kursliste_data.exchangeRatesYearEnd:
                if rate.currency in relevant_currencies: # Assuming ExchangeRateYearEnd has a 'currency' field for filtering
                    filtered_exchange_rates_year_end.append(rate)
            logging.info(f"Kept {len(filtered_exchange_rates_year_end)} year-end exchange rates.")
        else:
            logging.info("No year-end exchange rates (exchangeRatesYearEnd) found in input.")
        
        logging.info(f"Finished exchange rate filtering. Counts: Daily={len(filtered_exchange_rates)}, Monthly={len(filtered_exchange_rates_monthly)}, YearEnd={len(filtered_exchange_rates_year_end)}")

        # 11. Filter DefinitionCurrency Elements
        filtered_definition_currencies = []
        if kursliste_data.currencies: # This is List[DefinitionCurrency]
            logging.info(f"Processing {len(kursliste_data.currencies)} definition currencies...")
            for def_curr in kursliste_data.currencies:
                if def_curr.currency in relevant_currencies:
                    filtered_definition_currencies.append(def_curr)
            logging.info(f"Kept {len(filtered_definition_currencies)} definition currencies.")
        else:
            logging.info("No definition currencies (currencies) found in input.")

        # 12. Identify Relevant Country Codes from Securities
        relevant_country_codes = set()
        for sec_list in [filtered_shares, filtered_funds, filtered_bonds]:
            for sec in sec_list:
                if sec.country: # Assuming securities have a 'country' attribute (ISO2 code)
                    relevant_country_codes.add(sec.country)
        logging.info(f"Identified relevant country codes from securities: {relevant_country_codes}")
        
        # 13. Identify Referenced Institutions and Filter Institution Elements
        referenced_institution_ids = set()
        for sec_list in [filtered_shares, filtered_funds, filtered_bonds]:
            for sec in sec_list:
                if hasattr(sec, 'institutionId') and sec.institutionId: # Check if attribute exists
                    referenced_institution_ids.add(sec.institutionId)
        logging.info(f"Identified {len(referenced_institution_ids)} referenced institution IDs from securities.")

        filtered_institutions = []
        if kursliste_data.institutions:
            logging.info(f"Processing {len(kursliste_data.institutions)} institutions...")
            for inst in kursliste_data.institutions:
                if inst.id in referenced_institution_ids:
                    filtered_institutions.append(inst)
            logging.info(f"Kept {len(filtered_institutions)} institutions.")
            
            # Add country codes from filtered institutions to relevant_country_codes
            for inst in filtered_institutions:
                if inst.country: # Assuming Institution has a 'country' attribute
                    relevant_country_codes.add(inst.country)
            logging.info(f"Updated relevant country codes with institution countries: {relevant_country_codes}")
        else:
            logging.info("No institutions found in input.")

        # 14. Filter Country Elements based on updated relevant_country_codes
        filtered_countries = []
        if kursliste_data.countries:
            logging.info(f"Processing {len(kursliste_data.countries)} country definitions...")
            for country_def in kursliste_data.countries:
                if country_def.country in relevant_country_codes: # 'country' field on Country model is the ISO2 code
                    filtered_countries.append(country_def)
            logging.info(f"Kept {len(filtered_countries)} country definitions.")
        else:
            logging.info("No country definitions (countries) found in input.")

        logging.info("Finished definitional element filtering.")
        
        # 15. Construct Output Kursliste Object
        logging.info("Constructing the output Kursliste object...")
        output_kursliste_obj = Kursliste(
            # Top-level attributes from original data
            version=kursliste_data.version,
            creationDate=kursliste_data.creationDate,
            referingToDate=kursliste_data.referingToDate if kursliste_data.referingToDate else None,
            year=kursliste_data.year,

            # Definitions (Non-filtered - taken directly from source)
            # Ensure these attributes exist on kursliste_data before assigning
            cantons=kursliste_data.cantons if kursliste_data.cantons else [],
            capitalKeys=kursliste_data.capitalKeys if kursliste_data.capitalKeys else [],
            securityGroups=kursliste_data.securityGroups if kursliste_data.securityGroups else [],
            securityTypes=kursliste_data.securityTypes if kursliste_data.securityTypes else [],
            legalForms=kursliste_data.legalForms if kursliste_data.legalForms else [],
            sectors=kursliste_data.sectors if kursliste_data.sectors else [],
            shortCuts=kursliste_data.shortCuts if kursliste_data.shortCuts else [],
            signs=kursliste_data.signs if kursliste_data.signs else [],
            da1Rates=kursliste_data.da1Rates if kursliste_data.da1Rates else [],
            mediumTermBonds=kursliste_data.mediumTermBonds if kursliste_data.mediumTermBonds else [],
            
            # Definitions (Filtered)
            countries=filtered_countries,
            currencies=filtered_definition_currencies,
            institutions=filtered_institutions,

            # Securities (Filtered)
            bonds=filtered_bonds,
            coinBullions=[], # Not processed in this script
            currencyNotes=[], # Not processed in this script
            derivatives=[], # Not processed in this script
            funds=filtered_funds,
            liborSwaps=[], # Not processed in this script
            shares=filtered_shares,
 
            # Exchange Rates (Filtered)
            exchangeRates=filtered_exchange_rates,
            exchangeRatesMonthly=filtered_exchange_rates_monthly,
            exchangeRatesYearEnd=filtered_exchange_rates_year_end
        )
        logging.info("Successfully constructed output_kursliste_obj.")

        # 16. Serialize to XML
        logging.info(f"Serializing output Kursliste to XML for output file: {args.output_file}...")
        try:
            # Use the instance method to_xml for serialization
            # ns_map should be handled by the model's own definition
            output_xml_bytes = output_kursliste_obj.to_xml(
                pretty_print=True,
                encoding="UTF-8",
                xml_declaration=True,
                exclude_unset=True,
                exclude_none=True,
            )
            logging.info("Successfully serialized Kursliste to XML bytes using instance method.")
        except Exception as e:
            logging.error(f"Error during XML serialization using instance method: {e}", exc_info=True)
            return 1 # Exit if serialization fails

        # 17. Write to Output File
        try:
            with open(args.output_file, 'wb') as f:
                f.write(output_xml_bytes)
            logging.info(f"Successfully wrote filtered Kursliste to {args.output_file}")
        except IOError as e:
            logging.error(f"Error writing output XML to file {args.output_file}: {e}", exc_info=True)
            return 1 # Exit if file writing fails
            
        logging.info("Script finished successfully.")
        return 0 # Exit with success code

    except FileNotFoundError:
        logging.error(f"Error: Input file not found at {args.input_file}")
        return 1
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
        return 1
    return 1 # Exit with error code

if __name__ == "__main__":
    sys.exit(main())
