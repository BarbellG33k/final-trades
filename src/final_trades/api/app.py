"""FastAPI application factory — the public read-only surface.

Security posture (docs/security.md):
- GET-only routes; no mutation or collection-trigger endpoints exist.
- Generic error envelopes; unhandled exceptions never leak details.
- Rate limiting, security headers, restrictive CORS, bounded pagination.
- Static SPA served with immutable caching; API JSON short-lived caching.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from final_trades.api.deps import get_cache
from final_trades.api.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from final_trades.api.routes import router
from final_trades.config import Settings, get_settings
from final_trades.db.session import get_logger, setup_logging

logger = get_logger(__name__)

ERROR_INTERNAL = {"error": "internal_error", "message": "An unexpected error occurred."}


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    setup_logging(cfg, service="final-trades-api")

    app = FastAPI(
        title="Final Trade Intelligence Platform API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(RateLimitMiddleware, rps=cfg.rate_limit_rps, burst=cfg.rate_limit_burst)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=[],
        allow_credentials=False,
        max_age=600,
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            404: "not_found",
            400: "bad_request",
            422: "validation_error",
            405: "method_not_allowed",
        }.get(exc.status_code, "http_error")
        # FastAPI's 422 handler carries validation details; surface a bounded,
        # safe version (field names only, never values).
        message = str(exc.detail) if exc.status_code != 422 else "Invalid query parameters."
        headers = {"Cache-Control": "no-store"}
        return JSONResponse(
            {"error": code, "message": message[:300]}, status_code=exc.status_code, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Never echo submitted values back; field locations only are safe.
        return JSONResponse(
            {"error": "validation_error", "message": "Invalid query parameters."},
            status_code=422,
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled api error",
            extra={"fields": {"path": request.url.path, "error_type": type(exc).__name__}},
        )
        return JSONResponse(ERROR_INTERNAL, status_code=500, headers={"Cache-Control": "no-store"})

    @app.middleware("http")
    async def cache_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/v1/") and "Cache-Control" not in response.headers:
            ttl = (
                cfg.overview_cache_ttl_seconds
                if path.rstrip("/")
                in (
                    "/api/v1/overview",
                    "/api/v1/coverage",
                )
                else 30
            )
            response.headers["Cache-Control"] = f"public, max-age={ttl}"
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)

    # Serve the built SPA if present (web/dist). Assets are content-hashed →
    # immutable caching; unknown non-API paths fall back to index.html.
    dist = (
        Path(cfg.web_dist_dir)
        if cfg.web_dist_dir
        else Path(__file__).resolve().parents[3] / "web" / "dist"
    )
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets, html=False), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
        async def spa(full_path: str) -> FileResponse | JSONResponse:  # pragma: no cover - trivial
            if full_path.startswith("api/"):
                return JSONResponse({"error": "not_found", "message": "Not Found"}, status_code=404)
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
            index = dist / "index.html"
            response = FileResponse(index)
            response.headers["Cache-Control"] = "no-cache"
            return response
    else:

        @app.get("/", include_in_schema=False)
        async def root() -> JSONResponse:
            return JSONResponse(
                {
                    "service": "final-trades-api",
                    "dashboard": "web/dist not built; run `cd web && npm run build`",
                    "docs": "/api/docs",
                }
            )

    return app


def invalidate_caches() -> None:
    """Test/utility hook: clear in-process summary caches."""
    get_cache().clear()
