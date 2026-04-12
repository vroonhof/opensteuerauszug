import typer
import logging
import os
from pathlib import Path
from typing import Optional
from .downloader import download_kursliste, get_latest_initial_export
from opensteuerauszug.config.paths import resolve_kursliste_dir, get_app_data_dir
from opensteuerauszug.model.kursliste import KurslisteMetadata
from .converter import (
    CONVERTER_SCHEMA_VERSION,
    convert_kursliste_xml_to_sqlite,
    read_kursliste_metadata,
    read_metadata_value,
)

app = typer.Typer(help="Manage Kursliste files.")

@app.callback()
def main():
    """
    Manage Kursliste files.
    """
    pass

@app.command()
def download(
    year: int = typer.Option(..., "--year", help="Tax year to download Kursliste for."),
    destination: Optional[Path] = typer.Option(None, "--destination", "-d", help="Directory to save the Kursliste XML file. Defaults to XDG data home."),
    convert: bool = typer.Option(True, "--convert/--no-convert", help="Automatically convert the downloaded XML to SQLite for faster processing.")
):
    """
    Downloads and prepares the Kursliste XML file for a given year.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if destination:
            effective_destination = resolve_kursliste_dir(destination)
        else:
            effective_destination = get_app_data_dir() / "kursliste"

        if not effective_destination.exists():
            effective_destination.mkdir(parents=True, exist_ok=True)

        latest_export = get_latest_initial_export(year)
        latest_kursliste_metadata = KurslisteMetadata(
            newest_file_hash=latest_export["file_hash"],
            file_id=latest_export["file_id"],
            file_name=latest_export["file_name"],
            export_type_short_name=latest_export.get("export_type_short_name"),
        )
        sqlite_path = effective_destination / f"kursliste_{year}.sqlite"

        if convert and sqlite_path.exists():
            metadata = read_kursliste_metadata(sqlite_path)
            converter_schema_version = read_metadata_value(
                sqlite_path, "converter_schema_version"
            )
            if (
                metadata is not None
                and metadata.newest_file_hash == latest_kursliste_metadata.newest_file_hash
                and converter_schema_version == CONVERTER_SCHEMA_VERSION
            ):
                logging.info(f"Kursliste for {year} is already up-to-date "
                    f"(archive hash {latest_kursliste_metadata.newest_file_hash}). "
                    "Skipping download and conversion.")
                return

        xml_path = download_kursliste(year, effective_destination, export_info=latest_export)
        logging.info(f"Successfully downloaded Kursliste for {year} to {xml_path}")

        if convert:
            logging.info(f"Converting {xml_path.name} to {sqlite_path.name}...")
            try:
                if sqlite_path.exists():
                    os.remove(sqlite_path)
                convert_kursliste_xml_to_sqlite(
                    xml_path, sqlite_path, kursliste_metadata=latest_kursliste_metadata
                )
                logging.info(f"Successfully converted to {sqlite_path}")
            except Exception as ce:
                logging.error(f"Failed to convert Kursliste to SQLite: {ce}")

    except Exception as e:
        logging.error(f"Error downloading Kursliste: {e}")
        raise typer.Exit(code=1)

@app.command()
def convert(
    input_xml: Path = typer.Argument(..., exists=True, dir_okay=False, help="Input Kursliste XML file."),
    output_sqlite: Optional[Path] = typer.Option(None, "--output", "-o", help="Output SQLite file. Defaults to input filename with .sqlite extension.")
):
    """
    Convert a Kursliste XML file to SQLite format.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if output_sqlite is None:
        output_sqlite = input_xml.with_suffix(".sqlite")

    try:
        logging.info(f"Converting {input_xml} to {output_sqlite}...")
        convert_kursliste_xml_to_sqlite(input_xml, output_sqlite)
        logging.info(f"Successfully converted to {output_sqlite}")
    except Exception as e:
        logging.error(f"Error converting Kursliste: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
