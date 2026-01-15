import sqlite3
import json # Added import
from typing import Optional, Dict as PyDict, List, Type
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from opensteuerauszug.model.kursliste import (
    Security, Share, Bond, Fund, Derivative, CoinBullion, CurrencyNote, LiborSwap,
    SecurityTypeESTV, Sign, Da1Rate, Da1RateType, SecurityGroupESTV
)

class KurslisteDBReader:
    """
    Reads security and exchange rate data from a Kursliste SQLite database.
    Securities are stored as JSON BLOBs and deserialized into Pydantic models.
    """
    _SECURITY_TYPE_MAP: PyDict[str, Type[Security]] = {  # Changed Dict to PyDict
        st.value: globals()[st.name.split('_')[-1].capitalize() if '.' not in st.name else st.name.split('.')[0].capitalize()]
        for st in SecurityTypeESTV if st.name.split('_')[-1].capitalize() in globals() or ('.' in st.name and st.name.split('.')[0].capitalize() in globals())
    }
    # Manually adjust specific mappings if capitalization/naming is tricky
    # For example, if SecurityTypeESTV.SHARE_COMMON -> Share, SecurityTypeESTV.BOND_BOND -> Bond
    # The comprehension above is a bit optimistic. Let's define it more explicitly for clarity and correctness.
    _SECURITY_TYPE_MAP: PyDict[str, Type[Security]] = { # Changed Dict to PyDict
        SecurityTypeESTV.SHARE_COMMON.value: Share,
        SecurityTypeESTV.SHARE_BEARERCERT.value: Share,
        SecurityTypeESTV.SHARE_BONUS.value: Share,
        SecurityTypeESTV.SHARE_COOP.value: Share,
        SecurityTypeESTV.SHARE_LIMITED.value: Share,
        SecurityTypeESTV.SHARE_LIMITEDOLD.value: Share,
        SecurityTypeESTV.SHARE_NOMINAL.value: Share,
        SecurityTypeESTV.SHARE_PARTCERT.value: Share,
        SecurityTypeESTV.SHARE_PREFERRED.value: Share,
        SecurityTypeESTV.SHARE_TRANSFERABLE.value: Share,
        SecurityTypeESTV.BOND_BOND.value: Bond,
        SecurityTypeESTV.BOND_CONVERTIBLE.value: Bond,
        SecurityTypeESTV.BOND_OPTION.value: Bond,
        SecurityTypeESTV.FUND_ACCUMULATION.value: Fund,
        SecurityTypeESTV.FUND_DISTRIBUTION.value: Fund,
        SecurityTypeESTV.FUND_REALESTATE.value: Fund,
        SecurityTypeESTV.DEVT_COMBINEDPRODUCT.value: Derivative,
        SecurityTypeESTV.DEVT_FUNDSIMILARASSET.value: Derivative,
        SecurityTypeESTV.DEVT_INDEXBASKET.value: Derivative,
        SecurityTypeESTV.COINBULL_COINGOLD.value: CoinBullion,
        SecurityTypeESTV.COINBULL_GOLD.value: CoinBullion,
        SecurityTypeESTV.COINBULL_PALLADIUM.value: CoinBullion,
        SecurityTypeESTV.COINBULL_PLATINUM.value: CoinBullion,
        SecurityTypeESTV.COINBULL_SILVER.value: CoinBullion,
        SecurityTypeESTV.CURRNOTE_CURRENCY.value: CurrencyNote,
        SecurityTypeESTV.CURRNOTE_CURRYEAR.value: CurrencyNote,
        SecurityTypeESTV.CURRNOTE_TOKEN.value: CurrencyNote,
        SecurityTypeESTV.LIBOSWAP_LIBOR.value: LiborSwap,
        SecurityTypeESTV.LIBOSWAP_SWAP.value: LiborSwap,
        SecurityTypeESTV.OPTION_CALL.value: Derivative, # Option could map to Derivative too
        SecurityTypeESTV.OPTION_PUT.value: Derivative,
        SecurityTypeESTV.OPTION_PHANTOM.value: Derivative,
        # Note: Some SecurityTypeESTV might not have a direct unique Pydantic model
        # or might be grouped under a more generic one like 'Derivative' or 'OtherSecurity'.
        # This map needs to be comprehensive for types stored.
    }


    def __init__(self, db_path: str):
        """
        Initializes the reader and connects to the SQLite database.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Access columns by name

    def _deserialize_object(self, blob_data: bytes, model_class: Type, object_type_name: str) -> Optional[object]:
        """
        Generic deserializer for objects stored as JSON BLOBs.
        """
        if not blob_data:
            return None
        if not model_class:
            print(f"Warning: No model class provided for deserialization of '{object_type_name}'.")
            return None
            
        try:
            json_string = blob_data.decode('utf-8')
            instance = model_class.model_validate_json(json_string)
            return instance
        except json.JSONDecodeError:
            print(f"Warning: Failed to decode JSON for type '{object_type_name}'. Data: {blob_data[:100]}...")
            return None
        except ValidationError as e:
            print(f"Warning: Pydantic validation error for type '{object_type_name}': {e}")
            return None
        except Exception as e:
            print(f"Warning: Unexpected error deserializing object type '{object_type_name}': {e}")
            return None

    def _deserialize_security(self, blob_data: bytes, type_identifier: str) -> Optional[Security]:
        """
        Deserializes a security object from BLOB data using its type identifier.
        """
        if not type_identifier: # blob_data check is done in _deserialize_object
             print(f"Warning: No type_identifier provided for security deserialization.")
             return None

        model_class = self._SECURITY_TYPE_MAP.get(type_identifier)
        if not model_class:
            print(f"Warning: Unknown security type identifier '{type_identifier}'. Cannot deserialize.")
            return None
        return self._deserialize_object(blob_data, model_class, f"Security (Type: {type_identifier})")

    def _execute_query_fetchone(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Helper to execute a query and fetch one result."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()
        except sqlite3.Error as e:
            print(f"SQLite error: {e} in query: {query} with params: {params}")
            return None

    def _execute_query_fetchall(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Helper to execute a query and fetch all results."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        except sqlite3.Error as e:
            print(f"SQLite error: {e} in query: {query} with params: {params}")
            return [] # Return empty list on error

    def _row_to_dict(self, row: Optional[sqlite3.Row]) -> Optional[PyDict]:
        """Converts an sqlite3.Row object to a dictionary."""
        if row:
            return dict(row) # This method is no longer used for securities.
        return None

    def find_security_by_valor(self, valor_number: int, tax_year: int) -> Optional[Security]:
        """
        Finds a single security by its VALOR number and tax year.
        Deserializes the security object from BLOB.
        """
        query = """
            SELECT security_object_blob, security_type_identifier 
            FROM securities
            WHERE valor_number = ? AND tax_year = ?
            LIMIT 1 
        """
        # valor_number in DB is TEXT, so ensure input valor_number is passed as string for query
        row = self._execute_query_fetchone(query, (str(valor_number), tax_year))
        if row:
            return self._deserialize_security(row["security_object_blob"], row["security_type_identifier"])
        return None

    def find_securities_by_valor(self, valor_number: int, tax_year: int) -> List[Security]:
        """
        Finds all securities matching the VALOR number and tax year.
        Deserializes security objects from BLOB.
        """
        query = """
            SELECT security_object_blob, security_type_identifier 
            FROM securities
            WHERE valor_number = ? AND tax_year = ?
        """
        rows = self._execute_query_fetchall(query, (str(valor_number), tax_year))
        securities = []
        for row in rows:
            sec = self._deserialize_security(row["security_object_blob"], row["security_type_identifier"])
            if sec:
                securities.append(sec)
        return securities

    def find_security_by_isin(self, isin: str, tax_year: int) -> Optional[Security]:
        """
        Finds a single security by its ISIN and tax year.
        Deserializes the security object from BLOB.
        """
        query = """
            SELECT security_object_blob, security_type_identifier
            FROM securities
            WHERE isin = ? AND tax_year = ?
            LIMIT 1
        """
        row = self._execute_query_fetchone(query, (isin, tax_year))
        if row:
            return self._deserialize_security(row["security_object_blob"], row["security_type_identifier"])
        return None

    def find_securities_by_isin(self, isin: str, tax_year: int) -> List[Security]:
        """
        Finds all securities matching the ISIN and tax year.
        Deserializes security objects from BLOB.
        """
        query = """
            SELECT security_object_blob, security_type_identifier
            FROM securities
            WHERE isin = ? AND tax_year = ?
        """
        rows = self._execute_query_fetchall(query, (isin, tax_year))
        securities = []
        for row in rows:
            sec = self._deserialize_security(row["security_object_blob"], row["security_type_identifier"])
            if sec:
                securities.append(sec)
        return securities

    def get_exchange_rate(self, currency_code: str, reference_date: date) -> Optional[Decimal]:
        """
        Retrieves the most relevant exchange rate for a given currency and date.
        Searches daily, then monthly, then year-end rates.

        Args:
            currency_code: The 3-letter currency code (e.g., "USD").
            reference_date: The date for which the exchange rate is needed.

        Returns:
            The exchange rate as a Decimal, or None if not found.
        """
        rate_value = None

        query_year_end = """
            SELECT rate, denomination FROM exchange_rates_year_end
            WHERE currency_code = ? AND year = ? AND tax_year = ?
            ORDER BY id DESC LIMIT 1
        """

        # Prefer year-end rate on December 31st
        if reference_date.month == 12 and reference_date.day == 31:
            row_year_end = self._execute_query_fetchone(
                query_year_end, (currency_code, reference_date.year, reference_date.year)
            )
            if row_year_end and row_year_end["rate"] is not None:
                try:
                    denomination = Decimal(1)
                    if row_year_end["denomination"]:
                        denomination = Decimal(str(row_year_end["denomination"]))
                    return Decimal(str(row_year_end["rate"])) / denomination
                except InvalidOperation:
                    print(
                        f"Warning: Could not convert year_end rate '{row_year_end['rate']}' to Decimal."
                    )

        # 1. Try daily rates
        date_iso = reference_date.isoformat()
        query_daily = """
            SELECT rate, denomination FROM exchange_rates_daily
            WHERE currency_code = ? AND date = ? AND tax_year = ?
            ORDER BY id DESC LIMIT 1
        """
        # Assuming tax_year in exchange_rates_daily refers to the year of the Kursliste publication
        # For daily rates, matching the reference_date's year seems most logical.
        row_daily = self._execute_query_fetchone(
            query_daily, (currency_code, date_iso, reference_date.year)
        )
        if row_daily and row_daily["rate"] is not None:
            try:
                denomination = Decimal(1)
                if row_daily["denomination"]:
                    denomination = Decimal(str(row_daily["denomination"]))
                return Decimal(str(row_daily["rate"])) / denomination
            except InvalidOperation:
                print(
                    f"Warning: Could not convert daily rate '{row_daily['rate']}' to Decimal."
                )

        # 2. Try monthly rates if daily not found or rate is None
        month_str = reference_date.strftime("%m")  # Format month as "01", "02", etc.
        query_monthly = """
            SELECT rate, denomination FROM exchange_rates_monthly
            WHERE currency_code = ? AND year = ? AND month = ? AND tax_year = ?
            ORDER BY id DESC LIMIT 1
        """
        # tax_year in exchange_rates_monthly should also match the reference_date's year
        row_monthly = self._execute_query_fetchone(
            query_monthly, (currency_code, reference_date.year, month_str, reference_date.year)
        )
        if row_monthly and row_monthly["rate"] is not None:
            try:
                denomination = Decimal(1)
                if row_monthly["denomination"]:
                    denomination = Decimal(str(row_monthly["denomination"]))
                return Decimal(str(row_monthly["rate"])) / denomination
            except InvalidOperation:
                print(
                    f"Warning: Could not convert monthly rate '{row_monthly['rate']}' to Decimal."
                )

        # 3. Try year-end rates if monthly not found or rate is None
        row_year_end = self._execute_query_fetchone(
            query_year_end, (currency_code, reference_date.year, reference_date.year)
        )
        if row_year_end and row_year_end["rate"] is not None:
            try:
                denomination = Decimal(1)
                if row_year_end["denomination"]:
                    denomination = Decimal(str(row_year_end["denomination"]))
                return Decimal(str(row_year_end["rate"])) / denomination
            except InvalidOperation:
                print(
                    f"Warning: Could not convert year_end rate '{row_year_end['rate']}' to Decimal."
                )

        return None  # If no rate found or convertible rate is None

    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_sign_by_value(self, sign_value: str, tax_year: int) -> Optional[Sign]:
        """
        Retrieves a Sign object by its sign_value and tax_year.
        Deserializes the Sign object from BLOB.
        """
        query = """
            SELECT sign_object_blob
            FROM signs
            WHERE sign_value = ? AND tax_year = ?
            LIMIT 1
        """
        row = self._execute_query_fetchone(query, (sign_value, tax_year))
        if row and row["sign_object_blob"]:
            # Type casting for clarity, _deserialize_object returns Optional[object]
            return self._deserialize_object(row["sign_object_blob"], Sign, "Sign") # type: ignore
        return None

    def get_da1_rate(self, country: str, security_group: SecurityGroupESTV, tax_year: int,
                     security_type: Optional[SecurityTypeESTV] = None,
                     da1_rate_type: Optional[Da1RateType] = None,
                     reference_date: Optional[date] = None) -> Optional[List[Da1Rate]]:
        """
        Retrieves a Da1Rate object based on criteria.
        Deserializes the Da1Rate object from BLOB.
        The reference_date is used to filter by validFrom and validTo if provided.
        Note: This currently fetches the first matching record. More complex selection logic
              (e.g. "most specific" or "latest valid") might be needed depending on business rules.
        """
        params = [country, security_group.value, tax_year]
        conditions = ["country = ?", "security_group = ?", "tax_year = ?"]

        # For now, let's fetch all DA1 rates for the main criteria and filter by date/type in Python
        query = f"""
            SELECT da1_rate_object_blob
            FROM da1_rates
            WHERE {" AND ".join(conditions)}
        """

        rows = self._execute_query_fetchall(query, tuple(params))

        candidates: List[Da1Rate] = []
        for row in rows:
            if row["da1_rate_object_blob"]:
                deserialized_obj = self._deserialize_object(row["da1_rate_object_blob"], Da1Rate, "Da1Rate")
                if deserialized_obj:
                    candidates.append(deserialized_obj) # type: ignore

        if not candidates:
            return None

        # Python-side filtering
        filtered_candidates = candidates
        if security_type:
            filtered_candidates = [
                r for r in filtered_candidates if r.securityType == security_type
            ]

        if da1_rate_type:
            filtered_candidates = [
                r for r in filtered_candidates if r.da1RateType == da1_rate_type
            ]

        if reference_date:
            final_candidates = []
            for rate in filtered_candidates:
                is_valid = True
                if rate.validFrom and rate.validFrom > reference_date:
                    is_valid = False
                if rate.validTo and rate.validTo < reference_date:
                    is_valid = False
                if is_valid:
                    final_candidates.append(rate)
            filtered_candidates = final_candidates

        if not filtered_candidates:
            return None

        return filtered_candidates


if __name__ == '__main__':
    # Example Usage (requires a dummy database to be set up)
    # This part is for illustrative purposes and won't be run by the agent.
    
    # Create a dummy DB for testing
    # conn = sqlite3.connect(':memory:')
    # cursor = conn.cursor()

    # # Create schemas (simplified from convert_kursliste_to_sqlite.py)
    # cursor.execute("""
    #     CREATE TABLE securities (
    #         internal_db_id INTEGER PRIMARY KEY AUTOINCREMENT, kl_id TEXT, name TEXT, isin TEXT,
    #         valor_id TEXT, type TEXT, security_group TEXT, currency TEXT,
    #         nominal_value REAL, country TEXT, tax_year INTEGER, source_file TEXT )""")
    # cursor.execute("""
    #     CREATE TABLE exchange_rates_daily (
    #         id INTEGER PRIMARY KEY AUTOINCREMENT, currency_code TEXT, date TEXT, rate REAL,
    #         denomination INTEGER, tax_year INTEGER, source_file TEXT )""")
    # cursor.execute("""
    #     CREATE TABLE exchange_rates_monthly (
    #         id INTEGER PRIMARY KEY AUTOINCREMENT, currency_code TEXT, year INTEGER, month TEXT,
    #         rate REAL, denomination INTEGER, tax_year INTEGER, source_file TEXT )""")
    # cursor.execute("""
    #     CREATE TABLE exchange_rates_year_end (
    #         id INTEGER PRIMARY KEY AUTOINCREMENT, currency_code TEXT, year INTEGER, rate REAL,
    #         rate_middle REAL, denomination INTEGER, tax_year INTEGER, source_file TEXT )""")

    # # Insert sample data
    # cursor.execute("INSERT INTO securities (valor_id, name, tax_year, isin) VALUES (?, ?, ?, ?)", ('12345', 'Test Security Valor', 2023, 'CH123'))
    # cursor.execute("INSERT INTO securities (isin, name, tax_year) VALUES (?, ?, ?)", ('DE678', 'Test Security ISIN', 2023))
    # cursor.execute("INSERT INTO exchange_rates_daily (currency_code, date, rate, tax_year) VALUES (?, ?, ?, ?)", ('USD', '2023-07-15', '0.89', 2023))
    # cursor.execute("INSERT INTO exchange_rates_monthly (currency_code, year, month, rate, tax_year) VALUES (?, ?, ?, ?, ?)", ('EUR', 2023, '08', '0.95', 2023))
    # cursor.execute("INSERT INTO exchange_rates_year_end (currency_code, year, rate, tax_year) VALUES (?, ?, ?, ?)", ('GBP', 2023, '1.12', 2023))
    # conn.commit()
    # conn.close()

    # # Now, use the reader (assuming dummy.db was created and populated)
    # # For real use, replace ':memory:' with 'path/to/your/kursliste.sqlite'
    
    # # Create a dummy db file for the example
    # DUMMY_DB_PATH = "dummy_kursliste_plural.sqlite" # Changed name for testing
    # conn_file = sqlite3.connect(DUMMY_DB_PATH)
    # cursor_file = conn_file.cursor()
    # cursor_file.execute("DROP TABLE IF EXISTS securities") # Ensure clean state
    # cursor_file.execute("DROP TABLE IF EXISTS exchange_rates_daily")
    # cursor_file.execute("DROP TABLE IF EXISTS exchange_rates_monthly")
    # cursor_file.execute("DROP TABLE IF EXISTS exchange_rates_year_end")
    # cursor_file.execute(""" CREATE TABLE securities ( internal_db_id INTEGER PRIMARY KEY AUTOINCREMENT, kl_id TEXT, name TEXT, isin TEXT, valor_id TEXT, type TEXT, security_group TEXT, currency TEXT, nominal_value REAL, country TEXT, tax_year INTEGER, source_file TEXT )""")
    # cursor_file.execute(""" CREATE TABLE exchange_rates_daily ( id INTEGER PRIMARY KEY AUTOINCREMENT, currency_code TEXT, date TEXT, rate REAL, denomination INTEGER, tax_year INTEGER, source_file TEXT )""")
    # cursor_file.execute(""" CREATE TABLE exchange_rates_monthly ( id INTEGER PRIMARY KEY AUTOINCREMENT, currency_code TEXT, year INTEGER, month TEXT, rate REAL, denomination INTEGER, tax_year INTEGER, source_file TEXT )""")
    # cursor_file.execute(""" CREATE TABLE exchange_rates_year_end ( id INTEGER PRIMARY KEY AUTOINCREMENT, currency_code TEXT, year INTEGER, rate REAL, rate_middle REAL, denomination INTEGER, tax_year INTEGER, source_file TEXT )""")
    # cursor_file.execute("INSERT INTO securities (valor_id, name, tax_year, isin, kl_id, type, security_group, currency, nominal_value, country, source_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ('12345', 'Test Security Valor 1', 2023, 'CH123', 'sec1', 'Share', 'SHARE', 'CHF', 10.0, 'CH', 'file1.xml'))
    # cursor_file.execute("INSERT INTO securities (valor_id, name, tax_year, isin, kl_id, type, security_group, currency, nominal_value, country, source_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ('12345', 'Test Security Valor 2', 2023, 'CH123', 'sec2', 'Bond', 'BOND', 'CHF', 100.0, 'CH', 'file1.xml')) # Same valor_id
    # cursor_file.execute("INSERT INTO securities (isin, name, tax_year, valor_id) VALUES (?, ?, ?, ?)", ('DE678', 'Test Security ISIN 1', 2023, '67890'))
    # cursor_file.execute("INSERT INTO securities (isin, name, tax_year, valor_id) VALUES (?, ?, ?, ?)", ('DE678', 'Test Security ISIN 2', 2023, '67891')) # Same ISIN
    # cursor_file.execute("INSERT INTO exchange_rates_daily (currency_code, date, rate, tax_year) VALUES (?, ?, ?, ?)", ('USD', '2023-07-15', '0.89', 2023))
    # cursor_file.execute("INSERT INTO exchange_rates_monthly (currency_code, year, month, rate, tax_year) VALUES (?, ?, ?, ?, ?)", ('EUR', 2023, '08', '0.95', 2023))
    # cursor_file.execute("INSERT INTO exchange_rates_year_end (currency_code, year, rate, tax_year) VALUES (?, ?, ?, ?)", ('CAD', 2023, '0.70', 2023)) # Fallback if daily/monthly for CAD not found
    # cursor_file.execute("INSERT INTO exchange_rates_daily (currency_code, date, rate, tax_year) VALUES (?, ?, ?, ?)", ('JPY', '2023-12-25', None, 2023)) # Test None rate

    # conn_file.commit()
    # conn_file.close()

    # print(f"Using dummy database: {DUMMY_DB_PATH}")
    # with KurslisteDBReader(DUMMY_DB_PATH) as reader:
    #     print("\n--- Securities (Single) ---")
    #     security_v_single = reader.find_security_by_valor(12345, 2023) # Old method
    #     print(f"Found by Valor (single - 12345, 2023): {security_v_single}")
        
    #     security_i_single = reader.find_security_by_isin("DE678", 2023) # Old method
    #     print(f"Found by ISIN (single - DE678, 2023): {security_i_single}")

    #     print("\n--- Securities (Multiple) ---")
    #     securities_v_list = reader.find_securities_by_valor(12345, 2023)
    #     print(f"Found by Valor (list - 12345, 2023): Count={len(securities_v_list)}")
    #     for sec in securities_v_list:
    #         print(f"  - {sec}")
            
    #     securities_i_list = reader.find_securities_by_isin("DE678", 2023)
    #     print(f"Found by ISIN (list - DE678, 2023): Count={len(securities_i_list)}")
    #     for sec in securities_i_list:
    #         print(f"  - {sec}")

    #     securities_v_none_list = reader.find_securities_by_valor(88888, 2023)
    #     print(f"Found by Valor (list - 88888, 2023) - Expected Empty List: {securities_v_none_list}")


    #     print("\n--- Exchange Rates ---") # Unchanged from previous example
    #     rate_usd = reader.get_exchange_rate("USD", date(2023, 7, 15)) 
    #     print(f"Rate USD on 2023-07-15 (Daily): {rate_usd} (Type: {type(rate_usd)})")

    #     rate_eur = reader.get_exchange_rate("EUR", date(2023, 8, 10)) # Should use monthly
    #     print(f"Rate EUR on 2023-08-10 (Monthly): {rate_eur} (Type: {type(rate_eur)})")

    #     rate_cad = reader.get_exchange_rate("CAD", date(2023, 5, 5)) # Should use year-end
    #     print(f"Rate CAD on 2023-05-05 (Year-End): {rate_cad} (Type: {type(rate_cad)})")
        
    #     rate_gbp = reader.get_exchange_rate("GBP", date(2023, 1, 1)) # No daily/monthly, should use year-end if exists
    #     # To test this, we'd need GBP in exchange_rates_year_end; currently it's CAD.
    #     # Let's assume it would pick from there if GBP was present.
    #     # For now, it will be None if no GBP entry for 2023.
    #     # Corrected: Added CAD to year_end to test this path
    #     print(f"Rate GBP on 2023-01-01 (Expected None or Year-End if GBP existed): {reader.get_exchange_rate('GBP', date(2023,1,1))}")

    #     rate_jpy_none = reader.get_exchange_rate("JPY", date(2023, 12, 25)) # Daily rate is None
    #     print(f"Rate JPY on 2023-12-25 (Rate is None in DB): {rate_jpy_none}")
        
    #     rate_nonexistent = reader.get_exchange_rate("XYZ", date(2023, 1, 1))
    #     print(f"Rate XYZ on 2023-01-01 (Non-existent): {rate_nonexistent}")
    
    # import os
    # os.remove(DUMMY_DB_PATH) # Clean up dummy db
    pass # End of example
