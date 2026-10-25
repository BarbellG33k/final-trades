# Runbook: source blocked or degraded

**Symptoms:** repeated `blocked` (HTTP 403/CAPTCHA) or `rate_limited`
issues for one source; coverage MISSING share rising for a show.

## Benzinga blocked

1. Confirm scope: is it all Benzinga fetches or only from CI/datacenter IPs?
   Run `final-trades collect --once` locally (residential IP) and compare.
2. If datacenter-only: options in order —
   a. Wait it out (self-healing design keeps dates UNRESOLVED, visible).
   b. Route collector egress via a residential-friendly path you control
      (documented config change, no third-party scraping services without
      maintainer approval — terms/legal review required).
   c. Switch Halftime discovery to Wayback Machine snapshots of the topic
      page + articles (`web.archive.org/cdx` API) — slower, complete,
      legal; mark records `extraction_method` accordingly and note snapshot
      retrieval dates in evidence.
3. If markup challenge changed (PoW/captcha even on residential): treat as
   source lost; current-day Halftime degrades to CNBC video evidence
   (segment existence + company names, no attribution → UNRESOLVED with
   note). Update `docs/source-validation.md` and PLAN risk table.

## CNBC (RSS/search/video) degraded

- RSS: static, stable; if gone, rely on queryly search alone (already the
  discovery primary).
- queryly search: undocumented endpoint. If blocked/changed: fall back to
  RSS (current week) + per-date video URL construction is impossible (slugs
  unknown) → historical FM discovery degrades to Wayback CDX of
  `cnbc.com/video/*/final-trade-*`. Document coverage impact.

## Quiver/other third parties

Never added without: robots/terms review, rate-limit plan, and a recorded
decision in `docs/DECISIONS.md`.

## Post-incident

1. Record findings in `docs/source-validation.md` (dated).
2. If adapter changed: refresh fixtures, add regression test reproducing
   the block/parse condition.
3. Issues resolve automatically when the source recovers and dates are
   re-collected — verify `resolved=true` and note the recovery window in
   STATUS if it was user-visible.
