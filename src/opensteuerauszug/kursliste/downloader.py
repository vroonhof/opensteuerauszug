import logging
import requests
import zipfile
import tempfile
import shutil
from pathlib import Path, PurePosixPath
from typing import Dict, Any

logger = logging.getLogger(__name__)

API_URL = "https://www.ictax.admin.ch/extern/api/xml/xmls.json"
SESSION_URL = "https://www.ictax.admin.ch/extern/api/authentication/session.json"
DOWNLOAD_BASE_URL = "https://www.ictax.admin.ch/extern/api/download"
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
EXTRACTION_CHUNK_SIZE = 128 * 1024


def _initialize_session(session: requests.Session) -> None:
    logger.info("Initializing session...")
    try:
        session_response = session.get(SESSION_URL, timeout=10)
        session_response.raise_for_status()
        session_data = session_response.json()

        csrf_token = session_data.get("data", {}).get("csrfToken")
        if csrf_token:
            logger.debug(f"Acquired CSRF token: {csrf_token[:10]}...")
            session.headers.update({"X-CSRF-TOKEN": csrf_token})
    except Exception as e:
        logger.warning(f"Session initialization failed: {e}")


def get_latest_initial_export(
    year: int, session: requests.Session | None = None
) -> Dict[str, Any]:
    own_session = session is None
    session = session or requests.Session()
    if own_session:
        _initialize_session(session)

    logger.info(f"Fetching Kursliste metadata for year {year}...")

    payload = {"from": 0, "size": 100, "sort": [], "year": year}
    response = session.post(API_URL, json=payload, timeout=30)
    if response.status_code == 403:
        logger.error(
            "403 Forbidden: The API rejected the request. "
            f"Content: {response.text[:200]}"
        )
    response.raise_for_status()

    result = response.json()
    if result.get("status") != "SUCCESS":
        raise RuntimeError(f"API returned error: {result.get('error')}")

    data = result.get("data", [])
    if not data:
        raise ValueError(f"No Kursliste data found for year {year}")

    initial_exports = [
        item
        for item in data
        if item.get("exportType", {}).get("shortName", "").startswith("THIRD.INIT.")
    ]

    if not initial_exports:
        raise ValueError(f"No 'Initial' Kursliste export found for year {year}")

    def get_version(item: Dict[str, Any]) -> int:
        short_name = item.get("exportType", {}).get("shortName", "")
        try:
            return int(short_name.split(".")[-1])
        except (ValueError, IndexError):
            return -1

    latest_version = max(get_version(item) for item in initial_exports)
    candidates = [item for item in initial_exports if get_version(item) == latest_version]
    candidates.sort(key=lambda x: x.get("exportDate", 0), reverse=True)
    selected = candidates[0]

    export_file = selected.get("exportFile") or {}
    file_id = export_file.get("id")
    file_hash = export_file.get("fileHash")
    file_name = export_file.get("fileName")

    if not all([file_id, file_hash, file_name]):
        raise ValueError(
            "Incomplete export file information: "
            f"id={file_id}, hash={file_hash}, name={file_name}"
        )

    return {
        "file_id": file_id,
        "file_hash": file_hash,
        "file_name": file_name,
        "export_type_short_name": selected.get("exportType", {}).get("shortName"),
    }


def download_kursliste(
    year: int, destination_dir: Path, export_info: Dict[str, Any] | None = None
) -> Path:
    """
    Downloads the Kursliste for the given year from the ICTax website.

    Args:
        year: The tax year to download.
        destination_dir: The directory where the XML file should be stored.

    Returns:
        Path to the downloaded XML file.
    """
    session = requests.Session()
    _initialize_session(session)
    export_info = export_info or get_latest_initial_export(year, session=session)
    file_id = export_info["file_id"]
    file_hash = export_info["file_hash"]
    file_name = export_info["file_name"]

    download_url = f"{DOWNLOAD_BASE_URL}/{file_id}/{file_hash}/{file_name}"

    logger.info(f"Downloading Kursliste from {download_url}...")
    dl_response = session.get(download_url, timeout=60, stream=True)
    dl_response.raise_for_status()
    with tempfile.TemporaryFile(suffix=".zip") as tmp_zip:
        # Stream download into temp file
        for chunk in dl_response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
            if chunk:
                tmp_zip.write(chunk)

        tmp_zip.seek(0)

        with zipfile.ZipFile(tmp_zip) as z:
            target_xml = None
            first_xml = None

            for name in z.namelist():
                if not name.endswith(".xml"):
                    continue

                if first_xml is None:
                    first_xml = name

                entry_name = PurePosixPath(name).name
                if entry_name == f"kursliste_{year}.xml":
                    target_xml = name
                    break

            if first_xml is None:
                raise ValueError("No XML file found in the downloaded zip archive")

            target_xml = target_xml or first_xml

            logger.info(f"Extracting {target_xml}...")
            destination_dir.mkdir(parents=True, exist_ok=True)

            target_path = destination_dir / f"kursliste_{year}.xml"

            with z.open(target_xml) as source, open(target_path, "wb") as dest:
                shutil.copyfileobj(source, dest, length=EXTRACTION_CHUNK_SIZE)

    logger.info(f"Successfully downloaded and saved Kursliste to {target_path}")
    return target_path
