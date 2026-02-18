# OpenSteuerAuszug Configuration System

This document describes how to configure the OpenSteuerAuszug application using a `config.toml` file. The system allows for general user settings, per-financial-institution (broker) overrides, and per-account settings, providing a high degree of flexibility for processing your bank statements for tax documents.

## Setup

The configuration file is **optional**. To set it up:

1. Copy the template file: `cp config.template.toml config.toml`
2. Edit `config.toml` with your personal information (canton, full name, account numbers, etc.)
3. The `config.toml` file is ignored by git to protect your personal data

**Note:** If `config.toml` is not present, the application will still run but will use empty configuration. You may need to provide required settings via command-line arguments.

## User Documentation: Configuring with `config.toml`

The configuration is loaded from a single `config.toml` file. The settings are structured hierarchically, allowing specific configurations to override more general ones in the following order of precedence (most specific wins):

1.  **Account-Specific Settings:** Defined for a particular account within a financial institution. Crucially, the `account_number` **must** be defined here.
2.  **Broker-Specific Settings:** Defined for a particular financial institution (referred to as "broker"), applying to all its accounts unless overridden by an account.
3.  **General Settings:** Global defaults that apply to all brokers and accounts unless overridden at a more specific level. This is where you define your `canton` and `full_name`.

### File Structure

The `config.toml` file is organized into sections using TOML's table syntax.

#### 1. General Settings

Global default settings are defined under the `[general]` table.

```toml
[general]
# Your canton (e.g., "ZH", "BE", "AG"). This is used for tax form generation.
canton = "ZH"

# Your full name as it should appear on tax documents.
full_name = "Erika Mustermann"

# Example: Default language for generated documents (e.g., "de", "fr", "it")
language = "de"

# Example: Optional default processing flags
[general.processing_flags]
detect_dividends = true
calculate_average_exchange_rates = false
```

2. Broker-Level Settings (Financial Institution)You can define settings specific to each financial institution (broker) under the [brokers.<BrokerName>] table. <BrokerName> should be a unique identifier for the institution (e.g., ubs, postfinance, kantonalbank_XY). These settings override values from the [general] section.[brokers.my_favorite_bank]
```toml
# Example: Override language for documents from this specific bank
language = "fr"

# Example: Specific processing flags for this bank
[brokers.my_favorite_bank.processing_flags]
handle_specific_fee_type = true
# detect_dividends would be inherited from general (true)
```
If a setting (other than account_number) is not specified for a broker, the value from [general] will be used.


3. Account-Level Settings (within a Broker)For granular control, specify settings for individual accounts within a broker. These are defined under [brokers.<BrokerName>.accounts.<AccountName>]. <AccountName> is a user-defined alias for the account (e.g., savings_main, checking_joint).The account_number (IBAN or bank-specific format) for the account MUST be defined here.These settings override both [general] and the parent [brokers.<BrokerName>] settings.[brokers.my_favorite_bank.accounts.primary_checking]
```toml
# MANDATORY: The actual account number (IBAN or other format)
account_number = "CH9300762011623852957"

# Example: Override processing flags specifically for this account
[brokers.my_favorite_bank.accounts.primary_checking.processing_flags]
detect_dividends = false # Overrides general and broker setting
calculate_average_exchange_rates = true # Overrides general setting
```
If a setting (like language or flags within processing_flags) is not found at the account level, the system looks at the parent broker level. If not found there, it looks at the [general] settings.

