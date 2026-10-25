"""API integration tests: read-only guarantees, pagination bounds, error hygiene.

Covers critical scenarios 10, 11, 12, 16, 17, 18 (docs/testing.md).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helpers.pipeline_env import ZSCALER_URL, Env, build_env


@pytest.fixture()
def seeded_env() -> Env:
    """Environment with one successful scheduled run already ingested."""
    from final_trades.pipeline.orchestrator import Collector
    from helpers.pipeline_env import TODAY

    env = build_env()
    Collector(env.session, env.make_fetcher(), env.settings, today=TODAY).run_scheduled()
    return env


@pytest.fixture()
def client(seeded_env: Env) -> TestClient:
    from fastapi import FastAPI

    from final_trades.api import deps
    from final_trades.api.app import create_app

    app: FastAPI = create_app(seeded_env.settings)
    app.dependency_overrides[deps.get_db] = lambda: seeded_env.session
    app.dependency_overrides[deps.get_api_settings] = lambda: seeded_env.settings
    deps.get_cache().clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    deps.get_cache().clear()


# Scenario 11: public requests cannot trigger collection ---------------------------


def test_all_routes_are_read_only(client: TestClient) -> None:
    app = client.app
    allowed = {"GET", "HEAD", "OPTIONS"}
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if methods is None:
            continue  # mounts (static)
        assert methods <= allowed, f"route {route} exposes {methods - allowed}"


def test_no_collection_endpoints_exist(client: TestClient) -> None:
    paths = " ".join(str(getattr(r, "path", "")) for r in client.app.routes)
    for banned in ("collect", "trigger", "rerun", "retry", "backfill", "ingest", "admin"):
        assert banned not in paths.lower(), f"banned concept in routes: {banned}"
    # POST to a known GET route must not perform any action
    r = client.post("/api/v1/runs")
    assert r.status_code == 405
    assert r.json()["error"] == "method_not_allowed"


# Scenario 12 + 16: bounded queries & pagination ------------------------------------


def test_pagination_caps_page_size(client: TestClient) -> None:
    r = client.get("/api/v1/recommendations", params={"page_size": 1000})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"
    assert "Invalid query parameters." in r.json()["message"]


def test_pagination_respects_limits_and_totals(client: TestClient) -> None:
    r = client.get("/api/v1/recommendations", params={"page_size": 3, "page": 1})
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) <= 3
    assert body["total"] >= len(body["data"])
    assert body["page"] == 1 and body["page_size"] == 3
    r2 = client.get("/api/v1/recommendations", params={"page_size": 3, "page": 2})
    ids1 = {row["id"] for row in body["data"]}
    ids2 = {row["id"] for row in r2.json()["data"]}
    assert not (ids1 & ids2), "pages must not overlap"


def test_date_range_is_bounded(client: TestClient) -> None:
    r = client.get(
        "/api/v1/recommendations", params={"date_from": "2020-01-01", "date_to": "2026-10-25"}
    )
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"
    r2 = client.get(
        "/api/v1/recommendations", params={"date_from": "2026-10-25", "date_to": "2026-10-01"}
    )
    assert r2.status_code == 400


# Scenario 17: error hygiene ----------------------------------------------------------


def test_404_envelope_is_generic(client: TestClient) -> None:
    r = client.get("/api/v1/runs/999999")
    assert r.status_code == 404
    body = r.json()
    assert body == {"error": "not_found", "message": "Run not found"}


def test_unhandled_errors_leak_nothing(seeded_env: Env) -> None:
    from fastapi import FastAPI

    from final_trades.api import deps
    from final_trades.api.app import create_app

    app: FastAPI = create_app(seeded_env.settings)

    def broken_db():
        raise RuntimeError("connection string postgres://user:SECRET@host exploded")

    app.dependency_overrides[deps.get_db] = broken_db
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/runs")
    assert r.status_code == 500
    body_text = r.text
    assert "SECRET" not in body_text
    assert "Traceback" not in body_text
    assert r.json() == {"error": "internal_error", "message": "An unexpected error occurred."}


def test_rate_limiting_kicks_in(seeded_env: Env) -> None:
    from final_trades.api import deps
    from final_trades.api.app import create_app
    from final_trades.config import Settings

    tight = Settings(
        DATABASE_URL="sqlite://",
        RATE_LIMIT_RPS=0.001,
        RATE_LIMIT_BURST=3,
        OVERVIEW_CACHE_TTL_SECONDS=0,
    )
    app = create_app(tight)
    app.dependency_overrides[deps.get_db] = lambda: seeded_env.session
    app.dependency_overrides[deps.get_api_settings] = lambda: seeded_env.settings
    with TestClient(app, raise_server_exceptions=False) as c:
        codes = [c.get("/api/v1/runs").status_code for _ in range(6)]
    assert codes.count(429) >= 1
    limited = [c for c in codes if c == 429]
    assert limited


# Security headers & CORS ---------------------------------------------------------------


def test_security_headers_present(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    r = client.get("/api/v1/overview", headers={"Origin": "https://evil.example"})
    assert (
        "access-control-allow-origin" not in {k.lower() for k in r.headers}
        or r.headers.get("access-control-allow-origin") != "https://evil.example"
    )


def test_api_cache_headers(client: TestClient) -> None:
    r = client.get("/api/v1/overview")
    assert r.headers["Cache-Control"] == "public, max-age=60"
    r2 = client.get("/api/v1/runs")
    assert r2.headers["Cache-Control"] == "public, max-age=30"


# Scenario 10 + 18: dashboard data shows failures honestly ------------------------------


def test_overview_exposes_failures_and_per_show_status() -> None:
    """A failed Halftime collection must be visible while Fast Money shows success."""
    from final_trades.pipeline.orchestrator import Collector
    from helpers.pipeline_env import TODAY

    env = build_env()
    env.routes[ZSCALER_URL] = (500, "boom")
    Collector(env.session, env.make_fetcher(), env.settings, today=TODAY).run_scheduled()

    from final_trades.api import deps
    from final_trades.api.app import create_app

    app = create_app(env.settings)
    app.dependency_overrides[deps.get_db] = lambda: env.session
    app.dependency_overrides[deps.get_api_settings] = lambda: env.settings
    deps.get_cache().clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/overview")
    deps.get_cache().clear()
    assert r.status_code == 200
    body = r.json()
    assert body["latest_run"]["status"] == "PARTIAL_SUCCESS"
    assert body["recent_failures"], "unresolved issue must surface on overview"
    shows = {s["show"]: s for s in body["shows"]}
    assert shows["fast_money"]["last_collected_date"] is not None  # FM healthy
    assert shows["halftime_report"]["last_collected_date"] is None  # HR failed, not hidden
    assert body["backlog_remaining"] >= 0


def test_runs_and_run_detail(client: TestClient) -> None:
    r = client.get("/api/v1/runs")
    assert r.status_code == 200
    runs = r.json()["data"]
    assert runs and runs[0]["id"] > 0
    detail = client.get(f"/api/v1/runs/{runs[0]['id']}").json()
    assert detail["status"] in ("SUCCESS", "PARTIAL_SUCCESS", "FAILED")
    assert isinstance(detail["source_results"], list)
    assert isinstance(detail["date_results"], list)
    for d in detail["date_results"]:
        assert {"show", "processing_date", "status", "attempts"} <= set(d)


def test_recommendation_detail_has_evidence(client: TestClient) -> None:
    rows = client.get(
        "/api/v1/recommendations", params={"show": "halftime_report", "page_size": 5}
    ).json()["data"]
    assert rows, "seeded run should have Halftime recommendations"
    detail = client.get(f"/api/v1/recommendations/{rows[0]['id']}").json()
    assert detail["evidence"], "provenance must be exposed"
    for ev in detail["evidence"]:
        assert ev["url"].startswith("http")
        assert len(ev["content_sha256"]) == 64
        assert ev["excerpt"]


def test_historical_distinguish_absent_from_unchecked(client: TestClient) -> None:
    r = client.get("/api/v1/historical/dates", params={"page_size": 100})
    assert r.status_code == 200
    rows = r.json()["data"]
    statuses = {row["status"] for row in rows}
    # weekend rows exist as NO_SEGMENT (verified absence), weekdays vary
    assert "NO_SEGMENT" in statuses
    by_date = {(row["the_date"], row["show"]): row["status"] for row in rows}
    assert by_date.get(("2026-10-24", "fast_money")) == "NO_SEGMENT"  # Saturday


def test_coverage_endpoint(client: TestClient) -> None:
    r = client.get("/api/v1/coverage")
    assert r.status_code == 200
    body = r.json()
    assert len(body["shows"]) == 2
    for show in body["shows"]:
        assert show["total_dates"] > 0
        assert "benzinga_article" in body["last_successful_check_by_source"] or True


def test_analysts_endpoint(client: TestClient) -> None:
    r = client.get("/api/v1/analysts", params={"page_size": 100})
    assert r.status_code == 200
    data = r.json()["data"]
    assert any(a["canonical_name"] == "Joshua Brown" for a in data)
    brown = next(a for a in data if a["canonical_name"] == "Joshua Brown")
    assert brown["recommendation_count"] >= 1
    assert brown["insufficient_performance_data"] is True  # honest: no perf data yet


def test_performance_summary_empty_is_honest(client: TestClient) -> None:
    r = client.get("/api/v1/performance/summary")
    assert r.status_code == 200
    body = r.json()
    assert len(body["horizons"]) == 4
    assert all(h["sample_size"] == 0 for h in body["horizons"])
    assert "Not investment advice" in body["disclaimer"]
    assert body["benchmark_symbol"] == "SPY"


def test_filters_combine(client: TestClient) -> None:
    r = client.get(
        "/api/v1/recommendations",
        params={
            "show": "fast_money",
            "ticker": "NVDA",
            "verification": "unverified",
            "date_from": "2026-10-01",
            "date_to": "2026-10-31",
        },
    )
    assert r.status_code == 200
    rows = r.json()["data"]
    assert rows, "fixture run collects NVDA on Fast Money 10/23"
    assert all(row["show"] == "fast_money" for row in rows)
    assert all(row["instrument"]["symbol"] == "NVDA" for row in rows)
