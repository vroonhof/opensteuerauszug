import typer
import logging
from pathlib import Path
from typing import Optional
from .downloader import download_kursliste
from ..config.paths import resolve_kursliste_dir, get_app_data_dir
from .converter import convert_kursliste_xml_to_sqlite

app = typer.Typer(help="Manage Kursliste files.")

@app.callback()
def main():
    """
    Manage Kursliste files.
    """
    pass

@app.command()
def fetch(
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

        xml_path = download_kursliste(year, effective_destination)
        print(f"Successfully downloaded Kursliste for {year} to {xml_path}")

        if convert:
            sqlite_path = xml_path.with_suffix(".sqlite")
            print(f"Converting {xml_path.name} to {sqlite_path.name}...")
            try:
                convert_kursliste_xml_to_sqlite(xml_path, sqlite_path)
                print(f"Successfully converted to {sqlite_path}")
            except Exception as ce:
                print(f"Warning: Failed to convert Kursliste to SQLite: {ce}")

    except Exception as e:
        print(f"Error downloading Kursliste: {e}")
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
        print(f"Converting {input_xml} to {output_sqlite}...")
        convert_kursliste_xml_to_sqlite(input_xml, output_sqlite)
        print(f"Successfully converted to {output_sqlite}")
    except Exception as e:
        print(f"Error converting Kursliste: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
