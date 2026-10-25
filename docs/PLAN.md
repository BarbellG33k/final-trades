# PLAN.md — Authoritative Plan & Task Ledger

Status: **MVP FEATURE-COMPLETE** (deployment prepared, not provisioned). Last updated: 2026-10-25.

## 1. Objectives

1. Collect CNBC Final Trade recommendations from **Halftime Report** and
   **Fast Money**, with source evidence for every record.
2. Reconstruct the 12-month window **2025-10-25 → 2026-10-25** (inclusive),
   resumably and idempotently.
3. Collect new segments daily via scheduled runs, with cross-run recovery of
   failed dates (no intra-run retries, no public triggers).
4. Serve a public, read-only, information-dense dashboard: Overview, Runs,
   Recommendations, Historical Data, Analysts, Performance, Data Coverage.
5. Compute forward-return performance (1/5/20/60 trading days) vs. benchmark
   with explicit conventions and honest gap reporting.
6. Operate at **$0/month** (ceiling $3), open-source (Apache-2.0), portable
   across hosts.

## 2. Non-goals

- No user accounts, auth, personalization, alerts, or write UI.
- No real-time/intraday data; no video transcription or paid LLM extraction.
- No redistribution of full articles/media (short attributed excerpts + links).
- No investment advice; performance is descriptive statistics.
- No intra-run retry loops or manual rerun controls (deliberate, see PRD §5).

## 3. Architecture & major decisions (summary)

Python modular monolith (FastAPI + CLI collector sharing one codebase),
React+Vite+TypeScript SPA served as static files by FastAPI. SQLAlchemy 2 +
Alembic; SQLite for dev/CI, Postgres (Neon free tier) in production.
Collector scheduled via GitHub Actions cron (public repo = free) with Cloud
Run Jobs + Cloud Scheduler configs provided as the alternative. Details:
`docs/ARCHITECTURE.md`; rationale: `docs/DECISIONS.md` + `docs/adr/`.

## 4. Data acquisition & validation

Sources (probe results in `docs/source-validation.md`):

| Source | Role | Evidence status |
|---|---|---|
| Benzinga topic page `halftime-report-final-trades` | Halftime listing + pagination | **VERIFIED accessible 2026-10-25**; JSON-LD ItemList; daily articles with analyst→ticker attribution in summaries/bodies |
| Benzinga topic page `fast-money-final-trade` | Fast Money listing | probe pending (WS-01.1) |
| Benzinga article pages | Attribution, thesis, evidence excerpt | probe pending (WS-01.1) |
| CNBC Fast Money RSS `id=15838499` | Fast Money segment detection, tickers in title, video URLs | **VERIFIED 2026-10-25**; ~1 week rolling window only |
| CNBC video pages | Fast Money evidence links | probe pending (WS-01.1) |
| Quiver Quantitative cnbctracker | optional corroboration | **DEPRIORITIZED** — heavy JS page, gated API |

Validation gate (before relying on a source): ≥10 dates sampled across all
four quarters of the target window, per show, recording article/video
availability, attribution quality, direction details, cross-source agreement,
access failures. Findings → `docs/source-validation.md`.

Acquisition rules: ≥2s between requests per host, polite UA with contact URL,
robots.txt honored, bounded fetches, content hash + retrieved_at stored,
never fabricate to fill gaps.

## 5. Historical backfill

- Operator-invoked CLI: `final-trades backfill --start … --end …` (never a
  public endpoint).
- Resumable: per-(show, date) `date_processing_status` rows drive work
  selection; idempotent upserts keyed on (segment, analyst, instrument,
  direction).
- Bounded per run: quota of dates, oldest-first, current-day work gets
  reserved capacity first.
- Market calendar (weekends + NYSE holidays) distinguishes non-trading days
  (`NO_SEGMENT`) from gaps.

## 6. Daily processing & recovery

Scheduled run algorithm:

1. Create `ingestion_runs` row (`RUNNING`).
2. Discover current source records (Benzinga listings, CNBC RSS).
3. Process current-day/trading-day dates for both shows (bounded attempts).
4. Select unresolved historical dates (FAILED/PENDING/UNRESOLVED, oldest
   first) within remaining quota.
