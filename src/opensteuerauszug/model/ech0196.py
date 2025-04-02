"""Pydantic models for eCH-0196 Tax Statement standard."""

from pydantic import BaseModel, Field, validator, field_validator, StringConstraints, AfterValidator
from pydantic.fields import FieldInfo # Import FieldInfo
from typing import List, Optional, Any, Dict, TypeVar, Type, Union, get_origin, get_args, Literal, Annotated # Import helpers & Literal, Annotated
from datetime import date, datetime
from decimal import Decimal
import lxml.etree as ET

# Define namespaces used in the XSD
NS_MAP = {
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
class BankAccountNameType(str): # maxLength: 40 - Handled by Field directly later
    pass
class BankAccountNumberType(str): # minLength: 1, maxLength: 32 - Handled by Field directly later
    pass
class ClientNumberType(str): # maxLength: 40 - Handled by Field directly later
    pass
# Add other simple types like currencyIdISO3Type, depotNumberType, etc.
class CurrencyIdISO3Type(str): # pattern="[A-Z]{3}"
    pass
class DepotNumberType(str): # maxLength: 40
    pass
class ValorType(int): # positiveInteger, maxInclusive=99999999
    pass
class ISINType(str): # length=12, pattern="[A-Z]{2}[A-Z0-9]{9}[0-9]{1}"
    pass
class LEIType(str): # length=20, pattern="[A-Z0-9]{18}[0-9]{2}"
    pass
class TINType(str): # maxLength=40
    pass
class LiabilityCategoryType(str): # enumeration
    pass
class ExpenseCategoryType(str): # enumeration
    pass

def check_positive(v: Decimal) -> Decimal:
    if v < Decimal(0):
        raise ValueError(f"Value must be positive, got {v}")
    return v

PositiveDecimal = Annotated[Decimal, AfterValidator(check_positive)]

# --- Types based on imported eCH standards ---

# eCH-0007 V6.0
CantonAbbreviationType = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Z]{2}$", # Needs to match one of the enum values below
        to_upper=True,
        min_length=2,
        max_length=2
    )
]
# Use Literal for actual validation against the XSD enum
CantonAbbreviationLiteral = Literal[
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
OrganisationNameType = Annotated[str, StringConstraints(max_length=60)]
MrMrsType = Literal["1", "2", "3"] # 1: Unknown, 2: Mr, 3: Mrs/Ms (approximation)
FirstNameType = Annotated[str, StringConstraints(max_length=30)]
LastNameType = Annotated[str, StringConstraints(max_length=30)]

# --- Placeholder for complex types referenced by import ---
# These would ideally be generated/defined based on the imported XSDs
# class ECH0007_CantonAbbreviationType(str): # length=2, pattern="[A-Z]{2}" - Replaced
#     pass

# class ECH0008_CountryIdISO2Type(str): # length=2, pattern="[A-Z]{2}" - Replaced
#     pass

# class ECH0010_OrganisationNameType(str): # minLength=1, maxLength=60 - Replaced
#     pass

# class ECH0010_MrMrsType(str): # enumeration "1", "2", "3" - Replaced
#     pass

# class ECH0010_FirstNameType(str): # minLength=1, maxLength=30 - Replaced
#     pass

# class ECH0010_LastNameType(str): # minLength=1, maxLength=30 - Replaced
#     pass

# Based on eCH-0097 V4.0 XSD
class ECH0097_UidStructureType(BaseModel):
    uidOrganisationIdCategorie: Literal["CHE", "CHE1", "ADM"] = Field(..., json_schema_extra={'tag_namespace': NS_MAP['eCH-0097']})
    uidOrganisationId: int = Field(..., ge=0, le=999999999, json_schema_extra={'tag_namespace': NS_MAP['eCH-0097']}) # NonNegativeInteger <= 999999999
    uidSuffix: Optional[str] = Field(default=None, max_length=3, json_schema_extra={'tag_namespace': NS_MAP['eCH-0097']})
    xml: Optional[Any] = Field(default=None, exclude=True) # Store raw lxml element

    class Config:
        arbitrary_types_allowed = True
        extra = 'allow' # Allow storing raw XML element if needed

# Generic Type Variable for Pydantic models
M = TypeVar('M', bound='BaseXmlModel')

# --- Base Model with XML capabilities (Pydantic v2 adjusted) ---
class BaseXmlModel(BaseModel):
    unknown_attrs: Dict[str, str] = Field(default_factory=dict, exclude=True)
    unknown_elements: List[Any] = Field(default_factory=list, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def _parse_attributes(cls: Type[M], element: ET._Element) -> Dict[str, Any]:
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
                    print(f"Warning: Could not parse attribute '{name}'='{value}' as {base_type}: {e}")
                    unknown_attrs[name] = value
            elif name not in known_attrs:
                # Check for XML namespace declarations if needed (e.g., xmlns:prefix=\"...\")
                if not name.startswith('{http://www.w3.org/2000/xmlns/}'):
                    unknown_attrs[name] = value
        if unknown_attrs:
            data['unknown_attrs'] = unknown_attrs
        return data

    def _build_attributes(self, element: ET._Element):
        for name, field_info in self.model_fields.items():
            if field_info.json_schema_extra and field_info.json_schema_extra.get("is_attribute"):
                value = getattr(self, name, None)
                if value is not None:
                    attr_name = field_info.alias or name
                    # Basic type conversion to string
                    str_value: str
                    if isinstance(value, (date, datetime)):
                        str_value = value.isoformat()
                    elif isinstance(value, bool):
                        str_value = str(value).lower()
                    elif isinstance(value, bytes):
                        # TODO: Implement base64 encoding if needed for fileData
                        str_value = value.decode('utf-8') # Assume utf-8 for now
                    else:
                        str_value = str(value)
                    element.set(attr_name, str_value)
        # Add unknown attributes back for round-tripping
        for name, value in self.unknown_attrs.items():
             # Avoid writing xmlns attributes if they are handled by lxml nsmap
             if not name.startswith('{http://www.w3.org/2000/xmlns/}'):
                element.set(name, value)

    @classmethod
    def _parse_children(cls: Type[M], element: ET._Element) -> Dict[str, Any]:
        data = {}
        children_data: Dict[str, list] = {}
        unknown_elements = []

        # Map XML tags to field names
        tag_to_field: Dict[tuple[Optional[str], str], str] = {}
        for name, field_info in cls.model_fields.items():
             extra = field_info.json_schema_extra or {}
             if not extra.get("is_attribute"):
                 # Ensure ns and local_name are strings for the key
                 ns = str(extra.get("tag_namespace", NS_MAP['eCH-0196']))
                 local_name = str(field_info.alias or name)
                 tag_to_field[(ns, local_name)] = name

        for child in element: # type: ignore
            if isinstance(child.tag, str): # Ignore comments, PIs
                child_ns = child.nsmap.get(child.prefix) if child.prefix else element.nsmap.get(None)
                localname = child.tag.split('}')[-1]
                lookup_key = (child_ns, localname)

                field_name = tag_to_field.get(lookup_key)

                if field_name:
                    field_info = cls.model_fields[field_name]
                    target_type = field_info.annotation
                    origin_type = get_origin(target_type)
                    type_args = get_args(target_type)

                    is_list = origin_type is list or origin_type is List
                    # Handle Optional[List[T]] or List[T]
                    item_type = Any
                    if is_list:
                        list_arg = type_args[0]
                        list_arg_origin = get_origin(list_arg)
                        list_arg_args = get_args(list_arg)
                        if list_arg_origin is Union and type(None) in list_arg_args:
                             item_type = next((t for t in list_arg_args if t is not type(None)), Any) # type: ignore
                        else:
                             item_type = list_arg
                    # Handle Optional[T] or T
                    elif origin_type is Union and type(None) in type_args:
                         item_type = next((t for t in type_args if t is not type(None)), Any) # type: ignore
                    else:
                        item_type = target_type

                    parsed_child: Any = None
                    try:
                        # Simplified check: If it's a type and a subclass of BaseXmlModel
                        if isinstance(item_type, type) and issubclass(item_type, BaseXmlModel): # type: ignore[arg-type]
                            parsed_child = item_type._from_xml_element(child)
                        else:
                            # Handle simple text content or other types
                            parsed_child = child.text # Basic handling
                            # TODO: Add type conversion like in _parse_attributes if needed for simple content types
                            if item_type == Decimal and parsed_child is not None:
                                parsed_child = Decimal(parsed_child)
                            # Add other simple type conversions here...
                    except (TypeError, ValueError) as e:
                         print(f"Warning: Could not parse element <{child.tag}> content '{child.text}' as {item_type}: {e}")
                         # Store raw element if parsing fails?
                         unknown_elements.append(child)
                         continue # Skip adding to field data

                    if is_list:
                        if field_name not in children_data:
                            children_data[field_name] = []
                        if parsed_child is not None:
                             children_data[field_name].append(parsed_child)
                    else:
                        if field_name in data:
                           print(f"Warning: Multiple elements found for non-list field '{field_name}' - using last one.")
                        data[field_name] = parsed_child
                else:
                     # Handle unknown elements / ##other namespace elements
                     unknown_elements.append(child) # Store the raw lxml element
            else:
                # Store comments, PIs etc. if needed for perfect round-tripping
                unknown_elements.append(child)

        data.update(children_data)
        if unknown_elements:
            data['unknown_elements'] = unknown_elements

        return data

    def _build_children(self, parent_element: ET._Element):
        tag_map = {}
        for name, field_info in self.model_fields.items():
            extra = field_info.json_schema_extra or {}
            if not extra.get("is_attribute"):
                ns = extra.get("tag_namespace", NS_MAP['eCH-0196'])
                local_name = field_info.alias or name
                tag_map[name] = (ns, local_name)

        for name, field_info in self.model_fields.items():
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
                        child_element = ET.Element(tag_name, attrib={}, nsmap=nsmap_for_element)
                        item._build_xml_element(child_element)
                        parent_element.append(child_element)
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

    def _build_xml_element(self, element: ET._Element):
        """Populates an existing lxml element from this model instance."""
        self._build_attributes(element)
        self._build_children(element)

    @classmethod
    def _from_xml_element(cls: Type[M], element: ET._Element) -> M:
        """Creates a model instance from an lxml element."""
        data = cls._parse_attributes(element)
        data.update(cls._parse_children(element))
        # Filter out internal fields before creating model instance
        init_data = {k: v for k, v in data.items() if k in cls.model_fields}
        instance = cls(**init_data)
        # Assign internal fields directly
        instance.unknown_attrs = data.get('unknown_attrs', {})
        instance.unknown_elements = data.get('unknown_elements', [])
        return instance

# --- Main eCH-0196 Types (Simplified Stubs) ---

class InstitutionType(BaseXmlModel):
    uid: Optional[ECH0097_UidStructureType] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    lei: Optional[LEIType] = Field(default=None, pattern=r"[A-Z0-9]{18}[0-9]{2}", json_schema_extra={'is_attribute': True}) # leiType
    name: Optional[OrganisationNameType] = Field(default=None, json_schema_extra={'is_attribute': True}) # organisationNameType, required in XSD
    # anyAttribute: Dict[str, Any] = Field(default_factory=dict)
    # otherElements: List[Any] = Field(default_factory=list)

class ClientType(BaseXmlModel):
    # attributes
    clientNumber: Optional[ClientNumberType] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True}) # required in XSD
    tin: Optional[TINType] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True}) # tinType
    salutation: Optional[MrMrsType] = Field(default=None, json_schema_extra={'is_attribute': True}) # mrMrsType
    firstName: Optional[FirstNameType] = Field(default=None, json_schema_extra={'is_attribute': True}) # firstNameType
    lastName: Optional[LastNameType] = Field(default=None, json_schema_extra={'is_attribute': True}) # lastNameType
    # anyAttribute: Dict[str, Any] = Field(default_factory=dict)
    # otherElements: List[Any] = Field(default_factory=list)

