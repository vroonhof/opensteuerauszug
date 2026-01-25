"""
Manager for Kursliste (price list) files.

This module provides functionality to load and manage multiple Kursliste instances
for different tax years.
"""

import os
import re # For parsing year from filename
import datetime
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Union # Union will be removed from self.kurslisten type

from opensteuerauszug.model.kursliste import Kursliste, Security, Payment  # Added Payment for type hint
from .kursliste_db_reader import KurslisteDBReader
from .kursliste_accessor import KurslisteAccessor # Added import


class KurslisteManager:
    """
    Manages KurslisteAccessors for different tax years.
    
    This class loads Kursliste data (prioritizing SQLite over XML), wraps it
    in a KurslisteAccessor, and provides methods to retrieve data.
    """
    
    def __init__(self):
        """Initialize an empty KurslisteManager."""
        self.kurslisten: Dict[int, KurslisteAccessor] = {} # Changed type hint

    def _get_year_from_filename(self, filename: str) -> Optional[int]:
        """
        Extracts the year from a filename like 'kursliste_2023.xml' or '2023_data.xml'.
        Tries to find a 4-digit number that looks like a year.
        """
        # Try to find 'kursliste_YYYY' or 'YYYY'
        match = re.search(r'(?:kursliste_)?(\d{4})', filename)
        if match:
            year_str = match.group(1)
            year = int(year_str)
            # Basic sanity check for a reasonable year range
            if 1900 < year < 2100:
                return year
        return None

    def _get_year_from_xml_content(self, file_path: Path) -> Optional[int]:
        """
        Extracts the year from XML content by reading the 'year' attribute of the root element.
        This is used as a fallback when filename doesn't contain a year.
        
        Args:
            file_path: Path to the XML file
            
        Returns:
            Year as integer if found, None otherwise
        """
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            year_str = root.get('year')
            if year_str:
                year = int(year_str)
                # Basic sanity check for a reasonable year range
                if 1900 < year < 2100:
                    return year
        except Exception as e:
            print(f"Warning: Could not extract year from XML content of {file_path.name}: {e}")
        return None

    def load_directory(self, directory_path: Union[str, Path]) -> None:
        """
        Load Kursliste data (SQLite DBs or XML files) from the specified directory.
        Prioritizes SQLite DBs (e.g., kursliste_YYYY.sqlite) if found for a year.
        Otherwise, loads XML files for that year.
        
        For XML files, tries to extract year from filename first, then from XML content if needed.
        
        Args:
            directory_path: Path to directory containing Kursliste XML files
        """
        directory = Path(directory_path)
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Directory does not exist or is not a directory: {directory}")

        potential_files = list(directory.glob("*.xml")) + list(directory.glob("*.sqlite"))
        
        # Determine years and file types
        year_file_map: Dict[int, Dict[str, List[Path]]] = {} # year -> {"xml": [...], "sqlite": [...]}

        for file_path in potential_files:
            year = None
            
            # For SQLite files, always try filename extraction
            if file_path.suffix == ".sqlite":
                year = self._get_year_from_filename(file_path.name)
            
            # For XML files, try filename first, then XML content
            elif file_path.suffix == ".xml":
                year = self._get_year_from_filename(file_path.name)
                if year is None:
                    year = self._get_year_from_xml_content(file_path)
            
            if year:
                year_file_map.setdefault(year, {"xml": [], "sqlite": []})
                if file_path.suffix == ".xml":
                    year_file_map[year]["xml"].append(file_path)
                elif file_path.suffix == ".sqlite":
                    year_file_map[year]["sqlite"].append(file_path)
        
        for year, files in sorted(year_file_map.items()):
            if year in self.kurslisten: # Already processed (e.g. by a DB for this year)
                continue

            sqlite_files = files["sqlite"]
            xml_files = files["xml"]

            # Prioritize SQLite DB
            # Use the first SQLite file found for that year (e.g. kursliste_YYYY.sqlite)
            db_loaded_for_year = False
            data_source: Optional[Union[KurslisteDBReader, List[Kursliste]]] = None # Initialize data_source

            if sqlite_files:
                # Attempt to find a specifically named SQLite file first
                expected_db_name = f"kursliste_{year}.sqlite"
                db_to_load = None
                for f_sqlite in sqlite_files:
                    if f_sqlite.name == expected_db_name:
                        db_to_load = f_sqlite
                        break
                if not db_to_load: # If not found, take the first sqlite file for that year
                    db_to_load = sqlite_files[0]
                
                data_source: Optional[Union[KurslisteDBReader, List[Kursliste]]] = None
                try:
                    print(f"Loading KurslisteDBReader for year {year} from {db_to_load.name}")
                    data_source = KurslisteDBReader(str(db_to_load))
                    db_loaded_for_year = True
                except Exception as e:
                    print(f"Error loading KurslisteDBReader from {db_to_load.name} for year {year}: {e}")
                    # Fallback to XML if DB loading fails for some reason
                    db_loaded_for_year = False # Ensure this is reset
                    data_source = None # Clear data_source from failed DB attempt
            
            if not db_loaded_for_year and xml_files: # Fallback to XML files
                loaded_xmls_for_year: List[Kursliste] = []
                for xml_file_path in xml_files:
                    try:
                        print(f"Loading Kursliste XML for year {year} from {xml_file_path.name}")
                        kursliste_obj = Kursliste.from_xml_file(xml_file_path, denylist=set())
                        
                        if kursliste_obj.year != year:
                            # This situation might indicate a mismatch between extracted year and XML content.
                            # We'll use the XML content year as authoritative.
                            print(f"Warning: Year mismatch for {xml_file_path.name}. Extracted year: {year}, XML content year: {kursliste_obj.year}. Using XML content year: {kursliste_obj.year}.")
                            # Update the year_file_map to use the correct year from XML content
                            actual_year = kursliste_obj.year
                            if actual_year != year:
                                # Move this file to the correct year bucket
                                year_file_map.setdefault(actual_year, {"xml": [], "sqlite": []})
                                year_file_map[actual_year]["xml"].append(xml_file_path)
                                # We'll process this in a later iteration, skip for now
                                continue
                        
                        loaded_xmls_for_year.append(kursliste_obj)
                    except Exception as e:
                        print(f"Error loading Kursliste XML from {xml_file_path.name} for year {year}: {e}")
                
                if loaded_xmls_for_year:
                    data_source = loaded_xmls_for_year
            
            if data_source:
                self.kurslisten[year] = KurslisteAccessor(data_source, year)

    def _load_kursliste_from_file(self, file_path: Path) -> Kursliste: # This method might become less central or removed
        """
        Load a Kursliste from an XML file. (Consider if this is still needed as public/private)
        Now internal logic in load_directory uses Kursliste.from_xml_file directly.
        
        Args:
            file_path: Path to the XML file
            
        Returns:
            Parsed Kursliste object
        """
        try:
            # Use the from_xml_file class method to parse the XML file
            return Kursliste.from_xml_file(file_path, denylist=set()) # Ensure all data loaded
        except Exception as e:
            # Provide more context about the error
            raise ValueError(f"Error parsing Kursliste from {file_path}: {str(e)}") from e
        
    def get_kurslisten_for_year(self, tax_year: int) -> Optional[KurslisteAccessor]:
        """
        Get the KurslisteAccessor for a specific tax year.
        
        Args:
            tax_year: The tax year to retrieve the accessor for.
            
        Returns:
            KurslisteAccessor for the specified year, or None if not found.
        """
        return self.kurslisten.get(tax_year)
    
    
    def get_available_years(self) -> List[int]:
        """
        Get a list of all tax years for which Kursliste data is available.
        
        Returns:
            List of available tax years, sorted
        """
        return sorted(self.kurslisten.keys())
    
    def ensure_year_available(self, required_year: int, kursliste_dir: Optional[Path] = None) -> None:
        """
        Validate that Kursliste data is available for the required year.
        Raises a clear error if the year is not available.
        
        Args:
            required_year: The tax year that must be available
            kursliste_dir: Optional directory path to include in error message
            
        Raises:
            ValueError: If the required year is not available with helpful error message
        """
        available_years = self.get_available_years()
        if required_year not in available_years:
            available_years_str = ", ".join(str(y) for y in available_years) if available_years else "none"
            dir_info = f" in {kursliste_dir}" if kursliste_dir else ""
            raise ValueError(
                f"Kursliste data for tax year {required_year} not found. "
                f"Available years: {available_years_str}. "
                f"Please ensure kursliste_{required_year}.sqlite or kursliste_{required_year}.xml exists{dir_info}"
            )
        
    def get_security_price(self, tax_year: int, isin: str, price_date: Optional[datetime.date] = None) -> Optional[Decimal]:
        """
        Get the price of a security for a specific tax year and ISIN.
        If price_date is provided, it attempts to find the price for that specific date.
        Otherwise, behavior might depend on the underlying data source (e.g., year-end price).

        Args:
            tax_year: The tax year to retrieve the price for.
            isin: The ISIN of the security.
            price_date: Optional specific date to get price for.

        Returns:
            Price as Decimal if available, otherwise None.
        """
        accessor = self.get_kurslisten_for_year(tax_year)

        if not accessor:
            return None

        # KurslisteAccessor.get_security_by_isin returns Optional[Security]
        # The Security object is a Pydantic model from ..model.kursliste
        security_model = accessor.get_security_by_isin(isin) 

        if not security_model:
            return None
        
        # Price extraction logic from the Pydantic Security model instance
        # This logic is similar to what was previously in the XML path

        # If a specific date is requested, try to find a daily price
        if price_date:
            if hasattr(security_model, 'daily') and security_model.daily:
                for daily_price_info in security_model.daily:
                    if daily_price_info.date == price_date:
                        if daily_price_info.taxValueCHF is not None:
                            return Decimal(str(daily_price_info.taxValueCHF))
                        if daily_price_info.taxValue is not None: # Fallback
                            return Decimal(str(daily_price_info.taxValue))
                        # If only percent is available, one might need nominal value and quotation type logic
                        # For now, sticking to taxValueCHF and taxValue.
            # If specific date price not found in daily, we might fall through to year-end if desired,
            # or return None if strict daily price for that date is required.
            # Current logic will fall through to year-end. If strict daily wanted, return None here.

        # If no specific date, or if daily price for specific date not found, try year-end price.
        if hasattr(security_model, 'yearend') and security_model.yearend:
            # security_model.yearend can be a list (e.g., for Share) or a single object (e.g., for Bond)
            yearend_price_list = security_model.yearend
            if not isinstance(yearend_price_list, list):
                yearend_price_list = [yearend_price_list] # Ensure it's iterable
            
            for ye_price_info in yearend_price_list:
                if ye_price_info: # Ensure the yearend price object itself is not None
                    if ye_price_info.taxValueCHF is not None:
                        return Decimal(str(ye_price_info.taxValueCHF))
                    if ye_price_info.taxValue is not None: # Fallback
                        return Decimal(str(ye_price_info.taxValue))
        
        return None # No suitable price found in the security model

    def get_security_payments(self, tax_year: int, isin: str) -> List["Payment"]:
        """Retrieve payment records for a security from the Kursliste."""
        accessor = self.get_kurslisten_for_year(tax_year)
        if not accessor:
            return []

        security_model = accessor.get_security_by_isin(isin)
        if not security_model:
            return []

        payments = security_model.payment
        return [p for p in payments if not p.deleted]
