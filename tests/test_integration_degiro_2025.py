"""End-to-end test for the DEGIRO importer with cash in more than one currency.

The sample directory is a reduced real-world DEGIRO export (account language
German) reported in
https://github.com/vroonhof/opensteuerauszug/pull/420#issuecomment-5554145930:
its ``Portfolio.csv`` holds a ``CASH & CASH FUND & FTX CASH`` row per currency.
Before the fix the importer kept only the last cash row, so the CHF balance was
silently dropped from the statement.
"""

from pathlib import Path

import lxml.etree as ET
from typer.testing import CliRunner

from opensteuerauszug.steuerauszug import app

runner = CliRunner()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = PROJECT_ROOT / "tests" / "samples" / "import" / "degiro" / "de_multi_currency_cash"

CONFIG_TOML = """
[general]
full_name = "Max Muster"
canton = "ZH"

[brokers.degiro.accounts.main]
kind = "degiro"
account_number = "12345678"
"""


class _LocalXsdResolver(ET.Resolver):
    def __init__(self, specs_dir: Path) -> None:
        super().__init__()
        self._specs_dir = specs_dir

    def resolve(self, url, pubid, context):
        if not url:
            return None
        basename = url.rsplit("/", 1)[-1]
        candidate = self._specs_dir / basename
        if candidate.exists():
            return self.resolve_filename(str(candidate), context)
        return None


def _ech(tag: str) -> str:
    return f"{{http://www.ech.ch/xmlns/eCH-0196/2}}{tag}"


def test_degiro_export_with_two_cash_currencies_reports_both_bank_accounts(tmp_path: Path):
    """Every cash currency of the DEGIRO export reaches the rendered statement."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG_TOML, encoding="utf-8")
    output_pdf = tmp_path / "degiro_2025.pdf"
    output_xml = tmp_path / "degiro_2025.xml"

    result = runner.invoke(
        app,
        [
            "process",
            str(SAMPLE_DIR),
            "--importer",
            "degiro",
            "--tax-year",
            "2025",
            "--config",
            str(config_path),
            "--kursliste-dir",
            str(PROJECT_ROOT / "tests" / "samples" / "kursliste"),
            "--output",
            str(output_pdf),
            "--xml-output",
            str(output_xml),
        ],
    )

    assert result.exit_code == 0, f"CLI execution failed with stdout:\n{result.stdout}"
    assert "Degiro import complete." in result.stdout
    assert "Processing finished successfully." in result.stdout
    assert output_pdf.exists() and output_pdf.stat().st_size > 0
    assert output_xml.exists()

    # Validate against the eCH-0196-2-2 XSD: one bank account per currency has
    # to stay schema-valid, not just model-valid.
    specs_dir = PROJECT_ROOT / "specs"
    xsd_parser = ET.XMLParser()
    xsd_parser.resolvers.add(_LocalXsdResolver(specs_dir))
    schema = ET.XMLSchema(ET.parse(str(specs_dir / "eCH-0196-2-2.xsd"), parser=xsd_parser))
    xml_doc = ET.parse(str(output_xml))
    assert schema.validate(xml_doc), f"XSD validation failed:\n{schema.error_log}"

    accounts = xml_doc.getroot().findall(f".//{_ech('bankAccount')}")
    balances = {}
    for account in accounts:
        tax_value = account.find(_ech("taxValue"))
        assert tax_value is not None
        balances[account.get("bankAccountCurrency")] = tax_value.get("balance")

    # Portfolio.csv lists CHF 500.00 and USD 200.00; the CHF row used to be
    # overwritten by the USD one.
    assert balances == {"CHF": "500", "USD": "200"}
    # Each currency gets its own account, keyed off the configured depot number.
    assert {account.get("bankAccountNumber") for account in accounts} == {
        "12345678-CHF",
        "12345678-USD",
    }

    # Both balances are converted and add up in the statement total (USD 200 at
    # the mini Kursliste year-end rate of 0.79225 is CHF 158.45).
    assert xml_doc.getroot().get("totalTaxValue") == "658.45"
