"""Unit tests for the Benzinga source adapter parsing functions."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from final_trades.domain import Confidence, Direction, ErrorCategory, ShowKey, SourceKey, Stage
from final_trades.sources import benzinga
from final_trades.sources.contracts import ParsedSegment
from helpers.helpers import article_html, assert_failure, fetch_result, fixture_json, fixture_text


def _parse(fixture_name: str) -> ParsedSegment:
    html, url = article_html(fixture_name)
    result = benzinga.parse_article(fetch_result(html, url), expected_show=None)
    assert isinstance(result, ParsedSegment), f"expected segment, got {result}"
    return result


def test_parse_zscaler_article() -> None:
    seg = _parse("benzinga_article_zscaler.json")
    assert seg.show == ShowKey.HALFTIME_REPORT
    # Published Fri 2026-10-23T07:51 ET → segment Thu 2026-10-22
    assert seg.segment_date == date(2026, 10, 22)
    assert seg.segment_date_basis == "published_minus_one_trading_day"
    picks = {(r.analyst_name_raw, r.ticker_raw): r for r in seg.recommendations}
    assert ("Malcolm Ethridge", "ZS") in picks
    assert ("Rob Sechan", "NOW") in picks
    assert ("Joshua Brown", "SPOT") in picks
    assert len(seg.recommendations) == 3
    zs = picks[("Malcolm Ethridge", "ZS")]
    assert zs.direction == Direction.LONG
    assert zs.confidence == Confidence.HIGH
    assert zs.evidence is not None
    assert zs.evidence.url.endswith("final-trades")
    assert zs.evidence.content_sha256
    assert 0 < len(zs.evidence.excerpt) <= 600
    # Supporting rating sentences must NOT create recommendations
    assert all(r.ticker_raw != "C" for r in seg.recommendations)


def test_parse_sk_hynix_article() -> None:
    seg = _parse("benzinga_article_sk_hynix.json")
    assert seg.segment_date == date(2026, 10, 7)
    picks = {(r.analyst_name_raw, r.ticker_raw): r for r in seg.recommendations}
    assert ("Joshua Brown", "TTAN") in picks
    assert ("Stephanie Link", "META") in picks
    assert ("Joseph M. Terranova", "ABNB") in picks
    assert ("Stephen Weiss", "SKHY") in picks
    # "Short Hills Capital Partners" must not flip direction to short
    assert all(r.direction == Direction.LONG for r in seg.recommendations)


def test_parse_treasury_article() -> None:
    seg = _parse("benzinga_article_treasury.json")
    assert seg.segment_date == date(2026, 9, 30)
    picks = {(r.analyst_name_raw, r.ticker_raw): r for r in seg.recommendations}
    assert ("Joseph M. Terranova", "CBOE") in picks
    assert ("Liz Thomas", "US10Y") in picks
    assert ("Jenny Van Leeuwen Harrington", "MRP") in picks
    assert ("Stephen Weiss", "META") in picks
    assert picks[("Liz Thomas", "US10Y")].confidence == Confidence.MEDIUM


def test_thesis_is_verbatim_sentence() -> None:
    seg = _parse("benzinga_article_zscaler.json")
    zs = next(r for r in seg.recommendations if r.ticker_raw == "ZS")
    assert zs.thesis is not None
    assert "Malcolm Ethridge" in zs.thesis
    assert "Zscaler" in zs.thesis


def test_parse_article_missing_show_is_attribution_failure() -> None:
    art = fixture_json("benzinga_article_zscaler.json")["news_article_ldjson"]
    art["articleBody"] = art["articleBody"].replace("Halftime Report Final Trades", "some segment")
    html = '<script type="application/ld+json">' + json.dumps(art) + "</script>"
    failure = benzinga.parse_article(fetch_result(html), expected_show=None)
    assert_failure(failure, ErrorCategory.ATTRIBUTION, Stage.PARSE)


def test_parse_article_no_attribution_found() -> None:
    art = fixture_json("benzinga_article_zscaler.json")["news_article_ldjson"]
    art["articleBody"] = (
        'On CNBC\'s "Halftime Report Final Trades," markets rose broadly on Thursday.'
    )
    html = '<script type="application/ld+json">' + json.dumps(art) + "</script>"
    failure = benzinga.parse_article(fetch_result(html), expected_show=None)
    assert_failure(failure, ErrorCategory.ATTRIBUTION, Stage.PARSE)


def test_parse_article_no_ldjson() -> None:
    failure = benzinga.parse_article(fetch_result("<html><body>nothing</body></html>"))
    assert_failure(failure, ErrorCategory.PARSE, Stage.PARSE)


def test_topic_listing_dedupes_and_filters() -> None:
    entry = fixture_json("benzinga_topic_collectionpage.json")
    html = '<script type="application/ld+json">' + json.dumps(entry) + "</script>"
    items = benzinga.parse_topic_listing(
        html, ShowKey.HALFTIME_REPORT, SourceKey.BENZINGA_HALFTIME_TOPIC
    )
    urls = [i.url for i in items]
    assert len(urls) == 2  # self-link excluded, duplicate collapsed
    assert all(u.startswith("https://www.benzinga.com/trading-ideas/") for u in urls)
    assert all(i.show == ShowKey.HALFTIME_REPORT for i in items)


def test_sitemap_url_filter() -> None:
    urls = benzinga.parse_sitemap_urls(fixture_text("benzinga_sitemap_month.xml"))
    assert len(urls) == 8
    assert all("final-trade" in u for u in urls)


def test_article_url_month() -> None:
    assert benzinga.article_url_month(
        "https://www.benzinga.com/trading-ideas/long-ideas/26/10/62555175/slug"
    ) == (2026, 10)
    assert benzinga.article_url_month("https://www.benzinga.com/topic/x") is None


def test_derive_segment_date_skips_weekend() -> None:
    # Monday-morning publish → previous trading day is Friday
    published = datetime(2026, 10, 26, 7, 30, tzinfo=UTC)
    d, basis = benzinga.derive_segment_date(published, ShowKey.HALFTIME_REPORT)
    assert d == date(2026, 10, 23)  # Friday
    assert basis == "published_minus_one_trading_day"
    d2, basis2 = benzinga.derive_segment_date(published, ShowKey.FAST_MONEY)
    assert d2 == date(2026, 10, 26)
    assert basis2 == "published_same_day"
