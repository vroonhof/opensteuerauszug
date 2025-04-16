from decimal import Decimal
from typing import List, Optional, Dict, Any, cast

from ..model.ech0196 import TaxStatement, Security, BankAccount, LiabilityAccount, Expense
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
        
        Args:
            tax_statement: The tax statement to process
            path_prefix: The path to this model from the root
        """
        # Reset accumulators
        self.total_tax_value = Decimal('0')
        self.total_gross_revenue_a = Decimal('0')
        self.total_gross_revenue_b = Decimal('0')
        self.total_withholding_tax_claim = Decimal('0')
        self.total_gross_revenue_da1 = Decimal('0')
        self.total_tax_value_da1 = Decimal('0')
        self.total_flat_rate_tax_credit = Decimal('0')
        self.total_additional_withholding_tax_usa = Decimal('0')
        
        # Process all securities
        if tax_statement.listOfSecurities and tax_statement.listOfSecurities.security:
            for security in tax_statement.listOfSecurities.security:
                self._process_security(security)
        
        # Process all bank accounts
        if tax_statement.listOfBankAccounts and tax_statement.listOfBankAccounts.bankAccount:
            for bank_account in tax_statement.listOfBankAccounts.bankAccount:
                self._process_bank_account(bank_account)
        
        # Process all liabilities
        if tax_statement.listOfLiabilities and tax_statement.listOfLiabilities.liabilityAccount:
            for liability in tax_statement.listOfLiabilities.liabilityAccount:
                self._process_liability(liability)
        
        # Process all expenses
        if tax_statement.listOfExpenses and tax_statement.listOfExpenses.expense:
            for expense in tax_statement.listOfExpenses.expense:
                self._process_expense(expense)
        
        # Set or verify the calculated totals
        self._set_field_value(tax_statement, 'totalTaxValue', self.total_tax_value, path_prefix)
        self._set_field_value(tax_statement, 'totalGrossRevenueA', self.total_gross_revenue_a, path_prefix)
        self._set_field_value(tax_statement, 'totalGrossRevenueB', self.total_gross_revenue_b, path_prefix)
        self._set_field_value(tax_statement, 'totalWithHoldingTaxClaim', self.total_withholding_tax_claim, path_prefix)
        self._set_field_value(tax_statement, 'totalGrossRevenueDA1', self.total_gross_revenue_da1, path_prefix)
        self._set_field_value(tax_statement, 'totalTaxValueDA1', self.total_tax_value_da1, path_prefix)
        self._set_field_value(tax_statement, 'totalFlatRateTaxCredit', self.total_flat_rate_tax_credit, path_prefix)
        self._set_field_value(tax_statement, 'totalAdditionalWithHoldingTaxUSA', self.total_additional_withholding_tax_usa, path_prefix)
    
    def _process_security(self, security: Security) -> None:
        """
        Process a security to extract its contribution to the totals.
        
        Args:
            security: The security to process
        """
        # Add tax value if present
        if security.taxValue and security.taxValue.value is not None:
            self.total_tax_value += security.taxValue.value
        
        # Process payments
        if security.payment:
            for payment in security.payment:
                # TODO: Implement logic to determine if payment is type A, B, or DA-1
                # For now, use placeholder logic based on available fields
                
                # Process gross revenue A
                if payment.grossRevenueA is not None:
                    self.total_gross_revenue_a += payment.grossRevenueA
                
                # Process gross revenue B
                if payment.grossRevenueB is not None:
                    self.total_gross_revenue_b += payment.grossRevenueB
                
                # Process withholding tax claim
                if payment.withHoldingTaxClaim is not None:
                    self.total_withholding_tax_claim += payment.withHoldingTaxClaim
                
                # Process DA-1 related fields (USA)
                # TODO: Implement proper logic to identify DA-1 payments
                if payment.country == "US" and payment.grossRevenueA is not None:
                    # This is a placeholder - actual logic would be more complex
                    self.total_gross_revenue_da1 += payment.grossRevenueA
                
                # Process flat rate tax credit
                if payment.flatRateTaxCredit is not None:
                    self.total_flat_rate_tax_credit += payment.flatRateTaxCredit
                
                # Process additional withholding tax USA
                if payment.country == "US" and payment.additionalWithHoldingTax is not None:
                    self.total_additional_withholding_tax_usa += payment.additionalWithHoldingTax
    
    def _process_bank_account(self, bank_account: BankAccount) -> None:
        """
        Process a bank account to extract its contribution to the totals.
        
        Args:
            bank_account: The bank account to process
        """
        # Add tax value if present
        if bank_account.taxValue and bank_account.taxValue.value is not None:
            self.total_tax_value += bank_account.taxValue.value
        
        # Process payments
        if bank_account.payment:
            for payment in bank_account.payment:
                # TODO: Implement logic to determine if payment is type A, B, or DA-1
                # For now, use placeholder logic based on available fields
                
                # Process gross revenue A
                if payment.grossRevenueA is not None:
                    self.total_gross_revenue_a += payment.grossRevenueA
                
                # Process gross revenue B
                if payment.grossRevenueB is not None:
                    self.total_gross_revenue_b += payment.grossRevenueB
                
                # Process withholding tax claim
                if payment.withHoldingTaxClaim is not None:
                    self.total_withholding_tax_claim += payment.withHoldingTaxClaim
    
    def _process_liability(self, liability: LiabilityAccount) -> None:
        """
        Process a liability account to extract its contribution to the totals.
        
        Args:
            liability: The liability account to process
        """
        # Add tax value if present (negative for liabilities)
        if liability.taxValue and liability.taxValue.value is not None:
            # Liabilities are typically negative values in the total
            self.total_tax_value -= liability.taxValue.value
        
        # Process payments
        if liability.payment:
            for payment in liability.payment:
                # TODO: Implement logic to determine if payment is type A, B, or DA-1
                # For now, use placeholder logic based on available fields
                
                # Process gross revenue A
                if payment.grossRevenueA is not None:
                    self.total_gross_revenue_a += payment.grossRevenueA
                
                # Process gross revenue B
                if payment.grossRevenueB is not None:
                    self.total_gross_revenue_b += payment.grossRevenueB
                
                # Process withholding tax claim
                if payment.withHoldingTaxClaim is not None:
                    self.total_withholding_tax_claim += payment.withHoldingTaxClaim
    
    def _process_expense(self, expense: Expense) -> None:
        """
        Process an expense to extract its contribution to the totals.
        
        Args:
            expense: The expense to process
        """
        # Expenses typically don't contribute to the totals calculated here,
        # but could be included in future calculations if needed
        pass