5. Normalize, dedupe, persist (commit per date — partial progress survives).
6. Record per-source results (`source_run_results`) and issues (`issues`).
7. Update coverage aggregates; finalize run status
   (SUCCESS / PARTIAL_SUCCESS / FAILED) with counts and duration.
8. Exit code reflects status (0 success, 1 partial, 2 failed) for CI/cron
   visibility.

Failure → record and move on; the **next scheduled run** retries the date.
Progress markers never advance past unprocessed records.

## 7. Database & data model

Entities: `shows`, `segments`, `analysts`, `instruments`, `recommendations`,
`sources`, `recommendation_sources`, `ingestion_runs`, `source_run_results`,
`date_processing_status`, `issues`, `performance_observations`,
`coverage_daily`. Full schema + index rationale: `docs/data-model.md`.
Alembic migrations under `src/final_trades/migrations/`.

## 8. Public dashboard & user workflows

Seven tabs (Overview, Runs, Recommendations, Historical, Analysts,
Performance, Data Coverage) per PRD §3. Server-side filtering/sorting/
pagination (default 20, max 100), URL-synced filter state, expandable detail
rows, sticky headers, explicit loading/empty/stale/error states, per-show
status separation everywhere, usable when the last run failed. Detail routes
for runs and recommendations.

## 9. Market data & performance analytics

Provider: free EOD CSV (Stooq primary, yfinance fallback — final choice after
WS-07.1 evaluation, see `docs/DECISIONS.md`). Horizons 1/5/20/60 trading
days. Entry convention: publication ≥16:00 ET → next trading day's close;
else same-day close. Benchmark: SPY (total return where available). Shorts
tracked separately; options/derivatives never substituted with underlying
returns; missing prices reported as gaps, persisted with timestamps.

## 10. Hosting evaluation & deployment

Candidates evaluated in `docs/cost-model.md` (WS-08.1, with date-checked
pricing): Cloud Run Jobs + Cloud Scheduler (initial preferred), GitHub
Actions cron, AWS Lambda + EventBridge, Netlify scheduled functions, Railway,
n8n, DO droplets. Deliverables: Dockerfile (two entrypoints), docker-compose
production simulation, GH Actions workflows (CI + scheduled collector), Cloud
Run/Scheduler configs, Neon setup guide. **No provisioning without explicit
approval.**

## 11. Cost controls

$0 target: public-repo GH Actions minutes (free), free-tier Postgres, free-
tier serverless/container hosting, free market data, no paid LLM/transcription.
Guards: bounded fetch quotas per run, response size caps, static asset
caching, no public endpoint can trigger ingestion work.

## 12. Security & public access

Read-only public API; rate limiting; validated params; pagination caps; DB
query timeouts; cached summaries; same-origin CORS; security headers; generic
errors (no stack traces/secrets); separate write (collector) vs read (API) DB
identities in prod; dependency audits + secret scanning in CI. Details:
`docs/security.md`.

## 13. Testing & release

pytest (unit + integration, recorded fixtures only — no live network in CI),
Vitest/RTL for web, Playwright smoke e2e. The 18 critical scenarios from the
master prompt §13 are mapped in `docs/testing.md`. Release = tagged main with
green CI, updated STATUS/README, license scan clean.

## 14. Parallel workstreams

WS-00 foundation · WS-01 sources · WS-02 database · WS-03 extraction/
normalization · WS-04 orchestration · WS-05 API · WS-06 dashboard ·
WS-07 market data · WS-08 hosting · WS-09 security validation ·
WS-10 integration/release. Ownership boundaries in `AGENTS.md`. Shared
contracts: `sources/contracts.py`, `api/schemas.py`, `db/models.py`.

## 15. Dependencies, risks, blockers, fallbacks

