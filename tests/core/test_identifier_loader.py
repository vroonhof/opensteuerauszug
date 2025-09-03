import unittest
import os
import csv
import tempfile
import shutil # For tearDown

from opensteuerauszug.core.identifier_loader import SecurityIdentifierMapLoader

class TestSecurityIdentifierMapLoader(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory to store test CSV files
        self.test_dir = tempfile.mkdtemp()


    def tearDown(self):
        # Remove the temporary directory and its contents
        shutil.rmtree(self.test_dir)

    def _create_temp_csv(self, filename: str, header_row: list, data_rows: list):
        """Helper method to create a CSV file in the temporary directory."""
        filepath = os.path.join(self.test_dir, filename)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if header_row: # Allow creating file with no header for specific tests
                writer.writerow(header_row)
            if data_rows: # Allow creating file with only header or completely empty
                writer.writerows(data_rows)
        return filepath

    def test_load_map_success(self):
        header = ['symbol', 'isin', 'valor']
        data = [
            ['AAPL', 'US0378331005', '37833100'],
            ['MSFT', 'US5949181045', ''],
            ['GOOG', '', '12345'],
            ['NESTLE', 'CH0038863350', '100']
        ]
        csv_path = self._create_temp_csv('success.csv', header, data)
        loader = SecurityIdentifierMapLoader(csv_path)
        
        result_map = loader.load_map()
        self.assertEqual(len(result_map), 4)
        self.assertEqual(result_map['AAPL'], {'isin': 'US0378331005', 'valor': 37833100})
        self.assertEqual(result_map['MSFT'], {'isin': 'US5949181045', 'valor': None})
        self.assertEqual(result_map['GOOG'], {'isin': None, 'valor': 12345})
        self.assertEqual(result_map['NESTLE'], {'isin': 'CH0038863350', 'valor': 100})


    def test_load_map_file_not_found(self):
        non_existent_path = os.path.join(self.test_dir, 'non_existent.csv')
        loader = SecurityIdentifierMapLoader(non_existent_path)
        
        result_map = loader.load_map()
        self.assertEqual(result_map, {})

    def test_load_map_empty_file(self):
        # Scenario 1: Completely empty file
        empty_csv_path = self._create_temp_csv('empty.csv', None, None)
        loader_empty = SecurityIdentifierMapLoader(empty_csv_path)
        result_map_empty = loader_empty.load_map()
        self.assertEqual(result_map_empty, {})

        # Scenario 2: File with only a header
        header_only_csv_path = self._create_temp_csv('header_only.csv', ['symbol', 'isin', 'valor'], None)
        loader_header_only = SecurityIdentifierMapLoader(header_only_csv_path)
        result_map_header_only = loader_header_only.load_map()
        self.assertEqual(result_map_header_only, {})


    def test_load_map_incorrect_header(self):
        csv_path = self._create_temp_csv('bad_header.csv', ['sym', 'id', 'val'], [['AAPL', 'US0378331005', '123']])
        loader = SecurityIdentifierMapLoader(csv_path)
        
        result_map = loader.load_map()
        self.assertEqual(result_map, {})

    def test_load_map_incorrect_column_count(self):
        header = ['symbol', 'isin', 'valor']
        data = [
            ['AAPL', 'US0378331005'], # Too few
            ['MSFT', 'US5949181045', '12345', 'ExtraCol'], # Too many
            ['GOOG', 'USGOOG', '54321'] # Correct
        ]
        csv_path = self._create_temp_csv('columns.csv', header, data)
        loader = SecurityIdentifierMapLoader(csv_path)
        
        result_map = loader.load_map()
        self.assertEqual(len(result_map), 1)
        self.assertIn('GOOG', result_map)
        self.assertEqual(result_map['GOOG'], {'isin': 'USGOOG', 'valor': 54321})

    def test_load_map_invalid_valor_format(self):
        header = ['symbol', 'isin', 'valor']
        data = [['BADVAL', 'US000000000X', 'NOTANUMBER']]
        csv_path = self._create_temp_csv('invalid_valor.csv', header, data)
        loader = SecurityIdentifierMapLoader(csv_path)
        
        result_map = loader.load_map()
        self.assertEqual(len(result_map), 1)
        self.assertEqual(result_map['BADVAL'], {'isin': 'US000000000X', 'valor': None})

    def test_load_map_empty_symbol(self):
        header = ['symbol', 'isin', 'valor']
        data = [['', 'US001', '100']]
        csv_path = self._create_temp_csv('empty_symbol.csv', header, data)
        loader = SecurityIdentifierMapLoader(csv_path)

        result_map = loader.load_map()
        self.assertEqual(len(result_map), 0)

    def test_load_map_duplicate_symbol(self):
        header = ['symbol', 'isin', 'valor']
        data = [
            ['DUPSYMBOL', 'US111', '111'],
            ['ANOTHER', 'USAAA', '000'],
            ['DUPSYMBOL', 'US222', '222'] # This one should win
        ]
        csv_path = self._create_temp_csv('duplicates.csv', header, data)
        loader = SecurityIdentifierMapLoader(csv_path)

        result_map = loader.load_map()
        self.assertEqual(len(result_map), 2)
        self.assertEqual(result_map['DUPSYMBOL'], {'isin': 'US222', 'valor': 222})
        self.assertEqual(result_map['ANOTHER'], {'isin': 'USAAA', 'valor': 0})

    def test_load_map_case_insensitive_header(self):
        header = ['SyMbOl', 'IsiN', 'VALoR'] # Case-insensitive
        data = [['AAPL', 'US0378331005', '37833100']]
        csv_path = self._create_temp_csv('case_header.csv', header, data)
        loader = SecurityIdentifierMapLoader(csv_path)
        
        result_map = loader.load_map()
        self.assertEqual(len(result_map), 1)
        self.assertEqual(result_map['AAPL'], {'isin': 'US0378331005', 'valor': 37833100})

    def test_load_map_whitespace_in_cells(self):
        header = ['symbol', 'isin', 'valor']
        data = [
            ['  SPACESYMBOL  ', '  USSPACEISIN  ', '  12345  '],
            ['NOSPA', 'USNOSPA', '67890']
        ]
        csv_path = self._create_temp_csv('whitespace.csv', header, data)
        loader = SecurityIdentifierMapLoader(csv_path)
        result_map = loader.load_map()

        self.assertEqual(len(result_map), 2)
        self.assertIn('SPACESYMBOL', result_map)
        self.assertEqual(result_map['SPACESYMBOL'], {'isin': 'USSPACEISIN', 'valor': 12345})
        self.assertEqual(result_map['NOSPA'], {'isin': 'USNOSPA', 'valor': 67890})

if __name__ == '__main__':
    unittest.main()
