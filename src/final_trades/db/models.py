"""SQLAlchemy 2.0 declarative models — the persistence contract.

Conventions (see docs/data-model.md):
- Integer surrogate PKs; natural keys enforced with unique constraints.
- snake_case plural table names; idx_<table>_<cols> / uq_<table>_<cols>.
- UTC-aware timestamps everywhere (DateTime(timezone=True)).
- String columns for enums (values from final_trades.domain) for
  SQLite/Postgres portability — no native ENUM types.
- Evidence (recommendation_sources) is append-only; normalized records
  (recommendations) are upserted by the pipeline only.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Show(Base):
    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # ShowKey
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    segments: Mapped[list[Segment]] = relationship(back_populates="show")


class Analyst(Base):
    __tablename__ = "analysts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # Raw spellings/aliases observed in sources, e.g. ["Josh Brown", "Joshua Brown"]
    name_variants: Mapped[list[Any] | None] = mapped_column(JSON, default=list)
    affiliation: Mapped[str | None] = mapped_column(String(256))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recommendations: Mapped[list[Recommendation]] = relationship(back_populates="analyst")


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="other"
    )  # AssetType
    name: Mapped[str | None] = mapped_column(String(256))
    is_delisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Symbol history for renames/ticker changes: [{"old": "X", "new": "Y", "seen": "..."}]
    symbol_changes: Mapped[list[Any] | None] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recommendations: Mapped[list[Recommendation]] = relationship(back_populates="instrument")


class Segment(Base):
    """One show's Final Trade(s) segment on one date."""

    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("show_id", "segment_date", name="uq_segments_show_date"),
        Index("idx_segments_segment_date", "segment_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    segment_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    show: Mapped[Show] = relationship(back_populates="segments")
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="segment", cascade="all, delete-orphan"
    )


class Recommendation(Base):
    """A normalized analyst→instrument call from one segment.

    analyst_id is never NULL: unattributed calls point at the canonical
    '(unattributed)' analyst placeholder so the dedupe key stays total.
    """

    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint(
            "segment_id",
            "analyst_id",
            "instrument_id",
            "direction",
            name="uq_recommendations_segment_analyst_instrument_direction",
        ),
        Index("idx_recommendations_instrument", "instrument_id"),
        Index("idx_recommendations_analyst", "analyst_id"),
        Index("idx_recommendations_verification", "verification_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"), nullable=False)
    analyst_id: Mapped[int] = mapped_column(ForeignKey("analysts.id"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # Direction
    position_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    thesis: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium"
    )  # Confidence
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unverified"
    )  # VerificationStatus
    extraction_method: Mapped[str] = mapped_column(String(48), nullable=False)  # ExtractionMethod
    # Normalization/ambiguity notes, e.g. conflicting attributions observed.
    review_notes: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    segment: Mapped[Segment] = relationship(back_populates="recommendations")
    analyst: Mapped[Analyst] = relationship(back_populates="recommendations")
    instrument: Mapped[Instrument] = relationship(back_populates="recommendations")
    sources: Mapped[list[RecommendationSource]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan"
    )
    performance: Mapped[list[PerformanceObservation]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan"
    )


class Source(Base):
    """A registered acquisition source (adapter target)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # SourceKey
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # listing|article|rss|video
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RecommendationSource(Base):
    """Append-only evidence linking a recommendation to a source retrieval."""

    __tablename__ = "recommendation_sources"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id", "source_id", "url", "content_sha256", name="uq_recsources_evidence"
        ),
        Index("idx_recsources_recommendation", "recommendation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)  # <= MAX_EXCERPT_LENGTH
    excerpt_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="body")

    recommendation: Mapped[Recommendation] = relationship(back_populates="sources")
    source: Mapped[Source] = relationship()


class IngestionRun(Base):
    """One scheduled/backfill/manual execution of the pipeline."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("idx_runs_started_at", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # RunTrigger
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RUNNING")  # RunStatus
    window_start: Mapped[date | None] = mapped_column(Date)  # processing date range (inclusive)
    window_end: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unresolved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    backlog_remaining: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)

    source_results: Mapped[list[SourceRunResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class SourceRunResult(Base):
    """Per-source outcome within one run (per-show separation lives in show_key)."""

    __tablename__ = "source_run_results"
    __table_args__ = (Index("idx_sourcerun_run", "run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)  # SourceKey
    show_key: Mapped[str | None] = mapped_column(String(32))  # ShowKey, if source is show-specific
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # SourceRunStatus
    items_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(32))  # ErrorCategory
    error_summary: Mapped[str | None] = mapped_column(Text)  # sanitized, human-readable
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # safe diagnostics (never secrets)

    run: Mapped[IngestionRun] = relationship(back_populates="source_results")


class DateProcessingStatus(Base):
    """Durable per-(show, date) queue entry — the backlog IS this table."""

    __tablename__ = "date_processing_status"
    __table_args__ = (
        UniqueConstraint("show_id", "processing_date", name="uq_datestatus_show_date"),
        Index("idx_datestatus_status_date", "status", "processing_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    processing_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")  # DateStatus
    is_trading_day: Mapped[bool | None] = mapped_column(Boolean)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id"))
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    show: Mapped[Show] = relationship()


class Issue(Base):
    """Aggregated failure observability across scheduled attempts."""

    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint(
            "fingerprint",
            name="uq_issues_fingerprint",
        ),
        Index("idx_issues_unresolved", "resolved", "last_occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stable identity: hash of (error_category, source_key, show_key, date, stage)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    error_category: Mapped[str] = mapped_column(String(32), nullable=False)  # ErrorCategory
    source_key: Mapped[str | None] = mapped_column(String(64))
    show_key: Mapped[str | None] = mapped_column(String(32))
    processing_date: Mapped[date | None] = mapped_column(Date)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)  # Stage
    summary: Mapped[str] = mapped_column(Text, nullable=False)  # human-readable, sanitized
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # safe diagnostics only
    first_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # distinct runs
    last_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CoverageDaily(Base):
    """Materialized coverage aggregate per (show, date) for fast dashboard reads."""

    __tablename__ = "coverage_daily"
    __table_args__ = (
        UniqueConstraint("show_id", "coverage_date", name="uq_coverage_show_date"),
        Index("idx_coverage_date", "coverage_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    coverage_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # CoverageStatus
    recommendations_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sources_ok: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sources_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    show: Mapped[Show] = relationship()


class PerformanceObservation(Base):
    """Recomputable forward-return measurement for one recommendation/horizon.

    Stores the exact prices/timestamps used so calculations are auditable and
    reproducible without touching recommendation evidence.
    """

    __tablename__ = "performance_observations"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id", "horizon_days", "price_provider", name="uq_perf_rec_horizon"
        ),
        Index("idx_perf_horizon", "horizon_days"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)  # trading days
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # PerformanceStatus
    entry_date: Mapped[date | None] = mapped_column(Date)
    entry_price: Mapped[float | None] = mapped_column(Float)
    entry_basis: Mapped[str | None] = mapped_column(String(32))  # same_day_close|next_close
    exit_date: Mapped[date | None] = mapped_column(Date)
    exit_price: Mapped[float | None] = mapped_column(Float)
    forward_return: Mapped[float | None] = mapped_column(Float)  # decimal, e.g. 0.0231
    benchmark_symbol: Mapped[str | None] = mapped_column(String(32))
    benchmark_entry_price: Mapped[float | None] = mapped_column(Float)
    benchmark_exit_price: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    relative_return: Mapped[float | None] = mapped_column(Float)
    price_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="yfinance")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recommendation: Mapped[Recommendation] = relationship(back_populates="performance")
