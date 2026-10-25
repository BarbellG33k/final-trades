# STATUS.md — Current State & Handoff

Last updated: 2026-10-25 (end of Phases 1–5 build session; MVP feature-complete,
deployment prepared but NOT provisioned — by explicit operator choice).

## Completed (validated)

- **WS-00 Foundation**: repo governance (README/AGENTS/CLAUDE/LICENSE
  Apache-2.0), full `docs/` tree (PLAN, PRD, ARCHITECTURE, DECISIONS,
  STATUS, CONTRIBUTING, data-model, source-validation, deployment,
  cost-model, operations, testing, security, 3 ADRs, agent guide,
  3 runbooks), Python 3.12 + uv, ruff/mypy-strict/pytest, Vite web scaffold.
- **WS-01 Sources**: Benzinga article/topic/sitemap adapters (Cloudflare
  handled via curl_cffi TLS impersonation; robots allowed), CNBC queryly
  search + Fast Money RSS + video page adapters. Recorded fixtures (68KB) —
  CI is network-free. Validation gate **PASSED** across 5 sampled months +
  current window, all four quarters: see `docs/source-validation.md`.
- **WS-02 Database**: 13 tables, Alembic migration `a7e1f22a9627`, seeded
  reference data, repositories with idempotent upserts. SQLite (dev) and
  Postgres (prod) compatible; psycopg extra wired.
- **WS-03 Extraction**: analyst/ticker normalization with curated alias and
  phrase maps, verification lattice (unverified<verified<corroborated;
  unresolved sticks), conflicts preserved, evidence append-only with
  sha256+excerpt ≤600 chars. Parser validated 8/8 on hard live samples.
- **WS-04 Orchestration**: scheduled + backfill runs, FM date-driven / HR
  article-driven processing, bounded oldest-first backlog with current-day
  capacity share, per-unit commits, cross-run recovery (verified live:
  FAILED→UNRESOLVED self-heal), URL-keyed issue recovery, NO_SEGMENT vs
  PENDING vs UNRESOLVED honesty, future-publish-date guard, exit codes.
- **WS-05 API**: 12 GET endpoints, pagination caps (100), 400-day range cap,
  token-bucket rate limiting, security headers, same-origin CORS, TTL
  caches, generic error envelopes. Read-only surface enforced by route-audit
  test (POST/DELETE → 405).
- **WS-06 Dashboard**: React 19 + Vite + Tailwind 4, all 7 tabs, URL-synced
  filters, expandable evidence drawer, per-show separation everywhere,
  honest empty/loading/stale/error states. 11 vitest tests. Build: 100KB gzip.
- **WS-07 Performance**: provider port (yfinance default keyless, Tiingo
  optional), entry conventions per show airtime (verified live: ZS entry
  237.76 == close quoted in source article), horizons 1/5/20/60, SPY
  benchmark, shorts separate, explicit MISSING_*/NOT_DUE/UNSUPPORTED
  statuses. **1,984 observations computed on real data** (n=574 at h=1 …
  381 at h=60 for longs).
- **WS-08 Deployment prep**: multi-stage Dockerfile (non-root, healthcheck),
  docker-compose prod simulation, GH Actions CI (lint/types/tests/coverage/
  audits/secret-scan/docker-smoke) + scheduled collector workflow (2 daily
  slots + nightly performance + operator-only backfill dispatch), Cloud Run
  service/job YAMLs (maxRetries=0), verified $0 cost model
  (`docs/cost-model.md`, prices checked 2026-10-25).
- **WS-09 Security**: scenarios 11/12/16/17 tests green; checklist in
  `docs/security.md` mapped to code + tests.
- **WS-10 (partial)**: 18-scenario map in `docs/testing.md` (17 covered by
  automated tests; #14 backup/restore is a documented manual runbook drill).

## Live data state (local dev DB, data/final_trades.sqlite3)

957 recommendations · 258 segments (89 FM / 169 HR) · 26 analysts ·
352 instruments · 8 runs · backlog 23 · open issues 3 · coverage spans
2025-11, 2026-02, 2026-05, 2026-07, 2026-09, 2026-09-04→10-23 continuous.

## Known issues / gaps (honest list)

1. **Full-window backfill not executed** — sampled months only (gate).
   Remaining months (~7) are an operator step:
   `final-trades backfill --start 2025-10-25 --end 2026-10-25 --max-units 40`
   repeated (or GH Actions dispatch) until coverage-report shows backlog
   exhausted. ~2 min/month at 2s politeness.
2. **Docker image not built locally** (no daemon on this machine) — CI
   `docker` job builds + smoke-tests it on push.
3. **Playwright browser e2e deferred** (documented deviation in
   `docs/testing.md`): CI docker smoke + TestClient full-stack + vitest
   page tests cover the same guarantees at lower CI weight.
4. FM 2026-02-06 remains FAILED in local DB (pre-fix row); next run with
   discovery coverage re-processes it to UNRESOLVED.
5. Fast Money attribution is `unverified/(unattributed)` by nature of the
   sources (no published per-trader attribution; no transcription by
   policy). Quantified in Analysts/Coverage tabs.
6. Port 8000 was occupied by an unrelated process during this session;
   smoke tests used 8123. No product impact.
7. yfinance logs noisy ERROR lines for delisted symbols (e.g., US20Y) —
   handled as MISSING_ENTRY; cosmetic only.
8. `performance` CLI computes for ALL recommendations each run (~75s at
   current size, per-run price cache). If it grows, add an incremental
   "due only" filter — noted as future optimization, not needed at 1k recs.

## Deployment assumptions

Nothing is provisioned. Target (operator executes, `docs/deployment.md`):
GH Actions cron (collector) + Cloud Run free tier (API+SPA) + Neon free
Postgres (collector RW role / api_ro SELECT-only role) = $0/month verified.

## Next steps (ordered)

1. Push to GitHub (public) → watch CI (first docker build validation).
2. Create Neon project + roles; add `DATABASE_URL` secret; run backfill
   dispatches until backlog=0; verify coverage report.
3. Deploy Cloud Run service (api-service.yaml edited) or compose on a host;
   verify /healthz, dashboard, 405 on POST.
4. Rehearse backup/restore drill (scenario #14) on a Neon branch.
5. Optional: Tiingo key for higher-quality adjusted prices; extend market
   calendar each December; consider Playwright e2e if UX regressions appear.
