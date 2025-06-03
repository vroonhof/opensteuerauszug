import pytest
import sqlite3
from decimal import Decimal, InvalidOperation
from datetime import date, datetime # Added datetime
from pathlib import Path # Added Path

# Import direct conversion function instead of subprocess
from scripts.convert_kursliste_to_sqlite import convert_kursliste_xml_to_sqlite

from opensteuerauszug.core.kursliste_db_reader import KurslisteDBReader
# Import Pydantic models for assertions
from opensteuerauszug.model.kursliste import (
    Security, Share, Bond, Fund, # Key security types
    SecurityTypeESTV # For checking type identifier
)

TAX_YEAR = 2023

# FIXED: Correct element ordering - Bonds BEFORE Shares (matches real files)
# This ordering is crucial for proper parsing with empty denylist
SAMPLE_XML_CONTENT = f"""<?xml version="1.0" encoding="UTF-8"?>
<kursliste xmlns="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xsi:schemaLocation="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste kursliste-2.0.0.xsd"
           version="2.0.0.1" creationDate="2024-01-01T00:00:00" year="{TAX_YEAR}">

    <bond id="202" quoted="true" source="KURSLISTE" securityGroup="BOND" securityType="BOND.BOND" 
          valorNumber="789012" isin="CH0078901234" securityName="Test Bond Corp" 
          currency="EUR" nominalValue="1000.00" country="CH" 
          institutionId="998" institutionName="Test Bank Bond" issueDate="{TAX_YEAR-3}-01-01" redemptionDate="{TAX_YEAR+7}-01-01">
        <yearend id="20201" quotationType="PERCENT" percent="101.25" taxValue="1012.50" />
    </bond>

    <fund id="303" quoted="true" source="KURSLISTE" securityGroup="FUND" securityType="FUND.DISTRIBUTION" 
          valorNumber="654321" isin="LU0065432109" securityName="Test Global Fund" 
          currency="USD" nominalValue="1.0" country="LU" 
          institutionId="997" institutionName="Test Bank Fund">
        <yearend id="30301" quotationType="PIECE" taxValue="75.20" taxValueCHF="68.70" />
    </fund>
    
    <fund id="501" quoted="true" source="KURSLISTE" securityGroup="FUND" securityType="FUND.ACCUMULATION" 
          valorNumber="111222" isin="LU0065432109" securityName="Test Global Fund Duplicate ISIN" 
          currency="EUR" nominalValue="1.0" country="LU" 
          institutionId="996" institutionName="Test Bank Fund Other">
        <yearend id='50101' quotationType='PIECE' />
    </fund>

    <share id="101" quoted="true" source="KURSLISTE" securityGroup="SHARE" securityType="SHARE.COMMON" 
           valorNumber="123456" isin="CH0012345678" securityName="Test Share AG" 
           currency="CHF" nominalValue="10.00" country="CH" 
           institutionId="999" institutionName="Test Bank Share">
        <yearend id="10101" quotationType="PIECE" taxValue="150.50" taxValueCHF="150.50" />
    </share>
    
    <share id="401" quoted="true" source="KURSLISTE" securityGroup="SHARE" securityType="SHARE.COMMON" 
           valorNumber="123456" isin="CH0000000401" securityName="Test Share AG Duplicate Valor" 
           currency="CHF" nominalValue="20.00" country="CH" 
           institutionId="999" institutionName="Test Bank Share">
        <yearend id='40101' quotationType='PIECE' />
    </share>

    <exchangeRate currency="USD" date="{TAX_YEAR}-10-25" denomination="1" value="0.8900" />
    <exchangeRate currency="EUR" date="{TAX_YEAR}-10-25" denomination="1" value="0.9500" />
    <exchangeRateMonthly currency="EUR" year="{TAX_YEAR}" month="10" denomination="1" value="0.9600" />
    <exchangeRateMonthly currency="GBP" year="{TAX_YEAR}" month="11" denomination="1" value="1.1200" />
    <exchangeRateYearEnd currency="JPY" year="{TAX_YEAR}" denomination="100" value="0.0065" />
    <exchangeRateYearEnd currency="USD" year="{TAX_YEAR}" denomination="1" value="0.8800" valueMiddle="0.8850" />
</kursliste>
"""

