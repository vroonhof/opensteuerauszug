from decimal import Decimal
from typing import List, Optional, Dict, Any, cast

from ..model.ech0196 import (
    TaxStatement, Security, BankAccount, LiabilityAccount, Expense,
    ListOfSecurities, Depot, ListOfBankAccounts, ListOfLiabilities, ListOfExpenses
)
from .base import BaseCalculator, CalculationMode, CalculationError

class TotalCalculator(BaseCalculator):
    """
    Calculator that computes and verifies the total values at the top level of the tax statement.
    
    This calculator handles:
    - totalTaxValue: Sum of all tax values across securities, bank accounts, and liabilities
    - totalGrossRevenueA: Sum of all type A gross revenues
    - totalGrossRevenueB: Sum of all type B gross revenues
    - totalWithHoldingTaxClaim: Sum of all withholding tax claims
    - totalGrossRevenueDA1: Sum of all DA-1 gross revenues (USA)
    - totalTaxValueDA1: Sum of all DA-1 tax values (USA)
    - totalFlatRateTaxCredit: Sum of all flat rate tax credits
    - totalAdditionalWithHoldingTaxUSA: Sum of all additional withholding taxes for USA
    """
    
    def __init__(self, mode: CalculationMode = CalculationMode.FILL):
        super().__init__(mode)
        # Initialize accumulators for the totals
        self.total_tax_value = Decimal('0')
        self.total_gross_revenue_a = Decimal('0')
        self.total_gross_revenue_b = Decimal('0')
        self.total_withholding_tax_claim = Decimal('0')
        self.total_gross_revenue_da1 = Decimal('0')
        self.total_tax_value_da1 = Decimal('0')
        self.total_flat_rate_tax_credit = Decimal('0')
        self.total_additional_withholding_tax_usa = Decimal('0')
    
    def _process_tax_statement(self, tax_statement: TaxStatement) -> None: # Overrides base class method
        """
        Process the tax statement to calculate and verify total values by explicitly iterating children.
        This method opts out of the base class visitor pattern for top-level traversal.
        
        Args:
            tax_statement: The tax statement to process
        """
        # Reset accumulators before processing children
        self.total_tax_value = Decimal('0')
        self.total_gross_revenue_a = Decimal('0')
        self.total_gross_revenue_b = Decimal('0')
        self.total_withholding_tax_claim = Decimal('0')
        self.total_gross_revenue_da1 = Decimal('0')
        self.total_tax_value_da1 = Decimal('0')
        self.total_flat_rate_tax_credit = Decimal('0')
        self.total_additional_withholding_tax_usa = Decimal('0')
        
        # Explicitly iterate through children and call handlers
        if tax_statement.listOfSecurities and tax_statement.listOfSecurities.depot:
            for i, depot in enumerate(tax_statement.listOfSecurities.depot):
                if depot.security:
                    for j, security in enumerate(depot.security):
                        path = f"listOfSecurities.depot[{i}].security[{j}]"
                        self._handle_Security(security, path)

        if tax_statement.listOfBankAccounts and tax_statement.listOfBankAccounts.bankAccount:
            list_tax_value = Decimal('0')
            list_revenue_a = Decimal('0')
            list_revenue_b = Decimal('0')
            list_withholding = Decimal('0')
            
            for i, account in enumerate(tax_statement.listOfBankAccounts.bankAccount):
                path = f"listOfBankAccounts.bankAccount[{i}]"
                # Calculate totals for this account
                account_tax_value = Decimal('0')
                account_revenue_a = Decimal('0')
                account_revenue_b = Decimal('0')
                account_withholding = Decimal('0')  # Always start from 0, ignore any existing value
                
                if account.taxValue and account.taxValue.value is not None:
                    account_tax_value = account.taxValue.value
                
                if account.payment:
                    for payment in account.payment:
                        if payment.grossRevenueA is not None:
                            account_revenue_a += payment.grossRevenueA
                        if payment.grossRevenueB is not None:
                            account_revenue_b += payment.grossRevenueB
                        if payment.withHoldingTaxClaim is not None:
                            account_withholding += payment.withHoldingTaxClaim
                
                # Set individual account totals - always set all totals in FILL mode
                self._set_field_value(account, 'totalTaxValue', account_tax_value, path)
                self._set_field_value(account, 'totalGrossRevenueA', account_revenue_a, path)
                self._set_field_value(account, 'totalGrossRevenueB', account_revenue_b, path)
                self._set_field_value(account, 'totalWithHoldingTaxClaim', account_withholding, path)
                
                # Accumulate list totals
                list_tax_value += account_tax_value
                list_revenue_a += account_revenue_a
                list_revenue_b += account_revenue_b
                list_withholding += account_withholding
            
            # Set list level totals
            self._set_field_value(tax_statement.listOfBankAccounts, 'totalTaxValue', list_tax_value, "listOfBankAccounts")
            self._set_field_value(tax_statement.listOfBankAccounts, 'totalGrossRevenueA', list_revenue_a, "listOfBankAccounts")
            self._set_field_value(tax_statement.listOfBankAccounts, 'totalGrossRevenueB', list_revenue_b, "listOfBankAccounts")
            self._set_field_value(tax_statement.listOfBankAccounts, 'totalWithHoldingTaxClaim', list_withholding, "listOfBankAccounts")
            
            # Add to overall totals
            self.total_tax_value += list_tax_value
            self.total_gross_revenue_a += list_revenue_a
            self.total_gross_revenue_b += list_revenue_b
            self.total_withholding_tax_claim += list_withholding

        if tax_statement.listOfLiabilities and tax_statement.listOfLiabilities.liabilityAccount:
            for i, account in enumerate(tax_statement.listOfLiabilities.liabilityAccount):
                path = f"listOfLiabilities.liabilityAccount[{i}]"
                self._handle_LiabilityAccount(account, path)

        if tax_statement.listOfExpenses and tax_statement.listOfExpenses.expense:
             for i, expense in enumerate(tax_statement.listOfExpenses.expense):
                 path = f"listOfExpenses.expense[{i}]"
                 self._handle_Expense(expense, path) # Currently does nothing, but kept for structure
        
        # Set the regular totals
        self._set_field_value(tax_statement, 'totalTaxValue', self.total_tax_value, "") # Path prefix is "" as we are at the root
        self._set_field_value(tax_statement, 'totalGrossRevenueA', self.total_gross_revenue_a, "")
        self._set_field_value(tax_statement, 'totalGrossRevenueB', self.total_gross_revenue_b, "")
        self._set_field_value(tax_statement, 'totalWithHoldingTaxClaim', self.total_withholding_tax_claim, "")
        
        # Set/Verify the DA1/USA totals directly since they're excluded fields
        if self.mode == CalculationMode.FILL or self.mode == CalculationMode.OVERWRITE:
            # In FILL and OVERWRITE modes we set the values
            tax_statement.steuerwert_da1_usa = self.total_tax_value_da1
            tax_statement.brutto_da1_usa = self.total_gross_revenue_da1
            tax_statement.pauschale_da1 = self.total_flat_rate_tax_credit
            tax_statement.rueckbehalt_usa = self.total_additional_withholding_tax_usa
            # Add modified fields tracking for DA1/USA fields
            self.modified_fields.add("steuerwert_da1_usa")
            self.modified_fields.add("brutto_da1_usa")
            self.modified_fields.add("pauschale_da1")
            self.modified_fields.add("rueckbehalt_usa")
        elif self.mode == CalculationMode.VERIFY:
            # In VERIFY mode we compare the values
            if not self._compare_values(self.total_tax_value_da1, tax_statement.steuerwert_da1_usa):
                self.errors.append(CalculationError("steuerwert_da1_usa", self.total_tax_value_da1, tax_statement.steuerwert_da1_usa))
            if not self._compare_values(self.total_gross_revenue_da1, tax_statement.brutto_da1_usa):
                self.errors.append(CalculationError("brutto_da1_usa", self.total_gross_revenue_da1, tax_statement.brutto_da1_usa))
            if not self._compare_values(self.total_flat_rate_tax_credit, tax_statement.pauschale_da1):
                self.errors.append(CalculationError("pauschale_da1", self.total_flat_rate_tax_credit, tax_statement.pauschale_da1))
            if not self._compare_values(self.total_additional_withholding_tax_usa, tax_statement.rueckbehalt_usa):
                self.errors.append(CalculationError("rueckbehalt_usa", self.total_additional_withholding_tax_usa, tax_statement.rueckbehalt_usa))

    # Note: _handle_ListOf... and _handle_Depot methods are removed as they are no longer needed
    # The base class visitor pattern won't call them because we override _process_tax_statement

    def _handle_Security(self, security: Security, path_prefix: str) -> None: # Renamed from _process_security
        """
        Process a security to accumulate its contribution to the totals.
        
        Args:
            security: The security to process
            path_prefix: The path to this model from the root
        """
        is_usa = security.country == "US"
        
        # Add tax value if present
        if security.taxValue and security.taxValue.value is not None:
            self.total_tax_value += security.taxValue.value
            if is_usa:
                self.total_tax_value_da1 += security.taxValue.value # Accumulate US tax value
        
        # Process payments
        if security.payment:
            for payment in security.payment:
                # Process gross revenue A
                if payment.grossRevenueA is not None:
                    self.total_gross_revenue_a += payment.grossRevenueA
                    if is_usa: # Check if security is US for DA-1
                         self.total_gross_revenue_da1 += payment.grossRevenueA
                
                # Process gross revenue B
                if payment.grossRevenueB is not None:
                    self.total_gross_revenue_b += payment.grossRevenueB
                
                # Process withholding tax claim
                if payment.withHoldingTaxClaim is not None:
                    self.total_withholding_tax_claim += payment.withHoldingTaxClaim
                
                # Process flat rate tax credit (lumpSumTaxCreditAmount)
                if payment.lumpSumTaxCreditAmount is not None:
                    self.total_flat_rate_tax_credit += payment.lumpSumTaxCreditAmount
                
                # Process additional withholding tax USA
                if is_usa and payment.additionalWithHoldingTaxUSA is not None:
                    self.total_additional_withholding_tax_usa += payment.additionalWithHoldingTaxUSA
    
    def _handle_BankAccount(self, bank_account: BankAccount, path_prefix: str) -> None: # Renamed from _process_bank_account
        """
        Process a bank account to accumulate its contribution to the totals.
        
        Args:
            bank_account: The bank account to process
            path_prefix: The path to this model from the root
        """
        # Add tax value if present
        if bank_account.taxValue and bank_account.taxValue.value is not None:
            self.total_tax_value += bank_account.taxValue.value
        
        # Process payments
        if bank_account.payment:
            for payment in bank_account.payment:
                # Process gross revenue A
                if payment.grossRevenueA is not None:
                    self.total_gross_revenue_a += payment.grossRevenueA
                
                # Process gross revenue B
                if payment.grossRevenueB is not None:
                    self.total_gross_revenue_b += payment.grossRevenueB
                
                # Process withholding tax claim
                if payment.withHoldingTaxClaim is not None:
                    self.total_withholding_tax_claim += payment.withHoldingTaxClaim
    
    def _handle_LiabilityAccount(self, liability: LiabilityAccount, path_prefix: str) -> None:
        """
        Process a liability account to accumulate its contribution to the totals.
        
        Args:
            liability: The liability account to process
            path_prefix: The path to this model from the root
        """
        # Subtract liability tax values from the total (they represent negative amounts)
        if liability.taxValue and liability.taxValue.value is not None:
            self.total_tax_value -= liability.taxValue.value  # The value is positive in the XML but represents a liability
        
        # Process payments
        if liability.payment:
            for payment in liability.payment:
                # Liability payments only contribute to grossRevenueB (debt interest)
                if payment.grossRevenueB is not None:
                    self.total_gross_revenue_b += payment.grossRevenueB
    
    def _handle_Expense(self, expense: Expense, path_prefix: str) -> None: # Renamed from _process_expense
        """
        Process an expense. Currently does nothing for total calculations.
        
        Args:
            expense: The expense to process
            path_prefix: The path to this model from the root
        """
        # Expenses typically don't contribute to the totals calculated here,
        # but could be included in future calculations if needed
        pass
