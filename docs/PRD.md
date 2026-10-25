# PRD.md — Product Requirements

## 1. Target users & use cases

- **Retail investors / market watchers** — browse what TV traders picked,
  filter by ticker/analyst/date, see what happened next.
- **Researchers / journalists** — export-quality historical dataset with
  provenance (source URL, excerpt, retrieval time) for analysis.
- **Operators / maintainers** — understand collection health at a glance:
  runs, failures, backlog, coverage; no manual intervention available by
  design.

Primary use cases: (a) "What were yesterday's final trades?" (b) "Every NVDA
mention in the last year, with sources." (c) "Why is data missing for
date X?" (d) "How did analyst picks perform over 20 days?" (e) "Is the
collector healthy?"

## 2. Public dashboard requirements

- Single-pane-of-glass, information-dense, read-only; tabs: **Overview,
  Runs, Recommendations, Historical Data, Analysts, Performance, Data
  Coverage** (all seven shipped).
- Overview: last successful collection, latest run status/start/finish/
  duration, discovered/created/updated/rejected counts, success rate over
  trailing 14 days, recent failures, current backlog size, missing/unresolved
  segments per show, newest recommendations, links to details. **Both shows
  displayed independently.**
- Runs: sortable/filterable grid (id, window, start, end, duration, overall +
  per-show status, counts, errors, summary), paginated server-side; row →
  run detail.
- Run detail: status/timestamps, date range, per-source outcomes, counts,
  extracted recommendations (analyst/ticker/direction/notes), evidence links,
  normalization decisions, errors with category+stage, dates processed/
  deferred, remaining backlog. Partial success visually distinct from success
  and failure.
- Recommendations: filters for date range, show, analyst, ticker, asset type,
  direction, verification status, extraction method; source links; detail
  view with full evidence + unresolved ambiguities.
- Historical Data: full-window exploration; date-range + show filters;
  verified absence vs unchecked vs failed retrieval clearly distinguished.
- Analysts: counts, show distribution, top instruments, performance when
  sample ≥ 30 observations (else "insufficient data"), attribution
  confidence. No reliability rankings without methodology.
- Performance: forward returns (1/5/20/60 td) vs SPY, methodology statement,
  sample sizes, missing-price counts, limitations, not-investment-advice
  disclaimer.
- Data Coverage: by show × date, verified/partial/missing/failed, last
  successful check per source, backlog size, trend over time.

## 3. Interface design principles

Maximize horizontal density; compact rows over cards; consistent type/space
system; sticky headers; expandable details; persistent URL-synced filters;
loading/empty/stale/error states everywhere; keyboard navigable, WCAG AA
contrast; responsive to mobile (graceful column hiding); **no full-dataset
client download** — server-side filtering/sorting/pagination with response
caps; dashboard fully usable when the latest run failed.

## 4. Background processing requirements

- Collect both shows daily; idempotent; resumable; independent of dashboard
  availability.
- Record per recommendation: show, segment date, analyst, ticker/instrument,
  direction, position type, thesis/notes, source URL, evidence excerpt,
  publication + retrieval timestamps, extraction method, confidence,
  verification status.
- Bounded attempt per source/date unit; commits per date so partial progress
  survives later failures.

## 5. Error visibility & recovery behavior (deliberate constraints)

- **No** manual rerun/retry controls in UI; **no** public collection
  endpoints; **no** intra-run retry loops; **no** unbounded backfill loops.
- Failures persisted with: error category, source, processing date, stage,
  human-readable summary, safe diagnostics (never secrets), first/last
  occurrence, attempt count across scheduled runs, last attempted run,
  unresolved flag.
- Next scheduled run recovers: current window first (reserved capacity),
  then oldest-first unresolved dates within quota. Failed dates are never
  permanently abandoned while inside the retention window.
- Run statuses: RUNNING / SUCCESS / PARTIAL_SUCCESS / FAILED; per-source and
  per-date statuses separate; execution status ≠ data completeness.

## 6. Historical research requirements

Window 2025-10-25 → 2026-10-25 inclusive. Operator-only backfill CLI.
Coverage report at end of backfill: per show, per month — collected,
no-segment (non-trading), unresolved, failed. Source validation gate before
reliance (≥10 sampled dates/show across quarters).

## 7. Data provenance & quality

Every recommendation → ≥1 source (URL, retrieved_at, sha256, excerpt).
Conflicts → `unresolved`, both readings stored. No fabrication, ever.
Extraction method recorded (`benzinga_article`, `cnbc_rss`, etc.).

## 8. Performance analytics requirements

Independent of collection/rendering. 1/5/20/60 trading-day forward returns;
entry convention: published ≥16:00 ET → next trading day close, else
same-day close; benchmark-relative (SPY); shorts separate; no underlying-
substitution for derivatives; prices + timestamps persisted per
observation; missing data reported honestly.

## 9. Hosting & cost requirements

$0/month target, <$3 ceiling; no always-on compute unless justified; no paid
LLM/transcription/market-data dependency; portable (Docker + standard SQL);
no unapproved provisioning; collector runnable locally and in Docker.

## 10. Nonfunctional requirements

- Public API p95 < 300 ms on cached summaries, < 1 s on filtered grids.
- Rate limited (~1 rps/IP, burst 30); pagination max 100; query timeouts.
- ≥90% test coverage on pipeline/API logic; CI green on main.
- Accessible (keyboard, contrast); mobile-usable; no secrets in responses/logs.

## 11. MVP vs deferred

**MVP:** everything above. **Deferred:** user accounts/alerts, exports
(CSV/API bulk), intraday data, additional shows, non-US instruments,
LLM-assisted extraction, Wayback-based deep backfill beyond 12 months,
benchmark other than SPY, notification webhooks.

## 12. Measurable acceptance criteria

1. Two consecutive `collect` runs on fixtures: second creates 0 duplicates.
2. Kill a source mid-run → run = PARTIAL_SUCCESS or FAILED, committed dates
   persist, next run retries the unresolved dates (integration test).
3. Backfill over window completes resumably after interruption (test).
4. All 7 tabs render with fixture-seeded data; grids paginate server-side
   (≤100 rows/response; verified in API tests).
5. No route outside GET exists on the public API (automated audit test).
6. Rate limit + error sanitization verified by tests (no stack traces, no
   env values).
7. Performance job computes horizons on fixture prices; missing prices leave
   explicit gaps.
8. Cost model documents $0 path with date-checked sources.
9. `docs/STATUS.md` handoff complete; README accurate.
