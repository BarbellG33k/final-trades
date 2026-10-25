# testing.md — Test Strategy & Scenario Map

## Layout & commands

```
tests/unit/          # parsers, http policy, calendar, normalize/persist, repos, CLI, performance
tests/integration/   # pipeline scenarios + API (fixture-backed, in-memory SQLite)
tests/fixtures/      # recorded/trimmed live snapshots (68KB) — CI never hits the network
tests/helpers/       # shared env builder, fake transports, fixture loaders
web/src/test/        # vitest + React Testing Library (components, pages, api client)
```

| Suite | Command | Network |
|---|---|---|
| Python unit+integration | `uv run pytest tests -q --cov` | none |
| Live-network checks (manual only) | `uv run pytest -m live` | yes — excluded from CI |
| Frontend | `cd web && npx vitest run` | none (fetch mocked) |
| Full-stack container e2e | CI `docker` job: build image → boot → `/healthz` + `/api/v1/overview` over real HTTP | none external |

Coverage floor: 90% line (enforced by pytest `--cov` fail_under). Current:
~92% backend. Lint (`ruff`), strict types (`mypy --strict`), format check,
pip-audit, npm audit, TruffleHog, license audit run in CI on every push/PR.

## Critical scenario map (master requirements §13)

| # | Scenario | Test(s) |
|---|---|---|
| 1 | Successful collection both shows | `test_scheduled_run_collects_both_shows`, `test_fast_money_records_are_unverified_unattributed`, `test_halftime_records_are_attributed_and_verified` |
| 2 | One show succeeds, other fails | `test_partial_success_when_one_show_fails`, `test_run_summary_separates_shows`, `test_overview_exposes_failures_and_per_show_status` |
| 3 | Source fails for historical date | `test_next_scheduled_run_recovers_failed_article` (phase 1), `test_failed_article_does_not_block_others` |
| 4 | Next scheduled run processes unresolved date | `test_next_scheduled_run_recovers_failed_article` (phase 2: COLLECTED + issue resolved) |
| 5 | Failed record doesn't block later records | `test_failed_article_does_not_block_others`, per-unit commits in `test_abort_preserves_committed_records` |
| 6 | Same data ingested twice, no duplicates | `test_double_ingest_is_idempotent`, `test_create_and_second_ingest_updates_without_duplicates`, evidence dedupe in `test_evidence_dedupe_on_url_and_hash` |
| 7 | Multiple sources support one recommendation | `test_corroboration_from_two_sources`, `test_second_source_corroborates` |
| 8 | Conflicting attribution stays unresolved | `test_conflicting_direction_stays_unresolved`, `test_conflict_marks_both_unresolved` |
| 9 | Run fails after partial success, records kept | `test_abort_preserves_committed_records` |
| 10 | Dashboard displays failure + diagnostics | `test_overview_exposes_failures_and_per_show_status`, `test_runs_and_run_detail`, web `overview.test.tsx` |
| 11 | Public requests cannot trigger collection | `test_all_routes_are_read_only`, `test_no_collection_endpoints_exist` |
| 12 | Public API queries bounded | `test_pagination_caps_page_size`, `test_date_range_is_bounded`, `test_pagination_respects_limits_and_totals` |
| 13 | DB survives separate scheduled executions | `test_state_persists_across_collector_instances`, `test_next_scheduled_run_recovers_failed_article`; durable-volume compose in `deploy/docker-compose.yml`; CI docker smoke |
| 14 | Backup & restore work | `docs/operations.md` runbook (pg_dump/restore verified manually at deploy time — see STATUS limitations) |
| 15 | Performance handles missing prices + after-hours publication | `test_entry_convention_after_hours_publication_never_same_day`, `test_missing_prices_are_explicit`, `test_unpriceable_instrument_marked_unsupported`, `test_short_direction_kept_separate`, `test_adjusted_prices_used_for_returns` |
| 16 | Pagination doesn't download dataset | `test_pagination_respects_limits_and_totals` (page disjointness + ≤100 cap), server-side filtering in all list endpoints |
| 17 | Public errors leak nothing | `test_unhandled_errors_leak_nothing`, `test_404_envelope_is_generic`, `test_error_summaries_never_include_body`, `test_json_formatter_exception_sanitized` |
| 18 | Frontend usable when latest run failed | web `overview.test.tsx` ("renders a failed show visibly next to a healthy one") |

## Policy notes

- **Fixtures only in CI.** Live fixtures are refreshed with
  `final-trades fetch-fixtures` (bounded, rate-limited) and trimmed before
  committing (structure preserved, not full copyrighted content).
- **Deterministic clocks**: `today` is injected into `Collector` and
  `compute_all`; fake providers/transports receive injected sleep/clock.
- **Assertions on values**, not existence: exact tickers, dates, counts,
  statuses, and envelope shapes throughout.
- **Deviation (documented):** no headless-browser e2e (Playwright) in MVP —
  the CI docker job boots the real image and exercises real HTTP against
  migrations+API+SPA-serving; component/page tests cover rendering with a
  mocked API. Browser automation deferred until post-launch abuse/UX issues
  justify its CI weight. Tracked in PLAN ledger (WS-10.3 note).
