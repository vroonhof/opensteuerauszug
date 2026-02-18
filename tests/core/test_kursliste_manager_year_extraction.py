import pytest
from pathlib import Path
from opensteuerauszug.core.kursliste_manager import KurslisteManager

# Reusing the template from test_kursliste_manager.py
SAMPLE_XML_CONTENT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<kursliste xmlns="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xsi:schemaLocation="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste kursliste-2.0.0.xsd"
           version="2.0.0.1" creationDate="2024-01-01T00:00:00" year="{year}">
    <currency id="432" currency="CHF">
        <currencyName lang="de" name="Franken"/>
    </currency>
</kursliste>
"""

def create_sample_xml_no_year_in_filename(file_path: Path, year: int):
    content = SAMPLE_XML_CONTENT_TEMPLATE.format(year=year)
    file_path.write_text(content)
    return file_path

def test_get_year_from_xml_content_success(tmp_path):
    manager = KurslisteManager()
    file_path = tmp_path / "data_file.xml" # No year in filename
    create_sample_xml_no_year_in_filename(file_path, 2025)

    year = manager._get_year_from_xml_content(file_path)
    assert year == 2025

def test_get_year_from_xml_content_malformed(tmp_path):
    manager = KurslisteManager()
    file_path = tmp_path / "malformed.xml"
    file_path.write_text("<not_kursliste>...</not_kursliste>")

    year = manager._get_year_from_xml_content(file_path)
    assert year is None

def test_get_year_from_xml_content_no_year_attribute(tmp_path):
    manager = KurslisteManager()
    file_path = tmp_path / "no_year_attr.xml"
    file_path.write_text('<kursliste version="2.0"></kursliste>')

    year = manager._get_year_from_xml_content(file_path)
    assert year is None

def test_load_directory_fallback_to_xml_content(tmp_path):
    manager = KurslisteManager()
    # Create a file without year in filename
    file_path = tmp_path / "my_kursliste_data.xml"
    create_sample_xml_no_year_in_filename(file_path, 2026)

    manager.load_directory(tmp_path)

    assert manager.get_available_years() == [2026]
    accessor = manager.get_kurslisten_for_year(2026)
    assert accessor is not None
    assert accessor.data_source[0].year == 2026
