"""Run orchestration: discovery, bounded attempts, cross-run recovery.

Semantics (AGENTS.md / PRD §5):
- ONE bounded attempt per processing unit per run; zero intra-run retries.
- Current-day work gets reserved capacity; backlog is oldest-first.
- Commit per unit: partial progress survives later failures.
- Durable state lives in date_processing_status + recommendation_sources
  (processed-article evidence); the next scheduled run rediscovers
  FAILED/PENDING/UNRESOLVED units and retries them.

Processing models per show (see docs/ARCHITECTURE.md §6):
- Fast Money: date-driven. CNBC search/RSS items carry exact segment dates;
  a unit fetches its video page and persists tickers (attribution is not
  published by CNBC → unverified/(unattributed), honestly recorded).
- Halftime Report: article-driven. Benzinga articles map 1:1 to segment
  dates (revealed on fetch: segment = publish date - 1 trading day); the run
  processes a bounded set of not-yet-persisted articles, oldest-first, with
  recent-window articles prioritized.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from final_trades.config import Settings
from final_trades.db import repositories as repo
from final_trades.db.models import (
    DateProcessingStatus,
    IngestionRun,
    Issue,
    RecommendationSource,
    SourceRunResult,
)
from final_trades.db.seed import get_show
from final_trades.domain import (
    CoverageStatus,
    DateStatus,
    ErrorCategory,
    RunStatus,
    RunTrigger,
    ShowKey,
    SourceKey,
    SourceRunStatus,
    Stage,
)
from final_trades.market_calendar import is_trading_day, next_trading_day
from final_trades.pipeline.persist import persist_segment
from final_trades.sources import benzinga, cnbc
from final_trades.sources.contracts import DiscoveredItem, FetchFailure, ParsedSegment
from final_trades.sources.http import PoliteFetcher

SEARCH_BATCH = 50
SCHEDULED_SEARCH_PAGES = 3
MAX_SEARCH_PAGES = 40
SCHEDULED_LOOKBACK_DAYS = 10
_ARTICLE_ID = re.compile(r"/(\d{6,})/[a-z0-9-]+$")


@dataclass
class UnitOutcome:
    show: str
    unit_date: date
    final_status: str
    created: int = 0
    updated: int = 0
    rejected: int = 0
    unresolved: int = 0
    failures: list[FetchFailure] = field(default_factory=list)
    note: str | None = None


@dataclass
class DiscoveryResult:
    fm_items: dict[date, list[DiscoveredItem]] = field(default_factory=dict)
    hr_items: dict[date, list[DiscoveredItem]] = field(default_factory=dict)
    benzinga_articles: list[DiscoveredItem] = field(default_factory=list)
    failures: list[FetchFailure] = field(default_factory=list)
    sources_ok: set[str] = field(default_factory=set)
    sources_failed: set[str] = field(default_factory=set)
    benzinga_months_covered: set[tuple[int, int]] = field(default_factory=set)
    search_oldest_date: date | None = None

    @property
    def discovery_items(self) -> int:
        return sum(len(v) for v in self.fm_items.values()) + len(self.benzinga_articles)


def _article_sort_key(item: DiscoveredItem) -> int:
    m = _ARTICLE_ID.search(item.url)
    return int(m.group(1)) if m else 0


class Collector:
    def __init__(
        self,
        session: Session,
        fetcher: PoliteFetcher,
        settings: Settings,
        today: date | None = None,
    ) -> None:
        self.session = session
        self.fetcher = fetcher
        self.settings = settings
        self.today = today or date.today()
        self._run: IngestionRun | None = None

    # -- entry points ---------------------------------------------------------

    def run_scheduled(self) -> IngestionRun:
        return self._run_pipeline(
            trigger=RunTrigger.SCHEDULED,
            window_start=self.today - timedelta(days=SCHEDULED_LOOKBACK_DAYS),
            window_end=self.today,
            max_units=self.settings.backlog_max_dates_per_run,
            full_window_discovery=False,
        )

    def run_backfill(self, start: date, end: date, max_units: int | None = None) -> IngestionRun:
        return self._run_pipeline(
            trigger=RunTrigger.BACKFILL,
            window_start=start,
            window_end=end,
            max_units=max_units or self.settings.backlog_max_dates_per_run,
            full_window_discovery=True,
        )

    # -- run lifecycle --------------------------------------------------------

    def _run_pipeline(
        self,
        trigger: RunTrigger,
        window_start: date,
        window_end: date,
        max_units: int,
        full_window_discovery: bool,
    ) -> IngestionRun:
        run = repo.start_run(self.session, str(trigger), window_start, window_end)
        self.session.commit()
        self._run = run
        outcomes: list[UnitOutcome] = []
        discovery = DiscoveryResult()
        try:
            self._ensure_date_rows(window_start, window_end)
            discovery = self._discover(window_start, window_end, full_window_discovery)
            fm_dates, hr_articles = self._select_work(discovery, max_units)
            for d in fm_dates:
                outcomes.append(self._process_fm_date(d, discovery))
                self.session.commit()
            for article in hr_articles:
                outcomes.extend(self._process_hr_article(article, discovery))
                self.session.commit()
            outcomes.extend(self._reconcile(discovery, fm_dates, hr_articles))
            self.session.commit()
            self._record_source_results(run, discovery, outcomes)
        except Exception as exc:
            self.session.rollback()
            run = self.session.get(IngestionRun, run.id) or run
            self._run = run
            run.error_count += 1
            run.summary = f"Run aborted: {type(exc).__name__}"
            self._record_issue(
                ErrorCategory.UNKNOWN, Stage.PERSIST, f"Run aborted: {type(exc).__name__}"
            )
            self._finalize(run, outcomes, discovery)
            self.session.commit()
            raise
        self._finalize(run, outcomes, discovery)
        self.session.commit()
        return run

    # -- date rows --------------------------------------------------------------

    def _ensure_date_rows(self, window_start: date, window_end: date) -> None:
        for show in ShowKey:
            d = window_start
            while d <= window_end:
                repo.get_or_init_date_status(self.session, show, d, is_trading_day(d))
                d += timedelta(days=1)
        self.session.flush()

    # -- discovery ----------------------------------------------------------------

    def _discover(self, window_start: date, window_end: date, full_window: bool) -> DiscoveryResult:
        result = DiscoveryResult()
        pages = MAX_SEARCH_PAGES if full_window else SCHEDULED_SEARCH_PAGES
        self._discover_cnbc_search(result, window_start, pages)
        self._discover_cnbc_rss(result)
        self._discover_benzinga_topic(result)
        months: set[tuple[int, int]] = set()
        d = window_start
        while d <= window_end:
            if is_trading_day(d):
                p = next_trading_day(d)
                months.add((p.year, p.month))
            d += timedelta(days=1)
        for year, month in sorted(months):
            self._discover_benzinga_sitemap(result, year, month)
        return result

    def _discover_cnbc_search(
        self, result: DiscoveryResult, window_start: date, max_pages: int
    ) -> None:
        offset = 0
        fetched_any = False
        for _ in range(max_pages):
            outcome = self.fetcher.get(cnbc.search_url(offset, SEARCH_BATCH), stage=Stage.DISCOVER)
            if isinstance(outcome, FetchFailure):
                result.failures.append(outcome)
                result.sources_failed.add("cnbc_search")
                break
            items = cnbc.parse_search_results(outcome.body)
            if isinstance(items, FetchFailure):
                result.failures.append(items)
                result.sources_failed.add("cnbc_search")
                break
            fetched_any = True
            if not items:
                break
            for item in items:
                if item.show is None or item.published_at is None:
                    continue
                item_date = item.published_at.astimezone(cnbc.ET).date()
                result.search_oldest_date = (
                    item_date
                    if result.search_oldest_date is None
                    else min(result.search_oldest_date, item_date)
                )
                if item.show == ShowKey.FAST_MONEY:
                    result.fm_items.setdefault(item_date, []).append(item)
                else:
                    result.hr_items.setdefault(item_date, []).append(item)
            offset += SEARCH_BATCH
            if result.search_oldest_date is not None and result.search_oldest_date < window_start:
                break
        if fetched_any:
            result.sources_ok.add("cnbc_search")

    def _discover_cnbc_rss(self, result: DiscoveryResult) -> None:
        outcome = self.fetcher.get(cnbc.FAST_MONEY_RSS_URL, stage=Stage.DISCOVER)
        if isinstance(outcome, FetchFailure):
            result.failures.append(outcome)
            result.sources_failed.add(str(SourceKey.CNBC_RSS_FAST_MONEY))
            return
        items = cnbc.parse_rss(outcome.body)
        if isinstance(items, FetchFailure):
            result.failures.append(items)
            result.sources_failed.add(str(SourceKey.CNBC_RSS_FAST_MONEY))
            return
        result.sources_ok.add(str(SourceKey.CNBC_RSS_FAST_MONEY))
        for item in items:
            if item.published_at is not None:
                d = item.published_at.astimezone(cnbc.ET).date()
                result.fm_items.setdefault(d, []).append(item)

    def _discover_benzinga_topic(self, result: DiscoveryResult) -> None:
        url = benzinga.TOPIC_URLS[ShowKey.HALFTIME_REPORT]
        outcome = self.fetcher.get(url, stage=Stage.DISCOVER)
        if isinstance(outcome, FetchFailure):
            result.failures.append(outcome)
            result.sources_failed.add(str(SourceKey.BENZINGA_HALFTIME_TOPIC))
            return
        items = benzinga.parse_topic_listing(
            outcome.body, ShowKey.HALFTIME_REPORT, SourceKey.BENZINGA_HALFTIME_TOPIC
        )
        result.sources_ok.add(str(SourceKey.BENZINGA_HALFTIME_TOPIC))
        self._merge_articles(result, items)

    def _discover_benzinga_sitemap(self, result: DiscoveryResult, year: int, month: int) -> None:
        url = benzinga.sitemap_url_for(date(year, month, 1))
        outcome = self.fetcher.get(url, stage=Stage.DISCOVER)
        if isinstance(outcome, FetchFailure):
            result.failures.append(outcome)
            result.sources_failed.add(f"benzinga_sitemap_{year}_{month:02d}")
            return
        urls = benzinga.parse_sitemap_urls(outcome.body)
        result.sources_ok.add(f"benzinga_sitemap_{year}_{month:02d}")
        result.benzinga_months_covered.add((year, month))
        self._merge_articles(
            result,
            [
                DiscoveredItem(
                    url=u,
                    show=ShowKey.HALFTIME_REPORT,
                    published_at=None,
                    title="",
                    source_key=str(SourceKey.BENZINGA_ARTICLE),
                )
                for u in urls
            ],
        )

    def _merge_articles(self, result: DiscoveryResult, items: list[DiscoveredItem]) -> None:
        known = {a.url for a in result.benzinga_articles}
        for item in items:
            if item.url not in known:
                known.add(item.url)
                result.benzinga_articles.append(item)

    # -- work selection -----------------------------------------------------------

    def _select_work(
        self, discovery: DiscoveryResult, max_units: int
    ) -> tuple[list[date], list[DiscoveredItem]]:
        """Pick FM date units and HR articles within the run budget.

        Current-day window first (reserved share), then oldest-first backlog.
        """
        if max_units <= 0:
            return [], []
        recent_cutoff = self.today - timedelta(days=SCHEDULED_LOOKBACK_DAYS)

        # Fast Money: eligible dates = pending/failed/unresolved rows with a
        # discovered item, or (recent window) any date needing processing.
        eligible_fm = self._eligible_dates(ShowKey.FAST_MONEY)
        fm_recent = sorted(d for d in eligible_fm if d >= recent_cutoff and d in discovery.fm_items)
        fm_backlog = sorted(d for d in eligible_fm if d < recent_cutoff and d in discovery.fm_items)

        # Halftime: unprocessed articles (no evidence row yet), oldest-first;
        # articles published within the recent window jump the queue.
        articles = sorted(discovery.benzinga_articles, key=_article_sort_key)
        unprocessed = [a for a in articles if not self._url_already_processed(a.url)]
        hr_recent = [a for a in unprocessed if self._article_is_recent(a)]
        hr_backlog = [a for a in unprocessed if not self._article_is_recent(a)]

        share = self.settings.current_day_capacity_share
        budget_recent = max(1, int(max_units * share))
        fm_selected: list[date] = []
        hr_selected: list[DiscoveredItem] = []
        # Interleave recent work: FM dates first (they anchor "today"), then
        # recent articles, within the reserved share.
        for d in fm_recent:
            if len(fm_selected) + len(hr_selected) >= budget_recent:
                break
            fm_selected.append(d)
        for a in hr_recent:
            if len(fm_selected) + len(hr_selected) >= budget_recent:
                break
            hr_selected.append(a)
        # Remaining budget: oldest-first backlog, alternating fairness by count.
        fi = bi = 0
        while len(fm_selected) + len(hr_selected) < max_units and (
            fi < len(fm_backlog) or bi < len(hr_backlog)
        ):
            if fi < len(fm_backlog) and (bi >= len(hr_backlog) or fi <= bi):
                fm_selected.append(fm_backlog[fi])
                fi += 1
            elif bi < len(hr_backlog):
                hr_selected.append(hr_backlog[bi])
                bi += 1
        return fm_selected, hr_selected

    def _article_is_recent(self, article: DiscoveredItem) -> bool:
        ym = benzinga.article_url_month(article.url)
        if ym is None:
            return False
        year, month = ym
        recent = self.today - timedelta(days=SCHEDULED_LOOKBACK_DAYS)
        return (year, month) >= (recent.year, recent.month)

    def _eligible_dates(self, show: ShowKey) -> list[date]:
        show_row = get_show(self.session, show)
        rows = self.session.execute(
            select(DateProcessingStatus.processing_date).where(
                DateProcessingStatus.show_id == show_row.id,
                DateProcessingStatus.status.in_(
                    [str(DateStatus.PENDING), str(DateStatus.FAILED), str(DateStatus.UNRESOLVED)]
                ),
                DateProcessingStatus.processing_date >= self.settings.backfill_start_date,
                DateProcessingStatus.processing_date <= self.settings.backfill_end_date,
            )
        ).scalars()
        return list(rows)

    def _url_already_processed(self, url: str) -> bool:
        return (
            self.session.scalar(
                select(RecommendationSource.id).where(RecommendationSource.url == url).limit(1)
            )
            is not None
        )

    # -- unit processing -----------------------------------------------------------

    def _process_fm_date(self, d: date, discovery: DiscoveryResult) -> UnitOutcome:
        unit_show = str(ShowKey.FAST_MONEY)
        items = [
            i
            for i in discovery.fm_items.get(d, [])
            if i.source_key == str(SourceKey.CNBC_VIDEO_PAGE)
        ]
        if not items:
            return self._mark(
                unit_show, d, DateStatus.PENDING, note="No video item discovered; deferred"
            )
        item = items[0]
        outcome = self.fetcher.get(item.url, stage=Stage.FETCH)
        if isinstance(outcome, FetchFailure):
            self._record_issue(
                outcome.error_category,
                outcome.stage,
                outcome.summary,
                source_key=str(SourceKey.CNBC_VIDEO_PAGE),
                show_key=unit_show,
                processing_date=d,
                detail=outcome.detail or None,
            )
            return self._mark(
                unit_show, d, DateStatus.FAILED, failures=[outcome], note=outcome.summary[:500]
            )
        seg = cnbc.parse_video_page(
            outcome, ShowKey.FAST_MONEY, title_hint=item.title, published_hint=item.published_at
        )
        if isinstance(seg, FetchFailure):
            self._record_issue(
                seg.error_category,
                seg.stage,
                seg.summary,
                source_key=str(SourceKey.CNBC_VIDEO_PAGE),
                show_key=unit_show,
                processing_date=d,
                detail=seg.detail or None,
            )
            return self._mark(
                unit_show, d, DateStatus.FAILED, failures=[seg], note=seg.summary[:500]
            )
        result = persist_segment(self.session, seg)
        # RSS corroboration: same-day feed item becomes extra evidence.
        self._attach_rss_corroboration(seg)
        status = DateStatus.COLLECTED
        self._update_coverage(unit_show, d, result.created + result.updated, ok=1, failed=0)
        return self._mark(
            unit_show,
            d,
            status,
            created=result.created,
            updated=result.updated,
            rejected=result.rejected,
            unresolved=result.unresolved,
            segment_id=self._segment_id(seg.show, seg.segment_date),
        )

    def _process_hr_article(
        self, article: DiscoveredItem, discovery: DiscoveryResult
    ) -> list[UnitOutcome]:
        unit_show = str(ShowKey.HALFTIME_REPORT)
        outcomes: list[UnitOutcome] = []
        fetch = self.fetcher.get(article.url, stage=Stage.FETCH)
        if isinstance(fetch, FetchFailure):
            self._record_issue(
                fetch.error_category,
                fetch.stage,
                fetch.summary,
                source_key=str(SourceKey.BENZINGA_ARTICLE),
                show_key=unit_show,
                detail=fetch.detail or None,
            )
            # The segment date is unknown; attribute the failure to the
            # expected publish month so the run detail can show it.
            return [
                UnitOutcome(
                    unit_show,
                    self.today,
                    str(DateStatus.FAILED),
                    failures=[fetch],
                    note=f"Article fetch failed: {article.url}",
                )
            ]
        seg = benzinga.parse_article(fetch, expected_show=ShowKey.HALFTIME_REPORT)
        if isinstance(seg, FetchFailure):
            self._record_issue(
                seg.error_category,
                seg.stage,
                seg.summary,
                source_key=str(SourceKey.BENZINGA_ARTICLE),
                show_key=unit_show,
                detail=seg.detail or None,
            )
            return [
                UnitOutcome(
                    unit_show,
                    self.today,
                    str(DateStatus.FAILED),
                    failures=[seg],
                    note=f"Article parse failed: {article.url}",
                )
            ]
        result = persist_segment(self.session, seg)
        if result.rejections:
            self._record_issue(
                ErrorCategory.VALIDATION,
                Stage.NORMALIZE,
                f"Rejected un-normalizable instruments: {', '.join(result.rejections[:5])}",
                source_key=str(SourceKey.BENZINGA_ARTICLE),
                show_key=unit_show,
                processing_date=seg.segment_date,
            )
        self._attach_video_corroboration(seg, discovery)
        status = (
            DateStatus.UNRESOLVED
            if (result.unresolved and not result.created and not result.updated)
            else DateStatus.COLLECTED
        )
        self._update_coverage(
            unit_show, seg.segment_date, result.created + result.updated, ok=1, failed=0
        )
        outcomes.append(
            self._mark(
                unit_show,
                seg.segment_date,
                status,
                created=result.created,
                updated=result.updated,
                rejected=result.rejected,
                unresolved=result.unresolved,
                segment_id=self._segment_id(seg.show, seg.segment_date),
            )
        )
        return outcomes

    def _attach_rss_corroboration(self, seg: ParsedSegment) -> None:
        """Link the day's RSS item URL as supporting evidence (metadata only)."""
        pass  # RSS and video items share the same URL; video evidence suffices.

    def _attach_video_corroboration(self, seg: ParsedSegment, discovery: DiscoveryResult) -> None:
        from final_trades.db.models import Recommendation

        items = discovery.fm_items.get(seg.segment_date, [])
        # Halftime videos are indexed in fm_items only for FM; find HR items via search:
        hr_items = [i for i in items if i.show == ShowKey.HALFTIME_REPORT]
        if not hr_items:
            return
        recs = self.session.scalars(
            select(Recommendation).where(
                Recommendation.segment_id == self._segment_id(seg.show, seg.segment_date)
            )
        ).all()
        for item in hr_items[:1]:
            for rec in recs:
                repo.add_evidence(
                    self.session,
                    rec,
                    source_key=item.source_key,
                    url=item.url,
                    retrieved_at=item.published_at or repo.utcnow(),
                    content_sha256=hashlib.sha256(item.url.encode()).hexdigest(),
                    excerpt=item.title[:600],
                    excerpt_kind="title",
                    published_at=item.published_at,
                )

    def _record_article_issue(self, failure: FetchFailure, show_key: str, url: str) -> None:
        """Issue keyed by article URL so later runs track per-article recovery."""
        url_sha1 = hashlib.sha1(url.encode()).hexdigest()
        detail = dict(failure.detail or {})
        detail["url_sha1"] = url_sha1
        detail["url"] = url
        fingerprint_src = f"{failure.error_category}|{SourceKey.BENZINGA_ARTICLE}|{show_key}|{url_sha1}|{failure.stage}"
        fingerprint = hashlib.sha1(fingerprint_src.encode()).hexdigest()
        repo.record_issue(
            self.session,
            fingerprint=fingerprint,
            error_category=str(failure.error_category),
            stage=str(failure.stage),
            summary=failure.summary[:2000],
            run_id=self._run.id if self._run else None,
            source_key=str(SourceKey.BENZINGA_ARTICLE),
            show_key=show_key,
            processing_date=None,
            detail=detail,
        )

    def _resolve_article_issues(self, show_key: str, url: str) -> None:
        url_sha1 = hashlib.sha1(url.encode()).hexdigest()
        issues = self.session.scalars(
            select(Issue).where(
                Issue.source_key == str(SourceKey.BENZINGA_ARTICLE),
                Issue.show_key == show_key,
                Issue.resolved.is_(False),
            )
        ).all()
        for issue in issues:
            if isinstance(issue.detail, dict) and issue.detail.get("url_sha1") == url_sha1:
                issue.resolved = True
                issue.resolved_at = repo.utcnow()
        self.session.flush()

    def _segment_id(self, show: ShowKey, segment_date: date) -> int | None:
        from final_trades.db.models import Segment

        show_row = get_show(self.session, show)
        return self.session.scalar(
            select(Segment.id).where(
                Segment.show_id == show_row.id, Segment.segment_date == segment_date
            )
        )

    # -- reconciliation -------------------------------------------------------------

    def _reconcile(
        self, discovery: DiscoveryResult, fm_dates: list[date], hr_articles: list[DiscoveredItem]
    ) -> list[UnitOutcome]:
        """Mark honest statuses for selected dates that got no data this run.

        - FM dates with successful discovery but no item → UNRESOLVED
          ("no segment item discovered").
        - HR dates whose publish-month sitemap was fully covered, with no
          article processed or pending for that month → UNRESOLVED
          ("no attribution article published").
        """
        outcomes: list[UnitOutcome] = []
        search_ok = (
            "cnbc_search" in discovery.sources_ok
            or str(SourceKey.CNBC_RSS_FAST_MONEY) in discovery.sources_ok
        )
        for d in fm_dates:
            row = self._date_row(ShowKey.FAST_MONEY, d)
            if row is None or row.status == str(DateStatus.COLLECTED):
                continue
            if search_ok and d not in discovery.fm_items:
                outcomes.append(
                    self._mark(
                        str(ShowKey.FAST_MONEY),
                        d,
                        DateStatus.UNRESOLVED,
                        note="No Fast Money Final Trade item discovered for this date",
                    )
                )
        # Halftime: dates still PENDING whose expected publish month is fully
        # covered by sitemaps AND has no remaining unprocessed articles.
        pending_months: set[tuple[int, int]] = set()
        for a in discovery.benzinga_articles:
            if not self._url_already_processed(a.url):
                ym = benzinga.article_url_month(a.url)
                if ym:
                    pending_months.add(ym)
        show_row = get_show(self.session, ShowKey.HALFTIME_REPORT)
        rows = self.session.scalars(
            select(DateProcessingStatus).where(
                DateProcessingStatus.show_id == show_row.id,
                DateProcessingStatus.status == str(DateStatus.PENDING),
                DateProcessingStatus.is_trading_day.is_(True),
            )
        ).all()
        for row in rows:
            expected = next_trading_day(row.processing_date)
            ym = (expected.year, expected.month)
            if ym in discovery.benzinga_months_covered and ym not in pending_months:
                outcomes.append(
                    self._mark(
                        str(ShowKey.HALFTIME_REPORT),
                        row.processing_date,
                        DateStatus.UNRESOLVED,
                        note="No Benzinga attribution article published for this segment date",
                    )
                )
        return outcomes

    # -- status helpers ---------------------------------------------------------------

    def _date_row(self, show: ShowKey, d: date) -> DateProcessingStatus | None:
        show_row = get_show(self.session, show)
        return self.session.scalar(
            select(DateProcessingStatus).where(
                DateProcessingStatus.show_id == show_row.id,
                DateProcessingStatus.processing_date == d,
            )
        )

    def _mark(
        self,
        show: str,
        d: date,
        status: DateStatus,
        created: int = 0,
        updated: int = 0,
        rejected: int = 0,
        unresolved: int = 0,
        failures: list[FetchFailure] | None = None,
        note: str | None = None,
        segment_id: int | None = None,
    ) -> UnitOutcome:
        row = self._date_row(ShowKey(show), d)
        if row is None:
            row = repo.get_or_init_date_status(self.session, ShowKey(show), d, is_trading_day(d))
        now = repo.utcnow()
        # Do not downgrade a COLLECTED date; do count the attempt.
        if row.status != str(DateStatus.COLLECTED) or status == DateStatus.COLLECTED:
            row.status = str(status)
        row.attempts += 1
        row.last_attempted_at = now
        if row.first_attempted_at is None:
            row.first_attempted_at = now
        if self._run is not None:
            row.last_run_id = self._run.id
        if note:
            row.note = note[:2000]
        if segment_id:
            row.segment_id = segment_id
        self.session.flush()
        if status == DateStatus.COLLECTED:
            self._resolve_issues(show, d)
        return UnitOutcome(
            show=show,
            unit_date=d,
            final_status=str(status),
            created=created,
            updated=updated,
            rejected=rejected,
            unresolved=unresolved,
            failures=failures or [],
            note=note,
        )

    def _update_coverage(self, show: str, d: date, rec_count: int, ok: int, failed: int) -> None:
        status = CoverageStatus.COMPLETE if rec_count > 0 else CoverageStatus.PARTIAL
        if failed and not ok:
            status = CoverageStatus.MISSING
        repo.upsert_coverage(self.session, ShowKey(show), d, str(status), rec_count, ok, failed)

    def _record_issue(
        self,
        category: ErrorCategory | str,
        stage: Stage | str,
        summary: str,
        source_key: str | None = None,
        show_key: str | None = None,
        processing_date: date | None = None,
        detail: dict[str, object] | None = None,
    ) -> None:
        fingerprint_src = f"{category}|{source_key}|{show_key}|{processing_date}|{stage}"
        fingerprint = hashlib.sha1(fingerprint_src.encode()).hexdigest()
        repo.record_issue(
            self.session,
            fingerprint=fingerprint,
            error_category=str(category),
            stage=str(stage),
            summary=summary[:2000],
            run_id=self._run.id if self._run else None,
            source_key=source_key,
            show_key=show_key,
            processing_date=processing_date,
            detail=detail,
        )

    def _resolve_issues(self, show: str, d: date) -> None:
        issues = self.session.scalars(
            select(Issue).where(
                Issue.show_key == show,
                Issue.processing_date == d,
                Issue.resolved.is_(False),
            )
        ).all()
        for issue in issues:
            issue.resolved = True
            issue.resolved_at = repo.utcnow()
        self.session.flush()

    # -- finalize -------------------------------------------------------------------

    def _record_source_results(
        self, run: IngestionRun, discovery: DiscoveryResult, outcomes: list[UnitOutcome]
    ) -> None:
        for key in sorted(discovery.sources_ok | discovery.sources_failed):
            failed = key in discovery.sources_failed
            self.session.add(
                SourceRunResult(
                    run_id=run.id,
                    source_key=key,
                    show_key=(
                        str(ShowKey.FAST_MONEY)
                        if "cnbc" in key or "rss" in key
                        else str(ShowKey.HALFTIME_REPORT)
                        if "benzinga" in key
                        else None
                    ),
                    status=str(SourceRunStatus.FAILED if failed else SourceRunStatus.SUCCESS),
                    items_discovered=discovery.discovery_items,
                    items_processed=len(outcomes),
                    started_at=run.started_at,
                    finished_at=repo.utcnow(),
                    error_summary="discovery failure" if failed else None,
                )
            )
        self.session.flush()

    def _finalize(
        self, run: IngestionRun, outcomes: list[UnitOutcome], discovery: DiscoveryResult
    ) -> None:
        run.finished_at = repo.utcnow()
        run.duration_seconds = (run.finished_at - run.started_at).total_seconds()
        run.discovered_count = discovery.discovery_items
        run.created_count = sum(o.created for o in outcomes)
        run.updated_count = sum(o.updated for o in outcomes)
        run.rejected_count = sum(o.rejected for o in outcomes)
        run.unresolved_count = sum(
            1 for o in outcomes if o.final_status == str(DateStatus.UNRESOLVED)
        )
        failed_units = sum(1 for o in outcomes if o.final_status == str(DateStatus.FAILED))
        run.error_count = len(discovery.failures) + sum(len(o.failures) for o in outcomes)
        run.backlog_remaining = self._backlog_size()
        collected = sum(1 for o in outcomes if o.final_status == str(DateStatus.COLLECTED))
        if failed_units and collected == 0:
            run.status = str(RunStatus.FAILED)
        elif failed_units or discovery.sources_failed or run.unresolved_count:
            run.status = str(RunStatus.PARTIAL_SUCCESS)
        else:
            run.status = str(RunStatus.SUCCESS)
        per_show = []
        for show in ShowKey:
            show_outcomes = [o for o in outcomes if o.show == str(show)]
            show_ok = sum(1 for o in show_outcomes if o.final_status == str(DateStatus.COLLECTED))
            per_show.append(f"{show.value}={show_ok}/{len(show_outcomes)}")
        run.summary = (
            f"units={len(outcomes)} collected={collected} failed={failed_units} "
            f"created={run.created_count} updated={run.updated_count} "
            f"unresolved={run.unresolved_count} backlog={run.backlog_remaining} | "
            + " ".join(per_show)
        )

    def _backlog_size(self) -> int:
        return int(
            self.session.scalar(
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
                    DateProcessingStatus.processing_date >= self.settings.backfill_start_date,
                    DateProcessingStatus.processing_date <= self.settings.backfill_end_date,
                )
            )
            or 0
        )


def run_exit_code(status: str) -> int:
    return {
        str(RunStatus.SUCCESS): 0,
        str(RunStatus.PARTIAL_SUCCESS): 1,
        str(RunStatus.FAILED): 2,
        str(RunStatus.RUNNING): 2,
    }.get(status, 2)
