"""Price providers (port + adapters).

D-007: yfinance is the default keyless provider; Tiingo is optional with a
free API key (higher-quality CRSP-adjusted data); both normalize to PriceBar.
FRED serves index-level context only (not wired into return math).
Tests inject FakeProvider — CI never touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from final_trades.config import Settings
from final_trades.db.session import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PriceBar:
    day: date
    close: float
    adj_close: float  # dividend/split adjusted — used for all return math


@dataclass(frozen=True)
class PriceFetchFailure:
    symbol: str
    reason: str


PriceHistory = list[PriceBar] | PriceFetchFailure


class PriceProvider(Protocol):
    name: str

    def daily_history(self, symbol: str, start: date, end: date) -> PriceHistory: ...


class YFinanceProvider:
    """Yahoo Finance via the yfinance library (keyless, adjusted closes)."""

    name = "yfinance"

    def daily_history(self, symbol: str, start: date, end: date) -> PriceHistory:
        try:
            import warnings

            import yfinance as yf

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = yf.download(
                    symbol,
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                )
        except Exception as exc:
            logger.warning(
                "yfinance fetch failed",
                extra={"fields": {"symbol": symbol, "error_type": type(exc).__name__}},
            )
            return PriceFetchFailure(symbol, f"provider error: {type(exc).__name__}")
        if df is None or df.empty:
            return PriceFetchFailure(symbol, "empty history")
        bars: list[PriceBar] = []
        try:
            # yfinance >=0.2.5x returns MultiIndex columns (field, ticker)
            # even for single-symbol downloads — flatten to plain fields.
            try:
                import pandas as pd

                if isinstance(df.columns, pd.MultiIndex):
                    df = df.copy()
                    df.columns = df.columns.get_level_values(0)
            except ImportError:  # pragma: no cover - pandas is a hard dep
                pass
            close = _flatten(df["Close"])
            adj = _flatten(df["Adj Close"]) if "Adj Close" in df else close
            for idx in df.index:
                day = idx.date()
                c = close.get(day)
                a = adj.get(day, c)
                if c is not None and a is not None:
                    bars.append(PriceBar(day=day, close=float(c), adj_close=float(a)))
        except (KeyError, TypeError, ValueError) as exc:
            return PriceFetchFailure(symbol, f"malformed frame: {type(exc).__name__}")
        return sorted(bars, key=lambda b: b.day)


class TiingoProvider:
    """Tiingo EOD REST (free key; CRSP-method adjusted closes)."""

    name = "tiingo"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def daily_history(self, symbol: str, start: date, end: date) -> PriceHistory:
        import httpx

        url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
        params = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "format": "json",
        }
        try:
            resp = httpx.get(
                url,
                params=params,
                headers={"Authorization": f"Token {self._api_key}"},
                timeout=30,
            )
        except httpx.HTTPError as exc:
            return PriceFetchFailure(symbol, f"transport error: {type(exc).__name__}")
        if resp.status_code == 404:
            return PriceFetchFailure(symbol, "symbol not found")
        if resp.status_code == 429:
            return PriceFetchFailure(symbol, "rate limited")
        if resp.status_code >= 400:
            return PriceFetchFailure(symbol, f"HTTP {resp.status_code}")
        try:
            rows = resp.json()
        except ValueError:
            return PriceFetchFailure(symbol, "invalid JSON")
        bars: list[PriceBar] = []
        for row in rows:
            try:
                day = date.fromisoformat(str(row["date"])[:10])
                close = float(row["close"])
                adj = float(row.get("adjClose", close))
            except (KeyError, TypeError, ValueError):
                continue
            bars.append(PriceBar(day=day, close=close, adj_close=adj))
        return sorted(bars, key=lambda b: b.day)


def make_provider(settings: Settings) -> PriceProvider:
    if settings.market_data_provider == "tiingo" and settings.tiingo_api_key:
        return TiingoProvider(settings.tiingo_api_key)
    return YFinanceProvider()


def _flatten(series: object) -> dict[date, float]:
    """Collapse a possibly-MultiIndex yfinance column to {date: value}."""
    out: dict[date, float] = {}
    items = getattr(series, "items", None)
    if not callable(items):
        return out
    for idx, value in items():
        try:
            day = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        except (AttributeError, ValueError):
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if v == v:  # skip NaN
            out[day] = v
    return out
