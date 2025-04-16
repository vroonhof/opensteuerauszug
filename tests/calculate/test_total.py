import os
import pytest
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional

from opensteuerauszug.calculate.base import CalculationMode, CalculationError
from opensteuerauszug.calculate.total import TotalCalculator
from opensteuerauszug.model.ech0196 import (
    TaxStatement, Security, BankAccount, LiabilityAccount, Expense,
    SecurityTaxValue, SecurityPayment, BankAccountTaxValue, BankAccountPayment,
    LiabilityAccountTaxValue, LiabilityAccountPayment, ListOfSecurities,
    ListOfBankAccounts, ListOfLiabilities, ListOfExpenses
)
from tests.utils.samples import get_sample_files

# Helper function to create a simple tax statement for testing
def create_test_tax_statement() -> TaxStatement:
    """Create a simple tax statement with some securities, bank accounts, and liabilities."""
    # Create a security with tax value and payments
    security1 = Security(
        valorNumber=123456,
        isin="CH0001234567",
        name="Test Security 1",
        taxValue=SecurityTaxValue(
            referenceDate="2023-12-31",
            quotationCurrency="CHF",
            quotation=Decimal("100.00"),
            quantity=Decimal("10"),
            exchangeRate=Decimal("1.0"),
            value=Decimal("1000.00")
        ),
        payment=[
            SecurityPayment(
                paymentDate="2023-06-30",
                name="Dividend",
                amountCurrency="CHF",
                amount=Decimal("50.00"),
                exchangeRate=Decimal("1.0"),
                grossRevenueA=Decimal("50.00"),
                grossRevenueB=Decimal("0.00"),
                withHoldingTaxClaim=Decimal("17.50")
            ),
            SecurityPayment(
                paymentDate="2023-12-31",
                name="Interest",
                amountCurrency="CHF",
                amount=Decimal("30.00"),
                exchangeRate=Decimal("1.0"),
                grossRevenueA=Decimal("0.00"),
                grossRevenueB=Decimal("30.00"),
                withHoldingTaxClaim=Decimal("10.50")
            )
        ]
    )
    
    # Create a bank account with tax value and payments
    bank_account1 = BankAccount(
        bankAccountNumber="123456789",
        bankAccountName="Test Account",
        taxValue=BankAccountTaxValue(
            referenceDate="2023-12-31",
            balanceCurrency="CHF",
            balance=Decimal("5000.00"),
            exchangeRate=Decimal("1.0"),
            value=Decimal("5000.00")
        ),
        payment=[
            BankAccountPayment(
                paymentDate="2023-06-30",
                name="Interest",
                amountCurrency="CHF",
                amount=Decimal("25.00"),
                exchangeRate=Decimal("1.0"),
                grossRevenueA=Decimal("25.00"),
                grossRevenueB=Decimal("0.00"),
                withHoldingTaxClaim=Decimal("8.75")
            )
        ]
    )
    
    # Create a liability with tax value
    liability1 = LiabilityAccount(
        liabilityAccountNumber="L123456",
        liabilityAccountName="Test Mortgage",
        category="MORTGAGE",
        taxValue=LiabilityAccountTaxValue(
            referenceDate="2023-12-31",
            balanceCurrency="CHF",
            balance=Decimal("200000.00"),
            exchangeRate=Decimal("1.0"),
            value=Decimal("200000.00")
        ),
        payment=[
            LiabilityAccountPayment(
                paymentDate="2023-06-30",
                name="Interest Payment",
                amountCurrency="CHF",
                amount=Decimal("2000.00"),
                exchangeRate=Decimal("1.0"),
                grossRevenueA=Decimal("0.00"),
                grossRevenueB=Decimal("2000.00"),
                withHoldingTaxClaim=Decimal("0.00")
            )
        ]
    )
    
    # Create a tax statement with the above components
    return TaxStatement(
        minorVersion=2,
        id="test-id-123",
        creationDate="2024-01-15T10:00:00",
        taxPeriod=2023,
        periodFrom="2023-01-01",
        periodTo="2023-12-31",
        canton="ZH",
        institution={"name": "Test Bank AG"},
        client=[{"clientNumber": "C1", "firstName": "Max", "lastName": "Muster", "salutation": "2"}],
        listOfSecurities=ListOfSecurities(security=[security1]),
        listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account1]),
        listOfLiabilities=ListOfLiabilities(liabilityAccount=[liability1]),
        # Leave totals empty for calculator to fill
    )