class AccompanyingLetterType(BaseXmlModel):
    # attributes
    fileName: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True}) # MaxLength 200
    fileSize: Optional[int] = Field(default=None, json_schema_extra={'is_attribute': True})
    fileData: Optional[bytes] = Field(default=None, json_schema_extra={'is_attribute': True}) # base64Binary
    # anyAttribute: Dict[str, Any] = Field(default_factory=dict)
    # otherElements: List[Any] = Field(default_factory=list)

class BankAccountType(BaseXmlModel):
    # Define fields based on bankAccountType in XSD
    iban: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True}) # Consider adding IBAN validation pattern
    bankAccountNumber: Optional[BankAccountNumberType] = Field(default=None, min_length=1, max_length=32, json_schema_extra={'is_attribute': True})
    bankAccountName: Optional[BankAccountNameType] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True}) # Required in XSD
    # ... other fields and attributes ...
    class Config:
        arbitrary_types_allowed = True

class ListOfBankAccountsType(BaseXmlModel):
    bankAccount: List[BankAccountType] = Field(default_factory=list, alias="bankAccount", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    totalTaxValue: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalGrossRevenueA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalGrossRevenueB: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalWithHoldingTaxClaim: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    # anyAttribute: Dict[str, Any] = Field(default_factory=dict)
    # otherElements: List[Any] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

class LiabilityAccountType(BaseXmlModel):
    # Define based on XSD - liabilityAccountType
    # Attributes
    id: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True}) # Required
    # Elements
    liabilityCategory: Optional[LiabilityCategoryType] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required, enum
    description: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    valueAsPer: Optional[date] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    taxValue: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    interest: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    interestCredited: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required

