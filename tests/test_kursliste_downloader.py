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

    # Mock responses for GET calls:
    # 1. HOME_URL
    # 2. SESSION_URL
    # 3. Download URL
    mock_home_resp = MagicMock(status_code=200)
    mock_session_resp = MagicMock(status_code=200)
    mock_session_resp.json.return_value = {
        "status": "SUCCESS",
        "data": {"csrfToken": "test-csrf-token"}
    }
    mock_dl_resp = MagicMock(status_code=200, content=b"zip_content")

    mock_get.side_effect = [mock_home_resp, mock_session_resp, mock_dl_resp]

    # Mock zip extraction
    mock_zip_instance = mock_zip.return_value.__enter__.return_value
    mock_zip_instance.namelist.return_value = ["kursliste_2025.xml"]

    # Mock z.open
    mock_xml_content = io.BytesIO(b"xml_content")
    mock_zip_instance.open.return_value.__enter__.return_value = mock_xml_content

    download_kursliste(2025, tmp_path)

    # Verify metadata call
    assert mock_post.call_count == 1
    # Check if CSRF token was added to session headers for the POST call
    # Note: downloader.py updates session.headers directly.
    # We can check the mock_post call headers if we really wanted,
    # but requests.Session.post uses session.headers by default.

    # Verify that THIRD.INIT.220 was selected (highest version)
    download_call = mock_get.call_args_list[2]
    assert download_call[0][0] == "https://www.ictax.admin.ch/extern/api/download/3586267/21f330db01497a390e5aa71cd5e3e21a/kursliste_2025.zip"

    # Verify that we tried to write the file
    mock_open.assert_called_with(tmp_path / "kursliste_2025.xml", "wb")
