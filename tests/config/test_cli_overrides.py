"""Tests for CLI configuration overrides."""
from opensteuerauszug.config.loader import ConfigManager


class TestCliOverrides:
    """Tests for the _apply_cli_overrides method."""

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

