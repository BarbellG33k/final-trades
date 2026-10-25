"""CNBC source adapters: site-search discovery, Fast Money RSS, video pages.

Evidence (docs/source-validation.md, probed 2026-10-25):
- The queryly-powered public site search returns both shows' Final Trade
  videos with exact segment dates: Fast Money titles are
  "Final Trade: <TICKERS>" and Halftime titles are
  "Final Trades: <Company Names>"; the `section` field names the show.
- The official Fast Money RSS feed (id=15838499) carries the daily
  "Final Trade:" video item (~1 week window).
- Video pages embed JSON-LD VideoObject (name, uploadDate, description).
  No transcripts are published, so Fast Money analyst attribution is not
  available from CNBC — those records persist as unverified/(unattributed).
- cnbc.com does not bot-wall plain HTTP clients (verified 200 with curl).
"""

from __future__ import annotations

import contextlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import feedparser

from final_trades.domain import (
    MAX_EXCERPT_LENGTH,
    Confidence,
    Direction,
    ErrorCategory,
    ExtractionMethod,
    PositionType,
    ShowKey,
    SourceKey,
    Stage,
)
from final_trades.sources.contracts import (
    DiscoveredItem,
    Evidence,
    FetchFailure,
    FetchResult,
    ParsedSegment,
    RawRecommendation,
)

ET = ZoneInfo("America/New_York")

SEARCH_URL = (
    "https://api.queryly.com/cnbc/json.aspx"
    "?queryly_key=31a35d40a9a64ab3&query=%22final%20trade%22"
    "&endindex={offset}&batchsize={batch}&sort=datepublished"
)
FAST_MONEY_RSS_URL = (
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15838499"
)

# "Final Trade: NVDA, JPM, SLB, XMAG" (Fast Money, tickers)
FM_TITLE = re.compile(r"^Final Trade:\s*(.+)$", re.IGNORECASE)
# "Final Trades: Devon Energy, Lockheed Martin, ..." (Halftime, company names)
HR_TITLE = re.compile(r"^Final Trades:\s*(.+)$", re.IGNORECASE)
# A token that looks like a US ticker symbol (letters, dots, dashes; <=6 chars
# covers BRK.B style; longer words are company names, not symbols).
TICKER_TOKEN = re.compile(r"^[A-Z][A-Z.\-]{0,5}$")
# Word-named instruments seen in Fast Money titles (curated from evidence).
FM_PHRASE_INSTRUMENTS: dict[str, tuple[str, str]] = {
    "10-year": ("US10Y", "fixed_income"),
    "10 year": ("US10Y", "fixed_income"),
    "us 10-year": ("US10Y", "fixed_income"),
    "treasury": ("US10Y", "fixed_income"),
    "telecom": ("TELECOM", "other"),  # sector mention, not a priced instrument
    "bitcoin": ("BTC-USD", "crypto"),
}


def search_url(offset: int, batch: int = 50) -> str:
    return SEARCH_URL.format(offset=offset, batch=batch)


def _et_date(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ET)


