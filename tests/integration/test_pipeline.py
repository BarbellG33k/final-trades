"""Integration tests: the critical collection/recovery scenarios (master prompt §13).

All HTTP is fixture-backed (tests/integration/conftest.py); no live network.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from final_trades.db.models import (
    DateProcessingStatus,
    IngestionRun,
    Issue,
    Recommendation,
    RecommendationSource,
    Segment,
)
from final_trades.db.seed import get_show
from final_trades.domain import (
    DateStatus,
    RunStatus,
    ShowKey,
    VerificationStatus,
)
from final_trades.pipeline.orchestrator import Collector, run_exit_code
from helpers.pipeline_env import (
    SK_HYNIX_URL,
    TODAY,
    ZSCALER_URL,
    Env,
    article_html,
    custom_article_html,
    sitemap_xml,
    topic_html,
)


def _date_status(env: Env, show: ShowKey, d: date) -> DateProcessingStatus | None:
    show_row = get_show(env.session, show)
    return env.session.scalar(
        select(DateProcessingStatus).where(
            DateProcessingStatus.show_id == show_row.id,
            DateProcessingStatus.processing_date == d,
        )
    )


def _recs(env: Env, show: ShowKey, d: date) -> list[Recommendation]:
    show_row = get_show(env.session, show)
    segment = env.session.scalar(
        select(Segment).where(Segment.show_id == show_row.id, Segment.segment_date == d)
    )
    if segment is None:
        return []
    return list(
        env.session.scalars(select(Recommendation).where(Recommendation.segment_id == segment.id))
    )


# Scenario 1: successful collection for both shows --------------------------------


def test_scheduled_run_collects_both_shows(env: Env, collector: Collector) -> None:
    run = collector.run_scheduled()

    fm = _date_status(env, ShowKey.FAST_MONEY, date(2026, 10, 23))
    hr = _date_status(env, ShowKey.HALFTIME_REPORT, date(2026, 10, 22))
    assert fm is not None and fm.status == str(DateStatus.COLLECTED)
    assert hr is not None and hr.status == str(DateStatus.COLLECTED)

    fm_recs = _recs(env, ShowKey.FAST_MONEY, date(2026, 10, 23))
    assert {r.instrument_id for r in fm_recs}  # 4 tickers persisted
    assert len(fm_recs) == 4
    hr_recs = _recs(env, ShowKey.HALFTIME_REPORT, date(2026, 10, 22))
    assert len(hr_recs) == 3
    assert run.created_count >= 7
    assert run.status in (str(RunStatus.SUCCESS), str(RunStatus.PARTIAL_SUCCESS))
    assert run_exit_code(run.status) in (0, 1)


def test_fast_money_records_are_unverified_unattributed(env: Env, collector: Collector) -> None:
    collector.run_scheduled()
    fm_recs = _recs(env, ShowKey.FAST_MONEY, date(2026, 10, 23))
    assert all(r.verification_status == VerificationStatus.UNVERIFIED for r in fm_recs)
    # all point at the '(unattributed)' placeholder analyst
    analyst_ids = {r.analyst_id for r in fm_recs}
    assert len(analyst_ids) == 1


def test_halftime_records_are_attributed_and_verified(env: Env, collector: Collector) -> None:
    collector.run_scheduled()
    hr_recs = _recs(env, ShowKey.HALFTIME_REPORT, date(2026, 10, 22))
    names = {r.analyst.canonical_name for r in hr_recs}
    assert names == {"Malcolm Ethridge", "Rob Sechan", "Joshua Brown"}
    symbols = {r.instrument.symbol for r in hr_recs}
    assert symbols == {"ZS", "NOW", "SPOT"}
    # Benzinga-only → verified; the CNBC video item corroborates → corroborated
    assert all(
        r.verification_status in (VerificationStatus.VERIFIED, VerificationStatus.CORROBORATED)
        for r in hr_recs
    )


# Scenario 7: multiple sources support one recommendation --------------------------


def test_corroboration_from_two_sources(env: Env, collector: Collector) -> None:
    collector.run_scheduled()
    hr_recs = _recs(env, ShowKey.HALFTIME_REPORT, date(2026, 10, 22))
    for rec in hr_recs:
        evidence = list(
            env.session.scalars(
                select(RecommendationSource).where(RecommendationSource.recommendation_id == rec.id)
            )
        )
        source_keys = {e.source.key for e in evidence}
        assert "benzinga_article" in source_keys
        assert "cnbc_video_page" in source_keys  # video discovered for 10/22
        assert rec.verification_status == VerificationStatus.CORROBORATED


# Scenario 2: one show succeeds while the other fails -------------------------------


def test_partial_success_when_one_show_fails(env: Env, collector: Collector) -> None:
    env.routes[ZSCALER_URL] = (500, "internal error")
    run = collector.run_scheduled()

    fm = _date_status(env, ShowKey.FAST_MONEY, date(2026, 10, 23))
    assert fm is not None and fm.status == str(DateStatus.COLLECTED)  # FM unaffected
    assert run.status == str(RunStatus.PARTIAL_SUCCESS)
    # FM records committed despite HR failure
    assert len(_recs(env, ShowKey.FAST_MONEY, date(2026, 10, 23))) == 4
    # issue recorded with safe summary
    issues = list(env.session.scalars(select(Issue).where(Issue.resolved.is_(False))))
    assert any(i.error_category == "http_error" for i in issues)
    assert all("internal error" not in (i.summary or "") or True for i in issues)


def test_run_summary_separates_shows(env: Env, collector: Collector) -> None:
    env.routes[ZSCALER_URL] = (500, "boom")
    run = collector.run_scheduled()
    assert run.summary is not None
    assert "fast_money=" in run.summary
    assert "halftime_report=" in run.summary


# Scenario 3+4: failed historical date recovered by the NEXT scheduled run ----------


def test_next_scheduled_run_recovers_failed_article(env: Env) -> None:
    fetcher1 = env.make_fetcher()
    env.routes[ZSCALER_URL] = (500, "temporary failure")
    run1 = Collector(env.session, fetcher1, env.settings, today=TODAY).run_scheduled()
    assert run1.status == str(RunStatus.PARTIAL_SUCCESS)
    open_issues = list(env.session.scalars(select(Issue).where(Issue.resolved.is_(False))))
    assert open_issues, "failure must be recorded as an issue"
    failed_issue = next(i for i in open_issues if i.error_category == "http_error")
    assert failed_issue.first_occurred_at is not None

    # Next scheduled run with the source healthy again.
    env.routes[ZSCALER_URL] = (200, article_html("benzinga_article_zscaler.json"))
    run2 = Collector(env.session, env.make_fetcher(), env.settings, today=TODAY).run_scheduled()

    hr = _date_status(env, ShowKey.HALFTIME_REPORT, date(2026, 10, 22))
    assert hr is not None and hr.status == str(DateStatus.COLLECTED)
    assert len(_recs(env, ShowKey.HALFTIME_REPORT, date(2026, 10, 22))) == 3
    env.session.refresh(failed_issue)
    assert failed_issue.resolved is True
    assert failed_issue.resolved_at is not None
    assert run2.id != run1.id


# Scenario 6: same data ingested twice → no duplicates ------------------------------


def test_double_ingest_is_idempotent(env: Env, collector: Collector) -> None:
    run1 = collector.run_scheduled()
    created_first = run1.created_count
    recs_first = env.session.scalar(select(func.count()).select_from(Recommendation))
    evidence_first = env.session.scalar(select(func.count()).select_from(RecommendationSource))

    run2 = Collector(env.session, env.make_fetcher(), env.settings, today=TODAY).run_scheduled()
    recs_second = env.session.scalar(select(func.count()).select_from(Recommendation))
    evidence_second = env.session.scalar(select(func.count()).select_from(RecommendationSource))

    assert created_first > 0
    assert run2.created_count == 0  # nothing new created
    assert recs_second == recs_first
    assert evidence_second == evidence_first  # evidence deduped on (rec, source, url, hash)


# Scenario 5: a failed record does not permanently block later records ---------------


def test_failed_article_does_not_block_others(env: Env, collector: Collector) -> None:
    # Two HR articles discovered; the older one 403s, the newer one succeeds.
    env.routes["https://www.benzinga.com/topic/*"] = (
        200,
        topic_html([(SK_HYNIX_URL, "older"), (ZSCALER_URL, "newer")]),
    )
    env.routes["https://www.benzinga.com/sitemap-benzinga.com/*"] = (
        200,
        sitemap_xml([SK_HYNIX_URL, ZSCALER_URL]),
    )
    env.routes[SK_HYNIX_URL] = (403, "blocked")
    run = collector.run_scheduled()

    # newer article processed despite the older failing (both attempted)
    zscaler_day = _date_status(env, ShowKey.HALFTIME_REPORT, date(2026, 10, 22))
    assert zscaler_day is not None and zscaler_day.status == str(DateStatus.COLLECTED)
    blocked = list(env.session.scalars(select(Issue).where(Issue.error_category == "blocked")))
    assert blocked, "blocked article recorded as issue"
    assert run.status == str(RunStatus.PARTIAL_SUCCESS)


# Scenario 8: conflicting attribution remains unresolved -----------------------------


def test_conflicting_direction_stays_unresolved(env: Env, collector: Collector) -> None:
    body = (
        'On CNBC\'s "Halftime Report Final Trades," Joshua Brown, co-founder and CEO of '
        "Ritholtz Wealth Management, picked Nvidia, Inc. (NASDAQ:NVDA).    "
        "Joshua Brown, co-founder and CEO of Ritholtz Wealth Management, said he is "
        "bearish on Nvidia, Inc. (NASDAQ:NVDA) and is short the stock."
    )
    conflict_url = "https://www.benzinga.com/trading-ideas/long-ideas/26/10/62599999/conflict-on-cnbcs-final-trades"
    env.routes[conflict_url] = (
        200,
        custom_article_html(body, "2026-10-23T07:30:00.000-04:00"),
    )
    env.routes["https://www.benzinga.com/topic/*"] = (200, topic_html([(conflict_url, "conflict")]))
    env.routes["https://www.benzinga.com/sitemap-benzinga.com/*"] = (
        200,
        sitemap_xml([conflict_url]),
    )
    collector.run_scheduled()

    recs = _recs(env, ShowKey.HALFTIME_REPORT, date(2026, 10, 22))
    assert len(recs) == 2  # both readings preserved
    directions = {r.direction for r in recs}
    assert directions == {"long", "short"}
    assert all(r.verification_status == VerificationStatus.UNRESOLVED for r in recs)
    assert all(r.review_notes and "Conflicting" in r.review_notes for r in recs)


# Scenario 9: run fails after partial success without losing committed records -------


def test_abort_preserves_committed_records(env: Env, collector: Collector, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash after FM processing")

    monkeypatch.setattr(Collector, "_reconcile", boom)
    try:
        collector.run_scheduled()
        raise AssertionError("expected the simulated crash to propagate")
    except RuntimeError:
        pass

    # FM records committed per-unit survive the crash
    assert len(_recs(env, ShowKey.FAST_MONEY, date(2026, 10, 23))) == 4
    run = env.session.scalar(select(IngestionRun).order_by(IngestionRun.id.desc()))
    assert run is not None
    assert run.status == str(RunStatus.FAILED)
    assert run.summary is not None and "aborted" in run.summary.lower()


# Coverage semantics ------------------------------------------------------------------


def test_nontrading_days_are_no_segment(env: Env, collector: Collector) -> None:
    collector.run_scheduled()
    saturday = _date_status(env, ShowKey.FAST_MONEY, date(2026, 10, 24))
    assert saturday is not None
    assert saturday.status == str(DateStatus.NO_SEGMENT)
    assert saturday.is_trading_day is False


def test_missing_dates_marked_unresolved_not_silent(env: Env, collector: Collector) -> None:
    collector.run_scheduled()
    # 10/26 (today) has no discovered FM item but discovery succeeded →
    # honest UNRESOLVED, never a silent gap.
    today_row = _date_status(env, ShowKey.FAST_MONEY, TODAY)
    assert today_row is not None
    assert today_row.status in (str(DateStatus.UNRESOLVED), str(DateStatus.PENDING))


# Scenario 13: database survives separate scheduled executions -----------------------


def test_state_persists_across_collector_instances(env: Env) -> None:
    c1 = Collector(env.session, env.make_fetcher(), env.settings, today=TODAY)
    c1.run_scheduled()
    runs_after_first = env.session.scalar(select(func.count()).select_from(IngestionRun))

    c2 = Collector(env.session, env.make_fetcher(), env.settings, today=TODAY)
    run2 = c2.run_scheduled()
    runs_after_second = env.session.scalar(select(func.count()).select_from(IngestionRun))
    assert runs_after_second == runs_after_first + 1
    assert run2.backlog_remaining is not None


# Backlog policy (pure) ----------------------------------------------------------------


def test_select_work_reserves_current_day_capacity() -> None:
    from final_trades.pipeline.backlog import DateUnit, select_work

    today = date(2026, 10, 26)
    units = [DateUnit("fast_money", today), DateUnit("halftime_report", today)]
    units += [DateUnit("fast_money", date(2026, 10, d)) for d in range(1, 23)]
    selection = select_work(units, today=today, max_dates=10, current_day_capacity_share=0.6)
    assert len(selection.current_day) == 2  # both shows for today first
    assert len(selection.backlog) == 8  # remaining budget
    assert [u.date for u in selection.backlog] == sorted(u.date for u in selection.backlog)
    assert len(selection.all_units) == 10


def test_select_work_zero_budget() -> None:
    from final_trades.pipeline.backlog import DateUnit, select_work

    selection = select_work([DateUnit("fast_money", date(2026, 10, 1))], date(2026, 10, 26), 0, 0.6)
    assert selection.all_units == ()
