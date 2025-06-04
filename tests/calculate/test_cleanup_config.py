import pytest
from datetime import date, datetime
from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.model.ech0196 import TaxStatement, Client, ClientNumber, Institution, LEIType
from opensteuerauszug.config.models import GeneralSettings


class TestCleanupCalculatorConfig:
    """Tests for configuration-based canton and client name setting in CleanupCalculator."""
    
    def test_set_canton_from_config_when_none(self):
        """Test that canton is set from config when it's None in the statement."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        config_settings = GeneralSettings(canton='ZH', full_name='Test User')
        
        statement = TaxStatement(
            id="test-id",
            creationDate=datetime(2024, 1, 1),
            taxPeriod=2024,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton=None,  # Canton not set
            minorVersion=22,
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(
            period_from, period_to, "TestImporter", 
            config_settings=config_settings
        )
        result = calculator.calculate(statement)
        
        # Assert
        assert result.canton == "ZH"
        assert "TaxStatement.canton (from config)" in calculator.modified_fields
        assert any("Set canton from configuration: ZH" in log for log in calculator.get_log())

    def test_do_not_override_existing_canton(self):
        """Test that existing canton is not overridden by config."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        config_settings = GeneralSettings(canton='ZH', full_name='Test User')
        
        statement = TaxStatement(
            id="test-id",
            creationDate=datetime(2024, 1, 1),
            taxPeriod=2024,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="BE",  # Canton already set
            minorVersion=22,
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(
            period_from, period_to, "TestImporter", 
            config_settings=config_settings
        )
        result = calculator.calculate(statement)
        
        # Assert
        assert result.canton == "BE"  # Original canton preserved
        assert "TaxStatement.canton (from config)" not in calculator.modified_fields

    def test_create_client_from_config_when_none_exist(self):
        """Test that a client is created from config when none exist."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        config_settings = GeneralSettings(canton='ZH', full_name='John Doe')
        
        statement = TaxStatement(
            id="test-id",
            creationDate=datetime(2024, 1, 1),
            taxPeriod=2024,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="ZH",
            minorVersion=22,
            client=[],  # No clients
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(
            period_from, period_to, "TestImporter", 
            config_settings=config_settings
        )
        result = calculator.calculate(statement)
        
        # Assert
        assert len(result.client) == 1
        assert result.client[0].firstName == "John"
        assert result.client[0].lastName == "Doe"
        assert "TaxStatement.client (created from config)" in calculator.modified_fields
        assert any("Created client from configuration: John Doe" in log for log in calculator.get_log())

    def test_update_existing_client_missing_names(self):
        """Test that existing client with missing names is updated from config."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        config_settings = GeneralSettings(canton='ZH', full_name='Jane Smith')
        
        statement = TaxStatement(
            id="test-id",
            creationDate=datetime(2024, 1, 1),
            taxPeriod=2024,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="ZH",
            minorVersion=22,
            client=[Client(clientNumber=ClientNumber("TestClient"))],  # Client exists but no names
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(
            period_from, period_to, "TestImporter", 
            config_settings=config_settings
        )
        result = calculator.calculate(statement)
        
        # Assert
        assert result.client[0].firstName == "Jane"
        assert result.client[0].lastName == "Smith"
        assert "TaxStatement.client[0] (name from config)" in calculator.modified_fields
        assert any("Updated client[0] name from configuration: Jane Smith" in log for log in calculator.get_log())

    def test_do_not_override_existing_client_names(self):
        """Test that existing client names are not overridden by config."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        config_settings = GeneralSettings(canton='ZH', full_name='Config User')
        
        statement = TaxStatement(
            id="test-id",
            creationDate=datetime(2024, 1, 1),
            taxPeriod=2024,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="ZH",
            minorVersion=22,
            client=[Client(
                clientNumber=ClientNumber("TestClient"),
                firstName="Existing",
                lastName="User"
            )],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(
            period_from, period_to, "TestImporter", 
            config_settings=config_settings
        )
        result = calculator.calculate(statement)
        
        # Assert
        assert result.client[0].firstName == "Existing"
        assert result.client[0].lastName == "User"
        assert "TaxStatement.client[0] (name from config)" not in calculator.modified_fields

    def test_handle_single_name_in_config(self):
        """Test handling of single name in configuration."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        config_settings = GeneralSettings(canton='ZH', full_name='Madonna')
        
        statement = TaxStatement(
            id="test-id",
            creationDate=datetime(2024, 1, 1),
            taxPeriod=2024,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="ZH",
            minorVersion=22,
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(
            period_from, period_to, "TestImporter", 
            config_settings=config_settings
        )
        result = calculator.calculate(statement)
        
        # Assert
        assert result.client[0].firstName == "Madonna"
        assert result.client[0].lastName is None

    def test_handle_multiple_names_in_config(self):
        """Test handling of multiple names in configuration."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        config_settings = GeneralSettings(canton='ZH', full_name='Jean-Claude Van Damme')
        
        statement = TaxStatement(
            id="test-id",
            creationDate=datetime(2024, 1, 1),
            taxPeriod=2024,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton="ZH",
            minorVersion=22,
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(
            period_from, period_to, "TestImporter", 
            config_settings=config_settings
        )
        result = calculator.calculate(statement)
        
        # Assert
        assert result.client[0].firstName == "Jean-Claude"
        assert result.client[0].lastName == "Van Damme"

    def test_no_config_provided(self):
        """Test that no changes are made when no config is provided."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        
        statement = TaxStatement(
            id="test-id",
            creationDate=datetime(2024, 1, 1),
            taxPeriod=2024,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton=None,
            minorVersion=22,
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(
            period_from, period_to, "TestImporter"
        )
        result = calculator.calculate(statement)
        
        # Assert
        assert result.canton is None
        assert result.client[0].firstName is None
        assert result.client[0].lastName is None
        assert "TaxStatement.canton (from config)" not in calculator.modified_fields
        assert "TaxStatement.client[0] (name from config)" not in calculator.modified_fields

    def test_empty_config_provided(self):
        """Test that no changes are made when empty config is provided."""
        # Arrange
        period_from = date(2024, 1, 1)
        period_to = date(2024, 12, 31)
        config_settings = None
        
        statement = TaxStatement(
            id="test-id",
            creationDate=datetime(2024, 1, 1),
            taxPeriod=2024,
            periodFrom=period_from,
            periodTo=period_to,
            country="CH",
            canton=None,
            minorVersion=22,
            client=[Client(clientNumber=ClientNumber("TestClient"))],
            institution=Institution(lei=LEIType("TESTLEI1234500000000"))
        )
        
        # Act
        calculator = CleanupCalculator(
            period_from, period_to, "TestImporter", 
            config_settings=config_settings
        )
        result = calculator.calculate(statement)
        
        # Assert
        assert result.canton is None
        assert result.client[0].firstName is None
        assert result.client[0].lastName is None
        assert "TaxStatement.canton (from config)" not in calculator.modified_fields
        assert "TaxStatement.client[0] (name from config)" not in calculator.modified_fields 