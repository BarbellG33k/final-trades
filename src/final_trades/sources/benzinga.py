"""Benzinga source adapters: sitemap/topic discovery + article parsing.

Evidence (docs/source-validation.md, probed 2026-10-25):
- Article pages embed JSON-LD NewsArticle with `articleBody` containing
  explicit attribution: "<Analyst>, <title>, <pick-verb> <Company>
  (<EXCHANGE>:<TICKER>)" plus a lead-in naming the show.
- Halftime articles publish the morning AFTER the segment airs
  (verified: published 2026-10-23T07:51 ET ↔ CNBC video dated 2026-10-22),
  so segment_date = previous_trading_day(datePublished).
- Monthly archive sitemaps (robots.txt-listed) enumerate all article URLs:
  https://www.benzinga.com/sitemap-benzinga.com/www/archive/YYYY/MM.xml
- benzinga.com sits behind Cloudflare; browser-TLS transport required
  (see sources/http.py IMPERSONATED_HOSTS).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

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
from final_trades.market_calendar import previous_trading_day
from final_trades.sources.contracts import (
    DiscoveredItem,
    Evidence,
    FetchFailure,
    FetchResult,
    ParsedSegment,
    RawRecommendation,
)

TOPIC_URLS: dict[ShowKey, str] = {
    ShowKey.HALFTIME_REPORT: "https://www.benzinga.com/topic/halftime-report-final-trades",
    ShowKey.FAST_MONEY: "https://www.benzinga.com/topic/fast-money-final-trade",
}
ARCHIVE_SITEMAP_URL = (
    "https://www.benzinga.com/sitemap-benzinga.com/www/archive/{year}/{month:02d}.xml"
)

_LDJSON_SCRIPT = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
# Exchange-qualified tickers as written by Benzinga: (NASDAQ:TTAN), (NYSE:NOW)
EXCHANGE_TICKER = re.compile(r"\(([A-Z]{2,10})\s*:\s*([A-Z][A-Z0-9.\-^]{0,11})\)")
# Non-ticker instruments named in words (curated, evidence-based only).
PHRASE_INSTRUMENTS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"\b(?:U\.S\.|US)?\s*10[\s-]*(?:Year|Yr|year)\s*(?:U\.S\.\s*)?Treasury(?:\s+[Nn]otes?)?\b"
        ),
        "US10Y",
        "fixed_income",
    ),
    (re.compile(r"\bBitcoin\b"), "BTC-USD", "crypto"),
)
PICK_CUES = re.compile(
    r"\b(?:picked|picks|named|names|recommended|recommends|selected|selects|chose|"
    r"chooses|backs|backed|backing|favored|favors|favours|touted|touts|highlighted|"
    r"highlights|likes|loves|bought|is buying|adding|added|urged|urges|"
    r"suggests|suggested|sees upside|is bullish on|is bearish on|sticking with|"
    r"is a great stock to buy|said)\b",
    re.IGNORECASE,
)
RATING_CUES = re.compile(
    r"\b(?:initiated|reiterated|maintained|upgraded|downgraded|assigned|"
    r"price target|rating on|coverage of)\b",
    re.IGNORECASE,
)
SUPPORTING_CUES = re.compile(
    r"\b(?:Supporting (?:his|her|their|the) (?:choice|view)|according to)\b", re.IGNORECASE
)
# Case-sensitive on purpose: "Short Hills Capital Partners" (a firm name)
# must not flip direction to short.
BEARISH_CUES = re.compile(r"\b(?:bearish|shorting|inverse)\b|\bshort\b|\bputs?\b")
# Person-name candidate: 2-4 capitalized words, may include "M." style initials.
NAME_CANDIDATE = re.compile(
    r"\b([A-Z][A-Za-z.'\u2019-]+(?:\s+(?:[A-Z]\.\s*)?[A-Z][A-Za-z.'\u2019-]+){1,3})\s*,"
)
ORG_WORDS = frozenset(
    {
        "Inc",
        "LLC",
        "Ltd",
        "Corp",
        "Corporation",
        "Company",
        "Co",
        "Bank",
        "Securities",
        "Capital",
        "Wealth",
        "Management",
        "Advisors",
        "Advisor",
        "Partners",
        "Partner",
        "Group",
        "Fund",
        "Funds",
        "Investments",
        "Investment",
        "Financial",
        "Holdings",
        "Analyst",
        "Strategist",
        "Chief",
        "Officer",
        "Head",
        "Director",
        "Manager",
        "President",
        "CEO",
        "CIO",
        "CTO",
        "CNBC",
        "Benzinga",
        "Street",
        "University",
        "Institute",
        "Association",
        "Exchange",
        "Markets",
        "Asset",
        "Trust",
        "Bancorp",
        "Treasury",
        "Federal",
        "Reserve",
        "Technology",
        "Technologies",
        "Energy",
        "Pharmaceuticals",
        "Solutions",
        "Services",
        "Systems",
        "Networks",
        "Global",
        "International",
        "National",
        "American",
        "First",
        "New",
        "Senior",
        "Junior",
        "Managing",
        "Executive",
        "VP",
        "Economist",
        "Trader",
        "Strategies",
        "Research",
        "Team",
        "Desk",
        "Report",
        "Halftime",
        "Money",
        "Fast",
        "Trade",
        "Trades",
    }
)
SHOW_HALFTIME_RE = re.compile(r"Halftime Report", re.IGNORECASE)
SHOW_FAST_MONEY_RE = re.compile(r"Fast Money", re.IGNORECASE)
# Abbreviations that must not terminate a "sentence" during thesis extraction.
_ABBREV = re.compile(
    r"\b(?:Inc|Ltd|Corp|Co|Jr|Sr|Mr|Ms|Mrs|Dr|No|vs|St|Oct|Nov|Dec|Jan|Feb|Mar|Apr|Aug|Sept|Sep|Ave|Blvd)\.$"
)


@dataclass(frozen=True)
class ArticleMeta:
    headline: str
    description: str | None
    date_published: datetime | None
    article_body: str
    url: str


def iter_ldjson(html: str) -> Iterator[dict[str, Any]]:
    for block in _LDJSON_SCRIPT.findall(html):
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                yield item


def extract_news_article(html: str) -> dict[str, Any] | None:
    for item in iter_ldjson(html):
        if item.get("@type") == "NewsArticle":
            return item
    return None


def parse_topic_listing(html: str, show: ShowKey, source_key: SourceKey) -> list[DiscoveredItem]:
    """Parse the JSON-LD ItemList on a Benzinga topic page."""
    items: list[DiscoveredItem] = []
    for entry in iter_ldjson(html):
        if entry.get("@type") != "CollectionPage":
            continue
        for li in entry.get("mainEntity", {}).get("itemListElement", []):
            url = li.get("url")
            name = li.get("name")
            if (
                isinstance(url, str)
                and isinstance(name, str)
                and url.startswith("https://www.benzinga.com/")
                and "/topic/" not in url  # skip self-links to the topic page
            ):
                items.append(
                    DiscoveredItem(
                        url=url.split("?")[0],
                        show=show,
                        published_at=None,
                        title=name,
                        source_key=str(source_key),
                    )
                )
    # de-dupe preserving order
    seen: set[str] = set()
    unique: list[DiscoveredItem] = []
    for it in items:
        if it.url not in seen:
            seen.add(it.url)
            unique.append(it)
    return unique


def parse_sitemap_urls(xml_text: str) -> list[str]:
    """All article URLs in a monthly archive sitemap whose slug mentions final trades."""
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text)
    return [
        u
        for u in urls
        if "final-trade" in u
        and u.startswith("https://www.benzinga.com/")
        and not u.endswith((".xml", ".json"))
    ]


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # e.g. 2026-10-23T07:51:26.000-04:00
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _split_sentences(text: str) -> list[str]:
    """Split on '. ' boundaries while respecting abbreviations and initials."""
    parts = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    sentences: list[str] = []
    buf = ""
    for part in parts:
        candidate = f"{buf} {part}".strip() if buf else part
        # Buffer single-letter initials ("Joseph M."), dotted acronyms
        # ("U.S."), and common abbreviations ("Inc.", "Oct.") that are not
        # sentence ends.
        if re.search(r"(?:^|\s)(?:[A-Z]\.){1,4}$", candidate) or _ABBREV.search(candidate[-8:]):
            buf = candidate
            continue
        sentences.append(candidate)
        buf = ""
    if buf:
        sentences.append(buf)
    return [s.strip() for s in sentences if s.strip()]


def _is_person_name(candidate: str) -> bool:
    tokens = candidate.split()
    if not 2 <= len(tokens) <= 4:
        return False
    for tok in tokens:
        cleaned = tok.rstrip(".,").strip("'\u2019")
        if not cleaned:
            continue
        if cleaned in ORG_WORDS or cleaned.upper() in ORG_WORDS:
            return False
        if not cleaned[0].isupper():
            return False
    return True


def _analyst_before(window: str, cue_pos: int) -> tuple[str, str | None] | None:
    """Find the person name that a pick cue attributes to, within window[:cue_pos]."""
    region = window[:cue_pos]
    matches = list(NAME_CANDIDATE.finditer(region))
    # Walk backwards: closest plausible person name to the cue wins.
    for m in reversed(matches):
        name = m.group(1).strip()
        if not _is_person_name(name):
            continue
        # Reject rating-style phrasing: "<Org> analyst <Name> reiterated ..."
        between = region[m.end() :]
        if RATING_CUES.search(between) and not PICK_CUES.search(between):
            return None
        title = None
        title_m = re.search(r",\s*([^,]{5,120}?),\s*$", region[m.start() :])
        if title_m:
            title = title_m.group(1).strip()
        return name, title
    return None


@dataclass(frozen=True)
class _Mention:
    ticker_raw: str
    asset_hint: str | None
    start: int
    end: int


def _find_mentions(body: str) -> list[_Mention]:
    mentions: list[_Mention] = []
    for m in EXCHANGE_TICKER.finditer(body):
        mentions.append(
            _Mention(ticker_raw=m.group(2), asset_hint=None, start=m.start(), end=m.end())
        )
    for pattern, symbol, asset in PHRASE_INSTRUMENTS:
        for m in pattern.finditer(body):
            mentions.append(
                _Mention(ticker_raw=symbol, asset_hint=asset, start=m.start(), end=m.end())
            )
    mentions.sort(key=lambda x: x.start)
    return mentions


def extract_raw_recommendations(body: str) -> list[RawRecommendation]:
    """Extract analyst→instrument calls from a Benzinga Final Trades article body."""
    results: list[RawRecommendation] = []
    sentences = _split_sentences(body)
    # Map char offsets of sentences for windowing.
    for sentence in sentences:
        for mention in _find_mentions(sentence):
            window = sentence[: mention.start]
            cue = None
            for cue_match in PICK_CUES.finditer(window):
                cue = cue_match
            if cue is None:
                continue  # no pick verb → supporting/rating sentence, skip
            if SUPPORTING_CUES.search(window) and not PICK_CUES.search(
                window[window.rfind(",") + 1 :]
            ):
                continue
            analyst = _analyst_before(window, cue.start())
            if analyst is None:
                continue  # unattributable in this sentence; other sentences may cover it
            name, title = analyst
            thesis_source = sentence.strip()
            thesis = thesis_source[:MAX_EXCERPT_LENGTH]
            direction = Direction.SHORT if BEARISH_CUES.search(thesis_source) else Direction.LONG
            results.append(
                RawRecommendation(
                    ticker_raw=mention.ticker_raw,
                    analyst_name_raw=name,
                    analyst_title_raw=title,
                    direction=direction,
                    position_type=PositionType.UNKNOWN,
                    thesis=thesis,
                    confidence=Confidence.HIGH if mention.asset_hint is None else Confidence.MEDIUM,
                    extraction_method=ExtractionMethod.BENZINGA_ARTICLE,
                    evidence=None,  # attached by caller (needs retrieval provenance)
                )
            )
    return results


def detect_show(body: str, headline: str, expected: ShowKey | None) -> ShowKey | None:
    text = f"{body[:600]} {headline}"
    if SHOW_HALFTIME_RE.search(text):
        return ShowKey.HALFTIME_REPORT
    if SHOW_FAST_MONEY_RE.search(text):
        return ShowKey.FAST_MONEY
    return expected


def derive_segment_date(published: datetime, show: ShowKey) -> tuple[date, str]:
    """Halftime articles publish the morning after the segment (verified)."""
    if show == ShowKey.HALFTIME_REPORT:
        return previous_trading_day(published.date()), "published_minus_one_trading_day"
    return published.date(), "published_same_day"


def parse_article(
    fetch: FetchResult,
    expected_show: ShowKey | None = None,
    source_key: SourceKey = SourceKey.BENZINGA_ARTICLE,
) -> ParsedSegment | FetchFailure:
    """Parse one Benzinga Final Trades article into a ParsedSegment."""
    article = extract_news_article(fetch.body)
    if article is None:
        return FetchFailure(
            ErrorCategory.PARSE,
            Stage.PARSE,
            "No NewsArticle JSON-LD found",
            url=fetch.url,
        )
    body = (article.get("articleBody") or "").strip()
    headline = str(article.get("headline") or "")
    if not body:
        return FetchFailure(ErrorCategory.PARSE, Stage.PARSE, "Empty articleBody", url=fetch.url)
    published = parse_iso_datetime(article.get("datePublished"))
    if published is None:
        return FetchFailure(
            ErrorCategory.PARSE, Stage.PARSE, "Missing/invalid datePublished", url=fetch.url
        )
    show = detect_show(body, headline, expected_show)
    if show is None:
        return FetchFailure(
            ErrorCategory.ATTRIBUTION,
            Stage.PARSE,
            "Article does not name the show; refusing to guess",
            url=fetch.url,
        )
    segment_date, basis = derive_segment_date(published, show)
    raw_recs = extract_raw_recommendations(body)
    excerpt = _build_excerpt(headline, body)
    evidence = Evidence(
        url=fetch.url,
        retrieved_at=fetch.retrieved_at,
        content_sha256=fetch.content_sha256,
        excerpt=excerpt,
        excerpt_kind="body",
        published_at=published,
    )
    recs = tuple(
        RawRecommendation(
            ticker_raw=r.ticker_raw,
            analyst_name_raw=r.analyst_name_raw,
            analyst_title_raw=r.analyst_title_raw,
            direction=r.direction,
            position_type=r.position_type,
            thesis=r.thesis,
            confidence=r.confidence,
            extraction_method=r.extraction_method,
            evidence=evidence,
        )
        for r in raw_recs
    )
    if not recs:
        return FetchFailure(
            ErrorCategory.ATTRIBUTION,
            Stage.PARSE,
            "No analyst→instrument attribution found in body",
            url=fetch.url,
            detail={"headline": headline[:120], "body_len": len(body)},
        )
    return ParsedSegment(
        show=show,
        segment_date=segment_date,
        title=headline[:512] or None,
        recommendations=recs,
        evidence=(evidence,),
        segment_date_basis=basis,
        source_key=str(source_key),
    )


def _build_excerpt(headline: str, body: str) -> str:
    """Short attributed excerpt: lead-in + first pick sentence (fair-use length)."""
    sentences = _split_sentences(body)
    lead = sentences[0] if sentences else body[:200]
    excerpt = f"{headline.split(' - ')[0]}. {lead}"
    return excerpt[:MAX_EXCERPT_LENGTH]


def article_url_month(url: str) -> tuple[int, int] | None:
    """(year, month) from a Benzinga article URL path like /26/10/<id>/."""
    m = re.search(r"benzinga\.com/[^/]+/[^/]+/(\d{2})/(\d{2})/", url)
    if not m:
        return None
    return 2000 + int(m.group(1)), int(m.group(2))


def sitemap_url_for(d: date) -> str:
    return ARCHIVE_SITEMAP_URL.format(year=d.year, month=d.month)


def is_final_trades_slug(url: str) -> bool:
    path = urlparse(url).path.lower()
    return "final-trade" in path
