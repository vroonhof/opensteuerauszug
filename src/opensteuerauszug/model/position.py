from typing import Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator

class BasePosition(BaseModel):
    depot: str

class CashPosition(BasePosition):
    type: Literal["cash"] = "cash"
    currentCy: str = Field(default="USD", description="Currency code for cash position")

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

    def __eq__(self, other):
        if not isinstance(other, SecurityPosition):
            return NotImplemented
        return (
            self.depot == other.depot and
            self.valor == other.valor and
            self.isin == other.isin and
            self.symbol == other.symbol
        )

    def __hash__(self):
        return hash((self.depot, self.valor, self.isin, self.symbol))

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