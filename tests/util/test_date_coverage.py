import pytest
from datetime import date
from src.opensteuerauszug.util import DateRangeCoverage

def test_date_range_coverage_basic():
    cov = DateRangeCoverage()
    cov.mark_covered(date(2024, 1, 1), date(2024, 1, 10))
    assert cov.is_covered(date(2024, 1, 1), date(2024, 1, 10))
    assert cov.is_covered(date(2024, 1, 2), date(2024, 1, 5))
    assert not cov.is_covered(date(2023, 12, 31), date(2024, 1, 1))
    assert not cov.is_covered(date(2024, 1, 10), date(2024, 1, 11))

def test_date_range_coverage_overlap_and_adjacent():
    cov = DateRangeCoverage()
    cov.mark_covered(date(2024, 1, 1), date(2024, 1, 5))
    cov.mark_covered(date(2024, 1, 4), date(2024, 1, 10))  # Overlaps
    cov.mark_covered(date(2024, 1, 11), date(2024, 1, 12))  # Adjacent
    assert cov.is_covered(date(2024, 1, 1), date(2024, 1, 12))
    assert not cov.is_covered(date(2024, 1, 1), date(2024, 1, 13))

def test_date_range_coverage_multiple_ranges():
    cov = DateRangeCoverage()
    cov.mark_covered(date(2024, 1, 1), date(2024, 1, 5))
    cov.mark_covered(date(2024, 1, 10), date(2024, 1, 15))
    assert cov.is_covered(date(2024, 1, 1), date(2024, 1, 5))
    assert cov.is_covered(date(2024, 1, 10), date(2024, 1, 15))
    assert not cov.is_covered(date(2024, 1, 5), date(2024, 1, 10))
    assert not cov.is_covered(date(2024, 1, 1), date(2024, 1, 15))

def test_date_range_coverage_invalid_range():
    cov = DateRangeCoverage()
    try:
        cov.mark_covered(date(2024, 1, 10), date(2024, 1, 1))
        assert False, "Should raise ValueError for invalid range"
    except ValueError:
        pass
    try:
        cov.is_covered(date(2024, 1, 10), date(2024, 1, 1))
        assert False, "Should raise ValueError for invalid range"
    except ValueError:
        pass 
def test_maximal_covered_range_containing_for_covered_date():
    cov = DateRangeCoverage()
    cov.mark_covered(date(2024, 1, 1), date(2024, 1, 10))
    cov.mark_covered(date(2024, 1, 15), date(2024, 1, 20))
    assert cov.maximal_covered_range_containing(date(2024, 1, 5)) == (
        date(2024, 1, 1),
        date(2024, 1, 10),
    )


def test_maximal_covered_range_containing_for_uncovered_date():
    cov = DateRangeCoverage()
    cov.mark_covered(date(2024, 1, 1), date(2024, 1, 10))
    cov.mark_covered(date(2024, 1, 15), date(2024, 1, 20))
    assert cov.maximal_covered_range_containing(date(2024, 1, 12)) is None


