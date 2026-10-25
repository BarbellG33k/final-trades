"""Pydantic response schemas for the public read-only API.

Envelopes (docs/ARCHITECTURE.md §7):
- lists: {data: [...], total, page, page_size}
- single resources: direct object
- errors: {error: short_code, message: human-readable}
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page[T](BaseModel):
    data: list[T]
    total: int
    page: int
    page_size: int


class ErrorEnvelope(BaseModel):
    error: str
    message: str


class ShowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    name: str


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    trigger: str
    status: str
    window_start: date | None
    window_end: date | None
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    discovered_count: int
    created_count: int
    updated_count: int
    rejected_count: int
    unresolved_count: int
    error_count: int
    backlog_remaining: int | None
    summary: str | None
    per_show: dict[str, str] = Field(default_factory=dict)


class SourceRunResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_key: str
    show_key: str | None
    status: str
    items_discovered: int
    items_processed: int
    started_at: datetime | None
    finished_at: datetime | None
    error_category: str | None
    error_summary: str | None


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    error_category: str
    source_key: str | None
    show_key: str | None
    processing_date: date | None
    stage: str
    summary: str
    first_occurred_at: datetime
    last_occurred_at: datetime
    occurrence_count: int
    attempt_count: int
    last_run_id: int | None
    resolved: bool
    resolved_at: datetime | None


class DateStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    show: str
    processing_date: date
    status: str
    is_trading_day: bool | None
    attempts: int
    first_attempted_at: datetime | None
    last_attempted_at: datetime | None
    last_run_id: int | None
    segment_id: int | None
    note: str | None


class RunDetail(RunSummary):
    source_results: list[SourceRunResultOut] = Field(default_factory=list)
    issues: list[IssueOut] = Field(default_factory=list)
    date_results: list[DateStatusOut] = Field(default_factory=list)


class AnalystBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    canonical_name: str
    affiliation: str | None


class InstrumentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    asset_type: str
    name: str | None


class RecommendationRow(BaseModel):
    id: int
    segment_date: date
    show: str
    analyst: AnalystBrief | None
    instrument: InstrumentBrief
    direction: str
    position_type: str
    thesis: str | None
    confidence: str
    verification_status: str
    extraction_method: str
    published_at: datetime | None
    source_urls: list[str] = Field(default_factory=list)


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_key: str
    url: str
    retrieved_at: datetime
    published_at: datetime | None
    content_sha256: str
    excerpt: str
    excerpt_kind: str


class PerformanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    horizon_days: int
    status: str
    entry_date: date | None
    entry_price: float | None
    entry_basis: str | None
    exit_date: date | None
    exit_price: float | None
    forward_return: float | None
    benchmark_symbol: str | None
    benchmark_return: float | None
    relative_return: float | None
    price_provider: str
    computed_at: datetime


class RecommendationDetail(RecommendationRow):
    review_notes: str | None = None
    analyst_title: str | None = None
    evidence: list[EvidenceOut] = Field(default_factory=list)
    performance: list[PerformanceOut] = Field(default_factory=list)


class HistoricalDateRow(BaseModel):
    the_date: date
    show: str
    status: str  # DateStatus
    coverage_status: str | None  # CoverageStatus
    recommendations_count: int
    is_trading_day: bool | None
    attempts: int
    note: str | None


class AnalystSummary(BaseModel):
    id: int
    canonical_name: str
    affiliation: str | None
    recommendation_count: int
    show_distribution: dict[str, int]
    top_instruments: list[tuple[str, int]]
    attributed_share_verified: float | None = None
    performance_sample_sizes: dict[int, int] = Field(default_factory=dict)
    insufficient_performance_data: bool = True


class PerformanceSummaryRow(BaseModel):
    horizon_days: int
    sample_size: int
    missing_count: int
    avg_forward_return: float | None
    avg_benchmark_return: float | None
    avg_relative_return: float | None
    win_rate: float | None
    short_sample_size: int = 0
    avg_short_relative_return: float | None = None


class PerformanceSummary(BaseModel):
    benchmark_symbol: str
    horizons: list[PerformanceSummaryRow]
    methodology: str
    disclaimer: str


class ShowCoverage(BaseModel):
    show: str
    total_dates: int
    collected: int
    verified_absent: int
    partial: int
    missing: int
    unchecked: int
    backlog: int
    monthly: list[dict[str, object]] = Field(default_factory=list)


class CoverageOut(BaseModel):
    window_start: date
    window_end: date
    shows: list[ShowCoverage]
    last_successful_check_by_source: dict[str, datetime | None]


class OverviewShowStatus(BaseModel):
    show: str
    last_collected_date: date | None
    last_success_run_id: int | None
    unresolved_dates: int
    failed_dates: int
    recent_recommendations: int


class OverviewOut(BaseModel):
    generated_at: datetime
    window: tuple[date, date]
    latest_run: RunSummary | None
    last_successful_run: RunSummary | None
    success_rate_14d: float | None
    runs_14d: int
    backlog_remaining: int
    recent_failures: list[IssueOut]
    shows: list[OverviewShowStatus]
    newest_recommendations: list[RecommendationRow]
    totals: dict[str, int]
