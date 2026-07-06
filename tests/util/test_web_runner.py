from pathlib import Path

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