# Example: config.toml for OpenSteuerAuszug
```toml
# 1. General Settings
[general]
canton = "ZH"
full_name = "Max Mustermann"
language = "de"

[general.processing_flags]
detect_foreign_income = true
summarize_by_category = true

# 2. Broker-level Settings / Overrides
[brokers.swiss_bank_alpha]
language = "en" # Documents from Swiss Bank Alpha will be in English

[brokers.swiss_bank_alpha.processing_flags]
# Inherits detect_foreign_income = true from general
# Inherits summarize_by_category = true from general
custom_alpha_parser_enabled = true

[brokers.local_kantonalbank]
# Inherits canton, full_name, language from [general]
[brokers.local_kantonalbank.processing_flags]
# Inherits detect_foreign_income = true from general
summarize_by_category = false # Override for this bank

# 3. Account-level Settings / Overrides
[brokers.swiss_bank_alpha.accounts.main_chf_account]
account_number = "CH560023323312345678A"
# Inherits language = "en" from swiss_bank_alpha
[brokers.swiss_bank_alpha.accounts.main_chf_account.processing_flags]
# Inherits custom_alpha_parser_enabled = true from swiss_bank_alpha
detect_foreign_income = false # Override for this specific account

[brokers.swiss_bank_alpha.accounts.euro_savings]
account_number = "CH210023323398765432B"
# Inherits language = "en" from swiss_bank_alpha
# All processing_flags inherited from swiss_bank_alpha and general

[brokers.local_kantonalbank.accounts.private_account]
account_number = "CH1200700110001234567"
# Inherits language = "de" from general
[brokers.local_kantonalbank.accounts.private_account.processing_flags]
# Inherits summarize_by_category = false from local_kantonalbank
# Inherits detect_foreign_income = true from general
```

By structuring your config.toml this way, you can maintain clear and manageable configurations for OpenSteuerAuszug.

# Implementation Appendix (for LLM Agent)

This section provides details for implementing the Python configuration loader using TOML and Pydantic for OpenSteuerAuszug. These are guiding examples, 

Requirements

Python 3.7+pydantic librarytomli library (for Python < 3.11) or tomllib (Python 3.11+)Install them using pip:pip install pydantic "tomli>=1.1.0" # For Python < 3.11

1. Pydantic Model for Resolved Account Settings

This model represents the final, merged configuration settings that the application will use for a specific account.

   In the real application this should probably consist of a hierarchy of classes per level.

e.g. SchwabAccountSettings inherits from SchwabSettings inherits from GlobalSettings (or similar)

```python
# In app_config.py (or app_config_models.py)
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class AccountSettings(BaseModel):
    """
    Represents the fully resolved configuration for a specific broker and account
    for OpenSteuerAuszug, after merging general, broker, and account-specific settings.
    """
    # Global user settings (can be overridden)
    canton: str
    full_name: str
    language: str = "de" # Default language

    # Account-specific MANDATORY setting
    account_number: str # This must come from the account-level config

    # Processing flags (merged dictionary)
    processing_flags: Dict[str, bool] = Field(default_factory=dict)

    # Contextual information added by the ConfigManager
    broker_name: str
    account_name_alias: str # The alias used in the config file

    # Allow any other settings found during merge to be part of the model
    class Config:
        extra = "allow"
```
2. Configuration Manager Implementation

The ConfigManager will load the TOML file, perform the hierarchical merge, and return an AccountSettings instance.

