"""Pydantic models for eCH-0196 Tax Statement standard."""

from pydantic import BaseModel, Field, validator, field_validator, StringConstraints, AfterValidator
from pydantic.fields import FieldInfo  # Import FieldInfo
from pydantic import ConfigDict  # Import ConfigDict for model_config
from pydantic_core import PydanticUndefined
from typing import (
    ClassVar,
    List,
    Optional,
    Any,
    Dict,
    TypeVar,
    Type,
    Union,
    get_origin,
    get_args,
    Literal,
    Annotated,
)
from datetime import date, datetime
from decimal import Decimal
import lxml.etree as ET
from inspect import isclass  # Add import for isclass function
import logging

logger = logging.getLogger(__name__)

# Define namespaces used in the XSD
NS_MAP = {
    None: "http://www.ech.ch/xmlns/eCH-0196/2",
    'xs': "http://www.w3.org/2001/XMLSchema",
    'eCH-0007': "http://www.ech.ch/xmlns/eCH-0007/6",
    'eCH-0008': "http://www.ech.ch/xmlns/eCH-0008/3",
    'eCH-0010': "http://www.ech.ch/xmlns/eCH-0010/7",
    'eCH-0097': "http://www.ech.ch/xmlns/eCH-0097/4",
    'eCH-0196': "http://www.ech.ch/xmlns/eCH-0196/2"
}

# Helper to get namespaced tag name
def ns_tag(prefix: str, tag: str) -> str:
    return f"{{{NS_MAP[prefix]}}}{tag}"

# --- Base Types based on XSD Simple Types (add more as needed) ---
# Using Optional[...] generously for partial model creation/dumping
# Specific validation (length, patterns) will be in the validate method or custom validators

# Placeholder simple types - replace with actual constraints later if needed
class BankAccountName(str): # maxLength: 40 - Handled by Field directly later
    pass
class BankAccountNumber(str): # minLength: 1, maxLength: 32 - Handled by Field directly later
    pass
class ClientNumber(str): # maxLength: 40 - Handled by Field directly later
    pass
# Add other simple types like currencyIdISO3Type, depotNumberType, etc.
CurrencyId = Annotated[str, Field(pattern=r"[A-Z]{3}", json_schema_extra={'is_attribute': True})]
class DepotNumber(str): # maxLength: 4
    pass
class ValorNumber(int): # positiveInteger, maxInclusive=999999999999, minInclusive=100
    """Valor number for security identification."""
    pass
class ISINType(str): # length=12, pattern="[A-Z]{2}[A-Z0-9]{9}[0-9]{1}"
    pass
class LEIType(str): # length=20, pattern="[A-Z0-9]{18}[0-9]{2}"
    pass
class TINType(str): # maxLength=40
    pass

# Explicit enumerations
# LiabilityCategoryType defined as string Literal
LiabilityCategory = Literal[
    "MORTGAGE", "LOAN", "OTHER"
]

# Liability category description mapping
LIABILITY_CATEGORY_DESCRIPTIONS = {
    "MORTGAGE": "Mortgage",
    "LOAN": "Loan",
    "OTHER": "Other"
}

# ExpenseTypeType defined as string Literal
ExpenseType = Literal[
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
    "31", "32", "33", "34", "35", "36", "37", "38", "39", "40",
    "41", "42", "43", "44", "99"
]

# ExpenseType description mapping
EXPENSE_TYPE_DESCRIPTIONS = {
    "1": "Stempelabgaben (Emissions- und Umsatzabgaben)",
    "2": "Transaktionskosten",
    "3": "Vorfälligkeitsentschädigungen",
    "4": "Administrationsgebühren (Verwaltungsgebühren)",
    "5": "Banklagernd",
    "6": "Beratungskosten",
    "7": "Kosten für das Ausfüllen von Formularen",
    "8": "Kosten für die Erstellung der Steuererklärung",
    "9": "Kosten für die Erstellung der Steuerunterlagen",
    "10": "Kosten für die Erstellung der Steuerverzeichnisse von Banken",
    "11": "Kosten der Vermögensumlagerung",
    "12": "Provisionen (Agent Fee)",
    "13": "Treuhandkommissionen / Treuhandgebühren",
    "14": "Vermittlungsgebühren",
    "15": "Vermögensverwaltungskosten (aktives Depotmanagement)",
    "16": "Verrechenbare Courtagegebühren aus IUP",
    "17": "Abgezogene Quellensteuer",
    "18": "Affidavitspesen",
    "19": "All-in Fee",
    "20": "Auslieferung Edelmetalle",
    "21": "Auslieferungsspesen / Titellieferungsgebühren",
    "22": "Depotgebühren",
    "23": "Gebühren für Bescheinigungen",
    "24": "Inkassospesen",
    "25": "Kontoführungsgebühren",
    "26": "Kosten für eigene Bemühungen",
    "27": "Managementgebühren",
    "28": "Metallkontokommissionen",
    "29": "Negativzinsen (im Privatvermögen)",
    "30": "Nummernkontogebühren",
    "31": "Pauschalgebühren / Verwaltungsgebühren",
    "32": "Performanceorientierte / Erfolgsorientierte Honorare",
    "33": "Porto / Versandkosten",
    "34": "Saldierungsspesen",
    "35": "Tresorfachgebühren / Schrankfachgebühren",
    "36": "Absicherungskosten",
    "37": "Diverse Gebühren",
    "38": "Devisenkurssicherungskosten",
    "39": "Externe Gebühren / Fremdspesen",
    "40": "Kartengebühren / Kreditkartengebühren",
    "41": "Kreditgebühren / Kreditkommissionen",
    "42": "Nichtkündigungsabzug",
    "43": "Zessionskommission",
    "44": "Erstellung/Erhöhung Schuldbriefe",
    "99": "Sonstige unqualifizierte Begriffe"
}

# SecurityCategoryType defined as string Literal
SecurityCategory = Literal[
    "BOND", "COINBULL", "CURRNOTE", "DEVT", "FUND", 
    "LIBOSWAP", "OPTION", "OTHER", "SHARE"
]

# Security category description mapping
SECURITY_CATEGORY_DESCRIPTIONS = {
    "BOND": "Bond",
    "COINBULL": "Coin/Bullion",
    "CURRNOTE": "Currency/Banknote",
    "DEVT": "Derivative",
    "FUND": "Fund",
    "LIBOSWAP": "LIBOR/Swap",
    "OPTION": "Option",
    "OTHER": "Other",
    "SHARE": "Share"
}

# SecurityTypeType defined as string Literal
SecurityType = Literal[
    "BOND.BOND", "BOND.OPTION", "BOND.CONVERTIBLE",
    "COINBULL.COINGOLD", "COINBULL.GOLD", "COINBULL.PALLADIUM", "COINBULL.PLATINUM", "COINBULL.SILVER",
    "CURRNOTE.CURRENCY", "CURRNOTE.CURRYEAR",
    "DEVT.COMBINEDPRODUCT", "DEVT.FUNDSIMILARASSET", "DEVT.INDEXBASKET",
    "FUND.ACCUMULATION", "FUND.DISTRIBUTION", "FUND.REALESTATE",
    "LIBOSWAP.LIBOR", "LIBOSWAP.SWAP",
    "OPTION.CALL", "OPTION.PHANTOM", "OPTION.PUT",
    "SHARE.BEARERCERT", "SHARE.BONUS", "SHARE.COMMON", "SHARE.COOP", 
    "SHARE.LIMITED", "SHARE.NOMINAL", "SHARE.PARTCERT", "SHARE.PREFERRED", "SHARE.TRANSFERABLE"
]

