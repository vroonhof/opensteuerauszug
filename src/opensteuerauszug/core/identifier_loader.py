import csv
import os
import logging # Use standard logging

# Configure a logger for this module (or class) if desired, or use root logger
logger = logging.getLogger(__name__)

class SecurityIdentifierMapLoader:
    def __init__(self, csv_path: str):
        """
        Initializes the loader with the path to the security identifiers CSV file.

        Args:
            csv_path: The absolute path to the CSV file.
        """
        self.csv_path = csv_path
        # Expected headers are checked case-insensitively after normalizing them.
        self.expected_headers_normalized = ['symbol', 'isin', 'valor'] 

    def load_map(self) -> dict:
        """
        Loads the security identifiers from the CSV file.

        The CSV file must have a header row: symbol,isin,valor (case-insensitive).
        - symbol: The security name/symbol for lookup.
        - isin: The ISIN. Can be empty.
        - valor: The Valor number. Can be empty or a valid integer.

        Returns:
            A dictionary where keys are symbols (str) and values are
            dictionaries {'isin': Optional[str], 'valor': Optional[int]}.
            Returns an empty dictionary if the file is not found, header is incorrect,
            or other critical parsing errors occur.
        """
        identifier_map = {}

        if not os.path.exists(self.csv_path):
            logger.debug(f"Security identifiers file not found at {self.csv_path}. Enrichment will be skipped.")
            return identifier_map

        try:
            with open(self.csv_path, mode='r', encoding='utf-8-sig', newline='') as file:
                reader = csv.reader(file)
                
                try:
                    header = next(reader)
                except StopIteration:
                    logger.error(f"Security identifiers file {self.csv_path} is empty (no header).")
                    return identifier_map

                normalized_header = [h.lower().strip() for h in header]
                
                if normalized_header != self.expected_headers_normalized:
                    logger.error(
                        f"Incorrect header in security identifiers file {self.csv_path}. "
                        f"Expected: {self.expected_headers_normalized}, Got: {header} (normalized: {normalized_header})."
                    )
                    return identifier_map

                for i, row in enumerate(reader, start=2): # start=2 for 1-based data row index
                    if len(row) != len(self.expected_headers_normalized):
                        logger.warning(
                            f"Row {i} in {self.csv_path} has incorrect number of columns "
                            f"(expected {len(self.expected_headers_normalized)}, got {len(row)}). Skipping row: {row}"
                        )
                        continue

                    symbol = row[0].strip()
                    isin_str = row[1].strip()
                    valor_str = row[2].strip()

                    if not symbol:
                        logger.warning(f"Row {i} in {self.csv_path} has an empty symbol. Skipping row.")
                        continue

                    isin_val = isin_str if isin_str else None
                    valor_val = None

                    if valor_str:
                        try:
                            valor_val = int(valor_str)
                        except ValueError:
                            logger.warning(
                                f"Row {i} in {self.csv_path} for symbol '{symbol}': "
                                f"Could not convert valor '{valor_str}' to an integer. Valor will be considered missing."
                            )
                    
                    if symbol in identifier_map:
                        logger.warning(f"Duplicate symbol '{symbol}' found in {self.csv_path} at row {i}. Previous entry will be overwritten.")

                    identifier_map[symbol] = {'isin': isin_val, 'valor': valor_val}
        
        except csv.Error as e:
            # reader.line_num might not be reliable after an error, log the general error
            logger.error(f"CSV parsing error in {self.csv_path}: {e}")
            return {} 
        except IOError as e:
            logger.error(f"Could not read security identifiers file {self.csv_path}: {e}")
            return {} 

        if identifier_map: # Log only if some identifiers were actually loaded
            logger.info(f"Successfully loaded {len(identifier_map)} security identifiers from {self.csv_path}.")
        elif os.path.exists(self.csv_path): # File exists but was empty after header or all rows had errors
            logger.info(f"Security identifiers file {self.csv_path} was processed, but no valid identifiers were loaded.")
        return identifier_map

# Removed or commented out the __main__ block as per instructions.
# # if __name__ == '__main__':
# #     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
# #     dummy_csv_path = 'temp_test_identifiers.csv'
# #     with open(dummy_csv_path, 'w', newline='') as f:
# #         writer = csv.writer(f)
# #         writer.writerow(['SYMBOL', 'ISIN', 'VALOR']) # Test case-insensitivity of header
# #         writer.writerow(['AAPL', 'US0378331005', '37833100'])
# #         writer.writerow(['MSFT', 'US5949181045', ''])
# #         writer.writerow(['GOOG', '', '12345'])
# #         writer.writerow(['BADVAL', 'US000000000X', 'NOTANUMBER'])
# #         writer.writerow(['', 'US001', '100']) # Empty symbol
# #         writer.writerow(['DUPSYMBOL', 'US111', '111'])
# #         writer.writerow(['DUPSYMBOL', 'US222', '222'])
# #         writer.writerow(['TRAILINGSPACE ', ' USTRAILINGISIN ', ' 777 '])
# #         writer.writerow(['MISSINGCOLS', 'US123'])
# #         writer.writerow(['ALLGOOD', 'ALLGOODISIN', '999'])
# #
# #     loader = SecurityIdentifierMapLoader(dummy_csv_path)
# #     id_map = loader.load_map()
# #     print("\n--- Loaded Map ---")
# #     for k, v in id_map.items():
# #         print(f"{k}: {v}")
# #
# #     os.remove(dummy_csv_path)
# #
# #     print("\n--- Test File Not Found ---")
# #     non_existent_loader = SecurityIdentifierMapLoader('non_existent.csv')
# #     nf_map = non_existent_loader.load_map()
# #     print(f"Map from non-existent file: {nf_map}")
# #
# #     print("\n--- Test Empty File ---")
# #     empty_csv_path = 'temp_empty.csv'
# #     with open(empty_csv_path, 'w') as f:
# #         pass # create empty file
# #     empty_loader = SecurityIdentifierMapLoader(empty_csv_path)
# #     em_map = empty_loader.load_map()
# #     print(f"Map from empty file: {em_map}")
# #     os.remove(empty_csv_path)
# #
# #     print("\n--- Test Incorrect Header ---")
# #     dummy_bad_header_csv_path = 'temp_bad_header.csv'
# #     with open(dummy_bad_header_csv_path, 'w', newline='') as f:
# #         writer = csv.writer(f)
# #         writer.writerow(['sym', 'is', 'val'])
# #         writer.writerow(['AAPL', 'US0378331005', '37833100'])
# #     bad_header_loader = SecurityIdentifierMapLoader(dummy_bad_header_csv_path)
# #     bh_map = bad_header_loader.load_map()
# #     print(f"Map from bad header file: {bh_map}")
# #     os.remove(dummy_bad_header_csv_path)
