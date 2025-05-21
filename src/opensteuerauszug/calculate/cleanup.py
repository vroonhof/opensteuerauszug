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
                 identifier_map: Optional[Dict[str, Dict[str, any]]] = None, # New argument
                 enable_filtering: bool = True,
                 print_log: bool = False):
        self.period_from = period_from
        self.period_to = period_to
        self.identifier_map = identifier_map # Store injected map
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

    def calculate(self, statement: TaxStatement) -> TaxStatement:
        self.modified_fields = []
        self.log_messages = []
        self._log("Starting cleanup calculation...")

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
                        if self.identifier_map and security.securityName: # securityName is used as lookup key
                            lookup_symbol = security.securityName
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
            self._log(f"Cleanup calculation finished. Fields modified by filtering: {', '.join(self.modified_fields)}.")
        else:
            self._log("Cleanup calculation finished. No data was filtered out by period.")
        return statement

    def get_log(self) -> List[str]:
        return list(self.log_messages)