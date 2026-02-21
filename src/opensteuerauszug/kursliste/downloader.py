import logging
import requests
import zipfile
import io
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

API_URL = "https://www.ictax.admin.ch/extern/api/xml/xmls.json"
SESSION_URL = "https://www.ictax.admin.ch/extern/api/authentication/session.json"
HOME_URL = "https://www.ictax.admin.ch/extern/en.html"
DOWNLOAD_BASE_URL = "https://www.ictax.admin.ch/extern/api/download"

# Standard headers to avoid 403
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.ictax.admin.ch",
    "Referer": HOME_URL
}

def download_kursliste(year: int, destination_dir: Path) -> Path:
    """
    Downloads the Kursliste for the given year from ICTax API.

    Args:
        year: The tax year to download.
        destination_dir: The directory where the XML file should be stored.

    Returns:
        Path to the downloaded XML file.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    # First, hit the home page and the session endpoint to get cookies and CSRF token
    logger.info("Initializing session...")
    try:
        session.get(HOME_URL, timeout=10)
        session_response = session.get(SESSION_URL, timeout=10)
        session_response.raise_for_status()
        session_data = session_response.json()

        csrf_token = session_data.get("data", {}).get("csrfToken")
        if csrf_token:
            logger.debug(f"Acquired CSRF token: {csrf_token[:10]}...")
            session.headers.update({"X-CSRF-TOKEN": csrf_token})
    except Exception as e:
        logger.warning(f"Session initialization failed: {e}")

    logger.info(f"Fetching Kursliste metadata for year {year}...")

    payload = {
        "from": 0,
        "size": 100,
        "sort": [],
        "year": year
    }

    response = session.post(API_URL, json=payload, timeout=30)
    if response.status_code == 403:
        logger.error(f"403 Forbidden: The API rejected the request. Content: {response.text[:200]}")
    response.raise_for_status()

    result = response.json()
    if result.get("status") != "SUCCESS":
        raise RuntimeError(f"API returned error: {result.get('error')}")

    data = result.get("data", [])
    if not data:
        raise ValueError(f"No Kursliste data found for year {year}")

    # Filter for Initial exports
    initial_exports = [
        item for item in data
        if item.get("exportType", {}).get("shortName", "").startswith("THIRD.INIT.")
    ]

    if not initial_exports:
        raise ValueError(f"No 'Initial' Kursliste export found for year {year}")

    # Find the latest format (highest version suffix)
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

    export_file = selected.get("exportFile")
    if not export_file:
        raise ValueError(f"No export file information found for the selected export")

    file_id = export_file.get("id")
    file_hash = export_file.get("fileHash")
    file_name = export_file.get("fileName")

    if not all([file_id, file_hash, file_name]):
        raise ValueError(f"Incomplete export file information: id={file_id}, hash={file_hash}, name={file_name}")

    download_url = f"{DOWNLOAD_BASE_URL}/{file_id}/{file_hash}/{file_name}"

    logger.info(f"Downloading Kursliste from {download_url}...")
    dl_response = session.get(download_url, timeout=60)
    dl_response.raise_for_status()

    # Extract zip
    with zipfile.ZipFile(io.BytesIO(dl_response.content)) as z:
        xml_files = [name for name in z.namelist() if name.endswith(".xml")]
        if not xml_files:
            raise ValueError("No XML file found in the downloaded zip archive")

        target_xml = None
        for name in xml_files:
            if f"kursliste_{year}" in name:
                target_xml = name
                break
        if not target_xml:
            target_xml = xml_files[0]

        logger.info(f"Extracting {target_xml}...")
        destination_dir.mkdir(parents=True, exist_ok=True)

        target_path = destination_dir / f"kursliste_{year}.xml"

        with z.open(target_xml) as source_file, open(target_path, "wb") as dest_file:
            dest_file.write(source_file.read())

    logger.info(f"Successfully downloaded and saved Kursliste to {target_path}")
    return target_path
