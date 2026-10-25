"""Bounded, fair backlog policy (pure functions).

Guarantees:
- current-day work gets reserved capacity first (never starved by backlog);
- backlog is processed oldest-first;
- a run never exceeds `max_dates` processing units;
- failed dates stay eligible for later runs (selection is stateless).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DateUnit:
    show: str  # ShowKey value
    date: date


@dataclass(frozen=True)
class WorkSelection:
    current_day: tuple[DateUnit, ...]
    backlog: tuple[DateUnit, ...]

    @property
    def all_units(self) -> tuple[DateUnit, ...]:
        return self.current_day + self.backlog


def select_work(
    eligible: list[DateUnit],
    today: date,
    max_dates: int,
    current_day_capacity_share: float,
) -> WorkSelection:
    """Split eligible units into current-day vs backlog within a total budget.

    `eligible` must contain only units that are actually pending/failed/
    unresolved (selection never touches COLLECTED/NO_SEGMENT rows).
    """
    if max_dates <= 0:
        return WorkSelection((), ())
    current = sorted((u for u in eligible if u.date == today), key=lambda u: u.show)
    backlog = sorted((u for u in eligible if u.date != today), key=lambda u: (u.date, u.show))

    current_budget = max(1, math.ceil(max_dates * current_day_capacity_share)) if current else 0
    selected_current = tuple(current[:current_budget])
    remaining = max_dates - len(selected_current)
    selected_backlog = tuple(backlog[:remaining]) if remaining > 0 else ()
    return WorkSelection(selected_current, selected_backlog)
