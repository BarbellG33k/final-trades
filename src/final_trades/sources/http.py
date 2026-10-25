"""Polite, bounded HTTP fetching for all source adapters.

Policy (AGENTS.md / docs/security.md):
- per-host minimum interval between requests (default 2s)
- robots.txt respected (cached per host; unavailable robots → allow + warn)
- ZERO retries — one bounded attempt; failures become FetchFailure values
- response size cap; timeouts on every call
- no secrets or full bodies in error summaries
- browser-TLS transport (curl_cffi) only for hosts behind bot walls
  (benzinga.com — Cloudflare, verified 2026-10-25); httpx elsewhere.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from final_trades.config import Settings, get_settings
from final_trades.db.session import get_logger
from final_trades.domain import ErrorCategory, Stage
from final_trades.sources.contracts import FetchFailure, FetchOutcome, FetchResult

logger = get_logger(__name__)

MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 4 MiB hard cap on any single document
# Hosts requiring browser TLS impersonation (bot-wall evidence in
# docs/source-validation.md). Never expand without a recorded probe.
IMPERSONATED_HOSTS = frozenset({"www.benzinga.com", "benzinga.com"})


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes
    final_url: str


class Transport(Protocol):
    def get(self, url: str, timeout: float) -> TransportResponse: ...


class HttpxTransport:
    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent

    def get(self, url: str, timeout: float) -> TransportResponse:
        import httpx

        with httpx.Client(
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            resp = client.get(url)
            return TransportResponse(resp.status_code, resp.content, str(resp.url))


class CurlCffiTransport:
    """Browser TLS impersonation for bot-walled hosts."""

    def get(self, url: str, timeout: float) -> TransportResponse:
        from curl_cffi import requests as cffi_requests

        resp = cffi_requests.get(url, impersonate="chrome", timeout=timeout)
        return TransportResponse(resp.status_code, resp.content, str(resp.url))


class PoliteFetcher:
    """Rate-limited, robots-respecting fetcher. One attempt per call."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: Transport | None = None,
        impersonated_transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        robots_enabled: bool = True,
    ) -> None:
        cfg = settings or get_settings()
        self._min_interval = cfg.http_min_request_interval_seconds
        self._timeout = cfg.http_timeout_seconds
        self._transport = transport or HttpxTransport(cfg.http_user_agent)
        self._impersonated = impersonated_transport or CurlCffiTransport()
        self._sleep = sleep
        self._clock = clock
        self._robots_enabled = robots_enabled
        self._last_request_by_host: dict[str, float] = {}
        self._robots_cache: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    # -- public API ---------------------------------------------------------

    def get(self, url: str, stage: Stage = Stage.FETCH) -> FetchOutcome:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if not host or parsed.scheme not in ("http", "https"):
            return FetchFailure(
                error_category=ErrorCategory.VALIDATION,
                stage=stage,
                summary=f"Invalid URL scheme/host for {url[:120]}",
                url=url,
            )
        if self._robots_enabled and not self._robots_allows(url, host, stage):
            return FetchFailure(
                error_category=ErrorCategory.BLOCKED,
                stage=stage,
                summary=f"robots.txt disallows {parsed.path[:120]}",
                url=url,
            )
        self._throttle(host)
        transport = self._impersonated if host in IMPERSONATED_HOSTS else self._transport
        try:
            resp = transport.get(url, self._timeout)
        except TimeoutError as exc:
            return FetchFailure(
                ErrorCategory.NETWORK,
                stage,
                f"Timeout after {self._timeout}s",
                url,
                {"exc": type(exc).__name__},
            )
        except Exception as exc:
            return FetchFailure(
                ErrorCategory.NETWORK,
                stage,
                f"Transport error: {type(exc).__name__}",
                url,
                {"exc": str(exc)[:200]},
            )
        if len(resp.body) > MAX_RESPONSE_BYTES:
            return FetchFailure(
                ErrorCategory.VALIDATION,
                stage,
                f"Response too large ({len(resp.body)} bytes)",
                url,
            )
        if resp.status_code == 429:
            return FetchFailure(ErrorCategory.RATE_LIMITED, stage, "HTTP 429 from source", url)
        if resp.status_code in (401, 403):
            return FetchFailure(
                ErrorCategory.BLOCKED, stage, f"HTTP {resp.status_code} (bot wall?)", url
            )
        if resp.status_code == 404:
            return FetchFailure(ErrorCategory.NOT_FOUND, stage, "HTTP 404", url)
        if resp.status_code >= 400:
            return FetchFailure(ErrorCategory.HTTP_ERROR, stage, f"HTTP {resp.status_code}", url)
        text = resp.body.decode("utf-8", errors="replace")
        return FetchResult(
            url=resp.final_url or url,
            status_code=resp.status_code,
            body=text,
            content_sha256=hashlib.sha256(resp.body).hexdigest(),
            retrieved_at=datetime.now(UTC),
        )

    # -- internals ----------------------------------------------------------

    def _throttle(self, host: str) -> None:
        with self._lock:
            now = self._clock()
            last = self._last_request_by_host.get(host)
            if last is not None:
                elapsed = now - last
                if elapsed < self._min_interval:
                    self._sleep(self._min_interval - elapsed)
            self._last_request_by_host[host] = self._clock()

    def _robots_allows(self, url: str, host: str, stage: Stage) -> bool:
        with self._lock:
            cached = self._robots_cache.get(host)
        if cached is not None:
            return cached.can_fetch("*", url)
        robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
        parser: RobotFileParser
        try:
            transport = self._impersonated if host in IMPERSONATED_HOSTS else self._transport
            resp = transport.get(robots_url, self._timeout)
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.body.decode("utf-8", errors="replace").splitlines())
            else:
                logger.warning(
                    "robots.txt fetch returned %s for %s; allowing", resp.status_code, host
                )
                parser = _AllowAll()
        except Exception as exc:
            logger.warning(
                "robots.txt fetch failed for %s (%s); allowing", host, type(exc).__name__
            )
            parser = _AllowAll()
        with self._lock:
            self._robots_cache[host] = parser
        return parser.can_fetch("*", url)


class _AllowAll(RobotFileParser):
    def can_fetch(self, useragent: str, url: str) -> bool:
        return True


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
