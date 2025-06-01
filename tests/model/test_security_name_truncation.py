"""Tests for security name truncation functionality."""

import pytest
from src.opensteuerauszug.model.ech0196 import Security


class TestSecurityNameTruncation:
    """Test cases for the security name truncation validator."""
    
    def test_short_name_not_truncated(self):
        """Test that names under 60 characters are not truncated."""
        short_name = "Apple Inc"
        security = Security(
            positionId=1,
            country='US',
            currency='USD',
            quotationType='PIECE',
            securityCategory='SHARE',
            securityName=short_name
        )
        assert security.securityName == short_name
        assert len(security.securityName) == len(short_name)

    def test_exact_60_char_name_not_truncated(self):
        """Test that names exactly 60 characters are not truncated."""
        exact_name = "A" * 60  # Exactly 60 characters
        security = Security(
            positionId=1,
            country='US',
            currency='USD',
            quotationType='PIECE',
            securityCategory='SHARE',
            securityName=exact_name
        )
        assert security.securityName == exact_name
        assert len(security.securityName) == 60

    def test_long_name_truncated_to_60_chars(self):
        """Test that names over 60 characters are truncated to exactly 60."""
        long_name = 'PICTET AM (EUROPE) (LU) PICTET SHORT-TERM MONEY MARKET (CHF) "P" INC'
        security = Security(
            positionId=1,
            country='CH',
            currency='CHF',
            quotationType='PIECE',
            securityCategory='FUND',
            securityName=long_name
        )
        assert len(security.securityName) == 60
        assert "..." in security.securityName
        
    def test_truncation_preserves_beginning_and_end(self):
        """Test that truncation preserves the beginning and end of the name."""
        long_name = 'PICTET AM (EUROPE) (LU) PICTET SHORT-TERM MONEY MARKET (CHF) "P" INC'
        security = Security(
            positionId=1,
            country='CH',
            currency='CHF',
            quotationType='PIECE',
            securityCategory='FUND',
            securityName=long_name
        )
        truncated = security.securityName
        
        # Should start with the beginning of the original name
        assert truncated.startswith('PICTET AM (EUROPE) (LU) PICTE')
        
        # Should end with the end of the original name
        assert truncated.endswith('M MONEY MARKET (CHF) "P" INC')
        
        # Should contain ellipsis
        assert "..." in truncated
        
    def test_very_long_name_truncation(self):
        """Test truncation with an extremely long name."""
        very_long_name = "A" * 200  # Very long name
        security = Security(
            positionId=1,
            country='US',
            currency='USD',
            quotationType='PIECE',
            securityCategory='SHARE',
            securityName=very_long_name
        )
        
        truncated = security.securityName
        assert len(truncated) == 60
        assert truncated.startswith("A" * 29)  # 29 A's at the start
        assert truncated.endswith("A" * 28)    # 28 A's at the end
        assert "..." in truncated
        
    def test_truncation_format_matches_expected(self):
        """Test that the truncation format matches the expected Pydantic-style format."""
        long_name = 'PICTET AM (EUROPE) (LU) PICTET SHORT-TERM MONEY MARKET (CHF) "P" INC'
        security = Security(
            positionId=1,
            country='CH',
            currency='CHF',
            quotationType='PIECE',
            securityCategory='FUND',
            securityName=long_name
        )
        
        # The expected result based on our algorithm:
        # 29 chars from start + "..." + 28 chars from end = 60 total
        expected = "PICTET AM (EUROPE) (LU) PICTE...M MONEY MARKET (CHF) \"P\" INC"
        assert security.securityName == expected
        
    def test_edge_case_61_chars(self):
        """Test truncation with a name just one character over the limit."""
        name_61_chars = "A" * 61
        security = Security(
            positionId=1,
            country='US',
            currency='USD',
            quotationType='PIECE',
            securityCategory='SHARE',
            securityName=name_61_chars
        )
        
        truncated = security.securityName
        assert len(truncated) == 60
        assert "..." in truncated
        
    def test_unicode_characters_handled_correctly(self):
        """Test that unicode characters are handled correctly in truncation."""
        # Create a long name with unicode characters
        unicode_name = "SOCIÉTÉ GÉNÉRALE S.A. - TRÈS LONG NOM AVEC CARACTÈRES SPÉCIAUX ÉÀÎÔÙ"
        security = Security(
            positionId=1,
            country='FR',
            currency='EUR',
            quotationType='PIECE',
            securityCategory='SHARE',
            securityName=unicode_name
        )
        
        truncated = security.securityName
        assert len(truncated) == 60
        assert "..." in truncated 