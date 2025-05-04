import re
import decimal
from datetime import datetime
import os
import argparse # Added for command-line arguments

# Attempt to import PyPDF2 and provide a helpful error message if not installed
import PyPDF2

# Use Decimal for precise financial calculations
decimal.getcontext().prec = 20 # Set precision for Decimal

# Define regex patterns for various data points
CLOSING_PRICE_PATTERN = r"Closing Price on (\d{2}/\d{2}/\d{4}) *: (\$[\d,.]+)"
ACCOUNT_SUMMARY_PATTERN = r"Account Summary: \w+"
PERIOD_PATTERN =  r"For Period: (\d{2}/\d{2}/\d{4}) - (\d{2}/\d{2}/\d{4})"
STOCK_HEADER_PATTERN = r'Opening\s*Closing\s*Closing\s+Share Price\s*Closing\s+Value\s+'

class StatementExtractor:
    """
    Reads a PDF statement file, extracts data assumed to be from a
    Charles Schwab account statement similar to the provided example.
    Requires the PyPDF2 library to be installed (`pip install pypdf2`).
    """

    def __init__(self, pdf_file_path):
        """
        Initializes the extractor by reading the text content from the PDF file.

        Args:
            pdf_file_path (str): The path to the PDF statement file.

        Raises:
            FileNotFoundError: If the pdf_file_path does not exist.
            ImportError: If PyPDF2 is not installed.
            Exception: For errors during PDF processing.
        """
        if not os.path.exists(pdf_file_path):
             # This error will be caught by the try...except in main()
             raise FileNotFoundError(f"Error: The file '{pdf_file_path}' was not found.")

        self.pdf_path = pdf_file_path
        self.text_content = ""
        self.pdf_author = None # To store the author of the PDF
        self.extracted_data = None # To store extracted data

        try:
            with open(self.pdf_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                self.pdf_author = reader.metadata.author if reader.metadata.author else "Unknown"
                num_pages = len(reader.pages)
                print(f"Reading {num_pages} pages from '{self.pdf_path}'...")
                for i, page in enumerate(reader.pages):
                    try:
                        page_text = page.extract_text()
                        if page_text: # Ensure text was extracted
                             self.text_content += page_text
                        else:
                             print(f"Warning: No text extracted from page {i+1}.")
                    except Exception as page_err:
                        # Catch potential issues during text extraction for a specific page
                        print(f"Warning: Could not extract text from page {i+1}. Error: {page_err}")
                    # Add a separator between pages for potentially better regex matching
                    if i < num_pages - 1:
                        self.text_content += "\n--- PAGE BREAK ---\n"
            print("PDF reading complete.")
            if not self.text_content.strip():
                 print("Warning: No text content could be extracted from the PDF.")

        except PyPDF2.errors.PdfReadError as pdf_err:
             raise Exception(f"Error reading PDF file '{self.pdf_path}'. It might be corrupted or password-protected. Details: {pdf_err}")
        except Exception as e:
            # Catch other potential file reading or PyPDF2 errors
            raise Exception(f"Error processing PDF file '{self.pdf_path}': {e}")


    def _clean_numeric_string(self, num_str):
        """Removes currency symbols, commas, newline chars and converts to Decimal."""
        if not num_str:
            return None
        # Remove $, ,, \n, and leading/trailing whitespace
        cleaned = re.sub(r'[$,\n"]', '', num_str).strip()
        try:
            return decimal.Decimal(cleaned)
        except decimal.InvalidOperation:
            print(f"Warning: Could not convert '{cleaned}' (original: '{num_str}') to Decimal.")
            return None

    def is_statement(self):
        """
        Detects if the extracted text content resembles the target statement format.

        Returns:
            bool: True if the content matches expected patterns, False otherwise.
        """
        if not re.match(r".*SCHWAB.*", self.pdf_author, re.IGNORECASE):
            print(f"Warning: Author {self.pdf_author} does not contain SCHWAB, skipping format check.")
            return False
        
        if not self.text_content.strip():
             print("Warning: Cannot check format, no text content available.")
             return False

        # Check for key identifiers and structural elements
        patterns = [
            r"Account Statement",
            ACCOUNT_SUMMARY_PATTERN
        ]

        # Check if all patterns are found in the text
        all_found = all(re.search(pattern, self.text_content, re.IGNORECASE | re.MULTILINE) for pattern in patterns)
        if not all_found:
            if re.search(r"Investments Purchases", self.text_content, re.IGNORECASE | re.MULTILINE):
                print("NOTE: Found likely main brokerage stagement. Ignoring.")
            else:
                print("Warning: Unknown Schwab document.")
            #print("Debug: Some statement identification patterns not found.")
            # Optionally print which patterns failed for debugging
            #for i, pattern in enumerate(patterns):
            #     if not re.search(pattern, self.text_content, re.IGNORECASE | re.MULTILINE):
            #         print(f"  - Pattern failed: {pattern}")
        return all_found


    def extract_data(self):
        """
        Extracts statement end date, symbol, closing shares, closing price,
        and closing value from the text content read from the PDF.

        Returns:
            dict: A dictionary containing the extracted data, or None if extraction fails
                  or if the text doesn't match the statement format.
                  Keys: 'end_date', 'symbol', 'closing_shares', 'closing_price', 'closing_value'
        """
        if not self.is_statement():
            print("Warning: Text does not appear to be a valid statement or no text was extracted.")
            return None

        data = {}

        # 1. Extract Statement End Date (No change here)
        end_date = None
        match_date = re.search(CLOSING_PRICE_PATTERN, self.text_content)
        if match_date:
            try:
                end_date = datetime.strptime(match_date.group(1), '%m/%d/%Y').date()
            except ValueError:
                print("Warning: Could not parse end date from 'Closing Price on' line.")

        match_period = re.search(PERIOD_PATTERN, self.text_content)
        if match_period:
            try:
                data['start_date'] = datetime.strptime(match_period.group(1), '%m/%d/%Y').date()
                period_end = datetime.strptime(match_period.group(2), '%m/%d/%Y').date()
            except ValueError:
                print("Warning: Could not parse end date from 'For Period' line.")

        if not end_date and period_end:
            end_date = period_end
        data['end_date'] = end_date
        if not end_date:
            print("Warning: Could not find statement end date.")

        # 2. Extract Symbol
        match_symbol = re.search(r"Account Summary: (\w+)", self.text_content, re.IGNORECASE)
        if match_symbol:
            data['symbol'] = match_symbol.group(1).upper() # Capture and uppercase the symbol
            print(f"Debug: Found symbol: {data['symbol']}")
        else:
            data['symbol'] = None
            print("Warning: Could not find symbol using 'Account Summary:' pattern.")
            # Optional: Add fallback attempt using the "Closing Price on SYMBOL" line if needed
            match_symbol_fallback = re.search(r"(\w+) Closing Price on", self.text_content, re.IGNORECASE)
            if match_symbol_fallback:
                 data['symbol'] = match_symbol_fallback.group(1).upper()
                 print(f"Debug: Found symbol via fallback: {data['symbol']}")
            else:
                 print("Warning: Could not find symbol via fallback pattern either.")


        # 3. Extract Stock Summary Data (Closing Shares, Price, Value) - (No change here)
        stock_summary_pattern = re.compile(
            r'Stock Summary:.*?'
            r'Opening\s*Closing\s*Closing\s*Share Price\s*Closing\s+Value\s*'
            r'([\d,.]+)\s+'       # Group 1: Opening Shares
            r'([\d,.]+)\s+'       # Group 2: Closing Shares
            r'(\$[\d,.]+)\s+'     # Group 3: Closing Share Price
            r'(\$[\d,.]+)\s',      # Group 4: Closing Value
            re.DOTALL | re.IGNORECASE
        )
        match_summary = stock_summary_pattern.search(self.text_content)
        if match_summary:
            data['opening_shares'] = self._clean_numeric_string(match_summary.group(1))
            data['closing_shares'] = self._clean_numeric_string(match_summary.group(2))
            data['closing_price'] = self._clean_numeric_string(match_summary.group(3))
            data['closing_value'] = self._clean_numeric_string(match_summary.group(4))
            print("Debug: Successfully matched and extracted from stock summary row.")
        else:
            print("Warning: Could not find or parse the Stock Summary data row using regex.")
            data['closing_shares'] = None
            data['closing_price'] = None
            data['closing_value'] = None

        # 3. Extract Cacsh Summary Data (Closing Shares, Price, Value) - (No change here)
        cash_summary_pattern = re.compile(
            r'Cash Summary:\s*'
            r'(\$[\d,.]+)\s+'       # Group 1: Opening Cash
            r'(\$[\d,.]+)\s+'       # Group 2: Closing Cash
            r'(\$[\d,.]+)\s',      # Group 3: Closing Value
            re.DOTALL | re.IGNORECASE
        )
        match_cash = cash_summary_pattern.search(self.text_content)
        if match_cash:
            data['opening_cash'] = self._clean_numeric_string(match_cash.group(1))
            data['closing_cash'] = self._clean_numeric_string(match_cash.group(2))
            print("Debug: Successfully matched and extracted from cash summary row.")
        
        # Fallback for Closing Price if not found in summary OR if summary parsing failed (No change here)
        if data.get('closing_price') is None:
             print("Debug: Attempting fallback for closing price.")
             match_price_line = re.search(r"Closing Price on \d{2}/\d{2}/\d{4} +: (\$[\d,.]+)", self.text_content)
             if match_price_line:
                 data['closing_price'] = self._clean_numeric_string(match_price_line.group(1))
                 print(f"Debug: Found closing price via fallback: {data['closing_price']}")
             else:
                 print("Warning: Could not find closing price via fallback regex either.")


        # 4. Check if all essential data points were extracted (Now includes symbol)
        required_keys = ['end_date', 'symbol', 'closing_shares', 'closing_price', 'closing_value']
        missing_keys = [key for key in required_keys if data.get(key) is None]

        if missing_keys:
             print(f"Warning: Failed to extract one or more required data points: {', '.join(missing_keys)}.")
             # Decide if you want to return None or partial data
             # For now, let's return the partial data and let verify_calculation handle missing numerics
             # return None

        self.extracted_data = data
        return data

    def verify_calculation(self, tolerance=decimal.Decimal('0.01')):
        """
        Verifies if Closing Shares * Closing Price approximately equals Closing Value.

        Args:
            tolerance (decimal.Decimal): The acceptable difference for the verification.
                                         Defaults to 0.01 (1 cent).

        Returns:
            bool: True if the calculation is within the tolerance, False otherwise.
                  Returns False if data hasn't been extracted successfully or is invalid.
        """
        if not self.extracted_data:
            print("Error: Data not extracted. Cannot perform verification.")
            return False

        shares = self.extracted_data.get('closing_shares')
        price = self.extracted_data.get('closing_price')
        value = self.extracted_data.get('closing_value')

        # Check specifically for the numeric values needed for calculation
        if None in [shares, price, value]:
            print("Error: Missing numeric data for verification (Shares, Price, or Value were not extracted or invalid).")
            return False

        try:
            # Ensure values are Decimal before calculation
            if not isinstance(shares, decimal.Decimal) or \
               not isinstance(price, decimal.Decimal) or \
               not isinstance(value, decimal.Decimal):
                print("Error: One or more values (shares, price, value) are not valid Decimals for calculation.")
                return False

            calculated_value = shares * price
            difference = abs(calculated_value - value)

            print(f"Verification: Shares ({shares}) * Price ({price}) = Calculated Value ({calculated_value})")
            print(f"Statement Value: {value}")
            print(f"Difference: {difference}")

            is_within_tolerance = difference <= tolerance
            if not is_within_tolerance:
                 print(f"Warning: Calculated value differs from statement value by more than the tolerance ({tolerance}).")
            return is_within_tolerance

        except (TypeError, decimal.InvalidOperation) as e:
             print(f"Error: Could not perform verification due to invalid numeric data or operation error: {e}")
             return False


# --- Sample Main Function ---
def main():
    """
    Main execution function. Parses command-line arguments for the PDF file,
    creates a StatementExtractor instance, extracts data, and verifies calculations.
    Requires PyPDF2: pip install pypdf2
    """
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="Extracts and verifies data from a Charles Schwab PDF account statement.",
        epilog="Example: python your_script_name.py \"Account Statement_2024-12-31  GOOG.PDF\""
    )
    parser.add_argument(
        "pdf_file", # Argument name
        type=str,
        help="Path to the PDF statement file to process."
    )
    args = parser.parse_args()
    pdf_file_to_process = args.pdf_file
    # ---------------------

    # Check if PyPDF2 is available before proceeding
    if PyPDF2 is None:
        # Error message already printed at import time
        return # Exit script

    print(f"--- Analyzing Statement: {pdf_file_to_process} ---")
    try:
        # Instantiation will raise FileNotFoundError if file doesn't exist
        extractor = StatementExtractor(pdf_file_to_process)

        # Extract the data (this also implicitly checks the format via is_statement())
        print("\n--- Extracting Data ---")
        data = extractor.extract_data() # data is the dictionary returned

        print(extractor.text_content) # Print the extracted text content for debugging
        
        print("\n--- Extracted Data ---")
        # Check if extraction returned a dictionary and if the instance has stored data
        if data and extractor.extracted_data:
            print("\nExtracted Data:")
            # Define the desired order for printing
            print_order = ['end_date', 'start_date', 'symbol', 'opening_shares', 'closing_shares', 'closing_price', 'closing_value',
                           'opening_cash', 'closing_cash']
            for key in print_order:
                 value = extractor.extracted_data.get(key) # Use .get() for safety
                 # Handle potential None values gracefully for printing
                 print_val = value if value is not None else "Not Found"
                 print(f"- {key.replace('_', ' ').title()}: {print_val}")

            # Verify the calculation (only if numeric data seems present)
            if all(extractor.extracted_data.get(k) is not None for k in ['closing_shares', 'closing_price', 'closing_value']):
                print("\n--- Verifying Calculation ---")
                is_valid = extractor.verify_calculation()
                if is_valid:
                    print("\nVerification Result: SUCCESS - Calculated value matches statement value within tolerance.")
                else:
                    # Specific reasons for failure are printed within verify_calculation()
                    print("\nVerification Result: FAILED")
            else:
                print("\n--- Verification Skipped (Missing numeric data) ---")

        else:
            # Specific warnings/errors are printed within extract_data() or __init__
            print("\nData extraction failed or statement format not recognized.")

    except FileNotFoundError as fnf_error:
        print(fnf_error) # Print the specific error message from __init__
    except ImportError as imp_error:
        print(imp_error) # Print PyPDF2 import error if it occurs here (shouldn't normally)
    # let the rest of the exceptions propagate for debugging

if __name__ == "__main__":
    main()
