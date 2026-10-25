"""Idempotent seeding of static reference rows (shows, sources, placeholder analyst).

Called after migrations by the CLI bootstrap and by test fixtures. Safe to
run repeatedly: rows are keyed on natural unique keys.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from final_trades.db.models import Analyst, Show, Source
from final_trades.domain import UNATTRIBUTED_ANALYST_NAME, ShowKey, SourceKey

SHOWS: list[dict[str, str]] = [
    {
        "key": ShowKey.HALFTIME_REPORT,
        "name": "CNBC Halftime Report",
        "description": "Midday market show; 'Final Trades' segment airs near the close of the program.",
    },
    {
        "key": ShowKey.FAST_MONEY,
        "name": "CNBC Fast Money",
        "description": "Post-market show hosted by Melissa Lee; 'Final Trade' segment closes each episode.",
    },
]

SOURCES: list[dict[str, str]] = [
    {
        "key": SourceKey.BENZINGA_HALFTIME_TOPIC,
        "name": "Benzinga — Halftime Report Final Trades topic",
        "base_url": "https://www.benzinga.com/topic/halftime-report-final-trades",
        "kind": "listing",
    },
    {
        "key": SourceKey.BENZINGA_FAST_MONEY_TOPIC,
        "name": "Benzinga — Fast Money Final Trade topic",
        "base_url": "https://www.benzinga.com/topic/fast-money-final-trade",
        "kind": "listing",
    },
    {
        "key": SourceKey.BENZINGA_ARTICLE,
        "name": "Benzinga — article pages",
        "base_url": "https://www.benzinga.com/",
        "kind": "article",
    },
    {
        "key": SourceKey.CNBC_RSS_FAST_MONEY,
        "name": "CNBC — Fast Money RSS feed",
        "base_url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15838499",
        "kind": "rss",
    },
    {
        "key": SourceKey.CNBC_VIDEO_PAGE,
        "name": "CNBC — video pages",
        "base_url": "https://www.cnbc.com/video/",
        "kind": "video",
    },
]


def ensure_reference_data(session: Session) -> None:
    """Insert shows, sources, and the '(unattributed)' analyst placeholder if absent."""
    for spec in SHOWS:
        if session.scalar(select(Show).where(Show.key == spec["key"])) is None:
            session.add(Show(**spec))
    for spec in SOURCES:
        if session.scalar(select(Source).where(Source.key == spec["key"])) is None:
            session.add(Source(**spec))
    if (
        session.scalar(select(Analyst).where(Analyst.canonical_name == UNATTRIBUTED_ANALYST_NAME))
        is None
    ):
        session.add(
            Analyst(
                canonical_name=UNATTRIBUTED_ANALYST_NAME,
                name_variants=[],
                notes="Placeholder for segment calls without evidenced analyst attribution.",
            )
        )
    session.commit()


def get_show(session: Session, key: ShowKey | str) -> Show:
    show = session.scalar(select(Show).where(Show.key == str(key)))
    if show is None:
        raise LookupError(f"show {key!r} not seeded — call ensure_reference_data() first")
    return show


def get_source(session: Session, key: SourceKey | str) -> Source:
    source = session.scalar(select(Source).where(Source.key == str(key)))
    if source is None:
        raise LookupError(f"source {key!r} not seeded — call ensure_reference_data() first")
    return source


def get_unattributed_analyst(session: Session) -> Analyst:
    analyst = session.scalar(
        select(Analyst).where(Analyst.canonical_name == UNATTRIBUTED_ANALYST_NAME)
    )
    if analyst is None:
        raise LookupError("placeholder analyst not seeded — call ensure_reference_data() first")
    return analyst
