# data-model.md — Schema Reference

SQLAlchemy 2.0 models in `src/final_trades/db/models.py`; migrations in
`src/final_trades/migrations/`. Conventions: integer surrogate PKs, natural
keys via unique constraints, snake_case plural tables, UTC-aware timestamps,
String columns for enum values (SQLite/Postgres portability — values defined
once in `src/final_trades/domain.py`).

## Entity relationship sketch

```
shows 1──* segments 1──* recommendations *──1 analysts
                              │  *──1 instruments
                              │
                              ├──* recommendation_sources *──1 sources   (append-only evidence)
                              └──* performance_observations              (recomputable)

ingestion_runs 1──* source_run_results
      │1──* date_processing_status.last_run_id
      └─1──* issues.last_run_id

date_processing_status (show, date) — the durable backlog queue
coverage_daily (show, date)         — materialized aggregates for the UI
```

## Tables

### shows
Static: `halftime_report`, `fast_money` (seeded). key (uq), name, description, active.

### segments
One show's Final Trade(s) segment on one date. **uq(show_id, segment_date)**,
idx(segment_date). title nullable (best-known source title).

### analysts
canonical_name (uq) + `name_variants` JSON (raw spellings observed) +
affiliation + notes. Special row `(unattributed)` keeps
recommendations.analyst_id NOT NULL so the dedupe key is total.

### instruments
symbol (uq), asset_type (equity/etf/index/fixed_income/commodity/crypto/
option/other), name, is_delisted, `symbol_changes` JSON for renames.
Weak asset_type ('other') upgrades to strong typing on better evidence,
never downgrades.

### recommendations
The normalized call. **uq(segment_id, analyst_id, instrument_id, direction)**
= the idempotency key. direction (long/short/neutral/mention), position_type,
thesis (verbatim source sentence), confidence, verification_status
(unverified < verified < corroborated; unresolved on conflict — lattice in
`pipeline/normalize.py`), extraction_method, review_notes (conflict text),
published_at, created/updated. idx: instrument, analyst, verification_status.

### sources
Registry: benzinga_halftime_topic, benzinga_fast_money_topic,
benzinga_article, cnbc_rss_fast_money, cnbc_video_page (seeded).

### recommendation_sources (evidence — APPEND ONLY)
**uq(recommendation_id, source_id, url, content_sha256)** → re-ingesting the
same page adds nothing; a second source adds corroboration. url, retrieved_at,
published_at, content_sha256, excerpt (≤600 chars, attributed fair-use),
excerpt_kind (body/title/summary/feed_item). idx(recommendation_id).

### ingestion_runs
trigger (scheduled/backfill/manual), status (RUNNING/SUCCESS/PARTIAL_SUCCESS/
FAILED), window_start/end (dates), started/finished_at, duration_seconds,
discovered/created/updated/rejected/unresolved/error counts,
backlog_remaining, summary (includes per-show `halftime_report=x/y
fast_money=x/y` so one show's success never hides the other's failure).
idx(started_at).

### source_run_results
Per (run, source_key): status (SUCCESS/PARTIAL/FAILED/SKIPPED),
items_discovered/processed, error_category, error_summary (sanitized),
detail JSON (safe diagnostics only). show_key when source is show-specific.

### date_processing_status — the durable backlog
**uq(show_id, processing_date)**. status: PENDING (never attempted) /
PROCESSING / COLLECTED / NO_SEGMENT (verified non-trading day) / FAILED
(attempt failed; retried by later runs) / UNRESOLVED (partial/ambiguous or
segment without attribution source). is_trading_day, attempts,
first/last_attempted_at, last_run_id, segment_id, note (human-readable
reason, e.g. "No Fast Money item discovered for this date").
idx(status, processing_date) drives backlog selection.

### issues — failure observability
**uq(fingerprint)** where fingerprint = sha1(category|source|show|date|stage)
— or sha1(category|source|show|url_sha1|stage) for article-fetch failures
(URL-keyed so recovery is per-article). error_category, stage, summary
(sanitized, ≤2000 chars), detail JSON (never secrets), first/last_occurred_at,
occurrence_count, attempt_count, last_run_id, resolved + resolved_at
(recovery history preserved — resolution doesn't delete).
idx(resolved, last_occurred_at).

### coverage_daily
Materialized per (show, date): status (COMPLETE/PARTIAL/VERIFIED_ABSENT/
MISSING/UNCHECKED), recommendations_count, sources_ok/failed,
last_checked_at. Keeps the Coverage tab fast; recomputable from the tables
above.

### performance_observations
**uq(recommendation_id, horizon_days, price_provider)** — recompute overwrites
its own rows, never touches recommendation evidence. horizon_days ∈ {1,5,20,
60}; status OK/NOT_DUE/MISSING_ENTRY/MISSING_EXIT/INSTRUMENT_UNSUPPORTED;
entry_date/price/basis (same_day_close|next_close), exit_date/price,
forward_return, benchmark_symbol/entry/exit/return, relative_return,
price_provider, computed_at. All prices stored = reproducible audit trail.

## Index rationale (dashboard queries)

| Query pattern | Index |
|---|---|
| Recommendations grid (newest first) | segments(segment_date) + recs FK joins |
| Filter by ticker / analyst | idx_recommendations_instrument / _analyst |
| Filter by verification | idx_recommendations_verification |
| Runs grid | idx_runs_started_at |
| Run detail date table | date_processing_status.last_run_id (seq ok; per-run rows few) |
| Backlog selection | idx_datestatus_status_date |
| Issue list (open first) | idx_issues_unresolved |
| Coverage by month | idx_coverage_date |

## Invariants enforced in code

1. Evidence is append-only; no update/delete paths exist for
   recommendation_sources.
2. Recommendations mutate only via `pipeline/persist.py` upserts.
3. Analyst FK never NULL (placeholder row).
4. Verification never downgrades except into `unresolved` (conflicts).
5. date_processing_status never regresses COLLECTED → other status.
6. Issues preserve first_occurred_at across bumps; resolution is a flag, not
   a deletion.
7. Performance recompute is idempotent per (rec, horizon, provider).
