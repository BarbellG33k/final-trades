"""Unit tests for the static NYSE market calendar."""

from __future__ import annotations

from datetime import date

from final_trades.market_calendar import (
    count_trading_days,
    is_trading_day,
    next_trading_day,
    previous_trading_day,
    same_or_next_trading_day,
    trading_days_between,
)


def test_weekends_are_not_trading_days() -> None:
    assert not is_trading_day(date(2026, 10, 24))  # Saturday
    assert not is_trading_day(date(2026, 10, 25))  # Sunday
    assert is_trading_day(date(2026, 10, 23))  # Friday


def test_known_holidays() -> None:
    assert not is_trading_day(date(2026, 1, 1))  # New Year's
    assert not is_trading_day(date(2026, 7, 3))  # Jul 4 observed (Sat holiday)
    assert not is_trading_day(date(2026, 11, 26))  # Thanksgiving
    assert not is_trading_day(date(2025, 1, 9))  # Carter mourning day
    assert not is_trading_day(date(2025, 11, 27))  # Thanksgiving 2025


def test_previous_trading_day_skips_weekend_and_holiday() -> None:
    # Monday after Thanksgiving 2025 (Thu 11/27 holiday, Fri 11/28 traded)
    assert previous_trading_day(date(2025, 12, 1)) == date(2025, 11, 28)
    # Day after Christmas 2025 (Thu holiday) → Wed
    assert previous_trading_day(date(2025, 12, 26)) == date(2025, 12, 24)
    # Monday → Friday
    assert previous_trading_day(date(2026, 10, 26)) == date(2026, 10, 23)


def test_next_trading_day() -> None:
    assert next_trading_day(date(2026, 10, 23)) == date(2026, 10, 26)
    assert next_trading_day(date(2025, 12, 24)) == date(2025, 12, 26)


def test_same_or_next_trading_day() -> None:
    assert same_or_next_trading_day(date(2026, 10, 23)) == date(2026, 10, 23)
    assert same_or_next_trading_day(date(2026, 10, 24)) == date(2026, 10, 26)


def test_trading_days_between_inclusive() -> None:
    days = trading_days_between(date(2026, 10, 19), date(2026, 10, 25))
    assert days == [
        date(2026, 10, 19),
        date(2026, 10, 20),
        date(2026, 10, 21),
        date(2026, 10, 22),
        date(2026, 10, 23),
    ]


def test_count_trading_days_excludes_start() -> None:
    assert count_trading_days(date(2026, 10, 19), date(2026, 10, 23)) == 4
    assert count_trading_days(date(2026, 10, 23), date(2026, 10, 23)) == 0
    assert count_trading_days(date(2026, 10, 23), date(2026, 10, 19)) == 0