# Unit tests for TotalCalculator
class TestTotalCalculator:
    
    def test_calculate_fill_mode(self):
        """Test that the calculator correctly fills in missing total values."""
        # Create a tax statement with no totals
        tax_statement = create_test_tax_statement()
        
        # Expected values based on the test data
        expected_tax_value = Decimal("1000.00") + Decimal("5000.00") - Decimal("200000.00")
        expected_gross_revenue_a = Decimal("50.00") + Decimal("25.00") + Decimal("0.00")
        expected_gross_revenue_b = Decimal("30.00") + Decimal("0.00") + Decimal("2000.00")
        expected_withholding_tax_claim = Decimal("17.50") + Decimal("10.50") + Decimal("8.75") + Decimal("0.00")
        
        # Calculate in FILL mode
        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)
        
        # Check that totals were filled correctly
        assert result.totalTaxValue == expected_tax_value
        assert result.totalGrossRevenueA == expected_gross_revenue_a
        assert result.totalGrossRevenueB == expected_gross_revenue_b
        assert result.totalWithHoldingTaxClaim == expected_withholding_tax_claim
        
        # Check that the modified fields were tracked
        assert "totalTaxValue" in calculator.modified_fields
        assert "totalGrossRevenueA" in calculator.modified_fields
        assert "totalGrossRevenueB" in calculator.modified_fields
        assert "totalWithHoldingTaxClaim" in calculator.modified_fields
    
    def test_calculate_verify_mode_success(self):
        """Test that the calculator correctly verifies existing total values."""
        # Create a tax statement with correct totals
        tax_statement = create_test_tax_statement()
        tax_statement.totalTaxValue = Decimal("-194000.00")  # 1000 + 5000 - 200000
        tax_statement.totalGrossRevenueA = Decimal("75.00")  # 50 + 25
        tax_statement.totalGrossRevenueB = Decimal("2030.00")  # 30 + 2000
        tax_statement.totalWithHoldingTaxClaim = Decimal("36.75")  # 17.50 + 10.50 + 8.75
        
        # Calculate in VERIFY mode
        calculator = TotalCalculator(mode=CalculationMode.VERIFY)
        result = calculator.calculate(tax_statement)
        
        # No exception should be raised, and no fields should be modified
        assert len(calculator.modified_fields) == 0
        assert len(calculator.errors) == 0
    
    def test_calculate_verify_mode_failure(self):
        """Test that the calculator raises an error when verification fails."""
        # Create a tax statement with incorrect totals
        tax_statement = create_test_tax_statement()
        tax_statement.totalTaxValue = Decimal("-194000.00")  # Correct
        tax_statement.totalGrossRevenueA = Decimal("100.00")  # Incorrect (should be 75)
        tax_statement.totalGrossRevenueB = Decimal("2030.00")  # Correct
        tax_statement.totalWithHoldingTaxClaim = Decimal("36.75")  # Correct
        
        # Calculate in VERIFY mode
        calculator = TotalCalculator(mode=CalculationMode.VERIFY)
        
        # Should raise a CalculationError
        with pytest.raises(CalculationError) as excinfo:
            calculator.calculate(tax_statement)
        
        # Check the error details
        assert "totalGrossRevenueA" in str(excinfo.value)
        assert "expected 75.00" in str(excinfo.value).lower() or "expected 75" in str(excinfo.value).lower()
    
    def test_calculate_overwrite_mode(self):
        """Test that the calculator correctly overwrites existing total values."""
        # Create a tax statement with incorrect totals
        tax_statement = create_test_tax_statement()
        tax_statement.totalTaxValue = Decimal("0.00")  # Incorrect
        tax_statement.totalGrossRevenueA = Decimal("0.00")  # Incorrect
        tax_statement.totalGrossRevenueB = Decimal("0.00")  # Incorrect
        tax_statement.totalWithHoldingTaxClaim = Decimal("0.00")  # Incorrect
        
        # Expected values based on the test data
        expected_tax_value = Decimal("-194000.00")  # 1000 + 5000 - 200000
        expected_gross_revenue_a = Decimal("75.00")  # 50 + 25
        expected_gross_revenue_b = Decimal("2030.00")  # 30 + 2000
        expected_withholding_tax_claim = Decimal("36.75")  # 17.50 + 10.50 + 8.75
        
        # Calculate in OVERWRITE mode
        calculator = TotalCalculator(mode=CalculationMode.OVERWRITE)
        result = calculator.calculate(tax_statement)
        
        # Check that totals were overwritten correctly
        assert result.totalTaxValue == expected_tax_value
        assert result.totalGrossRevenueA == expected_gross_revenue_a
        assert result.totalGrossRevenueB == expected_gross_revenue_b
        assert result.totalWithHoldingTaxClaim == expected_withholding_tax_claim
        
        # Check that the modified fields were tracked
        assert "totalTaxValue" in calculator.modified_fields
        assert "totalGrossRevenueA" in calculator.modified_fields
        assert "totalGrossRevenueB" in calculator.modified_fields
        assert "totalWithHoldingTaxClaim" in calculator.modified_fields
    
    def test_usa_specific_calculations(self):
        """Test USA-specific calculations (DA-1)."""
        # Create a security with USA payments
        security_usa = Security(
            valorNumber=654321,
            isin="US0001234567",
            name="US Security",
            taxValue=SecurityTaxValue(
                referenceDate="2023-12-31",
                quotationCurrency="USD",
                quotation=Decimal("50.00"),
                quantity=Decimal("20"),
                exchangeRate=Decimal("0.9"),
                value=Decimal("900.00")
            ),
            payment=[
                SecurityPayment(
                    paymentDate="2023-06-30",
                    name="US Dividend",
                    country="US",
                    amountCurrency="USD",
                    amount=Decimal("100.00"),
                    exchangeRate=Decimal("0.9"),
                    grossRevenueA=Decimal("90.00"),
                    grossRevenueB=Decimal("0.00"),
                    withHoldingTaxClaim=Decimal("31.50"),
                    additionalWithHoldingTax=Decimal("15.00"),
                    flatRateTaxCredit=Decimal("5.00")
                )
            ]
        )
        
        # Create a tax statement with the USA security
        tax_statement = TaxStatement(
            minorVersion=2,
            id="test-id-usa",
            creationDate="2024-01-15T10:00:00",
            taxPeriod=2023,
            periodFrom="2023-01-01",
            periodTo="2023-12-31",
            canton="ZH",
            institution={"name": "Test Bank AG"},
            client=[{"clientNumber": "C1", "firstName": "Max", "lastName": "Muster", "salutation": "2"}],
            listOfSecurities=ListOfSecurities(security=[security_usa]),
            # Leave totals empty for calculator to fill
        )
        
        # Calculate in FILL mode
        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)
        
        # Check USA-specific totals
        assert result.totalGrossRevenueDA1 == Decimal("90.00")
        assert result.totalTaxValueDA1 == Decimal("900.00")
        assert result.totalFlatRateTaxCredit == Decimal("5.00")
        assert result.totalAdditionalWithHoldingTaxUSA == Decimal("15.00")
        
        # Check regular totals
        assert result.totalTaxValue == Decimal("900.00")
        assert result.totalGrossRevenueA == Decimal("90.00")
        assert result.totalGrossRevenueB == Decimal("0.00")
        assert result.totalWithHoldingTaxClaim == Decimal("31.50")

