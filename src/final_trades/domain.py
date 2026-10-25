"""Domain vocabulary: enums and constants shared across modules.

Single source of truth for status values, direction, verification levels,
error categories, and pipeline stages. String-backed enums keep the schema
portable across SQLite and Postgres (no native ENUM types).
"""

from __future__ import annotations

from enum import StrEnum


class ShowKey(StrEnum):
    """The two collected shows."""

    HALFTIME_REPORT = "halftime_report"
    FAST_MONEY = "fast_money"


class SourceKey(StrEnum):
    """Registered acquisition sources."""

    BENZINGA_HALFTIME_TOPIC = "benzinga_halftime_topic"
    BENZINGA_FAST_MONEY_TOPIC = "benzinga_fast_money_topic"
    BENZINGA_ARTICLE = "benzinga_article"
    CNBC_RSS_FAST_MONEY = "cnbc_rss_fast_money"
    CNBC_VIDEO_PAGE = "cnbc_video_page"


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    BACKFILL = "backfill"
    MANUAL = "manual"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class SourceRunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class DateStatus(StrEnum):
    """Per-(show, date) processing state. Execution state, not completeness."""

    PENDING = "PENDING"  # never attempted (in-window, eligible)
    PROCESSING = "PROCESSING"  # attempt in flight
    COLLECTED = "COLLECTED"  # segment found and recommendations persisted
    NO_SEGMENT = "NO_SEGMENT"  # verified absence (non-trading day or no show)
    FAILED = "FAILED"  # attempt failed; eligible for later scheduled runs
    UNRESOLVED = "UNRESOLVED"  # partially processed; ambiguity remains


class CoverageStatus(StrEnum):
    """Data completeness for coverage reporting (distinct from DateStatus)."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    VERIFIED_ABSENT = "VERIFIED_ABSENT"
    MISSING = "MISSING"  # failed retrieval or unresolved
    UNCHECKED = "UNCHECKED"


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"
    MENTION = "mention"  # named in segment without clear directional stance


class PositionType(StrEnum):
    STOCK = "stock"
    ETF = "etf"
    OPTION = "option"
    INDEX = "index"
    FIXED_INCOME = "fixed_income"
    COMMODITY = "commodity"
    CRYPTO = "crypto"
    INTERNATIONAL = "international_equity"
    UNKNOWN = "unknown"


class AssetType(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"
    FIXED_INCOME = "fixed_income"
    COMMODITY = "commodity"
    CRYPTO = "crypto"
    OPTION = "option"
    OTHER = "other"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"  # attribution evidenced by >=1 parsed source
    UNVERIFIED = "unverified"  # recorded from a source lacking attribution detail
    UNRESOLVED = "unresolved"  # ambiguous or conflicting attribution
    CORROBORATED = "corroborated"  # >=2 independent sources agree


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExtractionMethod(StrEnum):
    BENZINGA_ARTICLE = "benzinga_article"
    BENZINGA_LISTING_SUMMARY = "benzinga_listing_summary"
    CNBC_RSS_TITLE = "cnbc_rss_title"
    CNBC_VIDEO_PAGE = "cnbc_video_page"
    MANUAL = "manual"


class ErrorCategory(StrEnum):
    NETWORK = "network"  # timeout, DNS, connection reset
    HTTP_ERROR = "http_error"  # 4xx/5xx response
    RATE_LIMITED = "rate_limited"  # 429 or politeness backoff
    BLOCKED = "blocked"  # bot-wall / captcha / access denied
    PARSE = "parse"  # unexpected markup, missing expected structure
    ATTRIBUTION = "attribution"  # could not establish analyst↔ticker
    NOT_FOUND = "not_found"  # no article/segment for date
    VALIDATION = "validation"  # data failed schema/evidence checks
    DATABASE = "database"
    CONFIG = "config"
    UNKNOWN = "unknown"


class Stage(StrEnum):
    DISCOVER = "discover"
    FETCH = "fetch"
    PARSE = "parse"
    NORMALIZE = "normalize"
    PERSIST = "persist"
    PERFORMANCE = "performance"


class PerformanceStatus(StrEnum):
    OK = "OK"
    NOT_DUE = "NOT_DUE"  # horizon end date not reached yet
    MISSING_ENTRY = "MISSING_ENTRY"
    MISSING_EXIT = "MISSING_EXIT"
    INSTRUMENT_UNSUPPORTED = "INSTRUMENT_UNSUPPORTED"  # e.g. delisted, no price feed


# Canonical placeholder analyst so recommendations.analyst_id is never NULL
# (keeps the uniqueness/dedupe key total; shown as "(unattributed)" in UI).
UNATTRIBUTED_ANALYST_NAME = "(unattributed)"

# Forward-return horizons in trading days.
PERFORMANCE_HORIZONS: tuple[int, ...] = (1, 5, 20, 60)

# Max stored evidence excerpt length (characters) — short attributed quotes.
MAX_EXCERPT_LENGTH = 600

# Historical window (inclusive) per product requirements.
BACKFILL_WINDOW_START = "2025-10-25"
BACKFILL_WINDOW_END = "2026-10-25"
