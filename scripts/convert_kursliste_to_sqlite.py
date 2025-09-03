import argparse
import argparse
import sqlite3
import json # Added import
from pydantic import ValidationError # Added import
from opensteuerauszug.model.kursliste import Kursliste
import os # Added for os.path.basename

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

def populate_data(conn, kursliste, tax_year, source_file_name):
    """Populates the database with data from the Kursliste."""
    cursor = conn.cursor()

    # The Kursliste model has separate lists for different security types (shares, bonds, etc.)
    # We need to iterate through all of them.
    # For simplicity, starting with 'shares'. This might need to be expanded.
    # Wertschriften is not a direct attribute of Kursliste, rather there are specific lists like kursliste.shares, kursliste.bonds etc.
    
    # Consolidate all security types into one list for iteration
    all_securities = []
    # Based on Kursliste model, these are the lists of different security types
    security_lists_names = ['shares', 'bonds', 'funds', 'derivatives', 'coinBullions', 'currencyNotes', 'liborSwaps']
    for list_name in security_lists_names:
        if hasattr(kursliste, list_name) and getattr(kursliste, list_name):
            all_securities.extend(getattr(kursliste, list_name))

    for security in all_securities:
        print(f'Processing for DB: id={getattr(security, "id", "N/A")}, type={getattr(security, "securityType", "N/A")}, name={getattr(security, "securityName", "N/A")}') # Added print
        kl_id = str(getattr(security, 'id', None))
        
        valor_num_attr = getattr(security, 'valorNumber', None)
        valor_num = str(valor_num_attr) if valor_num_attr is not None else None
        
        isin_val = getattr(security, 'isin', None)
        
        sec_type_attr = getattr(security, 'securityType', None)
        sec_type_id = sec_type_attr.value if sec_type_attr else None
        
        # Serialize the Pydantic model to JSON, then encode to bytes for BLOB
        json_str = security.model_dump_json(by_alias=True)
        blob_data = json_str.encode('utf-8')

        cursor.execute("""
            INSERT INTO securities (
                kl_id, valor_number, isin, tax_year, 
                security_type_identifier, security_object_blob
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            kl_id, valor_num, isin_val, tax_year, 
            sec_type_id, blob_data
        ))

    # Debug: Check exchange rates in the parsed Kursliste
    print(f"DEBUG: Checking exchange rates in parsed Kursliste:")
    print(f"DEBUG: hasattr(kursliste, 'exchangeRates'): {hasattr(kursliste, 'exchangeRates')}")
    if hasattr(kursliste, 'exchangeRates'):
        exchange_rates = kursliste.exchangeRates
        print(f"DEBUG: kursliste.exchangeRates is None: {exchange_rates is None}")
        print(f"DEBUG: type(kursliste.exchangeRates): {type(exchange_rates)}")
        if exchange_rates is not None:
            print(f"DEBUG: len(kursliste.exchangeRates): {len(exchange_rates)}")
            if exchange_rates:
                for i, rate in enumerate(exchange_rates):
                    print(f"DEBUG: Exchange rate {i}: {rate.currency} = {rate.value} on {rate.date}")
        else:
            print("DEBUG: kursliste.exchangeRates is None")

    print(f"DEBUG: hasattr(kursliste, 'exchangeRatesMonthly'): {hasattr(kursliste, 'exchangeRatesMonthly')}")
    if hasattr(kursliste, 'exchangeRatesMonthly'):
        monthly_rates = kursliste.exchangeRatesMonthly
        print(f"DEBUG: type(kursliste.exchangeRatesMonthly): {type(monthly_rates)}")
        if monthly_rates is not None:
            print(f"DEBUG: len(kursliste.exchangeRatesMonthly): {len(monthly_rates)}")
        else:
            print("DEBUG: kursliste.exchangeRatesMonthly is None")
        
    print(f"DEBUG: hasattr(kursliste, 'exchangeRatesYearEnd'): {hasattr(kursliste, 'exchangeRatesYearEnd')}")
    if hasattr(kursliste, 'exchangeRatesYearEnd'):
        yearend_rates = kursliste.exchangeRatesYearEnd
        print(f"DEBUG: type(kursliste.exchangeRatesYearEnd): {type(yearend_rates)}")
        if yearend_rates is not None:
            print(f"DEBUG: len(kursliste.exchangeRatesYearEnd): {len(yearend_rates)}")
        else:
            print("DEBUG: kursliste.exchangeRatesYearEnd is None")

    # Populate exchange_rates_daily
    if hasattr(kursliste, 'exchangeRates') and kursliste.exchangeRates:
        print(f"DEBUG: Processing {len(kursliste.exchangeRates)} daily exchange rates...")
        for ex_rate in kursliste.exchangeRates:
            currency_code = getattr(ex_rate, 'currency', None)
            rate_date = getattr(ex_rate, 'date', None)
            rate_date_iso = rate_date.isoformat() if rate_date else None
            rate_value = getattr(ex_rate, 'value', None)
            # Convert Decimal to string to preserve precision
            rate_value_str = str(rate_value) if rate_value is not None else None
            denomination = getattr(ex_rate, 'denomination', None)
            
            print(f"DEBUG: Inserting daily rate: {currency_code} = {rate_value_str} on {rate_date_iso}")
            cursor.execute("""
                INSERT INTO exchange_rates_daily (
                    currency_code, date, rate, denomination, tax_year, source_file
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (currency_code, rate_date_iso, rate_value_str, denomination, tax_year, source_file_name))
    else:
        print("DEBUG: No daily exchange rates to process")

    # Populate exchange_rates_monthly
    if hasattr(kursliste, 'exchangeRatesMonthly') and kursliste.exchangeRatesMonthly:
        print(f"DEBUG: Processing {len(kursliste.exchangeRatesMonthly)} monthly exchange rates...")
        for er_monthly in kursliste.exchangeRatesMonthly:
            currency_code = getattr(er_monthly, 'currency', None)
            year = getattr(er_monthly, 'year', None)
            month = getattr(er_monthly, 'month', None)
            rate_value = getattr(er_monthly, 'value', None)
            # Convert Decimal to string to preserve precision
            rate_value_str = str(rate_value) if rate_value is not None else None
            denomination = getattr(er_monthly, 'denomination', None)

            print(f"DEBUG: Inserting monthly rate: {currency_code} = {rate_value_str} for {year}-{month}")
            cursor.execute("""
                INSERT INTO exchange_rates_monthly (
                    currency_code, year, month, rate, denomination, tax_year, source_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (currency_code, year, month, rate_value_str, denomination, tax_year, source_file_name))
    else:
        print("DEBUG: No monthly exchange rates to process")

    # Populate exchange_rates_year_end
    if hasattr(kursliste, 'exchangeRatesYearEnd') and kursliste.exchangeRatesYearEnd:
        print(f"DEBUG: Processing {len(kursliste.exchangeRatesYearEnd)} year-end exchange rates...")
        for er_ye in kursliste.exchangeRatesYearEnd:
            currency_code = getattr(er_ye, 'currency', None)
            year = getattr(er_ye, 'year', None)
            rate_value = getattr(er_ye, 'value', None)
            rate_middle = getattr(er_ye, 'valueMiddle', None)
            # Convert Decimal values to strings to preserve precision
            rate_value_str = str(rate_value) if rate_value is not None else None
            rate_middle_str = str(rate_middle) if rate_middle is not None else None
            denomination = getattr(er_ye, 'denomination', None)

            print(f"DEBUG: Inserting year-end rate: {currency_code} = {rate_value_str} for {year}")
            cursor.execute("""
                INSERT INTO exchange_rates_year_end (
                    currency_code, year, rate, rate_middle, denomination, tax_year, source_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (currency_code, year, rate_value_str, rate_middle_str, denomination, tax_year, source_file_name))
    else:
        print("DEBUG: No year-end exchange rates to process")

    # Populate signs
    if hasattr(kursliste, 'signs') and kursliste.signs:
        print(f"DEBUG: Processing {len(kursliste.signs)} signs...")
        for sign_obj in kursliste.signs:
            kl_id = str(getattr(sign_obj, 'id', None))
            sign_value = getattr(sign_obj, 'sign', None) # This is the actual sign string like "KEST"

            json_str = sign_obj.model_dump_json(by_alias=True)
            blob_data = json_str.encode('utf-8')

            print(f"DEBUG: Inserting sign: ID={kl_id}, SignValue={sign_value}")
            cursor.execute("""
                INSERT INTO signs (
                    kl_id, sign_value, tax_year, source_file, sign_object_blob
                ) VALUES (?, ?, ?, ?, ?)
            """, (kl_id, sign_value, tax_year, source_file_name, blob_data))
    else:
        print("DEBUG: No signs to process")

    # Populate da1_rates
    if hasattr(kursliste, 'da1Rates') and kursliste.da1Rates:
        print(f"DEBUG: Processing {len(kursliste.da1Rates)} DA1 rates...")
        for da1_rate_obj in kursliste.da1Rates:
            kl_id = str(getattr(da1_rate_obj, 'id', None))
            country = getattr(da1_rate_obj, 'country', None)
            security_group_enum = getattr(da1_rate_obj, 'securityGroup', None)
            security_group = security_group_enum.value if security_group_enum else None

            json_str = da1_rate_obj.model_dump_json(by_alias=True)
            blob_data = json_str.encode('utf-8')

            print(f"DEBUG: Inserting DA1 rate: ID={kl_id}, Country={country}, SecGroup={security_group}")
            cursor.execute("""
                INSERT INTO da1_rates (
                    kl_id, country, security_group, tax_year, source_file, da1_rate_object_blob
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (kl_id, country, security_group, tax_year, source_file_name, blob_data))
    else:
        print("DEBUG: No DA1 rates to process")
            
    conn.commit()

def convert_kursliste_xml_to_sqlite(xml_file_path, db_file_path, denylist=None):
    """
    Core conversion function that can be called directly from Python code.
    
    Args:
        xml_file_path: Path to the Kursliste XML file
        db_file_path: Path to the SQLite database file to create
        denylist: Optional denylist for XML parsing (defaults to empty set for full parsing)
                 NOTE: XML element ordering matters! For correct parsing with empty denylist,
                 bonds must come before shares in the XML (which matches real kursliste files).
    
    Returns:
        True if successful, raises exception if failed
    """
    conn = None
    try:
        # Use empty denylist by default for full parsing, unless specified otherwise
        if denylist is None:
            denylist = set()
            
        # Parse the XML file
        kursliste = Kursliste.from_xml_file(xml_file_path, denylist=denylist)

        # Print parsed list lengths
        print(f'Parsed Shares: {len(kursliste.shares) if hasattr(kursliste, "shares") and kursliste.shares else 0}')
        print(f'Parsed Bonds: {len(kursliste.bonds) if hasattr(kursliste, "bonds") and kursliste.bonds else 0}')
        print(f'Parsed Funds: {len(kursliste.funds) if hasattr(kursliste, "funds") and kursliste.funds else 0}')
        print(f'Parsed Derivatives: {len(kursliste.derivatives) if hasattr(kursliste, "derivatives") and kursliste.derivatives else 0}')
        print(f'Parsed CoinBullions: {len(kursliste.coinBullions) if hasattr(kursliste, "coinBullions") and kursliste.coinBullions else 0}')
        print(f'Parsed CurrencyNotes: {len(kursliste.currencyNotes) if hasattr(kursliste, "currencyNotes") and kursliste.currencyNotes else 0}')
        print(f'Parsed LiborSwaps: {len(kursliste.liborSwaps) if hasattr(kursliste, "liborSwaps") and kursliste.liborSwaps else 0}')

        # Create/connect to the SQLite database
        conn = sqlite3.connect(db_file_path)

        # Create the database schema
        create_schema(conn)

        # Extract additional information for populating data
        tax_year = getattr(kursliste, 'year', None)
        source_file_name = os.path.basename(xml_file_path)

        # Populate the database
        populate_data(conn, kursliste, tax_year, source_file_name)

        print(f"Successfully converted {xml_file_path} to {db_file_path}")
        return True

    except FileNotFoundError:
        raise FileNotFoundError(f"XML file not found at {xml_file_path}")
    except ValidationError as ve:
        raise ValidationError(f"Pydantic validation error during XML parsing: {ve}")
    except Exception as e:
        raise Exception(f"Conversion failed: {e}")
    finally:
        if conn:
            conn.close()

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
