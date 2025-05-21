from typing import Dict, Any, Union, Literal
from pydantic import BaseModel, Field

class GeneralSettings(BaseModel):
    '''General settings applicable globally.'''
    canton: str = Field(description="Your canton (e.g., 'ZH', 'BE').")
    full_name: str = Field(description="Your full name for tax documents.")
    language: str = Field(default="de", description="Default language for documents (e.g., 'de', 'fr', 'it').")
    processing_flags: Dict[str, bool] = Field(default_factory=dict, description="Default processing flags.")

    class Config:
        extra = "allow" # Allow other general settings not explicitly defined

class BrokerSettings(GeneralSettings):
    '''Settings specific to a financial institution (broker), inheriting from GeneralSettings.'''
    # Broker-specific fields can be added here if any arise beyond what GeneralSettings provides.
    # For now, it mostly serves as a hierarchical level.
    pass

class AccountSettingsBase(BrokerSettings):
    '''Base model for account-specific settings, inheriting from BrokerSettings.'''
    account_number: str = Field(description="The actual account number (e.g., IBAN or bank-specific format). This is mandatory at the account level.")
    
    # Contextual information to be added by the ConfigManager
    broker_name: str = Field(description="Name of the broker/financial institution.")
    account_name_alias: str = Field(description="User-defined alias for the account from the config file.")

class SchwabAccountSettings(AccountSettingsBase):
    '''Specific configuration settings for a Schwab account.'''
    # Add any Schwab-specific fields here if needed in the future.
    # For example:
    # schwab_specific_option: bool = True
    pass

# Add other broker-specific account settings here if needed, e.g.:
# class UBSAccountSettings(AccountSettingsBase):
#     ubs_specific_feature_enabled: bool = False

# A type union for all possible specific account settings models
SpecificAccountSettingsUnion = Union[SchwabAccountSettings] # Add other types like UBSAccountSettings here

class ConcreteAccountSettings(BaseModel):
    '''
    A wrapper model that holds the actual specific account settings.
    This is what the ConfigManager.get_account_settings will return.
    The 'settings' field will contain an instance of SchwabAccountSettings,
    or other specific types in the future.
    '''
    kind: Literal["schwab"] # Add other literals like "ubs" when more types are supported
    settings: SpecificAccountSettingsUnion
    
    # Delegate attribute access to the underlying specific settings model
    # This allows direct access like: config.account_number
    def __getattr__(self, name: str) -> Any:
        if hasattr(self.settings, name):
            return getattr(self.settings, name)
        # Raise AttributeError if not found in self.settings or self itself
        # Check self explicitly to avoid recursion if 'settings' is not yet initialized
        if name in self.__dict__ or (hasattr(self, 'settings') and name in self.settings.__dict__):
             return super().__getattribute__(name) # Fallback to default behavior
        raise AttributeError(f"'{self.__class__.__name__}' object and its underlying '{self.settings.__class__.__name__}' settings have no attribute '{name}'")


# Example of how it might be used by ConfigManager:
# resolved_data = {"canton": "ZH", ..., "broker_name": "schwab", ...}
# schwab_settings = SchwabAccountSettings(**resolved_data)
# concrete_settings = ConcreteAccountSettings(kind="schwab", settings=schwab_settings)
