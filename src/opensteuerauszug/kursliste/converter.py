import sqlite3
import os
import xml.etree.ElementTree as ET
from typing import Optional, Union
from pathlib import Path

from opensteuerauszug.model.kursliste import (
    Share, Bond, Fund, Derivative, CoinBullion, CurrencyNote, LiborSwap,
    Sign, Da1Rate, KurslisteMetadata
)

CONVERTER_SCHEMA_VERSION = "1"
KURSLISTE_METADATA_KEY = "kursliste_metadata"


def create_schema(conn):
    """Creates the database schema. Every time there are changes to the schema, increment the CONVERTER_SCHEMA_VERSION.
    This will make sure that old converted databases are not used and the conversion is re-run when the converter code
    is updated."""
    cursor = conn.cursor()
    # Securities Table - New Schema
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS securities (
            kl_id TEXT PRIMARY KEY,
            valor_number TEXT,
            isin TEXT,
            tax_year INTEGER,
            security_type_identifier TEXT,
            security_object_blob BLOB
        )
    """)
    # Add Indexes for securities table
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_valor ON securities (valor_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_isin ON securities (isin);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tax_year ON securities (tax_year);")

    # Signs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signs (
            kl_id TEXT PRIMARY KEY,
            sign_value TEXT,
            tax_year INTEGER,
            source_file TEXT,
            sign_object_blob BLOB
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sign_value ON signs (sign_value);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sign_tax_year ON signs (tax_year);")

    # DA1 Rates Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS da1_rates (
            kl_id TEXT PRIMARY KEY,
            country TEXT,
            security_group TEXT,
            tax_year INTEGER,
            source_file TEXT,
            da1_rate_object_blob BLOB
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_da1_country ON da1_rates (country);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_da1_security_group ON da1_rates (security_group);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_da1_tax_year ON da1_rates (tax_year);")

    # Exchange Rates Daily Table - Changed rate from REAL to TEXT for Decimal precision
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exchange_rates_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_code TEXT, -- Foreign currency code (e.g., USD)
            date TEXT, -- Date of the exchange rate
            rate TEXT, -- Changed from REAL to TEXT to preserve Decimal precision
            denomination INTEGER,
            tax_year INTEGER,
            source_file TEXT
        )
    """)

    # Exchange Rates Monthly Table - Changed rate from REAL to TEXT for Decimal precision
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exchange_rates_monthly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_code TEXT,
            year INTEGER,
            month TEXT, -- e.g., "01", "12"
            rate TEXT, -- Changed from REAL to TEXT to preserve Decimal precision
            denomination INTEGER,
            tax_year INTEGER,
            source_file TEXT
        )
    """)

    # Exchange Rates Year End Table - Changed rate fields from REAL to TEXT for Decimal precision
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exchange_rates_year_end (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_code TEXT,
            year INTEGER,
            rate TEXT, -- Changed from REAL to TEXT to preserve Decimal precision
            rate_middle TEXT, -- Changed from REAL to TEXT to preserve Decimal precision
            denomination INTEGER,
            tax_year INTEGER,
            source_file TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("converter_schema_version", CONVERTER_SCHEMA_VERSION),
    )
    conn.commit()

def get_attr(elem, attr):
    """Helper to get attribute from an XML element."""
    return elem.get(attr)

def serialize_element_to_pydantic_json(elem, model_class):
    """
    Convert an XML element to a Pydantic model and serialize to JSON.

    Args:
        elem: The XML element
        model_class: The Pydantic model class to use

    Returns:
        JSON string of the model, or None if parsing fails
    """
    try:
        # Convert element subtree to XML string
        xml_str = ET.tostring(elem, encoding='unicode')

        # Try parsing with the original namespace first
        try:
            model_instance = model_class.from_xml(xml_str)
            return model_instance.model_dump_json(by_alias=True)
        except Exception as e1:
            # If that fails, try replacing the namespace with the expected one
            # This handles older kursliste versions with different namespaces
            xml_str_fixed = xml_str.replace(
                'http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste',
                'http://xmlns.estv.admin.ch/ictax/2.2.0/kursliste'
            )
            try:
                model_instance = model_class.from_xml(xml_str_fixed)
                return model_instance.model_dump_json(by_alias=True)
            except Exception as e2:
                # If both attempts fail, print warning and return None
                print(f"Warning: Failed to parse element to {model_class.__name__}: {e1}")
                return None

    except Exception as e:
        print(f"Warning: Failed to serialize element to {model_class.__name__}: {e}")
        return None

def read_conversion_metadata(db_file_path: Union[str, Path]) -> dict[str, str]:
    db_path = Path(db_file_path)
    if not db_path.exists():
        return {}
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'"
        )
        if cursor.fetchone() is None:
            return {}
        cursor.execute("SELECT key, value FROM metadata")
        return {row[0]: row[1] for row in cursor.fetchall()}
    except Exception:
        return {}
    finally:
        if conn:
            conn.close()


def read_metadata_value(db_file_path: Union[str, Path], key: str) -> Optional[str]:
    db_path = Path(db_file_path)
    if not db_path.exists():
        return None

    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'"
        )
        if cursor.fetchone() is None:
            return None

        cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row is None:
            return None
        return row[0]
    except Exception:
        return None
    finally:
        if conn:
            conn.close()


def read_kursliste_metadata(db_file_path: Union[str, Path]) -> Optional[KurslisteMetadata]:
    metadata_json = read_metadata_value(db_file_path, KURSLISTE_METADATA_KEY)
    if metadata_json is None:
        return None

    try:
        return KurslisteMetadata.model_validate_json(metadata_json)
    except Exception:
        return None


def convert_kursliste_xml_to_sqlite(
    xml_file_path: Union[str, Path],
    db_file_path: Union[str, Path],
    kursliste_metadata: Optional[KurslisteMetadata] = None
) -> bool:
    """
    Streaming conversion function that processes XML without loading entire file into memory.

    Args:
        xml_file_path: Path to the Kursliste XML file
        db_file_path: Path to the SQLite database file to create

    Returns:
        True if successful, raises exception if failed
    """
    conn = None
    try:
        # Create/connect to the SQLite database
        conn = sqlite3.connect(str(db_file_path))
        cursor = conn.cursor()

        # Create the database schema
        create_schema(conn)

        source_file_name = os.path.basename(str(xml_file_path))

        # Use iterparse for streaming XML processing
        print(f"Starting streaming parse of {xml_file_path}...")

        # Detect namespace
        namespace = None
        # Must cast to str because ET.iterparse expects str or bytes, not Path
        for event, elem in ET.iterparse(str(xml_file_path), events=('start',)):
            if '}' in elem.tag:
                namespace = elem.tag.split('}')[0][1:]
            break

        # Security types to process
        security_tags = ['share', 'bond', 'fund', 'derivative', 'coinBullion', 'currencyNote', 'liborSwap']
        security_model_map = {
            'share': Share,
            'bond': Bond,
            'fund': Fund,
            'derivative': Derivative,
            'coinBullion': CoinBullion,
            'currencyNote': CurrencyNote,
            'liborSwap': LiborSwap
        }

        counts = {tag: 0 for tag in security_tags}
        counts['exchangeRate'] = 0
        counts['exchangeRateMonthly'] = 0
        counts['exchangeRateYearEnd'] = 0
        counts['sign'] = 0
        counts['da1Rate'] = 0

        tax_year = None
        batch_size = 1000
        batch_count = 0

        # Batch lists for executemany
        securities_batch = []
        exchange_rates_daily_batch = []
        exchange_rates_monthly_batch = []
        exchange_rates_year_end_batch = []
        signs_batch = []
        da1_rates_batch = []

        def flush_batches():
            if securities_batch:
                cursor.executemany("""
                    INSERT INTO securities (
                        kl_id, valor_number, isin, tax_year,
                        security_type_identifier, security_object_blob
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, securities_batch)
                securities_batch.clear()
            if exchange_rates_daily_batch:
                cursor.executemany("""
                    INSERT INTO exchange_rates_daily (
                        currency_code, date, rate, denomination, tax_year, source_file
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, exchange_rates_daily_batch)
                exchange_rates_daily_batch.clear()
            if exchange_rates_monthly_batch:
                cursor.executemany("""
                    INSERT INTO exchange_rates_monthly (
                        currency_code, year, month, rate, denomination, tax_year, source_file
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, exchange_rates_monthly_batch)
                exchange_rates_monthly_batch.clear()
            if exchange_rates_year_end_batch:
                cursor.executemany("""
                    INSERT INTO exchange_rates_year_end (
                        currency_code, year, rate, rate_middle, denomination, tax_year, source_file
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, exchange_rates_year_end_batch)
                exchange_rates_year_end_batch.clear()
            if signs_batch:
                cursor.executemany("""
                    INSERT INTO signs (
                        kl_id, sign_value, tax_year, source_file, sign_object_blob
                    ) VALUES (?, ?, ?, ?, ?)
                """, signs_batch)
                signs_batch.clear()
            if da1_rates_batch:
                cursor.executemany("""
                    INSERT INTO da1_rates (
                        kl_id, country, security_group, tax_year, source_file, da1_rate_object_blob
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, da1_rates_batch)
                da1_rates_batch.clear()

        # First pass to get tax year from the root element attribute
        for event, elem in ET.iterparse(str(xml_file_path), events=('start',)):
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag == 'kursliste':
                # Year is an attribute of kursliste element
                tax_year_str = elem.get('year')
                if tax_year_str:
                    tax_year = int(tax_year_str)
                    print(f"Processing kursliste for tax year: {tax_year}")
                break  # Only process the first kursliste element

        if tax_year is not None:
            cursor.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("tax_year", str(tax_year)),
            )
        if kursliste_metadata is not None:
            cursor.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (KURSLISTE_METADATA_KEY, kursliste_metadata.model_dump_json()),
            )
        cursor.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("source_xml_file", source_file_name),
        )

        # Reset file parsing for main processing
        # Process XML in streaming fashion
        for event, elem in ET.iterparse(str(xml_file_path), events=('end',)):
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

            # Process security elements
            if tag in security_tags:
                kl_id = get_attr(elem, 'id')
                valor_number = get_attr(elem, 'valorNumber')
                isin = get_attr(elem, 'isin')
                security_type = get_attr(elem, 'securityType')

                # Convert element to Pydantic model and serialize to JSON
                model_class = security_model_map[tag]
                json_str = serialize_element_to_pydantic_json(elem, model_class)

                if json_str:  # Only insert if parsing succeeded
                    blob_data = json_str.encode('utf-8')
                    securities_batch.append((kl_id, valor_number, isin, tax_year, security_type, blob_data))

                counts[tag] += 1
                batch_count += 1

                # Clear element to free memory
                elem.clear()

            # Process exchange rates
            elif tag == 'exchangeRate':
                currency = get_attr(elem, 'currency')
                date = get_attr(elem, 'date')
                rate = get_attr(elem, 'value')
                denomination = get_attr(elem, 'denomination')

                exchange_rates_daily_batch.append((currency, date, rate, denomination, tax_year, source_file_name))

                counts['exchangeRate'] += 1
                batch_count += 1
                elem.clear()

            # Process monthly exchange rates
            elif tag == 'exchangeRateMonthly':
                currency = get_attr(elem, 'currency')
                year = get_attr(elem, 'year')
                month = get_attr(elem, 'month')
                rate = get_attr(elem, 'value')
                denomination = get_attr(elem, 'denomination')

                exchange_rates_monthly_batch.append((currency, year, month, rate, denomination, tax_year, source_file_name))

                counts['exchangeRateMonthly'] += 1
                batch_count += 1
                elem.clear()

            # Process year-end exchange rates
            elif tag == 'exchangeRateYearEnd':
                currency = get_attr(elem, 'currency')
                year = get_attr(elem, 'year')
                rate = get_attr(elem, 'value')
                rate_middle = get_attr(elem, 'valueMiddle')
                denomination = get_attr(elem, 'denomination')

                exchange_rates_year_end_batch.append((currency, year, rate, rate_middle, denomination, tax_year, source_file_name))

                counts['exchangeRateYearEnd'] += 1
                batch_count += 1
                elem.clear()

            # Process signs
            elif tag == 'sign':
                kl_id = get_attr(elem, 'id')
                sign_value = get_attr(elem, 'sign')

                # Convert element to Pydantic model and serialize to JSON
                json_str = serialize_element_to_pydantic_json(elem, Sign)

                if json_str:  # Only insert if parsing succeeded
                    blob_data = json_str.encode('utf-8')

                    signs_batch.append((kl_id, sign_value, tax_year, source_file_name, blob_data))

                    counts['sign'] += 1
                    batch_count += 1

                elem.clear()

            # Process DA1 rates
            elif tag == 'da1Rate':
                kl_id = get_attr(elem, 'id')
                country = get_attr(elem, 'country')
                security_group = get_attr(elem, 'securityGroup')

                # Convert element to Pydantic model and serialize to JSON
                json_str = serialize_element_to_pydantic_json(elem, Da1Rate)

                if json_str:  # Only insert if parsing succeeded
                    blob_data = json_str.encode('utf-8')

                    da1_rates_batch.append((kl_id, country, security_group, tax_year, source_file_name, blob_data))

                    counts['da1Rate'] += 1
                    batch_count += 1

                elem.clear()

            # Commit in batches to improve performance
            if batch_count >= batch_size:
                flush_batches()
                conn.commit()
                print(f"\rProcessed {sum(counts.values())} records...", end='', flush=True)
                batch_count = 0

        # Final commit
        flush_batches()
        conn.commit()

        # Print summary
        print(f"\nConversion complete:")
        print(f"  Shares: {counts['share']}")
        print(f"  Bonds: {counts['bond']}")
        print(f"  Funds: {counts['fund']}")
        print(f"  Derivatives: {counts['derivative']}")
        print(f"  Coin/Bullions: {counts['coinBullion']}")
        print(f"  Currency Notes: {counts['currencyNote']}")
        print(f"  LIBOR Swaps: {counts['liborSwap']}")
        print(f"  Exchange Rates (daily): {counts['exchangeRate']}")
        print(f"  Exchange Rates (monthly): {counts['exchangeRateMonthly']}")
        print(f"  Exchange Rates (year-end): {counts['exchangeRateYearEnd']}")
        print(f"  Signs: {counts['sign']}")
        print(f"  DA1 Rates: {counts['da1Rate']}")
        print(f"\nSuccessfully converted {xml_file_path} to {db_file_path}")

        return True

    except FileNotFoundError:
        raise FileNotFoundError(f"XML file not found at {xml_file_path}")
    except Exception as e:
        raise Exception(f"Conversion failed: {e}")
    finally:
        if conn:
            conn.close()
