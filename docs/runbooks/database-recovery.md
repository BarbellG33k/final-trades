# Runbook: database recovery

**Symptoms:** `database` error category in issues; API 500s; collector
aborts with DB exceptions; Neon compute suspended or storage full.

## Diagnose

1. Neon console: compute active? storage vs 1 GB free limit? CU-hours
   exhausted (compute suspends until next period)?
2. From an operator shell: `psql "$DATABASE_URL" -c 'SELECT 1'`.
3. API health: `/healthz` is DB-independent; `/api/v1/runs` failing with
   generic 500 + logs showing `error_type=OperationalError` → DB path.

## By cause

- **CU-hours exhausted (free tier):** compute suspended; resumes at period
  reset. Mitigation: raise `OVERVIEW_CACHE_TTL_SECONDS`, reduce traffic
  exposure; consider Supabase/Turso fallback (cost-model.md ladder).
- **Storage full (>1 GB):** writes blocked. Prune is rarely needed at our
  volume — inspect growth: `SELECT pg_size_pretty(pg_database_size(current_database()));`.
  Evidence excerpts dominate; they are the product — scale plan instead of
  deleting provenance (Neon paid or provider switch; export first).
- **Connection failures from CI:** Neon autosuspends after 5 min; first
  query pays a cold-start (~500ms–2s). Ensure `pool_pre_ping=True` (already
  default in `db/session.py`) and generous job timeouts.
- **Corruption / bad migration:**
  1. Stop collectors (disable workflow temporarily).
  2. `alembic current` / `alembic history` — identify state.
  3. If a migration broke: `alembic downgrade -1`, fix, re-upgrade. Never
     hand-edit rows to "match" a migration.
  4. If data lost/corrupted: restore latest `pg_dump` or Neon PITR branch:
     create branch at timestamp → verify with `final-trades coverage-report`
     against the branch DSN → promote (point DATABASE_URL at restored
     project/branch).
  5. Re-enable workflows; next scheduled run resumes backlog automatically.

## Verification after recovery

1. `final-trades migrate` idempotent success.
2. `final-trades coverage-report` matches pre-incident numbers (±1 run).
3. Dashboard Overview shows a fresh successful run within one schedule cycle.
4. Spot-check three random recommendations retain evidence rows.

## Prevention

- Weekly pg_dump (operations.md) — rehearse restore quarterly on a branch.
- Never run the API with the collector (read-write) role.
- Migrations must be reversible; CI applies them on every PR (docker job).
