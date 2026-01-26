import argparse
import sqlite3
import json
import os
import xml.etree.ElementTree as ET
from decimal import Decimal
from opensteuerauszug.model.kursliste import (
    Share, Bond, Fund, Derivative, CoinBullion, CurrencyNote, LiborSwap,
    Sign, Da1Rate
)

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
        
        # First pass to get tax year from the root element attribute
        for event, elem in ET.iterparse(xml_file_path, events=('start',)):
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag == 'kursliste':
                # Year is an attribute of kursliste element
                tax_year_str = elem.get('year')
                if tax_year_str:
                    tax_year = int(tax_year_str)
                    print(f"Processing kursliste for tax year: {tax_year}")
                break  # Only process the first kursliste element
        
        # Reset file parsing for main processing
        # Process XML in streaming fashion
        for event, elem in ET.iterparse(xml_file_path, events=('end',)):
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
                currency = get_attr(elem, 'currency')
                date = get_attr(elem, 'date')
                rate = get_attr(elem, 'value')
                denomination = get_attr(elem, 'denomination')
                
                cursor.execute("""
                    INSERT INTO exchange_rates_daily (
                        currency_code, date, rate, denomination, tax_year, source_file
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (currency, date, rate, denomination, tax_year, source_file_name))
                
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
                
                cursor.execute("""
                    INSERT INTO exchange_rates_monthly (
                        currency_code, year, month, rate, denomination, tax_year, source_file
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (currency, year, month, rate, denomination, tax_year, source_file_name))
                
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
                
                cursor.execute("""
                    INSERT INTO exchange_rates_year_end (
                        currency_code, year, rate, rate_middle, denomination, tax_year, source_file
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (currency, year, rate, rate_middle, denomination, tax_year, source_file_name))
                
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
                kl_id = get_attr(elem, 'id')
                country = get_attr(elem, 'country')
                security_group = get_attr(elem, 'securityGroup')
                
                # Convert element to Pydantic model and serialize to JSON
                json_str = serialize_element_to_pydantic_json(elem, Da1Rate)
                
                if json_str:  # Only insert if parsing succeeded
                    blob_data = json_str.encode('utf-8')
                    
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
