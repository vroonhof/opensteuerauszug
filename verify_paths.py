from opensteuerauszug.config.paths import (
    get_xdg_config_home,
    get_xdg_data_home,
    get_app_config_dir,
    get_app_data_dir,
)
import os
from pathlib import Path

print(f"XDG_CONFIG_HOME: {get_xdg_config_home()}")
print(f"XDG_DATA_HOME: {get_xdg_data_home()}")
print(f"App Config Dir: {get_app_config_dir()}")
print(f"App Data Dir: {get_app_data_dir()}")

# Verify against expected defaults if env vars are unset
if "XDG_CONFIG_HOME" not in os.environ:
    expected_config = Path.home() / ".config"
    assert get_xdg_config_home() == expected_config

if "XDG_DATA_HOME" not in os.environ:
    expected_data = Path.home() / ".local/share"
    assert get_xdg_data_home() == expected_data
