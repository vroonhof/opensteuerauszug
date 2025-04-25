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

                            # Set individual security totals
                            self._set_field_value(security, 'totalTaxValue', sec_tax_value, path)
                            self._set_field_value(security, 'totalGrossRevenueA', sec_revenue_a, path)
                            self._set_field_value(security, 'totalGrossRevenueB', sec_revenue_b, path)
                            self._set_field_value(security, 'totalWithHoldingTaxClaim', sec_withholding, path)

                            # Accumulate depot totals
                            depot_tax_value += sec_tax_value
                            depot_revenue_a += sec_revenue_a
                            depot_revenue_b += sec_revenue_b
                            depot_withholding += sec_withholding

                            # Accumulate global totals (USA-specific handling already done above)
                            self.total_tax_value += sec_tax_value
                            self.total_gross_revenue_a += sec_revenue_a
                            self.total_gross_revenue_b += sec_revenue_b
                            self.total_withholding_tax_claim += sec_withholding

                            if is_usa:
                                self.total_tax_value_da1 += sec_tax_value

                    # Set depot level totals
                    depot_path = f"listOfSecurities.depot[{i}]"
                    self._set_field_value(depot, 'totalTaxValue', depot_tax_value, depot_path)
                    self._set_field_value(depot, 'totalGrossRevenueA', depot_revenue_a, depot_path)
                    self._set_field_value(depot, 'totalGrossRevenueB', depot_revenue_b, depot_path)
                    self._set_field_value(depot, 'totalWithHoldingTaxClaim', depot_withholding, depot_path)

                    # Accumulate list totals from depot totals
                    list_tax_value += depot_tax_value
                    list_revenue_a += depot_revenue_a
                    list_revenue_b += depot_revenue_b
                    list_withholding += depot_withholding

            # Set list level totals for securities (now only based on depot totals)
            self._set_field_value(tax_statement.listOfSecurities, 'totalTaxValue', list_tax_value, "listOfSecurities")
            self._set_field_value(tax_statement.listOfSecurities, 'totalGrossRevenueA', list_revenue_a, "listOfSecurities")
            self._set_field_value(tax_statement.listOfSecurities, 'totalGrossRevenueB', list_revenue_b, "listOfSecurities")
            self._set_field_value(tax_statement.listOfSecurities, 'totalWithHoldingTaxClaim', list_withholding, "listOfSecurities")

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

                # Set individual account totals
                self._set_field_value(account, 'totalTaxValue', account_tax_value, path)
                self._set_field_value(account, 'totalGrossRevenueA', account_revenue_a, path)
                self._set_field_value(account, 'totalGrossRevenueB', account_revenue_b, path)
                self._set_field_value(account, 'totalWithHoldingTaxClaim', account_withholding, path)

                # Accumulate list totals
                list_tax_value += account_tax_value
                list_revenue_a += account_revenue_a
                list_revenue_b += account_revenue_b
                list_withholding += account_withholding

                # Add to overall totals
                self.total_tax_value += account_tax_value
                self.total_gross_revenue_a += account_revenue_a
                self.total_gross_revenue_b += account_revenue_b
                self.total_withholding_tax_claim += account_withholding

            # Set list level totals
            self._set_field_value(tax_statement.listOfBankAccounts, 'totalTaxValue', list_tax_value, "listOfBankAccounts")
            self._set_field_value(tax_statement.listOfBankAccounts, 'totalGrossRevenueA', list_revenue_a, "listOfBankAccounts")
            self._set_field_value(tax_statement.listOfBankAccounts, 'totalGrossRevenueB', list_revenue_b, "listOfBankAccounts")
            self._set_field_value(tax_statement.listOfBankAccounts, 'totalWithHoldingTaxClaim', list_withholding, "listOfBankAccounts")

        if tax_statement.listOfLiabilities and tax_statement.listOfLiabilities.liabilityAccount:
            liability_list_tax_value = Decimal('0')
            liability_list_revenue_b = Decimal('0')

            for i, account in enumerate(tax_statement.listOfLiabilities.liabilityAccount):
                path = f"listOfLiabilities.liabilityAccount[{i}]"

                liability_value = Decimal('0') # Initialize liability_value
                if account.taxValue and account.taxValue.value is not None:
                    liability_value = account.taxValue.value
                    liability_list_tax_value += liability_value  # Add to list total (positive)
                    self.total_tax_value -= liability_value      # Subtract from overall total (negative impact)

                # Process payments for gross revenue B
                account_revenue_b = Decimal('0')
                if account.payment:
                    for payment in account.payment:
                        if payment.grossRevenueB is not None:
                            account_revenue_b += payment.grossRevenueB
                            liability_list_revenue_b += payment.grossRevenueB  # Add to list total
                            self.total_gross_revenue_b += payment.grossRevenueB  # Add to overall total

                # Set account totals
                self._set_field_value(account, 'totalTaxValue', liability_value, path)
                self._set_field_value(account, 'totalGrossRevenueB', account_revenue_b, path)

            # Set list level totals for liabilities
            self._set_field_value(tax_statement.listOfLiabilities, 'totalTaxValue', liability_list_tax_value, "listOfLiabilities")
            self._set_field_value(tax_statement.listOfLiabilities, 'totalGrossRevenueB', liability_list_revenue_b, "listOfLiabilities")

        if tax_statement.listOfExpenses and tax_statement.listOfExpenses.expense:
             # Expenses currently don't contribute to these totals
             pass

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
