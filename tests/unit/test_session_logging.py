"""Unit tests for logging/session plumbing (no network, no real DB files)."""

from __future__ import annotations

import json
import logging

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from final_trades.config import Settings
from final_trades.db.session import (
    JsonFormatter,
    _sanitize_url,
    get_engine,
    reset_engine,
    session_scope,
    setup_logging,
)


def test_sanitize_url_strips_credentials() -> None:
    assert (
        _sanitize_url("postgresql+psycopg://user:secret@host:5432/db")
        == "postgresql+psycopg://***@host:5432/db"
    )
    assert _sanitize_url("sqlite:///data/x.db") == "sqlite:///data/x.db"


def test_json_formatter_required_fields() -> None:
    record = logging.LogRecord("svc.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    payload = json.loads(JsonFormatter("final-trades").format(record))
    assert payload["level"] == "info"
    assert payload["msg"] == "hello world"
    assert payload["service"] == "final-trades"
    assert "ts" in payload


def test_json_formatter_includes_fields_extra() -> None:
    record = logging.LogRecord("svc", logging.WARNING, __file__, 1, "warn", None, None)
    record.fields = {"run_id": 7}  # type: ignore[attr-defined]
    payload = json.loads(JsonFormatter("x").format(record))
    assert payload["run_id"] == 7


def test_json_formatter_exception_sanitized() -> None:
    try:
        raise ValueError("boom with SECRET=abc")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "svc", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    payload = json.loads(JsonFormatter("x").format(record))
    assert payload["error_type"] == "ValueError"
    assert "SECRET=abc" not in json.dumps(payload)


def test_setup_logging_sets_level_and_quiet_noisy() -> None:
    settings = Settings(DATABASE_URL="sqlite://", LOG_LEVEL="DEBUG", LOG_JSON="false")
    setup_logging(settings, service="test")
    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.WARNING


def test_session_scope_commits_and_rolls_back() -> None:
    reset_engine()
    settings = Settings(DATABASE_URL="sqlite://")
    engine = get_engine(settings)
    from final_trades.db import models

    models.Base.metadata.create_all(engine)
    from final_trades.db.seed import ensure_reference_data

    with session_scope() as s:
        ensure_reference_data(s)
        s.execute(text("SELECT 1"))
    # rollback path
    with pytest.raises(OperationalError), session_scope() as s:
        s.execute(text("SELECT * FROM nonexistent_table"))
    reset_engine()


def test_get_engine_singleton_and_sqlite_pragmas() -> None:
    reset_engine()
    settings = Settings(DATABASE_URL="sqlite://")
    e1 = get_engine(settings)
    e2 = get_engine(settings)
    assert e1 is e2
    with e1.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert str(mode).lower() == "wal" or str(mode).lower() == "memory"
    assert fk == 1
    reset_engine()
