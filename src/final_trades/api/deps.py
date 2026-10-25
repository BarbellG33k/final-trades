"""API dependencies: read-only session, pagination, bounded filters, TTL cache."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from final_trades.config import Settings, get_settings
from final_trades.db.session import get_session

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
# Hard cap on any date-range query (12-month window + margin).
MAX_RANGE_DAYS = 400


def get_db() -> Iterator[Session]:
    """Yield a session for read-only use.

    Production deploys point the API at a read-only DB role; the session
    itself only issues SELECTs (enforced by route code + audit tests).
    """
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_api_settings() -> Settings:
    return get_settings()


DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_api_settings)]


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


PageDep = Annotated[PageParams, Depends(page_params)]


def date_range(
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> tuple[date | None, date | None]:
    if date_from and date_to and (date_to - date_from).days > MAX_RANGE_DAYS:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="date range exceeds maximum of 400 days")
    if date_from and date_to and date_from > date_to:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="date_from must be <= date_to")
    return date_from, date_to


DateRangeDep = Annotated[tuple[date | None, date | None], Depends(date_range)]


class TtlCache:
    """Tiny in-process TTL cache for expensive summary endpoints.

    Single-instance deployments (Cloud Run min-instances=0..1) make an
    in-process cache sufficient; multi-instance would need shared cache.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get_or_set(self, key: str, ttl_seconds: int, producer: Callable[[], Any]) -> Any:
        now = time.monotonic()
        hit = self._store.get(key)
        if hit is not None and now - hit[0] < ttl_seconds:
            return hit[1]
        value = producer()
        self._store[key] = (now, value)
        return value

    def clear(self) -> None:
        self._store.clear()


_cache = TtlCache()


def get_cache() -> TtlCache:
    return _cache
