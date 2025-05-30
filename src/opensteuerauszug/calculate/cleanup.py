import re # Added for sanitization
from datetime import date, timedelta
from typing import List, Optional, Dict # Added Dict
# import os # Removed os import
# Removed pandas import
from opensteuerauszug.model.ech0196 import SecurityTaxValue, TaxStatement, SecurityStock, BankAccountPayment, SecurityPayment
from opensteuerauszug.util.sorting import find_index_of_date, sort_security_stocks, sort_payments, sort_security_payments
# from opensteuerauszug.core.identifier_loader import SecurityIdentifierMapLoader # Removed loader import

class CleanupCalculator:
    """
    Calculator responsible for initial cleanup tasks:
    1. Sorting payments and stock statements.
    2. Optionally filtering these entries to the specified tax period.
    3. Optionally enriching securities with missing ISIN/Valor from a provided map.
    """
    def __init__(self,
                 period_from: Optional[date],
                 period_to: Optional[date],
                 importer_name: str, # Added importer_name parameter
                 identifier_map: Optional[Dict[str, Dict[str, any]]] = None,
                 enable_filtering: bool = True,
                 print_log: bool = False):
        self.period_from = period_from
        self.period_to = period_to
        self.importer_name = importer_name # Store importer_name
        self.identifier_map = identifier_map
        self.enable_filtering = enable_filtering
        self.print_log = print_log
        self.modified_fields: List[str] = []
        self.log_messages: List[str] = []
        
        # Log if an identifier map was provided
        if self.identifier_map is not None: # Check if it's not None, could be an empty dict
            self._log(f"CleanupCalculator initialized with an identifier map containing {len(self.identifier_map)} entries.")
        else:
            self._log("CleanupCalculator initialized without an identifier map. Enrichment will be skipped.")

    def _log(self, message: str):
        self.log_messages.append(message)
        if self.print_log:
            print(f"  [CleanupCalculator] {message}")

    from opensteuerauszug.model.ech0196 import TaxStatement  # Explicit import for clarity

    def _generate_tax_statement_id(self, statement: TaxStatement) -> str:
        """
        Generates a new ID for the tax statement based on its content.
        Format: CCOOOOOOOOOOOCCCCCCCCCCCCCCYYYYMMDDSS (Page number PP omitted)
        CC: Country Code (2 Chars)
        OOOOOOOOOOOO: Organization ID ("OPNAUS" + 6 chars from importer name) (12 Chars)
        CCCCCCCCCCCCCC: Customer ID (sanitized clientNumber or TIN) (14 Chars)
        YYYYMMDD: Statement Period To Date (8 Chars)
        SS: Sequential Number (fixed "01") (2 Chars)
        """
        # 1. Country Code (2 chars)
        country_code = statement.country
        if not country_code or not country_code.strip(): # Check for None or empty/whitespace string
            country_code = "XX"
            self._log("Warning: TaxStatement.country is None, using 'XX' for ID generation.")
        else:
            country_code = country_code.strip()
        country_code = country_code.upper()
        country_code = country_code[:2] # Ensure 2 chars

        # 2. Organization ID (12 chars): "OPNAUS" + 6 chars from importer name
        # Use importer_name passed during calculator initialization
        raw_importer_name = self.importer_name
        # self._log(f"Info: Using raw_importer_name='{raw_importer_name}' from self.importer_name for Org ID generation.")

        if not raw_importer_name or not raw_importer_name.strip():
            importer_name_part = "XXXXXX"
            self._log("Warning: Importer name is None or empty, using 'XXXXXX' for Org ID part.")
        else:
            upper_importer_name = raw_importer_name.upper()
            sanitized_importer_name = re.sub(r'[^a-zA-Z0-9]', '', upper_importer_name)
            if not sanitized_importer_name:
                importer_name_part = "XXXXXX"
                self._log(f"Warning: Sanitized importer name '{upper_importer_name}' is empty, using 'XXXXXX' for Org ID part.")
            elif len(sanitized_importer_name) >= 6:
                importer_name_part = sanitized_importer_name[:6]
            else: # len < 6
                importer_name_part = sanitized_importer_name.rjust(6, 'X') # Left-pad with X

        org_id = f"OPNAUS{importer_name_part}"
        # End of new OrgID generation strategy

        # Page number (e.g., "01") was part of the original eCH-0196 spec for the ID,
        # but is omitted here as it's reportedly not used in practice,
        # and simplifies the ID structure.
        # page_no = "01" # Removed

        # 4. Customer ID (14 chars, alphanumeric)
        customer_id_raw = ""
        customer_id_source = "None"
        if statement.client: # Check if the list is not empty
            first_client = statement.client[0]
            # Check if clientNumber exists and is not just whitespace
            if first_client.clientNumber and first_client.clientNumber.strip():
                customer_id_raw = first_client.clientNumber.strip()
                customer_id_source = "clientNumber"
            # Else, check if tin exists and is not just whitespace
            elif first_client.tin and first_client.tin.strip():
                customer_id_raw = first_client.tin.strip()
                customer_id_source = "tin"
            else:
                customer_id_raw = "NOIDENTIFIER" # Placeholder before padding
                customer_id_source = "placeholder_no_client_id"
                self._log("Warning: No clientNumber or TIN found for the first client. Using placeholder for customer ID part.")
        else:
            customer_id_raw = "NOCLIENTDATA" # Placeholder before padding
            customer_id_source = "placeholder_no_clients"
            self._log("Warning: statement.client list is empty. Using placeholder for customer ID part.")

        # Remove spaces and special characters (sanitize)
        sanitized_customer_id = re.sub(r'[^a-zA-Z0-9]', '', customer_id_raw)

        # Format to exactly 14 characters
        if len(sanitized_customer_id) > 14:
            customer_id = sanitized_customer_id[:14]  # Truncate to 14 chars if longer
        else:
            customer_id = sanitized_customer_id.ljust(14, 'X')  # Pad with 'X' to 14 chars if shorter

        # 5. Date (8 chars)
        # statement.periodTo is mandatory, so direct access should be safe.
        date_str = statement.periodTo.strftime("%Y%m%d")

        # 6. Sequential Number (2 chars)
        seq_no = "01"

        # Concatenate all parts
        final_id = f"{country_code}{org_id}{customer_id}{date_str}{seq_no}"

        self._log(f"Generated ID components: Country='{country_code}', Org='{org_id}' (ImporterRaw: '{raw_importer_name}'), CustRaw='{customer_id_raw}' (Source: {customer_id_source}), CustSanitized='{customer_id}', Date='{date_str}', Seq='{seq_no}'")
        
        return final_id

    def calculate(self, statement: TaxStatement) -> TaxStatement:
        self.modified_fields = []
        self.log_messages = []
        self._log("Starting cleanup calculation...")

        # Generate statement ID if it's missing
        if statement.id is None:
            try:
                statement.id = self._generate_tax_statement_id(statement)
                self._log(f"Generated new TaxStatement.id: {statement.id}")
                self.modified_fields.append("TaxStatement.id (generated)")
            except NotImplementedError as e: # Should ideally not be raised if logic is complete
                self._log(f"Error generating TaxStatement.id (NotImplemented): {e}")
            except Exception as e: # Catch any other unexpected error during ID generation
                self._log(f"Unexpected error during TaxStatement.id generation: {e}")
                # statement.id will remain None, allowing process to potentially continue

        # Process Bank Accounts
        if statement.listOfBankAccounts and statement.listOfBankAccounts.bankAccount:
            for idx, bank_account in enumerate(statement.listOfBankAccounts.bankAccount):
                account_id = bank_account.bankAccountNumber or bank_account.iban or f"BankAccount_{idx+1}"
                if bank_account.payment:
                    original_payment_count = len(bank_account.payment)

                    # Sort payments (silently)
                    bank_account.payment = sort_payments(bank_account.payment)

                    if self.enable_filtering:
                        if self.period_from and self.period_to:
                            filtered_payments = [
                                p for p in bank_account.payment
                                if self.period_from <= p.paymentDate <= self.period_to
                            ]
                            removed_count = len(bank_account.payment) - len(filtered_payments)
                            if removed_count > 0:
                                bank_account.payment = filtered_payments
                                self.modified_fields.append(f"{account_id}.payment (filtered)")
                                self._log(f"  BankAccount {account_id}: Filtered {original_payment_count} payments to {len(bank_account.payment)} for period [{self.period_from} - {self.period_to}].")
                            # No log if no payments were removed by filtering
                        else:
                            self._log(f"  BankAccount {account_id}: Payment filtering skipped (tax period not fully defined).")
                    # No log if filtering is disabled globally
        else:
            self._log("No bank accounts found to process.")

        # Process Securities Accounts
        if statement.listOfSecurities and statement.listOfSecurities.depot:
            for depot_idx, depot in enumerate(statement.listOfSecurities.depot):
                depot_id = depot.depotNumber or f"Depot_{depot_idx+1}"
                if depot.security:
                    for sec_idx, security in enumerate(depot.security):
                        security_id_parts = [
                            security.isin,
                            str(security.valorNumber) if security.valorNumber else None,
                            security.securityName
                        ]
                        security_display_id = next((s_id for s_id in security_id_parts if s_id), f"Security_{sec_idx+1}")
                        pos_id = f"{depot_id}/{security_display_id}" # Original pos_id for logging before enrichment

                        # Identifier Enrichment Logic
                        if self.identifier_map and security.symbol: # Use security.symbol for condition
                            lookup_symbol = security.symbol # Use security.symbol for lookup
                            if (not security.isin or not security.valorNumber or security.valorNumber == 0) and lookup_symbol in self.identifier_map:
                                found_identifiers = self.identifier_map[lookup_symbol]
                                enriched = False
                                if not security.isin and found_identifiers.get('isin'):
                                    security.isin = found_identifiers['isin']
                                    enriched = True
                                
                                if (not security.valorNumber or security.valorNumber == 0) and found_identifiers.get('valor'):
                                    # Valor in map is already int or None due to loading logic
                                    security.valorNumber = found_identifiers['valor']
                                    enriched = True
                                
                                if enriched:
                                    # Update security_display_id and pos_id for subsequent logging if identifiers changed
                                    new_security_id_parts = [
                                        security.isin,
                                        str(security.valorNumber) if security.valorNumber else None,
                                        security.securityName
                                    ]
                                    security_display_id = next((s_id for s_id in new_security_id_parts if s_id), f"Security_{sec_idx+1}")
                                    # Reconstruct pos_id based on potentially new security_display_id
                                    # This ensures logs for filtering etc. use the enriched ID.
                                    # However, for the enrichment log itself, we use the original pos_id or lookup_symbol.
                                    log_pos_id_for_enrichment = f"{depot_id}/{lookup_symbol}" # Use symbol for this specific log.
                                    self._log(f"  Security {log_pos_id_for_enrichment}: Enriched ISIN/Valor from identifier file using symbol '{lookup_symbol}'.")
                                    self.modified_fields.append(f"{log_pos_id_for_enrichment} (enriched)")
                                    # Update pos_id for subsequent operations in this loop, if needed
                                    pos_id = f"{depot_id}/{security_display_id}"


                        if security.stock:
                            original_stock_count = len(security.stock)

                            # Sort stock events (silently)
                            security.stock = sort_security_stocks(security.stock)
                            # End of period balances are reflected in the tax value
                            if self.period_to:
                                period_end_plus_one = self.period_to + timedelta(days=1)
                                find_index = find_index_of_date(period_end_plus_one, security.stock)
                                if find_index < len(security.stock):
                                    candidate = security.stock[find_index]
                                    if candidate.referenceDate == period_end_plus_one and not candidate.mutation:
                                        # First balance after the period end is the end balance of the period
                                        security.taxValue = SecurityTaxValue(
                                            referenceDate=candidate.referenceDate,
                                            quotationType=candidate.quotationType,
                                            quantity=candidate.quantity,
                                            balanceCurrency=candidate.balanceCurrency,
                                            balance=candidate.balance,
                                            unitPrice=candidate.unitPrice)

                            # TODO Should we ensure the balances at the start and end of the period are
                            #       present here instead of in the importers?.
                            if self.enable_filtering:
                                # could have used bisect
                                if self.period_from and self.period_to:
                                    newly_filtered_stocks = []
                                    for s_event in security.stock:
                                        keep_event = False
                                        if s_event.mutation: # It's a transaction/mutation
                                            # Keep mutations if they fall within the tax period
                                            if self.period_from <= s_event.referenceDate <= self.period_to:
                                                keep_event = True
                                        else: # It's a balance (not a mutation)
                                            # Keep balances only if they are at the start of the period
                                            if s_event.referenceDate == self.period_from:
                                                keep_event = True
                                        
                                        if keep_event:
                                            newly_filtered_stocks.append(s_event)

                                    removed_count = len(security.stock) - len(newly_filtered_stocks)
                                    if removed_count > 0:
                                        security.stock = newly_filtered_stocks
                                        self.modified_fields.append(f"{pos_id}.stock (filtered)")
                                        self._log(f"  Security {pos_id}: Filtered {original_stock_count} stock events to {len(security.stock)} for period [{self.period_from} - {self.period_to}] (retaining start/end balances & period mutations).")
                                    # No log if no stock events were removed by filtering
                                else:
                                    self._log(f"  Security {pos_id}: Stock event filtering skipped (tax period not fully defined).")
                            # No log if filtering is disabled globally

                        # Process Security Payments for the current security
                        if security.payment:
                            original_sec_payment_count = len(security.payment)

                            # Sort security payments (silently)
                            security.payment = sort_security_payments(security.payment)

                            if self.enable_filtering:
                                if self.period_from and self.period_to:
                                    filtered_sec_payments = [
                                        p for p in security.payment
                                        if self.period_from <= p.paymentDate <= self.period_to
                                    ]
                                    removed_sec_payment_count = len(security.payment) - len(filtered_sec_payments)
                                    if removed_sec_payment_count > 0:
                                        security.payment = filtered_sec_payments
                                        self.modified_fields.append(f"{pos_id}.payment (filtered)")
                                        self._log(f"  Security {pos_id}: Filtered {original_sec_payment_count} security payments to {len(security.payment)} for period [{self.period_from} - {self.period_to}].")
                                else:
                                    self._log(f"  Security {pos_id}: Security payment filtering skipped (tax period not fully defined).")
        else:
            self._log("No securities accounts found to process.")

        if self.modified_fields:
            self._log(f"Cleanup calculation finished. Fields modified: {', '.join(self.modified_fields)}.")
        else:
            self._log("Cleanup calculation finished. No data was modified.") # Adjusted log
        return statement

    def get_log(self) -> List[str]:
        return list(self.log_messages)