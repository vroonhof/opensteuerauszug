"""Tests for the security module in the core package."""

import pytest
from decimal import Decimal
from datetime import date
from typing import Optional, List

from opensteuerauszug.core.security import determine_security_type, SecurityType
from opensteuerauszug.model.ech0196 import (
    Security, SecurityPayment, CurrencyId, QuotationType, SecurityCategory, ValorNumber, ISINType
)


def create_test_security(
    country: str = "CH", 
    payments: Optional[List[SecurityPayment]] = None,
    with_nonrecoverable_tax: bool = False,
    with_usa_withholding: bool = False,
    with_revenue_a: bool = False,
    with_revenue_b: bool = False
) -> Security:
    """Helper to create test securities with different attributes."""
    if payments is None:
        payments = []
        
        # Add payment with specified attributes
        if with_nonrecoverable_tax or with_usa_withholding or with_revenue_a or with_revenue_b:
            payment = SecurityPayment(
                paymentDate=date(2023, 6, 30),
                quotationType="PIECE",
                quantity=Decimal("10"),
                amountCurrency=CurrencyId("CHF"),
                nonRecoverableTax=Decimal("15.00") if with_nonrecoverable_tax else None,
                additionalWithHoldingTaxUSA=Decimal("15.00") if with_usa_withholding else None,
                grossRevenueA=Decimal("100.00") if with_revenue_a else None,
                grossRevenueB=Decimal("100.00") if with_revenue_b else None
            )
            payments.append(payment)
    
    return Security(
        positionId=1,
        country=country,
        currency=CurrencyId("CHF"),
        quotationType="PIECE",
        securityCategory="SHARE",
        securityName="Test Security",
        payment=payments
    )


class TestSecurity:
    """Tests for security-related functions."""
    
    def test_determine_security_type_da1_nonrecoverable(self):
        """Test DA1 determination with non-recoverable tax."""
        security = create_test_security(with_nonrecoverable_tax=True)
        assert determine_security_type(security) == "DA1"
    
    def test_determine_security_type_da1_usa_withholding(self):
        """Test DA1 determination with USA withholding tax."""
        security = create_test_security(with_usa_withholding=True)
        assert determine_security_type(security) == "DA1"
    
    def test_determine_security_type_a_with_revenue(self):
        """Test type A determination with revenue A."""
        security = create_test_security(with_revenue_a=True)
        assert determine_security_type(security) == "A"
    
    def test_determine_security_type_a_swiss_no_revenue(self):
        """Test type A determination for Swiss security without revenue."""
        security = create_test_security(country="CH")
        assert determine_security_type(security) == "A"
    
    def test_determine_security_type_b_non_swiss_no_revenue(self):
        """Test type B determination for non-Swiss security without revenue."""
        security = create_test_security(country="US")
        assert determine_security_type(security) == "B"
    
    def test_determine_security_type_b_with_revenue_b(self):
        """Test type B determination with revenue B."""
        security = create_test_security(country="US", with_revenue_b=True)
        assert determine_security_type(security) == "B"
    
    def test_da1_takes_precedence(self):
        """Test that DA1 determination takes precedence over A or B."""
        # Security with both DA1 criteria and type A criteria
        security = create_test_security(
            with_nonrecoverable_tax=True,
            with_revenue_a=True
        )
        assert determine_security_type(security) == "DA1"
        
    def test_security_type_values(self):
        """Test that SecurityType accepts the correct values."""
        # This test verifies the type annotation works correctly
        # We're not testing any runtime behavior, just making sure the type exists
        values: List[SecurityType] = ["A", "B", "DA1"]
        assert len(values) == 3 