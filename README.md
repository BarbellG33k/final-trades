# Final Trade Intelligence Platform

An open-source platform that collects, organizes, displays, and analyzes **CNBC
Final Trade** recommendations from two shows:

- **CNBC Halftime Report** — the "Final Trades" segment
- **CNBC Fast Money** — the "Final Trade" segment

It reconstructs 12 months of historical recommendations (2025-10-25 →
2026-10-25), collects new segments on a daily schedule, preserves source
evidence for every record, and serves a public read-only dashboard covering
recent activity, historical records, collection runs, errors, coverage, and
recommendation performance.

## Features

- **Evidence-backed collection.** Every recommendation stores its source URL,
  an allowed evidence excerpt, a content hash, and retrieval timestamps. Gaps
  are recorded as gaps — never fabricated.
- **Resumable, idempotent pipeline.** Failed dates are marked unresolved and
  retried by *later scheduled runs* (bounded, oldest-first backlog). There are
  deliberately no retry buttons, no public trigger endpoints, and no intra-run
  retry loops.
- **Operational transparency.** The dashboard shows per-run, per-source, and
  per-date outcomes, including partial success (one show collected while the
  other failed), error categories, and recovery history.
- **Performance analytics.** Forward returns at 1/5/20/60 trading days vs. a
  benchmark, with explicit entry conventions, sample sizes, and honest
  reporting of missing data. Not investment advice.
- **Dense, fast UI.** Seven tabs (Overview, Runs, Recommendations, Historical
  Data, Analysts, Performance, Data Coverage) built for scanning: server-side
  filtering, sorting, pagination; expandable rows; URL-synced filter state.

## Architecture (high level)

```
                 ┌────────────────────────────┐
 GitHub Actions  │  Collector (Python CLI)    │   scheduled daily
 cron ──────────▶│  sources → normalize → DB  │   (no public trigger)
                 └─────────────┬──────────────┘
                               │ SQLAlchemy (write)
                        ┌──────▼──────┐
                        │  Postgres   │  (SQLite for local dev)
                        └──────▲──────┘
                               │ SQLAlchemy (read-only)
   Browser ◀── static SPA ── ┌─┴───────────────┐
   (React + Vite)            │ FastAPI service │  rate-limited, cached,
                             │ /api/v1/...     │  paginated, read-only
                             └─────────────────┘
```

One Python codebase, two entrypoints: `final-trades collect` (background
pipeline) and `final-trades serve` (public API + built SPA). A separate
`final-trades performance` job computes forward returns from free market data.
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Data provenance

Primary sources (validated in [`docs/source-validation.md`](docs/source-validation.md)):

- Benzinga topic pages and articles for both shows' Final Trade recaps
  (analyst→ticker attribution, evidence excerpts).
- CNBC's official Fast Money RSS feed and video pages (segment detection,
  tickers, URLs).

Records carry an extraction method, a confidence level, and a verification
status. Conflicting or ambiguous attribution is stored as unresolved rather
than guessed.

## Local development

```bash
# Backend (Python 3.12, uv)
uv sync --extra dev
cp .env.example .env
uv run alembic upgrade head          # creates SQLite schema
uv run final-trades collect --once   # one bounded collection run
uv run final-trades serve            # API on http://127.0.0.1:8000

# Frontend (Node 20+)
cd web && npm install && npm run dev # SPA on http://localhost:5173

# Tests, lint, types
uv run pytest --cov
uv run ruff check .
uv run mypy
```

CI never touches live external sites — tests use recorded fixtures.

## Deployment

Deployment configs (Docker, GitHub Actions scheduled collector, Cloud Run +
Cloud Scheduler, Postgres on Neon free tier) live in `deploy/` and
`.github/workflows/`. The target operating cost is **$0/month** (ceiling $3);
the verified cost model is in [`docs/cost-model.md`](docs/cost-model.md). This
repository does not provision infrastructure by itself.

## Documentation

| Doc | Contents |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Authoritative plan + task ledger |
| [`docs/PRD.md`](docs/PRD.md) | Product requirements |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Consequential decisions + ADRs |
| [`docs/STATUS.md`](docs/STATUS.md) | Current state / handoff |
| [`docs/data-model.md`](docs/data-model.md) | Schema reference |
| [`docs/source-validation.md`](docs/source-validation.md) | Source evidence |
| [`docs/operations.md`](docs/operations.md) · [`docs/runbooks/`](docs/runbooks/) | Ops procedures |
| [`AGENTS.md`](AGENTS.md) | Canonical guidance for coding agents |

## Licensing

- **This application's source code**: Apache License 2.0 — see
  [`LICENSE`](LICENSE). Includes an express patent grant.
- **Third-party content**: Articles, videos, and text from CNBC, Benzinga, and
  other sources remain the property of their publishers and are **not**
  covered by this license. This project stores short attributed evidence
  excerpts and links for research/commentary purposes; it does not
  redistribute full articles or media.
- **Market data**: Provided by third parties (e.g., Stooq, Yahoo Finance via
  yfinance) under their own terms; stored prices are used to compute derived
  statistics. Review provider terms before redistributing raw price data.
- **Optional services**: Hosting/DB providers (Google Cloud, Neon, GitHub)
  have their own terms.

Third-party dependency licenses: see [`docs/DECISIONS.md`](docs/DECISIONS.md)
(dependency table).

## Limitations

- Attribution for Fast Money trades depends on source availability; some
  historical records may remain `unverified` or `unresolved` — the coverage
  tab shows exactly which.
- Performance figures are descriptive statistics about TV segments, not
  investment advice; short/option mentions are not treated as executable
  trades.
- Collection depends on third-party sites that may change or block access;
  failures are visible in the dashboard, and recovery is automatic on later
  scheduled runs.

## Disclaimer

This is an independent open-source research project. It is not affiliated
with, endorsed by, or sponsored by CNBC, NBCUniversal, or Benzinga. Nothing
here is investment advice.