| Risk | Impact | Mitigation / fallback |
|---|---|---|
| Benzinga blocks scraping (bot detection) | Historical attribution lost | RSS-first for current day; CNBC pages; mark dates UNRESOLVED; document coverage gaps honestly |
| Benzinga pagination depth < 12 months | Backfill incomplete | Wayback Machine snapshots of topic pages as secondary evidence (documented, marked) |
| Fast Money attribution unavailable for old dates | Unverified records | Store tickers from RSS/video titles with `verification_status=unverified`; coverage tab shows share |
| Free market data gaps (delisted symbols) | Performance holes | Multi-provider fallback; report missing honestly |
| Free DB tier limits change | Cost > $0 | SQLite-on-durable-volume fallback; provider switch documented (SQLAlchemy portable) |
| GH Actions cron delays/skips | Collection lag | Next-run catch-up design absorbs it; Cloud Run Scheduler config as alternative |
| Legal/terms objection from source | Must stop collecting | Adapter-per-source design; disable source via config; preserve already-collected evidence per fair-use excerpts; documented in security.md |

## 16. Acceptance criteria (product-level)

Per master prompt §15 Definition of Done — tracked in the ledger below and
verified in WS-10 with evidence links (test names, command output).

## 17. Task ledger

Legend: `TODO` → `IN_PROGRESS` → `DONE` (+ validation evidence) · `BLOCKED`

