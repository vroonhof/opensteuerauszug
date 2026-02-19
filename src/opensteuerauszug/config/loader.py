import os
import copy
import logging
from typing import Dict, Any, List, Optional
from decimal import Decimal, InvalidOperation as DecimalInvalidOperation

try:
    import tomllib # Python 3.11+
except ImportError:
    import tomli as tomllib # Fallback for Python < 3.11

from .models import (
    GeneralSettings,
    BrokerSettings,
    AccountSettingsBase,
    SchwabAccountSettings,
    ConcreteAccountSettings,
    SpecificAccountSettingsUnion,
    CalculateSettings,
)

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self, config_file_path: str = "config.toml"):
        self.config_file_path = config_file_path
        self._raw_config: Dict[str, Any] = self._load_raw_config()

        self.general_settings: Dict[str, Any] = self._raw_config.get("general", {})
        self.brokers_settings: Dict[str, Any] = self._raw_config.get("brokers", {})
        self.calculate_settings: CalculateSettings = CalculateSettings(**self._raw_config.get("calculate", {}))

    def _load_raw_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_file_path):
            # Returning an empty dict allows the app to proceed with default Pydantic model values if possible,
            # or fail later if essential configs like 'canton' or 'full_name' are missing and accessed.
            logger.warning(
                "Configuration file '%s' not found. Using empty config. "
                "To configure, copy config.template.toml to config.toml and edit with your details.",
                self.config_file_path,
            )
            return {}
        try:
            with open(self.config_file_path, "rb") as f:
                return tomllib.load(f, parse_float=Decimal) # NEW LINE
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Error decoding TOML file '{self.config_file_path}': {e}") from e

    def _deep_merge_dicts(self, base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in update.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                # If both are dicts, and the key exists in base, recurse
                merged[key] = self._deep_merge_dicts(merged[key], value)
            else:
                # Otherwise, update or add the value
                merged[key] = value
        return merged

    def _set_nested_value(self, data_dict: Dict[str, Any], path_str: str, value_str: str) -> None:
        keys = path_str.split('.')
        current_level = data_dict
        for i, key in enumerate(keys[:-1]):
            current_level = current_level.setdefault(key, {})
            if not isinstance(current_level, dict):
                # This would happen if a path tries to treat a non-dict as a dict
                # e.g., general.canton.subfield=X when general.canton is "ZH"
                raise ValueError(f"Cannot set nested value: '{key}' in path '{path_str}' is not a dictionary.")
        
        # Coerce value
        final_key = keys[-1]
        coerced_value: Any
        if value_str.lower() == "true":
            coerced_value = True
        elif value_str.lower() == "false":
            coerced_value = False
        else:
            try:
                coerced_value = int(value_str)
            except ValueError:
                try:
                    coerced_value = Decimal(value_str)
                except DecimalInvalidOperation:
                    try:
                        coerced_value = float(value_str)
                    except ValueError:
                        coerced_value = value_str # Fallback to string
        
        current_level[final_key] = coerced_value

    def _apply_cli_overrides(self, config_dict: Dict[str, Any], overrides: Optional[List[str]]) -> Dict[str, Any]:
        if not overrides:
            return config_dict

        modified_config_dict = copy.deepcopy(config_dict) # Work on a copy
        
        for override_entry in overrides:
            if '=' not in override_entry:
                logger.warning(
                    "Invalid override format '%s'. Skipping. Expected 'path.to.key=value'.",
                    override_entry,
                )
                continue
            
            path_str, value_str = override_entry.split('=', 1)
            try:
                self._set_nested_value(modified_config_dict, path_str, value_str)
            except ValueError as e:
                logger.warning(
                    "Could not apply override '%s': %s. Skipping.", override_entry, e
                )
            except Exception as e:  # Catch any other unexpected errors during override
                logger.warning(
                    "Unexpected error applying override '%s': %s. Skipping.",
                    override_entry,
                    e,
                )

        return modified_config_dict

    def get_account_settings(self, broker_name: str, account_name_alias: str, overrides: Optional[List[str]] = None) -> ConcreteAccountSettings:
        if not self._raw_config:
             # This check is important if _load_raw_config returns {} for a missing file
            raise ValueError(
                f"Cannot create settings for '{broker_name}/{account_name_alias}': "
                "Configuration file was not found or was empty."
            )

        # 1. Start with general settings
        current_config = copy.deepcopy(self.general_settings)

        # 2. Merge broker-specific settings
        broker_config_raw = self.brokers_settings.get(broker_name, {})
        if broker_config_raw:
            broker_accounts_data = broker_config_raw.get("accounts", {})
            # Exclude 'accounts' table from broker-level settings before merging
            broker_settings_only = {k: v for k, v in broker_config_raw.items() if k != "accounts"}
            current_config = self._deep_merge_dicts(current_config, broker_settings_only)
        else:
            # Log a warning if the broker is not found, but proceed with general settings.
            # Specific account settings might still exist if the structure is flat, though not per spec.
            logger.warning(
                "Broker '%s' not found in configuration. Proceeding with general settings for account '%s'.",
                broker_name,
                account_name_alias,
            )
            broker_accounts_data = {}


        # 3. Merge account-specific settings
        account_config_raw = broker_accounts_data.get(account_name_alias, {})
        if account_config_raw:
            current_config = self._deep_merge_dicts(current_config, account_config_raw)
        else:
            # This is a critical failure: account alias must exist to provide mandatory 'account_number'.
            raise ValueError(
                f"Account alias '{account_name_alias}' under broker '{broker_name}' not found in configuration. "
                "An account-specific section is required."
            )

        # Apply CLI overrides before Pydantic validation and adding contextual info
        current_config = self._apply_cli_overrides(current_config, overrides)
        
        # Add contextual information (broker_name, account_name_alias)
        # This should happen AFTER overrides in case these contextual fields were somehow targeted by overrides (though unlikely/undesirable)
        current_config["broker_name"] = broker_name
        current_config["account_name_alias"] = account_name_alias
        
        # Pydantic will validate 'account_number' when creating the model instance.
        # The explicit check for 'account_number' in `account_config_raw` is removed
        # as Pydantic in AccountSettingsBase will enforce its presence in the final `current_config`.

        # Determine the specific Pydantic model based on broker_name
        specific_settings: SpecificAccountSettingsUnion
        kind_literal: str

        if broker_name.lower() == "schwab":
            specific_settings = SchwabAccountSettings(**current_config)
            kind_literal = "schwab"
        # Example for future expansion:
        # elif broker_name.lower() == "ubs":
        #     specific_settings = UBSAccountSettings(**current_config)
        #     kind_literal = "ubs"
        else:
            # Fallback or error if broker type is unknown/unsupported for specific models
            # For now, we can try to use AccountSettingsBase if no specific model matches,
            # but this might not be ideal if specific fields are expected later.
            # A stricter approach would be to raise an error.
            logger.warning(
                "No specific Pydantic model defined for broker '%s'. Using AccountSettingsBase. Some broker-specific features might not be available.",
                broker_name,
            )
            # This will fail if AccountSettingsBase itself is not meant to be instantiated directly
            # or if current_config has fields not allowed by AccountSettingsBase.
            # Given the current setup, SchwabAccountSettings is derived from AccountSettingsBase
            # and doesn't add new fields, so this path is less likely to be hit for "schwab".
            # If we had a distinct model, we'd use:
            #   specific_settings = AccountSettingsBase(**current_config)
            #   kind_literal = "base" # Or some other generic literal
            # However, since ConcreteAccountSettings expects a kind from a Literal set,
            # we must handle unknown brokers more gracefully or restrict them.
            # For now, let's assume "schwab" is the only configured one.
            raise ValueError(f"Unsupported broker type for specific settings: {broker_name}. Only 'schwab' is currently configured with a specific model.")

        try:
            # Wrap in ConcreteAccountSettings
            # The Pydantic validation for ConcreteAccountSettings will also run here.
            return ConcreteAccountSettings(kind=kind_literal, settings=specific_settings)
        except Exception as e: # Catch Pydantic validation error or other issues
            raise ValueError(
                f"Validation error for resolved settings of account '{account_name_alias}' on broker '{broker_name}': {e}\n"
                f"Merged Data for Pydantic: {current_config}"
            ) from e

    def list_brokers(self) -> List[str]:
        return list(self.brokers_settings.keys())

    def list_accounts(self, broker_name: str) -> List[str]:
        broker_config = self.brokers_settings.get(broker_name, {})
        return list(broker_config.get("accounts", {}).keys())

    def get_all_account_settings_for_broker(self, broker_name: str, overrides: Optional[List[str]] = None) -> List[ConcreteAccountSettings]:
        '''
        Retrieves and merges configuration for all accounts under a specific broker,
        applying any CLI overrides.
        Returns a list of ConcreteAccountSettings objects.
        '''
        if not self._raw_config:
            logger.warning(
                "Configuration file '%s' not found or empty. Cannot retrieve accounts for broker '%s'.",
                self.config_file_path,
                broker_name,
            )
            return []

        broker_config_raw = self.brokers_settings.get(broker_name, {})
        if not broker_config_raw:
            logger.warning(
                "Broker '%s' not found in configuration. Cannot list accounts.",
                broker_name,
            )
            return []

        account_aliases = list(broker_config_raw.get("accounts", {}).keys())
        if not account_aliases:
            logger.info("No accounts found configured under broker '%s'.", broker_name)
            return []

        all_settings: List[ConcreteAccountSettings] = []
        for alias in account_aliases:
            try:
                # Use the existing get_account_settings method (which should be renamed to
                # _get_resolved_account_settings or similar if we want to make it private,
                # but for now, let's assume it's still public as per plan description)
                # If get_account_settings is made private (e.g. _get_resolved_account_settings),
                # this call needs to be updated.
                account_specific_settings = self.get_account_settings(broker_name, alias, overrides=overrides)
                all_settings.append(account_specific_settings)
            except ValueError as e:
                # Log the error for the specific account and continue with others
                logger.warning(
                    "Could not load settings for account '%s' under broker '%s': %s",
                    alias,
                    broker_name,
                    e,
                )
        
        return all_settings

