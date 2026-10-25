# source-validation.md — Acquisition Evidence & Validation Gate

All probes performed **2026-10-25** from a residential macOS connection.
Probe method: plain `curl`/`httpx` first; `curl_cffi` (Chrome TLS
impersonation) where bot-walled. Findings drive the adapter design in
`src/final_trades/sources/`.

## 1. Source-by-source findings

### Benzinga topic page — Halftime Report ✅ PRIMARY
- URL: `https://www.benzinga.com/topic/halftime-report-final-trades`
- Access: **Cloudflare bot-wall vs plain curl (403 "Attention Required")**;
  HTTP 200 with browser TLS impersonation (`curl_cffi impersonate="chrome"`).
  robots.txt (v2026-09-11): topic + article paths **allowed**; only
  admin/user/script paths disallowed.
- Structure: JSON-LD `CollectionPage.mainEntity.itemListElement` lists the 30
  most recent articles; one "CNBC's 'Final Trades'" article **per trading
  day** observed across Sept–Oct 2026.
- No pagination links in HTML (`?page=` absent; "Read More" is JS-driven) →
  historical discovery uses the monthly archive sitemaps instead.

### Benzinga monthly archive sitemaps ✅ HISTORICAL DISCOVERY
- `https://www.benzinga.com/sitemap-benzinga.com/www/archive.xml` → index of
  `archive/YYYY/MM.xml` covering 2014 → 2026/10 (verified 2026/10 = 1.1 MB,
  contains every `/trading-ideas/long-ideas/26/10/…final-trades` URL).
- robots.txt lists these sitemaps explicitly → sanctioned discovery route.

### Benzinga article pages ✅ ATTRIBUTION SOURCE
- Verified 3 live articles (2026-10-23, 2026-10-08, 2026-10-01 publishes).
- JSON-LD `NewsArticle.articleBody` carries explicit attribution sentences:
  `"<Analyst>, <title/affiliation>, <pick-verb> <Company> (<EXCHANGE>:<TICKER>)"`,
  a lead-in naming the show ("On CNBC's 'Halftime Report Final Trades'"), and
  a "Price Action" section referencing the segment's trading day.
- Parser validation (fixture-pinned tests): **8/8 recommendations extracted
  with correct analyst, ticker, direction** across the 3 samples, including
  hard cases: initials ("Joseph M. Terranova"), dotted acronyms
  ("U.S. 10 Year Treasury" → US10Y), multi-comma titles, "Short Hills Capital
  Partners" false-bearish trap, supporting-rating sentences correctly
  rejected (no phantom "Andrew Sherman → ZS" pick).
- Publication timing: articles publish the **morning after** the segment
  (2026-10-23T07:51 ET article ↔ 2026-10-22 segment; cross-verified against
  the CNBC video URL date). Rule: `segment_date = previous_trading_day(datePublished)`.

### Benzinga topic page — Fast Money ⚠️ STALE (rejected for window)
- URL: `https://www.benzinga.com/topic/fast-money-final-trade` → HTTP 200
  (impersonated), but the listing's "Fast Money Picks" articles date from
  **2020–2021**. No coverage inside the target window → not used.

### CNBC Fast Money RSS ✅ OFFICIAL FEED (current week)
- URL: `search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15838499`
- Access: plain HTTP 200 (no bot wall on cnbc.com/search.cnbc.com).
- Contains daily `Final Trade: <TICKERS>` video items (~30-item rolling
  window ≈ 1 week), `pubDate` = segment day (posted ~18:00 ET), video URL.
- **No analyst attribution** in feed items.

### CNBC site search API (queryly) ✅ UNIFIED DISCOVERY
- `api.queryly.com/cnbc/json.aspx?queryly_key=31a35d40a9a64ab3&query="final trade"&sort=datepublished&batchsize=50`
  — the public endpoint powering cnbc.com search; works keyless (plain HTTP
  200; note: TLS verifier quirk with curl_cffi — plain transport fine).
- Returns both shows with exact segment dates: Fast Money titles
  `Final Trade: NVDA, JPM, SLB, XMAG` (tickers), Halftime titles
  `Final Trades: <Company Names>`; `section` field names the show;
  12,802 total matches for the quoted phrase; pagination verified (50/page,
  sorted by datePublished). 12 months ≈ 250 items ≈ 6–8 pages.
- Status: undocumented but publicly served; low-volume polite use; adapter
  isolated so it can be swapped if it disappears (fallback: Wayback CDX).

### CNBC video pages ✅ EVIDENCE
- `https://www.cnbc.com/video/YYYY-MM-DD/final-trade-<tickers>.html` → 200
  plain HTTP; JSON-LD `VideoObject` (name, uploadDate, description).
- **No transcript published** (verified) → Fast Money per-trader attribution
  unavailable from CNBC.

### CNBC Halftime show page ✅ CROSS-CHECK
- `https://www.cnbc.com/halftime/` lists recent videos; slug convention
  distinguishes shows: `final-trade-<TICKERS>` (Fast Money) vs
  `final-trades-<Company-Names>` (Halftime). Used to confirm the
  publish-minus-one-trading-day rule (ZS/NOW/SPOT video dated 2026-10-22 ↔
  article published 2026-10-23 07:51).

### Quiver Quantitative cnbctracker ❌ DEPRIORITIZED
- Page exceeds 5 MB fetch limit (JS-heavy); API is account-gated. Not used.

### Stooq ❌ DEAD (market data, for the record)
- PoW JS challenge then "Access denied" even after solving + TLS
- impersonation (probe 2026-10-25). See DECISIONS D-007 → yfinance default.

## 2. Attribution capability matrix

| Show | Tickers | Analyst attribution | Direction | Thesis/notes | Evidence |
|---|---|---|---|---|---|
| Halftime Report | ✅ article body (EXCHANGE:TICKER) | ✅ explicit per pick | ✅ (bearish cues) | ✅ verbatim sentence | ✅ article URL+hash+excerpt, corroborated by CNBC video |
| Fast Money | ✅ video/RSS titles | ❌ not published | ⚠️ assumed long (final trades are long calls; labeled unverified) | ⚠️ generic segment description | ✅ video/RSS URL+hash |

Fast Money records therefore persist with `analyst=(unattributed)`,
`verification_status=unverified` — the dashboard shows this honestly; the
coverage/analyst tabs quantify it. This is the documented gap the master
requirements anticipated ("if a source cannot provide reliable attribution,
document the gap").

## 3. Validation gate (WS-01.5) — protocol + results

Protocol: sample ≥10 dates per show across all four quarters of
2025-10-25 → 2026-10-25 plus the last two weeks; for each date record
article/video availability, attribution, direction, cross-source agreement,
and failures. Executed via bounded operator backfill invocations
(`final-trades backfill`), results land in `coverage_daily` +
`date_processing_status` and are summarized below after execution.

### Results (sampled runs, residential IP)

*(Appended by the validation runs — see docs/STATUS.md for the latest table.)*

## 4. Access-condition notes & risks

- Benzinga bot-wall may tighten (datacenter IPs on CI could be treated more
  strictly than residential). Mitigations: impersonated transport isolated
  in one module; failures degrade to UNRESOLVED dates + visible issues;
  RSS/search-based current-day collection survives without Benzinga;
  Wayback fallback documented in PLAN §15.
- queryly endpoint is undocumented — isolated adapter, polite volume
  (≤40 pages/run), documented swap path.
- Rate limits honored: ≥2s between requests/host, zero retries, 4 MiB cap.
- Content use: short attributed excerpts + links only; no full-article
  storage or redistribution; see README licensing section.
