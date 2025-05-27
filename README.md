# OpenSteuerAuszug

A Python package for generaring Swiss tax statements (Steuerauszüge) from brokers' statements that don't support it, e.g. mostly foreign ones.
This goal is to eliminate tedious and error prone manual typing into the tax softwware.

## Disclaimer

TODO: explain that 
- The package is not formally audited
- the main focus is on getting core transaction and interest data.
- These need to be verified by the user before submitting with the tax return
- Tax values are computed best effort for informational purpose (the man Tax software should be able to compute it from the core transaction data.


## Features

- TBD

## Supported Brokers

For now the focus is on brokers / banks that the author has 

- Charles Schwab (main trading account and Equity Awards)
- [planned] Interactive Brokers
  
Additionally we can recalculate and verify any existing steuer-auszug (this is mostly to increase confidence in the software itself)

## Installation

This needs newer version of pdf417gen and (for testing) pdf417decoder than
available on PyPY for now there are my vendored branches

```bash
pip install .
pip install git+https://github.com/vroonhof/pdf417-py.git
```

## Usage

### Generating a Tax statement

```python
from opensteuerauszug import SteuerAuszug

# Example usage will be added
```
### Importing the result into your tax software.

TODO

## Scripts and Tools

This project includes various scripts for data processing, testing, and utility tasks.
For detailed documentation on available scripts, including the Kursliste filtering tool, see the [Scripts Readme](scripts/README.md).

## Development

To set up the development environment:

```bash
# Create and activate virtual environment
python -m venv .venv
source venv/bin/activate  # On Windows: venv\Scriptsctivate

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

## Developer Scripts

This project includes utility scripts for development and data management. For detailed information on these scripts, please see the [Scripts Documentation](scripts/README.md).
