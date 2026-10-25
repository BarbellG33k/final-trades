# AGENTS.md — Canonical Project Guidance

This file is the single source of truth for coding agents (Claude Code, Kiro,
Amp, OpenCode, Cursor, etc.) working on this repository. Other agent config
files point here. Human docs live under `docs/`.

## Project purpose

Collect, organize, display, and analyze CNBC "Final Trade" recommendations
from **Halftime Report** and **Fast Money**: 12 months of history
(2025-10-25 → 2026-10-26 window inclusive), daily scheduled collection,
source-evidence preservation, and a public read-only dashboard.

## Repository layout

```
src/final_trades/       # Python package (modular monolith)
  config.py             #   settings, env validation (fail fast at startup)
  db/                   #   models.py (SQLAlchemy), session.py, repositories/
  migrations/           #   Alembic versions
  sources/              #   adapters: benzinga, cnbc_rss, http client, contracts
  pipeline/             #   orchestration: runs, backlog, normalize, dedupe,
                        #   evidence, market calendar, coverage
  performance/          #   prices, forward returns, benchmarks
  api/                  #   FastAPI app, routes, schemas, middleware
  cli.py                #   typer entrypoints (collect/backfill/performance/serve)
web/                    # React + Vite + TypeScript SPA (dashboard)
tests/                  # pytest; fixtures/ holds recorded HTML/RSS (no live net)
docs/                   # PLAN, PRD, ARCHITECTURE, DECISIONS, STATUS,
                        # CONTRIBUTING, source-validation, data-model,
                        # deployment, cost-model, operations, testing,
                        # security, adr/, agent-guides/, runbooks/
deploy/                 # Dockerfile, docker-compose, cloud run configs
.github/workflows/      # CI + scheduled collector
```

## Commands

| Task | Command |
|---|---|
| Install deps | `uv sync --extra dev` |
| Run migrations | `uv run alembic upgrade head` |
| One collection run | `uv run final-trades collect --once` |
| Operator backfill | `uv run final-trades backfill --start 2025-10-25 --end 2026-10-25` |
| Compute performance | `uv run final-trades performance` |
| Coverage report | `uv run final-trades coverage-report` |
| Serve API (+built SPA) | `uv run final-trades serve` |
| Tests | `uv run pytest --cov` (no network; `live` marker excluded) |
| Lint / format | `uv run ruff check .` / `uv run ruff format .` |
| Types | `uv run mypy` |
| Frontend dev | `cd web && npm install && npm run dev` |
| Frontend test/lint | `cd web && npm test` / `npm run lint` / `npm run build` |

## Architecture boundaries (do not cross)

1. `sources/` fetches and parses **only** — returns typed DTOs + raw evidence;
   it never touches the DB.
2. `pipeline/` owns normalization, dedupe, persistence orchestration, run
   bookkeeping, and backlog policy. It is the only writer of ingestion tables.
3. `api/` is **read-only**. It must never import `pipeline/` writers or expose
   any endpoint that mutates ingestion state or triggers collection.
4. `performance/` is independent of collection and rendering; it only reads
   recommendations and writes `performance_observations`.
5. `web/` talks exclusively to `/api/v1/*`; no direct DB access, no secrets.

Shared contracts (DTOs in `sources/contracts.py`, Pydantic schemas in
`api/schemas.py`, models in `db/models.py`) must not change without updating
all consumers, tests, `docs/data-model.md`, and `docs/ARCHITECTURE.md`.

## Data provenance rules (non-negotiable)

- Never fabricate a recommendation, analyst attribution, or price.
- Every persisted recommendation links to ≥1 source with URL, retrieved_at,
  content hash, and an allowed short evidence excerpt (attribution + link).
- Ambiguous/conflicting attribution → verification_status `unresolved`, with
  the conflict recorded. Gaps stay visible in coverage tables.
- Distinguish verified segment absence (`NO_SEGMENT`) from unchecked
  (`PENDING`) and failed retrieval (`FAILED`).
- Respect sources: rate-limit (≥2s between requests/host), polite UA, honor
  robots.txt, bounded page fetches.

## Failure-handling semantics (deliberate product decisions)

- **No** rerun/retry buttons in the UI; **no** public endpoint triggers
  collection; **no** intra-run retry loops; one bounded attempt per
  source/date unit per scheduled run.
- Failures are recorded (error category, stage, first/last occurrence,
  attempt count) and recovered by **later scheduled runs** via a bounded,
  oldest-first backlog that cannot starve current-day collection
  (`CURRENT_DAY_CAPACITY_SHARE`, `BACKLOG_MAX_DATES_PER_RUN`).
- Run statuses: `RUNNING`, `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`. Per-source
  and per-date statuses are tracked separately; one show's success must never
  mask the other's failure.
- Durable progress markers never advance past unprocessed records.
- Committed records survive later failures in the same run (commit per date).

## Security rules

- Public API: read-only, validated query params, pagination (default 20,
  max 100), rate limiting, query timeouts, cache headers, same-origin CORS,
  security headers, generic error envelope (`{error, message}`) — never stack
  traces, env values, or connection strings.
- Secrets only via env vars; never logged (log presence, not values).
- Collector and API use separate DB roles in production (API read-only where
  practical).
- Assume every endpoint is discoverable by arbitrary clients; public traffic
  must never trigger paid or unbounded work.

## Parallel-work conventions

- Work is tracked as workstreams WS-00…WS-10 in the `docs/PLAN.md` task
  ledger (unique IDs, status, dependencies, validation evidence). Update the
  ledger when you finish a task.
- `main` must stay runnable: migrations apply cleanly, tests pass, `serve`
  boots, SPA builds.
- Keep commits Conventional (`feat(collector): …`), subject ≤72 chars.
- If an external integration is blocked, build against fixtures + the written
  contract and record the blocker in `docs/STATUS.md`.
- Do not modify shared interfaces without updating all consumers + docs in
  the same change.

## Definition of done (per task)

Tests written and passing (fixtures only, no live network in CI), coverage
floor respected (≥90% on pipeline/API logic), lint+types clean, docs updated
(PLAN ledger, STATUS if handoff-relevant), no secrets, migrations reversible.

## Key references

- `docs/PLAN.md` — authoritative plan + task ledger
- `docs/PRD.md` — requirements and acceptance criteria
- `docs/ARCHITECTURE.md` — system design and query patterns
- `docs/STATUS.md` — current state, known issues, next steps
- `docs/DECISIONS.md` + `docs/adr/` — why things are the way they are
