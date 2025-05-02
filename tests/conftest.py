"""
Configuration file for pytest.

This file ensures that the src directory is in the Python path
so that tests can import modules from the package.
"""

import os
import sys
from pathlib import Path

# Add the src directory to the Python path
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))
