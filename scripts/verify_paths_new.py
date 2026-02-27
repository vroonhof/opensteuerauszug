from opensteuerauszug.config.paths import (
    get_app_config_dir,
    get_app_data_dir,
)
import os
from pathlib import Path

print(f"App Config Dir: {get_app_config_dir()}")
print(f"App Data Dir: {get_app_data_dir()}")

assert isinstance(get_app_config_dir(), Path)
assert isinstance(get_app_data_dir(), Path)

# platformdirs respects XDG variables on Linux
if "XDG_CONFIG_HOME" not in os.environ:
    expected_config_suffix = ".config/opensteuerauszug"
    assert str(get_app_config_dir()).endswith(expected_config_suffix)

if "XDG_DATA_HOME" not in os.environ:
    expected_data_suffix = ".local/share/opensteuerauszug"
    assert str(get_app_data_dir()).endswith(expected_data_suffix)
