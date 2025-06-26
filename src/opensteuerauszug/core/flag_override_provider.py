import configparser
import csv
from typing import Dict, Optional


class FlagOverrideProvider:
    """Provides a mechanism to override Kursliste flags from configuration files."""

    def __init__(self, config_path: str, identifiers_path: str):
        """
        Initializes the provider by loading overrides from the specified files.

        Args:
            config_path: Path to the config.toml file.
            identifiers_path: Path to the security_identifiers.csv file.
        """
        self._overrides: Dict[str, str] = {}
        self._load_from_csv(identifiers_path)
        self._load_from_config(config_path)

    def _load_from_csv(self, file_path: str):
        """Loads flag overrides from the security_identifiers.csv file."""
        try:
            with open(file_path, mode='r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                if 'flags' in reader.fieldnames:
                    for row in reader:
                        if row.get('isin') and row.get('flags'):
                            self._overrides[row['isin']] = row['flags'].strip()
        except FileNotFoundError:
            # It's okay if the file doesn't exist.
            pass
        except Exception as e:
            print(f"Warning: Could not load flag overrides from {file_path}: {e}")

    def _load_from_config(self, file_path: str):
        """Loads flag overrides from the config.toml file."""
        try:
            config = configparser.ConfigParser()
            config.read(file_path)
            if 'overrides' in config:
                for isin, flag in config['overrides'].items():
                    self._overrides[isin.upper().strip('"')] = flag.strip('"')
        except FileNotFoundError:
            # It's okay if the file doesn't exist.
            pass
        except Exception as e:
            print(f"Warning: Could not load flag overrides from {file_path}: {e}")

    def get_flag(self, isin: str) -> Optional[str]:
        """Returns the override flag for a given ISIN."""
        return self._overrides.get(isin)
