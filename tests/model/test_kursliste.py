import pytest
from decimal import Decimal
from pathlib import Path

from src.opensteuerauszug.model.kursliste import (
    Kursliste, Security, Bond, Share, Fund
)

class TestKurslisteFindMethods:
    """Tests for the security lookup methods in Kursliste."""
    
    @pytest.fixture
    def sample_kursliste(self) -> Kursliste:
        """Create a sample Kursliste with various securities for testing."""
        kursliste = Kursliste(
            version="2.0.0.1",
            creationDate="2023-01-01T12:00:00",
            year=2023
        )
        
        # Add some test securities
        # Bond with valor 123456
        bond = Bond(
            id=1,
            valorNumber=123456,
            isin="CH0001234567",
            securityGroup="BOND",
            securityType="BOND.BOND",
            securityName="Test Bond",
            institutionId=1,
            institutionName="Test Institution",
            country="CH",
            currency="CHF",
            nominalValue=Decimal("1000")
        )
        kursliste.bonds.append(bond)
        
        # Share with valor 234567
        share = Share(
            id=2,
            valorNumber=234567,
            isin="CH0002345678",
            securityGroup="SHARE",
            securityType="SHARE.COMMON",
            securityName="Test Share",
            institutionId=1,
            institutionName="Test Institution",
            country="CH",
            currency="CHF",
            nominalValue=Decimal("100")
        )
        kursliste.shares.append(share)
        
        # Fund with valor 345678
        fund = Fund(
            id=3,
            valorNumber=345678,
            isin="CH0003456789",
            securityGroup="FUND",
            securityType="FUND.DISTRIBUTION",
            securityName="Test Fund",
            institutionId=1,
            institutionName="Test Institution",
            country="CH",
            currency="CHF",
            nominalValue=Decimal("100")
        )
        kursliste.funds.append(fund)
        
        # Another share with the same ISIN as the first share (for testing multiple results)
        duplicate_share = Share(
            id=4,
            valorNumber=456789,
            isin="CH0002345678",  # Same ISIN as the first share
            securityGroup="SHARE",
            securityType="SHARE.PREFERRED",
            securityName="Test Share Preferred",
            institutionId=1,
            institutionName="Test Institution",
            country="CH",
            currency="CHF",
            nominalValue=Decimal("100")
        )
        kursliste.shares.append(duplicate_share)
        
        return kursliste
    
    def test_existing_security_can_be_found_by_valor(self, sample_kursliste):
        """Verify that an existing security can be found by its valor number."""
        security = sample_kursliste.find_security_by_valor(123456)
        assert security is not None
        assert security.valorNumber == 123456
        assert security.securityName == "Test Bond"
        assert security.securityGroup == "BOND"
    
    def test_nonexistent_valor_returns_none(self, sample_kursliste):
        """Verify that searching for a non-existent valor returns None."""
        security = sample_kursliste.find_security_by_valor(999999)
        assert security is None
    
    def test_existing_security_can_be_found_by_isin(self, sample_kursliste):
        """Verify that an existing security can be found by its ISIN."""
        security = sample_kursliste.find_security_by_isin("CH0001234567")
        assert security is not None
        assert security.isin == "CH0001234567"
        assert security.securityName == "Test Bond"
    
    def test_nonexistent_isin_returns_none(self, sample_kursliste):
        """Verify that searching for a non-existent ISIN returns None."""
        security = sample_kursliste.find_security_by_isin("CH9999999999")
        assert security is None
    
    def test_find_securities_by_valor_returns_all_matches(self, sample_kursliste):
        """Verify that find_securities_by_valor returns all matching securities."""
        securities = sample_kursliste.find_securities_by_valor(123456)
        assert len(securities) == 1
        assert securities[0].valorNumber == 123456
        assert securities[0].securityName == "Test Bond"
    
    def test_find_securities_by_valor_returns_empty_list_when_no_matches(self, sample_kursliste):
        """Verify that find_securities_by_valor returns an empty list when no matches are found."""
        securities = sample_kursliste.find_securities_by_valor(999999)
        assert len(securities) == 0
        assert isinstance(securities, list)
    
    def test_find_securities_by_isin_returns_all_matches(self, sample_kursliste):
        """Verify that find_securities_by_isin returns all matching securities."""
        securities = sample_kursliste.find_securities_by_isin("CH0002345678")
        assert len(securities) == 2
        assert all(security.isin == "CH0002345678" for security in securities)
        assert any(security.securityName == "Test Share" for security in securities)
        assert any(security.securityName == "Test Share Preferred" for security in securities)
    
    def test_find_securities_by_isin_returns_empty_list_when_no_matches(self, sample_kursliste):
        """Verify that find_securities_by_isin returns an empty list when no matches are found."""
        securities = sample_kursliste.find_securities_by_isin("CH9999999999")
        assert len(securities) == 0
        assert isinstance(securities, list)
