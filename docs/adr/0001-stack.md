# ADR-0001: Python modular monolith with React/Vite SPA

Date: 2026-10-25 · Status: accepted · Refs: DECISIONS D-002/D-004

## Context

Two runtime concerns: a scheduled collector/analytics pipeline (parsing,
normalization, price math) and a public read-only dashboard. Constraints:
$0/month hosting, portable, easy for agents/maintainers to work on, dense
interactive data grids, no SEO requirement.

## Decision

One Python codebase (FastAPI + Typer CLI + pandas) producing one Docker
image with two entrypoints (`serve`, `collect`); the dashboard is a static
React 19 + Vite + TypeScript + Tailwind SPA served by FastAPI from
`web/dist`. SQLAlchemy 2 + Alembic over SQLite (dev) / Postgres (prod).

## Consequences

- Single language for pipeline+API+analytics; shared models and query code;
  one deployable unit at $0 (Cloud Run free tier + GH Actions free cron).
- No SSR/SEO; acceptable — internal-style data tool.
- Vite over Next.js: no Node runtime in prod, no duplicated API layer,
  host-portable static bundle.
- Cost: one container serves both concerns — scaling is coarse (fine at
  hobby traffic; max-instances caps abuse).

## Alternatives rejected

Next.js full-stack (second runtime, TS API duplicate, Vercel-shaped);
Python-only SSR/htmx (weaker dense-grid UX); microservices (unjustified
ops cost at this scale).