# Integration tests using real sample files
class TestTotalCalculatorIntegration:
    
    @pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
    def test_calculation_verify_with_samples(self, sample_file):
        """Test that calculations verify correctly against real sample files."""
        if not sample_file:
            pytest.skip("No sample files found")
        
        # Load the sample file
        tax_statement = TaxStatement.from_xml_file(sample_file)
        
        # First, calculate in FILL mode to ensure all totals are populated
        fill_calculator = TotalCalculator(mode=CalculationMode.FILL)
        filled_statement = fill_calculator.calculate(tax_statement)
        
        # Then verify the filled values
        verify_calculator = TotalCalculator(mode=CalculationMode.VERIFY)
        try:
            verify_calculator.calculate(filled_statement)
        except CalculationError as e:
            pytest.fail(f"Verification failed for {sample_file}: {e}")
    
    @pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
    def test_calculation_consistency(self, sample_file):
        """Test that calculations are consistent when applied multiple times."""
        if not sample_file:
            pytest.skip("No sample files found")
        
        # Load the sample file
        tax_statement = TaxStatement.from_xml_file(sample_file)
        
        # Calculate in OVERWRITE mode to ensure all totals are populated
        calculator = TotalCalculator(mode=CalculationMode.OVERWRITE)
        first_result = calculator.calculate(tax_statement)
        
        # Store the calculated totals
        first_totals = {
            "totalTaxValue": first_result.totalTaxValue,
            "totalGrossRevenueA": first_result.totalGrossRevenueA,
            "totalGrossRevenueB": first_result.totalGrossRevenueB,
            "totalWithHoldingTaxClaim": first_result.totalWithHoldingTaxClaim,
            "totalGrossRevenueDA1": first_result.totalGrossRevenueDA1,
            "totalTaxValueDA1": first_result.totalTaxValueDA1,
            "totalFlatRateTaxCredit": first_result.totalFlatRateTaxCredit,
            "totalAdditionalWithHoldingTaxUSA": first_result.totalAdditionalWithHoldingTaxUSA
        }
        
        # Calculate again
        second_result = calculator.calculate(first_result)
        
        # Store the second calculated totals
        second_totals = {
            "totalTaxValue": second_result.totalTaxValue,
            "totalGrossRevenueA": second_result.totalGrossRevenueA,
            "totalGrossRevenueB": second_result.totalGrossRevenueB,
            "totalWithHoldingTaxClaim": second_result.totalWithHoldingTaxClaim,
            "totalGrossRevenueDA1": second_result.totalGrossRevenueDA1,
            "totalTaxValueDA1": second_result.totalTaxValueDA1,
            "totalFlatRateTaxCredit": second_result.totalFlatRateTaxCredit,
            "totalAdditionalWithHoldingTaxUSA": second_result.totalAdditionalWithHoldingTaxUSA
        }
        
        # Compare the two sets of totals
        for key, value in first_totals.items():
            if value is not None:
                assert value == second_totals[key], f"Inconsistent calculation for {key} in {sample_file}"
