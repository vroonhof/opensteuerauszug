import argparse
import sqlite3
import json
import os
import xml.etree.ElementTree as ET
from decimal import Decimal

def create_schema(conn):
    """Creates the database schema."""
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
    conn.commit()

def get_text(elem, tag, namespace=None):
    """Helper to get text from an XML element."""
    if namespace:
        child = elem.find(f'{{{namespace}}}{tag}')
    else:
        child = elem.find(tag)
    return child.text if child is not None else None

def process_security_element(cursor, elem, tax_year, source_file_name, namespace):
    """Process a single security element (share, bond, fund, etc.) and insert into DB."""
    kl_id = get_text(elem, 'id', namespace)
    valor_number = get_text(elem, 'valorNumber', namespace)
    isin = get_text(elem, 'isin', namespace)
    security_type = get_text(elem, 'securityType', namespace)
    
    # Convert element to JSON for blob storage
    elem_dict = {}
    for child in elem:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        elem_dict[tag] = child.text
    
    blob_data = json.dumps(elem_dict).encode('utf-8')
    
    cursor.execute("""
        INSERT INTO securities (
            kl_id, valor_number, isin, tax_year, 
            security_type_identifier, security_object_blob
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (kl_id, valor_number, isin, tax_year, security_type, blob_data))

def convert_kursliste_xml_to_sqlite_streaming(xml_file_path, db_file_path):
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
        conn = sqlite3.connect(db_file_path)
        cursor = conn.cursor()
        
        # Create the database schema
        create_schema(conn)
        
        source_file_name = os.path.basename(xml_file_path)
        
        # Use iterparse for streaming XML processing
        print(f"Starting streaming parse of {xml_file_path}...")
        
        # Detect namespace
        namespace = None
        for event, elem in ET.iterparse(xml_file_path, events=('start',)):
            if '}' in elem.tag:
                namespace = elem.tag.split('}')[0][1:]
            break
        
        ns_prefix = f'{{{namespace}}}' if namespace else ''
        
        # Security types to process
        security_tags = ['share', 'bond', 'fund', 'derivative', 'coinBullion', 'currencyNote', 'liborSwap']
        
        counts = {tag: 0 for tag in security_tags}
        counts['exchangeRate'] = 0
        counts['sign'] = 0
        counts['da1Rate'] = 0
        
        tax_year = None
        batch_size = 1000
        batch_count = 0
        
        # Process XML in streaming fashion
        for event, elem in ET.iterparse(xml_file_path, events=('end',)):
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            # Extract tax year from root element
            if tag == 'kursliste' and tax_year is None:
                year_elem = elem.find(f'{ns_prefix}year')
                if year_elem is not None:
                    tax_year = int(year_elem.text)
                    print(f"Processing kursliste for tax year: {tax_year}")
            
            # Process security elements
            if tag in security_tags:
                kl_id = get_text(elem, 'id', namespace)
                valor_number = get_text(elem, 'valorNumber', namespace)
                isin = get_text(elem, 'isin', namespace)
                security_type = get_text(elem, 'securityType', namespace)
                
                # Convert element to dict for blob
                elem_dict = {child.tag.split('}')[-1]: child.text for child in elem}
                blob_data = json.dumps(elem_dict).encode('utf-8')
                
                cursor.execute("""
                    INSERT INTO securities (
                        kl_id, valor_number, isin, tax_year, 
                        security_type_identifier, security_object_blob
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (kl_id, valor_number, isin, tax_year, security_type, blob_data))
                
                counts[tag] += 1
                batch_count += 1
                
                # Clear element to free memory
                elem.clear()
                
            # Process exchange rates
            elif tag == 'exchangeRate':
                currency = get_text(elem, 'currency', namespace)
                date = get_text(elem, 'date', namespace)
                rate = get_text(elem, 'value', namespace)
                denomination = get_text(elem, 'denomination', namespace)
                
                cursor.execute("""
                    INSERT INTO exchange_rates_daily (
                        currency_code, date, rate, denomination, tax_year, source_file
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (currency, date, rate, denomination, tax_year, source_file_name))
                
                counts['exchangeRate'] += 1
                batch_count += 1
                elem.clear()
                
            # Process signs
            elif tag == 'sign':
                kl_id = get_text(elem, 'id', namespace)
                sign_value = get_text(elem, 'sign', namespace)
                
                elem_dict = {child.tag.split('}')[-1]: child.text for child in elem}
                blob_data = json.dumps(elem_dict).encode('utf-8')
                
                cursor.execute("""
                    INSERT INTO signs (
                        kl_id, sign_value, tax_year, source_file, sign_object_blob
                    ) VALUES (?, ?, ?, ?, ?)
                """, (kl_id, sign_value, tax_year, source_file_name, blob_data))
                
                counts['sign'] += 1
                batch_count += 1
                elem.clear()
                
            # Process DA1 rates
            elif tag == 'da1Rate':
                kl_id = get_text(elem, 'id', namespace)
                country = get_text(elem, 'country', namespace)
                security_group = get_text(elem, 'securityGroup', namespace)
                
                elem_dict = {child.tag.split('}')[-1]: child.text for child in elem}
                blob_data = json.dumps(elem_dict).encode('utf-8')
                
                cursor.execute("""
                    INSERT INTO da1_rates (
                        kl_id, country, security_group, tax_year, source_file, da1_rate_object_blob
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (kl_id, country, security_group, tax_year, source_file_name, blob_data))
                
                counts['da1Rate'] += 1
                batch_count += 1
                elem.clear()
            
            # Commit in batches to improve performance
            if batch_count >= batch_size:
                conn.commit()
                print(f"Processed {sum(counts.values())} records...", flush=True)
                batch_count = 0
        
        # Final commit
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
        print(f"  Exchange Rates: {counts['exchangeRate']}")
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

def convert_kursliste_xml_to_sqlite(xml_file_path, db_file_path, denylist=None):
    """
    Legacy wrapper - now uses streaming conversion by default.
    """
    return convert_kursliste_xml_to_sqlite_streaming(xml_file_path, db_file_path)

def main():
    parser = argparse.ArgumentParser(description="Convert Kursliste XML to SQLite database.")
    parser.add_argument("xml_file", help="Path to the Kursliste XML file.")
    parser.add_argument("db_file", help="Path to the SQLite database file.")
    args = parser.parse_args()

    try:
        # Call the core conversion function
        convert_kursliste_xml_to_sqlite(args.xml_file, args.db_file)
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    main()
