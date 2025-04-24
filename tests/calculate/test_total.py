import os
import pytest
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional
from opensteuerauszug.model.ech0196 import (
    CurrencyId, ListOfSecurities, ValorNumber, ISINType, BankAccountNumber, BankAccountName,
    ClientNumber, CountryIdISO2Type, LiabilityCategory, PositiveDecimal,
    BankAccountNumber, BankAccountName, CountryIdISO2Type, CurrencyId
)

from opensteuerauszug.calculate.base import CalculationMode, CalculationError
from opensteuerauszug.calculate.total import TotalCalculator
from opensteuerauszug.model.ech0196 import (
    TaxStatement, Security, BankAccount, LiabilityAccount, Expense,
    SecurityTaxValue, SecurityPayment, BankAccountTaxValue, BankAccountPayment,
    LiabilityAccountTaxValue, LiabilityAccountPayment, ListOfSecurities,
    ListOfBankAccounts, ListOfLiabilities, ListOfExpenses, ClientNumber
)
from tests.utils.samples import get_sample_files

# Helper function to create a simple tax statement for testing
def create_test_tax_statement() -> TaxStatement:
    """Create a simple tax statement with some securities, bank accounts, and liabilities."""
    # Create a security with tax value and payments
    security1 = Security(
        positionId=123,  # Changed to int
        valorNumber=ValorNumber(123456),  # Wrapped in ValorNumber
        isin=ISINType("CH0001234567"),  # Wrapped in ISINType
        name="Test Security 1",
        country="CH",
        currency=CurrencyId("CHF"),
        quotationType="PIECE",  # Added missing field
        securityCategory="SHARE",  # Changed from EQUITY
        securityName="Test Security 1",
        taxValue=SecurityTaxValue(
            referenceDate="2023-12-31",
            quotationCurrency="CHF",
            quotation=Decimal("100.00"),
            quantity=Decimal("10"),
            exchangeRate=Decimal("1.0"),
            value=Decimal("1000.00"),
            quotationType="PIECE",
            balanceCurrency=CurrencyId("CHF")
        ),
        payment=[
            SecurityPayment(
                paymentDate="2023-06-30",
                name="Dividend",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("50.00"),
                exchangeRate=Decimal("1.0"),
                grossRevenueA=Decimal("50.00"),
                grossRevenueB=Decimal("0.00"),
                withHoldingTaxClaim=Decimal("17.50"),
                quotationType="PIECE",
                quantity=Decimal("10")
            ),
            SecurityPayment(
                paymentDate="2023-12-31",
                name="Interest",
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("30.00"),
                exchangeRate=Decimal("1.0"),
                grossRevenueA=Decimal("0.00"),
                grossRevenueB=Decimal("30.00"),
                withHoldingTaxClaim=Decimal("10.50"),
                quotationType="PIECE",
                quantity=Decimal("10")
            )
        ]
    )
    
    # Create a bank account with tax value and payments
    bank_account1 = BankAccount(
        bankAccountNumber=BankAccountNumber("123456789"),  # Wrapped in type
        bankAccountName=BankAccountName("Test Account"),  # Wrapped in type
        bankAccountCountry=CountryIdISO2Type("CH"),  # Added missing required field
        bankAccountCurrency=CurrencyId("CHF"),  # Added missing required field
        totalWithHoldingTaxClaim=Decimal("8.75"),  # Added missing required field
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
        bankAccountNumber=BankAccountNumber("L123456"),  # Wrapped in type, field renamed
        bankAccountName=BankAccountName("Test Mortgage"),  # Wrapped in type
        bankAccountCountry=CountryIdISO2Type("CH"),  # Added missing required field
        bankAccountCurrency=CurrencyId("CHF"),  # Added missing required field
        liabilityCategory="MORTGAGE",  # Assign literal directly
        totalTaxValue=PositiveDecimal("200000.00"),  # Added missing required field, wrapped
        totalGrossRevenueB=PositiveDecimal("2000.00"),  # Added missing required field, wrapped
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
                amountCurrency=CurrencyId("CHF"),
                amount=Decimal("2000.00"),
                exchangeRate=Decimal("1.0"),
                grossRevenueB=Decimal("2000.00")
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
        client=[{
            "clientNumber": ClientNumber("C1"), 
            "firstName": "Max", 
            "lastName": "Muster", 
            "salutation": "2"
        }],
        listOfSecurities=ListOfSecurities(security=[security1]),
        listOfBankAccounts=ListOfBankAccounts(bankAccount=[bank_account1]),
        listOfLiabilities=ListOfLiabilities(liabilityAccount=[liability1]),
        # Leave totals empty for calculator to fill
    )