```python
# In app_config.py (or app_config_loader.py)
import os
import copy
from typing import Dict, Any, Optional, List

try:
    import tomllib # Python 3.11+
except ImportError:
    import tomli as tomllib # Fallback for Python < 3.11

# (Pydantic AccountSettings model from above should be defined here or imported)
# from .app_config_models import AccountSettings # If in a separate file

class ConfigManager:
    def __init__(self, config_file_path: str = "config.toml"):
        self.config_file_path = config_file_path
        self._raw_config: Dict[str, Any] = self._load_raw_config()

        self.general_settings: Dict[str, Any] = self._raw_config.get("general", {})
        self.brokers_settings: Dict[str, Any] = self._raw_config.get("brokers", {})

    def _load_raw_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_file_path):
            print(f"Warning: Configuration file '{self.config_file_path}' not found. Using empty config.")
            return {}
        try:
            with open(self.config_file_path, "rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Error decoding TOML file '{self.config_file_path}': {e}") from e

    def _deep_merge_dicts(self, base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in update.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                merged[key] = self._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

    def get_account_settings(self, broker_name: str, account_name_alias: str) -> AccountSettings:
        """
        Retrieves and merges configuration for a specific account on a specific broker.
        Merging order (later ones override earlier ones): General -> Broker -> Account.
        'account_number' is expected to be defined at the account level.
        """
        if not self._raw_config:
            raise ValueError(
                f"Cannot create settings for '{broker_name}/{account_name_alias}': "
                "Configuration file was empty or not found."
            )

        # 1. Start with general settings
        current_config = copy.deepcopy(self.general_settings)

        # 2. Merge broker-specific settings
        broker_config_raw = self.brokers_settings.get(broker_name, {})
        if broker_config_raw:
            broker_accounts_data = broker_config_raw.get("accounts", {})
            broker_settings_only = {k: v for k, v in broker_config_raw.items() if k != "accounts"}
            current_config = self._deep_merge_dicts(current_config, broker_settings_only)
        else:
            print(f"Warning: Broker '{broker_name}' not found. Using general settings for broker level.")
            broker_accounts_data = {}

        # 3. Merge account-specific settings
        account_config_raw = broker_accounts_data.get(account_name_alias, {})
        if account_config_raw:
            current_config = self._deep_merge_dicts(current_config, account_config_raw)
        else:
            # If the account alias is not found, it means we can't get an account_number,
            # which is mandatory for AccountSettings.
            raise ValueError(
                f"Account alias '{account_name_alias}' under broker '{broker_name}' not found in configuration. "
                "An account-specific section with 'account_number' is required."
            )

        # Ensure 'account_number' is present from the account-specific config
        if "account_number" not in account_config_raw:
            raise ValueError(
                f"Mandatory setting 'account_number' is missing for account '{account_name_alias}' "
                f"under broker '{broker_name}'."
            )

        # Add contextual information
        current_config["broker_name"] = broker_name
        current_config["account_name_alias"] = account_name_alias

        try:
            return AccountSettings(**current_config)
        except Exception as e: # Catch Pydantic validation error
            raise ValueError(
                f"Validation error for resolved settings of account '{account_name_alias}' on broker '{broker_name}': {e}\n"
                f"Merged Data for Pydantic: {current_config}"
            ) from e

    def list_brokers(self) -> List[str]:
        return list(self.brokers_settings.keys())

    def list_accounts(self, broker_name: str) -> List[str]:
        broker_config = self.brokers_settings.get(broker_name, {})
        return list(broker_config.get("accounts", {}).keys())
```
3. Example Usage (for testing the implementation)

```python
# In app_config.py or a separate test script
if __name__ == "__main__":
    # Create a dummy config.toml for testing OpenSteuerAuszug
    dummy_config_content = """
[general]
canton = "ZH"
full_name = "Erika Mustermann"
language = "de"
[general.processing_flags]
detect_foreign_income = true
summarize_by_category = true

[brokers.bank_alpha]
language = "en" # Override
[brokers.bank_alpha.processing_flags]
custom_alpha_parser = true

[brokers.bank_beta]
# Inherits general settings
[brokers.bank_beta.processing_flags]
summarize_by_category = false # Override general

[brokers.bank_alpha.accounts.chf_primary]
account_number = "CH112233445566778899A"
[brokers.bank_alpha.accounts.chf_primary.processing_flags]
detect_foreign_income = false # Override general & broker

[brokers.bank_alpha.accounts.usd_secondary]
account_number = "US998877665544332211B"
# Inherits language from bank_alpha
# Inherits processing_flags from bank_alpha & general

[brokers.bank_beta.accounts.local_savings]
account_number = "CH00112233445566778S"
full_name = "Erika Mustermann-Spar" # Account specific full name override
# Inherits language from general
# Inherits canton from general
[brokers.bank_beta.accounts.local_savings.processing_flags]
# Inherits summarize_by_category = false from bank_beta
# Inherits detect_foreign_income = true from general
    """
    with open("config.toml", "w") as f:
        f.write(dummy_config_content)

    try:
        config_manager = ConfigManager(config_file_path="config.toml")

        print("Available brokers:", config_manager.list_brokers())
        if "bank_alpha" in config_manager.list_brokers():
            print("Accounts in bank_alpha:", config_manager.list_accounts("bank_alpha"))

        print("\n--- Settings for bank_alpha / chf_primary ---")
        settings_alpha_chf = config_manager.get_account_settings("bank_alpha", "chf_primary")
        print(f"Canton: {settings_alpha_chf.canton}")  # Expected: ZH
        print(f"Full Name: {settings_alpha_chf.full_name}") # Expected: Erika Mustermann
        print(f"Language: {settings_alpha_chf.language}") # Expected: en (from broker)
        print(f"Account Number: {settings_alpha_chf.account_number}") # Expected: CH...A
        print(f"Processing Flags: {settings_alpha_chf.processing_flags}")
        # Expected: {'detect_foreign_income': False, 'summarize_by_category': True, 'custom_alpha_parser': True}
        print(f"Full model dump: {settings_alpha_chf.model_dump(exclude_none=True)}")

        print("\n--- Settings for bank_alpha / usd_secondary ---")
        settings_alpha_usd = config_manager.get_account_settings("bank_alpha", "usd_secondary")
        print(f"Language: {settings_alpha_usd.language}") # Expected: en
        print(f"Account Number: {settings_alpha_usd.account_number}") # Expected: US...B
        print(f"Processing Flags: {settings_alpha_usd.processing_flags}")
        # Expected: {'detect_foreign_income': True, 'summarize_by_category': True, 'custom_alpha_parser': True}

        print("\n--- Settings for bank_beta / local_savings ---")
        settings_beta_savings = config_manager.get_account_settings("bank_beta", "local_savings")
        print(f"Canton: {settings_beta_savings.canton}") # Expected: ZH
        print(f"Full Name: {settings_beta_savings.full_name}") # Expected: Erika Mustermann-Spar (overridden)
        print(f"Language: {settings_beta_savings.language}") # Expected: de (from general)
        print(f"Account Number: {settings_beta_savings.account_number}") # Expected: CH...S
        print(f"Processing Flags: {settings_beta_savings.processing_flags}")
        # Expected: {'detect_foreign_income': True, 'summarize_by_category': False}

        print("\n--- Testing missing account alias (should raise ValueError) ---")
        try:
            config_manager.get_account_settings("bank_beta", "non_existent_alias")
        except ValueError as e:
            print(f"Caught expected error: {e}")

        print("\n--- Testing account missing account_number (should raise ValueError) ---")
        # Create a faulty config for this test
        faulty_config_content = """
[general]
canton = "AG"
full_name = "Faulty User"
[brokers.faulty_bank.accounts.no_num_account]
# account_number is missing!
language = "it"
        """
        with open("faulty_config.toml", "w") as f:
            f.write(faulty_config_content)
        try:
            faulty_manager = ConfigManager(config_file_path="faulty_config.toml")
            faulty_manager.get_account_settings("faulty_bank", "no_num_account")
        except ValueError as e:
            print(f"Caught expected error: {e}")
        finally:
            if os.path.exists("faulty_config.toml"):
                os.remove("faulty_config.toml")


    except ValueError as e:
        print(f"Configuration Error: {e}")
    finally:
        if os.path.exists("config.toml"):
            os.remove("config.toml")
```

