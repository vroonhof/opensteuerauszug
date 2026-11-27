"""End-to-end tests for the Morgan Stanley (MSSB) importer through the CLI."""

import csv
from pathlib import Path

import lxml.etree as ET
from typer.testing import CliRunner

from opensteuerauszug.steuerauszug import app

runner = CliRunner()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_TOML = """
[general]
full_name = "Max Muster"
canton = "ZH"
experimental_importers = {experimental}

[brokers.mssb.accounts.main]
account_number = "MSSB-123"
"""


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


def _write_reports(directory: Path) -> None:
    _write_csv(
        directory / "Releases Report.csv",
        [
            [
                "Vest Date",
                "Order Number",
                "Plan",
                "Type",
                "Status",
                "Price",
                "Quantity",
                "Net Cash Proceeds",
                "Net Share Proceeds",
                "Tax Payment Method",
            ],
            [
                "25-Mar-2025",
                "R-1",
                "GSU Class C",
                "Release",
                "Complete",
                "$160.00",
                "20.000",
                "$0.00",
                "10.000",
                "Fractional Shares",
            ],
        ],
    )
    _write_csv(
        directory / "Withdrawals Report.csv",
        [
            [
                "Execution Date",
                "Order Number",
                "Plan",
                "Type",
                "Order Status",
                "Price",
                "Quantity",
                "Net Amount",
                "Net Share Proceeds",
                "Tax Payment Method",
            ],
            [
                "10-Jun-2025",
                "S-1",
                "GSU Class C",
                "Sale",
                "Complete",
                "$170.00",
                "-4",
                "$680.00",
                "0",
                "N/A",
            ],
        ],
    )


def _run(tmp_path: Path, experimental: bool):
    inputs = tmp_path / "mssb"
    inputs.mkdir()
    _write_reports(inputs)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        CONFIG_TOML.format(experimental="true" if experimental else "false"), encoding="utf-8"
    )
    output_xml = tmp_path / "mssb_2025.xml"
    result = runner.invoke(
        app,
        [
            "process",
            str(inputs),
            "--importer",
            "mssb",
            "--tax-year",
            "2025",
            "--config",
            str(config_path),
            "--kursliste-dir",
            str(PROJECT_ROOT / "tests" / "samples" / "kursliste"),
            "--output",
            str(tmp_path / "mssb_2025.pdf"),
            "--xml-output",
            str(output_xml),
        ],
    )
    return result, output_xml


def test_mssb_importer_requires_experimental_flag(tmp_path: Path):
    result, _ = _run(tmp_path, experimental=False)

    assert result.exit_code != 0
    assert "experimental" in result.output


def test_mssb_export_end_to_end(tmp_path: Path):
    result, output_xml = _run(tmp_path, experimental=True)

    assert result.exit_code == 0, f"CLI execution failed with stdout:\n{result.stdout}"
    assert "MSSB import complete." in result.stdout
    assert (tmp_path / "mssb_2025.pdf").stat().st_size > 0

    specs_dir = PROJECT_ROOT / "specs"

    class _LocalXsdResolver(ET.Resolver):
        def resolve(self, url, pubid, context):
            candidate = specs_dir / url.rsplit("/", 1)[-1] if url else None
            if candidate is not None and candidate.exists():
                return self.resolve_filename(str(candidate), context)
            return None

    xsd_parser = ET.XMLParser()
    xsd_parser.resolvers.add(_LocalXsdResolver())
    schema = ET.XMLSchema(ET.parse(str(specs_dir / "eCH-0196-2-2.xsd"), parser=xsd_parser))
    xml_doc = ET.parse(str(output_xml))
    assert schema.validate(xml_doc), f"XSD validation failed:\n{schema.error_log}"

    ns = "{http://www.ech.ch/xmlns/eCH-0196/2}"
    tax_value = xml_doc.getroot().find(f".//{ns}security/{ns}taxValue")
    assert tax_value is not None and tax_value.get("quantity") == "6"
    cash = xml_doc.getroot().find(f".//{ns}bankAccount/{ns}taxValue")
    assert cash is not None and cash.get("balance") == "680"