# Unit tests for TotalCalculator
class TestTotalCalculator:
    
    @pytest.mark.skip(reason="Temporarily disabled for fixing")
    def test_calculate_fill_mode(self):
        """Test that the calculator correctly fills in missing total values."""
        # Create a tax statement with no totals
        tax_statement = create_test_tax_statement()
        
        # Expected values based on the test data
        expected_tax_value = Decimal("-194000.00")  # 1000 + 5000 - 200000
        expected_gross_revenue_a = Decimal("75.00")  # 50 + 25
        expected_gross_revenue_b = Decimal("2030.00")  # 30 + 2000
        expected_withholding_tax_claim = Decimal("36.75")  # 17.50 + 10.50 + 8.75
        
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
    
    @pytest.mark.skip(reason="Temporarily disabled for fixing")
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
    
    @pytest.mark.skip(reason="Temporarily disabled for fixing")
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
    
    @pytest.mark.skip(reason="Temporarily disabled for fixing")
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
    
    @pytest.mark.skip(reason="Temporarily disabled for fixing")
    def test_usa_specific_calculations(self):
        """Test USA-specific calculations (DA-1)."""
        # Create a security with USA payments
        security_usa = Security(
            positionId=999,  # Changed to int
            isin=ISINType("US0006543210"),  # Wrapped in ISINType
            name="Test US Security",
            country="US",
            currency=CurrencyId("USD"),
            quotationType="PIECE",  # Added missing field
            securityCategory="SHARE",  # Changed from EQUITY
            securityName="Test US Security",
            valorNumber=ValorNumber(654321),  # Wrapped in ValorNumber
            taxValue=SecurityTaxValue(
                referenceDate="2023-12-31",
                quotationCurrency="USD",
                quotation=Decimal("50.00"),
                quantity=Decimal("20"),
                exchangeRate=Decimal("0.9"),
                value=Decimal("900.00"),
                quotationType="PIECE",
                balanceCurrency=CurrencyId("CHF")
            ),
            payment = [ SecurityPayment(
                    paymentDate="2023-06-30",
                    name="US Dividend",
                    country="US",  # This might belong here or on Security, check definition
                    amountCurrency=CurrencyId("USD"),  # Correct place for amountCurrency
                    amount=Decimal("100.00"),
                    exchangeRate=Decimal("0.9"),
                    grossRevenueA=Decimal("90.00"),
                    grossRevenueB=Decimal("0.00"),
                    withHoldingTaxClaim=Decimal("31.50"),
                    additionalWithHoldingTax=Decimal("15.00"),  # These seem specific to payment
                    flatRateTaxCredit=Decimal("5.00"),  # These seem specific to payment
                    quotationType="PIECE",  # Correct place for quotationType
                    quantity=Decimal("20")  # Correct place for quantity
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
            institution={"name": "Test Bank AG"},  # Added missing institution
            client=[{
                "clientNumber": ClientNumber("C1"), 
                "firstName": "Max", 
                "lastName": "Muster", 
                "salutation": "2"
            }],
            listOfSecurities=ListOfSecurities(security=[security_usa])
        )
        
        # Calculate in FILL mode
        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)
        
        # Check USA-specific totals
        assert result.brutto_da1_usa == Decimal("90.00")
        assert result.steuerwert_da1_usa == Decimal("900.00")
        assert result.pauschale_da1 == Decimal("5.00")
        assert result.rueckbehalt_usa == Decimal("15.00")
        
        # Check regular totals
        assert result.totalTaxValue == Decimal("900.00")
        assert result.totalGrossRevenueA == Decimal("90.00")
        assert result.totalGrossRevenueB == Decimal("0.00")
        assert result.totalWithHoldingTaxClaim == Decimal("31.50")

    def test_minimal_bank_account_only(self):
        """Test calculation with only one CHF bank account and no payments, ensuring sub-totals are calculated."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("CH1234567890123456789"),
            bankAccountName=BankAccountName("Minimal Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            # Initialize optional totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
            taxValue=BankAccountTaxValue(
                referenceDate="2023-12-31",
                balanceCurrency="CHF",
                balance=Decimal("1234.56"),
                exchangeRate=Decimal("1.0"),
                value=Decimal("1234.56")
            ),
            payment=[] # Explicitly empty
        )

        list_of_accounts = ListOfBankAccounts(
            bankAccount=[bank_account],
            # Initialize list totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None
        )

        tax_statement = TaxStatement(
            minorVersion=2,
            id="test-minimal-bank",
            creationDate="2024-01-15T10:00:00",
            taxPeriod=2023,
            periodFrom="2023-01-01",
            periodTo="2023-12-31",
            canton="ZH",
            institution={"name": "Minimal Bank"},
            client=[{
                "clientNumber": ClientNumber("CMin"),
                "firstName": "Min",
                "lastName": "Imal",
                "salutation": "2"
            }],
            listOfBankAccounts=list_of_accounts,
            # Initialize statement totals as None
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
            # No securities, liabilities, or expenses
        )

        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)

        # Assert totals on TaxStatement level
        assert result.totalTaxValue == Decimal("1234.56")
        assert result.totalGrossRevenueA == Decimal("0.00")
        assert result.totalGrossRevenueB == Decimal("0.00")
        assert result.totalWithHoldingTaxClaim == Decimal("0.00")

        # Assert totals on ListOfBankAccounts level
        assert result.listOfBankAccounts is not None
        assert result.listOfBankAccounts.totalTaxValue == Decimal("1234.56")
        assert result.listOfBankAccounts.totalGrossRevenueA == Decimal("0.00")
        assert result.listOfBankAccounts.totalGrossRevenueB == Decimal("0.00")
        assert result.listOfBankAccounts.totalWithHoldingTaxClaim == Decimal("0.00")

        # Assert totals on the individual BankAccount level
        assert len(result.listOfBankAccounts.bankAccount) == 1
        calculated_bank_account = result.listOfBankAccounts.bankAccount[0]
        assert calculated_bank_account.totalTaxValue == Decimal("1234.56")
        assert calculated_bank_account.totalGrossRevenueA == Decimal("0.00")
        assert calculated_bank_account.totalGrossRevenueB == Decimal("0.00")
        assert calculated_bank_account.totalWithHoldingTaxClaim == Decimal("0.00")

        expected_modified = {
            "totalTaxValue", "totalGrossRevenueA", "totalGrossRevenueB", "totalWithHoldingTaxClaim",
            "listOfBankAccounts.totalTaxValue", "listOfBankAccounts.totalGrossRevenueA",
            "listOfBankAccounts.totalGrossRevenueB", "listOfBankAccounts.totalWithHoldingTaxClaim",
            "listOfBankAccounts.bankAccount[0].totalTaxValue", "listOfBankAccounts.bankAccount[0].totalGrossRevenueA",
            "listOfBankAccounts.bankAccount[0].totalGrossRevenueB",
            "listOfBankAccounts.bankAccount[0].totalWithHoldingTaxClaim"
        }
 
        assert calculator.modified_fields.issuperset(expected_modified)

    def test_bank_account_with_payment_and_withholding(self):
        """Test calculation with a bank account that has a payment with withholding tax."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("CH9876543210987654321"),
            bankAccountName=BankAccountName("Savings Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            # Initialize optional totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
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
                    name="Interest Payment",
                    amountCurrency="CHF",
                    amount=Decimal("100.00"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueA=Decimal("100.00"),
                    grossRevenueB=Decimal("0.00"),
                    withHoldingTaxClaim=Decimal("35.00")  # 35% withholding tax
                )
            ]
        )

        list_of_accounts = ListOfBankAccounts(
            bankAccount=[bank_account],
            # Initialize list totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None
        )

        tax_statement = TaxStatement(
            minorVersion=2,
            id="test-bank-with-withholding",
            creationDate="2024-01-15T10:00:00",
            taxPeriod=2023,
            periodFrom="2023-01-01",
            periodTo="2023-12-31",
            canton="ZH",
            institution={"name": "Test Bank AG"},
            client=[{
                "clientNumber": ClientNumber("C123"),
                "firstName": "John",
                "lastName": "Doe",
                "salutation": "2"
            }],
            listOfBankAccounts=list_of_accounts,
            # Initialize statement totals as None
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
        )

        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)

        # Assert totals on TaxStatement level
        assert result.totalTaxValue == Decimal("5000.00")  # Account balance
        assert result.totalGrossRevenueA == Decimal("100.00")  # Interest payment
        assert result.totalGrossRevenueB == Decimal("0.00")  # No revenue B
        assert result.totalWithHoldingTaxClaim == Decimal("35.00")  # Withholding tax

        # Assert totals on ListOfBankAccounts level
        assert result.listOfBankAccounts.totalTaxValue == Decimal("5000.00")
        assert result.listOfBankAccounts.totalGrossRevenueA == Decimal("100.00")
        assert result.listOfBankAccounts.totalGrossRevenueB == Decimal("0.00")
        assert result.listOfBankAccounts.totalWithHoldingTaxClaim == Decimal("35.00")

        # Assert totals on the individual BankAccount level
        calculated_bank_account = result.listOfBankAccounts.bankAccount[0]
        assert calculated_bank_account.totalTaxValue == Decimal("5000.00")
        assert calculated_bank_account.totalGrossRevenueA == Decimal("100.00")
        assert calculated_bank_account.totalGrossRevenueB == Decimal("0.00")
        assert calculated_bank_account.totalWithHoldingTaxClaim == Decimal("35.00")

        expected_modified = {
            "totalTaxValue", "totalGrossRevenueA", "totalGrossRevenueB", "totalWithHoldingTaxClaim",
            "listOfBankAccounts.totalTaxValue", "listOfBankAccounts.totalGrossRevenueA",
            "listOfBankAccounts.totalGrossRevenueB", "listOfBankAccounts.totalWithHoldingTaxClaim",
            "listOfBankAccounts.bankAccount[0].totalTaxValue", "listOfBankAccounts.bankAccount[0].totalGrossRevenueA",
            "listOfBankAccounts.bankAccount[0].totalGrossRevenueB",
            "listOfBankAccounts.bankAccount[0].totalWithHoldingTaxClaim"
        }
        
        assert calculator.modified_fields.issuperset(expected_modified)

    def test_bank_account_with_payment_no_withholding(self):
        """Test calculation with a bank account that has a payment without withholding tax."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("CH5555444433332222"),
            bankAccountName=BankAccountName("Current Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            # Initialize optional totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
            taxValue=BankAccountTaxValue(
                referenceDate="2023-12-31",
                balanceCurrency="CHF",
                balance=Decimal("10000.00"),
                exchangeRate=Decimal("1.0"),
                value=Decimal("10000.00")
            ),
            payment=[
                BankAccountPayment(
                    paymentDate="2023-09-15",
                    name="Tax-Free Interest",
                    amountCurrency="CHF",
                    amount=Decimal("75.50"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueA=Decimal("0.00"),  # Tax-free goes into revenue B
                    grossRevenueB=Decimal("75.50"),
                    withHoldingTaxClaim=Decimal("0.00")  # No withholding tax
                )
            ]
        )

        list_of_accounts = ListOfBankAccounts(
            bankAccount=[bank_account],
            # Initialize list totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None
        )

        tax_statement = TaxStatement(
            minorVersion=2,
            id="test-bank-no-withholding",
            creationDate="2024-01-15T10:00:00",
            taxPeriod=2023,
            periodFrom="2023-01-01",
            periodTo="2023-12-31",
            canton="ZH",
            institution={"name": "Test Bank AG"},
            client=[{
                "clientNumber": ClientNumber("C456"),
                "firstName": "Jane",
                "lastName": "Smith",
                "salutation": "2"
            }],
            listOfBankAccounts=list_of_accounts,
            # Initialize statement totals as None
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
        )

        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)

        # Assert totals on TaxStatement level
        assert result.totalTaxValue == Decimal("10000.00")  # Account balance
        assert result.totalGrossRevenueA == Decimal("0.00")  # No revenue A
        assert result.totalGrossRevenueB == Decimal("75.50")  # Tax-free interest
        assert result.totalWithHoldingTaxClaim == Decimal("0.00")  # No withholding tax

        # Assert totals on ListOfBankAccounts level
        assert result.listOfBankAccounts.totalTaxValue == Decimal("10000.00")
        assert result.listOfBankAccounts.totalGrossRevenueA == Decimal("0.00")
        assert result.listOfBankAccounts.totalGrossRevenueB == Decimal("75.50")
        assert result.listOfBankAccounts.totalWithHoldingTaxClaim == Decimal("0.00")

        # Assert totals on the individual BankAccount level
        calculated_bank_account = result.listOfBankAccounts.bankAccount[0]
        assert calculated_bank_account.totalTaxValue == Decimal("10000.00")
        assert calculated_bank_account.totalGrossRevenueA == Decimal("0.00")
        assert calculated_bank_account.totalGrossRevenueB == Decimal("75.50")
        assert calculated_bank_account.totalWithHoldingTaxClaim == Decimal("0.00")

        expected_modified = {
            "totalTaxValue", "totalGrossRevenueA", "totalGrossRevenueB", "totalWithHoldingTaxClaim",
            "listOfBankAccounts.totalTaxValue", "listOfBankAccounts.totalGrossRevenueA",
            "listOfBankAccounts.totalGrossRevenueB", "listOfBankAccounts.totalWithHoldingTaxClaim",
            "listOfBankAccounts.bankAccount[0].totalTaxValue", "listOfBankAccounts.bankAccount[0].totalGrossRevenueA",
            "listOfBankAccounts.bankAccount[0].totalGrossRevenueB",
            "listOfBankAccounts.bankAccount[0].totalWithHoldingTaxClaim"
        }
        
        assert calculator.modified_fields.issuperset(expected_modified)

    def test_bank_account_multiple_payments(self):
        """Test calculation with a bank account that has multiple payments to ensure they are added correctly."""
        bank_account = BankAccount(
            bankAccountNumber=BankAccountNumber("CH1111222233334444"),
            bankAccountName=BankAccountName("Multiple Payments Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            # Initialize optional totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
            taxValue=BankAccountTaxValue(
                referenceDate="2023-12-31",
                balanceCurrency="CHF",
                balance=Decimal("8000.00"),
                exchangeRate=Decimal("1.0"),
                value=Decimal("8000.00")
            ),
            payment=[
                # First payment: Interest with withholding tax
                BankAccountPayment(
                    paymentDate="2023-03-15",
                    name="Q1 Interest",
                    amountCurrency="CHF",
                    amount=Decimal("50.00"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueA=Decimal("50.00"),
                    grossRevenueB=Decimal("0.00"),
                    withHoldingTaxClaim=Decimal("17.50")  # 35% withholding tax
                ),
                # Second payment: Interest with withholding tax
                BankAccountPayment(
                    paymentDate="2023-06-15",
                    name="Q2 Interest",
                    amountCurrency="CHF",
                    amount=Decimal("55.00"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueA=Decimal("55.00"),
                    grossRevenueB=Decimal("0.00"),
                    withHoldingTaxClaim=Decimal("19.25")  # 35% withholding tax
                ),
                # Third payment: Tax-free interest
                BankAccountPayment(
                    paymentDate="2023-09-15",
                    name="Q3 Tax-Free Bonus",
                    amountCurrency="CHF",
                    amount=Decimal("30.00"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueA=Decimal("0.00"),
                    grossRevenueB=Decimal("30.00"),
                    withHoldingTaxClaim=Decimal("0.00")  # No withholding tax
                ),
                # Fourth payment: Mixed revenue types
                BankAccountPayment(
                    paymentDate="2023-12-15",
                    name="Q4 Mixed Payment",
                    amountCurrency="CHF",
                    amount=Decimal("100.00"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueA=Decimal("70.00"),
                    grossRevenueB=Decimal("30.00"),
                    withHoldingTaxClaim=Decimal("24.50")  # 35% on revenue A
                ),
            ]
        )

        list_of_accounts = ListOfBankAccounts(
            bankAccount=[bank_account],
            # Initialize list totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None
        )

        tax_statement = TaxStatement(
            minorVersion=2,
            id="test-multiple-payments",
            creationDate="2024-01-15T10:00:00",
            taxPeriod=2023,
            periodFrom="2023-01-01",
            periodTo="2023-12-31",
            canton="ZH",
            institution={"name": "Test Bank AG"},
            client=[{
                "clientNumber": ClientNumber("C789"),
                "firstName": "Alice",
                "lastName": "Johnson",
                "salutation": "2"
            }],
            listOfBankAccounts=list_of_accounts,
            # Initialize statement totals as None
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
        )

        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)

        # Expected totals - sum of all payments
        expected_gross_revenue_a = Decimal("175.00")  # 50 + 55 + 0 + 70
        expected_gross_revenue_b = Decimal("60.00")   # 0 + 0 + 30 + 30
        expected_withholding_tax = Decimal("61.25")   # 17.50 + 19.25 + 0 + 24.50

        # Assert totals on TaxStatement level
        assert result.totalTaxValue == Decimal("8000.00")
        assert result.totalGrossRevenueA == expected_gross_revenue_a
        assert result.totalGrossRevenueB == expected_gross_revenue_b
        assert result.totalWithHoldingTaxClaim == expected_withholding_tax

        # Assert totals on ListOfBankAccounts level
        assert result.listOfBankAccounts.totalTaxValue == Decimal("8000.00")
        assert result.listOfBankAccounts.totalGrossRevenueA == expected_gross_revenue_a
        assert result.listOfBankAccounts.totalGrossRevenueB == expected_gross_revenue_b
        assert result.listOfBankAccounts.totalWithHoldingTaxClaim == expected_withholding_tax

        # Assert totals on the individual BankAccount level
        calculated_bank_account = result.listOfBankAccounts.bankAccount[0]
        assert calculated_bank_account.totalTaxValue == Decimal("8000.00")
        assert calculated_bank_account.totalGrossRevenueA == expected_gross_revenue_a
        assert calculated_bank_account.totalGrossRevenueB == expected_gross_revenue_b
        assert calculated_bank_account.totalWithHoldingTaxClaim == expected_withholding_tax

        expected_modified = {
            "totalTaxValue", "totalGrossRevenueA", "totalGrossRevenueB", "totalWithHoldingTaxClaim",
            "listOfBankAccounts.totalTaxValue", "listOfBankAccounts.totalGrossRevenueA",
            "listOfBankAccounts.totalGrossRevenueB", "listOfBankAccounts.totalWithHoldingTaxClaim",
            "listOfBankAccounts.bankAccount[0].totalTaxValue", "listOfBankAccounts.bankAccount[0].totalGrossRevenueA",
            "listOfBankAccounts.bankAccount[0].totalGrossRevenueB",
            "listOfBankAccounts.bankAccount[0].totalWithHoldingTaxClaim"
        }
        
        assert calculator.modified_fields.issuperset(expected_modified)

    def test_multiple_bank_accounts(self):
        """Test calculation with multiple bank accounts to ensure totals are correctly summed at the statement level."""
        # First bank account with payment
        bank_account1 = BankAccount(
            bankAccountNumber=BankAccountNumber("CH1212121212121212"),
            bankAccountName=BankAccountName("Savings Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            # Initialize optional totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
            taxValue=BankAccountTaxValue(
                referenceDate="2023-12-31",
                balanceCurrency="CHF",
                balance=Decimal("5000.00"),
                exchangeRate=Decimal("1.0"),
                value=Decimal("5000.00")
            ),
            payment=[
                BankAccountPayment(
                    paymentDate="2023-06-15",
                    name="Savings Interest",
                    amountCurrency="CHF",
                    amount=Decimal("75.00"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueA=Decimal("75.00"),
                    grossRevenueB=Decimal("0.00"),
                    withHoldingTaxClaim=Decimal("26.25")  # 35% withholding tax
                )
            ]
        )
        
        # Second bank account with different currency and payment
        bank_account2 = BankAccount(
            bankAccountNumber=BankAccountNumber("CH3434343434343434"),
            bankAccountName=BankAccountName("USD Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("USD"),
            # Initialize optional totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
            taxValue=BankAccountTaxValue(
                referenceDate="2023-12-31",
                balanceCurrency="USD",
                balance=Decimal("3000.00"),
                exchangeRate=Decimal("0.9"),
                value=Decimal("2700.00")  # 3000 USD * 0.9 exchange rate = 2700 CHF
            ),
            payment=[
                BankAccountPayment(
                    paymentDate="2023-08-15",
                    name="USD Interest",
                    amountCurrency="USD",
                    amount=Decimal("100.00"),
                    exchangeRate=Decimal("0.9"),
                    grossRevenueA=Decimal("0.00"),
                    grossRevenueB=Decimal("90.00"),  # 100 USD * 0.9 exchange rate = 90 CHF
                    withHoldingTaxClaim=Decimal("0.00")  # No withholding tax
                )
            ]
        )
        
        # Third bank account with no payments but with balance
        bank_account3 = BankAccount(
            bankAccountNumber=BankAccountNumber("CH5656565656565656"),
            bankAccountName=BankAccountName("Current Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            # Initialize optional totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
            taxValue=BankAccountTaxValue(
                referenceDate="2023-12-31",
                balanceCurrency="CHF",
                balance=Decimal("2300.00"),
                exchangeRate=Decimal("1.0"),
                value=Decimal("2300.00")
            ),
            payment=[]  # No payments
        )

        list_of_accounts = ListOfBankAccounts(
            bankAccount=[bank_account1, bank_account2, bank_account3],
            # Initialize list totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None
        )

        tax_statement = TaxStatement(
            minorVersion=2,
            id="test-multiple-bank-accounts",
            creationDate="2024-01-15T10:00:00",
            taxPeriod=2023,
            periodFrom="2023-01-01",
            periodTo="2023-12-31",
            canton="ZH",
            institution={"name": "Multi Bank AG"},
            client=[{
                "clientNumber": ClientNumber("C999"),
                "firstName": "Robert",
                "lastName": "Smith",
                "salutation": "2"
            }],
            listOfBankAccounts=list_of_accounts,
            # Initialize statement totals as None
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
        )

        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)

        # Expected totals at statement level - sum of all accounts
        expected_tax_value = Decimal("10000.00")  # 5000 + 2700 + 2300
        expected_gross_revenue_a = Decimal("75.00")  # Only from account1
        expected_gross_revenue_b = Decimal("90.00")  # Only from account2
        expected_withholding_tax = Decimal("26.25")  # Only from account1

        # Assert totals on TaxStatement level
        assert result.totalTaxValue == expected_tax_value
        assert result.totalGrossRevenueA == expected_gross_revenue_a
        assert result.totalGrossRevenueB == expected_gross_revenue_b
        assert result.totalWithHoldingTaxClaim == expected_withholding_tax

        # Assert totals on ListOfBankAccounts level
        assert result.listOfBankAccounts.totalTaxValue == expected_tax_value
        assert result.listOfBankAccounts.totalGrossRevenueA == expected_gross_revenue_a
        assert result.listOfBankAccounts.totalGrossRevenueB == expected_gross_revenue_b
        assert result.listOfBankAccounts.totalWithHoldingTaxClaim == expected_withholding_tax

        # Assert totals on the individual BankAccount level
        account1 = result.listOfBankAccounts.bankAccount[0]
        assert account1.totalTaxValue == Decimal("5000.00")
        assert account1.totalGrossRevenueA == Decimal("75.00")
        assert account1.totalGrossRevenueB == Decimal("0.00")
        assert account1.totalWithHoldingTaxClaim == Decimal("26.25")

        account2 = result.listOfBankAccounts.bankAccount[1]
        assert account2.totalTaxValue == Decimal("2700.00")  # USD value converted to CHF
        assert account2.totalGrossRevenueA == Decimal("0.00")
        assert account2.totalGrossRevenueB == Decimal("90.00")  # USD value converted to CHF
        assert account2.totalWithHoldingTaxClaim == Decimal("0.00")

        account3 = result.listOfBankAccounts.bankAccount[2]
        assert account3.totalTaxValue == Decimal("2300.00")
        assert account3.totalGrossRevenueA == Decimal("0.00")
        assert account3.totalGrossRevenueB == Decimal("0.00")
        assert account3.totalWithHoldingTaxClaim == Decimal("0.00")

        # Check that modified fields includes all expected fields
        expected_modified = {
            "totalTaxValue", "totalGrossRevenueA", "totalGrossRevenueB", "totalWithHoldingTaxClaim",
            "listOfBankAccounts.totalTaxValue", "listOfBankAccounts.totalGrossRevenueA",
            "listOfBankAccounts.totalGrossRevenueB", "listOfBankAccounts.totalWithHoldingTaxClaim"
        }
        
        # Also include individual account fields
        for i in range(3):
            for field in ["totalTaxValue", "totalGrossRevenueA", "totalGrossRevenueB", "totalWithHoldingTaxClaim"]:
                expected_modified.add(f"listOfBankAccounts.bankAccount[{i}].{field}")
        
        assert calculator.modified_fields.issuperset(expected_modified)

# Integration tests using real sample files
class TestTotalCalculatorIntegration:
    
    @pytest.mark.skip(reason="Temporarily disabled for fixing")
    @pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
    def test_calculation_verify_with_samples(self, sample_file):
        """Test that calculations verify correctly against real sample files."""
        if not sample_file:
            pytest.skip("No sample files found")
        
        # Load the sample file
        tax_statement = TaxStatement.from_xml_file(sample_file)

        # We assume these real world files have correct totals       
        # First, calculate in FILL mode to ensure all totals are populated
        # whilst verifying values that exist.
        fill_calculator = TotalCalculator(mode=CalculationMode.FILL)
        filled_statement = fill_calculator.calculate(tax_statement)
        
        # Then verify the filled values
        verify_calculator = TotalCalculator(mode=CalculationMode.VERIFY)
        verify_calculator.calculate(filled_statement)
   
    @pytest.mark.skip(reason="Temporarily disabled for fixing")
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
            "steuerwert_da1_usa": first_result.steuerwert_da1_usa,
            "brutto_da1_usa": first_result.brutto_da1_usa,
            "pauschale_da1": first_result.pauschale_da1,
            "rueckbehalt_usa": first_result.rueckbehalt_usa
        }
        
        # Calculate again
        second_result = calculator.calculate(first_result)
        
        # Store the second calculated totals
        second_totals = {
            "totalTaxValue": second_result.totalTaxValue,
            "totalGrossRevenueA": second_result.totalGrossRevenueA,
            "totalGrossRevenueB": second_result.totalGrossRevenueB,
            "totalWithHoldingTaxClaim": second_result.totalWithHoldingTaxClaim,
            "steuerwert_da1_usa": second_result.steuerwert_da1_usa,
            "brutto_da1_usa": second_result.brutto_da1_usa,
            "pauschale_da1": second_result.pauschale_da1,
            "rueckbehalt_usa": second_result.rueckbehalt_usa
        }
        
        # Compare the two sets of totals
        for key, value in first_totals.items():
            if value is not None:
                assert value == second_totals[key], f"Inconsistent calculation for {key} in {sample_file}"
