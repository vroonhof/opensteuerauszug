"""
Manager for Kursliste (price list) files.

This module provides functionality to load and manage multiple Kursliste instances
for different tax years.
"""

import re
import sqlite3
import datetime
import defusedxml.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Union

from opensteuerauszug.kursliste.converter import (
    convert_kursliste_xml_to_sqlite,
    read_metadata_value,
)
from opensteuerauszug.model.kursliste import Kursliste, Payment
from .kursliste_db_reader import KurslisteDBReader
from .kursliste_accessor import KurslisteAccessor

# Definition and institution tags omitted by the SQLite converter
KURSLISTE_UNUSED_XML_TAGS = {
    "canton",
    "capitalKey",
    "country",
    "currency",
    "securityGroup",
    "securityType",
    "legalForm",
    "sector",
    "shortCut",
    "capitalisationRate",
    "mediumTermBond",
    "institution",
}


class KurslisteManager:
    """
    Manages KurslisteAccessors for different tax years.

    This class loads Kursliste data (prioritizing on-disk SQLite over XML,
    and streaming XML into an in-memory SQLite database), wraps it
    in a KurslisteAccessor, and provides methods to retrieve data.
    """

    def __init__(self):
        """Initialize an empty KurslisteManager."""
        self.kurslisten: Dict[int, KurslisteAccessor] = {}  # Changed type hint

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
            # Use iterparse to read only the start of the root element
            # Open file manually to ensure it's closed properly
            with file_path.open('rb') as f:
                context = ET.iterparse(f, events=('start',))
                for event, elem in context:
                    year_str = elem.get('year')
                    if year_str:
                        year = int(year_str)
                        # Basic sanity check for a reasonable year range
                        if 1900 < year < 2100:
                            return year
                    # We only need to check the root element
                    break
        except Exception as e:
            print(f"Warning: Could not extract year from XML content of {file_path.name}: {e}")
        return None

    def _get_year_from_sqlite_metadata(self, file_path: Path) -> Optional[int]:
        """
        Extracts the tax year from a SQLite database's metadata table.
        Used as a fallback when filename doesn't contain a year and to verify year consistency.

        Args:
            file_path: Path to the SQLite file

        Returns:
            Year as integer if found, None otherwise
        """
        try:
            year_str = read_metadata_value(file_path, "tax_year")
            if year_str:
                year = int(year_str)
                if 1900 < year < 2100:
                    return year
        except Exception as e:
            print(f"Warning: Could not extract year from SQLite metadata of {file_path.name}: {e}")
        return None

    def load_directory(self, directory_path: Union[str, Path]) -> None:
        """
        Load Kursliste data (SQLite DBs or XML files) from the specified directory.
        Prioritizes on-disk SQLite DBs (e.g., kursliste_YYYY.sqlite) if found for a year.
        Otherwise, streams XML files for that year into an in-memory SQLite database.

        For both SQLite and XML files, tries to extract year from filename first,
        then falls back to metadata / XML content if needed.

        Args:
            directory_path: Path to directory containing Kursliste XML/SQLite files
        """
        directory = Path(directory_path)
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Directory does not exist or is not a directory: {directory}")

        potential_files = list(directory.glob("*.xml")) + list(directory.glob("*.sqlite"))

        # Determine years and file types
        year_file_map: Dict[int, Dict[str, List[Path]]] = (
            {}
        )  # year -> {"xml": [...], "sqlite": [...]}

        for file_path in potential_files:
            year = None

            # For SQLite files, prefer the authoritative metadata tax_year up front
            # so a DB whose filename year is later than its metadata year still
            # takes precedence over XML files for its metadata year.
            if file_path.suffix == ".sqlite":
                filename_year = self._get_year_from_filename(file_path.name)
                metadata_year = self._get_year_from_sqlite_metadata(file_path)
                if (
                    filename_year is not None
                    and metadata_year is not None
                    and filename_year != metadata_year
                ):
                    print(
                        f"Warning: Year mismatch for {file_path.name}. Extracted year: {filename_year}, "
                        f"SQLite metadata year: {metadata_year}. Using SQLite metadata year: {metadata_year}."
                    )
                year = metadata_year if metadata_year is not None else filename_year

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

        processed_years = set()
        while True:
            pending_years = sorted(y for y in year_file_map if y not in processed_years)
            if not pending_years:
                break
            year = pending_years[0]
            processed_years.add(year)

            if year in self.kurslisten:  # Already processed (e.g. by a DB for this year)
                continue

            files = year_file_map[year]
            sqlite_files = list(files["sqlite"])
            xml_files = list(files["xml"])

            # Prioritize SQLite DB
            # Use the first SQLite file found for that year (e.g. kursliste_YYYY.sqlite)
            db_loaded_for_year = False
            data_source: Optional[KurslisteDBReader] = None

            if sqlite_files:
                # Filter out any SQLite files whose authoritative metadata year mismatches
                valid_sqlite_files: List[Path] = []
                for f_sqlite in sqlite_files:
                    metadata_year = self._get_year_from_sqlite_metadata(f_sqlite)
                    if metadata_year is not None and metadata_year != year:
                        print(
                            f"Warning: Year mismatch for {f_sqlite.name}. Extracted year: {year}, "
                            f"SQLite metadata year: {metadata_year}. Using SQLite metadata year: {metadata_year}."
                        )
                        year_file_map.setdefault(metadata_year, {"xml": [], "sqlite": []})
                        year_file_map[metadata_year]["sqlite"].append(f_sqlite)
                        processed_years.discard(metadata_year)
                    else:
                        valid_sqlite_files.append(f_sqlite)

                if valid_sqlite_files:
                    # Attempt to find a specifically named SQLite file first
                    expected_db_name = f"kursliste_{year}.sqlite"
                    db_to_load = None
                    for f_sqlite in valid_sqlite_files:
                        if f_sqlite.name == expected_db_name:
                            db_to_load = f_sqlite
                            break
                    if not db_to_load:  # If not found, take the first sqlite file for that year
                        db_to_load = valid_sqlite_files[0]

                    try:
                        print(f"Loading KurslisteDBReader for year {year} from {db_to_load.name}")
                        data_source = KurslisteDBReader(str(db_to_load))
                        db_loaded_for_year = True
                    except Exception as e:
                        print(
                            f"Error loading KurslisteDBReader from {db_to_load.name} for year {year}: {e}"
                        )
                        # Fallback to XML if DB loading fails for some reason
                        db_loaded_for_year = False
                        data_source = None

            if not db_loaded_for_year and xml_files:  # Fallback to XML files via in-memory SQLite
                valid_xml_files: List[Path] = []
                for xml_file_path in xml_files:
                    actual_year = self._get_year_from_xml_content(xml_file_path)
                    if actual_year is None:
                        print(
                            f"Warning: Skipping invalid Kursliste XML {xml_file_path.name} (missing root year attribute)."
                        )
                        continue
                    if actual_year != year:
                        print(
                            f"Warning: Year mismatch for {xml_file_path.name}. Extracted year: {year}, "
                            f"XML content year: {actual_year}. Using XML content year: {actual_year}."
                        )
                        year_file_map.setdefault(actual_year, {"xml": [], "sqlite": []})
                        year_file_map[actual_year]["xml"].append(xml_file_path)
                        processed_years.discard(actual_year)
                        continue
                    valid_xml_files.append(xml_file_path)

                if valid_xml_files:
                    mem_conn = sqlite3.connect(":memory:")
                    any_loaded = False
                    for xml_file_path in valid_xml_files:
                        try:
                            print(
                                f"Loading Kursliste XML for year {year} into in-memory SQLite from {xml_file_path.name}"
                            )
                            convert_kursliste_xml_to_sqlite(xml_file_path, mem_conn)
                            any_loaded = True
                        except Exception as e:
                            print(
                                f"Error loading Kursliste XML from {xml_file_path.name} for year {year}: {e}"
                            )
                    if any_loaded:
                        data_source = KurslisteDBReader(mem_conn)
                    else:
                        mem_conn.close()

            if data_source:
                self.kurslisten[year] = KurslisteAccessor(data_source, year)

    def _load_kursliste_from_file(
        self, file_path: Path
    ) -> Kursliste:  # This method might become less central or removed
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
            return Kursliste.from_xml_file(file_path, denylist=KURSLISTE_UNUSED_XML_TAGS)
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

    def ensure_year_available(
        self, required_year: int, kursliste_dir: Optional[Path] = None
    ) -> None:
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
            available_years_str = (
                ", ".join(str(y) for y in available_years) if available_years else "none"
            )
            dir_info = f" in {kursliste_dir}" if kursliste_dir else ""
            raise ValueError(
                f"Kursliste data for tax year {required_year} not found. "
                f"Available years: {available_years_str}. "
                f"Please ensure kursliste_{required_year}.sqlite or kursliste_{required_year}.xml exists{dir_info}"
            )

    def get_security_price(
        self, tax_year: int, isin: str, price_date: Optional[datetime.date] = None
    ) -> Optional[Decimal]:
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
        # The Security object is a Pydantic model from opensteuerauszug.model.kursliste
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
                        if daily_price_info.taxValue is not None:  # Fallback
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
                yearend_price_list = [yearend_price_list]  # Ensure it's iterable

            for ye_price_info in yearend_price_list:
                if ye_price_info:  # Ensure the yearend price object itself is not None
                    if ye_price_info.taxValueCHF is not None:
                        return Decimal(str(ye_price_info.taxValueCHF))
                    if ye_price_info.taxValue is not None:  # Fallback
                        return Decimal(str(ye_price_info.taxValue))

        return None  # No suitable price found in the security model

    def get_security_payments(self, tax_year: int, isin: str) -> List["Payment"]:
        """Retrieve payment records for a security from the Kursliste."""
        accessor = self.get_kurslisten_for_year(tax_year)
        if not accessor:
            return []

        security_model = accessor.get_security_by_isin(isin)
        if not security_model:
            return []

        payments = getattr(security_model, 'payment', [])
        return [p for p in payments if not p.deleted]