# Security type description mapping
SECURITY_TYPE_DESCRIPTIONS = {
    "BOND.BOND": "Bond",
    "BOND.OPTION": "Option Bond",
    "BOND.CONVERTIBLE": "Convertible Bond",
    "COINBULL.COINGOLD": "Gold Coin",
    "COINBULL.GOLD": "Gold",
    "COINBULL.PALLADIUM": "Palladium",
    "COINBULL.PLATINUM": "Platinum",
    "COINBULL.SILVER": "Silver",
    "CURRNOTE.CURRENCY": "Currency",
    "CURRNOTE.CURRYEAR": "Current Year Currency",
    "DEVT.COMBINEDPRODUCT": "Combined Product",
    "DEVT.FUNDSIMILARASSET": "Fund-Similar Asset",
    "DEVT.INDEXBASKET": "Index/Basket",
    "FUND.ACCUMULATION": "Accumulation Fund",
    "FUND.DISTRIBUTION": "Distribution Fund",
    "FUND.REALESTATE": "Real Estate Fund",
    "LIBOSWAP.LIBOR": "LIBOR",
    "LIBOSWAP.SWAP": "Swap",
    "OPTION.CALL": "Call Option",
    "OPTION.PHANTOM": "Phantom Option",
    "OPTION.PUT": "Put Option",
    "SHARE.BEARERCERT": "Bearer Certificate",
    "SHARE.BONUS": "Bonus Share",
    "SHARE.COMMON": "Common Share",
    "SHARE.COOP": "Cooperative Share",
    "SHARE.LIMITED": "Limited Share",
    "SHARE.NOMINAL": "Nominal Share",
    "SHARE.PARTCERT": "Participation Certificate",
    "SHARE.PREFERRED": "Preferred Share",
    "SHARE.TRANSFERABLE": "Transferable Share"
}

QuotationType = Literal["PIECE", "PERCENT"]

def check_positive(v: Decimal) -> Decimal:
    if v < Decimal(0):
        raise ValueError(f"Value must be positive, got {v}")
    return v
PositiveDecimal = Annotated[Decimal, AfterValidator(check_positive)]


def get_expense_description(expense_code: ExpenseType) -> str:
    """Get the description of an expense type based on its code."""
    return EXPENSE_TYPE_DESCRIPTIONS.get(expense_code, "Unknown expense type")

def get_security_category_description(category_code: SecurityCategory) -> str:
    """Get the description of a security category based on its code."""
    return SECURITY_CATEGORY_DESCRIPTIONS.get(category_code, "Unknown security category")

def get_security_type_description(type_code: SecurityType) -> str:
    """Get the description of a security type based on its code."""
    return SECURITY_TYPE_DESCRIPTIONS.get(type_code, "Unknown security type")

def get_liability_category_description(category_code: LiabilityCategory) -> str:
    """Get the description of a liability category based on its code."""
    return LIABILITY_CATEGORY_DESCRIPTIONS.get(category_code, "Unknown liability category")

# --- Types based on imported eCH standards ---

# eCH-0007 V6.0
# Use Literal for actual validation against the XSD enum
CantonAbbreviation = Literal[
    "ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "FR", "SO",
    "BS", "BL", "SH", "AR", "AI", "SG", "GR", "AG", "TG", "TI", "VD",
    "VS", "NE", "GE", "JU"
]

# eCH-0008 V3.0
CountryIdISO2Type = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Z]{2}$",
        to_upper=True,
        min_length=2,
        max_length=2
    )
]

# eCH-0010 V7.0
OrganisationName = Annotated[str, StringConstraints(max_length=60)]

MrMrs = Literal["1", "2", "3"] # 1: Unknown, 2: Mr, 3: Mrs/Ms (approximation)
# More descriptive definition for MrMrsType
MrMrsCodes = {
    "1": "Unknown",
    "2": "Mr",
    "3": "Mrs/Ms"
}

# Helper function to get salutation description
def get_salutation_description(salutation_code: MrMrs) -> str:
    """Get the description of a salutation based on its code."""
    return MrMrsCodes.get(salutation_code, "Unknown salutation")

FirstName = Annotated[str, StringConstraints(max_length=30)]
LastName = Annotated[str, StringConstraints(max_length=30)]

# --- Placeholder for complex types referenced by import ---
# These would ideally be generated/defined based on the importe

# Generic Type Variable for Pydantic models
M = TypeVar('M', bound='BaseXmlModel')

