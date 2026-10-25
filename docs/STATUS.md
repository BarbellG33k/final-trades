# STATUS.md — Current State & Handoff

Last updated: 2026-10-25 (Phase 1 in progress)

## Completed

- WS-00.1/.2: repo initialized (`main`), Apache-2.0 LICENSE, README,
  AGENTS.md (canonical), CLAUDE.md pointer, .gitignore, .env.example,
  pyproject with ruff/mypy/pytest config, uv-managed Python 3.12 venv,
  dependencies locked.
- WS-00.3 (partial): docs/PLAN.md (authoritative + task ledger),
  docs/PRD.md, docs/ARCHITECTURE.md, docs/DECISIONS.md written.
- Source probes (initial): Benzinga Halftime topic page + CNBC Fast Money
  RSS verified accessible 2026-10-25 (details in PLAN §4; full validation
  gate pending WS-01).
- Market-data research complete (subagent): Stooq dead for scripts;
  yfinance verified working keyless; Tiingo best-with-key; FRED keyless for
  index levels. Decision recorded as D-007.

## In progress

- WS-00.3: remaining docs (CONTRIBUTING, data-model, testing, security,
  operations, deployment, cost-model, runbooks).
- WS-08.1: hosting cost-model research (background subagent still running).

## Verified behavior

- `uv sync --extra dev` resolves and installs cleanly (Python 3.12.15).
- Live fetch: Benzinga topic page returns JSON-LD ItemList of 30 recent
  Final Trades articles; CNBC RSS returns ~30 items incl. daily
  `Final Trade: <TICKERS>` entries.
- yfinance probe: AAPL/SPY 1y daily = 251 rows through 2026-10-23, with
  dividend-adjusted close (external throwaway probe, not committed).

## Known issues / blockers

- Node is available only via nvm (`~/.nvm/versions/node/v24.21.0/bin`) —
  PATH must be extended in shells and CI for `web/` work.
- Default subagent model (`zai-coding-plan/glm-5.2`) unavailable in this
  environment; subagents must be pinned to `bailian-cli/qwen3.8-max`.
- Quiver Quantitative unusable (heavy JS); deprioritized.
- Stooq unusable (PoW + access denied) — D-007 records the switch.

## Deployment assumptions (current)

- Prod: GH Actions cron (collector) + Cloud Run free tier (API+SPA) + Neon
  free Postgres. Pending WS-08.1 pricing verification. Nothing provisioned.

## Next steps (ordered)

1. Finish WS-00.3 docs + WS-00.4 web scaffold.
2. WS-01: HTTP client + adapters + fixtures + validation gate (≥10 dates).
3. WS-02: models + Alembic + repositories.
4. WS-03/04: normalization, orchestrator, backlog, CLI.
5. WS-05/06: API + dashboard. WS-07: performance. WS-08/09/10: deploy prep,
   security tests, integration + real backfill.
