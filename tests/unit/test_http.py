"""Unit tests for the polite HTTP fetcher: throttling, robots, failure mapping."""

from __future__ import annotations

from final_trades.config import Settings
from final_trades.domain import ErrorCategory, Stage
from final_trades.sources.contracts import FetchResult
from final_trades.sources.http import MAX_RESPONSE_BYTES, PoliteFetcher
from helpers.helpers import FakeTransport, RaisingTransport, assert_failure

ROBOTS_ALLOW = "User-agent: *\nDisallow: /admin/\n"
ROBOTS_DENY = "User-agent: *\nDisallow: /\n"


def make_fetcher(
    routes: dict[str, tuple[int, str]],
    robots_enabled: bool = True,
) -> tuple[PoliteFetcher, FakeTransport, list[float]]:
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        HTTP_MIN_REQUEST_INTERVAL_SECONDS=2.0,
        HTTP_TIMEOUT_SECONDS=5,
    )
    transport = FakeTransport(
        {
            "https://feed.example/robots.txt": (200, ROBOTS_ALLOW),
            "https://blocked.example/robots.txt": (200, ROBOTS_DENY),
            "https://norobots.example/robots.txt": (404, ""),
            **routes,
        }
    )
    slept: list[float] = []
    ticks = iter(range(0, 10_000))
    fetcher = PoliteFetcher(
        settings=settings,
        transport=transport,
        impersonated_transport=transport,
        sleep=slept.append,
        clock=lambda: float(next(ticks)),
        robots_enabled=robots_enabled,
    )
    return fetcher, transport, slept


def test_success_captures_hash_and_provenance() -> None:
    fetcher, _, _ = make_fetcher({"https://feed.example/a.xml": (200, "<rss/>")})
    out = fetcher.get("https://feed.example/a.xml")
    assert isinstance(out, FetchResult)
    assert out.status_code == 200
    assert out.body == "<rss/>"
    assert len(out.content_sha256) == 64
    assert out.retrieved_at.tzinfo is not None


def test_throttles_same_host_only() -> None:
    fetcher, transport, slept = make_fetcher(
        {
            "https://feed.example/a": (200, "x"),
            "https://feed.example/b": (200, "x"),
            "https://other.example/robots.txt": (200, ROBOTS_ALLOW),
            "https://other.example/c": (200, "x"),
        }
    )
    fetcher.get("https://feed.example/a")
    fetcher.get("https://feed.example/b")  # same host → sleep
    fetcher.get("https://other.example/c")  # different host → no additional sleep
    assert len(slept) == 1
    # clock ticks 1s per call: interval 2.0 - elapsed 1.0 = sleep 1.0
    assert slept[0] == 1.0
    # robots fetched once per host, then cached
    assert transport.requested.count("https://feed.example/robots.txt") == 1


def test_zero_retries_on_failure() -> None:
    fetcher, transport, _ = make_fetcher({"https://feed.example/x": (500, "boom")})
    out = fetcher.get("https://feed.example/x")
    assert_failure(out, ErrorCategory.HTTP_ERROR, Stage.FETCH)
    assert transport.requested.count("https://feed.example/x") == 1


def test_status_mapping() -> None:
    fetcher, _, _ = make_fetcher(
        {
            "https://feed.example/403": (403, ""),
            "https://feed.example/429": (429, ""),
            "https://feed.example/404": (404, ""),
        }
    )
    assert_failure(fetcher.get("https://feed.example/403"), ErrorCategory.BLOCKED)
    assert_failure(fetcher.get("https://feed.example/429"), ErrorCategory.RATE_LIMITED)
    assert_failure(fetcher.get("https://feed.example/404"), ErrorCategory.NOT_FOUND)


def test_transport_exception_is_network_failure() -> None:
    settings = Settings(DATABASE_URL="sqlite:///:memory:", HTTP_MIN_REQUEST_INTERVAL_SECONDS=2.0)
    fetcher = PoliteFetcher(
        settings=settings,
        transport=RaisingTransport(TimeoutError("slow")),
        impersonated_transport=RaisingTransport(TimeoutError("slow")),
        sleep=lambda _: None,
        robots_enabled=False,
    )
    out = fetcher.get("https://anywhere.example/x")
    failure = assert_failure(out, ErrorCategory.NETWORK)
    assert "Timeout" in failure.summary
    assert "secret" not in str(failure.detail).lower()


def test_robots_denied_is_blocked() -> None:
    fetcher, transport, _ = make_fetcher({"https://blocked.example/page": (200, "x")})
    out = fetcher.get("https://blocked.example/page")
    assert_failure(out, ErrorCategory.BLOCKED)
    assert "https://blocked.example/page" not in transport.requested


def test_robots_unavailable_allows_with_warning() -> None:
    fetcher, _, _ = make_fetcher({"https://norobots.example/page": (200, "ok")})
    out = fetcher.get("https://norobots.example/page")
    assert isinstance(out, FetchResult)


def test_oversized_response_rejected() -> None:
    big = "x" * (MAX_RESPONSE_BYTES + 10)
    fetcher, _, _ = make_fetcher({"https://feed.example/big": (200, big)}, robots_enabled=False)
    out = fetcher.get("https://feed.example/big")
    assert_failure(out, ErrorCategory.VALIDATION)


def test_invalid_url_rejected() -> None:
    fetcher, _, _ = make_fetcher({})
    out = fetcher.get("ftp://feed.example/x")
    assert_failure(out, ErrorCategory.VALIDATION)


def test_error_summaries_never_include_body() -> None:
    secret_body = "AKIA_SECRET_VALUE=should-not-leak"
    fetcher, _, _ = make_fetcher({"https://feed.example/e": (500, secret_body)})
    out = fetcher.get("https://feed.example/e")
    failure = assert_failure(out, ErrorCategory.HTTP_ERROR)
    assert "should-not-leak" not in failure.summary
    assert "should-not-leak" not in json.dumps(failure.detail)


import json  # noqa: E402  (used in last test)
