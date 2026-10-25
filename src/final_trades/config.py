"""Application settings with fail-fast startup validation.

All configuration comes from environment variables (see .env.example).
Secrets are never logged — `Settings.summary()` renders them as presence only.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = Field(default="sqlite:///data/final_trades.sqlite3", alias="DATABASE_URL")

    # API server
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, alias="API_PORT")
    api_cors_origins: str = Field(default="http://localhost:5173", alias="API_CORS_ORIGINS")
    rate_limit_rps: float = Field(default=1.0, gt=0, alias="RATE_LIMIT_RPS")
    rate_limit_burst: int = Field(default=30, gt=0, alias="RATE_LIMIT_BURST")
    overview_cache_ttl_seconds: int = Field(default=60, ge=0, alias="OVERVIEW_CACHE_TTL_SECONDS")
    db_query_timeout_ms: int = Field(default=5000, gt=0, alias="DB_QUERY_TIMEOUT_MS")

    # Collector
    http_min_request_interval_seconds: float = Field(
        default=2.0, ge=0.5, alias="HTTP_MIN_REQUEST_INTERVAL_SECONDS"
    )
    http_timeout_seconds: float = Field(default=30.0, gt=0, alias="HTTP_TIMEOUT_SECONDS")
    http_user_agent: str = Field(
        default="final-trades-collector/0.1 (+https://github.com/final-trades/final-trades)",
        alias="HTTP_USER_AGENT",
    )
    backlog_max_dates_per_run: int = Field(default=40, gt=0, alias="BACKLOG_MAX_DATES_PER_RUN")
    current_day_capacity_share: float = Field(
        default=0.6, gt=0, le=1.0, alias="CURRENT_DAY_CAPACITY_SHARE"
    )
    backfill_start_date: date = Field(default=date(2025, 10, 25), alias="BACKFILL_START_DATE")
    backfill_end_date: date = Field(default=date(2026, 10, 25), alias="BACKFILL_END_DATE")

    # Market data
    market_data_provider: str = Field(default="yfinance", alias="MARKET_DATA_PROVIDER")
    tiingo_api_key: str | None = Field(default=None, alias="TIINGO_API_KEY")
    benchmark_symbol: str = Field(default="SPY", alias="BENCHMARK_SYMBOL")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=True, alias="LOG_JSON")

    # Frontend build location (set in containers; defaults to repo web/dist)
    web_dist_dir: str | None = Field(default=None, alias="WEB_DIST_DIR")

    @field_validator("market_data_provider")
    @classmethod
    def _check_provider(cls, v: str) -> str:
        allowed = {"yfinance", "tiingo"}
        if v not in allowed:
            raise ValueError(f"MARKET_DATA_PROVIDER must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return v.upper()

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, v: str) -> str:
        if not (v.startswith("sqlite") or v.startswith("postgresql")):
            raise ValueError("DATABASE_URL must be sqlite:///... or postgresql+psycopg://...")
        return v

    def model_post_init(self, __context: object) -> None:
        if self.backfill_start_date > self.backfill_end_date:
            raise ValueError("BACKFILL_START_DATE must be <= BACKFILL_END_DATE")
        if self.market_data_provider == "tiingo" and not self.tiingo_api_key:
            raise ValueError("MARKET_DATA_PROVIDER=tiingo requires TIINGO_API_KEY")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def summary(self) -> dict[str, object]:
        """Non-secret configuration summary for startup logs (secrets as presence)."""
        return {
            "database_url_scheme": self.database_url.split(":", 1)[0],
            "api_host": self.api_host,
            "api_port": self.api_port,
            "market_data_provider": self.market_data_provider,
            "tiingo_api_key": "set" if self.tiingo_api_key else "unset",
            "backlog_max_dates_per_run": self.backlog_max_dates_per_run,
            "current_day_capacity_share": self.current_day_capacity_share,
            "backfill_window": f"{self.backfill_start_date}..{self.backfill_end_date}",
            "log_level": self.log_level,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate settings once; raises on invalid configuration."""
    return Settings()
