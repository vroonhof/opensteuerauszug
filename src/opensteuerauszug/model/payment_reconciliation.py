from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class PaymentReconciliationRow(BaseModel):
    country: str
    security: str
    payment_date: date
    kursliste_dividend_chf: Decimal = Field(default=Decimal("0"))
    kursliste_withholding_chf: Decimal = Field(default=Decimal("0"))
    broker_dividend_amount: Optional[Decimal] = None
    broker_dividend_currency: Optional[str] = None
    broker_withholding_amount: Optional[Decimal] = None
    broker_withholding_currency: Optional[str] = None
    broker_withholding_entry_text: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    accumulating: bool = False
    matched: bool = False
    status: str = "mismatch"
    note: Optional[str] = None


class PaymentReconciliationReport(BaseModel):
    rows: List[PaymentReconciliationRow] = Field(default_factory=list)
    match_count: int = 0
    mismatch_count: int = 0
    expected_missing_count: int = 0
