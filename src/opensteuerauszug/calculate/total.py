from decimal import Decimal
from typing import List, Optional, Dict, Any, cast

from ..core.security import determine_security_type
from ..model.ech0196 import (
    TaxStatement, Security, BankAccount, LiabilityAccount, Expense,
    ListOfSecurities, Depot, ListOfBankAccounts, ListOfLiabilities, ListOfExpenses
)
from .base import BaseCalculator, CalculationMode, CalculationError
from ..util import round_accounting

class TotalCalculator(BaseCalculator):
    """
    Calculator that computes and verifies the total values at the top level of the tax statement.
    """
    
    def __init__(self, mode: CalculationMode = CalculationMode.FILL,
                 round_sub_total: bool = True) -> None:
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
        self.round_sub_total = round_sub_total
    
    def _round_sub_total(self, value: Decimal) -> Decimal:
        """Round a sub-total value according to the current rounding strategy."""
        if self.round_sub_total:
            return round_accounting(value)
        return value
    
    def _round_and_set_field(self, model: Any, field_name: str, value: Decimal, path: str) -> None:
        """Round a value and set it on a model field."""
        rounded_value = round_accounting(value)
        self._set_field_value(model, field_name, rounded_value, path)
    
    def _process_tax_statement(self, tax_statement: TaxStatement) -> None:
        # Reset global accumulators
        self.total_tax_value = Decimal('0')
        self.total_gross_revenue_a = Decimal('0')
        self.total_gross_revenue_b = Decimal('0')
        self.total_withholding_tax_claim = Decimal('0')
        self.total_gross_revenue_da1 = Decimal('0')
        self.total_tax_value_da1 = Decimal('0')
        self.total_tax_value_a_sv = Decimal('0')
        self.total_tax_value_b_sv = Decimal('0')
        self.total_gross_revenue_a_sv = Decimal('0')
        self.total_gross_revenue_b_sv = Decimal('0')
        self.total_tax_value_a_summary = Decimal('0')
        self.total_tax_value_b_summary = Decimal('0')
        self.total_gross_revenue_a_summary = Decimal('0')
        self.total_gross_revenue_b_summary = Decimal('0')
        self.total_flat_rate_tax_credit = Decimal('0')
        self.total_additional_withholding_tax_usa = Decimal('0')

        # 1. Process Securities
        if tax_statement.listOfSecurities:
            list_tax_value = Decimal('0')
            list_revenue_a = Decimal('0')
            list_revenue_b = Decimal('0')
            list_withholding = Decimal('0')
            list_lump_sum_tax_credit = Decimal('0')
            list_additional_withholding_tax_usa = Decimal('0')
            list_non_recoverable_tax = Decimal('0')
            
            # sv/summary/da1 specific list accumulators
            list_tax_value_a_sv = Decimal('0')
            list_tax_value_b_sv = Decimal('0')
            list_revenue_a_sv = Decimal('0')
            list_revenue_b_sv = Decimal('0')
            list_tax_value_da1 = Decimal('0')
            list_revenue_da1 = Decimal('0')

            if tax_statement.listOfSecurities.depot:
                for i, depot in enumerate(tax_statement.listOfSecurities.depot):
                    if depot.security:
                        for j, security in enumerate(depot.security):
                            path = f"listOfSecurities.depot[{i}].security[{j}]"
                            sec_tax_value = security.taxValue.value if security.taxValue and security.taxValue.value is not None else Decimal('0')
                            sec_revenue_a = Decimal('0')
                            sec_revenue_b = Decimal('0')
                            sec_withholding = Decimal('0')
                            sec_lump_sum_tax_credit = Decimal('0')
                            sec_additional_withholding_tax_usa = Decimal('0')
                            sec_non_recoverable_tax = Decimal('0')

                            if security.payment:
                                for payment in security.payment:
                                    if payment.grossRevenueA is not None: sec_revenue_a += payment.grossRevenueA
                                    if payment.grossRevenueB is not None: sec_revenue_b += payment.grossRevenueB
                                    if payment.withHoldingTaxClaim is not None: sec_withholding += payment.withHoldingTaxClaim
                                    if payment.lumpSumTaxCreditAmount is not None: sec_lump_sum_tax_credit += payment.lumpSumTaxCreditAmount
                                    if payment.additionalWithHoldingTaxUSA is not None: sec_additional_withholding_tax_usa += payment.additionalWithHoldingTaxUSA
                                    if payment.nonRecoverableTaxAmount is not None: sec_non_recoverable_tax += payment.nonRecoverableTaxAmount
                            
                                if self.mode in [CalculationMode.FILL, CalculationMode.OVERWRITE]:                                   
                                    security.totalGrossRevenueA = round_accounting(sec_revenue_a)
                                    security.totalGrossRevenueB = round_accounting(sec_revenue_b)
                                    security.totalWithHoldingTaxClaim = round_accounting(sec_withholding)
                                    security.totalNonRecoverableTax = round_accounting(sec_non_recoverable_tax)
                                    security.totalAdditionalWithHoldingTaxUSA = round_accounting(sec_additional_withholding_tax_usa)
                            
                            list_tax_value += sec_tax_value
                            list_revenue_a += sec_revenue_a
                            list_revenue_b += sec_revenue_b
                            list_withholding += sec_withholding
                            list_lump_sum_tax_credit += sec_lump_sum_tax_credit
                            list_additional_withholding_tax_usa += sec_additional_withholding_tax_usa
                            list_non_recoverable_tax += sec_non_recoverable_tax

                            security_type = determine_security_type(security)
                            if security_type == "DA1":
                                list_tax_value_da1 += sec_tax_value
                                list_revenue_da1 += sec_revenue_b
                            else:
                                if security_type == "A":
                                    list_tax_value_a_sv += sec_tax_value
                                else:
                                    list_tax_value_b_sv += sec_tax_value
                                list_revenue_a_sv += sec_revenue_a
                                list_revenue_b_sv += sec_revenue_b

            # Set list-level fields (rounded)
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalTaxValue', list_tax_value, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalGrossRevenueA', list_revenue_a, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalGrossRevenueB', list_revenue_b, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalWithHoldingTaxClaim', list_withholding, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalLumpSumTaxCredit', list_lump_sum_tax_credit, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalAdditionalWithHoldingTaxUSA', list_additional_withholding_tax_usa, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalNonRecoverableTax', list_non_recoverable_tax, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalGrossRevenueIUP', Decimal('0'), "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalGrossRevenueConversion', Decimal('0'), "listOfSecurities")

            # Accumulate global/internal totals from ROUNDED list subtotals
            self.total_tax_value += self._round_sub_total(list_tax_value)
            self.total_gross_revenue_a += self._round_sub_total(list_revenue_a)
            self.total_gross_revenue_b += self._round_sub_total(list_revenue_b)
            self.total_withholding_tax_claim += self._round_sub_total(list_withholding)

            self.total_tax_value_a_sv += self._round_sub_total(list_tax_value_a_sv)
            self.total_tax_value_b_sv += self._round_sub_total(list_tax_value_b_sv)
            self.total_gross_revenue_a_sv += self._round_sub_total(list_revenue_a_sv)
            self.total_gross_revenue_b_sv += self._round_sub_total(list_revenue_b_sv)

            # summary totals from securities (excluding DA1)
            self.total_tax_value_a_summary += self._round_sub_total(list_tax_value_a_sv)
            self.total_tax_value_b_summary += self._round_sub_total(list_tax_value_b_sv)
            self.total_gross_revenue_a_summary += self._round_sub_total(list_revenue_a_sv)
            self.total_gross_revenue_b_summary += self._round_sub_total(list_revenue_b_sv)

            self.total_tax_value_da1 += self._round_sub_total(list_tax_value_da1)
            self.total_gross_revenue_da1 += self._round_sub_total(list_revenue_da1)

        # 2. Process Bank Accounts
        if tax_statement.listOfBankAccounts and tax_statement.listOfBankAccounts.bankAccount:
            list_tax_value = Decimal('0')
            list_revenue_a = Decimal('0')
            list_revenue_b = Decimal('0')
            list_withholding = Decimal('0')
            
            # summary specific list accumulators for bank accounts
            list_tax_value_a_summary = Decimal('0')
            list_tax_value_b_summary = Decimal('0')
            list_revenue_a_summary = Decimal('0')
            list_revenue_b_summary = Decimal('0')

            for i, account in enumerate(tax_statement.listOfBankAccounts.bankAccount):
                path = f"listOfBankAccounts.bankAccount[{i}]"
                acc_tax_value = account.taxValue.value if account.taxValue and account.taxValue.value is not None else Decimal('0')
                acc_revenue_a = Decimal('0')
                acc_revenue_b = Decimal('0')
                acc_withholding = Decimal('0')

                if account.payment:
                    for payment in account.payment:
                        if payment.grossRevenueA is not None: acc_revenue_a += payment.grossRevenueA
                        if payment.grossRevenueB is not None: acc_revenue_b += payment.grossRevenueB
                        if payment.withHoldingTaxClaim is not None: acc_withholding += payment.withHoldingTaxClaim

                if self.mode in [CalculationMode.FILL, CalculationMode.OVERWRITE]:
                    self._round_and_set_field(account, 'totalTaxValue', acc_tax_value, path)
                    self._round_and_set_field(account, 'totalGrossRevenueA', acc_revenue_a, path)
                    self._round_and_set_field(account, 'totalGrossRevenueB', acc_revenue_b, path)
                    self._round_and_set_field(account, 'totalWithHoldingTaxClaim', acc_withholding, path)

                list_tax_value += acc_tax_value
                list_revenue_a += acc_revenue_a
                list_revenue_b += acc_revenue_b
                list_withholding += acc_withholding

                if acc_revenue_a > 0:
                    list_tax_value_a_summary += acc_tax_value
                else:
                    list_tax_value_b_summary += acc_tax_value
                list_revenue_a_summary += acc_revenue_a
                list_revenue_b_summary += acc_revenue_b

            self._round_and_set_field(tax_statement.listOfBankAccounts, 'totalTaxValue', list_tax_value, "listOfBankAccounts")
            self._round_and_set_field(tax_statement.listOfBankAccounts, 'totalGrossRevenueA', list_revenue_a, "listOfBankAccounts")
            self._round_and_set_field(tax_statement.listOfBankAccounts, 'totalGrossRevenueB', list_revenue_b, "listOfBankAccounts")
            self._round_and_set_field(tax_statement.listOfBankAccounts, 'totalWithHoldingTaxClaim', list_withholding, "listOfBankAccounts")

            # Accumulate global/summary totals from ROUNDED list subtotals
            self.total_tax_value += self._round_sub_total(list_tax_value)
            self.total_gross_revenue_a += self._round_sub_total(list_revenue_a)
            self.total_gross_revenue_b += self._round_sub_total(list_revenue_b)
            self.total_withholding_tax_claim += self._round_sub_total(list_withholding)

            self.total_tax_value_a_summary += self._round_sub_total(list_tax_value_a_summary)
            self.total_tax_value_b_summary += self._round_sub_total(list_tax_value_b_summary)
            self.total_gross_revenue_a_summary += self._round_sub_total(list_revenue_a_summary)
            self.total_gross_revenue_b_summary += self._round_sub_total(list_revenue_b_summary)

        # 3. Process Liabilities
        if tax_statement.listOfLiabilities and tax_statement.listOfLiabilities.liabilityAccount:
            list_tax_value = Decimal('0')
            list_revenue_b = Decimal('0')

            for i, account in enumerate(tax_statement.listOfLiabilities.liabilityAccount):
                path = f"listOfLiabilities.liabilityAccount[{i}]"
                liab_value = account.taxValue.value if account.taxValue and account.taxValue.value is not None else Decimal('0')
                liab_revenue_b = Decimal('0')
                if account.payment:
                    for payment in account.payment:
                        if payment.grossRevenueB is not None: liab_revenue_b += payment.grossRevenueB

                # Always set liability totals as they are required by the standard
                self._round_and_set_field(account, 'totalTaxValue', liab_value, path)
                self._round_and_set_field(account, 'totalGrossRevenueB', liab_revenue_b, path)

                list_tax_value += liab_value
                list_revenue_b += liab_revenue_b

            # Always set list-level liability totals
            self._round_and_set_field(tax_statement.listOfLiabilities, 'totalTaxValue', list_tax_value, "listOfLiabilities")
            self._round_and_set_field(tax_statement.listOfLiabilities, 'totalGrossRevenueB', list_revenue_b, "listOfLiabilities")

        # Set final global totals (already rounded when accumulated from list subtotals)
        self._round_and_set_field(tax_statement, 'totalTaxValue', self.total_tax_value, "") 
        self._round_and_set_field(tax_statement, 'totalGrossRevenueA', self.total_gross_revenue_a, "")
        self._round_and_set_field(tax_statement, 'totalGrossRevenueB', self.total_gross_revenue_b, "")
        self._round_and_set_field(tax_statement, 'totalWithHoldingTaxClaim', self.total_withholding_tax_claim, "")
        
        if self.mode in [CalculationMode.FILL, CalculationMode.OVERWRITE]:
            tax_statement.svTaxValueA = round_accounting(self.total_tax_value_a_sv)
            tax_statement.svTaxValueB = round_accounting(self.total_tax_value_b_sv)
            tax_statement.svGrossRevenueA = round_accounting(self.total_gross_revenue_a_sv)
            tax_statement.svGrossRevenueB = round_accounting(self.total_gross_revenue_b_sv)
            
            tax_statement.summaryTaxValueA = round_accounting(self.total_tax_value_a_summary)
            tax_statement.summaryTaxValueB = round_accounting(self.total_tax_value_b_summary)
            tax_statement.summaryGrossRevenueA = round_accounting(self.total_gross_revenue_a_summary)
            tax_statement.summaryGrossRevenueB = round_accounting(self.total_gross_revenue_b_summary)
            tax_statement.steuerwert_ab = tax_statement.summaryTaxValueA + tax_statement.summaryTaxValueB

            tax_statement.da1TaxValue = round_accounting(self.total_tax_value_da1)
            tax_statement.da_GrossRevenue = round_accounting(self.total_gross_revenue_da1)
