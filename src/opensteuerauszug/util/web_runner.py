"""Helpers to drive the processing pipeline from a web (Pyodide/WASM) frontend.

The standalone web app (see ``web/`` and ``scripts/build_web_app.py``) runs the
regular CLI pipeline inside the browser.  This module provides a small, plain
Python API on top of the Typer CLI so the JavaScript side only has to deal
with file paths and simple dictionaries.  It is intentionally free of any
Pyodide specific imports so it can be tested natively with pytest.
"""

import logging
import sys
import traceback
from pathlib import Path
from typing import Callable, List, Optional

OutputCallback = Callable[[str], None]


class _CallbackWriter:
    """A minimal text stream that forwards complete lines to a callback."""

    def __init__(self, callback: OutputCallback):
        self._callback = callback
        self._buffer = ""

    def write(self, text: str) -> int:
        # Treat carriage returns as line breaks so in-place progress tickers
        # (e.g. the Kursliste converter's "\rProcessed N records...") reach
        # the callback while they happen instead of piling up in the buffer.
        self._buffer += text.replace("\r", "\n")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._callback(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._callback(self._buffer)
            self._buffer = ""

    def isatty(self) -> bool:
        return False


def ensure_workspace(root: str = "/work") -> dict:
    """Create the standard workspace layout used by the web UI.

    Returns a dictionary with the created paths so the JavaScript side can
    write uploaded files into the right places.
    """
    base = Path(root)
    layout = {
        "root": base,
        "input": base / "input",
        "kursliste": base / "kursliste",
        "output": base / "output",
        "config": base / "config",
    }
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    return {name: str(path) for name, path in layout.items()}


def _reset_root_logging() -> None:
    """Drop root handlers so ``logging.basicConfig`` in the CLI re-attaches
    to the *current* ``sys.stderr`` (which we redirect per run)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)


def build_cli_args(
    input_path: str,
    output_pdf: str,
    importer: str,
    tax_year: int,
    kursliste_dir: str,
    config_path: Optional[str] = None,
    xml_output: Optional[str] = None,
    identifiers_csv: Optional[str] = None,
    tax_calculation_level: str = "kursliste",
    log_level: str = "INFO",
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """Translate web UI options into CLI arguments for the ``process`` command."""
    args = [
        "process",
        input_path,
        "--importer",
        importer,
        "--tax-year",
        str(tax_year),
        "--kursliste-dir",
        kursliste_dir,
        "--output",
        output_pdf,
        "--tax-calculation-level",
        tax_calculation_level,
        "--log-level",
        log_level,
    ]
    if config_path:
        args.extend(["--config", config_path])
    if xml_output:
        args.extend(["--xml-output", xml_output])
    if identifiers_csv:
        args.extend(["--identifiers-csv-path", identifiers_csv])
    if extra_args:
        args.extend(extra_args)
    return args


def run_cli(args: List[str], on_output: Optional[OutputCallback] = None) -> dict:
    """Run the opensteuerauszug CLI with the given arguments.

    stdout/stderr (and log output) produced during the run are forwarded
    line by line to ``on_output``.  Returns ``{"exit_code": int}``; the run
    never raises so the JavaScript caller only needs to check the code.
    """
    # Imported lazily so that merely importing this module stays cheap.
    from typer.main import get_command

    from opensteuerauszug.steuerauszug import app

    callback: OutputCallback = on_output or (lambda line: None)
    writer = _CallbackWriter(callback)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = writer  # type: ignore[assignment]
    sys.stderr = writer  # type: ignore[assignment]
    _reset_root_logging()
    exit_code = 0
    try:
        # Standalone mode makes click (or, for typer >= 0.26, its vendored
        # copy in typer._click) print CLI errors to our redirected stderr and
        # signal the exit code via SystemExit — so we never have to touch
        # click's exception classes, which differ across typer versions.
        command = get_command(app)
        command.main(args=args, prog_name="opensteuerauszug")
    except SystemExit as exc:
        if isinstance(exc.code, int):
            exit_code = exc.code
        elif exc.code is not None:
            callback(str(exc.code))
            exit_code = 1
    except Exception:
        for line in traceback.format_exc(limit=20).splitlines():
            callback(line)
        exit_code = 1
    finally:
        writer.flush()
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        _reset_root_logging()
    return {"exit_code": exit_code}


def convert_kursliste_xmls(kursliste_dir: str, on_output: Optional[OutputCallback] = None) -> dict:
    """Convert Kursliste XML files in a directory to SQLite databases in place.

    Loading a full Kursliste XML needs roughly 30x the file size in memory,
    which does not fit in the browser's WebAssembly heap for real files.  The
    streaming XML-to-SQLite converter runs in near-constant memory, so the web
    worker calls this before the pipeline and the page caches the resulting
    database for later runs.

    Each successfully converted XML file is deleted so the pipeline picks up
    the SQLite database instead.  XML files whose year already has a SQLite
    database are left untouched and reported as skipped.  Returns
    ``{"converted": [{"source", "path", "year", "size"}], "skipped": [...],
    "errors": [{"source", "error"}]}``.
    """
    from opensteuerauszug.core.kursliste_manager import KurslisteManager
    from opensteuerauszug.kursliste.converter import convert_kursliste_xml_to_sqlite

    callback: OutputCallback = on_output or (lambda line: None)
    writer = _CallbackWriter(callback)
    manager = KurslisteManager()
    directory = Path(kursliste_dir)
    result: dict = {"converted": [], "skipped": [], "errors": []}

    for xml_path in sorted(directory.glob("*.xml")):
        year = manager._get_year_from_filename(xml_path.name)
        if year is None:
            year = manager._get_year_from_xml_content(xml_path)
        db_path = directory / (f"kursliste_{year}.sqlite" if year else xml_path.stem + ".sqlite")
        if db_path.is_file():
            callback(f"Skipping {xml_path.name}: {db_path.name} already exists.")
            result["skipped"].append(xml_path.name)
            continue

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = writer  # type: ignore[assignment]
        sys.stderr = writer  # type: ignore[assignment]
        try:
            convert_kursliste_xml_to_sqlite(xml_path, db_path)
        except Exception as exc:
            db_path.unlink(missing_ok=True)
            result["errors"].append({"source": xml_path.name, "error": str(exc)})
        else:
            xml_path.unlink()
            result["converted"].append(
                {
                    "source": xml_path.name,
                    "path": str(db_path),
                    "year": year,
                    "size": db_path.stat().st_size,
                }
            )
        finally:
            writer.flush()
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    for err in result["errors"]:
        callback(f"Error converting {err['source']}: {err['error']}")
    return result


def run_process(
    input_path: str,
    output_pdf: str,
    importer: str,
    tax_year: int,
    kursliste_dir: str,
    config_path: Optional[str] = None,
    xml_output: Optional[str] = None,
    identifiers_csv: Optional[str] = None,
    tax_calculation_level: str = "kursliste",
    log_level: str = "INFO",
    extra_args: Optional[List[str]] = None,
    on_output: Optional[OutputCallback] = None,
) -> dict:
    """High level entry point used by the web worker.

    Runs the full pipeline and reports which of the requested output files
    were actually produced.
    """
    args = build_cli_args(
        input_path=input_path,
        output_pdf=output_pdf,
        importer=importer,
        tax_year=tax_year,
        kursliste_dir=kursliste_dir,
        config_path=config_path,
        xml_output=xml_output,
        identifiers_csv=identifiers_csv,
        tax_calculation_level=tax_calculation_level,
        log_level=log_level,
        extra_args=extra_args,
    )
    result = run_cli(args, on_output=on_output)
    outputs = {}
    for name, path_str in (("pdf", output_pdf), ("xml", xml_output)):
        if path_str and Path(path_str).is_file():
            outputs[name] = path_str
    result["outputs"] = outputs
    result["success"] = result["exit_code"] == 0 and "pdf" in outputs
    return result
