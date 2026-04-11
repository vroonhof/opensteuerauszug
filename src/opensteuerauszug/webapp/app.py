import importlib
import logging
import os
import tempfile
import types
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, send_file
from flask.typing import ResponseReturnValue
from werkzeug.utils import secure_filename
from pypdf import PdfReader

from opensteuerauszug.config.paths import resolve_kursliste_dir
from opensteuerauszug.kursliste.converter import convert_kursliste_xml_to_sqlite, read_kursliste_metadata, \
    CONVERTER_SCHEMA_VERSION, read_metadata_value
from opensteuerauszug.kursliste.downloader import get_latest_initial_export, download_kursliste
from opensteuerauszug.model.kursliste import KurslisteMetadata
from opensteuerauszug.steuerauszug import (
    ImporterType,
    LogLevel,
    TaxCalculationLevel,
    process,
    UseBrokerWithholding,
)

app = Flask(__name__, template_folder=Path(__file__).parent)

ALLOWED_LANGUAGES = ["de", "en", "fr", "it"]
MAX_UPLOAD_FILE_SIZE_MB = 5

logger = logging.getLogger(__name__)

last_year = datetime.now().year - 1
allowed_years = [last_year - i for i in range(4)]


def extract_error_message(exc: Exception) -> str:
    """Extract a user-friendly error message from an exception.

    Prefers direct message content over exception type, strips unnecessary
    stack trace context, and provides actionable guidance.
    """
    seen: set[int] = set()
    current: Exception | None = exc

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        exc_str = str(current).strip()
        if exc_str:
            if exc_str.startswith("("):
                exc_str = exc_str.lstrip("(").rstrip(")")
            return exc_str
        current = current.__cause__ or current.__context__

    return type(exc).__name__


def validate_xml_content(file_content: bytes) -> tuple[bool, str]:
    """Validate that uploaded content is valid XML. Returns (is_valid, error_message)."""
    try:
        secure_et = importlib.import_module("defusedxml.ElementTree")
    except ModuleNotFoundError:
        return False, "Secure XML parser is unavailable. Install defusedxml."

    try:
        secure_et.fromstring(file_content)
        return True, ""
    except ET.ParseError as e:
        return False, f"Invalid XML: {str(e)}"
    except Exception as e:
        return False, f"Error parsing XML: {str(e)}"


def validate_upload_filename(filename: str, allowed_extension: str) -> tuple[bool, str]:
    """Validate and sanitize the uploaded filename metadata."""
    sanitized = secure_filename(filename or "")
    if not sanitized:
        return False, "Invalid upload filename."
    if not sanitized.lower().endswith(allowed_extension):
        return False, f"Uploaded file must have {allowed_extension} extension."
    return True, sanitized


def validate_pdf_content(file_content: bytes) -> tuple[bool, str]:
    """Validate that uploaded content is a valid PDF. Returns (is_valid, error_message)."""
    try:
        # Try to create a PdfReader to validate the PDF
        from io import BytesIO
        PdfReader(BytesIO(file_content))
        return True, ""
    except Exception as e:
        return False, f"Invalid PDF: {str(e)}"


def render_form(error: str | None = None) -> str:
    """Render the form template with given error message."""
    return render_template(
        "template.html",
        error=error,
        years=allowed_years,
        languages=ALLOWED_LANGUAGES,
    )


