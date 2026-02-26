import typer
import logging
from pathlib import Path
from typing import Optional
from .downloader import download_kursliste
from ..config.paths import resolve_kursliste_dir, get_app_data_dir

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
    destination: Optional[Path] = typer.Option(None, "--destination", "-d", help="Directory to save the Kursliste XML file. Defaults to XDG data home.")
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
    except Exception as e:
        print(f"Error downloading Kursliste: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