## Security Identifier Enrichment

The OpenSteuerAuszug application can automatically enrich your security data by adding missing ISIN (International Securities Identification Number) and Valor numbers. This is achieved by using a CSV file located at `data/security_identifiers.csv` relative to the project root.

The `CleanupCalculator` process utilizes this file during its operations to look up securities by their name and populate the `isin` and/or `valorNumber` fields if they are not already present in the input data.

### CSV File Format

The CSV file must adhere to the following format:

1.  **Header Row**: The first line of the file must be `symbol,isin,valor`.
2.  **Data Rows**: Subsequent lines should contain the data for each security:
    *   `symbol`: This is the lookup key. It should match the security name found in your financial documents (e.g., the `securityName` field in the eCH-0196 data).
    *   `isin`: The ISIN to be populated if the security is missing one. This field can be left empty if you only want to provide a Valor number for the given symbol.
    *   `valor`: The Valor number to be populated if the security is missing one. This field can be left empty if you only want to provide an ISIN. If provided, it must be a valid integer.

### File Location and Configuration
By default, the application looks for this file at `data/security_identifiers.csv` (relative to the project root). However, you can specify a custom path using the command-line argument:
`--identifiers-csv-path /path/to/your/identifiers.csv`

If this argument is not provided, the default path will be used.

### Example CSV Content

```csv
symbol,isin,valor
MyTech Stock,US1234567890,1234567
OldCorp Bonds,,7654321
EuroFund Tranche X,DE000XYZ1234,
Another Security Name Without Valor,CH9876543210,
```

### Optional File

This `security_identifiers.csv` file is **optional**.
*   If the file is not found at the specified location (`data/security_identifiers.csv`), a warning message will be logged.
*   The enrichment step will be skipped, and the program will continue to operate normally with the data as it was originally provided.

This feature is particularly useful when your bank's export files do not consistently provide ISIN or Valor numbers for all securities, allowing you to maintain a supplementary list for complete data records.
