"""Translation management for PDF rendering.

This module provides translation functionality with support for multiple languages.
Translations are loaded from separate language files in the translations/ subfolder.
Falls back to German ('de') if a translation is missing in the requested language.
"""

import importlib
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Cache for loaded translation modules
_translation_cache: Dict[str, Dict[str, str]] = {}

# Default language
DEFAULT_LANGUAGE = 'de'


def _load_translations(lang: str) -> Optional[Dict[str, str]]:
    """Load translations for a specific language.

    Args:
        lang: The language code (e.g., 'de', 'fr', 'en')

    Returns:
        Dictionary of translations or None if language file doesn't exist
    """
    if lang in _translation_cache:
        return _translation_cache[lang]

    try:
        # Dynamically import the language module
        module = importlib.import_module(f'opensteuerauszug.render.translations.{lang}')
        translations = getattr(module, 'TRANSLATIONS', {})
        _translation_cache[lang] = translations
        logger.debug(f"Loaded {len(translations)} translations for language '{lang}'")
        return translations
    except (ImportError, AttributeError) as e:
        logger.warning(f"Could not load translations for language '{lang}': {e}")
        return None


def get_text(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Get translated text for a given key.

    Falls back to default language if the translation is not found in the requested language.

    Args:
        key: The translation key
        lang: The language code (default: 'de')

    Returns:
        The translated text, or the key itself if not found in any language
    """
    # Try to get translation in requested language
    translations = _load_translations(lang)
    if translations and key in translations:
        return translations[key]

    # Fallback to default language if different language was requested
    if lang != DEFAULT_LANGUAGE:
        logger.debug(f"Translation key '{key}' not found in '{lang}', falling back to '{DEFAULT_LANGUAGE}'")
        default_translations = _load_translations(DEFAULT_LANGUAGE)
        if default_translations and key in default_translations:
            return default_translations[key]

    # If still not found, return the key itself
    logger.warning(f"Translation key '{key}' not found in any language, returning key as fallback")
    return key


def t(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Shorthand alias for get_text.

    Args:
        key: The translation key
        lang: The language code (default: 'de')

    Returns:
        The translated text, or the key itself if not found
    """
    return get_text(key, lang)


def clear_translation_cache():
    """Clear the translation cache.

    Useful for testing or if translation files are modified at runtime.
    """
    _translation_cache.clear()
    logger.debug("Translation cache cleared")

