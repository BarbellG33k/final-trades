"""Static NYSE market calendar for the 12-month collection window.

Distinguishes non-trading days (weekends + NYSE holidays) from missing data.
The holiday table is static and must be extended when the window moves
(see docs/operations.md runbook). Dates verified against NYSE holiday
schedules; 2026 observances follow the standard federal-holiday rules
(Jul 4 2026 Sat → observed Fri Jul 3; Christmas 2026 Fri).
"""

from __future__ import annotations

from datetime import date, timedelta

# NYSE full-day closures.
NYSE_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2025
        date(2025, 1, 1),  # New Year's Day
        date(2025, 1, 9),  # National Day of Mourning (Jimmy Carter)
        date(2025, 1, 20),  # MLK Day / Inauguration
        date(2025, 2, 17),  # Presidents Day
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 26),  # Memorial Day
        date(2025, 6, 19),  # Juneteenth
        date(2025, 7, 4),  # Independence Day
        date(2025, 9, 1),  # Labor Day
        date(2025, 11, 27),  # Thanksgiving
        date(2025, 12, 25),  # Christmas
        # 2026
        date(2026, 1, 1),  # New Year's Day
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Presidents Day
        date(2026, 4, 3),  # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 6, 19),  # Juneteenth
        date(2026, 7, 3),  # Independence Day (observed; Jul 4 is Saturday)
        date(2026, 9, 7),  # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
        # 2027 (window margin)
        date(2027, 1, 1),  # New Year's Day
    }
)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def previous_trading_day(d: date) -> date:
    """Strictly previous trading day (does not return d itself)."""
    cur = d - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def next_trading_day(d: date) -> date:
    """Strictly next trading day."""
    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def same_or_next_trading_day(d: date) -> date:
    return d if is_trading_day(d) else next_trading_day(d)


def trading_days_between(start: date, end: date) -> list[date]:
    """Inclusive list of trading days from start to end."""
    days: list[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


def count_trading_days(start: date, end: date) -> int:
    """Number of trading days in (start, end] — used for horizon offsets."""
    if end <= start:
        return 0
    return len(trading_days_between(start + timedelta(days=1), end))
