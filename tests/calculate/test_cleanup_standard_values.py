import pytest
from datetime import date, datetime, timedelta
from freezegun import freeze_time
from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.model.ech0196 import TaxStatement, Client, ClientNumber, Institution, LEIType

class TestCleanupCalculatorStandardValues:
    """
    Tests for standard values set in the calculate method.
    """
    
    @freeze_time("2025-05-29 10:00:00")
    def test_standard_values_are_set(self):
        """Test that standard values are correctly set in the TaxStatement."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        
        # Create a minimal statement
        statement = TaxStatement(
            id=None, 
            creationDate=None,  # Should be set by calculate
            taxPeriod=None,     # Should be set by calculate
            periodFrom=None,    # Should be set by calculate
            periodTo=None,      # Should be set by calculate
            country=None,       # Should be set by calculate
            canton="ZH", 
            minorVersion=None,  # Should be set by calculate
            client=[Client(clientNumber=ClientNumber("TestClient"))], 
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(period_from, period_to, "TestImporter")
        result = calculator.calculate(statement)
        
        # Assert
        assert result.minorVersion == 22
        assert result.periodFrom == period_from
        assert result.periodTo == period_to
        assert result.taxPeriod == period_to.year
        assert result.country == "CH"
        assert result.creationDate == datetime(2025, 5, 29, 10, 0, 0)
        
    def test_period_values_propagation(self):
        """Test that period values are correctly propagated from the calculator to the statement."""
        # Arrange
        period_from = date(2023, 1, 1)
        period_to = date(2023, 12, 31)
        
        statement = TaxStatement(
            id=None,
            creationDate=None,
            taxPeriod=2000,  # Different year to test override
            periodFrom=date(2000, 1, 1),  # Different date to test override
            periodTo=date(2000, 12, 31),  # Different date to test override
            country="FR",  # Different country to test override
            canton="ZH",
            minorVersion=0,  # Different version to test override
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(period_from, period_to, "TestImporter")
        result = calculator.calculate(statement)
        
        # Assert
        assert result.minorVersion == 22
        assert result.periodFrom == period_from
        assert result.periodTo == period_to
        assert result.taxPeriod == period_to.year
        assert result.country == "CH"
        
    @freeze_time("2025-05-29 10:00:00")
    def test_creation_date_is_set_to_current_time(self):
        """Test that creationDate is set to the current time."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        
        statement = TaxStatement(
            id=None,
            creationDate=datetime(2000, 1, 1),  # Old date to test override
            taxPeriod=None,
            periodFrom=None,
            periodTo=None,
            country=None,
            canton="ZH",
            minorVersion=None,
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(period_from, period_to, "TestImporter")
        result = calculator.calculate(statement)
        
        # Assert
        assert result.creationDate == datetime(2025, 5, 29, 10, 0, 0)
        
    def test_standard_values_in_modified_fields(self):
        """Test that standard values are not logged in modified_fields as they are expected to be set."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        
        statement = TaxStatement(
            id=None,
            creationDate=None,
            taxPeriod=None,
            periodFrom=None,
            periodTo=None,
            country=None,
            canton="ZH",
            minorVersion=None,
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(period_from, period_to, "TestImporter")
        result = calculator.calculate(statement)
        
        # Assert - Only ID should be in modified_fields since standard values are not tracked
        assert len(calculator.modified_fields) == 1
        assert "TaxStatement.id (generated)" in calculator.modified_fields
        
        # Verify standard values are set but not logged as modifications
        assert result.minorVersion == 22
        assert result.periodFrom == period_from
        assert result.periodTo == period_to
        assert result.taxPeriod == period_to.year
        assert result.country == "CH"
        assert result.creationDate is not None
    
    def test_datetime_now_for_creation_date(self):
        """Test that creationDate uses datetime.now() by measuring before and after."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        
        statement = TaxStatement(
            id=None,
            creationDate=None,
            taxPeriod=None,
            periodFrom=None,
            periodTo=None,
            country=None,
            canton="ZH",
            minorVersion=None,
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Get time before calculation
        before_time = datetime.now()
        
        # Act
        calculator = CleanupCalculator(period_from, period_to, "TestImporter")
        result = calculator.calculate(statement)
        
        # Get time after calculation
        after_time = datetime.now()
        
        # Assert
        # First verify creationDate is not None
        assert result.creationDate is not None
        
        # The creation date should be between before_time and after_time
        assert before_time <= result.creationDate <= after_time
        
        # Also verify all other standard values are set
        assert result.minorVersion == 22
        assert result.periodFrom == period_from
        assert result.periodTo == period_to
        assert result.taxPeriod == period_to.year
        assert result.country == "CH"
