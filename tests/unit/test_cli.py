"""CLI tests — DB-only commands run for real; network commands are monkeypatched."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from final_trades.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "cli_test.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("LOG_JSON", "false")
    from final_trades.config import get_settings
    from final_trades.db import session as db_session

    get_settings.cache_clear()
    db_session.reset_engine()
    yield
    get_settings.cache_clear()
    db_session.reset_engine()


def test_migrate_creates_schema_and_seeds() -> None:
    result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0, result.output
    assert "migrations applied" in result.output


def test_coverage_report_lists_both_shows() -> None:
    runner.invoke(app, ["migrate"])
    result = runner.invoke(app, ["coverage-report"])
    assert result.exit_code == 0, result.output
    assert "fast_money" in result.output
    assert "halftime_report" in result.output


def test_collect_uses_orchestrator_and_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    runner.invoke(app, ["migrate"])
    from final_trades.db.models import IngestionRun
    from final_trades.domain import RunStatus

    class FakeRun:
        id = 1
        status = str(RunStatus.PARTIAL_SUCCESS)
        summary = "units=1 collected=1 failed=0"

    def fake_run_scheduled(self):
        return FakeRun()

    monkeypatch.setattr(
        "final_trades.pipeline.orchestrator.Collector.run_scheduled", fake_run_scheduled
    )
    result = runner.invoke(app, ["collect"])
    assert result.exit_code == 1  # PARTIAL_SUCCESS → 1
    assert "PARTIAL_SUCCESS" in result.output
    assert IngestionRun is not None


def test_backfill_parses_window_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    runner.invoke(app, ["migrate"])
    from final_trades.domain import RunStatus

    captured = {}

    class FakeRun:
        id = 2
        status = str(RunStatus.SUCCESS)
        summary = "ok"

    def fake_backfill(self, start, end, max_units=None):
        captured["window"] = (start, end)
        return FakeRun()

    monkeypatch.setattr("final_trades.pipeline.orchestrator.Collector.run_backfill", fake_backfill)
    result = runner.invoke(
        app, ["backfill", "--start", "2025-10-25", "--end", "2026-10-25", "--max-units", "5"]
    )
    assert result.exit_code == 0, result.output
    assert captured["window"][0].isoformat() == "2025-10-25"
    assert captured["window"][1].isoformat() == "2026-10-25"


def test_fetch_fixtures_unknown_source_errors() -> None:
    result = runner.invoke(app, ["fetch-fixtures", "--source", "nope"])
    assert result.exit_code == 2
    assert "unknown source" in result.output
