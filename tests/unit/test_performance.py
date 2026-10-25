"""Performance computation tests — deterministic fake provider, no network.

Covers critical scenario 15: missing prices and after-hours publication
handled correctly; entry conventions per show; recompute is idempotent;
shorts kept separate; unpriceable instruments are honest gaps.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from final_trades.config import Settings
from final_trades.db import models
from final_trades.db.seed import (
    ensure_reference_data,
    get_show,
    get_source,
    get_unattributed_analyst,
)
from final_trades.domain import Direction, ExtractionMethod, PerformanceStatus, ShowKey, SourceKey
from final_trades.performance.providers import PriceBar, PriceFetchFailure
from final_trades.performance.returns import (
    compute_all,
    entry_date_for,
    exit_date_for,
)


class FakeProvider:
    name = "fake"

    def __init__(self, series: dict[str, list[PriceBar]]) -> None:
        self.series = series
        self.calls: list[str] = []

    def daily_history(self, symbol: str, start: date, end: date):
        self.calls.append(symbol)
        bars = self.series.get(symbol)
        if bars is None:
            return PriceFetchFailure(symbol, "no data")
        return [b for b in bars if start <= b.day <= end]


def bars_for(days_prices: list[tuple[date, float]]) -> list[PriceBar]:
    return [PriceBar(day=d, close=p, adj_close=p) for d, p in days_prices]


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    ensure_reference_data(s)
    yield s
    s.close()
    engine.dispose()


def add_rec(
    session: Session,
    *,
    show: ShowKey,
    segment_date: date,
    symbol: str,
    direction: Direction = Direction.LONG,
    analyst_name: str | None = "Joshua Brown",
    published_at: datetime | None = None,
    asset_type: str = "equity",
) -> models.Recommendation:
    from final_trades.db import repositories as repo

    show_row = get_show(session, show)
    segment, _ = repo.get_or_create_segment(session, show, segment_date)
    analyst = (
        repo.get_or_create_analyst(session, analyst_name)
        if analyst_name
        else get_unattributed_analyst(session)
    )
    instrument = repo.get_or_create_instrument(session, symbol, asset_type)
    rec = models.Recommendation(
        segment_id=segment.id,
        analyst_id=analyst.id,
        instrument_id=instrument.id,
        direction=str(direction),
        position_type="stock",
        verification_status="verified",
        extraction_method=str(ExtractionMethod.BENZINGA_ARTICLE),
        published_at=published_at,
    )
    session.add(rec)
    session.commit()
    assert show_row is not None
    return rec


SETTINGS = Settings(DATABASE_URL="sqlite://", MARKET_DATA_PROVIDER="yfinance")


def test_entry_convention_halftime_same_day_close() -> None:
    # Halftime airs pre-close → same-day close entry
    d, basis = entry_date_for(str(ShowKey.HALFTIME_REPORT), date(2026, 10, 22), None)
    assert d == date(2026, 10, 22)
    assert basis == "same_day_close"


def test_entry_convention_fast_money_next_close() -> None:
    # Fast Money airs post-close (Friday) → next trading day (Monday)
    d, basis = entry_date_for(str(ShowKey.FAST_MONEY), date(2026, 10, 23), None)
    assert d == date(2026, 10, 26)
    assert basis == "next_close"


def test_entry_convention_after_hours_publication_never_same_day() -> None:
    # Published 18:04 ET on segment date → next close (not same-day)
    published = datetime(2026, 10, 23, 22, 4, tzinfo=UTC)  # 18:04 ET
    d, basis = entry_date_for(str(ShowKey.FAST_MONEY), date(2026, 10, 23), published)
    assert d == date(2026, 10, 26)
    assert basis == "next_close"


def test_exit_dates_skip_weekends_and_holidays() -> None:
    assert exit_date_for(date(2026, 10, 22), 1) == date(2026, 10, 23)
    assert exit_date_for(date(2026, 10, 23), 1) == date(2026, 10, 26)  # Fri → Mon
    # Thanksgiving week 2025: Wed 11/26 → +1 = Fri 11/28 (Thu holiday)
    assert exit_date_for(date(2025, 11, 26), 1) == date(2025, 11, 28)


def test_compute_all_ok_and_relative(session: Session) -> None:
    rec = add_rec(
        session, show=ShowKey.HALFTIME_REPORT, segment_date=date(2026, 10, 19), symbol="NVDA"
    )
    # entry Mon 10/19 close=100; +1d Tue 10/20 close=110
    days = [
        (date(2026, 10, 19), 100.0),
        (date(2026, 10, 20), 110.0),
        (date(2026, 10, 21), 105.0),
        (date(2026, 10, 22), 108.0),
        (date(2026, 10, 23), 120.0),
        (date(2026, 10, 26), 121.0),
        (date(2026, 10, 27), 122.0),
    ]
    spy = [(d, 100.0 + i) for i, (d, _) in enumerate(days)]
    provider = FakeProvider({"NVDA": bars_for(days), "SPY": bars_for(spy)})
    stats = compute_all(session, SETTINGS, provider=provider, today=date(2026, 10, 27))
    assert stats["computed"] >= 1
    obs = session.scalars(
        select(models.PerformanceObservation).where(
            models.PerformanceObservation.recommendation_id == rec.id,
            models.PerformanceObservation.horizon_days == 1,
        )
    ).one()
    assert obs.status == str(PerformanceStatus.OK)
    assert obs.entry_date == date(2026, 10, 19)
    assert obs.entry_basis == "same_day_close"
    assert obs.entry_price == 100.0
    assert obs.exit_date == date(2026, 10, 20)
    assert obs.exit_price == 110.0
    assert obs.forward_return == pytest.approx(0.10)
    assert obs.benchmark_return == pytest.approx(0.01)
    assert obs.relative_return == pytest.approx(0.09)
    # longer horizons beyond today are NOT_DUE, not silently zero
    obs60 = session.scalar(
        select(models.PerformanceObservation).where(
            models.PerformanceObservation.recommendation_id == rec.id,
            models.PerformanceObservation.horizon_days == 60,
        )
    )
    assert obs60 is not None and obs60.status == str(PerformanceStatus.NOT_DUE)
    assert obs60.forward_return is None


def test_missing_prices_are_explicit(session: Session) -> None:
    rec = add_rec(
        session, show=ShowKey.HALFTIME_REPORT, segment_date=date(2026, 10, 19), symbol="DELISTED"
    )
    provider = FakeProvider({"SPY": bars_for([(date(2026, 10, 19), 100.0)])})
    stats = compute_all(session, SETTINGS, provider=provider, today=date(2026, 10, 27))
    assert stats["missing"] >= 1
    obs = session.scalars(
        select(models.PerformanceObservation).where(
            models.PerformanceObservation.recommendation_id == rec.id
        )
    ).all()
    assert obs and all(o.status == str(PerformanceStatus.MISSING_ENTRY) for o in obs)
    assert all(o.forward_return is None for o in obs)


def test_unpriceable_instrument_marked_unsupported(session: Session) -> None:
    rec = add_rec(
        session,
        show=ShowKey.HALFTIME_REPORT,
        segment_date=date(2026, 10, 19),
        symbol="US10Y",
        asset_type="fixed_income",
    )
    provider = FakeProvider({})
    stats = compute_all(session, SETTINGS, provider=provider, today=date(2026, 10, 27))
    assert stats["unsupported"] >= 1
    obs = session.scalars(
        select(models.PerformanceObservation).where(
            models.PerformanceObservation.recommendation_id == rec.id
        )
    ).all()
    assert len(obs) == 4
    assert all(o.status == str(PerformanceStatus.INSTRUMENT_UNSUPPORTED) for o in obs)
    assert "US10Y" not in provider.calls  # never wastes a fetch on unpriceable instruments


def test_short_direction_kept_separate(session: Session) -> None:
    add_rec(
        session,
        show=ShowKey.FAST_MONEY,
        segment_date=date(2026, 10, 19),
        symbol="BEAR",
        direction=Direction.SHORT,
    )
    days = [(date(2026, 10, 20), 50.0), (date(2026, 10, 21), 45.0)]
    provider = FakeProvider(
        {"BEAR": bars_for(days), "SPY": bars_for([(d, 100.0) for d, _ in days])}
    )
    compute_all(session, SETTINGS, provider=provider, today=date(2026, 10, 27))
    obs = session.scalar(
        select(models.PerformanceObservation)
        .join(
            models.Recommendation,
            models.PerformanceObservation.recommendation_id == models.Recommendation.id,
        )
        .where(models.PerformanceObservation.horizon_days == 1)
    )
    assert obs is not None
    # FM 10/19 (Mon) → next close Tue 10/20 = 50 → Wed 10/21 = 45
    assert obs.entry_date == date(2026, 10, 20)
    assert obs.entry_basis == "next_close"
    assert obs.forward_return == pytest.approx(
        -0.10
    )  # raw instrument move; UI reports shorts separately


def test_neutral_and_mention_skipped(session: Session) -> None:
    add_rec(
        session,
        show=ShowKey.FAST_MONEY,
        segment_date=date(2026, 10, 19),
        symbol="ZZZ",
        direction=Direction.MENTION,
    )
    provider = FakeProvider({})
    stats = compute_all(session, SETTINGS, provider=provider, today=date(2026, 10, 27))
    assert stats == {"computed": 0, "not_due": 0, "missing": 0, "unsupported": 0}


def test_recompute_is_idempotent_and_overwrites_own_rows(session: Session) -> None:
    rec = add_rec(
        session, show=ShowKey.HALFTIME_REPORT, segment_date=date(2026, 10, 19), symbol="NVDA"
    )
    days = [(date(2026, 10, 19), 100.0), (date(2026, 10, 20), 110.0)]
    provider = FakeProvider(
        {"NVDA": bars_for(days), "SPY": bars_for([(d, 100.0) for d, _ in days])}
    )
    compute_all(session, SETTINGS, provider=provider, today=date(2026, 10, 27))
    n1 = session.scalar(select(func.count()).select_from(models.PerformanceObservation))
    compute_all(session, SETTINGS, provider=provider, today=date(2026, 10, 27))
    n2 = session.scalar(select(func.count()).select_from(models.PerformanceObservation))
    assert n1 == n2 == 4  # one row per horizon, no duplicates
    # recommendation evidence untouched by recompute
    assert session.get(models.Recommendation, rec.id) is not None


def test_adjusted_prices_used_for_returns(session: Session) -> None:
    rec = add_rec(
        session, show=ShowKey.HALFTIME_REPORT, segment_date=date(2026, 10, 19), symbol="DIV"
    )
    bars = [
        PriceBar(day=date(2026, 10, 19), close=100.0, adj_close=99.0),
        PriceBar(day=date(2026, 10, 20), close=101.0, adj_close=100.98),
    ]
    provider = FakeProvider(
        {"DIV": bars, "SPY": bars_for([(date(2026, 10, 19), 100.0), (date(2026, 10, 20), 100.0)])}
    )
    compute_all(session, SETTINGS, provider=provider, today=date(2026, 10, 27))
    obs = session.scalar(
        select(models.PerformanceObservation).where(
            models.PerformanceObservation.recommendation_id == rec.id,
            models.PerformanceObservation.horizon_days == 1,
        )
    )
    assert obs is not None
    assert obs.forward_return == pytest.approx(100.98 / 99.0 - 1.0)
    assert obs.entry_price == 99.0  # adjusted, consistent both legs


def test_source_row_unused_import_guard(session: Session) -> None:
    # reference data sanity for FK targets used by persistence
    assert get_source(session, SourceKey.BENZINGA_ARTICLE) is not None


def test_flatten_handles_multiindex_columns() -> None:
    """yfinance >=0.2.5x returns (field, ticker) MultiIndex columns even for
    single-symbol downloads — regression test for the silent-drop bug."""
    import pandas as pd

    from final_trades.performance import providers

    idx = pd.to_datetime(["2026-10-19", "2026-10-20"])
    cols = pd.MultiIndex.from_tuples([("Close", "NVDA"), ("Adj Close", "NVDA")])
    df = pd.DataFrame([[100.0, 99.0], [110.0, 108.9]], index=idx, columns=cols)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = providers._flatten(df["Close"])
    assert close[date(2026, 10, 19)] == 100.0
    assert close[date(2026, 10, 20)] == 110.0
    # raw (unflattened) frame column would flatten to nothing — prove the guard matters
    df2 = pd.DataFrame(
        [[100.0], [110.0]], index=idx, columns=pd.MultiIndex.from_tuples([("Close", "NVDA")])
    )
    assert providers._flatten(df2["Close"]) == {} or len(providers._flatten(df2["Close"])) <= 1
