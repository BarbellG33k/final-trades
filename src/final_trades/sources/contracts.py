"""Typed DTOs exchanged between source adapters and the pipeline.

Adapters return these; they never touch the database. Field semantics are
documented in docs/ARCHITECTURE.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from final_trades.domain import (
    Confidence,
    Direction,
    ErrorCategory,
    ExtractionMethod,
    PositionType,
    ShowKey,
    Stage,
)


@dataclass(frozen=True)
class Evidence:
    """A retrieved source artifact supporting one or more recommendations."""

    url: str
    retrieved_at: datetime
    content_sha256: str
    excerpt: str  # short attributed excerpt, <= MAX_EXCERPT_LENGTH
    excerpt_kind: str = "body"  # body | title | summary | feed_item
    published_at: datetime | None = None


@dataclass(frozen=True)
class RawRecommendation:
    """One analyst→instrument call as read from a source, pre-normalization."""

    ticker_raw: str  # as written in source ("ZS", "10-year Treasury", "SK hynix")
    analyst_name_raw: str | None  # None → unattributed
    analyst_title_raw: str | None = None  # "managing partner at Capital Area Planning Group"
    direction: Direction = Direction.LONG
    position_type: PositionType = PositionType.UNKNOWN
    thesis: str | None = None  # supporting sentence(s), verbatim, trimmed
    confidence: Confidence = Confidence.MEDIUM
    extraction_method: ExtractionMethod = ExtractionMethod.BENZINGA_ARTICLE
    evidence: Evidence | None = None


@dataclass(frozen=True)
class ParsedSegment:
    """A fully parsed segment ready for normalization/persistence."""

    show: ShowKey
    segment_date: date
    title: str | None
    recommendations: tuple[RawRecommendation, ...]
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)
    # How segment_date was established: "published_minus_one_trading_day",
    # "rss_pubdate", "video_url_date", "body_weekday_reference".
    segment_date_basis: str = "unknown"
    source_key: str = ""


@dataclass(frozen=True)
class DiscoveredItem:
    """A candidate source record found during discovery (listing/RSS/sitemap)."""

    url: str
    show: ShowKey | None  # None if show must be determined from detail
    published_at: datetime | None
    title: str
    source_key: str
    # Hint from discovery (e.g. slug tickers); detail fetch remains authoritative.
    hint: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchFailure:
    """A bounded-attempt failure; feeds issues + source_run_results."""

    error_category: ErrorCategory
    stage: Stage
    summary: str  # human-readable, sanitized (no secrets, no full bodies)
    url: str | None = None
    detail: dict[str, object] = field(default_factory=dict)  # safe diagnostics


@dataclass(frozen=True)
class FetchResult:
    """Successful retrieval with provenance."""

    url: str
    status_code: int
    body: str
    content_sha256: str
    retrieved_at: datetime


FetchOutcome = FetchResult | FetchFailure