def parse_search_results(payload: str) -> list[DiscoveredItem] | FetchFailure:
    """Parse queryly search JSON into discovered Final Trade video items."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError) as exc:
        return FetchFailure(
            ErrorCategory.PARSE, Stage.PARSE, f"Invalid search JSON: {type(exc).__name__}"
        )
    items: list[DiscoveredItem] = []
    for result in data.get("results", []):
        title = str(result.get("cn:title") or result.get("title") or "")
        section = str(result.get("section") or "")
        url = str(result.get("url") or "")
        published_raw = result.get("datePublished") or result.get("cn:lastPubDate")
        if not url or not (FM_TITLE.match(title) or HR_TITLE.match(title)):
            continue
        show: ShowKey | None = None
        source_key = SourceKey.CNBC_VIDEO_PAGE
        if "Fast Money" in section or FM_TITLE.match(title):
            show = ShowKey.FAST_MONEY
        elif "Halftime" in section or HR_TITLE.match(title):
            show = ShowKey.HALFTIME_REPORT
        published_at = None
        if isinstance(published_raw, str):
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = None
        items.append(
            DiscoveredItem(
                url=url,
                show=show,
                published_at=published_at,
                title=title,
                source_key=str(source_key),
                hint={"section": section},
            )
        )
    return items


def parse_rss(payload: str) -> list[DiscoveredItem] | FetchFailure:
    """Parse the official Fast Money RSS feed; keep Final Trade items only."""
    feed = feedparser.parse(payload)
    if feed.bozo and not feed.entries:
        return FetchFailure(ErrorCategory.PARSE, Stage.PARSE, "Unparseable RSS payload")
    items: list[DiscoveredItem] = []
    for entry in feed.entries:
        title = str(entry.get("title") or "")
        if not FM_TITLE.match(title):
            continue
        link = str(entry.get("link") or "")
        if not link:
            continue
        published_at = None
        if entry.get("published_parsed"):
            t = entry.published_parsed
            published_at = datetime(
                t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, tzinfo=UTC
            )
        items.append(
            DiscoveredItem(
                url=link,
                show=ShowKey.FAST_MONEY,
                published_at=published_at,
                title=title,
                source_key=str(SourceKey.CNBC_RSS_FAST_MONEY),
            )
        )
    return items


def parse_fm_tickers(title: str) -> list[tuple[str, str | None]]:
    """Extract (ticker_raw, asset_hint) pairs from a Fast Money title.

    Returns the raw token plus an asset hint when the token is a curated
    word-named instrument; None asset hint means 'looks like a symbol'.
    """
    m = FM_TITLE.match(title)
    if not m:
        return []
    parts = [p.strip() for p in m.group(1).split(",")]
    # Trailing "and X" conjunction: "A, B and C"
    expanded: list[str] = []
    for part in parts:
        if " and " in part.lower():
            idx = part.lower().rfind(" and ")
            expanded.extend([part[:idx].strip(), part[idx + 5 :].strip()])
        else:
            expanded.append(part)
    out: list[tuple[str, str | None]] = []
    for token in expanded:
        if not token:
            continue
        phrase = FM_PHRASE_INSTRUMENTS.get(token.lower())
        if phrase:
            out.append(phrase)
        elif TICKER_TOKEN.match(token):
            out.append((token, None))
        else:
            # Non-symbol word (e.g. "Telecom"): keep raw, unpriced instrument.
            out.append((token.upper().replace(" ", "-"), "other"))
    return out


def extract_video_ldjson(html: str) -> dict[str, Any] | None:
    for block in re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "VideoObject":
                return item
    return None


def video_url_date(url: str) -> datetime | None:
    m = re.search(r"cnbc\.com/video/(\d{4})/(\d{2})/(\d{2})/", url) or re.search(
        r"cnbc\.com/video/(\d{4})-(\d{2})-(\d{2})/", url
    )
    if not m:
        return None
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 12, 0, tzinfo=ET)


def parse_video_page(
    fetch: FetchResult,
    show: ShowKey,
    title_hint: str | None = None,
    published_hint: datetime | None = None,
) -> ParsedSegment | FetchFailure:
    """Parse a CNBC Final Trade video page into a ParsedSegment.

    Fast Money: tickers from the title become recommendations with
    (unattributed) analysts and verification=unverified — CNBC publishes no
    attribution for these segments. Halftime: the video page records segment
    existence/date only; recommendations come from the Benzinga article.
    """
    video = extract_video_ldjson(fetch.body)
    name = str((video or {}).get("name") or title_hint or "")
    description = str((video or {}).get("description") or "")
    upload_raw = (video or {}).get("uploadDate")
    published: datetime | None = published_hint
    if isinstance(upload_raw, str):
        with contextlib.suppress(ValueError):
            published = datetime.fromisoformat(upload_raw.replace("Z", "+00:00"))
    segment_dt = published or video_url_date(fetch.url)
    if segment_dt is None or not name:
        return FetchFailure(
            ErrorCategory.PARSE, Stage.PARSE, "Video page lacks name/date", url=fetch.url
        )
    segment_date = _et_date(segment_dt).date()

    excerpt = f"{name}. {description}".strip()[:MAX_EXCERPT_LENGTH]
    evidence = Evidence(
        url=fetch.url,
        retrieved_at=fetch.retrieved_at,
        content_sha256=fetch.content_sha256,
        excerpt=excerpt or name[:MAX_EXCERPT_LENGTH],
        excerpt_kind="title",
        published_at=published,
    )
    recs: tuple[RawRecommendation, ...] = ()
    if show == ShowKey.FAST_MONEY:
        parsed = parse_fm_tickers(name)
        if not parsed:
            return FetchFailure(
                ErrorCategory.ATTRIBUTION,
                Stage.PARSE,
                "Fast Money title contained no instruments",
                url=fetch.url,
                detail={"title": name[:120]},
            )
        recs = tuple(
            RawRecommendation(
                ticker_raw=ticker_raw,
                analyst_name_raw=None,  # CNBC publishes no FM attribution
                analyst_title_raw=None,
                direction=Direction.LONG,
                position_type=PositionType.UNKNOWN,
                thesis=f"Named in CNBC Fast Money segment '{name}' (no per-trader attribution published).",
                confidence=Confidence.MEDIUM if asset_hint is None else Confidence.LOW,
                extraction_method=ExtractionMethod.CNBC_VIDEO_PAGE,
                evidence=evidence,
            )
            for ticker_raw, asset_hint in parsed
        )
    return ParsedSegment(
        show=show,
        segment_date=segment_date,
        title=name[:512] or None,
        recommendations=recs,
        evidence=(evidence,),
        segment_date_basis="video_upload_date_et" if published else "video_url_date",
        source_key=str(SourceKey.CNBC_VIDEO_PAGE),
    )
