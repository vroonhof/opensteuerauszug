import pytest
from datetime import date, datetime
from decimal import Decimal

from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    Institution,
    Client,
    ClientNumber
)
from opensteuerauszug.core.organisation import (
    compute_org_nr,
    hash_organization_name
)

@pytest.fixture
def sample_tax_statement():
    """Provides a basic tax statement for testing the organisation functions."""
    return TaxStatement(
        minorVersion=2,
        id="test-id-123",
        creationDate=datetime(2023, 10, 26, 10, 30, 00),
        taxPeriod=2023,
        periodFrom=date(2023, 1, 1),
        periodTo=date(2023, 12, 31),
        canton="ZH",
        institution=Institution(name="Test Bank AG"),
        client=[
            Client(
                clientNumber=ClientNumber("C1"),
                firstName="Max",
                lastName="Muster",
                salutation="2"  # "2" is code for "Mr"
            )
        ],
        totalTaxValue=Decimal("1000.50"),
        totalGrossRevenueA=Decimal("100.00"),
        totalGrossRevenueB=Decimal("50.00"),
        totalWithHoldingTaxClaim=Decimal("35.00")
    )

def test_hash_organization_name():
    """Test that hash_organization_name correctly hashes organization names."""
    # Test with empty string
    assert hash_organization_name("") == "000"
    
    # Test with None-like values (the function handles this internally)
    # Pass empty string instead of None directly to match the type hint
    assert hash_organization_name("") == "000"
    
    # Test with actual name (results should be consistent)
    result1 = hash_organization_name("Test Bank AG")
    result2 = hash_organization_name("Test Bank AG")
    assert result1 == result2
    assert len(result1) == 3
    assert result1.isdigit()
    
    # Test with different names (results should be different)
    result3 = hash_organization_name("Another Bank")
    assert result3 != result1
    assert len(result3) == 3
    assert result3.isdigit()

def test_compute_org_nr(sample_tax_statement):
    """Test that compute_org_nr correctly determines the organization number."""
    # Test with valid override
    assert compute_org_nr(sample_tax_statement, "12345") == "12345"
    
    # Test with invalid override
    with pytest.raises(ValueError):
        compute_org_nr(sample_tax_statement, "123")  # Too short
    
    with pytest.raises(ValueError):
        compute_org_nr(sample_tax_statement, "abcde")  # Not digits
    
    # Test default behavior (using institution name)
    org_nr = compute_org_nr(sample_tax_statement)
    assert org_nr.startswith("19")  # Should use the "19" prefix
    assert len(org_nr) == 5  # Should be 5 digits
    assert org_nr.isdigit()  # Should be all digits
    
    # Test consistent hashing (same name should give same number)
    org_nr2 = compute_org_nr(sample_tax_statement)
    assert org_nr == org_nr2
    
    # Test fallback when no institution name is available
    no_name_statement = sample_tax_statement.model_copy(deep=True)
    no_name_statement.institution.name = None
    assert compute_org_nr(no_name_statement) == "19999" 