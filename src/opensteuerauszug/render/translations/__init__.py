"""Translation management package for PDF rendering.

This package provides translation functionality with support for multiple languages.
Translations are loaded from separate language files (de.py, fr.py, etc.) in this directory.
"""

from .manager import t, get_text, clear_translation_cache, DEFAULT_LANGUAGE

__all__ = ['t', 'get_text', 'clear_translation_cache', 'DEFAULT_LANGUAGE']


