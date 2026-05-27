# CLAUDE.md

## Agent Guidelines
Refer to [AGENTS.md](AGENTS.md) in the root directory for full details on project architecture, environment setup, coding guidelines, and linting/formatting standards. All AI assistants must adhere strictly to the guidelines defined there.

## Build and Environment Commands
- **Install for Development**: `pip install -e ".[dev]"`
- **Install PDF417 Decoder**: `pip install git+https://github.com/vroonhof/pdf417decoder.git#subdirectory=python`

## Testing Commands
- **Run all tests**: `.venv/bin/pytest tests/`
- **Run single test**: `.venv/bin/pytest tests/path/to/test_file.py -k test_name`

## Linting and Formatting
- **Format Code (Black)**: `.venv/bin/black src/ tests/ scripts/`
- **Lint Code (Flake8)**: `.venv/bin/flake8 .`
- **Check Code (Ruff)**: `.venv/bin/ruff check src/ tests/`
