"""API middleware: per-IP token-bucket rate limiting + security headers.

Deliberately simple and dependency-free: a single Cloud Run instance means
in-process state is authoritative. If the deployment scales out, swap in a
shared store — the middleware interface stays the same.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

RATE_LIMIT_ERROR = {"error": "rate_limited", "message": "Too many requests. Slow down."}


@dataclass
class _Bucket:
    tokens: float
    last: float


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, rps: float, burst: int, max_clients: int = 10_000) -> None:
        super().__init__(app)
        self.rps = rps
        self.burst = burst
        self.max_clients = max_clients
        self._buckets: dict[str, _Bucket] = {}

    def _client_key(self, request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/healthz":
            return await call_next(request)
        key = self._client_key(request)
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self.max_clients:
                self._buckets.clear()  # crude but bounded memory
            bucket = _Bucket(tokens=float(self.burst), last=now)
            self._buckets[key] = bucket
        bucket.tokens = min(self.burst, bucket.tokens + (now - bucket.last) * self.rps)
        bucket.last = now
        if bucket.tokens < 1:
            return JSONResponse(RATE_LIMIT_ERROR, status_code=429, headers={"Retry-After": "1"})
        bucket.tokens -= 1
        return await call_next(request)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    ),
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response
