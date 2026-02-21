import pytest
import io
from pathlib import Path
from unittest.mock import MagicMock, patch
from opensteuerauszug.kursliste.downloader import download_kursliste

@pytest.fixture
def mock_response():
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "status": "SUCCESS",
        "data": [
            {
                "id": 42519,
                "exportDate": 1771617701000,
                "exportFile": {
                    "id": 3586307,
                    "fileName": "kursliste_2025.zip",
                    "fileHash": "549f00e9a0737da2f65559bf774e7fdd"
                },
                "exportType": {
                    "shortName": "THIRD.INIT.120"
                }
            },
            {
                "id": 42515,
                "exportDate": 1771616371000,
                "exportFile": {
                    "id": 3586289,
                    "fileName": "kursliste_2025.zip",
                    "fileHash": "258094db8756eb413f762048fdca23fb"
                },
                "exportType": {
                    "shortName": "THIRD.INIT.200"
                }
            },
            {
                "id": 42511,
                "exportDate": 1771615102000,
                "exportFile": {
                    "id": 3586267,
                    "fileName": "kursliste_2025.zip",
                    "fileHash": "21f330db01497a390e5aa71cd5e3e21a"
                },
                "exportType": {
                    "shortName": "THIRD.INIT.220"
                }
            }
        ]
    }
    return mock

@patch("requests.Session.post")
@patch("requests.Session.get")
@patch("zipfile.ZipFile")
@patch("builtins.open")
def test_download_kursliste_logic(mock_open, mock_zip, mock_get, mock_post, mock_response, tmp_path):
    mock_post.return_value = mock_response

    # Mock the home page and API pre-flight calls
    mock_preflight = MagicMock()
    mock_preflight.status_code = 200
    mock_get.side_effect = [mock_preflight, mock_preflight, MagicMock(status_code=200, content=b"zip_content")]

    # Mock zip extraction
    mock_zip_instance = mock_zip.return_value.__enter__.return_value
    mock_zip_instance.namelist.return_value = ["kursliste_2025.xml"]

    # Mock z.open
    mock_xml_content = io.BytesIO(b"xml_content")
    mock_zip_instance.open.return_value.__enter__.return_value = mock_xml_content

    download_kursliste(2025, tmp_path)

    # Verify that THIRD.INIT.220 was selected (highest version)
    # The third call to get should be the download URL
    download_call = mock_get.call_args_list[2]
    assert download_call[0][0] == "https://www.ictax.admin.ch/extern/api/download/3586267/21f330db01497a390e5aa71cd5e3e21a/kursliste_2025.zip"

    # Verify that we tried to write the file
    mock_open.assert_called_with(tmp_path / "kursliste_2025.xml", "wb")
