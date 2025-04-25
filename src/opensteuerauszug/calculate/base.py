from enum import Enum
from typing import Any, Dict, List, Optional, Set, Type, TypeVar, Union, cast
from decimal import Decimal

from ..model.ech0196 import TaxStatement, BaseXmlModel

# Type variable for generic calculation handlers
T = TypeVar('T', bound=BaseXmlModel)

class CalculationMode(Enum):
    """Defines how calculations should be applied to the model."""
    VERIFY = "verify"  # Only verify values are correct, raise errors if not
    FILL = "fill"      # Fill in missing values, verify existing ones
    OVERWRITE = "overwrite"  # Calculate and overwrite all calculated fields

class CalculationError(Exception):
    """Exception raised when a calculation verification fails."""
    def __init__(self, field_path: str, expected: Any, actual: Any):
        self.field_path = field_path
        self.expected = expected
        self.actual = actual
        message = f"Calculation error at {field_path}: expected {expected}, got {actual}"
        super().__init__(message)

class BaseCalculator:
    """Base class for all calculators that process the tax statement model."""
    
    def __init__(self, mode: CalculationMode = CalculationMode.FILL):
        self.mode = mode
        self.errors: List[CalculationError] = []
        self.modified_fields: Set[str] = set()
    
    def calculate(self, tax_statement: TaxStatement) -> TaxStatement:
        """
        Process the tax statement according to the calculation mode.
        
        Args:
            tax_statement: The tax statement to process
            
        Returns:
            The processed tax statement
        """
        self.errors = []
        self.modified_fields = set()
        
        # Process the tax statement
        self._process_tax_statement(tax_statement)
        
        return tax_statement
    
    def _process_tax_statement(self, tax_statement: TaxStatement) -> None:
        """Process the main TaxStatement object. Subclasses can override this."""
        self._process_model(tax_statement, "")

    def _process_model(self, model: BaseXmlModel, path_prefix: str) -> None:
        """
        Recursively process a model and its nested models using a visitor pattern.
        
        Args:
            model: The model to process
            path_prefix: The path to this model from the root
        """
        # Call the appropriate handler method if it exists
        model_type = type(model)
        handler_name = f"_handle_{model_type.__name__}"
        handler = getattr(self, handler_name, None)
        
        if handler:
            handler(cast(Any, model), path_prefix)
        
        # Get all fields that are BaseXmlModel instances or lists of BaseXmlModel
        for field_name, field_value in model.__dict__.items():
            # Skip internal fields and unknown_attrs
            if field_name.startswith('_') or field_name == 'unknown_attrs':
                continue
                
            field_path = f"{path_prefix}.{field_name}" if path_prefix else field_name
            
            # Process lists of models
            if isinstance(field_value, list):
                for i, item in enumerate(field_value):
                    if isinstance(item, BaseXmlModel):
                        item_path = f"{field_path}[{i}]"
                        self._process_model(item, item_path)
            
            # Process nested models
            elif isinstance(field_value, BaseXmlModel):
                self._process_model(field_value, field_path)
    
    def _set_field_value(self, model: BaseXmlModel, field_name: str, value: Any, path: str) -> None:
        """
        Set a field value according to the calculation mode.
        
        Args:
            model: The model containing the field
            field_name: The name of the field to set
            value: The calculated value
            path: The full path to the field for error reporting
        """
        current_value = getattr(model, field_name, None)
        field_path = f"{path}.{field_name}" if path else field_name
        
        # Handle Decimal comparison with special care
        values_equal = current_value == value
        if isinstance(current_value, Decimal) and isinstance(value, (int, float, Decimal)):
            # Convert to Decimal for proper comparison
            value_as_decimal = Decimal(str(value)) if not isinstance(value, Decimal) else value
            values_equal = current_value == value_as_decimal
        
        # In VERIFY mode, check if the value matches
        if self.mode == CalculationMode.VERIFY:
            if current_value is not None and not values_equal:
                self.errors.append(CalculationError(field_path, value, current_value))
        
        # In FILL mode, only set if the field is None or empty
        elif self.mode == CalculationMode.FILL:
            if current_value is None or (isinstance(current_value, (str, list, dict)) and not current_value):
                setattr(model, field_name, value)
                self.modified_fields.add(field_path)
        
        # In OVERWRITE mode, always set the value
        elif self.mode == CalculationMode.OVERWRITE:
            setattr(model, field_name, value)
            self.modified_fields.add(field_path)
    
    def _compare_values(self, expected: Any, actual: Any) -> bool:
        """
        Compare two values with special handling for Decimal types.
        
        Args:
            expected: The expected value
            actual: The actual value
            
        Returns:
            True if the values are equal, False otherwise
        """
        if isinstance(expected, Decimal) or isinstance(actual, Decimal):
            # Convert both to Decimal for proper comparison
            try:
                expected_decimal = Decimal(str(expected)) if not isinstance(expected, Decimal) else expected
                actual_decimal = Decimal(str(actual)) if not isinstance(actual, Decimal) else actual
                return expected_decimal == actual_decimal
            except (ValueError, TypeError):
                return False
        
        return expected == actual
