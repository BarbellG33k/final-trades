"""Persist a ParsedSegment: normalization, dedupe, multi-source merge.

Idempotency: the unique key (segment, analyst, instrument, direction) makes
re-ingestion safe; verification upgrades follow the lattice in normalize.py;
evidence rows dedupe on (recommendation, source, url, hash).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from final_trades.db import repositories as repo
from final_trades.db.models import Analyst, Instrument, Recommendation, Segment
from final_trades.db.seed import get_unattributed_analyst
from final_trades.domain import UNATTRIBUTED_ANALYST_NAME, VerificationStatus
from final_trades.pipeline.normalize import (
    canonicalize_analyst,
    normalize_instrument,
    upgrade_verification,
)
from final_trades.sources.contracts import ParsedSegment, RawRecommendation


@dataclass
class PersistResult:
    created: int = 0
    updated: int = 0
    rejected: int = 0
    unresolved: int = 0
    rejections: list[str] = field(default_factory=list)  # raw tokens that could not normalize


def _incoming_verification(raw: RawRecommendation) -> str:
    if raw.analyst_name_raw is None:
        return VerificationStatus.UNVERIFIED
    return VerificationStatus.VERIFIED


def _append_evidence(
    session: Session, rec: Recommendation, raw: RawRecommendation, seg: ParsedSegment
) -> bool:
    ev = raw.evidence
    if ev is None:
        return False
    source_keys = {seg.source_key} if seg.source_key else set()
    added = False
    for key in source_keys or {seg.source_key}:
        added |= repo.add_evidence(
            session,
            rec,
            source_key=key,
            url=ev.url,
            retrieved_at=ev.retrieved_at,
            content_sha256=ev.content_sha256,
            excerpt=ev.excerpt,
            excerpt_kind=ev.excerpt_kind,
            published_at=ev.published_at,
        )
    return added


def persist_segment(session: Session, seg: ParsedSegment) -> PersistResult:
    """Upsert one segment's recommendations; caller commits."""
    result = PersistResult()
    segment, _segment_created = repo.get_or_create_segment(
        session, seg.show, seg.segment_date, seg.title
    )

    for raw in seg.recommendations:
        instrument_norm = normalize_instrument(raw.ticker_raw)
        if instrument_norm is None:
            result.rejected += 1
            result.rejections.append(raw.ticker_raw)
            continue
        symbol, asset_type = instrument_norm
        instrument = repo.get_or_create_instrument(session, symbol, str(asset_type))

        canonical = canonicalize_analyst(raw.analyst_name_raw)
        if canonical is None:
            analyst = get_unattributed_analyst(session)
        else:
            analyst = repo.get_or_create_analyst(session, canonical)
            if raw.analyst_name_raw and raw.analyst_name_raw != canonical:
                repo.add_analyst_variant(session, analyst, raw.analyst_name_raw)

        incoming_verification = _incoming_verification(raw)
        existing = repo.find_recommendation(
            session, segment.id, analyst.id, instrument.id, str(raw.direction)
        )
        conflicts = repo.find_conflicting_directions(
            session, segment.id, analyst.id, instrument.id, str(raw.direction)
        )
        if conflicts:
            # Conflicting attribution/direction for the same call: mark all
            # readings unresolved; never silently pick a winner.
            note = (
                f"Conflicting direction recorded for {symbol} by "
                f"{canonical or UNATTRIBUTED_ANALYST_NAME} on {seg.segment_date}."
            )
            for c in conflicts:
                c.verification_status = VerificationStatus.UNRESOLVED
                c.review_notes = _merge_note(c.review_notes, note)
            if existing is not None:
                existing.verification_status = VerificationStatus.UNRESOLVED
                existing.review_notes = _merge_note(existing.review_notes, note)
                result.unresolved += 1
                _append_evidence(session, existing, raw, seg)
            else:
                rec = _new_recommendation(session, segment, analyst, instrument, raw)
                rec.verification_status = VerificationStatus.UNRESOLVED
                rec.review_notes = _merge_note(rec.review_notes, note)
                _append_evidence(session, rec, raw, seg)
                result.unresolved += 1
                result.created += 1
            session.flush()
            continue

        if existing is not None:
            changed = False
            evidence_added = _append_evidence(session, existing, raw, seg)
            distinct = repo.count_distinct_sources(session, existing.id)
            new_status = upgrade_verification(
                existing.verification_status, incoming_verification, distinct
            )
            if new_status != existing.verification_status:
                existing.verification_status = new_status
                changed = True
            if raw.thesis and not existing.thesis:
                existing.thesis = raw.thesis
                changed = True
            if raw.analyst_title_raw and analyst.affiliation is None:
                analyst.affiliation = raw.analyst_title_raw[:256]
                changed = True
            if raw.evidence and raw.evidence.published_at and existing.published_at is None:
                existing.published_at = raw.evidence.published_at
                changed = True
            if changed or evidence_added:
                result.updated += 1
            session.flush()
        else:
            rec = _new_recommendation(session, segment, analyst, instrument, raw)
            _append_evidence(session, rec, raw, seg)
            distinct = repo.count_distinct_sources(session, rec.id)
            rec.verification_status = upgrade_verification(
                rec.verification_status, incoming_verification, distinct
            )
            session.flush()
            result.created += 1

    return result


def _new_recommendation(
    session: Session,
    segment: Segment,
    analyst: Analyst,
    instrument: Instrument,
    raw: RawRecommendation,
) -> Recommendation:
    rec = Recommendation(
        segment_id=segment.id,
        analyst_id=analyst.id,
        instrument_id=instrument.id,
        direction=str(raw.direction),
        position_type=str(raw.position_type),
        thesis=raw.thesis,
        confidence=str(raw.confidence),
        verification_status=_incoming_verification(raw),
        extraction_method=str(raw.extraction_method),
        published_at=raw.evidence.published_at if raw.evidence else None,
    )
    session.add(rec)
    session.flush()
    return rec


def _merge_note(existing: str | None, note: str) -> str:
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing} | {note}"
