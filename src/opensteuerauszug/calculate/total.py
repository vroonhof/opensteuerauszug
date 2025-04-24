from decimal import Decimal
from typing import List, Optional, Dict, Any, cast

from ..model.ech0196 import (
    TaxStatement, Security, BankAccount, LiabilityAccount, Expense,
    ListOfSecurities, Depot, ListOfBankAccounts, ListOfLiabilities, ListOfExpenses
)
from .base import BaseCalculator, CalculationMode

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
    
    def _handle_TaxStatement(self, tax_statement: TaxStatement, path_prefix: str) -> None:
        """
        Process the tax statement to calculate and verify total values.
        Delegates processing to child handlers and then sets/verifies totals.
        
        Args:
            tax_statement: The tax statement to process
            path_prefix: The path to this model from the root
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
        
        # Recurse into child elements using _process_model
        if tax_statement.listOfSecurities:
            self._process_model(tax_statement.listOfSecurities, f"{path_prefix}.listOfSecurities")
        if tax_statement.listOfBankAccounts:
            self._process_model(tax_statement.listOfBankAccounts, f"{path_prefix}.listOfBankAccounts")
        if tax_statement.listOfLiabilities:
            self._process_model(tax_statement.listOfLiabilities, f"{path_prefix}.listOfLiabilities")
        if tax_statement.listOfExpenses:
            self._process_model(tax_statement.listOfExpenses, f"{path_prefix}.listOfExpenses")
        
        # Set the regular totals
        self._set_field_value(tax_statement, 'totalTaxValue', self.total_tax_value, path_prefix)
        self._set_field_value(tax_statement, 'totalGrossRevenueA', self.total_gross_revenue_a, path_prefix)
        self._set_field_value(tax_statement, 'totalGrossRevenueB', self.total_gross_revenue_b, path_prefix)
        self._set_field_value(tax_statement, 'totalWithHoldingTaxClaim', self.total_withholding_tax_claim, path_prefix)
        
        # Set the DA1/USA totals directly since they're excluded fields
        if self.mode == CalculationMode.FILL or self.mode == CalculationMode.OVERWRITE:
            # In FILL and OVERWRITE modes we set the values
            tax_statement.steuerwert_da1_usa = self.total_tax_value_da1
            tax_statement.brutto_da1_usa = self.total_gross_revenue_da1
            tax_statement.pauschale_da1 = self.total_flat_rate_tax_credit
            tax_statement.rueckbehalt_usa = self.total_additional_withholding_tax_usa
        elif self.mode == CalculationMode.VERIFY:
            # In VERIFY mode we compare the values
            if tax_statement.steuerwert_da1_usa != self.total_tax_value_da1:
                self.errors.append(self._create_error("steuerwert_da1_usa", self.total_tax_value_da1, tax_statement.steuerwert_da1_usa))
            if tax_statement.brutto_da1_usa != self.total_gross_revenue_da1:
                self.errors.append(self._create_error("brutto_da1_usa", self.total_gross_revenue_da1, tax_statement.brutto_da1_usa))
            if tax_statement.pauschale_da1 != self.total_flat_rate_tax_credit:
                self.errors.append(self._create_error("pauschale_da1", self.total_flat_rate_tax_credit, tax_statement.pauschale_da1))
            if tax_statement.rueckbehalt_usa != self.total_additional_withholding_tax_usa:
                self.errors.append(self._create_error("rueckbehalt_usa", self.total_additional_withholding_tax_usa, tax_statement.rueckbehalt_usa))

    def _handle_ListOfSecurities(self, list_of_securities: ListOfSecurities, path_prefix: str) -> None:
        if list_of_securities.depot:
            for i, depot in enumerate(list_of_securities.depot):
                self._process_model(depot, f"{path_prefix}.depot[{i}]")

    def _handle_Depot(self, depot: Depot, path_prefix: str) -> None:
        if depot.security:
            for i, security in enumerate(depot.security):
                self._process_model(security, f"{path_prefix}.security[{i}]")

    def _handle_ListOfBankAccounts(self, list_of_bank_accounts: ListOfBankAccounts, path_prefix: str) -> None:
        if list_of_bank_accounts.bankAccount:
            for i, account in enumerate(list_of_bank_accounts.bankAccount):
                self._process_model(account, f"{path_prefix}.bankAccount[{i}]")

    def _handle_ListOfLiabilities(self, list_of_liabilities: ListOfLiabilities, path_prefix: str) -> None:
        if list_of_liabilities.liabilityAccount:
            for i, account in enumerate(list_of_liabilities.liabilityAccount):
                self._process_model(account, f"{path_prefix}.liabilityAccount[{i}]")

    def _handle_ListOfExpenses(self, list_of_expenses: ListOfExpenses, path_prefix: str) -> None:
        if list_of_expenses.expense:
            for i, expense in enumerate(list_of_expenses.expense):
                self._process_model(expense, f"{path_prefix}.expense[{i}]")

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
