"""Shared test helpers: fixture loading and fake HTTP transport."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from final_trades.sources.contracts import FetchFailure, FetchResult
from final_trades.sources.http import Transport, TransportResponse

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str) -> dict:
    return json.loads(fixture_text(name))


def article_html(fixture_name: str) -> tuple[str, str]:
    """Wrap a recorded NewsArticle fixture in minimal HTML; returns (html, url)."""
    data = fixture_json(fixture_name)
    html = (
        '<html><head><script type="application/ld+json">'
        + json.dumps(data["news_article_ldjson"])
        + "</script></head><body></body></html>"
    )
    return html, data["url"]


def fetch_result(body: str, url: str = "https://example.test/x") -> FetchResult:
    import hashlib

    return FetchResult(
        url=url,
        status_code=200,
        body=body,
        content_sha256=hashlib.sha256(body.encode()).hexdigest(),
        retrieved_at=datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC),
    )


class FakeTransport:
    """Transport serving canned responses; records requested URLs.

    routes maps exact URL (or URL prefix with '*') to (status, body).
    Unrouted URLs return 404.
    """

    def __init__(self, routes: dict[str, tuple[int, str]]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    def get(self, url: str, timeout: float) -> TransportResponse:
        self.requested.append(url)
        for pattern, (status, body) in self.routes.items():
            if pattern.endswith("*") and url.startswith(pattern[:-1]):
                return TransportResponse(status, body.encode("utf-8"), url)
            if pattern == url:
                return TransportResponse(status, body.encode("utf-8"), url)
        return TransportResponse(404, b"not found", url)


class RaisingTransport(Transport):
    """Transport that always raises — for network-failure paths."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def get(self, url: str, timeout: float) -> TransportResponse:
        raise self._exc


def assert_failure(outcome: object, category: str, stage: str | None = None) -> FetchFailure:
    assert isinstance(outcome, FetchFailure), f"expected FetchFailure, got {type(outcome)}"
    assert outcome.error_category == category, f"expected {category}, got {outcome.error_category}"
    if stage is not None:
        assert outcome.stage == stage
    return outcome