# --- Base Model with XML capabilities (Pydantic v2 adjusted) ---
class BaseXmlModel(BaseModel):
    unknown_attrs: Dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)
    unknown_elements: List[Any] = Field(default_factory=list, exclude=True, repr=False)

    model_config: ClassVar[ConfigDict] = {
        "arbitrary_types_allowed": True,
        "extra": "allow",  # Allow extra attributes like we had in Config
    }
    
    # Class variable for strict parsing that can be overridden by subclasses
    # Mark as excluded so it doesn't show up in XML
    strict_parsing: bool = Field(default=False, exclude=True, repr=False)

    @staticmethod
    def _iter_element(element: ET._Element) -> List[ET._Element]:
        """Helper method to get list of child elements, addressing lxml typing issue.
        
        This method helps with type checking when iterating over lxml elements.
        """
        # Use xpath to get all child elements - this is safer for typing
        return element.xpath('./*')
        
    @classmethod
    def _parse_attributes(cls: Type[M], element: ET._Element, strict: Optional[bool] = None) -> Dict[str, Any]:
        """Parse XML element attributes into a dictionary.
        
        Args:
            element: The XML element to parse attributes from
            strict: If True, raise errors for unknown attributes. If None, use class config.
        
        Returns:
            Dictionary of attribute name to parsed value
        
        Raises:
            ValueError: If strict is True and an unknown attribute is encountered
        """
        # Determine strictness from parameter or class config
        strict_mode = strict if strict is not None else cls.model_config.get('strict_parsing', False)
        
        data = {}
        known_attrs = { field_info.alias or name
                        for name, field_info in cls.model_fields.items()
                        if field_info.json_schema_extra and field_info.json_schema_extra.get("is_attribute") }
        unknown_attrs = {}
        for name, value in element.attrib.items():
            # Find the field corresponding to this attribute name
            field_name = next((fn for fn, fi in cls.model_fields.items() if (fi.alias or fn) == name), None)

            if field_name:
                field_info = cls.model_fields[field_name]
                field_type = field_info.annotation
                origin_type = get_origin(field_type)
                type_args = get_args(field_type)
                is_annotated = origin_type is Annotated

                # Handle Optional[T]
                actual_type = field_type
                if origin_type is Union and type(None) in type_args:
                   actual_type = next((t for t in type_args if t is not type(None)), str) # type: ignore # Use str as fallback
                   origin_type = get_origin(actual_type) # Re-check origin after stripping Optional
                   type_args = get_args(actual_type)
                   is_annotated = origin_type is Annotated
                   if actual_type is None: actual_type = str # Fallback if only Optional[None]

                # If it was Annotated[T, ...], get the base type T
                base_type = actual_type
                if is_annotated:
                    base_type = type_args[0]
                    origin_type = get_origin(base_type) # Use origin of base type for checks

                try:
                    parsed_value: Any = None
                    # Check for Literal origin *before* trying to call the type
                    if origin_type is Literal:
                        parsed_value = value # Assign string directly for Literal
                    elif base_type == Decimal:
                        parsed_value = Decimal(value)
                    elif base_type == int:
                        parsed_value = int(value)
                    elif base_type == date:
                        parsed_value = date.fromisoformat(value)
                    elif base_type == datetime:
                        parsed_value = datetime.fromisoformat(value)
                    elif base_type == bool:
                        parsed_value = value.lower() in ('true', '1')
                    elif base_type == bytes: # Handle base64Binary
                         # TODO: Implement base64 decoding if needed for fileData
                         parsed_value = value # Store as string for now
                    else:
                         # Assume string or custom type derived from string
                         # Check if base_type is callable before calling
                         parsed_value = base_type(value) if callable(base_type) else value
                    data[field_name] = parsed_value
                except (ValueError, TypeError) as e:
                    logger.warning(
                        "Could not parse attribute '%s'='%s' as %s: %s",
                        name,
                        value,
                        base_type,
                        e,
                    )
                    if strict_mode:
                        raise ValueError(
                            f"Could not parse attribute '{name}'='{value}' as {base_type}: {e}"
                        )
                    unknown_attrs[name] = value
            elif name not in known_attrs:
                # Check for XML namespace declarations if needed (e.g., xmlns:prefix=\"...\")
                if not (name.startswith('{http://www.w3.org/2000/xmlns/}') 
                        or name.startswith('{http://www.w3.org/2001/XMLSchema-instance}')):
                    if strict_mode:
                        raise ValueError(f"Unknown attribute: {name}")  
                    unknown_attrs[name] = value
        if unknown_attrs:
            data['unknown_attrs'] = unknown_attrs
        return data

    def _build_attributes(self, element: ET._Element):
        for name, field_info in self.__class__.model_fields.items():
            if field_info.json_schema_extra and field_info.json_schema_extra.get("is_attribute"):
                value = getattr(self, name, None)
                # print(f"Building attribute {name} with value {value}")
                if value is not None:
                    attr_name = field_info.alias or name
                    # Basic type conversion to string
                    str_value: str
                    if isinstance(value, (date, datetime)):
                        str_value = value.isoformat()
                    elif isinstance(value, bool):
                        if value:
                            str_value = "1"
                        else:
                            if field_info.default is PydanticUndefined:
                                str_value = "0"
                            else:
                                continue
                    elif isinstance(value, bytes):
                        # TODO: Implement base64 encoding if needed for fileData
                        raise NotImplementedError("Base64 encoding is not implemented")
                    elif isinstance(value, Decimal):
                        # Format Decimal as a plain string to avoid scientific notation
                        str_value = f'{value:f}'
                    else:
                        str_value = str(value)
                    element.set(attr_name, str_value)
        # Add unknown attributes back for round-tripping
        for name, value in self.unknown_attrs.items():
             # Avoid writing xmlns attributes if they are handled by lxml nsmap
             if not name.startswith('{http://www.w3.org/2000/xmlns/}'):
                element.set(name, value)

    @classmethod
    def _parse_children(cls: Type[M], element: ET._Element, strict: Optional[bool] = None) -> Dict[str, Any]:
        """Parse XML child elements into a dictionary.
        
        Args:
            element: The XML element to parse children from
            strict: If True, raise errors for unknown elements. If None, use class config.
        
        Returns:
            Dictionary of child element name to parsed value
        
        Raises:
            ValueError: If strict is True and an unknown element is encountered
        """
        # Determine strictness from parameter or class config
        strict_mode = strict if strict is not None else cls.model_config.get('strict_parsing', False)
        
        data = {}
        # All child element fields that aren't marked as attributes
        # Map from tag -> field name
        tag_map = {}
        element_fields = []
        unknown_elements = []

        for name, field_info in cls.model_fields.items():
            # Skip attributes
            if field_info.json_schema_extra and field_info.json_schema_extra.get("is_attribute"):
                continue
            # Skip fields to exclude at XML level
            if field_info.exclude:
                continue
            tag_name = None
            tag_ns = None
            # Check field extra info (or class extra) for tag name
            if field_info.json_schema_extra:
                extra_info = field_info.json_schema_extra
                # Tag name from field's extra info
                if isinstance(extra_info, dict) and 'tag_name' in extra_info:
                    tag_name = extra_info.get('tag_name')
                # Namespace from field's extra info
                if isinstance(extra_info, dict) and 'tag_namespace' in extra_info:
                    tag_ns = extra_info.get('tag_namespace')

            # Fallback: use field name or alias for tag name
            if not tag_name:
                tag_name = field_info.alias or name

            # If namespace provided, use qualified tag with namespace
            if tag_ns:
                if tag_ns in NS_MAP:
                    ns_pfx = NS_MAP[tag_ns]
                    qualified_tag = f"{{{ns_pfx}}}{tag_name}"
                else:
                    qualified_tag = f"{{{tag_ns}}}{tag_name}"
            else:
                qualified_tag = tag_name

            element_fields.append((name, field_info))
            tag_map[qualified_tag] = name

        # Process all child elements
        for child in cls._iter_element(element):
            if child.tag in tag_map:
                field_name = tag_map[child.tag]
                field_info = cls.model_fields[field_name]
                field_type = field_info.annotation
                origin_type = get_origin(field_type)

                # Handle Optional[T]
                actual_type = field_type
                if origin_type is Union and type(None) in get_args(field_type):
                    # Extract the actual type from Optional[T]
                    non_none_types = [t for t in get_args(field_type) if t is not type(None)]
                    if non_none_types:
                        actual_type = non_none_types[0]  # Use first non-None type
                        origin_type = get_origin(actual_type)
                        inner_args = get_args(actual_type)
                        # If the actual_type is a class with _from_xml_element, we can parse it
                        if isclass(actual_type) and hasattr(actual_type, '_from_xml_element'):
                            try:
                                parsed_item = actual_type._from_xml_element(child, strict=strict_mode)
                                data[field_name] = parsed_item
                                continue  # Successfully parsed Optional[Class] field
                            except Exception as e:
                                logger.warning(
                                    "Failed to parse child element <%s> as %s: %s",
                                    child.tag,
                                    actual_type,
                                    e,
                                )
                                if strict_mode:
                                    raise ValueError(f"Failed to parse child element <{child.tag}> as {actual_type}: {e}")
                                unknown_elements.append(child)
                                continue

                # Handle Literal type
                if origin_type is Literal:
                    # For Literals, we just use the text value directly
                    if child.text:
                        literal_values = get_args(field_type)
                        child_text = child.text.strip()
                        if child_text in literal_values:
                            data[field_name] = child_text
                        else:
                            error_msg = f"Invalid value '{child_text}' for Literal field, expected one of: {literal_values}"
                            logger.warning(error_msg)
                            if strict_mode:
                                raise ValueError(error_msg)
                            unknown_elements.append(child)
                    continue

                # List handling
                if origin_type in (list, List):
                    item_type = get_args(field_type)[0]
                    if not isclass(item_type):
                        # Handle List[Union[..]] etc.
                        item_origin = get_origin(item_type)
                        if item_origin:
                            item_type = get_args(item_type)[0]  # Use first type arg (might need refinement)

                    # For simple types, extract the plain text value if present
                    if item_type in (str, int, float, bool, Decimal, date, datetime):
                        if child.text is not None:
                            try:
                                # Use a conversion based on the type
                                if item_type == str:
                                    value = child.text.strip()
                                elif item_type == int:
                                    value = int(child.text.strip())
                                elif item_type == float:
                                    value = float(child.text.strip())
                                elif item_type == bool:
                                    value = child.text.strip().lower() in ('true', '1', 'yes')
                                elif item_type == Decimal:
                                    value = Decimal(child.text.strip())
                                elif item_type == date:
                                    value = date.fromisoformat(child.text.strip())
                                elif item_type == datetime:
                                    value = datetime.fromisoformat(child.text.strip())
                                else:
                                    value = child.text.strip()
                            except (ValueError, TypeError) as e:
                                logger.warning(
                                    "Could not parse element <%s> content '%s' as %s: %s",
                                    child.tag,
                                    child.text,
                                    item_type,
                                    e,
                                )
                                if strict_mode:
                                    raise ValueError(f"Could not parse element <{child.tag}> content '{child.text}' as {item_type}: {e}")  
                                unknown_elements.append(child)
                                continue  # Skip adding to field data
                            if field_name not in data:
                                data[field_name] = []
                            data[field_name].append(value)
                    # For complex types, delegate to the subclass's XML parser
                    elif hasattr(item_type, '_from_xml_element'):
                        try:
                            parsed_item = item_type._from_xml_element(child, strict=strict_mode)
                            if field_name not in data:
                                data[field_name] = []
                            data[field_name].append(parsed_item)
                        except Exception as e:
                            logger.warning(
                                "Failed to parse child element <%s> as %s: %s",
                                child.tag,
                                item_type,
                                e,
                            )
                            if strict_mode:
                                raise ValueError(f"Failed to parse child element <{child.tag}> as {item_type}: {e}")
                            unknown_elements.append(child)
                    else:
                        logger.warning(
                            "Unsupported item type for list field: %s for tag %s",
                            item_type,
                            child.tag,
                        )
                        if strict_mode:
                            raise ValueError(f"Unsupported item type for list field: {item_type} for tag {child.tag}")
                        unknown_elements.append(child)
                # Direct submodel handling
                elif isclass(field_type) and hasattr(field_type, '_from_xml_element'):
                    try:
                        parsed_item = field_type._from_xml_element(child, strict=strict_mode)
                        data[field_name] = parsed_item
                    except Exception as e:
                        logger.warning(
                            "Failed to parse child element <%s> as %s: %s",
                            child.tag,
                            field_type,
                            e,
                        )
                        if strict_mode:
                            raise ValueError(f"Failed to parse child element <{child.tag}> as {field_type}: {e}")
                        unknown_elements.append(child)
                # Simple direct value case
                elif field_type in (str, int, float, bool, Decimal, date, datetime):
                    if child.text is not None:
                        try:
                            # Use a conversion based on the type
                            if field_type == str:
                                value = child.text.strip()
                            elif field_type == int:
                                value = int(child.text.strip())
                            elif field_type == float:
                                value = float(child.text.strip())
                            elif field_type == bool:
                                value = child.text.strip().lower() in ('true', '1', 'yes')
                            elif field_type == Decimal:
                                value = Decimal(child.text.strip())
                            elif field_type == date:
                                value = date.fromisoformat(child.text.strip())
                            elif field_type == datetime:
                                value = datetime.fromisoformat(child.text.strip())
                            else:
                                value = child.text.strip()
                            data[field_name] = value
                        except (ValueError, TypeError) as e:
                            logger.warning(
                                "Could not parse element <%s> content '%s' as %s: %s",
                                child.tag,
                                child.text,
                                field_type,
                                e,
                            )
                            if strict_mode:
                                raise ValueError(f"Could not parse element <{child.tag}> content '{child.text}' as {field_type}: {e}")
                            unknown_elements.append(child)
                else:
                    # Unknown complex type - we might need more handling here
                    logger.warning(
                        "Unsupported field type for element <%s>: %s",
                        child.tag,
                        field_type,
                    )
                    if strict_mode:
                        raise ValueError(f"Unsupported field type for element <{child.tag}>: {field_type}")
                    unknown_elements.append(child)
            else:
                # Handle unknown elements / ##other namespace elements
                if strict_mode:
                    raise ValueError(f"Unknown element <{child.tag}> in namespace {child.nsmap} - content '{child.text}'") 
                unknown_elements.append(child)  # Store the raw lxml element
        
        if unknown_elements:
            data['unknown_elements'] = unknown_elements
        return data

    def _build_children(self, parent_element: ET._Element):
        tag_map = {}
        for name, field_info in self.__class__.model_fields.items():
            extra = field_info.json_schema_extra or {}
            # Skip excluded fields and attributes
            if field_info.exclude or extra.get("is_attribute"):
                continue
            ns = extra.get("tag_namespace", NS_MAP['eCH-0196'])
            local_name = field_info.alias or name
            tag_map[name] = (ns, local_name)

        for name, field_info in self.__class__.model_fields.items():
            # Skip excluded fields
            if field_info.exclude:
                continue
            if name in tag_map:
                value = getattr(self, name, None)
                if value is None:
                    continue

                ns_uri, local_name = tag_map[name]
                # Construct tag name correctly using lxml helper if ns_uri is present
                if ns_uri:
                    tag_name = f"{{{ns_uri}}}{local_name}"
                    # Ensure namespace is defined in the parent or globally if needed
                    # ET.register_namespace might be needed, or pass nsmap to Element
                else:
                    tag_name = local_name # No namespace

                values_to_process = value if isinstance(value, list) else [value]

                for item in values_to_process:
                    if item is None: continue

                    # Determine namespace prefix for the element
                    prefix = next((p for p, u in NS_MAP.items() if u == ns_uri), None)
                    nsmap_for_element = {prefix: ns_uri} if prefix and ns_uri else ( {None: ns_uri} if ns_uri else None)

                    if isinstance(item, BaseXmlModel):
                        # Pass nsmap to ensure prefix is defined if needed
                        item._build_xml_element(parent_element, tag_name)
                    else:
                        # Handle simple text content
                        child_element = ET.SubElement(parent_element, tag_name, attrib={}, nsmap=nsmap_for_element)
                        child_element.text = str(item) # Basic handling

        # Add unknown elements back for round-tripping
        for unknown in self.unknown_elements:
            # We stored raw lxml elements, so just append them
            # Ensure they are deepcopied if necessary to avoid issues when appending to different trees
            from copy import deepcopy
            parent_element.append(deepcopy(unknown))

    def _build_xml_element(self, 
                    parent_element: Optional[ET._Element] = None, 
                    name: Optional[str] = None) -> ET._Element:
        """Build XML element from this model instance."""
        # Determine tag name: specified name, or from config, or class name
        tag_name = None
        ns = NS_MAP['eCH-0196']  # Default namespace
        config = getattr(self.__class__, 'Config', None)
        
        if name is not None:
            # If name is provided externally, use it (likely already has namespace)
            if '{' in name:
                # If name already has namespace in {ns}localname format, extract it
                ns, tag_name = name.split('}', 1)
                ns = ns[1:]  # Remove leading '{'
            else:
                # Use name as is for tag_name
                tag_name = name
        else:
            # No name provided, get from config or class
            if config and hasattr(config, 'tag_name'):
                tag_name = config.tag_name
            else:
                # Convert class name to camelCase for tag name
                class_name = self.__class__.__name__
                # Convert first character to lowercase
                tag_name = class_name[0].lower() + class_name[1:] if class_name else ''
        
        # Get namespace from config if available
        if config and hasattr(config, 'tag_namespace'):
            ns = config.tag_namespace
        
        # Use model_config instead of Config if available
        model_config = getattr(self.__class__, 'model_config', {})
        json_schema_extra = model_config.get('json_schema_extra', {})
        if json_schema_extra:
            if 'tag_name' in json_schema_extra:
                tag_name = json_schema_extra['tag_name']
            if 'tag_namespace' in json_schema_extra:
                ns = json_schema_extra['tag_namespace']
        
        # Create element with namespace
        if parent_element is not None:
            # For SubElement, use {namespace}localname format for the tag
            qualified_name = f"{{{ns}}}{tag_name}"
            element = ET.SubElement(parent_element, qualified_name, attrib={}, nsmap=parent_element.nsmap)
        else:
            # For root element, use the tag_name and set nsmap
            element = ET.Element(tag_name, attrib={}, nsmap={None: ns})
        
        # Build attributes
        self._build_attributes(element)
        
        # Build children - ensure that we follow the schema order
        self._build_children(element)
        
        return element

    @classmethod
    def _from_xml_element(cls: Type[M], element: ET._Element, strict: Optional[bool] = None) -> M:
        """Creates a model instance from an lxml element.
        
        Args:
            element: The XML element to parse
            strict: If True, raise errors for unknown attributes and elements. 
                   If None, use class config.
        
        Returns:
            An instance of this model
            
        Raises:
            ValueError: If strict is True and unknown attributes or elements are encountered
        """
        # Determine strictness from parameter or class config
        strict_mode = strict if strict is not None else cls.model_config.get('strict_parsing', False)
        
        data = cls._parse_attributes(element, strict=strict_mode)
        data.update(cls._parse_children(element, strict=strict_mode))
        # Filter out internal fields before creating model instance
        init_data = {k: v for k, v in data.items() if k in cls.model_fields}
        instance = cls(**init_data)
        # Assign internal fields directly
        instance.unknown_attrs = data.get('unknown_attrs', {})
        instance.unknown_elements = data.get('unknown_elements', [])
        return instance