class ListOfLiabilitiesType(BaseXmlModel):
    liabilityAccount: List[LiabilityAccountType] = Field(default_factory=list, alias="liabilityAccount", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    totalTaxValue: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal, required
    totalGrossRevenueB: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal, required
    # anyAttribute: Dict[str, Any] = Field(default_factory=dict)
    # otherElements: List[Any] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

class ExpenseType(BaseXmlModel):
    # Define based on XSD - expenseType
    # Attributes
    id: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True}) # Required
    # Elements
    expenseCategory: Optional[ExpenseCategoryType] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required, enum
    description: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    amount: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    amountDeductible: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    amountDeductibleCanton: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})

class ListOfExpensesType(BaseXmlModel):
    expense: List[ExpenseType] = Field(default_factory=list, alias="expense", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    totalExpenses: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal, required
    totalExpensesDeductible: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal
    totalExpensesDeductibleCanton: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # positive-decimal
    # anyAttribute: Dict[str, Any] = Field(default_factory=dict)
    # otherElements: List[Any] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

class SecuritySecurityType(BaseXmlModel):
    # Define based on XSD - securitySecurityType
    # Attributes
    id: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True}) # Required
    # Elements (Simplified - needs detailed review of XSD)
    isin: Optional[ISINType] = Field(default=None, pattern=r"[A-Z]{2}[A-Z0-9]{9}[0-9]{1}", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    valor: Optional[ValorType] = Field(default=None, gt=0, le=99999999, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    securityName: Optional[str] = Field(default=None, max_length=200, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    quantity: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    currency: Optional[CurrencyIdISO3Type] = Field(default=None, pattern=r"[A-Z]{3}", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    price: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    priceDate: Optional[date] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    taxValue: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    grossRevenueA: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    grossRevenueACanton: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    grossRevenueB: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    grossRevenueBCanton: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    withHoldingTaxClaim: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    lumpSumTaxCredit: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    nonRecoverableTax: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    additionalWithHoldingTaxUSA: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    grossRevenueIUP: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required
    grossRevenueConversion: Optional[PositiveDecimal] = Field(default=None, json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']}) # Required

class SecurityDepotType(BaseXmlModel):
    security: List[SecuritySecurityType] = Field(default_factory=list, alias="security", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    # attributes
    depotNumber: Optional[DepotNumberType] = Field(default=None, max_length=40, json_schema_extra={'is_attribute': True}) # depotNumberType, required
    # anyAttribute: Dict[str, Any] = Field(default_factory=dict)
    # otherElements: List[Any] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

class ListOfSecuritiesType(BaseXmlModel):
    depot: List[SecurityDepotType] = Field(default_factory=list, alias="depot", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
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
    # anyAttribute: Dict[str, Any] = Field(default_factory=dict)
    # otherElements: List[Any] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

# --- Root Element Model --- Adjusted for inheritance and attributes/elements
class TaxStatementExtension(BaseXmlModel):
    # Elements
    institution: Optional[InstitutionType] = Field(default=None, alias="institution", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    client: List[ClientType] = Field(default_factory=list, alias="client", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    accompanyingLetter: List[AccompanyingLetterType] = Field(default_factory=list, alias="accompanyingLetter", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    listOfBankAccounts: Optional[ListOfBankAccountsType] = Field(default=None, alias="listOfBankAccounts", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    listOfLiabilities: Optional[ListOfLiabilitiesType] = Field(default=None, alias="listOfLiabilities", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    listOfExpenses: Optional[ListOfExpensesType] = Field(default=None, alias="listOfExpenses", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})
    listOfSecurities: Optional[ListOfSecuritiesType] = Field(default=None, alias="listOfSecurities", json_schema_extra={'tag_namespace': NS_MAP['eCH-0196']})

    # Base taxStatementType attributes
    id: Optional[str] = Field(default=None, json_schema_extra={'is_attribute': True}) # ID, required in XSD
    creationDate: Optional[datetime] = Field(default=None, json_schema_extra={'is_attribute': True}) # dateTime, required in XSD
    taxPeriod: Optional[int] = Field(default=None, json_schema_extra={'is_attribute': True}) # gYear, required in XSD
    periodFrom: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True}) # date, required in XSD
    periodTo: Optional[date] = Field(default=None, json_schema_extra={'is_attribute': True}) # date, required in XSD
    country: Optional[CountryIdISO2Type] = Field(default="CH", json_schema_extra={'is_attribute': True})
    canton: Optional[CantonAbbreviationLiteral] = Field(default=None, json_schema_extra={'is_attribute': True}) # cantonAbbreviationType, required in XSD
    totalTaxValue: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalGrossRevenueA: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalGrossRevenueACanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalGrossRevenueB: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD
    totalGrossRevenueBCanton: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True})
    totalWithHoldingTaxClaim: Optional[Decimal] = Field(default=None, json_schema_extra={'is_attribute': True}) # required in XSD

    def validate_model(self):
        """Placeholder for schema validation logic."""
        # TODO: Implement validation based on XSD rules (required fields, types, constraints)
        print("Validation logic not yet implemented.")
        # Example checks:
        # if self.id is None:
        #     raise ValueError("'id' attribute is required")
        # if not self.client:
        #     raise ValueError("At least one 'client' element is required")
        # ... etc.
        return True

# Final root model including the minorVersion attribute
class TaxStatement(TaxStatementExtension):
    # Attribute specific to the root 'taxStatement' element
    minorVersion: Optional[int] = Field(..., json_schema_extra={'is_attribute': True}) # required in XSD -> Changed default=None to ...

    @classmethod
    def from_xml_file(cls, file_path: str) -> "TaxStatement":
        """Loads the model from an eCH-0196 XML file."""
        try:
            parser = ET.XMLParser(remove_blank_text=True)
            tree = ET.parse(file_path, parser)
            root = tree.getroot()
            # Basic check for root element name and namespace
            expected_tag = ns_tag('eCH-0196', 'taxStatement')
            if root.tag != expected_tag:
                raise ValueError(f"Expected root element '{expected_tag}' but found '{root.tag}'")
            return cls._from_xml_element(root)
        except ET.ParseError as e:
            print(f"Error parsing XML file {file_path}: {e}")
            raise
        except Exception as e:
            print(f"Error creating model from XML {file_path}: {e}")
            raise

    def to_xml_bytes(self, pretty_print=True) -> bytes:
        """Serializes the model to XML bytes."""
        root_tag = ns_tag('eCH-0196', 'taxStatement')
        # Create root element with namespace declarations
        root = ET.Element(root_tag, attrib={}, nsmap=NS_MAP)
        self._build_xml_element(root)
        return ET.tostring(root, pretty_print=pretty_print, xml_declaration=True, encoding='UTF-8') # type: ignore

    def to_xml_file(self, file_path: str, pretty_print=True):
        """Dumps the model to an eCH-0196 XML file."""
        xml_bytes = self.to_xml_bytes(pretty_print=pretty_print)
        with open(file_path, 'wb') as f:
            f.write(xml_bytes)
        print(f"Model successfully written to {file_path}")

    def dump_debug_xml(self, file_path: str):
        """Dumps the current model state to XML, potentially incomplete/invalid."""
        # For now, this behaves the same as to_xml_file
        # Future: could add options to relax validation or add comments
        try:
            self.to_xml_file(file_path, pretty_print=True)
            print(f"Debug XML dumped to: {file_path}")
        except Exception as e:
            print(f"Error dumping debug XML to {file_path}: {e}")

# Example Usage block removed, replaced by tests in tests/test_ech0196_model.py 