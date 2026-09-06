"""Tests for resolving broker account sections from config.toml."""

import pytest

from opensteuerauszug.config.loader import ConfigManager
from opensteuerauszug.config.models import DegiroAccountSettings

CONFIG_TEMPLATE = """
[general]
full_name = "Max Muster"
canton = "ZH"

[brokers.{broker}.accounts.main]
kind = "{broker}"
account_number = "12345678"
"""


def _config_manager(tmp_path, broker: str) -> ConfigManager:
    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG_TEMPLATE.format(broker=broker), encoding="utf-8")
    return ConfigManager(str(config_path))


def test_degiro_account_section_resolves_to_degiro_settings(tmp_path):
    """A [brokers.degiro.accounts.*] section is usable, as documented in the DEGIRO guide."""
    manager = _config_manager(tmp_path, "degiro")

    settings = manager.get_account_settings("degiro", "main")

    assert settings.kind == "degiro"
    assert isinstance(settings.settings, DegiroAccountSettings)
    assert settings.account_number == "12345678"
    assert settings.full_name == "Max Muster"
    assert settings.canton == "ZH"


@pytest.mark.parametrize("broker", ["schwab", "ibkr", "fidelity", "degiro"])
def test_all_supported_brokers_load_their_accounts(tmp_path, broker):
    manager = _config_manager(tmp_path, broker)

    all_settings = manager.get_all_account_settings_for_broker(broker)

    assert [s.kind for s in all_settings] == [broker]


def test_unknown_broker_reports_the_supported_brokers(tmp_path):
    manager = _config_manager(tmp_path, "unsupported")

    with pytest.raises(ValueError, match="degiro"):
        manager.get_account_settings("unsupported", "main")
