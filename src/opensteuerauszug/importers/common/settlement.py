"""Settlement dates of US equity trades."""

from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import holidays


@lru_cache(maxsize=None)
def _nyse_holidays(year: int) -> Any:
    """Return cached NYSE holiday calendar for *year*."""
    return holidays.NYSE(years=year)  # type: ignore[attr-defined]


def _is_nyse_holiday(d: date) -> bool:
    """Return True if *d* is a NYSE exchange holiday (weekends excluded)."""
    return d in _nyse_holidays(d.year)


def next_business_day(d: date) -> date:
    """Return the next calendar day that is a NYSE trading day.

    Skips weekends and US exchange (NYSE) holidays so that settlement dates
    accurately reflect days on which the exchange is open for business.
    """
    result = d + timedelta(days=1)
    while result.weekday() >= 5 or _is_nyse_holiday(result):
        result += timedelta(days=1)
    return result


def settlement_date(trade_date: date) -> date:
    """Return the T+1 settlement date for a trade.

    US equities settled T+2 until May 2024, then switched to T+1.
    We use T+1 as the conservative default, skipping weekends and NYSE
    exchange holidays.
    """
    return next_business_day(trade_date)
