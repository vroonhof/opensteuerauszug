import argparse
import argparse
import sqlite3
import json # Added import
from pydantic import ValidationError # Added import
from opensteuerauszug.model.kursliste import Kursliste

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

    # Exchange Rates Daily Table - Unchanged
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exchange_rates_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_code TEXT, -- Foreign currency code (e.g., USD)
            date TEXT, -- Date of the exchange rate
            rate REAL,
            denomination INTEGER,
            tax_year INTEGER,
            source_file TEXT
        )
    """)

    # Exchange Rates Monthly Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exchange_rates_monthly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_code TEXT,
            year INTEGER,
            month TEXT, -- e.g., "01", "12"
            rate REAL,
            denomination INTEGER,
            tax_year INTEGER,
            source_file TEXT
        )
    """)

    # Exchange Rates Year End Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exchange_rates_year_end (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_code TEXT,
            year INTEGER,
            rate REAL,
            rate_middle REAL, -- For specific year-end rates that have a middle value
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
        json_str = security.model_dump_json()
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

    # Populate exchange_rates_daily
    if hasattr(kursliste, 'exchangeRates') and kursliste.exchangeRates:
        for ex_rate in kursliste.exchangeRates:
            currency_code = getattr(ex_rate, 'currency', None)
            rate_date = getattr(ex_rate, 'date', None)
            rate_date_iso = rate_date.isoformat() if rate_date else None
            rate_value = getattr(ex_rate, 'value', None)
            denomination = getattr(ex_rate, 'denomination', None)
            
            cursor.execute("""
                INSERT INTO exchange_rates_daily (
                    currency_code, date, rate, denomination, tax_year, source_file
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (currency_code, rate_date_iso, rate_value, denomination, tax_year, source_file_name))

    # Populate exchange_rates_monthly
    if hasattr(kursliste, 'exchangeRatesMonthly') and kursliste.exchangeRatesMonthly:
        for er_monthly in kursliste.exchangeRatesMonthly:
            currency_code = getattr(er_monthly, 'currency', None)
            year = getattr(er_monthly, 'year', None)
            month = getattr(er_monthly, 'month', None)
            rate_value = getattr(er_monthly, 'value', None)
            denomination = getattr(er_monthly, 'denomination', None)

            cursor.execute("""
                INSERT INTO exchange_rates_monthly (
                    currency_code, year, month, rate, denomination, tax_year, source_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (currency_code, year, month, rate_value, denomination, tax_year, source_file_name))

    # Populate exchange_rates_year_end
    if hasattr(kursliste, 'exchangeRatesYearEnd') and kursliste.exchangeRatesYearEnd:
        for er_ye in kursliste.exchangeRatesYearEnd:
            currency_code = getattr(er_ye, 'currency', None)
            year = getattr(er_ye, 'year', None)
            rate_value = getattr(er_ye, 'value', None)
            rate_middle = getattr(er_ye, 'valueMiddle', None)
            denomination = getattr(er_ye, 'denomination', None)

            cursor.execute("""
                INSERT INTO exchange_rates_year_end (
                    currency_code, year, rate, rate_middle, denomination, tax_year, source_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (currency_code, year, rate_value, rate_middle, denomination, tax_year, source_file_name))
            
    conn.commit()

import os # Added for os.path.basename

def main():
    parser = argparse.ArgumentParser(description="Convert Kursliste XML to SQLite database.")
    parser.add_argument("xml_file", help="Path to the Kursliste XML file.")
    parser.add_argument("db_file", help="Path to the SQLite database file.")
    args = parser.parse_args()

    try:
        # Parse the XML file
        # Consider which denylist to use, or if any, for Kursliste.from_xml_file
        # For now, using default denylist which might exclude some needed data,
        # or pass denylist=set() to parse all.
        # For this script, we need 'shares', 'bonds', 'funds', etc. and 'exchangeRates*'
        # The default denylist in Kursliste model seems to exclude most of these.
        # So, we should pass an empty set or a specific allowlist.
        # Let's assume for now the default is okay or has been handled upstream.
        # A better approach for this script might be to parse everything:
        kursliste = Kursliste.from_xml_file(args.xml_file, denylist=set())

        # Print parsed list lengths
        print(f'Parsed Shares: {len(kursliste.shares) if hasattr(kursliste, "shares") and kursliste.shares else 0}')
        print(f'Parsed Bonds: {len(kursliste.bonds) if hasattr(kursliste, "bonds") and kursliste.bonds else 0}')
        print(f'Parsed Funds: {len(kursliste.funds) if hasattr(kursliste, "funds") and kursliste.funds else 0}')
        print(f'Parsed Derivatives: {len(kursliste.derivatives) if hasattr(kursliste, "derivatives") and kursliste.derivatives else 0}')
        print(f'Parsed CoinBullions: {len(kursliste.coinBullions) if hasattr(kursliste, "coinBullions") and kursliste.coinBullions else 0}')
        print(f'Parsed CurrencyNotes: {len(kursliste.currencyNotes) if hasattr(kursliste, "currencyNotes") and kursliste.currencyNotes else 0}')
        print(f'Parsed LiborSwaps: {len(kursliste.liborSwaps) if hasattr(kursliste, "liborSwaps") and kursliste.liborSwaps else 0}')

        # Create/connect to the SQLite database
        conn = sqlite3.connect(args.db_file)

        # Create the database schema
        create_schema(conn)

        # Extract additional information for populating data
        tax_year = getattr(kursliste, 'year', None)
        source_file_name = os.path.basename(args.xml_file)

        # Populate the database
        populate_data(conn, kursliste, tax_year, source_file_name)

        print(f"Successfully converted {args.xml_file} to {args.db_file}")

    except FileNotFoundError:
        print(f"Error: XML file not found at {args.xml_file}")
    except ValidationError as ve: # Added specific exception handler
        print(f"Pydantic validation error during XML parsing: {ve}")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    main()
