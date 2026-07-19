import shutil
from pathlib import Path

from opensteuerauszug.core.kursliste_db_reader import KurslisteDBReader
from opensteuerauszug.util import web_runner

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_workspace_layout_is_created(tmp_path: Path):
    layout = web_runner.ensure_workspace(str(tmp_path / "work"))
    assert set(layout) == {"root", "input", "kursliste", "output", "config"}
    for path in layout.values():
        assert Path(path).is_dir()


def test_run_process_generates_pdf_and_xml_from_ibkr_sample(tmp_path: Path):
    input_file = PROJECT_ROOT / "tests" / "samples" / "import" / "ibkr" / "vtandchill_2025.xml"
    kursliste_dir = PROJECT_ROOT / "tests" / "samples" / "kursliste"
    output_pdf = tmp_path / "out.pdf"
    output_xml = tmp_path / "out.xml"

    lines: list[str] = []
    result = web_runner.run_process(
        input_path=str(input_file),
        output_pdf=str(output_pdf),
        importer="ibkr",
        tax_year=2025,
        kursliste_dir=str(kursliste_dir),
        xml_output=str(output_xml),
        on_output=lines.append,
    )

    log = "\n".join(lines)
    assert result["exit_code"] == 0, f"pipeline failed:\n{log}"
    assert result["success"] is True
    assert result["outputs"] == {"pdf": str(output_pdf), "xml": str(output_xml)}
    assert output_pdf.stat().st_size > 0
    assert "IBKR import complete." in log
    assert "Processing finished successfully." in log


def test_convert_kursliste_xmls_produces_usable_sqlite(tmp_path: Path):
    """The web worker converts uploaded Kursliste XMLs to SQLite before the
    pipeline runs (a real XML cannot be parsed whole in the browser)."""
    kursliste_dir = tmp_path / "kursliste"
    kursliste_dir.mkdir()
    # Filename without a year: the year must be read from the XML content.
    shutil.copy(
        PROJECT_ROOT / "tests" / "samples" / "kursliste" / "kursliste_mini.xml",
        kursliste_dir / "kursliste_mini.xml",
    )

    lines: list[str] = []
    result = web_runner.convert_kursliste_xmls(str(kursliste_dir), on_output=lines.append)

    db_path = kursliste_dir / "kursliste_2024.sqlite"
    assert result["errors"] == []
    assert result["skipped"] == []
    assert [c["source"] for c in result["converted"]] == ["kursliste_mini.xml"]
    assert result["converted"][0] == {
        "source": "kursliste_mini.xml",
        "path": str(db_path),
        "year": 2024,
        "size": db_path.stat().st_size,
    }
    assert not (kursliste_dir / "kursliste_mini.xml").exists()
    assert any("Conversion complete" in line for line in lines)

    with KurslisteDBReader(str(db_path)) as reader:
        security = reader.find_security_by_isin("US9229087690", 2024)
    assert security is not None
    assert security.valorNumber == 1246192


def test_convert_kursliste_xmls_skips_year_with_existing_sqlite(tmp_path: Path):
    kursliste_dir = tmp_path / "kursliste"
    kursliste_dir.mkdir()
    xml_path = kursliste_dir / "kursliste_2024.xml"
    shutil.copy(PROJECT_ROOT / "tests" / "samples" / "kursliste" / "kursliste_mini.xml", xml_path)
    (kursliste_dir / "kursliste_2024.sqlite").write_bytes(b"existing")

    result = web_runner.convert_kursliste_xmls(str(kursliste_dir))

    assert result["converted"] == []
    assert result["skipped"] == ["kursliste_2024.xml"]
    assert xml_path.exists()
    assert (kursliste_dir / "kursliste_2024.sqlite").read_bytes() == b"existing"


def test_convert_kursliste_xmls_reports_invalid_xml(tmp_path: Path):
    kursliste_dir = tmp_path / "kursliste"
    kursliste_dir.mkdir()
    bad = kursliste_dir / "kursliste_2024.xml"
    bad.write_text("<kursliste year='2024'><unclosed></kursliste>")

    lines: list[str] = []
    result = web_runner.convert_kursliste_xmls(str(kursliste_dir), on_output=lines.append)

    assert result["converted"] == []
    assert [e["source"] for e in result["errors"]] == ["kursliste_2024.xml"]
    assert bad.exists()  # the input is left in place on failure
    assert not (kursliste_dir / "kursliste_2024.sqlite").exists()
    assert any("Error converting kursliste_2024.xml" in line for line in lines)


def test_run_process_succeeds_with_converted_kursliste(tmp_path: Path):
    """End to end: convert the XML like the worker does, then run the pipeline
    against the resulting SQLite-only directory."""
    kursliste_dir = tmp_path / "kursliste"
    kursliste_dir.mkdir()
    shutil.copy(
        PROJECT_ROOT / "tests" / "samples" / "kursliste" / "kursliste_mini_2025.xml",
        kursliste_dir / "kursliste_mini_2025.xml",
    )
    conversion = web_runner.convert_kursliste_xmls(str(kursliste_dir))
    assert conversion["errors"] == []

    result = web_runner.run_process(
        input_path=str(
            PROJECT_ROOT / "tests" / "samples" / "import" / "ibkr" / "vtandchill_2025.xml"
        ),
        output_pdf=str(tmp_path / "out.pdf"),
        importer="ibkr",
        tax_year=2025,
        kursliste_dir=str(kursliste_dir),
        on_output=lambda line: None,
    )
    assert result["success"] is True


def test_run_process_reports_failure_without_kursliste(tmp_path: Path):
    input_file = PROJECT_ROOT / "tests" / "samples" / "import" / "ibkr" / "vtandchill_2025.xml"
    empty_kursliste = tmp_path / "kursliste"
    empty_kursliste.mkdir()

    lines: list[str] = []
    result = web_runner.run_process(
        input_path=str(input_file),
        output_pdf=str(tmp_path / "out.pdf"),
        importer="ibkr",
        tax_year=2025,
        kursliste_dir=str(empty_kursliste),
        on_output=lines.append,
    )

    assert result["exit_code"] != 0
    assert result["success"] is False
    assert "Kursliste data for tax year 2025 not found" in "\n".join(lines)


def test_run_process_can_run_consecutively_without_duplicating_log_lines(tmp_path: Path):
    """Log handlers must be re-created per run, otherwise the second run in the
    same interpreter (the normal case in the browser) doubles every log line
    or writes to a stale stream."""
    input_file = PROJECT_ROOT / "tests" / "samples" / "import" / "ibkr" / "vtandchill_2025.xml"
    kursliste_dir = PROJECT_ROOT / "tests" / "samples" / "kursliste"

    for attempt in range(2):
        lines: list[str] = []
        result = web_runner.run_process(
            input_path=str(input_file),
            output_pdf=str(tmp_path / f"out_{attempt}.pdf"),
            importer="ibkr",
            tax_year=2025,
            kursliste_dir=str(kursliste_dir),
            on_output=lines.append,
        )
        assert result["exit_code"] == 0
        assert sum("Processing finished successfully." in line for line in lines) == 1
