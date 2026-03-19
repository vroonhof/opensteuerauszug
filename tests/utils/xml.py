from lxml import etree as ET
import re
from decimal import Decimal, InvalidOperation


_DECIMAL_LEXEME_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+)$")


def _normalize_decimal_lexeme(value: str) -> str:
    """Normalize decimal lexical forms like 1.20/.30 to 1.2/0.3 for robust XML comparisons."""
    if not _DECIMAL_LEXEME_RE.match(value):
        return value
    try:
        return format(Decimal(value).normalize(), "f")
    except (InvalidOperation, ValueError):
        return value


def _normalize_decimal_values(element: ET._Element) -> None:
    """Normalize decimal-looking attribute and text values recursively."""
    for attr_name, attr_value in list(element.attrib.items()):
        element.attrib[attr_name] = _normalize_decimal_lexeme(attr_value)

    if element.text:
        stripped = element.text.strip()
        if stripped:
            normalized = _normalize_decimal_lexeme(stripped)
            if normalized != stripped:
                element.text = normalized

    for child in element:
        _normalize_decimal_values(child)

def normalize_xml(xml_bytes: bytes, remove_xmlns: bool = False) -> str:
    """Normalize XML string by parsing and re-serializing it.
    
    Args:
        xml_bytes: The XML content as bytes
        remove_xmlns: If True, remove xmlns declarations and schema locations for more robust comparison
    """
    # First normalize without pretty print to get consistent attribute order
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.fromstring(xml_bytes, parser=parser)
    normalized_bytes = ET.tostring(tree, method='c14n')  # type: ignore
    
    # Re-parse and pretty print
    tree = ET.fromstring(normalized_bytes, parser=parser) 
    _normalize_decimal_values(tree)
    normalized = ET.tostring(tree, pretty_print=True).decode().replace('=".', '="0.')  # type: ignore
    if remove_xmlns:
        # Remove xmlns declarations
        normalized = re.sub(r'\s+xmlns(?::[^=]*)?="[^"]*"', '', normalized)
        # Remove schemaLocation and noNamespaceSchemaLocation attributes
        normalized = re.sub(r'\s+(?:xsi:)?schemaLocation="[^"]*"', '', normalized)
        normalized = re.sub(r'\s+(?:xsi:)?noNamespaceSchemaLocation="[^"]*"', '', normalized)
        
    return normalized

def sort_xml_elements(element: ET._Element) -> None:
    """Sort all children of an element by tag name recursively for consistent order.
    
    This is needed for testing because XML serialization order might differ between implementations
    but still represent the same data.
    """
    # Use list() to convert the element children to a list before sorting
    children = list(element)
    # Sort children by tag
    sorted_children = sorted(children, key=lambda e: str(e.tag))
    
    # Clear and re-add in sorted order
    for child in element:
        element.remove(child)
    for child in sorted_children:
        element.append(child)
    
    # Recursively sort grandchildren
    for child in element:
        sort_xml_elements(child)

def compare_xml_files(original_xml: bytes, output_xml: bytes) -> bool:
    """Compare two XML files by normalizing and sorting elements.
    
    Returns:
        True if they match after normalization, False otherwise
    """
    parser = ET.XMLParser(remove_blank_text=True)
    original_tree = ET.fromstring(original_xml, parser=parser)
    output_tree = ET.fromstring(output_xml, parser=parser)
    
    # Sort elements for consistent order
    sort_xml_elements(original_tree)
    sort_xml_elements(output_tree)
    
    # Convert to string and normalize
    orig_normalized = ET.tostring(original_tree, method='c14n').decode()
    output_normalized = ET.tostring(output_tree, method='c14n').decode()
    
    # Remove xmlns declarations and whitespace for more robust comparison
    orig_normalized = re.sub(r'\s+xmlns(?::[^=]*)?="[^"]*"', '', orig_normalized)
    output_normalized = re.sub(r'\s+xmlns(?::[^=]*)?="[^"]*"', '', output_normalized)
    
    # Normalize whitespace
    orig_normalized = re.sub(r'\s+', ' ', orig_normalized)
    output_normalized = re.sub(r'\s+', ' ', output_normalized)
    
    return orig_normalized == output_normalized

def normalize_xml_for_comparison(xml_bytes: bytes) -> str:
    """Normalize XML for comparison by removing whitespace and sorting attributes.
    
    Args:
        xml_bytes: The XML content as bytes
        
    Returns:
        Normalized string representation for comparison
    """
    # Parse the XML
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.fromstring(xml_bytes, parser=parser)
    
    # Convert to canonical XML
    canonical = ET.tostring(tree)
    
    # Remove all whitespace
    normalized = re.sub(r'\s+', '', canonical.decode())
    
    # Remove all namespace declarations for comparison
    normalized = re.sub(r'xmlns(?::[^=]*)?="[^"]*"', '', normalized)
    
    return normalized
