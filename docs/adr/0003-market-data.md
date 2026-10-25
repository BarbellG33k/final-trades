# ADR-0003: Free market data — yfinance default, optional Tiingo

Date: 2026-10-25 · Status: accepted · Refs: DECISIONS D-007

## Context

Forward-return analytics need daily adjusted closes for US equities/ETFs
(13+ months), at $0, without requiring credentials to build/run/CI the
project. Live probes (2026-10-25): Stooq's keyless CSV is dead (PoW +
access denied); yfinance 1.7.0 works keyless (251-row 1y pulls, Adj Close
≠ Close → dividend+split adjusted); Tiingo's free key offers CRSP-method
adjusted OHLC + audit fields (1000 req/day); FRED keyless CSV works for
index levels; Finnhub has no free candles; Twelve Data free tier forbids
display use.

## Decision

Provider port (`performance/providers.py`) with:
- **Default: yfinance** (keyless; repo stays credential-free for CI).
- **Optional: Tiingo** via `TIINGO_API_KEY` when higher-quality adjusted
  data or yfinance outages matter.
- FRED documented for benchmark/rate context (not wired into return math).
- Dashboard displays **derived values only** (entry/exit prices used,
  returns, dates) with provider attribution — no bulk price tables or
  export, respecting Yahoo/Tiingo redistribution terms.
- `performance_observations` stores provider + timestamps + both legs'
  prices → reproducible and auditable per row.

## Consequences

- Zero-cost analytics with an upgrade path; provider swap is one env var.
- yfinance is unofficial — breakage risk accepted with Tiingo fallback and
  honest MISSING_* statuses rather than stale silent data.
- Entry-time logic uses collector publish timestamps (price feeds carry no
  clock), per D-009 conventions.

## Alternatives rejected

Stooq (dead); Alpha Vantage (25/day free, adjusted premium-gated; their
open-source unlimited program unverified); Polygon/Massive free (2-yr
history, 5 calls/min, individual-use terms — viable secondary, not needed);
paid providers (violates $0 constraint).
