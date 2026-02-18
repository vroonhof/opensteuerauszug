"""Tests for logging configuration to ensure pypdf warnings are suppressed."""
import logging
import pytest
from opensteuerauszug.logging_utils import setup_logging


def test_setup_logging_suppresses_pypdf_warnings(caplog):
    """Verify that setup_logging() suppresses pypdf warnings but not errors."""
    # Setup logging with verbose=False (INFO level for opensteuerauszug)
    setup_logging(verbose=False)
    
    # Create a pypdf logger instance
    pypdf_logger = logging.getLogger('pypdf._text_extraction._layout_mode._fixed_width_page')
    
    # Test that WARNING level messages are suppressed
    with caplog.at_level(logging.WARNING):
        pypdf_logger.warning("Rotated text discovered. Output will be incomplete")
        # Warning should not be in the captured log
        assert not any('Rotated text discovered' in record.message for record in caplog.records)
    
    # Test that ERROR level messages are still logged
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        pypdf_logger.error("Critical PDF parsing error")
        # Error should be in the captured log
        assert any('Critical PDF parsing error' in record.message for record in caplog.records)


def test_pypdf_logger_level_is_error():
    """Verify that pypdf logger is set to ERROR level after setup."""
    setup_logging(verbose=False)
    pypdf_logger = logging.getLogger('pypdf')
    assert pypdf_logger.level == logging.ERROR, "pypdf logger should be set to ERROR level"


def test_opensteuerauszug_logger_respects_verbose_flag():
    """Verify that opensteuerauszug logger respects the verbose flag."""
    # Test with verbose=False (INFO level)
    setup_logging(verbose=False)
    osa_logger = logging.getLogger('opensteuerauszug')
    assert osa_logger.level == logging.INFO
    
    # Test with verbose=True (DEBUG level)
    setup_logging(verbose=True)
    osa_logger = logging.getLogger('opensteuerauszug')
    assert osa_logger.level == logging.DEBUG
