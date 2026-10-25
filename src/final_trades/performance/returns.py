"""Forward-return computation — deterministic, auditable, gap-honest.

Conventions (docs/DECISIONS.md D-009):
- Entry basis: Halftime Report airs 12:00-13:00 ET (pre-close) → entry at
  the segment day's close. Fast Money airs ~17:00-18:00 ET (post-close) →
  entry at the NEXT trading day's close. If a recommendation carries a
  publish timestamp before 16:00 ET on the segment date, same-day close is
  used regardless of show.
- Exit: close `horizon` trading days after the entry date.
- Returns use adjusted closes (dividend/split consistent on both legs).
- forward_return is the INSTRUMENT's raw move for both directions; short
  calls are reported separately (a negative relative return favors a short).
- Missing prices become explicit statuses, never silent zeros.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from final_trades.config import Settings
from final_trades.db.models import PerformanceObservation, Recommendation, Segment, Show
from final_trades.domain import (
    PERFORMANCE_HORIZONS,
    AssetType,
    Direction,
    PerformanceStatus,
    ShowKey,
)
from final_trades.market_calendar import next_trading_day, same_or_next_trading_day
from final_trades.performance.providers import (
    PriceBar,
    PriceFetchFailure,
    PriceProvider,
    make_provider,
)

ET = ZoneInfo("America/New_York")
MARKET_CLOSE_ET = time(16, 0)

# Instruments we refuse to price (yield quotes, sector words, etc.)
UNPRICEABLE_SYMBOLS = frozenset({"US10Y", "TELECOM"})
# Asset types without a reliable free price series.
UNPRICEABLE_ASSETS = frozenset({str(AssetType.OTHER), str(AssetType.INDEX)})


@dataclass
class ComputeStats:
    computed: int = 0
    not_due: int = 0
    missing: int = 0
    unsupported: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "computed": self.computed,
            "not_due": self.not_due,
            "missing": self.missing,
            "unsupported": self.unsupported,
        }


@dataclass(frozen=True)
class EntryInfo:
    day: date
    basis: str
    bar: PriceBar | None


@dataclass(frozen=True)
class ExitInfo:
    day: date
    bench_entry: PriceBar | None
    bench_exit: PriceBar | None


@dataclass(frozen=True)
class ReturnInfo:
    forward: float
    benchmark: float | None
    relative: float | None
    exit_bar: PriceBar


class PriceCache:
    """Per-run cache: one history fetch per symbol."""

    def __init__(self, provider: PriceProvider) -> None:
        self._provider = provider
        self._cache: dict[str, list[PriceBar] | PriceFetchFailure] = {}

    def get(self, symbol: str, start: date, end: date) -> list[PriceBar] | PriceFetchFailure:
        if symbol not in self._cache:
            self._cache[symbol] = self._provider.daily_history(symbol, start, end)
        return self._cache[symbol]


def entry_date_for(
    show_key: str, segment_date: date, published_at: datetime | None
) -> tuple[date, str]:
    """Returns (entry_date, basis). See module docstring for conventions."""
    if published_at is not None:
        pub_et = published_at.astimezone(ET)
        if pub_et.date() == segment_date and pub_et.time() < MARKET_CLOSE_ET:
            return same_or_next_trading_day(segment_date), "same_day_close"
    if show_key == str(ShowKey.HALFTIME_REPORT):
        return same_or_next_trading_day(segment_date), "same_day_close"
    return next_trading_day(segment_date), "next_close"


def exit_date_for(entry: date, horizon: int) -> date:
    cur = entry
    for _ in range(horizon):
        cur = next_trading_day(cur)
    return cur


def _bar_on(bars: list[PriceBar], day: date) -> PriceBar | None:
    """Exact trading-day bar; None when absent (halt/delist gaps)."""
    for bar in bars:
        if bar.day == day:
            return bar
        if bar.day > day:
            return None
    return None


def compute_all(
    session: Session,
    settings: Settings,
    provider: PriceProvider | None = None,
    today: date | None = None,
) -> dict[str, int]:
    today = today or date.today()
    prov = provider or make_provider(settings)
    cache = PriceCache(prov)
    stats = ComputeStats()
    benchmark = settings.benchmark_symbol

    rows = session.execute(
        select(Recommendation, Segment.segment_date, Show.key)
        .join(Segment, Recommendation.segment_id == Segment.id)
        .join(Show, Segment.show_id == Show.id)
        .join(Recommendation.instrument)
    ).all()
    if not rows:
        session.commit()
        return stats.as_dict()

    earliest = min(r[1] for r in rows)
    bench_bars = cache.get(benchmark, earliest - timedelta(days=5), today)

    for rec, segment_date, show_key in rows:
        instrument = rec.instrument
        if (
            instrument.symbol in UNPRICEABLE_SYMBOLS
            or str(instrument.asset_type) in UNPRICEABLE_ASSETS
        ):
            for horizon in PERFORMANCE_HORIZONS:
                _upsert(
                    session,
                    rec,
                    prov.name,
                    benchmark,
                    PerformanceStatus.INSTRUMENT_UNSUPPORTED,
                    horizon,
                )
            stats.unsupported += 1
            continue
        if rec.direction in (str(Direction.NEUTRAL), str(Direction.MENTION)):
            continue  # not a directional call; no return computed

        entry_day, basis = entry_date_for(show_key, segment_date, rec.published_at)
        fetched = cache.get(instrument.symbol, entry_day - timedelta(days=5), today)
        bars: list[PriceBar] = [] if isinstance(fetched, PriceFetchFailure) else fetched
        entry_bar = _bar_on(bars, entry_day)
        if entry_bar is None:
            for horizon in PERFORMANCE_HORIZONS:
                _upsert(
                    session,
                    rec,
                    prov.name,
                    benchmark,
                    PerformanceStatus.MISSING_ENTRY,
                    horizon,
                    entry=EntryInfo(entry_day, basis, None),
                )
            stats.missing += 1
            continue

        for horizon in PERFORMANCE_HORIZONS:
            exit_day = exit_date_for(entry_day, horizon)
            if exit_day > today:
                _upsert(
                    session,
                    rec,
                    prov.name,
                    benchmark,
                    PerformanceStatus.NOT_DUE,
                    horizon,
                    entry=EntryInfo(entry_day, basis, entry_bar),
                )
                stats.not_due += 1
                continue
            exit_bar = _bar_on(bars, exit_day)
            bench_entry = (
                _bar_on(bench_bars, entry_day)
                if not isinstance(bench_bars, PriceFetchFailure)
                else None
            )
            bench_exit = (
                _bar_on(bench_bars, exit_day)
                if not isinstance(bench_bars, PriceFetchFailure)
                else None
            )
            exit_info = ExitInfo(exit_day, bench_entry, bench_exit)
            if exit_bar is None:
                _upsert(
                    session,
                    rec,
                    prov.name,
                    benchmark,
                    PerformanceStatus.MISSING_EXIT,
                    horizon,
                    entry=EntryInfo(entry_day, basis, entry_bar),
                    exit_info=exit_info,
                )
                stats.missing += 1
                continue
            fwd = exit_bar.adj_close / entry_bar.adj_close - 1.0
            bench_ret = (
                bench_exit.adj_close / bench_entry.adj_close - 1.0
                if bench_entry and bench_exit
                else None
            )
            rel = fwd - bench_ret if bench_ret is not None else None
            _upsert(
                session,
                rec,
                prov.name,
                benchmark,
                PerformanceStatus.OK,
                horizon,
                entry=EntryInfo(entry_day, basis, entry_bar),
                exit_info=exit_info,
                returns=ReturnInfo(fwd, bench_ret, rel, exit_bar),
            )
            stats.computed += 1
    session.commit()
    return stats.as_dict()


def _upsert(
    session: Session,
    rec: Recommendation,
    provider_name: str,
    benchmark: str,
    status: PerformanceStatus,
    horizon: int,
    entry: EntryInfo | None = None,
    exit_info: ExitInfo | None = None,
    returns: ReturnInfo | None = None,
) -> None:
    row = session.scalar(
        select(PerformanceObservation).where(
            PerformanceObservation.recommendation_id == rec.id,
            PerformanceObservation.horizon_days == horizon,
            PerformanceObservation.price_provider == provider_name,
        )
    )
    if row is None:
        row = PerformanceObservation(
            recommendation_id=rec.id,
            horizon_days=horizon,
            price_provider=provider_name,
        )
        session.add(row)
    row.status = str(status)
    row.computed_at = datetime.now(UTC)
    row.benchmark_symbol = benchmark

    row.entry_date = entry.day if entry else None
    row.entry_basis = entry.basis if entry else None
    row.entry_price = entry.bar.adj_close if entry and entry.bar else None

    row.exit_date = exit_info.day if exit_info else None
    row.benchmark_entry_price = (
        exit_info.bench_entry.adj_close if exit_info and exit_info.bench_entry else None
    )
    row.benchmark_exit_price = (
        exit_info.bench_exit.adj_close if exit_info and exit_info.bench_exit else None
    )

    if returns:
        row.forward_return = returns.forward
        row.benchmark_return = returns.benchmark
        row.relative_return = returns.relative
        row.exit_price = returns.exit_bar.adj_close
    else:
        row.forward_return = None
        row.relative_return = None
        row.exit_price = None
        if exit_info is None or exit_info.bench_entry is None or exit_info.bench_exit is None:
            row.benchmark_return = None
        else:
            row.benchmark_return = (
                exit_info.bench_exit.adj_close / exit_info.bench_entry.adj_close - 1.0
            )
    session.flush()
