# AGENTS.md

## Project Overview

OpenSteuerAuszug is a Python package for generating Swiss tax statements (Steuerauszüge) in the official eCH-0196 XML/PDF format from foreign broker data (Charles Schwab, Interactive Brokers). It automates importing, calculating, and rendering tax-relevant financial data so users don't have to manually type it into Swiss tax software.

## Build and Environment

- **Python**: Requires 3.10 or newer.
- **Build system**: Hatchling (configured in `pyproject.toml`).
- **Dependency management**: All dependencies go in `pyproject.toml` under `[project.dependencies]` or `[project.optional-dependencies]`. Do **not** use `requirements.txt`.
- **Install for development**:
  ```bash
  python -m venv .venv
  source .venv/bin/activate
  pip install -e ".[dev]"
  pip install git+https://github.com/vroonhof/pdf417decoder.git#subdirectory=python
  ```

## Testing

- **Framework**: pytest
- **Run all tests**: `pytest tests/`
- **Test paths**: Configured in `pyproject.toml` under `[tool.pytest.ini_options]`, testpaths = `["tests"]`, pythonpath = `["."]`.
- **Markers**: `integration` for integration tests.
- **Integration tests** (`@pytest.mark.integration` or `@pytest.mark.parametrize` with sample files) must **not** be modified unless the underlying requirements have changed. If they fail, fix the implementation, not the test.
- **External samples**: The `EXTRA_SAMPLE_DIR` environment variable can point to a directory with real-world XML files used in integration tests. These are never committed.

## Linting

- **Flake8**: `flake8 .` with settings from `pyproject.toml` (`max-line-length=127`).
- **Black**: line-length 100, target Python 3.10.
- **isort**: profile "black", line-length 100.
- The CI pipeline runs flake8 for syntax errors/undefined names (`E9,F63,F7,F82`) as a hard gate.

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

Do **not** place Python files directly in `src/opensteuerauszug/` (except `steuerauszug.py` which is the CLI entry point and `logging_utils.py`).

## Key Architectural Patterns

- **Pydantic models** are used extensively for data validation and XML serialization (via `pydantic-xml`).
- **Configuration** uses a hierarchical TOML system: general settings -> broker-level overrides -> account-level overrides. See `docs/config.md`.
- **Calculators** follow a pipeline pattern with a base class in `calculate/base.py`. Modes include `minimal`, `kursliste`, and `fill_in`.
- **The Kursliste** is the official Swiss tax valuation list. It can be loaded from XML or SQLite. The `KurslisteManager` in `core/` handles access.
- **CLI** is built with Typer. Entry point: `opensteuerauszug.steuerauszug:app`.

## Supported Brokers

Each broker has its own subpackage under `importers/`:

- **`importers/schwab/`**: Charles Schwab (brokerage + equity awards). Multiple extractors handle different statement sections.
- **`importers/ibkr/`**: Interactive Brokers. Uses the `ibflex` library to parse Flex Query XML reports.

## Domain Notes

- The **eCH-0196** standard is the Swiss XML format for electronic tax statements. The XSD schemas are in `specs/`.
- Security names must be truncated to 60 characters (eCH-0196 limit) even though the Kursliste allows 120.
- The software is **not** the actual broker/bank; it generates statements from broker data. Organization identifiers use workarounds (e.g., prefixed with "OPNAUS") since the format assumes a Swiss financial institution.
- Tax values in the generated output are **informational only** — the official tax software should recalculate from Kursliste data.

## Git Conventions

- Do not override git user credentials with `-c user.name` or `-c user.email` in commands. Use global git config.
- Cursor rule files (`.mdc`) go exclusively in `.cursor/rules/` using kebab-case naming.

## Test Structure

Tests mirror the source layout:

```
tests/
├── calculate/      # Tests for tax calculation logic
├── core/           # Tests for core business logic
├── importers/      # Tests for broker importers
│   ├── ibkr/
│   └── schwab/
├── model/          # Tests for data models
├── render/         # Tests for rendering
├── scripts/        # Tests for utility scripts
├── samples/        # Test fixture files (XML, etc.)
├── test_data/      # Additional test data files
├── utils/          # Test utilities (sample loading, XML comparison)
└── util/           # Tests for utility functions
```

## CI/CD

GitHub Actions workflow (`.github/workflows/python-app.yml`) runs on pushes/PRs to `main`:
1. Sets up Python 3.10
2. Installs dependencies including vendored forks of pdf417gen and pdf417decoder
3. Runs flake8 lint checks
4. Runs pytest