# --- Main eCH-0196 Types (Simplified Stubs) ---

# Based on eCH-0097 V4.0 XSD
class Uid(BaseXmlModel):
    uidOrganisationIdCategorie: Literal["CHE", "CHE1", "ADM"] = Field(..., json_schema_extra={'tag_namespace': NS_MAP['eCH-0097']})
    uidOrganisationId: int = Field(..., ge=0, le=999999999, json_schema_extra={'tag_namespace': NS_MAP['eCH-0097']}) # NonNegativeInteger <= 999999999
    uidSuffix: Optional[str] = Field(default=None, max_length=3, json_schema_extra={'tag_namespace': NS_MAP['eCH-0097']})
    xml: Optional[Any] = Field(default=None, exclude=True) # Store raw lxml element

    model_config = {
        "arbitrary_types_allowed": True,
        "extra": "allow", # Allow storing raw XML element if needed
        "json_schema_extra": {'tag_name': 'uid', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class Institution(BaseXmlModel):
    uid: Optional[Uid] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    lei: Optional[LEIType] = Field(default=None, pattern=r"[A-Z0-9]{18}[0-9]{2}", json_schema_extra={'is_attribute': True}) # leiType
    name: Optional[OrganisationName] = Field(default=None, json_schema_extra={'is_attribute': True}) # organisationNameType, required in XSD
 
    model_config = {
        "json_schema_extra": {'tag_name': 'institution', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class Client(BaseXmlModel):
    # attributes
    clientNumber: Optional[ClientNumber] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True}) # required in XSD
    tin: Optional[TINType] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True}) # tinType
    salutation: Optional[MrMrs] = Field(default=None, json_schema_extra={'is_attribute': True}) # mrMrsType
    firstName: Optional[FirstName] = Field(default=None, json_schema_extra={'is_attribute': True}) # firstNameType
    lastName: Optional[LastName] = Field(default=None, json_schema_extra={'is_attribute': True}) # lastNameType
    
    model_config = {
        "json_schema_extra": {'tag_name': 'client', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class AccompanyingLetter(BaseXmlModel):
    # attributes
    fileName: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True}) # MaxLength 200
    fileSize: Optional[int] = Field(default=None, json_schema_extra={'is_attribute': True})
    fileData: Optional[bytes] = Field(default=None, json_schema_extra={'is_attribute': True}) # base64Binary
    
    model_config = {
        "json_schema_extra": {'tag_name': 'accompanyingLetter', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class BankAccountTaxValue(BaseXmlModel):
    """Represents a taxValue element in a bankAccount (bankAccountTaxValueType)."""
    # Attributes from schema
    referenceDate: date = Field(..., json_schema_extra={'is_attribute': True})
    name: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'is_attribute': True})
    balanceCurrency: str = Field(..., json_schema_extra={'is_attribute': True})
    balance: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    exchangeRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    value: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})

    model_config = {
        "json_schema_extra": {'tag_name': 'taxValue', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class BankAccountPayment(BaseXmlModel):
    """Represents a payment element in a bankAccount (bankAccountPaymentType)."""
    # Attributes from schema
    paymentDate: date = Field(..., json_schema_extra={'is_attribute': True})
    name: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'is_attribute': True})
    amountCurrency: str = Field(..., json_schema_extra={'is_attribute': True})
    amount: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    exchangeRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueACanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueB: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueBCanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    withHoldingTaxClaim: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    lumpSumTaxCredit: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    nonRecoverableTax: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    bankingExpenses: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})

    model_config = {
        "json_schema_extra": {'tag_name': 'payment', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class BankAccount(BaseXmlModel):
    """Represents a bankAccount element according to eCH-0196."""
    # Child elements from schema
    taxValue: Optional[BankAccountTaxValue] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    payment: List[BankAccountPayment] = Field(default_factory=list, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    
    # Attributes from schema
    iban: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True})
    bankAccountNumber: Optional[BankAccountNumber] = Field(default=None, min_length=1, max_length=32, json_schema_extra={'is_attribute': True})
    bankAccountName: Optional[BankAccountName] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True})
    bankAccountCountry: Optional[CountryIdISO2Type] = Field(default=None, json_schema_extra={'is_attribute': True})
    bankAccountCurrency: Optional[CurrencyId] = Field(default=None, pattern=r"[A-Z]{3}", json_schema_extra={'is_attribute': True})
    openingDate: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    closingDate: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalTaxValue: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalGrossRevenueA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalGrossRevenueACanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalGrossRevenueB: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalGrossRevenueBCanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalWithHoldingTaxClaim: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD

    model_config = {
        "arbitrary_types_allowed": True,
        "json_schema_extra": {'tag_name': 'bankAccount', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class ListOfBankAccounts(BaseXmlModel):
    bankAccount: List[BankAccount] = Field(default_factory=list, alias="bankAccount", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    totalTaxValue: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalGrossRevenueA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalGrossRevenueB: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalWithHoldingTaxClaim: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD

    model_config = {
        "arbitrary_types_allowed": True,
        "json_schema_extra": {'tag_name': 'listOfBankAccounts', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class LiabilityAccountTaxValue(BaseXmlModel):
    """Represents a taxValue element in a liabilityAccount (liabilityAccountTaxValueType)."""
    # Attributes from schema
    referenceDate: date = Field(..., json_schema_extra={'is_attribute': True})
    name: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'is_attribute': True})
    balanceCurrency: CurrencyId
    balance: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    exchangeRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    value: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})

    model_config = {
        "json_schema_extra": {'tag_name': 'taxValue', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class LiabilityAccountPayment(BaseXmlModel):
    """Represents a payment element in a liabilityAccount (liabilityAccountPaymentType)."""
    # Attributes from schema
    paymentDate: date = Field(..., json_schema_extra={'is_attribute': True})
    name: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'is_attribute': True})
    amountCurrency: str = Field(..., json_schema_extra={'is_attribute': True})
    amount: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    exchangeRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueB: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueBCanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})

    model_config = {
        "json_schema_extra": {'tag_name': 'payment', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class LiabilityAccount(BaseXmlModel):
    """Represents a liabilityAccount element according to eCH-0196."""
    # Child elements from schema
    taxValue: Optional[LiabilityAccountTaxValue] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    payment: List[LiabilityAccountPayment] = Field(default_factory=list, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    
    # Attributes from schema
    iban: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True})
    bankAccountNumber: Optional[BankAccountNumber] = Field(default=None, min_length=1, max_length=32, json_schema_extra={'is_attribute': True})
    bankAccountName: BankAccountName = Field(..., max_length=40, json_schema_extra={'is_attribute': True})
    bankAccountCountry: CountryIdISO2Type = Field(..., json_schema_extra={'is_attribute': True})
    bankAccountCurrency: CurrencyId = Field(..., pattern=r"[A-Z]{3}", json_schema_extra={'is_attribute': True})
    openingDate: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    closingDate: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    liabilityCategory: Optional[LiabilityCategory] = Field(
        default=None, 
        description="The category of the liability (MORTGAGE, LOAN, or OTHER)",
        json_schema_extra={'is_attribute': True}
    )
    totalTaxValue: PositiveDecimal = Field(
        ..., 
        description="Total of the tax values (absolute value ≥ 0) of negative tax values (debts), rounded according to DIN 1333",
        json_schema_extra={'is_attribute': True}
    ) # Required in XSD
    totalGrossRevenueB: PositiveDecimal = Field(
        ..., 
        description="Total of the amounts (absolute value ≥ 0) of gross expenses (debt interest) for category B (without withholding tax claim)",
        json_schema_extra={'is_attribute': True}
    ) # Required in XSD
    
    model_config = {
        "arbitrary_types_allowed": True,
        "json_schema_extra": {'tag_name': 'liabilityAccount', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class ListOfLiabilities(BaseXmlModel):
    liabilityAccount: List[LiabilityAccount] = Field(default_factory=list, alias="liabilityAccount", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    totalTaxValue: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal, required
    totalGrossRevenueB: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal, required

    model_config = {
        "arbitrary_types_allowed": True,
        "json_schema_extra": {'tag_name': 'listOfLiabilities', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class Expense(BaseXmlModel):
    """Represents expense entry (expenseType) according to eCH-0196 schema."""
    # All fields are attributes according to schema
    referenceDate: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    name: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'is_attribute': True}) # Required in XSD
    iban: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True})
    bankAccountNumber: Optional[BankAccountNumber] = Field(default=None, min_length=1, max_length=32, json_schema_extra={'is_attribute': True})
    depotNumber: Optional[DepotNumber] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True})
    amountCurrency: Optional[CurrencyId] = Field(default=None, pattern=r"[A-Z]{3}", json_schema_extra={'is_attribute': True}) # Required in XSD
    amount: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    exchangeRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    expenses: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # Required in XSD
    expensesDeductible: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    expensesDeductibleCanton: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    expenseType: Optional[ExpenseType] = Field(default=None, json_schema_extra={'is_attribute': True}) # Required in XSD, enum type
    
    model_config = {
        "json_schema_extra": {'tag_name': 'expense', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class ListOfExpenses(BaseXmlModel):
    expense: List[Expense] = Field(default_factory=list, alias="expense", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    totalExpenses: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal, required
    totalExpensesDeductible: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal
    totalExpensesDeductibleCanton: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal

    model_config = {
        "arbitrary_types_allowed": True,
        "json_schema_extra": {'tag_name': 'listOfExpenses', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class SecurityTaxValue(BaseXmlModel):
    """Represents the tax value of a security (securityTaxValueType)."""
    # Required attributes
    referenceDate: date = Field(..., json_schema_extra={'is_attribute': True})
    quotationType: QuotationType = Field(..., json_schema_extra={'is_attribute': True})
    quantity: Decimal = Field(..., json_schema_extra={'is_attribute': True})
    balanceCurrency: CurrencyId

    # Optional attributes
    name: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'is_attribute': True})
    unitPrice: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    balance: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    exchangeRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    value: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    blocked: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    blockingTo: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    undefined: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    kursliste: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    
    model_config = {
        "json_schema_extra": {'tag_name': 'taxValue', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class SecurityPurchaseDisposition(BaseXmlModel):
    """Represents purchase or disposition of a security for IUP calculation."""
    # Required attributes
    referenceDate: date = Field(..., json_schema_extra={'is_attribute': True})
    quotationType: QuotationType = Field(..., json_schema_extra={'is_attribute': True})
    quantity: Decimal = Field(..., json_schema_extra={'is_attribute': True})
    
    # Optional attributes
    amountCurrency: Optional[CurrencyId] = Field(default=None, json_schema_extra={'is_attribute': True})
    amount: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    exchangeRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    value: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    
    model_config = {
        "json_schema_extra": {'tag_name': 'purchase', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class SecurityPayment(BaseXmlModel):
    """Represents a payment (revenue) for a security (securityPaymentType)."""
    # Child elements
    purchase: List[SecurityPurchaseDisposition] = Field(default_factory=list, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    disposition: Optional[SecurityPurchaseDisposition] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    
    # Required attributes
    paymentDate: date = Field(..., json_schema_extra={'is_attribute': True})
    quotationType: QuotationType = Field(..., json_schema_extra={'is_attribute': True})
    quantity: Decimal = Field(..., json_schema_extra={'is_attribute': True})
    amountCurrency: CurrencyId = Field(..., json_schema_extra={'is_attribute': True})
    
    # Optional attributes
    exDate: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    name: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'is_attribute': True})
    amountPerUnit: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    amount: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    exchangeRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueACanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueB: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    grossRevenueBCanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    withHoldingTaxClaim: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    lumpSumTaxCredit: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    lumpSumTaxCreditPercent: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    lumpSumTaxCreditAmount: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    nonRecoverableTaxPercent: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    nonRecoverableTaxAmount: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    nonRecoverableTax: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    additionalWithHoldingTaxUSA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    iup: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    conversion: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    gratis: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    securitiesLending: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    lendingFee: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    retrocession: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    undefined: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    kursliste: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    sign: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True})
    
    model_config = {
        "json_schema_extra": {'tag_name': 'payment', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class SecurityStock(BaseXmlModel):
    """Represents stock changes for a security (securityStockType)."""
    # Required attributes from XSD
    # For balances (mutation=False) the value is at the start of the referenceDate unlike
    # what is common for stock statements.
    referenceDate: date = Field(..., json_schema_extra={'is_attribute': True})
    mutation: bool = Field(..., json_schema_extra={'is_attribute': True})
    quotationType: QuotationType = Field(..., json_schema_extra={'is_attribute': True})  
    quantity: Decimal = Field(..., json_schema_extra={'is_attribute': True})
    balanceCurrency: CurrencyId

    # Optional attributes from XSD
    name: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'is_attribute': True})
    unitPrice: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    balance: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    reductionCost: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    exchangeRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    value: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    blocked: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    blockingTo: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    
    model_config = {
        "json_schema_extra": {'tag_name': 'stock', 'tag_namespace': NS_MAP['eCH-0196']},
    }


class Security(BaseXmlModel):
    """Represents a security element according to eCH-0196 schema (securitySecurityType)."""
    # Child elements
    taxValue: Optional[SecurityTaxValue] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    payment: List[SecurityPayment] = Field(default_factory=list, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    stock: List[SecurityStock] = Field(default_factory=list, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    uid: Optional[Uid] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    
    # Required attributes
    positionId: int = Field(..., gt=0, json_schema_extra={'is_attribute': True})
    country: CountryIdISO2Type = Field(..., json_schema_extra={'is_attribute': True})
    currency: CurrencyId
    quotationType: QuotationType = Field(..., json_schema_extra={'is_attribute': True})
    securityCategory: SecurityCategory = Field(..., json_schema_extra={'is_attribute': True})
    securityName: str = Field(..., max_length=60, json_schema_extra={'is_attribute': True})
    
    # Optional attributes
    valorNumber: Optional[ValorNumber] = Field(default=None, ge=100, le=999999999999, json_schema_extra={'is_attribute': True})
    isin: Optional[ISINType] = Field(default=None, pattern=r"[A-Z]{2}[A-Z0-9]{9}[0-9]{1}", json_schema_extra={'is_attribute': True})
    city: Optional[str] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True})
    nominalValue: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    securityType: Optional[SecurityType] = Field(default=None, json_schema_extra={'is_attribute': True})
    issueDate: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    redemptionDate: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    redemptionDateEarly: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True})
    issuePrice: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    redemptionPrice: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    redemptionPriceEarly: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    interestRate: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    variableInterest: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    bfp: Optional[bool] = Field(default=None, json_schema_extra={'is_attribute': True})
    symbol: Optional[str] = Field(default=None, exclude=True)
    # Internal totals for rendering
    totalGrossRevenueA: Optional[Decimal] = Field(default=None, exclude=True)
    totalGrossRevenueB: Optional[Decimal] = Field(default=None, exclude=True)
    totalWithHoldingTaxClaim: Optional[Decimal] = Field(default=None, exclude=True)
    totalNonRecoverableTax: Optional[Decimal] = Field(default=None, exclude=True)
    totalAdditionalWithHoldingTaxUSA: Optional[Decimal] = Field(default=None, exclude=True)
    model_config = {
        "json_schema_extra": {'tag_name': 'security', 'tag_namespace': NS_MAP['eCH-0196']}
    }

    @field_validator('securityName', mode='before')
    @classmethod
    def truncate_security_name(cls, v: str) -> str:
        """Truncate security name to fit eCH-0196 60-character limit using Pydantic-style format.
        
        Preserves the beginning and end of the name with '...' in the middle if truncation is needed.
        See docs/SPEC_ISSUES.md for details on the eCH-0196 vs Kursliste specification discrepancy.
        """
        if len(v) <= 60:
            return v
        
        # Calculate how many characters we can preserve from start and end
        # Format: "start...end" where total length = 60
        ellipsis = "..."
        available_chars = 60 - len(ellipsis)  # 57 characters for actual content
        
        # Split available characters between start and end, favoring the start slightly
        start_chars = (available_chars + 1) // 2  # 29 characters
        end_chars = available_chars - start_chars  # 28 characters
        
        start_part = v[:start_chars]
        end_part = v[-end_chars:] if end_chars > 0 else ""
        
        truncated = f"{start_part}{ellipsis}{end_part}"
        
        # Ensure we didn't somehow exceed 60 characters
        assert len(truncated) == 60, f"Truncated name length {len(truncated)} != 60"
        
        return truncated


class Depot(BaseXmlModel):
    security: List[Security] = Field(default_factory=list, alias="security", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    depotNumber: Optional[DepotNumber] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True}) # depotNumberType, required

    model_config = {
        "arbitrary_types_allowed": True,
        "json_schema_extra": {'tag_name': 'depot', 'tag_namespace': NS_MAP['eCH-0196']}
    }


class ListOfSecurities(BaseXmlModel):
    depot: List[Depot] = Field(default_factory=list, alias="depot", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    totalTaxValue: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required
    totalGrossRevenueA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required
    totalGrossRevenueACanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalGrossRevenueB: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required
    totalGrossRevenueBCanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalWithHoldingTaxClaim: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required
    totalLumpSumTaxCredit: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required
    totalNonRecoverableTax: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required
    totalAdditionalWithHoldingTaxUSA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required
    totalGrossRevenueIUP: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required
    totalGrossRevenueConversion: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required

    model_config = {
        "arbitrary_types_allowed": True,
        "json_schema_extra": {'tag_name': 'listOfSecurities', 'tag_namespace': NS_MAP['eCH-0196']}
    }


# --- Root Element Model --- Adjusted for inheritance and attributes/elements
class TaxStatementBase(BaseXmlModel):
    # Elements
    institution: Optional[Institution] = Field(default=None, alias="institution", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    client: List[Client] = Field(default_factory=list, alias="client", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    accompanyingLetter: List[AccompanyingLetter] = Field(default_factory=list, alias="accompanyingLetter", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    listOfBankAccounts: Optional[ListOfBankAccounts] = Field(default=None, alias="listOfBankAccounts", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    listOfLiabilities: Optional[ListOfLiabilities] = Field(default=None, alias="listOfLiabilities", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    listOfExpenses: Optional[ListOfExpenses] = Field(default=None, alias="listOfExpenses", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    listOfSecurities: Optional[ListOfSecurities] = Field(default=None, alias="listOfSecurities", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})

    # Base taxStatementType attributes
    id: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True}) # ID, required in XSD
    creationDate: Optional[datetime] = Field(default=None, json_schema_extra={'is_attribute': True}) # dateTime, required in XSD
    taxPeriod: Optional[int] = Field(default=None, json_schema_extra={'is_attribute': True}) # gYear, required in XSD
    periodFrom: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True}) # date, required in XSD
    periodTo: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True}) # date, required in XSD
    country: Optional[CountryIdISO2Type] = Field(default="CH", json_schema_extra={'is_attribute': True})
    canton: Optional[CantonAbbreviation] = Field(default=None, json_schema_extra={'is_attribute': True}) # cantonAbbreviationType, required in XSD
    totalTaxValue: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalGrossRevenueA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalGrossRevenueACanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalGrossRevenueB: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalGrossRevenueBCanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalWithHoldingTaxClaim: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD

    def validate_model(self):
        """Placeholder for schema validation logic."""
        # TODO: Implement validation based on XSD rules (required fields, types, constraints)
        logger.info("Validation logic not yet implemented.")
        # Example checks:
        # if self.id is None:
        #     raise ValueError("'id' attribute is required")
        # if not self.client:
        #     raise ValueError("At least one 'client' element is required")
        # ... etc.
        return True


# Final root model including the minorVersion attribute
class TaxStatement(TaxStatementBase):
    # Attribute specific to the root 'taxStatement' element
    minorVersion: Optional[int] = Field(..., json_schema_extra={'is_attribute': True}) # required in XSD -> Changed default=None to ...
    
    # Additional fields for summary data (not serialized to XML)
    steuerwert_ab: Optional[Decimal] = Field(default=None, exclude=True)
    svTaxValueA: Optional[Decimal] = Field(default=None, exclude=True)
    svTaxValueB: Optional[Decimal] = Field(default=None, exclude=True)
    svGrossRevenueA: Optional[Decimal] = Field(default=None, exclude=True)
    svGrossRevenueB: Optional[Decimal] = Field(default=None, exclude=True)
    da1TaxValue: Optional[Decimal] = Field(default=Decimal('0'), exclude=True)
    da_GrossRevenue: Optional[Decimal] = Field(default=Decimal('0'), exclude=True)
    pauschale_da1: Optional[Decimal] = Field(default=Decimal('0'), exclude=True)
    rueckbehalt_usa: Optional[Decimal] = Field(default=Decimal('0'), exclude=True)
    total_brutto_gesamt: Optional[Decimal] = Field(default=None, exclude=True)
    # importer_name: Optional[str] = Field(default=None, exclude=True) # Field removed as per instruction

    model_config = {
        "json_schema_extra": {'tag_name': 'taxStatement', 'tag_namespace': NS_MAP['eCH-0196']}
    }
        
    @classmethod
    def from_xml_file(cls, file_path: str, strict: Optional[bool] = None) -> "TaxStatement":
        """Read a TaxStatement from an XML file.
        
        Args:
            file_path: Path to the XML file
            strict: If True, raise errors for unknown attributes and elements.
                   If None, use class config.
                   
        Returns:
            TaxStatement instance parsed from the file
            
        Raises:
            ValueError: If file can't be parsed or root element is invalid
            ValueError: If strict is True and unknown attributes or elements are encountered
        """
        # Parse the XML file
        try:
            parser = ET.XMLParser(remove_blank_text=True)
            tree = ET.parse(file_path, parser)
            root = tree.getroot()
            
            # Basic validation of root element
            expected_tag = ns_tag('eCH-0196', 'taxStatement')
            if root.tag != expected_tag:
                raise ValueError(f"Expected root element '{expected_tag}' but found '{root.tag}'")
            
            # Create the TaxStatement instance from the parsed root element
            return cls._from_xml_element(root, strict=strict)
            
        except ET.XMLSyntaxError as e:
            raise ValueError(f"Failed to parse XML file: {e}")
        except FileNotFoundError:
            raise ValueError(f"File not found: {file_path}")
        except Exception as e:
            raise ValueError(f"Error reading tax statement from file: {e}")

    def to_xml_bytes(self, pretty_print=True) -> bytes:
        """Serializes the model to XML bytes."""
        root = self._build_xml_element(None)
        return ET.tostring(root, pretty_print=pretty_print, xml_declaration=True, encoding='UTF-8') # type: ignore

    def to_xml_file(self, file_path: str, pretty_print=True):
        """Dumps the model to an eCH-0196 XML file."""
        xml_bytes = self.to_xml_bytes(pretty_print=pretty_print)
        with open(file_path, 'wb') as f:
            f.write(xml_bytes)
        logger.debug("Model successfully written to %s", file_path)

    def dump_debug_xml(self, file_path: str):
        """Dumps the current model state to XML, potentially incomplete/invalid."""
        # For now, this behaves the same as to_xml_file
        # Future: could add options to relax validation or add comments
        try:
            self.to_xml_file(file_path, pretty_print=True)
            logger.debug("Debug XML dumped to: %s", file_path)
        except Exception as e:
            logger.error("Error dumping debug XML to %s: %s", file_path, e)

# --- Description Helper Functions ---
class Descriptions:
    """Helper class for getting enum descriptions."""
    
    @staticmethod
    def expense(expense_code: ExpenseType) -> str:
        """Get the description of an expense type based on its code."""
        return EXPENSE_TYPE_DESCRIPTIONS.get(expense_code, "Unknown expense type")
    
    @staticmethod
    def security_category(category_code: SecurityCategory) -> str:
        """Get the description of a security category based on its code."""
        return SECURITY_CATEGORY_DESCRIPTIONS.get(category_code, "Unknown security category")
    
    @staticmethod
    def security_type(type_code: SecurityType) -> str:
        """Get the description of a security type based on its code."""
        return SECURITY_TYPE_DESCRIPTIONS.get(type_code, "Unknown security type")
    
    @staticmethod
    def liability_category(category_code: LiabilityCategory) -> str:
        """Get the description of a liability category based on its code."""
        return LIABILITY_CATEGORY_DESCRIPTIONS.get(category_code, "Unknown liability category")
    
    @staticmethod
    def salutation(salutation_code: MrMrs) -> str:
        """Get the description of a salutation based on its code."""
        return MrMrsCodes.get(salutation_code, "Unknown salutation")
