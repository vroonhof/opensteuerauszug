import logging
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from opensteuerauszug.kursliste.__main__ import app
from opensteuerauszug.kursliste.converter import CONVERTER_SCHEMA_VERSION
from pathlib import Path

runner = CliRunner()

def test_download_with_convert():
    with patch("opensteuerauszug.kursliste.__main__.get_latest_initial_export") as mock_latest, \
         patch("opensteuerauszug.kursliste.__main__.download_kursliste") as mock_download, \
         patch("opensteuerauszug.kursliste.__main__.read_kursliste_metadata") as mock_metadata, \
         patch("opensteuerauszug.kursliste.__main__.read_metadata_value") as mock_metadata_value, \
         patch("opensteuerauszug.kursliste.__main__.convert_kursliste_xml_to_sqlite") as mock_convert, \
         patch("opensteuerauszug.kursliste.__main__.os.remove") as mock_remove, \
         patch("pathlib.Path.exists") as mock_exists, \
         patch("pathlib.Path.mkdir") as mock_mkdir:

        mock_latest.return_value = {"file_hash": "abc123", "file_id": 1, "file_name": "kursliste_2023.zip"}
        mock_download.return_value = Path("/tmp/kursliste_2023.xml")
        mock_metadata.return_value = None
        mock_metadata_value.return_value = None
        mock_exists.return_value = True

        result = runner.invoke(app, ["download", "--year", "2023"])

        assert result.exit_code == 0
        mock_download.assert_called_once()
        mock_convert.assert_called_once()
        convert_args, convert_kwargs = mock_convert.call_args
        assert convert_args[0] == Path("/tmp/kursliste_2023.xml")
        assert convert_kwargs["kursliste_metadata"].newest_file_hash == "abc123"

def test_download_no_convert():
    with patch("opensteuerauszug.kursliste.__main__.get_latest_initial_export") as mock_latest, \
         patch("opensteuerauszug.kursliste.__main__.download_kursliste") as mock_download, \
         patch("opensteuerauszug.kursliste.__main__.convert_kursliste_xml_to_sqlite") as mock_convert, \
         patch("opensteuerauszug.kursliste.__main__.os.remove") as mock_remove, \
         patch("pathlib.Path.exists") as mock_exists, \
         patch("pathlib.Path.mkdir") as mock_mkdir:

        mock_latest.return_value = {"file_hash": "abc123", "file_id": 1, "file_name": "kursliste_2023.zip"}
        mock_download.return_value = Path("/tmp/kursliste_2023.xml")
        mock_exists.return_value = True

        result = runner.invoke(app, ["download", "--year", "2023", "--no-convert"])

        assert result.exit_code == 0
        mock_download.assert_called_once()
        mock_convert.assert_not_called()


def test_download_skips_when_newest_file_hash_unchanged(caplog):
    with patch("opensteuerauszug.kursliste.__main__.get_latest_initial_export") as mock_latest, \
         patch("opensteuerauszug.kursliste.__main__.read_kursliste_metadata") as mock_metadata, \
         patch("opensteuerauszug.kursliste.__main__.read_metadata_value") as mock_metadata_value, \
         patch("opensteuerauszug.kursliste.__main__.download_kursliste") as mock_download, \
         patch("opensteuerauszug.kursliste.__main__.convert_kursliste_xml_to_sqlite") as mock_convert, \
         patch("opensteuerauszug.kursliste.__main__.os.remove") as mock_remove, \
         patch("pathlib.Path.exists") as mock_exists, \
         patch("pathlib.Path.mkdir") as mock_mkdir:

        mock_latest.return_value = {"file_hash": "samehash", "file_id": 1, "file_name": "kursliste_2023.zip"}
        mock_metadata.return_value = MagicMock(newest_file_hash="samehash")
        mock_metadata_value.return_value = CONVERTER_SCHEMA_VERSION
        mock_exists.return_value = True

        with caplog.at_level(logging.INFO):
            result = runner.invoke(app, ["download", "--year", "2023"])

        assert result.exit_code == 0
        assert any("already up-to-date" in record.message for record in caplog.records)
        mock_download.assert_not_called()
        mock_convert.assert_not_called()
