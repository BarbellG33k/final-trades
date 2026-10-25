# operations.md — Operating the Platform

## Routine operations (all automatic)

| Cadence | Job | What it does |
|---|---|---|
| Daily 13:17 UTC | `collect` (GH Actions) | Halftime article from this morning + backlog catch-up |
| Weekdays 23:17 UTC | `collect` (GH Actions) | Tonight's Fast Money segment + backlog catch-up |
| Weekdays 23:47 UTC | `performance` (GH Actions) | Forward-return computation for due horizons |

No manual steps are required in steady state. **There are no rerun/retry
controls by design** — failures self-heal on later scheduled runs
(bounded oldest-first backlog). Observe health on the dashboard
Overview/Runs/Coverage tabs.

## Monitoring

- Dashboard Overview: latest run status, per-show health, open issues,
  backlog trend. This is the primary monitoring surface.
- GH Actions run history: cron delivery + exit codes.
- Neon console: CU-hours (alert at 80/month), storage (<1 GB free tier).
- GCP (if Option A3): billing alert at $1; Cloud Run metrics.

Health thresholds worth acting on (see runbooks):

| Signal | Threshold | Runbook |
|---|---|---|
| Both shows `last_collected_date` older than 3 trading days | investigate | `runbooks/collector-failure.md` |
| One show failing repeatedly (issues attempt_count ≥ 5) | investigate | `runbooks/source-blocked.md` |
| Backlog growing across ≥5 consecutive runs | investigate | `runbooks/collector-failure.md` |
| `coverage` MISSING share rising for a month | data-quality pass | `runbooks/source-blocked.md` |

## Backups & restore

- **Neon (prod):** point-in-time recovery + branching are built into the
  free plan. Additionally, weekly logical backup:
  ```bash
  pg_dump "$DATABASE_URL_COLLECTOR" --format=custom -f ft-$(date +%F).dump
  # restore:
  pg_restore --clean --if-exists -d "$DATABASE_URL_COLLECTOR" ft-YYYY-MM-DD.dump
  ```
  Store dumps outside the DB host (e.g., private GH release asset or any
  object store). Restore drill: run against a scratch Neon branch and
  compare `coverage-report` output.
- **Compose/local:** `pgdata` volume; same pg_dump commands via
  `docker compose exec db`.
- SQLite dev DB: file copy while no writer is active.

## Recurring maintenance

| Task | Cadence | How |
|---|---|---|
| Extend NYSE holiday table | each December | `src/final_trades/market_calendar.py` + tests |
| Refresh source fixtures after markup changes | on parse-failure issue spikes | `final-trades fetch-fixtures`, trim, commit, adjust parser + tests |
| Dependency updates (Dependabot/renovate PRs) | weekly | merge when CI green; watch pip-audit |
| Verify free-tier limits unchanged | quarterly | re-check `docs/cost-model.md` sources |
| Review open issues list | monthly | dashboard → issues; close stale resolved |

## Scaling knobs (all env vars, no code changes)

- `BACKLOG_MAX_DATES_PER_RUN` (default 40), `CURRENT_DAY_CAPACITY_SHARE`
  (0.6) — throughput vs politeness.
- `RATE_LIMIT_RPS`/`RATE_LIMIT_BURST` — public API protection.
- `OVERVIEW_CACHE_TTL_SECONDS`, `DB_QUERY_TIMEOUT_MS` — API cost guards.
- `HTTP_MIN_REQUEST_INTERVAL_SECONDS` (≥0.5 enforced) — source politeness.

## Incident basics

1. Dashboard first: Overview → recent failures → run detail (per-source,
   per-date, sanitized diagnostics).
2. GH Actions logs second (structured JSON logs; `error_type` only, never
   bodies or secrets).
3. Runbooks: `runbooks/collector-failure.md`, `runbooks/source-blocked.md`,
   `runbooks/database-recovery.md`.
4. Never delete `issues` rows to "clean up" — resolution is a flag; history
   is a feature.
