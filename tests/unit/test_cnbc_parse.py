"""Unit tests for the CNBC source adapter parsing functions."""

from __future__ import annotations

import json
from datetime import date

from final_trades.domain import Confidence, Direction, ErrorCategory, ShowKey, Stage
from final_trades.sources import cnbc
from final_trades.sources.contracts import ParsedSegment
from helpers.helpers import assert_failure, fetch_result, fixture_json, fixture_text


def test_parse_rss_keeps_only_final_trade_items() -> None:
    items = cnbc.parse_rss(fixture_text("cnbc_fastmoney_rss.xml"))
    assert not isinstance(items, cnbc.FetchFailure)
    assert len(items) >= 5
    assert all(i.show == ShowKey.FAST_MONEY for i in items)
    assert all(i.title.startswith("Final Trade:") for i in items)
    titles = [i.title for i in items]
    assert "Final Trade: NVDA, JPM, SLB, XMAG" in titles
    nvda = next(i for i in items if i.title == "Final Trade: NVDA, JPM, SLB, XMAG")
    assert nvda.url == "https://www.cnbc.com/video/2026/10/23/final-trade-nvda-jpm-slb-xmag.html"
    assert nvda.published_at is not None
    assert nvda.published_at.date() == date(2026, 10, 23)


def test_parse_search_results_both_shows() -> None:
    items = cnbc.parse_search_results(fixture_text("cnbc_search_results.json"))
    assert not isinstance(items, cnbc.FetchFailure)
    assert items, "fixture should yield final-trade items"
    shows = {i.show for i in items}
    assert ShowKey.FAST_MONEY in shows
    # Every returned item is a Final Trade(s) video with a cnbc video URL
    assert all("/video/" in i.url for i in items)
    fm = next(i for i in items if i.show == ShowKey.FAST_MONEY)
    assert fm.title.startswith("Final Trade:")


def test_parse_search_results_invalid_json() -> None:
    failure = cnbc.parse_search_results("{not json")
    assert_failure(failure, ErrorCategory.PARSE, Stage.PARSE)


def test_parse_fm_tickers() -> None:
    assert cnbc.parse_fm_tickers("Final Trade: NVDA, JPM, SLB, XMAG") == [
        ("NVDA", None),
        ("JPM", None),
        ("SLB", None),
        ("XMAG", None),
    ]
    assert cnbc.parse_fm_tickers("Final Trade: Telecom, GM, TLT, CLF") == [
        ("TELECOM", "other"),
        ("GM", None),
        ("TLT", None),
        ("CLF", None),
    ]
    assert cnbc.parse_fm_tickers("Final Trade: C, LLY, WMT and SMH") == [
        ("C", None),
        ("LLY", None),
        ("WMT", None),
        ("SMH", None),
    ]
    assert cnbc.parse_fm_tickers("Final Trade: US 10-Year, GM") == [
        ("US10Y", "fixed_income"),
        ("GM", None),
    ]
    assert cnbc.parse_fm_tickers("Not a final trade title") == []


def test_parse_video_page_fast_money() -> None:
    data = fixture_json("cnbc_video_fm.json")
    html = '<script type="application/ld+json">' + json.dumps(data["video_ldjson"]) + "</script>"
    result = cnbc.parse_video_page(fetch_result(html, data["url"]), ShowKey.FAST_MONEY)
    assert isinstance(result, ParsedSegment)
    # uploadDate 2026-10-23T22:04Z → 18:04 ET → same-day segment
    assert result.segment_date == date(2026, 10, 23)
    assert result.show == ShowKey.FAST_MONEY
    tickers = [r.ticker_raw for r in result.recommendations]
    assert tickers == ["NVDA", "JPM", "SLB", "XMAG"]
    for r in result.recommendations:
        assert r.analyst_name_raw is None  # CNBC publishes no FM attribution
        assert r.direction == Direction.LONG
        assert r.confidence == Confidence.MEDIUM
        assert r.evidence is not None
        assert r.evidence.url == data["url"]


def test_parse_video_page_halftime_has_no_recommendations() -> None:
    video = {
        "@type": "VideoObject",
        "name": "Final Trades: Zscaler, ServiceNow and Spotify",
        "description": "The Investment Committee's final trades.",
        "uploadDate": "2026-10-22T17:10:00.000Z",
    }
    html = '<script type="application/ld+json">' + json.dumps(video) + "</script>"
    result = cnbc.parse_video_page(
        fetch_result(html, "https://www.cnbc.com/video/2026-10-22/x.html"),
        ShowKey.HALFTIME_REPORT,
    )
    assert isinstance(result, ParsedSegment)
    assert result.segment_date == date(2026, 10, 22)  # 17:10Z = 13:10 ET
    assert result.recommendations == ()  # attribution comes from Benzinga


def test_parse_video_page_fm_company_name_title_yields_empty_recs() -> None:
    # Real-world variant: 'Final Trades: 2-year Treasury, S&P ETF, Meta, Alphabet'
    video = {
        "@type": "VideoObject",
        "name": "Final Trades: 2-year Treasury, S&P ETF, Meta, Alphabet",
        "description": "The final trades of the day.",
        "uploadDate": "2026-09-24T22:10:00.000Z",
    }
    html = '<script type="application/ld+json">' + json.dumps(video) + "</script>"
    result = cnbc.parse_video_page(
        fetch_result(html, "https://www.cnbc.com/video/2026-09-24/x.html"),
        ShowKey.FAST_MONEY,
    )
    assert isinstance(result, ParsedSegment)
    assert result.recommendations == ()  # never fabricate tickers from company names
    assert result.segment_date == date(2026, 9, 24)


def test_parse_video_page_missing_metadata() -> None:
    failure = cnbc.parse_video_page(
        fetch_result("<html></html>", "https://www.cnbc.com/video/x.html"),
        ShowKey.FAST_MONEY,
    )
    assert_failure(failure, ErrorCategory.PARSE, Stage.PARSE)


def test_video_url_date_fallback() -> None:
    assert cnbc.video_url_date("https://www.cnbc.com/video/2026-01-05/slug.html") is not None
    assert cnbc.video_url_date("https://www.cnbc.com/2026-01-05/slug.html") is None
