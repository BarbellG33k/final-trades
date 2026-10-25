"""Integration test environment: in-memory DB + fixture-backed fake HTTP.

No live network. Routes serve the recorded fixtures in tests/fixtures/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from final_trades.config import Settings
from final_trades.db import models
from final_trades.db.seed import ensure_reference_data
from final_trades.sources.http import PoliteFetcher, TransportResponse

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

ROBOTS_ALLOW = "User-agent: *\nDisallow:\n"

# Fixture article URLs (from the recorded sitemap/topic fixtures).
ZSCALER_URL = (
    "https://www.benzinga.com/trading-ideas/long-ideas/26/10/62555175/"
    "servicenow-zscaler-and-a-music-streaming-giant-on-cnbcs-final-trades"
)
SK_HYNIX_URL = (
    "https://www.benzinga.com/trading-ideas/long-ideas/26/10/62241548/"
    "servicetitan-meta-sk-hynix-and-a-consumer-cyclical-stock-on-cnbcs-final-trades"
)
TREASURY_URL = (
    "https://www.benzinga.com/trading-ideas/long-ideas/26/10/62102848/"
    "meta-millrose-properties-cboe-global-markets-and-more-on-cnbcs-final-trades"
)
FM_VIDEO_URL = "https://www.cnbc.com/video/2026-10-23/final-trade-nvda-jpm-slb-xmag.html"

TODAY = date(2026, 10, 26)  # Monday after the fixture week


def _wrap_ldjson(payload: dict) -> str:
    return f'<html><head><script type="application/ld+json">{json.dumps(payload)}</script></head><body></body></html>'


def article_html(fixture_name: str) -> str:
    data = json.loads((FIXTURES / fixture_name).read_text())
    return _wrap_ldjson(data["news_article_ldjson"])


def video_html(name: str, upload_date: str, description: str = "Final trades of the day.") -> str:
    return _wrap_ldjson(
        {
            "@type": "VideoObject",
            "name": name,
            "description": description,
            "uploadDate": upload_date,
        }
    )


def custom_article_html(body: str, published: str, headline: str = "Test Final Trades") -> str:
    return _wrap_ldjson(
        {
            "@type": "NewsArticle",
            "headline": headline,
            "datePublished": published,
            "articleBody": body,
        }
    )


def sitemap_xml(urls: list[str]) -> str:
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>"
    )


def topic_html(article_urls: list[tuple[str, str]]) -> str:
    items = [
        {"@type": "ListItem", "position": i + 1, "url": u, "name": t}
        for i, (u, t) in enumerate(article_urls)
    ]
    return _wrap_ldjson(
        {
            "@type": "CollectionPage",
            "url": "https://www.benzinga.com/topic/halftime-report-final-trades",
            "mainEntity": {"@type": "ItemList", "itemListElement": items},
        }
    )


@dataclass
class Env:
    session: Session
    settings: Settings
    routes: dict[str, tuple[int, str]] = field(default_factory=dict)
    requested: list[str] = field(default_factory=list)

    def make_fetcher(self) -> PoliteFetcher:
        outer = self

        class _Transport:
            def get(self, url: str, timeout: float) -> TransportResponse:
                outer.requested.append(url)
                for pattern, (status, body) in outer.routes.items():
                    if pattern.endswith("*") and url.startswith(pattern[:-1]):
                        return TransportResponse(status, body.encode(), url)
                    if pattern == url:
                        return TransportResponse(status, body.encode(), url)
                return TransportResponse(404, b"not routed", url)

        transport = _Transport()
        return PoliteFetcher(
            settings=self.settings,
            transport=transport,
            impersonated_transport=transport,
            sleep=lambda _: None,
            robots_enabled=True,
        )


def default_routes() -> dict[str, tuple[int, str]]:
    """Routes reproducing the fixture week: FM videos + HR articles for both shows."""
    search = (FIXTURES / "cnbc_search_results.json").read_text()
    rss = (FIXTURES / "cnbc_fastmoney_rss.xml").read_text()
    return {
        # robots for every host we touch
        "https://www.benzinga.com/robots.txt": (200, ROBOTS_ALLOW),
        "https://api.queryly.com/robots.txt": (200, ROBOTS_ALLOW),
        "https://search.cnbc.com/robots.txt": (200, ROBOTS_ALLOW),
        "https://www.cnbc.com/robots.txt": (200, ROBOTS_ALLOW),
        # discovery
        "https://api.queryly.com/*": (200, search),
        "https://search.cnbc.com/*": (200, rss),
        "https://www.benzinga.com/topic/*": (200, topic_html([(ZSCALER_URL, "Zscaler article")])),
        "https://www.benzinga.com/sitemap-benzinga.com/*": (200, sitemap_xml([ZSCALER_URL])),
        # details
        ZSCALER_URL: (200, article_html("benzinga_article_zscaler.json")),
        SK_HYNIX_URL: (200, article_html("benzinga_article_sk_hynix.json")),
        TREASURY_URL: (200, article_html("benzinga_article_treasury.json")),
        "https://www.cnbc.com/video/*": (
            200,
            video_html("Final Trade: NVDA, JPM, SLB, XMAG", "2026-10-23T22:04:09.000Z"),
        ),
    }


def build_env() -> Env:
    """Construct a fresh integration environment (in-memory SQLite + routes)."""
    engine = create_engine("sqlite://", future=True)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    ensure_reference_data(session)
    settings = Settings(
        DATABASE_URL="sqlite://",
        HTTP_MIN_REQUEST_INTERVAL_SECONDS=2.0,
        BACKFILL_START_DATE="2026-10-01",
        BACKFILL_END_DATE="2026-10-31",
        BACKLOG_MAX_DATES_PER_RUN=20,
        CURRENT_DAY_CAPACITY_SHARE=0.6,
    )
    return Env(session=session, settings=settings, routes=default_routes())
