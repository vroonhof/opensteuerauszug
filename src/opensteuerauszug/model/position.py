from typing import Optional, Union, Literal, List, Any
from pydantic import BaseModel, Field, field_validator, PrivateAttr

from opensteuerauszug.model.ech0196 import ISINType, ValorNumber

class BasePosition(BaseModel):
    depot: str

    model_config = {
        "frozen": True,
        "arbitrary_types_allowed": True,
    }

    def _comparison_key(self):
        # To be overridden by subclasses for relevant fields
        return (self.depot,)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, BasePosition):
            return NotImplemented
        return self._comparison_key() == other._comparison_key()

    def __hash__(self):
        return hash(self._comparison_key())

    def get_processing_identifier(self) -> str:
        """Returns a string identifier for processing and logging."""
        raise NotImplementedError("Subclasses must implement this method.")

    def get_balance_name_prefix(self) -> str:
        """Returns a prefix for naming opening/closing balances (e.g., 'Cash ')."""
        raise NotImplementedError("Subclasses must implement this method.")

class CashPosition(BasePosition):
    type: Literal["cash"] = "cash"
    currentCy: str = Field(default="USD", description="Currency code for cash position")
    cash_account_id: Optional[str] = Field(default=None, description="Optional identifier for a specific cash account within the same depot and currency")
    _identifier_str: Optional[str] = PrivateAttr(default=None)

    model_config = {
        "frozen": True,
        "arbitrary_types_allowed": True,
    }

    def _comparison_key(self):
        return (self.depot, self.currentCy, self.cash_account_id)

    def get_processing_identifier(self) -> str:
        if self._identifier_str is None:
            self._identifier_str = f"Cash-{self.depot}-{self.cash_account_id}-{self.currentCy}"
        return self._identifier_str

    def get_balance_name_prefix(self) -> str:
        return "Cash "

class SecurityPosition(BasePosition):
    """
    Security position model. Equality and hash ignore 'description' and 'security_type'.
    """
    type: Literal["security"] = "security"
    valor: Optional[ValorNumber] = None
    isin: Optional[ISINType] = Field(default=None, pattern=r"[A-Z]{2}[A-Z0-9]{9}[0-9]{1}")
    symbol: str
    security_type: Optional[str] = Field(default=None, alias="securityType", description="Type of security, if available")
    description: Optional[str] = Field(default=None, description="Description of the security from the import file")
    _identifier_str: Optional[str] = PrivateAttr(default=None)

    def _comparison_key(self):
        return (self.depot, self.valor, self.isin, self.symbol)

    def get_processing_identifier(self) -> str:
        if self._identifier_str is None:
            self._identifier_str = f"{self.depot}-{self.symbol}"
        return self._identifier_str

    def get_balance_name_prefix(self) -> str:
        return ""

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
    
    model_config = {
        "arbitrary_types_allowed": True,
        "frozen": True,
    }


Position = Union[CashPosition, SecurityPosition] 