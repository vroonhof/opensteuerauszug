import os
import pytest
from opensteuerauszug.core.flag_override_provider import FlagOverrideProvider


@pytest.fixture
def temp_files(tmp_path):
    config_path = tmp_path / "config.toml"
    csv_path = tmp_path / "security_identifiers.csv"
    return str(config_path), str(csv_path)


def test_load_from_csv(temp_files):
    config_path, csv_path = temp_files
    with open(csv_path, "w") as f:
        f.write("isin,valor,symbol,name,flags\n")
        f.write("IE00B3B8PX14,123456,SWDA,iShares Core S&P 500,Q\n")
        f.write("US0378331005,A0LHG2,AAPL,Apple Inc.,\n")
        f.write("DE000BASF111,BASF11,BAS,BASF SE,V\n")

    provider = FlagOverrideProvider(config_path, csv_path)
    assert provider.get_flag("IE00B3B8PX14") == "Q"
    assert provider.get_flag("US0378331005") is None
    assert provider.get_flag("DE000BASF111") == "V"


def test_load_from_config(temp_files):
    config_path, csv_path = temp_files
    with open(config_path, "w") as f:
        f.write("[overrides]\n")
        f.write("\"IE00B3B8PX14\" = \"Q\"\n")
        f.write("\"US0378331005\" = \"V\"\n")

    provider = FlagOverrideProvider(config_path, csv_path)
    assert provider.get_flag("IE00B3B8PX14") == "Q"
    assert provider.get_flag("US0378331005") == "V"


def test_config_overrides_csv(temp_files):
    config_path, csv_path = temp_files
    with open(csv_path, "w") as f:
        f.write("isin,valor,symbol,name,flags\n")
        f.write("IE00B3B8PX14,123456,SWDA,iShares Core S&P 500,Q\n")
    with open(config_path, "w") as f:
        f.write("[overrides]\n")
        f.write("\"IE00B3B8PX14\" = \"V\"\n")

    provider = FlagOverrideProvider(config_path, csv_path)
    assert provider.get_flag("IE00B3B8PX14") == "V"
