"""Tests for CLI configuration overrides."""
import pytest

from opensteuerauszug.config.loader import ConfigManager


class TestCliOverrides:
    """Tests for the _apply_cli_overrides method."""

    @staticmethod
    def _write_config(tmp_path, content: str):
        config_path = tmp_path / "config.toml"
        config_path.write_text(content, encoding="utf-8")
        return config_path

    def test_apply_override_to_string_value(self):
        """Test that string overrides work correctly."""
        config_dict = {"general": {"language": "de", "canton": "ZH"}}
        config_manager = ConfigManager()

        result = config_manager._apply_cli_overrides(
            config_dict,
            ["general.language=fr"]
        )

        assert result["general"]["language"] == "fr"
        assert result["general"]["canton"] == "ZH"  # Unchanged

    def test_apply_bare_general_override_to_string_value(self):
        """Test that bare overrides target general settings by default."""
        config_dict = {"general": {"language": "de", "canton": "ZH"}}
        config_manager = ConfigManager()

        result = config_manager._apply_cli_overrides(
            config_dict,
            ["language=fr"]
        )

        assert result["general"]["language"] == "fr"
        assert result["general"]["canton"] == "ZH"

    def test_apply_multiple_overrides(self):
        """Test that multiple overrides work correctly."""
        config_dict = {"general": {"language": "de", "canton": "ZH"}}
        config_manager = ConfigManager()

        result = config_manager._apply_cli_overrides(
            config_dict,
            ["general.language=fr", "general.canton=BE"]
        )

        assert result["general"]["language"] == "fr"
        assert result["general"]["canton"] == "BE"

    def test_apply_override_to_boolean(self):
        """Test that boolean overrides work correctly."""
        config_dict = {"settings": {"enabled": False}}
        config_manager = ConfigManager()

        result = config_manager._apply_cli_overrides(
            config_dict,
            ["settings.enabled=true"]
        )

        assert result["settings"]["enabled"] is True

    def test_apply_override_to_number(self):
        """Test that numeric overrides work correctly."""
        config_dict = {"settings": {"count": 10}}
        config_manager = ConfigManager()

        result = config_manager._apply_cli_overrides(
            config_dict,
            ["settings.count=42"]
        )

        assert result["settings"]["count"] == 42

    def test_apply_override_creates_nested_structure(self):
        """Test that overrides can create new nested structures."""
        config_dict = {}
        config_manager = ConfigManager()

        result = config_manager._apply_cli_overrides(
            config_dict,
            ["general.language=fr"]
        )

        assert result["general"]["language"] == "fr"

    def test_apply_override_with_no_overrides(self):
        """Test that None or empty overrides list returns original dict."""
        config_dict = {"general": {"language": "de"}}
        config_manager = ConfigManager()

        result_none = config_manager._apply_cli_overrides(config_dict, None)
        result_empty = config_manager._apply_cli_overrides(config_dict, [])

        assert result_none == config_dict
        assert result_empty == config_dict

    def test_override_does_not_modify_original(self):
        """Test that _apply_cli_overrides doesn't modify the original dict."""
        config_dict = {"general": {"language": "de"}}
        config_manager = ConfigManager()

        result = config_manager._apply_cli_overrides(
            config_dict,
            ["general.language=fr"]
        )

        # Original should be unchanged
        assert config_dict["general"]["language"] == "de"
        # Result should be modified
        assert result["general"]["language"] == "fr"

    def test_invalid_override_format_is_skipped(self):
        """Test that invalid override format is skipped."""
        config_dict = {"general": {"language": "de"}}
        config_manager = ConfigManager()

        result = config_manager._apply_cli_overrides(
            config_dict,
            ["invalid_format", "general.language=fr"]
        )

        # Valid override should still be applied
        assert result["general"]["language"] == "fr"

    def test_resolve_calculate_settings_uses_overridden_root_config(self, tmp_path):
        """Test that calculate settings are resolved from the overridden config tree."""
        config_path = self._write_config(
            tmp_path,
            """
[calculate]
keep_existing_payments = false
""".strip(),
        )
        config_manager = ConfigManager(config_file_path=str(config_path))

        result = config_manager.resolve_calculate_settings(
            ["calculate.keep_existing_payments=true"]
        )

        assert result.keep_existing_payments is True

    def test_resolve_calculate_settings_ignores_bare_calculate_key(self, tmp_path):
        """Test that bare calculate-looking overrides are not remapped into calculate."""
        config_path = self._write_config(
            tmp_path,
            """
[calculate]
keep_existing_payments = false
""".strip(),
        )
        config_manager = ConfigManager(config_file_path=str(config_path))

        result = config_manager.resolve_calculate_settings(
            ["keep_existing_payments=true"]
        )

        assert result.keep_existing_payments is False

    def test_invalid_calculate_override_raises_clear_error(self, tmp_path):
        """Test that invalid calculate overrides fail during model resolution."""
        config_path = self._write_config(tmp_path, "")
        config_manager = ConfigManager(config_file_path=str(config_path))

        with pytest.raises(ValueError, match="calculate configuration settings"):
            config_manager.resolve_calculate_settings(
                ["calculate.keep_existing_payments=not-a-bool"]
            )

    def test_account_settings_apply_overrides_before_flattening(self, tmp_path):
        """Test that top-level overrides affect inherited account settings without leaking nested keys."""
        config_path = self._write_config(
            tmp_path,
            """
[general]
full_name = "Ada Lovelace"
language = "de"

[brokers.schwab.accounts.main]
account_number = "CH123"
""".strip(),
        )
        config_manager = ConfigManager(config_file_path=str(config_path))

        result = config_manager.get_account_settings(
            "schwab",
            "main",
            overrides=["general.language=fr"],
        )

        assert result.settings.language == "fr"
        assert result.settings.model_extra == {} or "general" not in result.settings.model_extra

