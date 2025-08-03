import re # Added for sanitization
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any, cast, get_args # Added get_args import
# import os # Removed os import
# Removed pandas import
from decimal import Decimal
import logging
from opensteuerauszug.model.ech0196 import SecurityTaxValue, TaxStatement, SecurityStock, BankAccountPayment, SecurityPayment, Client, ClientNumber, CantonAbbreviation
from opensteuerauszug.util.sorting import find_index_of_date, sort_security_stocks, sort_payments, sort_security_payments
from opensteuerauszug.config.models import GeneralSettings
from opensteuerauszug.core.position_reconciler import PositionReconciler
from opensteuerauszug.core.constants import UNINITIALIZED_QUANTITY
# from opensteuerauszug.core.identifier_loader import SecurityIdentifierMapLoader # Removed loader import

logger = logging.getLogger(__name__)

class CleanupCalculator:
    """
    Calculator responsible for initial cleanup tasks:
    1. Sorting payments and stock statements.
    2. Optionally filtering these entries to the specified tax period.
    3. Optionally enriching securities with missing ISIN/Valor from a provided map.
    4. Setting canton and client name from configuration if not already set.
    """
    def __init__(self,
                 period_from: date,
                 period_to: date,
                 importer_name: str, # Added importer_name parameter
                 identifier_map: Optional[Dict[str, Dict[str, Any]]] = None,
                 enable_filtering: bool = True,
                 
                 config_settings: Optional[GeneralSettings] = None):
        self.period_from = period_from
        self.period_to = period_to
        self.importer_name = importer_name # Store importer_name
        self.identifier_map = identifier_map
        self.enable_filtering = enable_filtering
        self.config_settings = config_settings
        self.modified_fields: List[str] = []

        # Log if an identifier map was provided
        if self.identifier_map is not None: # Check if it's not None, could be an empty dict
            logger.info(f"Initialized with an identifier map containing {len(self.identifier_map)} entries.")
        else:
            logger.info("Initialized without an identifier map. Enrichment will be skipped.")

        # Log if configuration was provided
        if self.config_settings:
            logger.info(f"Initialized with configuration settings.")
        else:
            logger.info("Initialized without configuration settings.")

    

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
            logger.warning("TaxStatement.country is None, using 'XX' for ID generation.")
        else:
            country_code = country_code.strip()
        country_code = country_code.upper()
        country_code = country_code[:2] # Ensure 2 chars

        # 2. Organization ID (12 chars): "OPNAUS" + 6 chars from importer name
        # Use importer_name passed during calculator initialization
        raw_importer_name = self.importer_name
        # logger.info(f"Info: Using raw_importer_name='{raw_importer_name}' from self.importer_name for Org ID generation.")

        if not raw_importer_name or not raw_importer_name.strip():
            importer_name_part = "XXXXXX"
            logger.warning("Importer name is None or empty, using 'XXXXXX' for Org ID part.")
        else:
            upper_importer_name = raw_importer_name.upper()
            sanitized_importer_name = re.sub(r'[^a-zA-Z0-9]', '', upper_importer_name)
            if not sanitized_importer_name:
                importer_name_part = "XXXXXX"
                logger.warning(f"Sanitized importer name '{upper_importer_name}' is empty, using 'XXXXXX' for Org ID part.")
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
                logger.warning("No clientNumber or TIN found for the first client. Using placeholder for customer ID part.")
        else:
            customer_id_raw = "NOCLIENTDATA" # Placeholder before padding
            customer_id_source = "placeholder_no_clients"
            logger.warning("statement.client list is empty. Using placeholder for customer ID part.")

        # Remove spaces and special characters (sanitize)
        sanitized_customer_id = re.sub(r'[^a-zA-Z0-9]', '', customer_id_raw)

        # Format to exactly 14 characters
        if len(sanitized_customer_id) > 14:
            customer_id = sanitized_customer_id[:14]  # Truncate to 14 chars if longer
        else:
            customer_id = sanitized_customer_id.ljust(14, 'X')  # Pad with 'X' to 14 chars if shorter

        # 5. Date (8 chars)
        # statement.periodTo is mandatory, so direct access should be safe.
        assert statement.periodTo is not None
        date_str = statement.periodTo.strftime("%Y%m%d")

        # 6. Sequential Number (2 chars)
        seq_no = "01"

        # Concatenate all parts
        final_id = f"{country_code}{org_id}{customer_id}{date_str}{seq_no}"

        logger.debug(f"Generated ID components: Country='{country_code}', Org='{org_id}' (ImporterRaw: '{raw_importer_name}'), CustRaw='{customer_id_raw}' (Source: {customer_id_source}), CustSanitized='{customer_id}', Date='{date_str}', Seq='{seq_no}'")
        
        return final_id

    def calculate(self, statement: TaxStatement) -> TaxStatement:
        self.modified_fields = []
        logger.info("Starting cleanup calculation...")

        # set some standard values
        statement.minorVersion = 22
        statement.periodFrom = self.period_from
        statement.periodTo = self.period_to
        # Defensive for simpler testing in isolation
        statement.taxPeriod = self.period_to.year if self.period_to else None
        statement.country = "CH" # We are handling Swiss taxes

        # if set assume the importer used the stastment time.
        if not statement.creationDate:
            statement.creationDate = datetime.now()

        # Set canton from configuration if not already set
        if not statement.canton and self.config_settings and self.config_settings.canton:
            canton_value = self.config_settings.canton
            # Validate canton against allowed values
            valid_cantons = get_args(CantonAbbreviation)
            if canton_value in valid_cantons:
                statement.canton = cast(CantonAbbreviation, canton_value)
                self.modified_fields.append("TaxStatement.canton (from config)")
                logger.info(f"Set canton from configuration: {statement.canton}")
            else:
                logger.warning(f"Invalid canton '{canton_value}'. Valid cantons are: {', '.join(valid_cantons)}")

        # Set client name from configuration if client exists but lacks name
        if self.config_settings and self.config_settings.full_name:
            config_full_name = self.config_settings.full_name
            
            # Parse the full name (assuming "First Last" format)
            name_parts = config_full_name.strip().split()
            if len(name_parts) >= 2:
                config_first_name = name_parts[0]
                config_last_name = ' '.join(name_parts[1:])  # Join remaining parts as last name
            elif len(name_parts) == 1:
                config_first_name = name_parts[0]
                config_last_name = None  # Use None instead of empty string
            else:
                config_first_name = None  # Use None instead of empty string
                config_last_name = None

            # If no clients exist, create one with the configured name
            if not statement.client:
                new_client = Client(
                    firstName=config_first_name,
                    lastName=config_last_name
                )
                statement.client = [new_client]
                self.modified_fields.append("TaxStatement.client (created from config)")
                logger.info(f"Created client from configuration: {config_full_name}")
            else:
                # Check if existing clients need name updates
                for i, client in enumerate(statement.client):
                    client_modified = False
                    
                    # Set firstName if not already set
                    if not client.firstName and config_first_name:
                        client.firstName = config_first_name
                        client_modified = True
                        
                    # Set lastName if not already set
                    if not client.lastName and config_last_name:
                        client.lastName = config_last_name
                        client_modified = True
                    
                    if client_modified:
                        self.modified_fields.append(f"TaxStatement.client[{i}] (name from config)")
                        logger.info(f"Updated client[{i}] name from configuration: {config_full_name}")

        # Generate statement ID if it's missing
        if statement.id is None:
            try:
                statement.id = self._generate_tax_statement_id(statement)
                logger.info(f"Generated new TaxStatement.id: {statement.id}")
                self.modified_fields.append("TaxStatement.id (generated)")
            except NotImplementedError as e: # Should ideally not be raised if logic is complete
                logger.error(f"Error generating TaxStatement.id (NotImplemented): {e}")
            #except Exception as e: # Catch any other unexpected error during ID generation
            #    logger.error(f"Unexpected error during TaxStatement.id generation: {e}")
            #    # statement.id will remain None, allowing process to potentially continue

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
                                logger.debug(f"  BankAccount {account_id}: Filtered {original_payment_count} payments to {len(bank_account.payment)} for period [{self.period_from} - {self.period_to}].")
                            # No log if no payments were removed by filtering
                        else:
                            logger.info(f"  BankAccount {account_id}: Payment filtering skipped (tax period not fully defined).")
                    # No log if filtering is disabled globally
        else:
            logger.info("No bank accounts found to process.")

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
                        if self.identifier_map:
                            if security.symbol:
                                lookup_key = security.symbol
                            elif security.securityName:
                                lookup_key = security.securityName
                            else:
                                continue
                            
                            if (not security.isin or not security.valorNumber or security.valorNumber == 0) and lookup_key in self.identifier_map:
                                found_identifiers = self.identifier_map[lookup_key]
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
                                    log_pos_id_for_enrichment = f"{depot_id}/{lookup_key}" # Use symbol for this specific log.
                                    logger.info(f"  Security {log_pos_id_for_enrichment}: Enriched ISIN/Valor from identifier file using symbol '{lookup_key}'.")
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
                                            referenceDate=self.period_to,
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
                                        logger.debug(f"  Security {pos_id}: Filtered {original_stock_count} stock events to {len(security.stock)} for period [{self.period_from} - {self.period_to}] (retaining start/end balances & period mutations).")
                                    # No log if no stock events were removed by filtering
                                else:
                                    logger.info(f"  Security {pos_id}: Stock event filtering skipped (tax period not fully defined).")
                            # No log if filtering is disabled globally

                        # Process Security Payments for the current security
                        if security.payment:
                            payments_needing_qty_update = any(
                                p.quantity == UNINITIALIZED_QUANTITY for p in security.payment
                            )

                            if payments_needing_qty_update and not security.stock:
                                # security_display_id and depot_id are defined above
                                raise ValueError(
                                    f"Missing stock data (Security.stock is None or empty) for security '{security_display_id}' "
                                    f"(Depot: {depot_id}, ISIN: {security.isin or 'N/A'}, Valor: {security.valorNumber or 'N/A'}) "
                                    f"which has payments requiring quantity calculation. Cannot proceed."
                                )

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
                                        logger.debug(f"  Security {pos_id}: Filtered {original_sec_payment_count} security payments to {len(security.payment)} for period [{self.period_from} - {self.period_to}].")
                                else:
                                    logger.info(f"  Security {pos_id}: Security payment filtering skipped (tax period not fully defined).")

                            # --- Calculate SecurityPayment.quantity where it's UNINITIALIZED_QUANTITY ---
                            # This block is now only entered if security.stock is guaranteed to be non-empty (due to the check above)
                            # OR if no payments needed update in the first place.
                            if payments_needing_qty_update and security.stock: # security.stock check is technically redundant here but safe
                                reconciler = PositionReconciler(list(security.stock), identifier=f"{pos_id}-payment-qty-reconcile")
                                for payment_event in security.payment:
                                    if payment_event.quantity == UNINITIALIZED_QUANTITY:
                                        date_to_use_for_reconciliation = payment_event.paymentDate
                                        log_date_source = "paymentDate"
                                        if payment_event.exDate:
                                            date_to_use_for_reconciliation = payment_event.exDate
                                            log_date_source = "exDate"
                                            # Removed the preliminary "Using exDate..." log as requested.
                                            # The information will be in the success or error message.
                                        reconciled_quantity_info = reconciler.synthesize_position_at_date(date_to_use_for_reconciliation)

                                        if reconciled_quantity_info is not None and reconciled_quantity_info.quantity is not None:
                                            original_dummy_qty = payment_event.quantity
                                            payment_event.quantity = reconciled_quantity_info.quantity
                                            payment_identifier_log = f"Payment (Name: {payment_event.name or 'N/A'}, Date: {payment_event.paymentDate}, exDate: {payment_event.exDate or 'N/A'})"
                                            self.modified_fields.append(f"{pos_id}.{payment_identifier_log}.quantity (updated via {log_date_source})")
                                            logger.debug(
                                                f"  Security {pos_id}: Updated quantity for {payment_identifier_log} to {payment_event.quantity} "
                                                f"using {log_date_source} ({date_to_use_for_reconciliation}). Original dummy: {original_dummy_qty}."
                                            )
                                        else:
                                            # Construct security_display_id for error message using the already available 'pos_id'
                                            # which is f"{depot_id}/{security_display_id}"
                                            # security_display_id itself is defined at the start of the security loop.
                                            error_message = (
                                                f"Could not determine stock quantity for security '{security_display_id}' "
                                                f"(Depot: {depot_id}, Payment: '{payment_event.name or 'N/A'}' on {payment_event.paymentDate}, exDate: {payment_event.exDate or 'N/A'}) "
                                                f"using date {date_to_use_for_reconciliation} (as {log_date_source}). Check stock history. Current quantity remains {payment_event.quantity}."
                                            )
                                            raise ValueError(error_message)
                            # The case of (security.payment and not security.stock and payments_needing_qty_update)
                            # is now handled by the ValueError raised before this loop.
                            # If payments_needing_qty_update is False, this loop isn't problematic even if security.stock is empty.
                            # --- End Calculate SecurityPayment.quantity ---
        else:
            logger.info("No securities accounts found to process.")

        if self.modified_fields:
            logger.info(f"Cleanup calculation finished. Summary: Modified fields count: {len(self.modified_fields)}")
            logger.debug(f"Detailed list of modified fields: {', '.join(self.modified_fields)}")
        else:
            logger.info("Cleanup calculation finished. No data was modified.") # Adjusted log
        return statement

    