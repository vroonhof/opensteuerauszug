import os
from pathlib import Path
from typing import Optional, Union
from platformdirs import user_config_path, user_data_path

def get_app_config_dir() -> Path:
    """Returns the application config directory under XDG config home."""
    return user_config_path("opensteuerauszug")

def get_app_data_dir() -> Path:
    """Returns the application data directory under XDG data home."""
    return user_data_path("opensteuerauszug")

def get_cwd_config_file() -> Path:
    """Returns path to config.toml in current working directory."""
    return Path.cwd() / "config.toml"

def get_cwd_data_dir() -> Path:
    """Returns path to data directory in current working directory."""
    return Path.cwd() / "data"

def resolve_config_file(path_arg: Optional[Union[str, Path]] = None) -> Path:
    """
    Resolves the configuration file path.
    Priority:
    1. path_arg (if provided)
    2. $XDG_CONFIG_HOME/opensteuerauszug/config.toml (if exists)
    3. ./config.toml (if exists)
    4. $XDG_CONFIG_HOME/opensteuerauszug/config.toml (fallback)
    """
    if path_arg:
        return Path(path_arg)

    app_config = get_app_config_dir() / "config.toml"
    if app_config.exists():
        return app_config

    cwd_config = get_cwd_config_file()
    if cwd_config.exists():
        return cwd_config

    return app_config

def resolve_kursliste_dir(path_arg: Optional[Union[str, Path]] = None) -> Path:
    """
    Resolves the Kursliste directory path.
    Priority:
    1. path_arg (if provided)
    2. $XDG_DATA_HOME/opensteuerauszug/kursliste (if exists)
    3. ./data/kursliste (if exists)
    4. $XDG_DATA_HOME/opensteuerauszug/kursliste (fallback)
    """
    if path_arg:
        return Path(path_arg)

    app_kursliste = get_app_data_dir() / "kursliste"
    if app_kursliste.exists():
        return app_kursliste

    cwd_kursliste = get_cwd_data_dir() / "kursliste"
    if cwd_kursliste.exists():
        return cwd_kursliste

    return app_kursliste

def resolve_security_identifiers_file(path_arg: Optional[Union[str, Path]] = None) -> Path:
    """
    Resolves the security identifiers CSV file path.
    Priority:
    1. path_arg (if provided)
    2. $XDG_CONFIG_HOME/opensteuerauszug/security_identifiers.csv (if exists)
    3. ./data/security_identifiers.csv (if exists)
    4. $XDG_CONFIG_HOME/opensteuerauszug/security_identifiers.csv (fallback)
    """
    if path_arg:
        return Path(path_arg)

    app_identifiers = get_app_config_dir() / "security_identifiers.csv"
    if app_identifiers.exists():
        return app_identifiers

    cwd_identifiers = get_cwd_data_dir() / "security_identifiers.csv"
    if cwd_identifiers.exists():
        return cwd_identifiers

    return app_identifiers
