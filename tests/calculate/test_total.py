import os
import pytest
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional
from opensteuerauszug.model.ech0196 import (
    CurrencyId, ListOfSecurities, ValorNumber, ISINType, BankAccountNumber, BankAccountName,
    ClientNumber, CountryIdISO2Type, LiabilityCategory, PositiveDecimal,
    BankAccountNumber, BankAccountName, CountryIdISO2Type, CurrencyId, Depot, DepotNumber
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
        listOfSecurities=ListOfSecurities(depot=[Depot(security=[security1])]),
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
        expected_tax_value = Decimal("6000.00")  # 1000 + 5000
        expected_gross_revenue_a = Decimal("75.00")  # 50 + 25
        expected_gross_revenue_b = Decimal("30.00")  # 30 
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
    
    def test_calculate_verify_mode_success(self):
        """Test that the calculator correctly verifies existing total values."""
        # Create a tax statement with correct totals
        tax_statement = create_test_tax_statement()
        tax_statement.totalTaxValue = Decimal("6000.00")  # 1000 + 5000 
        tax_statement.totalGrossRevenueA = Decimal("75.00")  # 50 + 25
        tax_statement.totalGrossRevenueB = Decimal("30.00")  # 30
        tax_statement.totalWithHoldingTaxClaim = Decimal("36.75")  # 17.50 + 10.50 + 8.75
        
        # Calculate in VERIFY mode
        calculator = TotalCalculator(mode=CalculationMode.VERIFY)
        result = calculator.calculate(tax_statement)
        
        # No exception should be raised, and no fields should be modified
        assert len(calculator.modified_fields) == 0
        assert len(calculator.errors) == 0
    
    def test_calculate_verify_mode_failure(self):
        """Test that the calculator collects error when verification fails."""
        # Create a tax statement with incorrect totals
        tax_statement = create_test_tax_statement()
        tax_statement.totalTaxValue = Decimal("6000.00")  # Correct
        tax_statement.totalGrossRevenueA = Decimal("100.00")  # Incorrect (should be 75)
        tax_statement.totalGrossRevenueB = Decimal("30.00")  # Correct
        tax_statement.totalWithHoldingTaxClaim = Decimal("36.75")  # Correct
        
        # Calculate in VERIFY mode
        calculator = TotalCalculator(mode=CalculationMode.VERIFY)
        result = calculator.calculate(tax_statement)
        
        assert len(calculator.errors) == 1

        # Check the error details
        error = calculator.errors[0]
        assert "totalGrossRevenueA" in str(error)
        assert "expected 75.00" in str(error)

    def test_calculate_overwrite_mode(self):
        """Test that the calculator correctly overwrites existing total values."""
        # Create a tax statement with incorrect totals
        tax_statement = create_test_tax_statement()

        
        tax_statement.totalTaxValue = Decimal("0.00")  # Incorrect
        tax_statement.totalGrossRevenueA = Decimal("0.00")  # Incorrect
        tax_statement.totalGrossRevenueB = Decimal("0.00")
        tax_statement.totalWithHoldingTaxClaim = Decimal("0.00")  # Incorrect
        
        # Expected values based on the test data
        expected_tax_value = Decimal("6000.00")  # 1000 + 5000
        expected_gross_revenue_a = Decimal("75.00")  # 50 + 25
        expected_gross_revenue_b = Decimal("30.00")  # 30 
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
                    grossRevenueA=Decimal("0.00"),
                    grossRevenueB=Decimal("90.00"),
                    withHoldingTaxClaim=Decimal("31.50"),
                    lumpSumTaxCredit=True,
                    lumpSumTaxCreditPercent=Decimal("15.00"),
                    lumpSumTaxCreditAmount=Decimal("5.000"),      
                    additionalWithHoldingTaxUSA=Decimal("15.00"),
                    quotationType="PIECE",
                    quantity=Decimal("20")  
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
            listOfSecurities=ListOfSecurities(depot=[Depot(security=[security_usa])])
        )
        
        # Calculate in FILL mode
        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)
        
        # Check USA-specific totals
        assert result.da_GrossRevenue == Decimal("90.00")
        assert result.da1TaxValue == Decimal("900.00")
        assert result.listOfSecurities.totalLumpSumTaxCredit == Decimal("5.00")
        assert result.listOfSecurities.totalAdditionalWithHoldingTaxUSA == Decimal("15.00")
        
        # Check regular totals
        assert result.totalTaxValue == Decimal("900.00")
        assert result.totalGrossRevenueA == Decimal("0.00")
        assert result.totalGrossRevenueB == Decimal("90.00")
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
                    amountCurrency=CurrencyId("CHF"),
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
                    amountCurrency=CurrencyId("CHF"),
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

        # Assert totals on the individual BankAccount level
        calculated_bank_account = result.listOfBankAccounts.bankAccount[0]
        assert calculated_bank_account.totalTaxValue == Decimal("8000.00")
        assert calculated_bank_account.totalGrossRevenueA == expected_gross_revenue_a
        assert calculated_bank_account.totalGrossRevenueB == expected_gross_revenue_b
        assert calculated_bank_account.totalWithHoldingTaxClaim == expected_withholding_tax

        # Assert totals on ListOfBankAccounts level
        assert result.listOfBankAccounts.totalTaxValue == Decimal("8000.00")
        assert result.listOfBankAccounts.totalGrossRevenueA == expected_gross_revenue_a
        assert result.listOfBankAccounts.totalGrossRevenueB == expected_gross_revenue_b
        assert result.listOfBankAccounts.totalWithHoldingTaxClaim == expected_withholding_tax

        # Assert totals on TaxStatement level
        assert result.totalTaxValue == Decimal("8000.00")
        assert result.totalGrossRevenueA == expected_gross_revenue_a
        assert result.totalGrossRevenueB == expected_gross_revenue_b
        assert result.totalWithHoldingTaxClaim == expected_withholding_tax

    def test_minimal_security(self):
        """Test calculation with a minimal tax statement containing one security."""
        # Create a security with tax value and payment
        security = Security(
            positionId=1001,
            valorNumber=ValorNumber(987654),
            isin=ISINType("CH0009876543"),
            name="Test Security",
            country="CH",  # Non-USA security (ignoring DA-1)
            currency=CurrencyId("CHF"),
            quotationType="PIECE",
            securityCategory="SHARE",
            securityName="Test Security",
            taxValue=SecurityTaxValue(
                referenceDate="2023-12-31",
                quotationCurrency="CHF",
                quotation=Decimal("50.00"),
                quantity=Decimal("100"),
                exchangeRate=Decimal("1.0"),
                value=Decimal("5000.00"),
                quotationType="PIECE",
                balanceCurrency=CurrencyId("CHF")
            ),
            payment=[
                SecurityPayment(
                    paymentDate="2023-07-15",
                    name="Annual Dividend",
                    amountCurrency=CurrencyId("CHF"),
                    amount=Decimal("200.00"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueA=Decimal("200.00"),
                    grossRevenueB=Decimal("0.00"),
                    withHoldingTaxClaim=Decimal("70.00"),
                    quotationType="PIECE",
                    quantity=Decimal("100")
                )
            ]
        )

        # Create a depot containing the security
        depot = Depot(
            depotNumber=DepotNumber("D1"), # Add a depot number
            security=[security],
        )

        # Create list of securities containing the depot
        list_of_securities = ListOfSecurities(
            depot=[depot], # Changed from security=[security]
            # Initialize list totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None
        )

        # Create a minimal tax statement with just the security
        tax_statement = TaxStatement(
            minorVersion=2,
            id="test-minimal-security",
            creationDate="2024-01-15T10:00:00",
            taxPeriod=2023,
            periodFrom="2023-01-01",
            periodTo="2023-12-31",
            canton="ZH",
            institution={"name": "Test Bank AG"},
            client=[{
                "clientNumber": ClientNumber("S123"),
                "firstName": "John",
                "lastName": "Investor",
                "salutation": "2"
            }],
            listOfSecurities=list_of_securities,
            # Initialize statement totals as None
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
        )

        # Calculate in FILL mode
        calculator = TotalCalculator(mode=CalculationMode.FILL)
        result = calculator.calculate(tax_statement)

        # Assert totals on TaxStatement level
        assert result.totalTaxValue == Decimal("5000.00")
        assert result.totalGrossRevenueA == Decimal("200.00")
        assert result.totalGrossRevenueB == Decimal("0.00")
        assert result.totalWithHoldingTaxClaim == Decimal("70.00")

        # Assert totals on ListOfSecurities level
        assert result.listOfSecurities.totalTaxValue == Decimal("5000.00")
        assert result.listOfSecurities.totalGrossRevenueA == Decimal("200.00")
        assert result.listOfSecurities.totalGrossRevenueB == Decimal("0.00")
        assert result.listOfSecurities.totalWithHoldingTaxClaim == Decimal("70.00")
        # Without DA-1 values these should still set
        assert result.listOfSecurities.totalLumpSumTaxCredit == Decimal("0.00")
        assert result.listOfSecurities.totalAdditionalWithHoldingTaxUSA == Decimal("0.00")
    
        # Check internal SV split
        assert result.svTaxValueA == Decimal("5000.00")
        assert result.svTaxValueB == Decimal("0.00")
        assert result.svGrossRevenueA == Decimal("200.00")
        assert result.svGrossRevenueB == Decimal("0.00")

        # Verify DA-1 specific fields remain None or zero (since we're ignoring DA-1)
        assert result.da_GrossRevenue is None or result.da_GrossRevenue == Decimal("0.00")
        assert result.da1TaxValue is None or result.da1TaxValue == Decimal("0.00")

        # Check that modified fields include all expected fields
        expected_modified = {
            "totalTaxValue", "totalGrossRevenueA", "totalGrossRevenueB", "totalWithHoldingTaxClaim",
            "listOfSecurities.totalTaxValue", "listOfSecurities.totalGrossRevenueA",
            "listOfSecurities.totalGrossRevenueB", "listOfSecurities.totalWithHoldingTaxClaim",
        }
        
        assert calculator.modified_fields.issuperset(expected_modified)

    def test_minimal_liability(self):
        """Test calculation with a minimal tax statement containing one liability account."""
        # Create a liability with tax value and payment
        liability = LiabilityAccount(
            bankAccountNumber=BankAccountNumber("CH7777666655554444"),
            bankAccountName=BankAccountName("Mortgage Account"),
            bankAccountCountry=CountryIdISO2Type("CH"),
            bankAccountCurrency=CurrencyId("CHF"),
            liabilityCategory="MORTGAGE",
            # Initialize optional totals as None to test FILL mode - total* values are required though
            totalTaxValue=PositiveDecimal("123456.78"),
            totalGrossRevenueB=PositiveDecimal("9999.99"),
            taxValue=LiabilityAccountTaxValue(
                referenceDate="2023-12-31",
                balanceCurrency="CHF",
                balance=Decimal("120000.00"),
                exchangeRate=Decimal("1.0"),
                value=Decimal("120000.00")
            ),
            payment=[
                LiabilityAccountPayment(
                    paymentDate="2023-06-30",
                    name="Mortgage Interest (H1)",
                    amountCurrency=CurrencyId("CHF"),
                    amount=Decimal("900.00"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueB=Decimal("900.00")
                ),
                LiabilityAccountPayment(
                    paymentDate="2023-12-31",
                    name="Mortgage Interest (H2)",
                    amountCurrency=CurrencyId("CHF"),
                    amount=Decimal("900.00"),
                    exchangeRate=Decimal("1.0"),
                    grossRevenueB=Decimal("900.00")
                )
            ]
        )

        # Create list of liabilities with one liability
        list_of_liabilities = ListOfLiabilities(
            liabilityAccount=[liability],
            # Initialize list totals as None to test FILL mode
            totalTaxValue=None,
            totalGrossRevenueB=None
        )

        # Create a minimal tax statement with just the liability
        tax_statement = TaxStatement(
            minorVersion=2,
            id="test-minimal-liability",
            creationDate="2024-01-15T10:00:00",
            taxPeriod=2023,
            periodFrom="2023-01-01",
            periodTo="2023-12-31",
            canton="ZH",
            institution={"name": "Mortgage Bank AG"},
            client=[{
                "clientNumber": ClientNumber("L123"),
                "firstName": "Mary",
                "lastName": "Homeowner",
                "salutation": "2"
            }],
            listOfLiabilities=list_of_liabilities,
            # Initialize statement totals as None
            totalTaxValue=None,
            totalGrossRevenueA=None,
            totalGrossRevenueB=None,
            totalWithHoldingTaxClaim=None,
        )

        # Calculate in FILL mode
        calculator = TotalCalculator(mode=CalculationMode.OVERWRITE)
        result = calculator.calculate(tax_statement)

        # Assert totals on TaxStatement level - 
        # liabilities don not impact them
        assert result.totalTaxValue == Decimal("0.00")
        assert result.totalGrossRevenueA == Decimal("0.00")
        assert result.totalGrossRevenueB == Decimal("0.00")
        assert result.totalWithHoldingTaxClaim == Decimal("0.00")  # Liabilities don't have withholding tax

        # Assert totals on ListOfLiabilities level
        assert result.listOfLiabilities.totalTaxValue == Decimal("120000.00")  # Positive in list context
        assert result.listOfLiabilities.totalGrossRevenueB == Decimal("1800.00")

        # Assert totals on individual LiabilityAccount level
        calculated_liability = result.listOfLiabilities.liabilityAccount[0]
        assert calculated_liability.totalTaxValue == Decimal("120000.00")
        assert calculated_liability.totalGrossRevenueB == Decimal("1800.00")

        # Check that modified fields include all expected fields
        expected_modified = {
            "totalTaxValue", "totalGrossRevenueA", "totalGrossRevenueB", "totalWithHoldingTaxClaim",
            "listOfLiabilities.totalTaxValue", "listOfLiabilities.totalGrossRevenueB",
            "listOfLiabilities.liabilityAccount[0].totalTaxValue", 
            "listOfLiabilities.liabilityAccount[0].totalGrossRevenueB"
        }
        missing_fields = expected_modified - calculator.modified_fields
        assert not missing_fields, f"Fields missing from modified_fields: {missing_fields}"

# Integration tests using real sample files
class TestTotalCalculatorIntegration:
    
    # @pytest.mark.skip(reason="Temporarily disabled for fixing")
    @pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
    def test_calculation_verify_with_samples(self, sample_file):
        """Test that calculations verify correctly against real sample files."""
        if not sample_file:
            pytest.skip("No sample files found")
        
        # Load the sample file
        tax_statement = TaxStatement.from_xml_file(sample_file)

        # Our reading of the spec (and for nice composition) is that
        # this is the correct behavior
        round_sub_total = True
        # However some real world statements seem to disagree
        if tax_statement.institution:
            # Truewealth
            if tax_statement.institution.name == "True Wealth AG":
                # Truewealth seems compute all sums with rounding the intermediates
                round_sub_total = False
 
        # We assume these real world files have correct totals       
        verify_calculator = TotalCalculator(mode=CalculationMode.VERIFY, round_sub_total=round_sub_total)
        verify_calculator.calculate(tax_statement)

        # Check if any errors were found during verification
        if verify_calculator.errors:
            error_messages = [str(e) for e in verify_calculator.errors]
            error_details = "\n".join(error_messages)
            pytest.fail(f"Verification failed for {sample_file} with {len(verify_calculator.errors)} errors:\n{error_details}")

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
            "steuerwert_da1_usa": first_result.da1TaxValue,
            "brutto_da1_usa": first_result.da_GrossRevenue,
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
            "steuerwert_da1_usa": second_result.da1TaxValue,
            "brutto_da1_usa": second_result.da_GrossRevenue,
            "pauschale_da1": second_result.pauschale_da1,
            "rueckbehalt_usa": second_result.rueckbehalt_usa
        }
        
        # Compare the two sets of totals
        for key, value in first_totals.items():
            if value is not None:
                assert value == second_totals[key], f"Inconsistent calculation for {key} in {sample_file}"
