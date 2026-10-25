# security.md — Public Access & Abuse Prevention

Threat model: a **public, unauthenticated, read-only** data site. Every
endpoint is discoverable; every client is potentially hostile. Goals: no
mutation of system state from public traffic, no secret/PII leakage, bounded
cost per request, honest availability.

## Implemented controls (code references)

| Control | Where | Verified by |
|---|---|---|
| Read-only API: only GET routes registered | `api/routes.py`, `api/app.py` | `test_all_routes_are_read_only` (audits every route's methods) |
| No collection trigger/retry endpoints; banned-concept audit | routes | `test_no_collection_endpoints_exist` (POST/DELETE → 405) |
| Rate limit: token bucket per IP (1 rps, burst 30; env-tunable) | `api/middleware.py` | `test_rate_limiting_kicks_in` |
| Pagination caps: default 20, max 100; page bound | `api/deps.py` | `test_pagination_caps_page_size` |
| Date-range cap (400 days) + ordering validation | `api/deps.py` | `test_date_range_is_bounded` |
| Query param validation (enums, lengths) → generic envelope | FastAPI/Pydantic + `app.py` handler | `test_pagination_caps_page_size` |
| Generic error envelope; no stack traces/env/DSNs | `app.py` handlers | `test_unhandled_errors_leak_nothing`, `test_404_envelope_is_generic` |
| Security headers (nosniff, DENY frame, CSP, referrer, permissions, HSTS) | `api/middleware.py` | `test_security_headers_present` |
| Restrictive CORS (same-origin; SPA served by API) | `app.py` | `test_cors_rejects_unknown_origin` |
| Cache headers: API 30s / summaries 60s / hashed assets immutable / index no-cache | `app.py` | `test_api_cache_headers` |
| DB statement timeout (Postgres `statement_timeout`) | `db/session.py` | config test |
| Collector/API identity split: API gets read-only role in prod (Neon) | `docs/deployment.md` | operator checklist |
| Secrets via env only; startup validation; presence-only logging | `config.py`, `db/session.py` | `test_sanitize_url_strips_credentials`, `test_json_formatter_exception_sanitized` |
| Outbound politeness: ≥2s/host, robots.txt, zero retries, 4 MiB cap, UA with contact | `sources/http.py` | `tests/unit/test_http.py` |
| Error records sanitized at write time (category+summary, no bodies) | `sources/http.py`, orchestrator | `test_error_summaries_never_include_body` |
| Dependency vuln scans (pip-audit, npm audit) + secret scan (TruffleHog) in CI | `.github/workflows/ci.yml` | CI |
| License audit (no copyleft contamination) | CI | CI |
| Non-root container, pinned base images | `deploy/Dockerfile` | CI docker smoke |
| Bounded ingestion cost: per-run quotas; public traffic can never trigger paid work | orchestrator config | integration tests |

## Deployment-level controls (operator checklist)

- Cloud Run: `max-scale=2`, container concurrency 80, unauthenticated
  invocation allowed **only** for the API service; jobs are IAM-restricted
  (Scheduler SA only).
- Billing alerts at $1 on every cloud account; Neon usage alerts at 80
  CU-hours.
- Postgres: collector role = read/write; API role = `SELECT` only
  (`GRANT SELECT ON ALL TABLES`); connection strings via Secret Manager /
  GH Actions secrets — never in the repo or client bundle.
- Backups: Neon PITR/branching + weekly `pg_dump` (see operations.md).
- GitHub: branch protection on `main`, required CI checks, Dependabot
  alerts enabled.

## What we deliberately do NOT do

- No CAPTCHA/auth friction (no abuse observed; requirements forbid
  unnecessary friction). Rate limits are the first line; provider-level
  controls (Cloud Run concurrency, Neon limits) are the second.
- No client-side secrets, no analytics beacons, no third-party scripts
  (CSP `default-src 'self'` enforces).
- No bulk export endpoints (bounded pages only) — protects both the DB and
  market-data provider terms.
- Obscurity is never the control: the collector's non-exposure is enforced
  by route audit tests, not by unguessable URLs.

## Known limitations

- In-process rate limiter is per-instance; horizontal scaling would need a
  shared store (documented in middleware docstring; single-instance deploy
  is the design point).
- `x-forwarded-for` is spoofable; acceptable for rate-limit bucketing
  (worst case: an attacker rotates buckets — global concurrency caps and
  query bounds still protect the DB).
- CSP allows `style-src 'unsafe-inline'` for Tailwind runtime-injected
  styles; tighten with nonces if the SPA grows custom inline styles.