| ID | Task | Depends | Status | Evidence |
|----|------|---------|--------|----------|
| WS-00.1 | Git init, LICENSE, README, AGENTS/CLAUDE, .gitignore, .env.example | — | DONE | commit c2642b5 |
| WS-00.2 | Python scaffold: pyproject, uv sync, tooling (ruff/mypy/pytest) | — | DONE | `uv sync` clean, deps locked |
| WS-00.3 | docs/ tree: PLAN, PRD, ARCHITECTURE, DECISIONS, STATUS, CONTRIBUTING | WS-00.1 | DONE | commit 9193c95+ |
| WS-00.4 | Web scaffold: Vite + React + TS + Tailwind, lint/test config | WS-00.2 | DONE | web/ builds + 11 vitest tests |
| WS-00.5 | CI workflow: lint, types, tests, build web, dep audit, secret scan | WS-00.4 | DONE | .github/workflows/ci.yml |
| WS-01.1 | Live probes: Benzinga fast-money topic + article pages, CNBC video page; record findings | — | DONE | docs/source-validation.md probes |
| WS-01.2 | HTTP client: rate limit, UA, robots, retries=0, hash+excerpt capture | WS-00.2 | DONE | tests/unit/test_http.py |
| WS-01.3 | Benzinga adapters (topic listing + article parse) with fixtures | WS-01.2 | DONE | test_benzinga_parse.py; 8/8 live-sample extraction |
| WS-01.4 | CNBC RSS adapter + video-page adapter with fixtures | WS-01.2 | DONE | test_cnbc_parse.py |
| WS-01.5 | Validation-gate sampling: ≥10 dates × 2 shows across quarters | WS-01.3/4 | DONE | gate PASSED — 6 windows, 4 quarters, 957 recs |
| WS-02.1 | SQLAlchemy models (all entities) + naming/index conventions | WS-00.2 | DONE | 13 tables, commit 9193c95 |
| WS-02.2 | Alembic setup + initial migration; SQLite & Postgres compatible | WS-02.1 | DONE | a7e1f22a9627 applies clean |
| WS-02.3 | Repositories: segments, recommendations, runs, date status, issues, coverage | WS-02.2 | DONE | test_repositories.py |
| WS-03.1 | Normalization: analyst names, tickers/instruments, direction, position type | WS-01.3 | DONE | pipeline/normalize.py |
| WS-03.2 | Dedupe/idempotency + multi-source merge | WS-02.3 | DONE | test_persist.py + double-ingest test |
| WS-03.3 | Evidence validation (excerpt length, hash, attribution present) + review statuses | WS-03.1 | DONE | verification lattice + conflict tests |
| WS-04.1 | Market calendar (weekends + NYSE holidays 2025-26) | — | DONE | test_market_calendar.py |
| WS-04.2 | Run orchestrator: current-day processing, per-date commits | WS-03.x | DONE | tests/integration/test_pipeline.py |
| WS-04.3 | Backlog policy: bounded, oldest-first, capacity share | WS-04.2 | DONE | test_select_work_* |
| WS-04.4 | Run/source/date bookkeeping + issues store + run finalize/exit codes | WS-04.2 | DONE | recovery + abort tests |
| WS-04.5 | Backfill CLI + collect CLI | WS-04.3 | DONE | tests/unit/test_cli.py |
| WS-05.1 | API app: middleware (rate limit, security headers, CORS, errors), health | WS-02.3 | DONE | middleware + tests in test_api.py |
| WS-05.2 | Endpoints: overview, runs, run detail | WS-05.1 | DONE | test_runs_and_run_detail, overview tests |
| WS-05.3 | Endpoints: recommendations, historical, coverage | WS-05.1 | DONE | recommendations/historical/coverage tests |
| WS-05.4 | Endpoints: analysts, performance | WS-05.1, WS-07.2 | DONE | analysts/performance endpoint tests |
| WS-06.1 | SPA shell: routing, tabs, API client, design tokens, states | WS-00.4 | DONE | App shell, router, tokens, api client |
| WS-06.2 | Overview + Runs tabs (grid, filters, run detail) | WS-06.1, WS-05.2 | DONE | Overview/Runs/RunDetail pages |
| WS-06.3 | Recommendations + Historical tabs (filters, detail drawer, infinite scroll) | WS-06.1, WS-05.3 | DONE | Recommendations (9 filters + evidence drawer) / Historical |
| WS-06.4 | Coverage + Analysts + Performance tabs | WS-06.1, WS-05.3/4 | DONE | Coverage/Analysts/Performance pages |
| WS-07.1 | Provider evaluation (subagent report) + price ingestion module | WS-00.2 | DONE | D-007 (Stooq dead; yfinance default + optional Tiingo) |
| WS-07.2 | Forward returns 1/5/20/60 + benchmark + conventions + persistence | WS-07.1, WS-02.3 | DONE | 10 perf unit tests + 1984 live observations |
| WS-07.3 | performance CLI job + missing-data honesty in API/UI | WS-07.2 | DONE | final-trades performance + honest gaps in UI |
| WS-08.1 | Cost model research (subagent) + docs/cost-model.md | — | DONE | docs/cost-model.md, prices checked 2026-10-25 |
| WS-08.2 | Dockerfile, docker-compose prod sim | WS-05.x | DONE | deploy/Dockerfile + compose (CI-validated build) |
| WS-08.3 | GH Actions: scheduled collector + backfill (manual) workflows | WS-08.2 | DONE | .github/workflows/collector.yml |
| WS-08.4 | Cloud Run + Cloud Scheduler configs, Neon guide, deployment.md | WS-08.1 | DONE | deploy/cloud-run/* + docs/deployment.md |
| WS-09.1 | Security tests: read-only enforcement, no trigger endpoints, rate limit, error sanitization, query bounds | WS-05.x | DONE | scenarios 11/12/16/17 tests green |
| WS-09.2 | Abuse-prevention audit vs docs/security.md checklist | WS-09.1 | DONE | docs/security.md checklist mapped to code |
| WS-10.1 | 18 critical scenarios mapped + passing (docs/testing.md) | all | DONE | docs/testing.md scenario map (17/18 automated; #14 runbook) |
| WS-10.2 | Real backfill run over 12-month window + coverage report | WS-04.5 | IN_PROGRESS | PARTIAL: sampled months backfilled live (gate); full-window run is an operator step — see STATUS |
| WS-10.3 | e2e smoke (Playwright), release prep, STATUS handoff | WS-10.1/2 | IN_PROGRESS | PARTIAL: e2e = CI docker smoke + vitest; Playwright deferred (documented); release ready pending GitHub push |

## 18. Definition of done (MVP)

Master prompt §15 checklist, item by item, verified with evidence in
`docs/STATUS.md` at WS-10.3. Do not claim completion for unverified items.
