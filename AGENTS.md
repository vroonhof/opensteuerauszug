# AGENTS.md

## Project Overview

OpenSteuerAuszug is a Python package for generating Swiss tax statements (Steuerauszüge) in the official eCH-0196 XML/PDF format from foreign broker data. For domain background and broker details see `docs/domain.md`.

## Build and Environment

- **Python**: Requires 3.10 or newer.
- **Build system**: Hatchling (configured in `pyproject.toml`).
- **Dependency management**: All dependencies go in `pyproject.toml` under `[project.dependencies]` or `[project.optional-dependencies]`. Do **not** use `requirements.txt`.
- **Install for development**:
  ```bash
  uv sync --locked --extra dev
  ```
- **Update dependencies**: Run `./scripts/update_lockfiles.sh --upgrade` and commit both `uv.lock` and `pylock.toml`.

## Testing

- **Run all tests**: `uv run --locked --extra dev pytest tests/`
- **Integration tests** (`@pytest.mark.integration` or `@pytest.mark.parametrize` with sample files) must **not** be modified unless the underlying requirements have changed. If they fail, fix the implementation, not the test.
- **External samples**: The `EXTRA_SAMPLE_DIR` environment variable can point to a directory with real-world XML files used in integration tests. These are never committed.
- **Test naming**: Name tests after the invariant they verify, not after the function they call.
  ```python
  def test_security_name_is_truncated_to_60_characters():
  def test_missing_isin_is_enriched_from_identifiers_csv():
  ```
- **Pydantic attribute checks**: Do not use `getattr`, `hasattr`, or `try/except AttributeError` to test attributes on Pydantic models. Pydantic fields always exist with defaults, so these checks silently pass. Assert the value directly.
  ```python
  assert position.isin == "US0378331005"
  assert len(statement.securities) == 3
  ```

## Linting and Formatting

- **Flake8**: `uv run --locked --extra dev flake8 .` with settings from `pyproject.toml` (`max-line-length=127`).
- **Black**: line-length 100, target Python 3.10.
- **isort**: profile "black", line-length 100.
- CI runs flake8 for syntax errors/undefined names (`E9,F63,F7,F82`) as a hard gate.

### Guidelines for AI Coding Agents:
1. **Run Black Formatter**: Always run Black (`uv run --locked --extra dev black src/ tests/ scripts/`) to auto-format all created or modified Python files before concluding your task.
2. **Quote Preference**: Match the existing style of the file you are editing. If creating a new file, prefer double quotes (`"..."`) for string literals (matching Black's standard default).
3. **Preserve Format Blocks**: Absolutely preserve and do **not** modify or restructure code regions wrapped in `# fmt: off` and `# fmt: on` (which protect visual test data matrices).

## Code Organization

All source code lives under `src/opensteuerauszug/`. New code must be placed in one of these subpackages:

| Subpackage    | Purpose                                              |
|---------------|------------------------------------------------------|
| `importers/`  | Broker-specific data import (parsers, extractors)    |
| `model/`      | Data models (Pydantic models, eCH-0196 schema types) |
| `core/`       | Core business logic, Kursliste access, reconciliation |
| `calculate/`  | Tax calculation and processing algorithms            |
| `render/`     | PDF/report generation and formatting                 |
| `util/`       | Shared utility functions and helpers                 |
| `config/`     | Configuration loading and settings models            |

Do **not** place Python files directly in `src/opensteuerauszug/` (except `steuerauszug.py` and `logging_utils.py`).

## Key Architectural Patterns

- **Pydantic models** are used extensively for data validation and XML serialization (via `pydantic-xml`).
- **Configuration** uses a hierarchical TOML system: general -> broker -> account. See `docs/config.md`.
- **Calculators** follow a pipeline pattern with a base class in `calculate/base.py`. Modes: `minimal`, `kursliste`, `fill_in`.
- **CLI** is built with Typer. Entry point: `opensteuerauszug.steuerauszug:app`.

## Git Conventions

- Do not override git user credentials with `-c user.name` or `-c user.email`. Use global git config.
- Cursor rule files (`.mdc`) go exclusively in `.cursor/rules/` using kebab-case naming.

## Test Structure

Tests mirror the source layout under `tests/` (`calculate/`, `core/`, `importers/`, `model/`, `render/`, `scripts/`, `util/`). Test fixtures live in `tests/samples/` and `tests/test_data/`. Shared test utilities are in `tests/utils/`.

## CI/CD

GitHub Actions (`.github/workflows/python-app.yml`) runs on pushes/PRs to `main`: installs Python 3.10 + dependencies, runs flake8, then pytest.
