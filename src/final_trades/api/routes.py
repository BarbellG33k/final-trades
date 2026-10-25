"""Public read-only API routes. GET only — no mutation, no collection triggers.

All list endpoints are paginated (default 20, max 100) with validated,
bounded filters. Errors use the generic envelope; no stack traces or
environment details ever reach clients (see middleware + app.py handlers).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from final_trades.api.deps import DateRangeDep, DbDep, PageDep, SettingsDep, get_cache
from final_trades.api.schemas import (
    AnalystBrief,
    AnalystSummary,
    CoverageOut,
    DateStatusOut,
    EvidenceOut,
    HistoricalDateRow,
    InstrumentBrief,
    IssueOut,
    OverviewOut,
    OverviewShowStatus,
    Page,
    PerformanceOut,
    PerformanceSummary,
    PerformanceSummaryRow,
    RecommendationDetail,
    RecommendationRow,
    RunDetail,
    RunSummary,
    ShowCoverage,
    SourceRunResultOut,
)
from final_trades.db.models import (
    Analyst,
    CoverageDaily,
    DateProcessingStatus,
    IngestionRun,
    Instrument,
    Issue,
    PerformanceObservation,
    Recommendation,
    RecommendationSource,
    Segment,
    Show,
    Source,
    SourceRunResult,
)
from final_trades.domain import DateStatus, RunStatus, ShowKey

router = APIRouter(prefix="/api/v1")

ShowFilter = Literal["halftime_report", "fast_money"]
DirectionFilter = Literal["long", "short", "neutral", "mention"]
VerificationFilter = Literal["verified", "unverified", "unresolved", "corroborated"]
RunStatusFilter = Literal["RUNNING", "SUCCESS", "PARTIAL_SUCCESS", "FAILED"]

PERFORMANCE_METHODOLOGY = (
    "Forward returns measured over 1/5/20/60 trading days. Entry convention: "
    "recommendations published at or after 16:00 ET enter at the next trading "
    "day's close; earlier publications enter at the same day's close. Prices "
    "are dividend/split-adjusted closes from the configured free provider. "
    "Benchmark: SPY total return. Short-direction calls are reported separately "
    "and never netted into long statistics. Instruments without reliable price "
    "data (delisted, word-named, derivatives) are reported as gaps."
)
PERFORMANCE_DISCLAIMER = (
    "Descriptive statistics about television segments. Not investment advice; "
    "past performance does not guarantee future results."
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rec_rows(session: Session, rec_ids: list[int]) -> list[RecommendationRow]:
    if not rec_ids:
        return []
    recs = session.scalars(
        select(Recommendation)
        .options(
            joinedload(Recommendation.segment).joinedload(Segment.show),
            joinedload(Recommendation.analyst),
            joinedload(Recommendation.instrument),
        )
        .where(Recommendation.id.in_(rec_ids))
    ).all()
    by_id = {r.id: r for r in recs}
    urls = session.execute(
        select(RecommendationSource.recommendation_id, RecommendationSource.url).where(
            RecommendationSource.recommendation_id.in_(rec_ids)
        )
    ).all()
    urls_by_rec: dict[int, list[str]] = {}
    for rec_id, url in urls:
        urls_by_rec.setdefault(rec_id, []).append(url)
    rows = []
    for rid in rec_ids:  # preserve caller ordering
        r = by_id.get(rid)
        if r is None:
            continue
        rows.append(
            RecommendationRow(
                id=r.id,
                segment_date=r.segment.segment_date,
                show=r.segment.show.key,
                analyst=(
                    AnalystBrief.model_validate(r.analyst)
                    if r.analyst.canonical_name != "(unattributed)"
                    else None
                ),
                instrument=InstrumentBrief.model_validate(r.instrument),
                direction=r.direction,
                position_type=r.position_type,
                thesis=r.thesis,
                confidence=r.confidence,
                verification_status=r.verification_status,
                extraction_method=r.extraction_method,
                published_at=r.published_at,
                source_urls=sorted(set(urls_by_rec.get(r.id, []))),
            )
        )
    return rows


def _newest_recommendation_ids(session: Session, limit: int) -> list[int]:
    rows = session.execute(
        select(Recommendation.id)
        .join(Segment, Recommendation.segment_id == Segment.id)
        .order_by(Segment.segment_date.desc(), Recommendation.id.desc())
        .limit(limit)
    ).all()
    return [r[0] for r in rows]


def _run_summary(session: Session, run: IngestionRun) -> RunSummary:
    out = RunSummary.model_validate(run)
    out.per_show = _per_show_from_summary(run.summary)
    return out


def _per_show_from_summary(summary: str | None) -> dict[str, str]:
    per_show: dict[str, str] = {}
    if summary and "|" in summary:
        for part in summary.split("|", 1)[1].split():
            if "=" in part:
                key, _, val = part.partition("=")
                per_show[key] = val
    return per_show


def _avg_attr(observations: list[PerformanceObservation], attr: str) -> float | None:
    values = [v for v in (getattr(o, attr) for o in observations) if v is not None]
    return round(sum(values) / len(values), 5) if values else None


def _run_or_404(session: Session, run_id: int) -> IngestionRun:
    run: IngestionRun | None = session.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=OverviewOut)
def get_overview(session: DbDep, settings: SettingsDep) -> OverviewOut:
    cache = get_cache()

    def produce() -> OverviewOut:
        now = datetime.now(UTC)
        latest = session.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()))
        last_success = session.scalar(
            select(IngestionRun)
            .where(IngestionRun.status == str(RunStatus.SUCCESS))
            .order_by(IngestionRun.started_at.desc())
        )
        since = now - timedelta(days=14)
        runs_14d = session.execute(
            select(IngestionRun.status).where(IngestionRun.started_at >= since)
        ).all()
        finished = [r[0] for r in runs_14d if r[0] != str(RunStatus.RUNNING)]
        success_rate = (
            round(sum(1 for s in finished if s == str(RunStatus.SUCCESS)) / len(finished), 3)
            if finished
            else None
        )
        backlog = int(
            session.scalar(
                select(func.count())
                .select_from(DateProcessingStatus)
                .where(
                    DateProcessingStatus.status.in_(
                        [
                            str(DateStatus.PENDING),
                            str(DateStatus.FAILED),
                            str(DateStatus.UNRESOLVED),
                        ]
                    ),
                    DateProcessingStatus.is_trading_day.is_(True),
                    DateProcessingStatus.processing_date >= settings.backfill_start_date,
                    DateProcessingStatus.processing_date <= settings.backfill_end_date,
                )
            )
            or 0
        )
        failures = session.scalars(
            select(Issue)
            .where(Issue.resolved.is_(False))
            .order_by(Issue.last_occurred_at.desc())
            .limit(10)
        ).all()
        shows: list[OverviewShowStatus] = []
        for show in ShowKey:
            show_row = session.scalar(select(Show).where(Show.key == str(show)))
            if show_row is None:
                continue
            last_collected = session.scalar(
                select(func.max(DateProcessingStatus.processing_date)).where(
                    DateProcessingStatus.show_id == show_row.id,
                    DateProcessingStatus.status == str(DateStatus.COLLECTED),
                )
            )
            unresolved = int(
                session.scalar(
                    select(func.count())
                    .select_from(DateProcessingStatus)
                    .where(
                        DateProcessingStatus.show_id == show_row.id,
                        DateProcessingStatus.status == str(DateStatus.UNRESOLVED),
                    )
                )
                or 0
            )
            failed = int(
                session.scalar(
                    select(func.count())
                    .select_from(DateProcessingStatus)
                    .where(
                        DateProcessingStatus.show_id == show_row.id,
                        DateProcessingStatus.status == str(DateStatus.FAILED),
                    )
                )
                or 0
            )
            recent = int(
                session.scalar(
                    select(func.count())
                    .select_from(Recommendation)
                    .join(Segment, Recommendation.segment_id == Segment.id)
                    .where(
                        Segment.show_id == show_row.id,
                        Segment.segment_date >= (now - timedelta(days=14)).date(),
                    )
                )
                or 0
            )
            last_success_run_id = session.scalar(
                select(func.max(DateProcessingStatus.last_run_id)).where(
                    DateProcessingStatus.show_id == show_row.id,
                    DateProcessingStatus.status == str(DateStatus.COLLECTED),
                )
            )
            shows.append(
                OverviewShowStatus(
                    show=str(show),
                    last_collected_date=last_collected,
                    last_success_run_id=last_success_run_id,
                    unresolved_dates=unresolved,
                    failed_dates=failed,
                    recent_recommendations=recent,
                )
            )
        totals = {
            "recommendations": int(
                session.scalar(select(func.count()).select_from(Recommendation)) or 0
            ),
            "segments": int(session.scalar(select(func.count()).select_from(Segment)) or 0),
            "analysts": int(session.scalar(select(func.count()).select_from(Analyst)) or 0),
            "instruments": int(session.scalar(select(func.count()).select_from(Instrument)) or 0),
            "runs": int(session.scalar(select(func.count()).select_from(IngestionRun)) or 0),
        }
        return OverviewOut(
            generated_at=now,
            window=(settings.backfill_start_date, settings.backfill_end_date),
            latest_run=_run_summary(session, latest) if latest else None,
            last_successful_run=_run_summary(session, last_success) if last_success else None,
            success_rate_14d=success_rate,
            runs_14d=len(finished),
            backlog_remaining=backlog,
            recent_failures=[IssueOut.model_validate(i) for i in failures],
            shows=shows,
            newest_recommendations=_rec_rows(session, _newest_recommendation_ids(session, 10)),
            totals=totals,
        )

    ttl = settings.overview_cache_ttl_seconds
    return cache.get_or_set("overview", ttl, produce) if ttl > 0 else produce()


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


@router.get("/runs", response_model=Page[RunSummary])
def list_runs(
    session: DbDep,
    page: PageDep,
    status: Annotated[RunStatusFilter | None, Query()] = None,
    trigger: Annotated[Literal["scheduled", "backfill", "manual"] | None, Query()] = None,
    sort: Annotated[Literal["started_at", "id"], Query()] = "started_at",
) -> Page[RunSummary]:
    stmt = select(IngestionRun)
    count_stmt = select(func.count()).select_from(IngestionRun)
    if status:
        stmt = stmt.where(IngestionRun.status == status)
        count_stmt = count_stmt.where(IngestionRun.status == status)
    if trigger:
        stmt = stmt.where(IngestionRun.trigger == trigger)
        count_stmt = count_stmt.where(IngestionRun.trigger == trigger)
    order = IngestionRun.started_at.desc() if sort == "started_at" else IngestionRun.id.desc()
    total = int(session.scalar(count_stmt) or 0)
    runs = session.scalars(stmt.order_by(order).offset(page.offset).limit(page.page_size)).all()
    return Page[RunSummary](
        data=[_run_summary(session, r) for r in runs],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(session: DbDep, run_id: int) -> RunDetail:
    run = _run_or_404(session, run_id)
    source_results = session.scalars(
        select(SourceRunResult).where(SourceRunResult.run_id == run.id)
    ).all()
    issues = session.scalars(select(Issue).where(Issue.last_run_id == run.id)).all()
    date_rows = session.execute(
        select(DateProcessingStatus, Show.key)
        .join(Show, DateProcessingStatus.show_id == Show.id)
        .where(DateProcessingStatus.last_run_id == run.id)
        .order_by(DateProcessingStatus.processing_date)
    ).all()
    date_results = []
    per_show: dict[str, list[int]] = {}
    for row, show_key in date_rows:
        out = DateStatusOut(
            show=show_key,
            processing_date=row.processing_date,
            status=row.status,
            is_trading_day=row.is_trading_day,
            attempts=row.attempts,
            first_attempted_at=row.first_attempted_at,
            last_attempted_at=row.last_attempted_at,
            last_run_id=row.last_run_id,
            segment_id=row.segment_id,
            note=row.note,
        )
        date_results.append(out)
        stats = per_show.setdefault(show_key, [0, 0])
        stats[1] += 1
        if row.status == str(DateStatus.COLLECTED):
            stats[0] += 1
    detail = RunDetail(
        **_run_summary(session, run).model_dump(),
        source_results=[SourceRunResultOut.model_validate(s) for s in source_results],
        issues=[IssueOut.model_validate(i) for i in issues],
        date_results=date_results,
    )
    if date_results:
        detail.per_show = {k: f"{v[0]}/{v[1]}" for k, v in per_show.items()}
    return detail


# ---------------------------------------------------------------------------
# recommendations
# ---------------------------------------------------------------------------


@router.get("/recommendations", response_model=Page[RecommendationRow])
def list_recommendations(
    session: DbDep,
    page: PageDep,
    dates: DateRangeDep,
    show: Annotated[ShowFilter | None, Query()] = None,
    analyst: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    ticker: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    asset_type: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    direction: Annotated[DirectionFilter | None, Query()] = None,
    verification: Annotated[VerificationFilter | None, Query()] = None,
    extraction_method: Annotated[str | None, Query(min_length=1, max_length=48)] = None,
    sort: Annotated[Literal["date_desc", "date_asc"], Query()] = "date_desc",
) -> Page[RecommendationRow]:
    date_from, date_to = dates
    stmt = (
        select(Recommendation.id)
        .join(Segment, Recommendation.segment_id == Segment.id)
        .join(Show, Segment.show_id == Show.id)
        .join(Analyst, Recommendation.analyst_id == Analyst.id)
        .join(Instrument, Recommendation.instrument_id == Instrument.id)
    )
    count_stmt = (
        select(func.count())
        .select_from(Recommendation)
        .join(Segment, Recommendation.segment_id == Segment.id)
        .join(Show, Segment.show_id == Show.id)
        .join(Analyst, Recommendation.analyst_id == Analyst.id)
        .join(Instrument, Recommendation.instrument_id == Instrument.id)
    )
    conds = []
    if date_from:
        conds.append(Segment.segment_date >= date_from)
    if date_to:
        conds.append(Segment.segment_date <= date_to)
    if show:
        conds.append(Show.key == show)
    if analyst:
        conds.append(Analyst.canonical_name.ilike(f"%{analyst}%"))
    if ticker:
        conds.append(Instrument.symbol.ilike(f"%{ticker}%"))
    if asset_type:
        conds.append(Instrument.asset_type == asset_type)
    if direction:
        conds.append(Recommendation.direction == direction)
    if verification:
        conds.append(Recommendation.verification_status == verification)
    if extraction_method:
        conds.append(Recommendation.extraction_method == extraction_method)
    for c in conds:
        stmt = stmt.where(c)
        count_stmt = count_stmt.where(c)
    order = (
        (
            Segment.segment_date.desc(),
            Recommendation.id.desc(),
        )
        if sort == "date_desc"
        else (Segment.segment_date.asc(), Recommendation.id.asc())
    )
    total = int(session.scalar(count_stmt) or 0)
    ids = [
        r[0]
        for r in session.execute(
            stmt.order_by(*order).offset(page.offset).limit(page.page_size)
        ).all()
    ]
    return Page[RecommendationRow](
        data=_rec_rows(session, ids), total=total, page=page.page, page_size=page.page_size
    )


@router.get("/recommendations/{rec_id}", response_model=RecommendationDetail)
def get_recommendation(session: DbDep, rec_id: int) -> RecommendationDetail:
    rec = session.scalar(
        select(Recommendation)
        .options(
            joinedload(Recommendation.segment).joinedload(Segment.show),
            joinedload(Recommendation.analyst),
            joinedload(Recommendation.instrument),
            joinedload(Recommendation.sources).joinedload(RecommendationSource.source),
            joinedload(Recommendation.performance),
        )
        .where(Recommendation.id == rec_id)
    )
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    row = _rec_rows(session, [rec.id])[0]
    return RecommendationDetail(
        **row.model_dump(),
        review_notes=rec.review_notes,
        analyst_title=rec.analyst.affiliation,
        evidence=[
            EvidenceOut(
                source_key=e.source.key,
                url=e.url,
                retrieved_at=e.retrieved_at,
                published_at=e.published_at,
                content_sha256=e.content_sha256,
                excerpt=e.excerpt,
                excerpt_kind=e.excerpt_kind,
            )
            for e in sorted(rec.sources, key=lambda x: x.retrieved_at)
        ],
        performance=[
            PerformanceOut.model_validate(p)
            for p in sorted(rec.performance, key=lambda p: p.horizon_days)
        ],
    )


# ---------------------------------------------------------------------------
# historical dates
# ---------------------------------------------------------------------------


@router.get("/historical/dates", response_model=Page[HistoricalDateRow])
def list_historical_dates(
    session: DbDep,
    page: PageDep,
    dates: DateRangeDep,
    show: Annotated[ShowFilter | None, Query()] = None,
    status: Annotated[str | None, Query(min_length=1, max_length=16)] = None,
) -> Page[HistoricalDateRow]:
    date_from, date_to = dates
    stmt = (
        select(DateProcessingStatus, Show.key, CoverageDaily)
        .join(Show, DateProcessingStatus.show_id == Show.id)
        .outerjoin(
            CoverageDaily,
            (CoverageDaily.show_id == DateProcessingStatus.show_id)
            & (CoverageDaily.coverage_date == DateProcessingStatus.processing_date),
        )
    )
    count_stmt = (
        select(func.count())
        .select_from(DateProcessingStatus)
        .join(Show, DateProcessingStatus.show_id == Show.id)
    )
    conds = []
    if date_from:
        conds.append(DateProcessingStatus.processing_date >= date_from)
    if date_to:
        conds.append(DateProcessingStatus.processing_date <= date_to)
    if show:
        conds.append(Show.key == show)
    if status:
        conds.append(DateProcessingStatus.status == status)
    for c in conds:
        stmt = stmt.where(c)
        count_stmt = count_stmt.where(c)
    total = int(session.scalar(count_stmt) or 0)
    rows = session.execute(
        stmt.order_by(DateProcessingStatus.processing_date.desc(), Show.key)
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    data = [
        HistoricalDateRow(
            the_date=dps.processing_date,
            show=show_key,
            status=dps.status,
            coverage_status=cov.status if cov else None,
            recommendations_count=cov.recommendations_count if cov else 0,
            is_trading_day=dps.is_trading_day,
            attempts=dps.attempts,
            note=dps.note,
        )
        for dps, show_key, cov in rows
    ]
    return Page[HistoricalDateRow](data=data, total=total, page=page.page, page_size=page.page_size)


# ---------------------------------------------------------------------------
# analysts
# ---------------------------------------------------------------------------

MIN_PERFORMANCE_SAMPLE = 30


@router.get("/analysts", response_model=Page[AnalystSummary])
def list_analysts(session: DbDep, page: PageDep) -> Page[AnalystSummary]:
    total = int(session.scalar(select(func.count()).select_from(Analyst)) or 0)
    analysts = session.scalars(
        select(Analyst).order_by(Analyst.canonical_name).offset(page.offset).limit(page.page_size)
    ).all()
    data = [_analyst_summary(session, a) for a in analysts]
    return Page[AnalystSummary](data=data, total=total, page=page.page, page_size=page.page_size)


@router.get("/analysts/{analyst_id}", response_model=AnalystSummary)
def get_analyst(session: DbDep, analyst_id: int) -> AnalystSummary:
    analyst = session.get(Analyst, analyst_id)
    if analyst is None:
        raise HTTPException(status_code=404, detail="Analyst not found")
    return _analyst_summary(session, analyst)


def _analyst_summary(session: Session, analyst: Analyst) -> AnalystSummary:
    rec_count = int(
        session.scalar(
            select(func.count())
            .select_from(Recommendation)
            .where(Recommendation.analyst_id == analyst.id)
        )
        or 0
    )
    show_rows = session.execute(
        select(Show.key, func.count())
        .select_from(Recommendation)
        .join(Segment, Recommendation.segment_id == Segment.id)
        .join(Show, Segment.show_id == Show.id)
        .where(Recommendation.analyst_id == analyst.id)
        .group_by(Show.key)
    ).all()
    top = session.execute(
        select(Instrument.symbol, func.count().label("n"))
        .select_from(Recommendation)
        .join(Instrument, Recommendation.instrument_id == Instrument.id)
        .where(Recommendation.analyst_id == analyst.id)
        .group_by(Instrument.symbol)
        .order_by(func.count().desc())
        .limit(5)
    ).all()
    verified = int(
        session.scalar(
            select(func.count())
            .select_from(Recommendation)
            .where(
                Recommendation.analyst_id == analyst.id,
                Recommendation.verification_status.in_(["verified", "corroborated"]),
            )
        )
        or 0
    )
    perf_sizes_rows = session.execute(
        select(PerformanceObservation.horizon_days, func.count())
        .select_from(PerformanceObservation)
        .join(Recommendation, PerformanceObservation.recommendation_id == Recommendation.id)
        .where(
            Recommendation.analyst_id == analyst.id,
            PerformanceObservation.status == "OK",
        )
        .group_by(PerformanceObservation.horizon_days)
    ).all()
    perf_sizes = dict(perf_sizes_rows)
    return AnalystSummary(
        id=analyst.id,
        canonical_name=analyst.canonical_name,
        affiliation=analyst.affiliation,
        recommendation_count=rec_count,
        show_distribution=dict(show_rows),
        top_instruments=[(s, n) for s, n in top],
        attributed_share_verified=round(verified / rec_count, 3) if rec_count else None,
        performance_sample_sizes=perf_sizes,
        insufficient_performance_data=not perf_sizes
        or min(perf_sizes.values()) < MIN_PERFORMANCE_SAMPLE,
    )


# ---------------------------------------------------------------------------
# performance
# ---------------------------------------------------------------------------


@router.get("/performance/summary", response_model=PerformanceSummary)
def performance_summary(session: DbDep, settings: SettingsDep) -> PerformanceSummary:
    rows: list[PerformanceSummaryRow] = []
    for horizon in (1, 5, 20, 60):
        ok = session.execute(
            select(PerformanceObservation, Recommendation.direction)
            .join(Recommendation, PerformanceObservation.recommendation_id == Recommendation.id)
            .where(PerformanceObservation.horizon_days == horizon)
        ).all()
        longs = [
            o for o, d in ok if d == "long" and o.status == "OK" and o.forward_return is not None
        ]
        shorts = [
            o for o, d in ok if d == "short" and o.status == "OK" and o.forward_return is not None
        ]
        missing = sum(1 for o, _ in ok if o.status.startswith("MISSING"))
        rel = [o.relative_return for o in longs if o.relative_return is not None]
        rows.append(
            PerformanceSummaryRow(
                horizon_days=horizon,
                sample_size=len(longs),
                missing_count=missing,
                avg_forward_return=_avg_attr(longs, "forward_return"),
                avg_benchmark_return=_avg_attr(longs, "benchmark_return"),
                avg_relative_return=_avg_attr(longs, "relative_return"),
                win_rate=round(sum(1 for r in rel if r > 0) / len(rel), 3) if rel else None,
                short_sample_size=len(shorts),
                avg_short_relative_return=_avg_attr(shorts, "relative_return"),
            )
        )
    return PerformanceSummary(
        benchmark_symbol=settings.benchmark_symbol,
        horizons=rows,
        methodology=PERFORMANCE_METHODOLOGY,
        disclaimer=PERFORMANCE_DISCLAIMER,
    )


@router.get("/performance/recommendations", response_model=Page[RecommendationRow])
def performance_recommendations(
    session: DbDep,
    page: PageDep,
    horizon: Annotated[Literal[1, 5, 20, 60], Query()] = 20,
) -> Page[RecommendationRow]:
    base = (
        select(Recommendation.id)
        .join(PerformanceObservation, PerformanceObservation.recommendation_id == Recommendation.id)
        .where(
            PerformanceObservation.horizon_days == horizon, PerformanceObservation.status == "OK"
        )
    )
    count_stmt = select(func.count()).select_from(base.subquery())
    total = int(session.scalar(count_stmt) or 0)
    ids = [
        r[0]
        for r in session.execute(
            base.order_by(Recommendation.id.desc()).offset(page.offset).limit(page.page_size)
        ).all()
    ]
    return Page[RecommendationRow](
        data=_rec_rows(session, ids), total=total, page=page.page, page_size=page.page_size
    )


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


@router.get("/coverage", response_model=CoverageOut)
def get_coverage(session: DbDep, settings: SettingsDep) -> CoverageOut:
    cache = get_cache()

    def produce() -> CoverageOut:
        shows_out: list[ShowCoverage] = []
        for show in ShowKey:
            show_row = session.scalar(select(Show).where(Show.key == str(show)))
            if show_row is None:
                continue
            counts = dict(
                session.execute(
                    select(CoverageDaily.status, func.count())
                    .where(CoverageDaily.show_id == show_row.id)
                    .group_by(CoverageDaily.status)
                ).all()
            )
            date_counts = dict(
                session.execute(
                    select(DateProcessingStatus.status, func.count())
                    .where(DateProcessingStatus.show_id == show_row.id)
                    .group_by(DateProcessingStatus.status)
                ).all()
            )
            is_sqlite = session.bind is not None and session.bind.dialect.name == "sqlite"
            month_expr = (
                func.strftime("%Y-%m", CoverageDaily.coverage_date)
                if is_sqlite
                else func.to_char(CoverageDaily.coverage_date, "YYYY-MM")
            )
            monthly_rows = session.execute(
                select(month_expr, CoverageDaily.status, func.count())
                .where(CoverageDaily.show_id == show_row.id)
                .group_by(month_expr, CoverageDaily.status)
                .order_by(month_expr)
            ).all()
            monthly: dict[str, dict[str, int]] = {}
            for month, status, n in monthly_rows:
                monthly.setdefault(str(month), {})[str(status)] = n
            backlog = int(
                session.scalar(
                    select(func.count())
                    .select_from(DateProcessingStatus)
                    .where(
                        DateProcessingStatus.show_id == show_row.id,
                        DateProcessingStatus.status.in_(
                            [
                                str(DateStatus.PENDING),
                                str(DateStatus.FAILED),
                                str(DateStatus.UNRESOLVED),
                            ]
                        ),
                        DateProcessingStatus.is_trading_day.is_(True),
                    )
                )
                or 0
            )
            total_dates = sum(date_counts.values())
            shows_out.append(
                ShowCoverage(
                    show=str(show),
                    total_dates=total_dates,
                    collected=date_counts.get(str(DateStatus.COLLECTED), 0),
                    verified_absent=date_counts.get(str(DateStatus.NO_SEGMENT), 0),
                    partial=counts.get("PARTIAL", 0),
                    missing=date_counts.get(str(DateStatus.FAILED), 0)
                    + date_counts.get(str(DateStatus.UNRESOLVED), 0),
                    unchecked=date_counts.get(str(DateStatus.PENDING), 0),
                    backlog=backlog,
                    monthly=[{"month": m, **v} for m, v in sorted(monthly.items())],
                )
            )
        last_checks: dict[str, datetime | None] = {}
        for source in session.scalars(select(Source)).all():
            last_checks[source.key] = session.scalar(
                select(func.max(SourceRunResult.finished_at)).where(
                    SourceRunResult.source_key == source.key,
                    SourceRunResult.status == "SUCCESS",
                )
            )
        return CoverageOut(
            window_start=settings.backfill_start_date,
            window_end=settings.backfill_end_date,
            shows=shows_out,
            last_successful_check_by_source=last_checks,
        )

    ttl = settings.overview_cache_ttl_seconds
    return cache.get_or_set("coverage", ttl, produce) if ttl > 0 else produce()


# ---------------------------------------------------------------------------
# issues + health
# ---------------------------------------------------------------------------


@router.get("/issues", response_model=Page[IssueOut])
def list_issues(
    session: DbDep,
    page: PageDep,
    resolved: Annotated[bool | None, Query()] = None,
) -> Page[IssueOut]:
    stmt = select(Issue)
    count_stmt = select(func.count()).select_from(Issue)
    if resolved is not None:
        stmt = stmt.where(Issue.resolved.is_(resolved))
        count_stmt = count_stmt.where(Issue.resolved.is_(resolved))
    total = int(session.scalar(count_stmt) or 0)
    issues = session.scalars(
        stmt.order_by(Issue.last_occurred_at.desc()).offset(page.offset).limit(page.page_size)
    ).all()
    return Page[IssueOut](
        data=[IssueOut.model_validate(i) for i in issues],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )
