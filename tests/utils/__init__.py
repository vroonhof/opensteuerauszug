# Import key functions for easier access
from .xml import (
    normalize_xml,
    sort_xml_elements,
    compare_xml_files,
    normalize_xml_for_comparison
)

from .samples import get_sample_files

__all__ = [
    'normalize_xml',
    'sort_xml_elements',
    'compare_xml_files',
    'normalize_xml_for_comparison',
    'get_sample_files'
]
