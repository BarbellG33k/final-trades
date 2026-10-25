# DECISIONS.md — Consequential Decisions

Format: context → decision → rationale → alternatives rejected. ADR-style
deep dives live in `docs/adr/`.

## D-001 License: Apache-2.0

Open-source distribution with express patent grant; permissive for reuse.
Full unmodified text in `LICENSE`. Third-party content (CNBC/Benzinga text,
market data) is explicitly NOT covered — README distinguishes code license
from content/provider terms. Rejected: MIT (no patent clause), GPL (copyleft
friction for contributors/hosts), AGPL (hostile to casual adoption).

## D-002 Stack: Python modular monolith + React/Vite SPA ("Stack A")

One Python codebase (FastAPI + CLI collector + pandas analytics), one Docker
image, two entrypoints; SPA is static files served by FastAPI.
Rationale: single language across pipeline+API+analytics; no Node runtime in
production; $0-friendly (one free-tier container + static assets); matches
"modular monolith" requirement. Rejected: Next.js full-stack (second runtime,
API duplicated in TS, Vercel-shaped lock-in, no SEO need), Python-only SSR
(weaker dense-grid UX, deviates from TS-frontend preference).

## D-003 Database: SQLAlchemy 2 + Alembic; SQLite dev/CI, Postgres prod

Portability across hosts; prod on Neon free tier (durable). SQLite banned for
the sole production DB (ephemeral filesystems on serverless). Types kept
dialect-portable (JSON with Text fallback). Separate collector (read-write)
and API (read-only where practical) identities in prod.

## D-004 Frontend build: Vite (not Next.js)

Dashboard is an internal-style data tool: no SEO requirement, API already
exists in Python, static bundle deploys anywhere. TanStack Query/Table for
server-driven dense grids. (Explained to maintainer 2026-10-25.)

## D-005 Scheduling: GitHub Actions cron primary; Cloud Run Jobs + Cloud
Scheduler as documented alternative

Public repo → unlimited free minutes for the collector (verified 2026-10-25;
the 2026-03-01 $0.002/min platform charge exempts public repos). Same image
runs in both. GH cron has known delays/skips — acceptable because recovery is
cross-run by design (backlog table is the durable queue). Cloud Scheduler
offers 3 free jobs with stronger guarantees as the alternative. Full verified
cost model: `docs/cost-model.md` → **$0/month** with GH Actions (collector) +
Cloud Run free tier (API+SPA) + Neon free Postgres; Cloud SQL rejected
(≈$9.4/mo minimum).

## D-006 Primary sources: Benzinga articles + CNBC Fast Money RSS

Probed 2026-10-25: Benzinga Halftime topic page accessible with JSON-LD
ItemList and daily "CNBC's 'Final Trades'" articles containing explicit
analyst→ticker attribution; CNBC RSS id=15838499 working with daily
"Final Trade: <TICKERS>" video items (~1 week window). Quiver Quantitative
deprioritized (heavy JS, gated API). Full gate results:
`docs/source-validation.md`. Attribution we cannot evidence is stored as
`unverified`/`unresolved` — never fabricated.

## D-007 Market data: yfinance (default, keyless) with optional Tiingo key;
FRED for index levels

Evidence (subagent probes 2026-10-25): **Stooq CSV is dead for scripts**
(PoW challenge → "Access denied" even with solved challenge + TLS
impersonation; pandas-datareader removed its Stooq reader). yfinance 1.7.0
verified working keyless (AAPL/SPY 1y = 251 rows, Adj Close ≠ Close →
dividend+split adjusted; raw Yahoo chart API also 200 keyless as escape
hatch). Tiingo free key = best adjusted data (CRSP method, divCash/
splitFactor audit fields, 1000 req/day) but requires signup → optional via
`TIINGO_API_KEY`, never required to build/run/CI. FRED fredgraph.csv keyless
(SP500/DGS10/VIXCLS) for benchmark context. Finnhub (no free candles),
Twelve Data (non-display terms), WIKI (dead 2018), Alpha Vantage (25/day,
adjusted premium-gated) rejected.
Terms caveat adopted: store prices as computation inputs; publicly display
only derived values (entry/exit close used, forward-return %, dates) with
attribution; no bulk price export from the dashboard.
Entry convention: publish timestamps come from the collector (price feeds
have no clock): published ≥16:00 ET → next trading day close; else same-day
close. Performance job scheduled after 18:00 ET so the day's bar is final.

## D-008 Failure semantics: cross-run recovery, zero intra-run retries

Deliberate product decision (master prompt §3): one bounded attempt per
(source, date) unit per scheduled run; failures recorded with category/stage/
occurrences; next scheduled run retries oldest-first within quota; capacity
share reserved for current-day work. No public triggers, no UI rerun/retry
buttons. Rationale: predictable cost, no retry storms against sources,
durable backlog table replaces queues/DLQs.

## D-009 Benchmark & performance methodology

SPY total return (Adj Close) as benchmark; horizons 1/5/20/60 trading days;
shorts reported separately, never netted into long stats; derivative mentions
(option ETFs, inverse products) measured as the traded instrument itself, no
underlying substitution; missing prices = explicit gaps with counts surfaced
in UI. Analyst performance shown only at n ≥ 30 observations per horizon,
else "insufficient data".

## D-010 Dependency licenses (third-party table)

| Package | License | Notes |
|---|---|---|
| fastapi, uvicorn, starlette | MIT / BSD | API server |
| sqlalchemy, alembic | MIT | ORM/migrations |
| httpx | BSD-3 | HTTP client |
| selectolax | MIT | HTML parsing (lexbor) |
| feedparser | ISC-style (BSD-2-clause-like) | RSS parsing |
| pandas | BSD-3 | analytics |
| pydantic, pydantic-settings | MIT | validation |
| typer, click | MIT | CLI |
| yfinance | Apache-2.0 | optional default price provider (data terms separate — see D-007) |
| react, react-dom | MIT | SPA |
| vite | MIT | build tool |
| tailwindcss | MIT | styling |
| @tanstack/react-query, react-table | MIT | data grid/state |
| typescript | Apache-2.0 | frontend types |

All permissive; compatible with Apache-2.0 distribution. No copyleft deps.
CI runs a license audit (`pip-licenses` + `license-checker-rs` equivalent via
npm) to keep this table honest.
