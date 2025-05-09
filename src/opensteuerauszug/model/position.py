from typing import Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator

class BasePosition(BaseModel):
    depot: str

    def _comparison_key(self):
        # To be overridden by subclasses for relevant fields
        return (self.depot,)

    def __eq__(self, other):
        if not isinstance(other, BasePosition):
            return NotImplemented
        return self._comparison_key() == other._comparison_key()

    def __hash__(self):
        return hash(self._comparison_key())

class CashPosition(BasePosition):
    type: Literal["cash"] = "cash"
    currentCy: str = Field(default="USD", description="Currency code for cash position")
    cash_account_id: Optional[str] = Field(default=None, description="Optional identifier for a specific cash account within the same depot and currency")

    def _comparison_key(self):
        return (self.depot, self.currentCy, self.cash_account_id)

class SecurityPosition(BasePosition):
    """
    Security position model. Equality and hash ignore 'description' and 'security_type'.
    """
    type: Literal["security"] = "security"
    valor: Optional[str] = None
    isin: Optional[str] = None
    symbol: str
    security_type: Optional[str] = Field(default=None, alias="securityType", description="Type of security, if available")
    description: Optional[str] = Field(default=None, description="Description of the security from the import file")

    def _comparison_key(self):
        return (self.depot, self.valor, self.isin, self.symbol)

    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v):
        if not v or ' ' in v:
            raise ValueError("Symbol must not be empty and must not contain spaces")
        return v

    @field_validator('security_type')
    @classmethod
    def validate_security_type(cls, v):
        # Allow None or empty
        return v

Position = Union[CashPosition, SecurityPosition] 