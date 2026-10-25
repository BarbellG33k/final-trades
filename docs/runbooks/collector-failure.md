# Runbook: collector failing / backlog growing

**Symptoms:** latest run FAILED or repeatedly PARTIAL_SUCCESS; per-show
`last_collected_date` stale >3 trading days; backlog growing across runs.

## Triage (10 min)

1. Dashboard → Overview → Recent failures: note error categories
   (`network`/`blocked`/`http_error`/`parse`) and which show/source.
2. Dashboard → Runs → latest run detail: which sources FAILED, which dates.
3. GH Actions → Collector workflow → latest run logs: JSON log lines with
   `error_type`.

## By category

- **`blocked` on benzinga_article / benzinga_halftime_topic** → bot-wall
  tightened or datacenter-IP policy. See `source-blocked.md`.
- **`network`/`http_error` sporadic** → transient; system self-heals on next
  run. Act only if the SAME source fails ≥5 consecutive runs.
- **`parse` on benzinga_article** → markup/JSON-LD changed:
  1. `final-trades fetch-fixtures --source benzinga_halftime`
  2. Diff new article JSON-LD vs `tests/fixtures/benzinga_article_*.json`.
  3. Update `sources/benzinga.py` patterns; pin with the new fixture; add a
     test reproducing the failure; deploy.
- **`parse` on cnbc search/RSS** → same procedure against
  `sources/cnbc.py` + `tests/fixtures/cnbc_*`.
- **DB errors (`database`)** → `database-recovery.md`.
- **Cron never fires** → repo inactive >60 days auto-disables scheduled
  workflows (re-enable on the Actions tab); or GitHub load dropped the run —
  next cron recovers automatically; if persistent, switch to the Cloud Run
  Jobs + Scheduler option (`deploy/cloud-run/README.md`).

## Verification after fix

1. `workflow_dispatch` → mode `collect` once (operator action; not a public
   feature).
2. Confirm run status improves and previously FAILED dates flip to
   COLLECTED/UNRESOLVED with issue `resolved=true`.
3. Watch the next two scheduled runs stay green.

## What NOT to do

- Do not add retry loops or manual-trigger endpoints "to fix it faster" —
  the bounded cross-run recovery is a deliberate product invariant
  (AGENTS.md failure semantics).
- Do not raise rate limits above politeness floors to clear backlog faster;
  sustained 2s/request is what keeps sources accessible.
