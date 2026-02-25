import typer
import logging
from pathlib import Path
from .downloader import download_kursliste

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
    destination: Path = typer.Option(Path("data/kursliste"), "--destination", "-d", help="Directory to save the Kursliste XML file.")
):
    """
    Downloads and prepares the Kursliste XML file for a given year.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        xml_path = download_kursliste(year, destination)
        print(f"Successfully downloaded Kursliste for {year} to {xml_path}")
    except Exception as e:
        print(f"Error downloading Kursliste: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
