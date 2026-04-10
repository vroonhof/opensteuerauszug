import sqlite3
import os
import lxml.etree as ET
from typing import Optional, Union
from pathlib import Path

from opensteuerauszug.model.kursliste import (
    KurslisteMetadata,
    KURSLISTE_NS_2_0, KURSLISTE_NS_2_2,
)

CONVERTER_SCHEMA_VERSION = "3"
KURSLISTE_METADATA_KEY = "kursliste_metadata"

# Blob format identifier: "xml" means blobs are raw XML bytes (parsed via from_xml).
BLOB_FORMAT = "xml"


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

def create_idx(conn):
    """Creates the database indexes."""
    cursor = conn.cursor()

    # Add composite indexes for securities table matching query patterns
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_securities_isin_tax_year ON securities (isin, tax_year);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_securities_valor_tax_year ON securities (valor_number, tax_year);")

    # Add index for signs
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signs_value_tax_year ON signs (sign_value, tax_year);")

    # Add index for DA1
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_da1_country_group_tax_year ON da1_rates (country, security_group, tax_year);")

    # Add indexes for exchange rate tables
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exchange_daily_currency_date_year ON exchange_rates_daily (currency_code, date, tax_year);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exchange_monthly_currency_year_month ON exchange_rates_monthly (currency_code, year, month, tax_year);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exchange_year_end_currency_year ON exchange_rates_year_end (currency_code, year, tax_year);")

    conn.commit()


def _normalize_ns_to_22(xml_bytes: bytes) -> bytes:
    """Fast byte-level namespace normalization from v2.0 to v2.2."""
    return xml_bytes.replace(
        KURSLISTE_NS_2_0.encode('ascii'),
        KURSLISTE_NS_2_2.encode('ascii'),
    )