def ensure_up_to_date_kursliste_available(year: int, destination_dir: Path) -> None:
    """Ensures that the Kursliste for the given year is available in the destination directory.
    If not present or outdated, downloads and converts the latest version.
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = destination_dir / f"kursliste_{year}.sqlite"

    latest_export = get_latest_initial_export(year)
    latest_kursliste_metadata = KurslisteMetadata(
        newest_file_hash=latest_export["file_hash"],
        file_id=latest_export["file_id"],
        file_name=latest_export["file_name"],
        export_type_short_name=latest_export.get("export_type_short_name"),
    )

    if sqlite_path.exists():
        metadata = read_kursliste_metadata(sqlite_path)
        converter_schema_version = read_metadata_value(
            sqlite_path, "converter_schema_version"
        )
        if (
                metadata is not None
                and metadata.newest_file_hash == latest_kursliste_metadata.newest_file_hash
                and converter_schema_version == CONVERTER_SCHEMA_VERSION
        ):
            logger.info(f"Kursliste for {year} is already up-to-date "
                        f"(archive hash {latest_kursliste_metadata.newest_file_hash}). "
                        "Skipping download and conversion.")
            return

    # Download and convert
    xml_path = download_kursliste(year, destination_dir, export_info=latest_export)
    logger.info(f"Successfully downloaded Kursliste for {year} to {xml_path}")
    # Remove existing SQLite if exists
    if sqlite_path.exists():
        os.remove(sqlite_path)
    # Convert
    convert_kursliste_xml_to_sqlite(
        xml_path, sqlite_path, kursliste_metadata=latest_kursliste_metadata
    )
    logger.info(f"Successfully converted to {sqlite_path}")


def validate_and_read_uploaded_file(field_name: str, allowed_extension: str, content_validator: callable,
                                    required: bool = False, missing_error_message: str | None = None) -> tuple[
    bytes | None, str | None]:
    """Validate and read an uploaded file. Returns (file_content, error_message)."""
    upload = request.files.get(field_name)
    if not upload or not upload.filename:
        if required:
            error = missing_error_message or f"Please select a {field_name.replace('_', ' ')} file."
            return None, error
        return None, None  # No file uploaded, which is OK for optional fields

    filename_ok, filename_msg = validate_upload_filename(upload.filename, allowed_extension)
    if not filename_ok:
        return None, f"{field_name.replace('_', ' ').title()}: {filename_msg}"

    # Validate file size
    upload.seek(0, 2)
    file_size = upload.tell()
    upload.seek(0)

    if file_size > MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024:
        return None, f"{field_name.replace('_', ' ').title()} file exceeds maximum size of {MAX_UPLOAD_FILE_SIZE_MB}MB."

    file_content = upload.read()

    # Validate content
    is_valid, error_msg = content_validator(file_content)
    if not is_valid:
        return None, f"{field_name.replace('_', ' ').title()} file validation failed: {error_msg}"

    return file_content, None


def save_file_to_temp_dir(file_content: bytes, filename: str, tmpdir_path: Path) -> Path:
    """Save file content to a temporary file and return the path."""
    file_path = tmpdir_path / filename
    try:
        file_path.write_bytes(file_content)
    except (IOError, OSError) as e:
        raise ValueError(f"Failed to save {filename}: {e}")
    return file_path


def render_form_error(error: str, status_code: int = 400) -> tuple[str, int]:
    """Render form with an error and explicit non-success status code."""
    return render_form(error=error), status_code


@app.get("/")
def index() -> str:
    return render_form()


@app.post("/generate")
def generate() -> ResponseReturnValue:
    # Validate and parse tax year
    try:
        tax_year = int(request.form.get("tax_year", ""))
    except (ValueError, TypeError):
        return render_form_error("Invalid tax year format. Please select a valid year.")

    if tax_year not in allowed_years:
        return render_form_error(f"Tax year {tax_year} is not supported.")

    # Validate language
    language = request.form.get("language", "").strip()
    if language not in ALLOWED_LANGUAGES:
        return render_form_error("Invalid language selected.")

    # Ensure kursliste is available
    kursliste_dir = resolve_kursliste_dir()
    try:
        ensure_up_to_date_kursliste_available(tax_year, kursliste_dir)
    except Exception:
        logger.exception(f"Failed to ensure kursliste for year {tax_year}")

    xml_file_content, error_msg = validate_and_read_uploaded_file("xml_file", ".xml", validate_xml_content,
                                                                  required=True,
                                                                  missing_error_message="Please select an IBKR XML file.")
    if error_msg:
        return render_form_error(error_msg)

    # Handle optional files
    corrections_file_content, error_msg = validate_and_read_uploaded_file("corrections_flex", ".xml",
                                                                          validate_xml_content)
    if error_msg:
        return render_form_error(error_msg)

    pre_amble_file_content, error_msg = validate_and_read_uploaded_file("pre_amble", ".pdf", validate_pdf_content)
    if error_msg:
        return render_form_error(error_msg)

    post_amble_file_content, error_msg = validate_and_read_uploaded_file("post_amble", ".pdf", validate_pdf_content)
    if error_msg:
        return render_form_error(error_msg)

    # At this point, all files are validated and read
    tmpdir_ctx = tempfile.TemporaryDirectory()
    tmpdir = tmpdir_ctx.name
    response_sent = False

    try:
        tmpdir_path = Path(tmpdir)
        input_path = tmpdir_path / "upload.xml"
        output_path = tmpdir_path / "steuerauszug.pdf"

        try:
            input_path.write_bytes(xml_file_content)
        except (IOError, OSError) as e:
            return render_form_error(f"Failed to save uploaded file: {e}", status_code=500)

        corrections_flex_paths = None
        if corrections_file_content:
            corrections_path = save_file_to_temp_dir(corrections_file_content, "corrections.xml", tmpdir_path)
            corrections_flex_paths = [corrections_path]

        pre_amble_paths = None
        if pre_amble_file_content:
            pre_amble_path = save_file_to_temp_dir(pre_amble_file_content, "pre_amble.pdf", tmpdir_path)
            pre_amble_paths = [pre_amble_path]

        post_amble_paths = None
        if post_amble_file_content:
            post_amble_path = save_file_to_temp_dir(post_amble_file_content, "post_amble.pdf", tmpdir_path)
            post_amble_paths = [post_amble_path]

        # Proceed with processing using the saved file paths

        period_from = f"{tax_year}-01-01"
        period_to = f"{tax_year}-12-31"

        try:
            process(
                ctx=types.SimpleNamespace(info_name="generate"),
                run_phases_input=None,
                debug_dump_path=None,
                final_xml_path=None,
                identifiers_csv_path_opt=None,
                config_file=None,
                broker_name=None,
                kursliste_dir=kursliste_dir,
                org_nr=None,
                corrections_flex=corrections_flex_paths,
                use_broker_withholding=UseBrokerWithholding.CAP,
                pre_amble=pre_amble_paths,
                post_amble=post_amble_paths,
                strict_consistency_flag=True,
                filter_to_period_flag=True,
                payment_reconciliation=True,
                log_level=LogLevel.INFO,
                tax_calculation_level=TaxCalculationLevel.KURSLISTE,
                input_file=input_path,
                output_file=output_path,
                raw_import=False,
                importer_type=ImporterType.IBKR,
                period_from_str=period_from,
                period_to_str=period_to,
                tax_year=tax_year,
                override_configs=[f"general.language={language}"],
            )
        except SystemExit as exc:
            exit_code = getattr(exc, "code", 1)
            if exit_code not in (0, None):
                return render_form_error(
                    error=(
                        f"PDF generation failed (exit code {exit_code}). "
                        "Please verify your XML file format and tax year are correct."
                    ),
                    status_code=400,
                )
            # Exit code 0 or None means success, continue to check for output file
        except Exception as exc:
            error_msg = extract_error_message(exc)
            logger.exception("Processing failed")
            return render_form_error(error_msg, status_code=400)

        if not output_path.exists():
            return render_form_error("Processing completed without producing a PDF.", status_code=500)

        response = send_file(
            output_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"steuerauszug_{tax_year}.pdf",
        )
        # Register cleanup callback - will execute after response is sent
        response.call_on_close(tmpdir_ctx.cleanup)
        response_sent = True
        return response

    except Exception as exc:
        logger.exception("Unexpected error in generate endpoint")
        error_msg = extract_error_message(exc)
        return render_form_error(error_msg, status_code=500)
    finally:
        if not response_sent:
            tmpdir_ctx.cleanup()


@app.get("/health")
def health() -> str:
    return "OK"


if __name__ == "__main__":
    app.run()
