from decimal import Decimal

import pytest

from opensteuerauszug.importers.common import to_decimal


def test_to_decimal_accepts_string_and_numeric():
    assert to_decimal("1.23", "x", "ctx") == Decimal("1.23")
    assert to_decimal(2, "x", "ctx") == Decimal("2")
    assert to_decimal(Decimal("3.5"), "x", "ctx") == Decimal("3.5")


def test_to_decimal_rejects_none_with_context():
    with pytest.raises(ValueError, match="field 'qty'.*Trade AAPL"):
        to_decimal(None, "qty", "Trade AAPL")


def test_to_decimal_rejects_garbage_with_context():
    with pytest.raises(ValueError, match="Invalid value.*'abc'.*field 'qty'.*Trade AAPL"):
        to_decimal("abc", "qty", "Trade AAPL")
