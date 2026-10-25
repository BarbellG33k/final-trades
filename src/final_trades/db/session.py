"""Database session/engine management and structured logging setup."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from final_trades.config import Settings, get_settings

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def _sanitize_url(url: str) -> str:
    """Strip credentials from a database URL for safe logging."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url


def get_engine(settings: Settings | None = None) -> Engine:
    """Create (once) and return the application engine."""
    global _engine, _sessionmaker
    if _engine is None:
        cfg = settings or get_settings()
        connect_args: dict[str, Any] = {}
        if cfg.is_sqlite:
            connect_args["timeout"] = 30
            _engine = create_engine(cfg.database_url, connect_args=connect_args, future=True)

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_connection: Any, _record: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()
        else:
            _engine = create_engine(
                cfg.database_url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=5,
                connect_args={"options": f"-c statement_timeout={cfg.db_query_timeout_ms}"},
                future=True,
            )
        _sessionmaker = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_session() -> Session:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed session: commit on success, rollback on error."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Dispose engine/sessionmaker (used by tests to switch databases)."""
    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None


class JsonFormatter(logging.Formatter):
    """Minimal structured JSON log formatter (level, msg, ts, service)."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "ts": datetime.now(UTC).isoformat(),
            "service": self.service,
            "logger": record.name,
        }
        if record.exc_info and record.exc_info[0] is not None:
            # Sanitized: exception type + message only, never env/stack details
            # beyond what the standard formatter would include for operators.
            payload["error_type"] = record.exc_info[0].__name__
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, default=str)


def setup_logging(settings: Settings | None = None, service: str = "final-trades") -> None:
    cfg = settings or get_settings()
    handler = logging.StreamHandler(sys.stdout)
    if cfg.log_json:
        handler.setFormatter(JsonFormatter(service))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(cfg.log_level)
    # Third-party noise reduction
    for noisy in ("httpx", "httpcore", "urllib3", "yfinance", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


__all__ = [
    "Engine",
    "Session",
    "_sanitize_url",
    "get_engine",
    "get_logger",
    "get_session",
    "reset_engine",
    "session_scope",
    "setup_logging",
]
