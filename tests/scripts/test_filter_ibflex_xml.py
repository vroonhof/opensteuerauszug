import subprocess
import sys
from pathlib import Path

import lxml.etree as ET


SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "filter_ibflex_xml.py"

SAMPLE_IBFLEX_XML = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<FlexQueryResponse queryName=\"Annual Tax Report\" type=\"AF\">
  <FlexStatements count=\"1\">
    <FlexStatement accountId=\"U1111111\" fromDate=\"2025-01-01\" toDate=\"2025-12-31\">
      <AccountInformation accountId=\"U1111111\" acctAlias=\"\" currency=\"CHF\" dateOpened=\"2020-01-01\" dateFunded=\"2020-01-15\" dateClosed=\"\" stateResidentialAddress=\"CH-ZH\" name=\"Jane Doe\" primaryEmail=\"jane@example.com\" street=\"Main St\" />
      <Trades>
        <Trade conid=\"1\" isin=\"US0000000001\" securityID=\"US0000000001\" securityIDType=\"ISIN\" symbol=\"KEEP\" />
        <Trade conid=\"2\" isin=\"US0000000002\" securityID=\"US0000000002\" securityIDType=\"ISIN\" symbol=\"DROP\" />
        <Trade conid=\"3\" isin=\"\" underlyingConid=\"1\" underlyingSecurityID=\"US0000000001\" symbol=\"KEEP_OPTION\" />
      </Trades>
      <CashTransactions>
        <CashTransaction conid=\"3\" isin=\"\" amount=\"10\" type=\"Dividends\" />
        <CashTransaction conid=\"2\" isin=\"\" amount=\"20\" type=\"Dividends\" />
      </CashTransactions>
      <SecuritiesInfo>
        <SecurityInfo conid=\"1\" isin=\"US0000000001\" />
        <SecurityInfo conid=\"2\" isin=\"US0000000002\" />
      </SecuritiesInfo>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


def run_filter_script(tmp_path: Path, *extra_args: str) -> Path:
    input_file = tmp_path / "input.xml"
    output_file = tmp_path / "output.xml"
    input_file.write_text(SAMPLE_IBFLEX_XML, encoding="utf-8")

    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--input-file",
        str(input_file),
        "--output-file",
        str(output_file),
        "--isins",
        "US0000000001",
        *extra_args,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert output_file.exists()
    return output_file


def test_non_selected_isins_are_removed_from_minimal_ibflex_xml(tmp_path):
    output_file = run_filter_script(tmp_path)
    tree = ET.parse(str(output_file))

    assert tree.xpath("count(.//Trade[@conid='1'])") == 1.0
    assert tree.xpath("count(.//Trade[@conid='3'])") == 1.0
    assert tree.xpath("count(.//Trade[@conid='2'])") == 0.0

    assert tree.xpath("count(.//CashTransaction[@conid='3'])") == 1.0
    assert tree.xpath("count(.//CashTransaction[@conid='2'])") == 0.0

    output_isins = {
        value for value in tree.xpath(".//*[@isin]/@isin") if value
    }
    assert output_isins == {"US0000000001"}


def test_account_information_keeps_only_allowed_attributes(tmp_path):
    output_file = run_filter_script(tmp_path)
    tree = ET.parse(str(output_file))

    account_information = tree.xpath(".//AccountInformation")[0]
    assert account_information.attrib == {
        "accountId": "U0000000",
        "acctAlias": "",
        "currency": "CHF",
        "stateResidentialAddress": "CH-ZH",
    }
