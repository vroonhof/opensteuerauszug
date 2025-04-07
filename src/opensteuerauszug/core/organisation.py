"""
Organization-related helper functions for OpenSteuerauszug.

This module provides utilities for working with organization IDs and other
organization-related data in tax statements.
"""

import hashlib
from typing import Optional

from opensteuerauszug.model.ech0196 import TaxStatement

def hash_organization_name(org_name: str) -> str:
    """
    Generate a 3-digit number based on a secure hash of the organization name.
    
    Args:
        org_name: The name of the organization to hash
        
    Returns:
        A 3-digit string derived from the hash
    """
    if not org_name or not isinstance(org_name, str):
        return "000"  # Default if no name provided
    
    # Create a hash of the organization name
    hash_obj = hashlib.sha256(org_name.encode('utf-8'))
    hash_hex = hash_obj.hexdigest()
    
    # Take the first 6 characters of the hash (24 bits)
    # and convert to an integer, then modulo 1000 to get 3 digits
    hash_int = int(hash_hex[:6], 16) % 1000
    
    # Format as a 3-digit string with leading zeros
    return f"{hash_int:03d}"

def compute_org_nr(tax_statement: TaxStatement, override_org_nr: Optional[str] = None) -> str:
    """
    Compute the organization number (org_nr) for barcode generation.
    
    Args:
        tax_statement: The tax statement containing institution information
        override_org_nr: Optional override for the organization number
        
    Returns:
        A 5-digit string representing the organization number
        
    Raises:
        ValueError: If the override_org_nr is not a valid 5-digit string
    """
    # Validate and use the override_org_nr if provided
    if override_org_nr is not None:
        # Check if it's a valid 5-digit string
        if not isinstance(override_org_nr, str) or not override_org_nr.isdigit() or len(override_org_nr) != 5:
            raise ValueError(f"Invalid org_nr format: '{override_org_nr}'. Must be a 5-digit string.")
        return override_org_nr
    
    # We need to make up a unique org_nr, the spec suggests using the Bankleitzahl/BIC.
    # But we don't have that here, so we use the hash of the institution name and
    # squat in the 19000 range which belongs to the Swiss National Bank and is unused.
    # Get organization name from tax statement if available
    org_name = ""
    
    if hasattr(tax_statement, 'institution') and tax_statement.institution:
        if hasattr(tax_statement.institution, 'name') and tax_statement.institution.name:
            org_name = tax_statement.institution.name
    
    # If we have an org_name, use the hash
    if org_name:
        # Generate the org_nr using '19' prefix and 3-digit hash
        hash_suffix = hash_organization_name(org_name)
        return f"19{hash_suffix}"
    
    # Default fallback if all else fails
    return '19999' 