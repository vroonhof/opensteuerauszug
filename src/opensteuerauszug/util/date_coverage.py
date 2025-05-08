from datetime import date, timedelta
from bisect import bisect_left, bisect_right
from typing import List, Tuple

class DateRangeCoverage:
    """
    Utility to track coverage of date ranges and check if a given range is fully covered.
    Date ranges are inclusive of both begin and end.
    """
    def __init__(self):
        # Store covered ranges as a sorted, non-overlapping list of (begin, end) tuples
        self.covered: List[Tuple[date, date]] = []

    def mark_covered(self, begin: date, end: date) -> None:
        """
        Mark the date range [begin, end] (inclusive) as covered.
        Overlapping or adjacent ranges are merged.
        """
        if begin > end:
            raise ValueError("Begin date must not be after end date.")
        new_ranges = []
        placed = False
        for b, e in self.covered:
            if e < begin - timedelta(days=1):
                new_ranges.append((b, e))
            elif end < b - timedelta(days=1):
                if not placed:
                    new_ranges.append((begin, end))
                    placed = True
                new_ranges.append((b, e))
            else:
                begin = min(begin, b)
                end = max(end, e)
        if not placed:
            new_ranges.append((begin, end))
        self.covered = new_ranges

    def is_covered(self, begin: date, end: date) -> bool:
        """
        Check if the date range [begin, end] (inclusive) is fully covered.
        """
        if begin > end:
            raise ValueError("Begin date must not be after end date.")
        for b, e in self.covered:
            if b <= begin and end <= e:
                return True
            if e < begin:
                continue
            if b > end:
                break
        return False

    def maximal_covered_range_containing(self, d: date) -> tuple[date, date] | None:
        """
        Returns the maximal continuously covered range (begin, end) that contains the given date,
        or None if the date is not in any covered range.
        """
        for b, e in self.covered:
            if b <= d <= e:
                return (b, e)
        return None 