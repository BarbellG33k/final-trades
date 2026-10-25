# Agent Guide: Parallel Workstreams

For coding agents (and humans) picking up work in parallel. Canonical rules:
root `AGENTS.md`. Ledger: `docs/PLAN.md` §17. Handoff state: `docs/STATUS.md`.

## Workstream ownership map

| WS | Modules owned | Shared contracts touched |
|----|---------------|---------------------------|
| WS-00 | docs/*, pyproject, web config, CI | — |
| WS-01 | `sources/*` | produces `sources/contracts.py` DTOs |
| WS-02 | `db/models.py`, `db/repositories.py`, `db/seed.py`, `migrations/*` | models are shared |
| WS-03 | `pipeline/normalize.py`, `pipeline/persist.py` | consumes contracts, models |
| WS-04 | `pipeline/orchestrator.py`, `pipeline/backlog.py`, `market_calendar.py`, `cli.py` | consumes all above |
| WS-05 | `api/*` | consumes models; produces `api/schemas.py` |
| WS-06 | `web/*` | consumes `api/schemas.py` (mirror in `web/src/types.ts`) |
| WS-07 | `performance/*` | consumes models; writes performance_observations only |
| WS-08 | `deploy/*`, `.github/workflows/*`, docs/cost-model, docs/deployment | — |
| WS-09 | security tests (extend `tests/integration/test_api.py`) | — |
| WS-10 | e2e, backfill execution, release docs | — |

## Rules for parallel agents

1. Claim a ledger row (set IN_PROGRESS + your handle) before editing; set
   DONE + evidence (test names/commits) after.
2. Never edit another WS's owned modules to work around a problem — file the
   need in `docs/STATUS.md` "Next steps" or change the contract WITH all
   consumers + docs in one commit.
3. Contract changes (contracts.py / schemas.py / models.py / types.ts)
   require: consumers updated, tests updated, `docs/data-model.md` or
   `docs/ARCHITECTURE.md` updated — same commit.
4. `main` stays runnable: before pushing, `uv run pytest -q`,
   `uv run mypy`, `uv run ruff check .`, `cd web && npm run build && npx vitest run`.
5. Blocked on an external integration? Build against fixtures + the written
   contract; record the blocker in STATUS; don't stall the workstream.
6. Tests never hit the network (fixtures in `tests/fixtures/`; `live` marker
   is excluded from CI). New adapter behavior ⇒ new recorded fixture.
7. Security invariants are not workstream-local: never add non-GET routes,
   never log secrets, never store full article bodies (excerpts ≤600 chars).

## Handy entry points

- Pipeline behavior spec: `docs/PRD.md` §5 + AGENTS.md failure semantics.
- "Why is data missing?" semantics: DateStatus vs CoverageStatus in
  `domain.py` + `docs/data-model.md`.
- Verification lattice: `pipeline/normalize.py::upgrade_verification`.
- Fixture-backed full pipeline example: `tests/integration/test_pipeline.py`.
