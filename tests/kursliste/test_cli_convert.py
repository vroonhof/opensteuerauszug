from typer.testing import CliRunner
from opensteuerauszug.kursliste.__main__ import app
import sqlite3

runner = CliRunner()

def test_convert_cli_command(tmp_path):
    # Sample XML
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
<kursliste xmlns="http://xmlns.estv.admin.ch/ictax/2.0.0/kursliste" version="2.0.0.1" year="2023">
    <share id="101" quoted="true" source="KURSLISTE" securityGroup="SHARE" securityType="SHARE.COMMON"
           valorNumber="123456" isin="CH0012345678" securityName="Test Share AG"
           currency="CHF" nominalValue="10.00" country="CH"
           institutionId="999" institutionName="Test Bank Share">
        <yearend id="10101" quotationType="PIECE" taxValue="150.50" taxValueCHF="150.50" />
    </share>
</kursliste>
"""
    xml_file = tmp_path / "test.xml"
    xml_file.write_text(sample_xml)

    # 1. Test convert command
    result = runner.invoke(app, ["convert", str(xml_file)])
    assert result.exit_code == 0, result.stdout

    sqlite_file = tmp_path / "test.sqlite"
    assert sqlite_file.exists()

    # Verify content
    conn = sqlite3.connect(sqlite_file)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM securities")
    count = cursor.fetchone()[0]
    assert count == 1
    conn.close()

    # 2. Test with explicit output
    output_sqlite = tmp_path / "explicit.sqlite"
    result = runner.invoke(app, ["convert", str(xml_file), "--output", str(output_sqlite)])
    assert result.exit_code == 0
    assert output_sqlite.exists()
