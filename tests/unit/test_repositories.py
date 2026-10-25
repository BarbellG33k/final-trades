"""Unit tests for repository helpers: upserts, variants, issues, coverage."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from final_trades.db import models
from final_trades.db import repositories as repo
from final_trades.db.seed import ensure_reference_data, get_unattributed_analyst
from final_trades.domain import (
    AssetType,
    CoverageStatus,
    DateStatus,
    ErrorCategory,
    ShowKey,
    SourceKey,
    Stage,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", future=True)
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    ensure_reference_data(s)
    yield s
    s.close()
    engine.dispose()


def test_get_or_create_analyst_idempotent(session: Session) -> None:
    a1 = repo.get_or_create_analyst(session, "Joshua Brown")
    a2 = repo.get_or_create_analyst(session, "Joshua Brown")
    assert a1.id == a2.id


def test_add_analyst_variant_dedupes(session: Session) -> None:
    analyst = repo.get_or_create_analyst(session, "Joshua Brown")
    assert repo.add_analyst_variant(session, analyst, "Josh Brown") is True
    assert repo.add_analyst_variant(session, analyst, "Josh Brown") is False
    assert repo.add_analyst_variant(session, analyst, "Joshua Brown") is False
    assert analyst.name_variants == ["Josh Brown"]


def test_instrument_asset_type_upgrade(session: Session) -> None:
    weak = repo.get_or_create_instrument(session, "XLF", "other")
    assert weak.asset_type == "other"
    upgraded = repo.get_or_create_instrument(session, "XLF", str(AssetType.ETF))
    assert upgraded.id == weak.id
    assert upgraded.asset_type == str(AssetType.ETF)
    # never downgrade strong typing with 'other'
    repo.get_or_create_instrument(session, "XLF", "other")
    assert upgraded.asset_type == str(AssetType.ETF)


def test_get_or_create_segment_fills_title_later(session: Session) -> None:
    seg, created = repo.get_or_create_segment(session, ShowKey.FAST_MONEY, date(2026, 10, 23))
    assert created is True
    assert seg.title is None
    seg2, created2 = repo.get_or_create_segment(
        session, ShowKey.FAST_MONEY, date(2026, 10, 23), title="Final Trade: NVDA"
    )
    assert created2 is False
    assert seg2.id == seg.id
    assert seg2.title == "Final Trade: NVDA"


def test_evidence_dedupe_on_url_and_hash(session: Session) -> None:
    seg, _ = repo.get_or_create_segment(session, ShowKey.FAST_MONEY, date(2026, 10, 23))
    analyst = get_unattributed_analyst(session)
    instrument = repo.get_or_create_instrument(session, "NVDA", str(AssetType.EQUITY))
    rec = models.Recommendation(
        segment_id=seg.id,
        analyst_id=analyst.id,
        instrument_id=instrument.id,
        direction="long",
        position_type="stock",
        verification_status="unverified",
        extraction_method="cnbc_video_page",
    )
    session.add(rec)
    session.flush()
    kwargs = dict(  # noqa: C408
        source_key=SourceKey.CNBC_VIDEO_PAGE,
        url="https://www.cnbc.com/video/x.html",
        retrieved_at=datetime(2026, 10, 23, 22, 0, tzinfo=UTC),
        content_sha256="a" * 64,
        excerpt="Final Trade: NVDA",
        excerpt_kind="title",
        published_at=None,
    )
    assert repo.add_evidence(session, rec, **kwargs) is True
    assert repo.add_evidence(session, rec, **kwargs) is False
    assert repo.count_distinct_sources(session, rec.id) == 1
    # different source key → second evidence row, 2 distinct sources
    kwargs2 = dict(kwargs, source_key=SourceKey.CNBC_RSS_FAST_MONEY)
    assert repo.add_evidence(session, rec, **kwargs2) is True
    assert repo.count_distinct_sources(session, rec.id) == 2


def test_date_status_init_trading_vs_nontrading(session: Session) -> None:
    trading = repo.get_or_init_date_status(session, ShowKey.FAST_MONEY, date(2026, 10, 23), True)
    assert trading.status == str(DateStatus.PENDING)
    weekend = repo.get_or_init_date_status(session, ShowKey.FAST_MONEY, date(2026, 10, 24), False)
    assert weekend.status == str(DateStatus.NO_SEGMENT)


def test_issue_bumps_and_preserves_first_occurrence(session: Session) -> None:
    i1 = repo.record_issue(
        session,
        fingerprint="fp1",
        error_category=str(ErrorCategory.NETWORK),
        stage=str(Stage.FETCH),
        summary="timeout",
        run_id=None,
        source_key="benzinga_article",
        show_key="halftime_report",
        processing_date=date(2026, 10, 22),
    )
    first_seen = i1.first_occurred_at
    i2 = repo.record_issue(
        session,
        fingerprint="fp1",
        error_category=str(ErrorCategory.NETWORK),
        stage=str(Stage.FETCH),
        summary="timeout again",
        run_id=None,
        source_key="benzinga_article",
        show_key="halftime_report",
        processing_date=date(2026, 10, 22),
    )
    assert i2.id == i1.id
    assert i2.occurrence_count == 2
    assert i2.attempt_count == 2
    assert i2.first_occurred_at == first_seen
    assert i2.summary == "timeout again"
    repo.resolve_issue(session, "fp1")
    assert i2.resolved is True and i2.resolved_at is not None
    # re-occurrence after resolution reopens
    i3 = repo.record_issue(
        session,
        fingerprint="fp1",
        error_category=str(ErrorCategory.NETWORK),
        stage=str(Stage.FETCH),
        summary="reopened",
        run_id=None,
    )
    assert i3.resolved is False
    assert i3.occurrence_count == 3


def test_coverage_upsert_updates_in_place(session: Session) -> None:
    repo.upsert_coverage(
        session, ShowKey.FAST_MONEY, date(2026, 10, 23), str(CoverageStatus.PARTIAL), 0, 1, 0
    )
    repo.upsert_coverage(
        session, ShowKey.FAST_MONEY, date(2026, 10, 23), str(CoverageStatus.COMPLETE), 4, 1, 0
    )
    rows = session.scalars(
        select(models.CoverageDaily).where(models.CoverageDaily.coverage_date == date(2026, 10, 23))
    ).all()
    assert len(rows) == 1
    assert rows[0].status == str(CoverageStatus.COMPLETE)
    assert rows[0].recommendations_count == 4


def test_start_run_defaults(session: Session) -> None:
    run = repo.start_run(session, "scheduled", date(2026, 10, 1), date(2026, 10, 26))
    assert run.status == "RUNNING"
    assert run.started_at.tzinfo is not None
    assert run.created_count == 0
