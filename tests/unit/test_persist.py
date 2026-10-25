"""Unit tests for persist_segment merge semantics (DTO-driven, no HTTP)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from final_trades.db import models
from final_trades.db.seed import ensure_reference_data, get_unattributed_analyst
from final_trades.domain import (
    Confidence,
    Direction,
    ExtractionMethod,
    ShowKey,
    SourceKey,
    VerificationStatus,
)
from final_trades.pipeline.persist import persist_segment
from final_trades.sources.contracts import Evidence, ParsedSegment, RawRecommendation

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def make_evidence(url: str = "https://www.benzinga.com/a/1", sha: str = "a" * 64) -> Evidence:
    return Evidence(
        url=url,
        retrieved_at=NOW,
        content_sha256=sha,
        excerpt="Brown picked NVDA.",
        published_at=NOW,
    )


def make_segment(recs: list[RawRecommendation], d: date = date(2026, 10, 22)) -> ParsedSegment:
    return ParsedSegment(
        show=ShowKey.HALFTIME_REPORT,
        segment_date=d,
        title="Final Trades",
        recommendations=tuple(recs),
        evidence=(make_evidence(),),
        source_key=str(SourceKey.BENZINGA_ARTICLE),
    )


def rec(
    ticker: str = "NVDA",
    analyst: str | None = "Joshua Brown",
    direction: Direction = Direction.LONG,
    thesis: str | None = "picked Nvidia",
    method: ExtractionMethod = ExtractionMethod.BENZINGA_ARTICLE,
    evidence: Evidence | None = None,
) -> RawRecommendation:
    return RawRecommendation(
        ticker_raw=ticker,
        analyst_name_raw=analyst,
        direction=direction,
        thesis=thesis,
        confidence=Confidence.HIGH,
        extraction_method=method,
        evidence=evidence if evidence is not None else make_evidence(),
    )


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", future=True)
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    ensure_reference_data(s)
    yield s
    s.close()
    engine.dispose()


def test_create_and_second_ingest_updates_without_duplicates(session: Session) -> None:
    r1 = persist_segment(session, make_segment([rec()]))
    session.commit()
    assert (r1.created, r1.updated) == (1, 0)
    r2 = persist_segment(session, make_segment([rec()]))
    session.commit()
    assert (r2.created, r2.updated) == (0, 0)  # identical re-ingest changes nothing
    assert session.scalar(select(models.Recommendation)) is not None


def test_second_source_corroborates(session: Session) -> None:
    persist_segment(session, make_segment([rec()]))
    session.commit()
    # same call from a different source with different evidence
    ev2 = make_evidence(url="https://www.cnbc.com/video/x.html", sha="b" * 64)
    seg2 = ParsedSegment(
        show=ShowKey.HALFTIME_REPORT,
        segment_date=date(2026, 10, 22),
        title=None,
        recommendations=(rec(method=ExtractionMethod.CNBC_VIDEO_PAGE, evidence=ev2, thesis=None),),
        evidence=(ev2,),
        source_key=str(SourceKey.CNBC_VIDEO_PAGE),
    )
    r = persist_segment(session, seg2)
    session.commit()
    assert r.updated == 1
    row = session.scalar(select(models.Recommendation))
    assert row is not None
    assert row.verification_status == VerificationStatus.CORROBORATED
    assert len(row.sources) == 2


def test_thesis_backfill_counts_as_update(session: Session) -> None:
    persist_segment(session, make_segment([rec(thesis=None)]))
    session.commit()
    r = persist_segment(session, make_segment([rec(thesis="late thesis")]))
    session.commit()
    assert r.updated == 1
    row = session.scalar(select(models.Recommendation))
    assert row is not None and row.thesis == "late thesis"


def test_unnormalizable_instrument_rejected(session: Session) -> None:
    r = persist_segment(session, make_segment([rec(ticker="some weird phrase!!")]))
    session.commit()
    assert r.rejected == 1
    assert r.rejections == ["some weird phrase!!"]
    assert session.scalar(select(models.Recommendation)) is None


def test_unattributed_uses_placeholder_analyst(session: Session) -> None:
    r = persist_segment(
        session,
        make_segment([rec(analyst=None, method=ExtractionMethod.CNBC_VIDEO_PAGE, thesis=None)]),
    )
    session.commit()
    assert r.created == 1
    row = session.scalar(select(models.Recommendation))
    placeholder = get_unattributed_analyst(session)
    assert row is not None and row.analyst_id == placeholder.id
    assert row.verification_status == VerificationStatus.UNVERIFIED


def test_analyst_alias_canonicalization(session: Session) -> None:
    persist_segment(session, make_segment([rec(analyst="Josh Brown")]))
    session.commit()
    analyst = session.scalar(
        select(models.Analyst).where(models.Analyst.canonical_name == "Joshua Brown")
    )
    assert analyst is not None
    assert "Josh Brown" in (analyst.name_variants or [])


def test_conflict_marks_both_unresolved(session: Session) -> None:
    persist_segment(session, make_segment([rec(direction=Direction.LONG)]))
    session.commit()
    r = persist_segment(
        session, make_segment([rec(direction=Direction.SHORT, thesis="is bearish and short")])
    )
    session.commit()
    assert r.unresolved == 1
    rows = list(session.scalars(select(models.Recommendation)))
    assert len(rows) == 2
    assert all(row.verification_status == VerificationStatus.UNRESOLVED for row in rows)
    assert all(row.review_notes and "Conflicting" in row.review_notes for row in rows)
