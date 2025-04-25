from decimal import Decimal
from typing import List, Optional, Dict, Any, cast

from ..model.ech0196 import (
    TaxStatement, Security, BankAccount, LiabilityAccount, Expense,
    ListOfSecurities, Depot, ListOfBankAccounts, ListOfLiabilities, ListOfExpenses
)
from .base import BaseCalculator, CalculationMode, CalculationError
from ..util import round_accounting

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
        """
        Round a sub-total value according to the current rounding strategy.
        
        Args:
            value: The value to round
            
        Returns:
            The rounded value
        """
        # Rounding subtotals is what I think the spec says but at least some
        # real world example round only the final values.
        if self.round_sub_total:
            # If round_sub_total is True, round the value
            return round_accounting(value)
        else:
            # Sadly this breaks composibility has the totals cannot be recomputed
            # from the stored values.
            return value
    
    def _round_and_set_field(self, model: Any, field_name: str, value: Decimal, path: str) -> None:
        """
        Round a value and set it on a model field.
        
        Args:
            model: The model containing the field
            field_name: The name of the field to set
            value: The value to round and set
            path: The path for error reporting
        """
        # all stored values are rounded. They may have been rounded before, but
        # that is OK as rounding is idempotent.
        rounded_value = round_accounting(value)
        self._set_field_value(model, field_name, rounded_value, path)
    
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
        if tax_statement.listOfSecurities:
            list_tax_value = Decimal('0')
            list_revenue_a = Decimal('0')
            list_revenue_b = Decimal('0')
            list_withholding = Decimal('0')

            # Process securities in depots
            if tax_statement.listOfSecurities.depot:
                for i, depot in enumerate(tax_statement.listOfSecurities.depot):
                    depot_tax_value = Decimal('0')
                    depot_revenue_a = Decimal('0')
                    depot_revenue_b = Decimal('0')
                    depot_withholding = Decimal('0')

                    if depot.security:
                        for j, security in enumerate(depot.security):
                            path = f"listOfSecurities.depot[{i}].security[{j}]"

                            # Calculate totals for this security
                            sec_tax_value = Decimal('0')
                            sec_revenue_a = Decimal('0')
                            sec_revenue_b = Decimal('0')
                            sec_withholding = Decimal('0')

                            if security.taxValue and security.taxValue.value is not None:
                                sec_tax_value = security.taxValue.value

                            is_usa = security.country == "US"

                            if security.payment:
                                for payment in security.payment:
                                    if payment.grossRevenueA is not None:
                                        sec_revenue_a += payment.grossRevenueA
                                        if is_usa:
                                            self.total_gross_revenue_da1 += payment.grossRevenueA

                                    if payment.grossRevenueB is not None:
                                        sec_revenue_b += payment.grossRevenueB

                                    if payment.withHoldingTaxClaim is not None:
                                        sec_withholding += payment.withHoldingTaxClaim

                                    if payment.lumpSumTaxCreditAmount is not None:
                                        self.total_flat_rate_tax_credit += payment.lumpSumTaxCreditAmount

                                    if is_usa and payment.additionalWithHoldingTaxUSA is not None:
                                        self.total_additional_withholding_tax_usa += payment.additionalWithHoldingTaxUSA

                            # Accumulate depot totals using rounded security totals
                            depot_tax_value += sec_tax_value
                            depot_revenue_a += sec_revenue_a
                            depot_revenue_b += sec_revenue_b
                            depot_withholding += sec_withholding

                            # Accumulate global USA-specific totals (will be rounded at the end)
                            if is_usa:
                                self.total_tax_value_da1 += sec_tax_value

                    # Accumulate list totals from depot totals
                    list_tax_value += depot_tax_value
                    list_revenue_a += depot_revenue_a
                    list_revenue_b += depot_revenue_b
                    list_withholding += depot_withholding

            # Round list totals before setting them
            list_tax_value_rounded = self._round_sub_total(list_tax_value)
            list_revenue_a_rounded = self._round_sub_total(list_revenue_a)
            list_revenue_b_rounded = self._round_sub_total(list_revenue_b)
            list_withholding_rounded = self._round_sub_total(list_withholding)

            # Set list level totals for securities
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalTaxValue', list_tax_value_rounded, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalGrossRevenueA', list_revenue_a_rounded, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalGrossRevenueB', list_revenue_b_rounded, "listOfSecurities")
            self._round_and_set_field(tax_statement.listOfSecurities, 'totalWithHoldingTaxClaim', list_withholding_rounded, "listOfSecurities")

            # Accumulate global totals from list totals (use rounded values)
            self.total_tax_value += list_tax_value_rounded
            self.total_gross_revenue_a += list_revenue_a_rounded
            self.total_gross_revenue_b += list_revenue_b_rounded
            self.total_withholding_tax_claim += list_withholding_rounded

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
                account_withholding = Decimal('0')

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

                # Round account totals before setting them
                account_tax_value_rounded = self._round_sub_total(account_tax_value)
                account_revenue_a_rounded = self._round_sub_total(account_revenue_a)
                account_revenue_b_rounded = self._round_sub_total(account_revenue_b)
                account_withholding_rounded = self._round_sub_total(account_withholding)

                # Set individual account totals (rounded)
                self._round_and_set_field(account, 'totalTaxValue', account_tax_value_rounded, path)
                self._round_and_set_field(account, 'totalGrossRevenueA', account_revenue_a_rounded, path)
                self._round_and_set_field(account, 'totalGrossRevenueB', account_revenue_b_rounded, path)
                self._round_and_set_field(account, 'totalWithHoldingTaxClaim', account_withholding_rounded, path)

                # Accumulate list totals (use rounded values)
                list_tax_value += account_tax_value_rounded
                list_revenue_a += account_revenue_a_rounded
                list_revenue_b += account_revenue_b_rounded
                list_withholding += account_withholding_rounded

            # Round list totals before setting them
            list_tax_value_rounded = self._round_sub_total(list_tax_value)
            list_revenue_a_rounded = self._round_sub_total(list_revenue_a)
            list_revenue_b_rounded = self._round_sub_total(list_revenue_b)
            list_withholding_rounded = self._round_sub_total(list_withholding)

            # Set list level totals (rounded)
            self._round_and_set_field(tax_statement.listOfBankAccounts, 'totalTaxValue', list_tax_value_rounded, "listOfBankAccounts")
            self._round_and_set_field(tax_statement.listOfBankAccounts, 'totalGrossRevenueA', list_revenue_a_rounded, "listOfBankAccounts")
            self._round_and_set_field(tax_statement.listOfBankAccounts, 'totalGrossRevenueB', list_revenue_b_rounded, "listOfBankAccounts")
            self._round_and_set_field(tax_statement.listOfBankAccounts, 'totalWithHoldingTaxClaim', list_withholding_rounded, "listOfBankAccounts")

            # Add to global totals (use rounded values)
            self.total_tax_value += list_tax_value_rounded
            self.total_gross_revenue_a += list_revenue_a_rounded
            self.total_gross_revenue_b += list_revenue_b_rounded
            self.total_withholding_tax_claim += list_withholding_rounded

        if tax_statement.listOfLiabilities and tax_statement.listOfLiabilities.liabilityAccount:
            liability_list_tax_value = Decimal('0')
            liability_list_revenue_b = Decimal('0')

            for i, account in enumerate(tax_statement.listOfLiabilities.liabilityAccount):
                path = f"listOfLiabilities.liabilityAccount[{i}]"

                liability_value = Decimal('0') # Initialize liability_value
                if account.taxValue and account.taxValue.value is not None:
                    liability_value = account.taxValue.value
                
                # Process payments for gross revenue B
                account_revenue_b = Decimal('0')
                if account.payment:
                    for payment in account.payment:
                        if payment.grossRevenueB is not None:
                            account_revenue_b += payment.grossRevenueB

                # Round account totals before setting them
                liability_value_rounded = self._round_sub_total(liability_value)
                account_revenue_b_rounded = self._round_sub_total(account_revenue_b)

                # Set account totals (rounded)
                self._round_and_set_field(account, 'totalTaxValue', liability_value_rounded, path)
                self._round_and_set_field(account, 'totalGrossRevenueB', account_revenue_b_rounded, path)

                # Accumulate list totals (use rounded values)  
                liability_list_tax_value += liability_value_rounded
                liability_list_revenue_b += account_revenue_b_rounded

            # Round list totals before setting them
            liability_list_tax_value_rounded = self._round_sub_total(liability_list_tax_value)
            liability_list_revenue_b_rounded = self._round_sub_total(liability_list_revenue_b)

            # Set list level totals for liabilities (rounded)
            self._round_and_set_field(tax_statement.listOfLiabilities, 'totalTaxValue', liability_list_tax_value_rounded, "listOfLiabilities")
            self._round_and_set_field(tax_statement.listOfLiabilities, 'totalGrossRevenueB', liability_list_revenue_b_rounded, "listOfLiabilities")

            # Note: Liabilities are handled seperate by the tax accounting, they are 
            # NOT subtracted from the report total value and income statments.
            pass

        if tax_statement.listOfExpenses and tax_statement.listOfExpenses.expense:
             # Expenses currently don't contribute to these totals
             pass

        # Round final global totals before setting them
        final_tax_value = self._round_sub_total(self.total_tax_value)
        final_gross_revenue_a = self._round_sub_total(self.total_gross_revenue_a)
        final_gross_revenue_b = self._round_sub_total(self.total_gross_revenue_b)
        final_withholding_tax_claim = self._round_sub_total(self.total_withholding_tax_claim)
        final_tax_value_da1 = self._round_sub_total(self.total_tax_value_da1)
        final_gross_revenue_da1 = self._round_sub_total(self.total_gross_revenue_da1)
        final_flat_rate_tax_credit = self._round_sub_total(self.total_flat_rate_tax_credit)
        final_additional_withholding_tax_usa = self._round_sub_total(self.total_additional_withholding_tax_usa)

        # Set the regular totals (rounded)
        self._round_and_set_field(tax_statement, 'totalTaxValue', final_tax_value, "") # Path prefix is "" as we are at the root
        self._round_and_set_field(tax_statement, 'totalGrossRevenueA', final_gross_revenue_a, "")
        self._round_and_set_field(tax_statement, 'totalGrossRevenueB', final_gross_revenue_b, "")
        self._round_and_set_field(tax_statement, 'totalWithHoldingTaxClaim', final_withholding_tax_claim, "")
        
        # Set/Verify the DA1/USA totals directly since they're excluded fields
        if self.mode == CalculationMode.FILL or self.mode == CalculationMode.OVERWRITE:
            # In FILL and OVERWRITE modes we set the values (rounded)
            tax_statement.steuerwert_da1_usa = final_tax_value_da1
            tax_statement.brutto_da1_usa = final_gross_revenue_da1
            tax_statement.pauschale_da1 = final_flat_rate_tax_credit
            tax_statement.rueckbehalt_usa = final_additional_withholding_tax_usa
            # Add modified fields tracking for DA1/USA fields
            self.modified_fields.add("steuerwert_da1_usa")
            self.modified_fields.add("brutto_da1_usa")
            self.modified_fields.add("pauschale_da1")
            self.modified_fields.add("rueckbehalt_usa")
        elif self.mode == CalculationMode.VERIFY:
            # In VERIFY mode we compare the values
            if not self._compare_values(final_tax_value_da1, tax_statement.steuerwert_da1_usa):
                self.errors.append(CalculationError("steuerwert_da1_usa", final_tax_value_da1, tax_statement.steuerwert_da1_usa))
            if not self._compare_values(final_gross_revenue_da1, tax_statement.brutto_da1_usa):
                self.errors.append(CalculationError("brutto_da1_usa", final_gross_revenue_da1, tax_statement.brutto_da1_usa))
            if not self._compare_values(final_flat_rate_tax_credit, tax_statement.pauschale_da1):
                self.errors.append(CalculationError("pauschale_da1", final_flat_rate_tax_credit, tax_statement.pauschale_da1))
            if not self._compare_values(final_additional_withholding_tax_usa, tax_statement.rueckbehalt_usa):
                self.errors.append(CalculationError("rueckbehalt_usa", final_additional_withholding_tax_usa, tax_statement.rueckbehalt_usa))
