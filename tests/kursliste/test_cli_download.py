from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from opensteuerauszug.kursliste.__main__ import app
from pathlib import Path

runner = CliRunner()

def test_download_with_convert():
    with patch("opensteuerauszug.kursliste.__main__.download_kursliste") as mock_download, \
         patch("opensteuerauszug.kursliste.__main__.convert_kursliste_xml_to_sqlite") as mock_convert, \
         patch("pathlib.Path.exists") as mock_exists, \
         patch("pathlib.Path.mkdir") as mock_mkdir:

        mock_download.return_value = Path("/tmp/kursliste_2023.xml")
        mock_exists.return_value = True

        result = runner.invoke(app, ["fetch", "--year", "2023"])

        assert result.exit_code == 0
        mock_download.assert_called_once()
        mock_convert.assert_called_once_with(Path("/tmp/kursliste_2023.xml"), Path("/tmp/kursliste_2023.sqlite"))

def test_download_no_convert():
    with patch("opensteuerauszug.kursliste.__main__.download_kursliste") as mock_download, \
         patch("opensteuerauszug.kursliste.__main__.convert_kursliste_xml_to_sqlite") as mock_convert, \
         patch("pathlib.Path.exists") as mock_exists, \
         patch("pathlib.Path.mkdir") as mock_mkdir:

        mock_download.return_value = Path("/tmp/kursliste_2023.xml")
        mock_exists.return_value = True

        result = runner.invoke(app, ["fetch", "--year", "2023", "--no-convert"])

        assert result.exit_code == 0
        mock_download.assert_called_once()
        mock_convert.assert_not_called()
