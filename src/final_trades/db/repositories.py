"""Low-level repository helpers: idempotent upserts keyed on natural keys.

All writes go through these functions so uniqueness and merge semantics live
in one place (AGENTS.md boundary: pipeline/ is the only ingestion writer).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from final_trades.db.models import (
    Analyst,
    CoverageDaily,
    DateProcessingStatus,
    IngestionRun,
    Instrument,
    Issue,
    Recommendation,
    RecommendationSource,
    Segment,
    Show,
    Source,
)
from final_trades.db.seed import get_show, get_source
from final_trades.domain import ShowKey, SourceKey


def utcnow() -> datetime:
    return datetime.now(UTC)


def get_or_create_analyst(session: Session, canonical_name: str) -> Analyst:
    analyst = session.scalar(select(Analyst).where(Analyst.canonical_name == canonical_name))
    if analyst is None:
        analyst = Analyst(canonical_name=canonical_name, name_variants=[])
        session.add(analyst)
        session.flush()
    return analyst


def add_analyst_variant(session: Session, analyst: Analyst, raw_name: str) -> bool:
    """Record a raw spelling as an alias if not already known. True if added."""
    if raw_name == analyst.canonical_name:
        return False
    variants = list(analyst.name_variants or [])
    if raw_name in variants:
        return False
    variants.append(raw_name)
    analyst.name_variants = variants
    session.flush()
    return True


def get_or_create_instrument(session: Session, symbol: str, asset_type: str) -> Instrument:
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if instrument is None:
        instrument = Instrument(symbol=symbol, asset_type=asset_type)
        session.add(instrument)
        session.flush()
    elif instrument.asset_type in ("other", "unknown") and asset_type not in ("other", "unknown"):
        instrument.asset_type = asset_type  # upgrade weak typing when better evidence arrives
        session.flush()
    return instrument


def get_or_create_segment(
    session: Session, show: ShowKey, segment_date: date, title: str | None = None
) -> tuple[Segment, bool]:
    show_row = get_show(session, show)
    segment = session.scalar(
        select(Segment).where(Segment.show_id == show_row.id, Segment.segment_date == segment_date)
    )
    if segment is None:
        segment = Segment(show_id=show_row.id, segment_date=segment_date, title=title)
        session.add(segment)
        session.flush()
        return segment, True
    if title and not segment.title:
        segment.title = title
        session.flush()
    return segment, False


def find_recommendation(
    session: Session, segment_id: int, analyst_id: int, instrument_id: int, direction: str
) -> Recommendation | None:
    return session.scalar(
        select(Recommendation).where(
            Recommendation.segment_id == segment_id,
            Recommendation.analyst_id == analyst_id,
            Recommendation.instrument_id == instrument_id,
            Recommendation.direction == direction,
        )
    )


def find_conflicting_directions(
    session: Session, segment_id: int, analyst_id: int, instrument_id: int, direction: str
) -> list[Recommendation]:
    rows = session.scalars(
        select(Recommendation).where(
            Recommendation.segment_id == segment_id,
            Recommendation.analyst_id == analyst_id,
            Recommendation.instrument_id == instrument_id,
            Recommendation.direction != direction,
        )
    ).all()
    return list(rows)


def add_evidence(
    session: Session,
    recommendation: Recommendation,
    source_key: SourceKey | str,
    url: str,
    retrieved_at: datetime,
    content_sha256: str,
    excerpt: str,
    excerpt_kind: str,
    published_at: datetime | None,
) -> bool:
    """Append an evidence row unless identical evidence already exists. True if added."""
    source: Source = get_source(session, source_key)
    existing = session.scalar(
        select(RecommendationSource).where(
            RecommendationSource.recommendation_id == recommendation.id,
            RecommendationSource.source_id == source.id,
            RecommendationSource.url == url,
            RecommendationSource.content_sha256 == content_sha256,
        )
    )
    if existing is not None:
        return False
    session.add(
        RecommendationSource(
            recommendation_id=recommendation.id,
            source_id=source.id,
            url=url,
            retrieved_at=retrieved_at,
            published_at=published_at,
            content_sha256=content_sha256,
            excerpt=excerpt,
            excerpt_kind=excerpt_kind,
        )
    )
    session.flush()
    return True


def count_distinct_sources(session: Session, recommendation_id: int) -> int:
    rows = session.execute(
        select(RecommendationSource.source_id)
        .where(RecommendationSource.recommendation_id == recommendation_id)
        .distinct()
    ).all()
    return len(rows)


def get_or_init_date_status(
    session: Session, show: ShowKey, processing_date: date, is_trading_day: bool
) -> DateProcessingStatus:
    show_row: Show = get_show(session, show)
    row = session.scalar(
        select(DateProcessingStatus).where(
            DateProcessingStatus.show_id == show_row.id,
            DateProcessingStatus.processing_date == processing_date,
        )
    )
    if row is None:
        from final_trades.domain import DateStatus

        initial = DateStatus.PENDING if is_trading_day else DateStatus.NO_SEGMENT
        row = DateProcessingStatus(
            show_id=show_row.id,
            processing_date=processing_date,
            status=str(initial),
            is_trading_day=is_trading_day,
        )
        session.add(row)
        session.flush()
    return row


def upsert_coverage(
    session: Session,
    show: ShowKey,
    coverage_date: date,
    status: str,
    recommendations_count: int,
    sources_ok: int,
    sources_failed: int,
) -> None:
    show_row = get_show(session, show)
    row = session.scalar(
        select(CoverageDaily).where(
            CoverageDaily.show_id == show_row.id, CoverageDaily.coverage_date == coverage_date
        )
    )
    if row is None:
        row = CoverageDaily(show_id=show_row.id, coverage_date=coverage_date)
        session.add(row)
    row.status = status
    row.recommendations_count = recommendations_count
    row.sources_ok = sources_ok
    row.sources_failed = sources_failed
    row.last_checked_at = utcnow()
    session.flush()


def record_issue(
    session: Session,
    fingerprint: str,
    error_category: str,
    stage: str,
    summary: str,
    run_id: int | None,
    source_key: str | None = None,
    show_key: str | None = None,
    processing_date: date | None = None,
    detail: dict[str, Any] | None = None,
) -> Issue:
    """Create or bump an issue; preserves first_occurred and recovery history."""
    now = utcnow()
    issue = session.scalar(select(Issue).where(Issue.fingerprint == fingerprint))
    if issue is None:
        issue = Issue(
            fingerprint=fingerprint,
            error_category=error_category,
            source_key=source_key,
            show_key=show_key,
            processing_date=processing_date,
            stage=stage,
            summary=summary[:2000],
            detail=detail,
            first_occurred_at=now,
            last_occurred_at=now,
            occurrence_count=1,
            attempt_count=1,
            last_run_id=run_id,
            resolved=False,
        )
        session.add(issue)
    else:
        issue.error_category = error_category
        issue.stage = stage
        issue.summary = summary[:2000]
        if detail is not None:
            issue.detail = detail
        issue.last_occurred_at = now
        issue.occurrence_count += 1
        issue.attempt_count += 1  # one bounded attempt per run, so attempts == occurrences
        issue.last_run_id = run_id
        issue.resolved = False
        issue.resolved_at = None
    session.flush()
    return issue


def resolve_issue(session: Session, fingerprint: str) -> None:
    issue = session.scalar(select(Issue).where(Issue.fingerprint == fingerprint))
    if issue is not None and not issue.resolved:
        issue.resolved = True
        issue.resolved_at = utcnow()
        session.flush()


def start_run(session: Session, trigger: str, window_start: date, window_end: date) -> IngestionRun:
    run = IngestionRun(
        trigger=trigger,
        status="RUNNING",
        window_start=window_start,
        window_end=window_end,
        started_at=utcnow(),
    )
    session.add(run)
    session.flush()
    return run
