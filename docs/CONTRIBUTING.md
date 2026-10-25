# CONTRIBUTING.md

Thanks for your interest! This project collects publicly available CNBC
Final Trade recommendations with full source attribution, and publishes the
data and analytics as open source under Apache-2.0.

## Before you start

- Read [`AGENTS.md`](../AGENTS.md) — architecture boundaries, data
  provenance rules, and failure-handling semantics are binding for humans
  and agents alike.
- Check [`docs/PLAN.md`](PLAN.md) (task ledger) and
  [`docs/STATUS.md`](STATUS.md) for what's in flight.

## Local setup

```bash
# Backend
uv sync --extra dev
cp .env.example .env
uv run alembic upgrade head
uv run pytest --cov          # tests use fixtures; no network needed

# Frontend
cd web && npm install && npm run dev
```

## Making changes

1. Branch from `main`: `feature/<short-desc>`, `fix/<short-desc>`.
2. Write tests first for logic changes (TDD); fixtures under `tests/fixtures/`
   — **CI must never hit live external sites**.
3. Conventional Commits (`feat(pipeline): …`), subject ≤72 chars, body
   explains *why* when touching >3 files or changing behavior.
4. Keep coverage ≥90% on pipeline/API logic; `ruff`, `mypy --strict`, and
   web lint/tests green.
5. Update docs in the same PR when you touch shared contracts
   (`sources/contracts.py`, `api/schemas.py`, `db/models.py`):
   `docs/data-model.md`, `docs/ARCHITECTURE.md`, and the PLAN ledger.
6. Open a PR ≤400 lines where practical; describe manual verification steps.

## Ground rules (non-negotiable)

- **Never fabricate data** — recommendations, attributions, or prices.
- No new public write endpoints, no collection triggers in the UI/API.
- No secrets in code, logs, error messages, or fixtures.
- Respect source sites: keep rate limits, polite UA, robots.txt handling.
- Don't add paid dependencies or services without an issue discussion.

## Recording source fixtures

When an adapter changes or a source's markup changes:

```bash
uv run final-trades fetch-fixtures --source benzinga_halftime   # bounded, rate-limited
```

Fixtures are trimmed snapshots (article body region only) kept small enough
to commit; they preserve structure, not full copyrighted content.

## Code of conduct

Be kind, review honestly, assume good faith. Maintainers merge via squash
(mission branches via merge commit).
