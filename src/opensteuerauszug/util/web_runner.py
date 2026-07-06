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

import click

OutputCallback = Callable[[str], None]


class _CallbackWriter:
    """A minimal text stream that forwards complete lines to a callback."""

    def __init__(self, callback: OutputCallback):
        self._callback = callback
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
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
        command = get_command(app)
        result = command.main(args=args, prog_name="opensteuerauszug", standalone_mode=False)
        if isinstance(result, int):
            exit_code = result
    except click.exceptions.Exit as exc:
        exit_code = exc.exit_code
    except SystemExit as exc:  # pragma: no cover - defensive
        exit_code = int(exc.code or 0)
    except click.ClickException as exc:
        callback(f"Error: {exc.format_message()}")
        exit_code = exc.exit_code
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