def serialize_element_to_xml_bytes(elem, needs_ns_rewrite):
    """
    Serialize an lxml element to XML bytes for storage.

    Skips the expensive Pydantic round-trip entirely. The element is serialized
    directly to XML bytes, with namespace normalization if needed.

    Args:
        elem: The lxml XML element
        needs_ns_rewrite: Whether to rewrite namespace from v2.0 to v2.2

    Returns:
        XML bytes, or None on error
    """
    try:
        xml_bytes = ET.tostring(elem)
        if needs_ns_rewrite:
            xml_bytes = _normalize_ns_to_22(xml_bytes)
        return xml_bytes
    except Exception as e:
        tag = getattr(elem, 'tag', '?')
        print(f"Warning: Failed to serialize element {tag}: {e}")
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

    Uses lxml iterparse for fast streaming, stores raw XML bytes as BLOBs
    (avoiding expensive Pydantic round-trips), and uses SQLite pragmas
    optimized for bulk inserts.

    Args:
        xml_file_path: Path to the Kursliste XML file
        db_file_path: Path to the SQLite database file to create

    Returns:
        True if successful, raises exception if failed
    """
    xml_file_path = str(xml_file_path)
    conn = None
    try:
        if not os.path.isfile(xml_file_path):
            raise FileNotFoundError(f"XML file not found at {xml_file_path}")

        # Create/connect to the SQLite database with bulk-insert optimizations
        conn = sqlite3.connect(str(db_file_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=OFF")
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.execute("PRAGMA cache_size=-65536")  # 64MB cache
        cursor.execute("PRAGMA temp_store=MEMORY")

        # Create the database schema
        create_schema(conn)

        source_file_name = os.path.basename(xml_file_path)

        print(f"Starting streaming parse of {xml_file_path}...")

        # Security types to process
        security_tags_local = frozenset([
            'share', 'bond', 'fund', 'derivative',
            'coinBullion', 'currencyNote', 'liborSwap',
        ])

        counts = {tag: 0 for tag in security_tags_local}
        counts['exchangeRate'] = 0
        counts['exchangeRateMonthly'] = 0
        counts['exchangeRateYearEnd'] = 0
        counts['sign'] = 0
        counts['da1Rate'] = 0

        tax_year = None
        batch_size = 5000
        batch_count = 0
        total_count = 0
        needs_ns_rewrite = False

        # Batch lists for executemany
        securities_batch = []
        exchange_rates_daily_batch = []
        exchange_rates_monthly_batch = []
        exchange_rates_year_end_batch = []
        signs_batch = []
        da1_rates_batch = []

        # Pre-compiled SQL statements
        sql_securities = """
            INSERT INTO securities (
                kl_id, valor_number, isin, tax_year,
                security_type_identifier, security_object_blob
            ) VALUES (?, ?, ?, ?, ?, ?)"""
        sql_exchange_daily = """
            INSERT INTO exchange_rates_daily (
                currency_code, date, rate, denomination, tax_year, source_file
            ) VALUES (?, ?, ?, ?, ?, ?)"""
        sql_exchange_monthly = """
            INSERT INTO exchange_rates_monthly (
                currency_code, year, month, rate, denomination, tax_year, source_file
            ) VALUES (?, ?, ?, ?, ?, ?, ?)"""
        sql_exchange_year_end = """
            INSERT INTO exchange_rates_year_end (
                currency_code, year, rate, rate_middle, denomination, tax_year, source_file
            ) VALUES (?, ?, ?, ?, ?, ?, ?)"""
        sql_signs = """
            INSERT INTO signs (
                kl_id, sign_value, tax_year, source_file, sign_object_blob
            ) VALUES (?, ?, ?, ?, ?)"""
        sql_da1_rates = """
            INSERT INTO da1_rates (
                kl_id, country, security_group, tax_year, source_file, da1_rate_object_blob
            ) VALUES (?, ?, ?, ?, ?, ?)"""

        def flush_batches():
            if securities_batch:
                cursor.executemany(sql_securities, securities_batch)
                securities_batch.clear()
            if exchange_rates_daily_batch:
                cursor.executemany(sql_exchange_daily, exchange_rates_daily_batch)
                exchange_rates_daily_batch.clear()
            if exchange_rates_monthly_batch:
                cursor.executemany(sql_exchange_monthly, exchange_rates_monthly_batch)
                exchange_rates_monthly_batch.clear()
            if exchange_rates_year_end_batch:
                cursor.executemany(sql_exchange_year_end, exchange_rates_year_end_batch)
                exchange_rates_year_end_batch.clear()
            if signs_batch:
                cursor.executemany(sql_signs, signs_batch)
                signs_batch.clear()
            if da1_rates_batch:
                cursor.executemany(sql_da1_rates, da1_rates_batch)
                da1_rates_batch.clear()

        # Quick first pass: detect namespace and tax year from root element only
        namespace = None
        for _event, elem in ET.iterparse(xml_file_path, events=('start',)):
            tag = elem.tag
            if tag and '}' in tag:
                namespace = tag.split('}')[0][1:]
                needs_ns_rewrite = (namespace == KURSLISTE_NS_2_0)
            tax_year_str = elem.get('year')
            if tax_year_str:
                tax_year = int(tax_year_str)
                print(f"Processing kursliste for tax year: {tax_year}")
            break  # Only need the root element

        # Build namespace-qualified tag set for fast lookup
        ns_qualified_tags = {}
        all_tags = (
            list(security_tags_local)
            + ['exchangeRate', 'exchangeRateMonthly', 'exchangeRateYearEnd',
               'sign', 'da1Rate']
        )
        for t in all_tags:
            if namespace:
                ns_qualified_tags[f'{{{namespace}}}{t}'] = t
            else:
                ns_qualified_tags[t] = t

        # Write metadata
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
        cursor.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("blob_format", BLOB_FORMAT),
        )

        # Main pass: only subscribe to 'end' events to avoid processing millions
        # of unused 'start' events. Use tag filtering for the top-level tags we need.
        root = None
        for event, elem in ET.iterparse(xml_file_path, events=('end',)):
            # Capture root element (first element to appear; its 'end' fires last,
            # but we can detect it as the parent of the first processed child)
            if root is None:
                parent = elem.getparent()
                if parent is not None:
                    root = parent

            tag = ns_qualified_tags.get(elem.tag)
            if tag is None:
                continue

            # Process security elements
            if tag in security_tags_local:
                kl_id = elem.get('id')
                valor_number = elem.get('valorNumber')
                isin = elem.get('isin')
                security_type = elem.get('securityType')

                blob_data = serialize_element_to_xml_bytes(elem, needs_ns_rewrite)

                if blob_data:
                    securities_batch.append((kl_id, valor_number, isin, tax_year, security_type, blob_data))

                counts[tag] += 1
                batch_count += 1

            # Process exchange rates
            elif tag == 'exchangeRate':
                exchange_rates_daily_batch.append((
                    elem.get('currency'), elem.get('date'), elem.get('value'),
                    elem.get('denomination'), tax_year, source_file_name,
                ))
                counts['exchangeRate'] += 1
                batch_count += 1

            # Process monthly exchange rates
            elif tag == 'exchangeRateMonthly':
                exchange_rates_monthly_batch.append((
                    elem.get('currency'), elem.get('year'), elem.get('month'),
                    elem.get('value'), elem.get('denomination'), tax_year, source_file_name,
                ))
                counts['exchangeRateMonthly'] += 1
                batch_count += 1

            # Process year-end exchange rates
            elif tag == 'exchangeRateYearEnd':
                exchange_rates_year_end_batch.append((
                    elem.get('currency'), elem.get('year'), elem.get('value'),
                    elem.get('valueMiddle'), elem.get('denomination'), tax_year, source_file_name,
                ))
                counts['exchangeRateYearEnd'] += 1
                batch_count += 1

            # Process signs
            elif tag == 'sign':
                kl_id = elem.get('id')
                sign_value = elem.get('sign')
                blob_data = serialize_element_to_xml_bytes(elem, needs_ns_rewrite)
                if blob_data:
                    signs_batch.append((kl_id, sign_value, tax_year, source_file_name, blob_data))
                    counts['sign'] += 1
                    batch_count += 1

            # Process DA1 rates
            elif tag == 'da1Rate':
                kl_id = elem.get('id')
                country = elem.get('country')
                security_group = elem.get('securityGroup')
                blob_data = serialize_element_to_xml_bytes(elem, needs_ns_rewrite)
                if blob_data:
                    da1_rates_batch.append((kl_id, country, security_group, tax_year, source_file_name, blob_data))
                    counts['da1Rate'] += 1
                    batch_count += 1

            # Free memory: clear processed element and remove from root
            elem.clear()
            if root is not None and len(root):
                # Remove processed direct children from root to free memory
                while len(root) and root[0].getparent() is root:
                    del root[0]

            # Flush batches periodically
            if batch_count >= batch_size:
                flush_batches()
                total_count += batch_count
                print(f"\rProcessed {total_count} records...", end='', flush=True)
                batch_count = 0

        # Final commit
        flush_batches()
        conn.commit()

        total_count += batch_count
        print(f"\nCreating indexes...")
        create_idx(conn)

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
