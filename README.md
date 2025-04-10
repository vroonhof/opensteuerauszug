# OpenSteuerAuszug

A Python package for handling and processing German tax statements (Steuerauszüge).

## Features

- TBD

## Installation

This needs newer version of pdf417gen and (for testing) pdf417decoder than
available on PyPY for now there are my vendored branches

```bash
pip install .
pip install git+https://github.com/vroonhof/pdf417-py.git
```

## Usage

```python
from opensteuerauszug import SteuerAuszug

# Example usage will be added
```

## Development

To set up the development environment:

```bash
# Create and activate virtual environment
python -m venv .venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
pip install git+https://github.com/vroonhof/pdf417-py.git
pip install git+https://github.com/vroonhof/pdf417decoder.git#subdirectory=python
# OR
# pip install git+https://github.com/sparkfish/pdf417decoder.git@08c01172b7150bb2d2c0591566f43d45f9294fac#subdirectory=python
```

## Testing

```bash
pytest tests/
```

## License

See [LICENSE](LICENSE) file.