@pytest.fixture
def db_path(tmp_path):
    """
    Creates a test SQLite database by calling the conversion function directly.
    Yields the path to the generated database file.
    """
    sample_xml_file = tmp_path / f"sample_kursliste_{TAX_YEAR}.xml"
    sample_xml_file.write_text(SAMPLE_XML_CONTENT)
    
    output_db_file = tmp_path / f"kursliste_test_{TAX_YEAR}.sqlite"
    
    # Use direct function call instead of subprocess for easier debugging
    convert_kursliste_xml_to_sqlite(str(sample_xml_file), str(output_db_file))
    
    assert output_db_file.exists(), "SQLite DB file was not created by conversion script."
    
    return output_db_file

# Test Cases

def test_find_security_by_valor_singular(db_path):
    with KurslisteDBReader(str(db_path)) as reader:
        # Existing security (Share)
        sec = reader.find_security_by_valor(123456, TAX_YEAR) # Valor from Test Share AG
        assert sec is not None
        assert isinstance(sec, Share)
        assert sec.id == 101
        assert sec.securityName == "Test Share AG"
        assert sec.isin == "CH0012345678"
        assert sec.valorNumber == 123456
        assert sec.securityType == SecurityTypeESTV.SHARE_COMMON
        assert sec.institutionId == 999
        assert sec.institutionName == "Test Bank Share"

        # Non-existing valor
        assert reader.find_security_by_valor(999999, TAX_YEAR) is None
        assert reader.find_security_by_valor(123456, TAX_YEAR - 1) is None


def test_find_securities_by_valor_plural(db_path):
    with KurslisteDBReader(str(db_path)) as reader:
        secs = reader.find_securities_by_valor(123456, TAX_YEAR)
        assert len(secs) == 2 
        assert all(isinstance(s, Share) for s in secs)
        names = sorted([s.securityName for s in secs if s.securityName is not None])
        assert names == ["Test Share AG", "Test Share AG Duplicate Valor"]
        ids = sorted([s.id for s in secs])
        assert ids == [101, 401]

        secs_single = reader.find_securities_by_valor(789012, TAX_YEAR) 
        assert len(secs_single) == 1
        assert isinstance(secs_single[0], Bond)
        assert secs_single[0].id == 202
        
        assert len(reader.find_securities_by_valor(888888, TAX_YEAR)) == 0


def test_find_security_by_isin_singular(db_path):
    with KurslisteDBReader(str(db_path)) as reader:
        sec = reader.find_security_by_isin("CH0078901234", TAX_YEAR) 
        assert sec is not None
        assert isinstance(sec, Bond)
        assert sec.id == 202
        assert sec.securityName == "Test Bond Corp"
        assert sec.valorNumber == 789012
        assert sec.institutionId == 998
        assert sec.institutionName == "Test Bank Bond"

        assert reader.find_security_by_isin("XX0000000000", TAX_YEAR) is None
        assert reader.find_security_by_isin("CH0078901234", TAX_YEAR - 1) is None


def test_find_securities_by_isin_plural(db_path):
    with KurslisteDBReader(str(db_path)) as reader:
        secs = reader.find_securities_by_isin("LU0065432109", TAX_YEAR)
        assert len(secs) == 2
        assert all(isinstance(s, Fund) for s in secs)
        names = sorted([s.securityName for s in secs if s.securityName is not None])
        assert names == ["Test Global Fund", "Test Global Fund Duplicate ISIN"]
        ids = sorted([s.id for s in secs])
        assert ids == [303, 501]

        secs_single = reader.find_securities_by_isin("CH0012345678", TAX_YEAR) 
        assert len(secs_single) == 1
        assert isinstance(secs_single[0], Share)
        assert secs_single[0].id == 101
        
        assert len(reader.find_securities_by_isin("YY0000000000", TAX_YEAR)) == 0


def test_get_exchange_rate(db_path):
    with KurslisteDBReader(str(db_path)) as reader:
        assert reader.get_exchange_rate("USD", date(TAX_YEAR, 10, 25)) == Decimal("0.8900")
        assert reader.get_exchange_rate("EUR", date(TAX_YEAR, 10, 25)) == Decimal("0.9500") 
        assert reader.get_exchange_rate("GBP", date(TAX_YEAR, 11, 15)) == Decimal("1.1200") 
        assert reader.get_exchange_rate("JPY", date(TAX_YEAR, 12, 31)) == Decimal("0.0065") 
        assert reader.get_exchange_rate("JPY", date(TAX_YEAR, 1, 1)) == Decimal("0.0065")   
        assert reader.get_exchange_rate("AUD", date(TAX_YEAR, 10, 25)) is None
        assert reader.get_exchange_rate("USD", date(TAX_YEAR, 1, 1)) == Decimal("0.8800")
