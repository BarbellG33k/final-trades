# ARCHITECTURE.md — System Design

## 1. Overview

Modular monolith in Python + a static React SPA. Two runtime entrypoints
share one codebase and one database:

- **Collector** (`final-trades collect|backfill|performance`) — scheduled,
  write-identity, never exposed publicly.
- **API server** (`final-trades serve`) — FastAPI, read-only, serves
  `/api/v1/*` and the built SPA from `web/dist/`.

```
┌────────────────────────────── one codebase ──────────────────────────────┐
│ sources/ ──▶ pipeline/ ──▶ db/ ◀── api/ ◀── web/ (static build served)   │
│                 ▲            ▲                                           │
│           performance/ ──────┘ (writes only performance_observations)    │
└───────────────────────────────────────────────────────────────────────────┘
```

## 2. Frontend / backend boundary

- `web/` (React 19 + Vite + TS + Tailwind + TanStack Query/Table) calls only
  `/api/v1/*` with JSON. In dev, Vite proxies `/api` to `:8000`. In prod,
  FastAPI mounts `web/dist` and serves it with long-lived cache headers
  (hashed asset filenames).
- All filtering/sorting/pagination happens server-side; the SPA never
  downloads the full dataset.

## 3. Background execution architecture

- Scheduled via GitHub Actions cron (primary, $0 for public repos) or Cloud
  Run Jobs + Cloud Scheduler (configs in `deploy/`). Both run the same Docker
  image entrypoint.
- One scheduled run = one `ingestion_runs` row. Inside a run: bounded single
  attempt per (source, date) unit; commit per date; no retries.
- Catch-up is cross-run: `date_processing_status` rows with status in
  {PENDING, FAILED, UNRESOLVED} form the backlog; oldest-first; quota
  `BACKLOG_MAX_DATES_PER_RUN` with `CURRENT_DAY_CAPACITY_SHARE` reserved for
  current-day work.
- Exit codes: 0 SUCCESS, 1 PARTIAL_SUCCESS, 2 FAILED (cron visibility).

## 4. Database & storage

- SQLAlchemy 2.0 ORM, Alembic migrations. Dev/CI: SQLite (WAL). Prod:
  Postgres (Neon free tier). No prod DB on ephemeral filesystems.
- Roles: collector uses read-write role; API uses read-only role in prod
  (same schema). SQLite dev uses one file for both.
- Schema in `db/models.py`; documented in `docs/data-model.md`. Key
  invariants: recommendations are only created via pipeline upserts keyed on
  (segment_id, analyst_id, instrument_id, direction); evidence rows are
  append-only; `performance_observations` recomputable without touching
  recommendation evidence.

## 5. Source adapter contracts

`sources/contracts.py` defines the adapter interface:

```python
class SourceAdapter(Protocol):
    source_key: str                      # e.g. "benzinga_halftime"
    def discover(self, window) -> Iterator[DiscoveredItem]   # listings/RSS
    def fetch_detail(self, item) -> ParsedSegment | FetchFailure
```

DTOs: `DiscoveredItem` (url, show, published_at, title), `ParsedSegment`
(show, segment_date, recommendations: list[RawRecommendation], evidence:
list[Evidence]), `RawRecommendation` (analyst_name_raw, ticker_raw, direction,
position_type, thesis, confidence), `Evidence` (url, retrieved_at, sha256,
excerpt, kind), `FetchFailure` (error_category, stage, detail).
Adapters never touch the DB; the pipeline maps DTOs → models.
All HTTP goes through `sources/http.py`: per-host rate limiting (≥2s),
polite UA, robots.txt check, timeouts, response size caps, zero retries.

Implemented adapters: `benzinga.py` (topic listing pagination + article
parse for both shows), `cnbc_rss.py` (Fast Money feed), `cnbc_video.py`
(video page evidence).

## 6. Data processing lifecycle

discover → fetch detail → validate evidence → normalize (analysts,
instruments, direction) → dedupe/merge (multi-source) → upsert segment +
recommendations + evidence → update `date_processing_status` → update
coverage aggregates → finalize run. Normalization failures produce
`unresolved` records with conflicts stored, never silent drops.

## 7. Public read-only API

- Routes: `/api/v1/overview`, `/runs`, `/runs/{id}`, `/recommendations`,
  `/recommendations/{id}`, `/historical/dates`, `/analysts`,
  `/analysts/{id}`, `/performance/summary`, `/performance/recommendations`,
  `/coverage`, `/healthz`. GET only (plus HEAD/OPTIONS handled by framework).
- Envelopes: lists `{data, total, page, page_size}`; single resources direct;
  errors `{error, message}` (generic codes only).
- Middleware: rate limit (token bucket per IP), security headers, CORS
  allowlist, request size cap, statement timeout on queries, 60s in-process
  cache for `/overview` and `/coverage`.
- Schemas: Pydantic v2 in `api/schemas.py`; strict param validation;
  pagination default 20, max 100; date ranges capped to the 12-month window
  + margin.

## 8. Dashboard query patterns

Indexed for: recommendations by (segment_date desc), by ticker, by analyst,
by show+date range, by verification status; runs by started_at desc;
date_processing_status by (show, status, date); coverage_daily by date.
Grid endpoints return only columns needed for rows; detail endpoints fetch
evidence lazily on expansion.

## 9. Caching, rate limiting, security

See `docs/security.md`. Summary: SPA assets immutable-cached (hashed),
API JSON `Cache-Control: public, max-age=30` (60 for overview/coverage),
rate limit 1 rps/IP burst 30 (in-memory; single-instance deployments),
HSTS/CSP/X-Content-Type-Options headers, no credentials anywhere in the
public bundle, generic errors.

## 10. Scheduling & recovery

Cron: collector daily 22:30 UTC weekdays + a weekend catch-up run (backlog
only). Failures alert via cron-provider UI/logs; the system self-heals by
design on the next run. No dead-letter queue needed: the backlog table IS
the durable queue.

## 11. Deployment alternatives

Primary: GH Actions cron (collector) + Cloud Run free tier (API+SPA) + Neon
free Postgres. Alternative: single Cloud Run Job + Scheduler. Fallback:
docker-compose on any $4 VPS. All three use the same image; only wiring
differs (`deploy/`).

## 12. Migration & portability

Alembic versioned migrations run at container start (API) or explicitly
(collector). Postgres↔SQLite compatible types only (JSON stored as JSON type
with Text fallback via SQLAlchemy `JSON`). No provider-specific SQL outside
dialect-guarded helpers. Export = `pg_dump`/SQLite file copy; documented in
`docs/operations.md`.
