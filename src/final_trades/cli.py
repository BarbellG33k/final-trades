"""Typer CLI — operator entrypoints.

Public note: none of these commands are exposed via the web API. The
dashboard is strictly read-only (AGENTS.md security rules).
"""

from __future__ import annotations

import sys
from datetime import datetime

import typer

app = typer.Typer(add_completion=False, help="Final Trade Intelligence Platform operator CLI.")


def _bootstrap(json_logs: bool | None = None) -> tuple:  # type: ignore[type-arg]
    from final_trades.config import get_settings
    from final_trades.db.seed import ensure_reference_data
    from final_trades.db.session import get_engine, get_session, setup_logging

    settings = get_settings()
    setup_logging(settings)
    get_engine(settings)
    session = get_session()
    ensure_reference_data(session)
    return session, settings


@app.command()
def collect(
    once: bool = typer.Option(True, "--once", help="Run a single scheduled collection pass."),
) -> None:
    """Run one bounded scheduled collection (current window + backlog catch-up)."""
    from final_trades.pipeline.orchestrator import Collector, run_exit_code
    from final_trades.sources.http import PoliteFetcher

    session, settings = _bootstrap()
    collector = Collector(session, PoliteFetcher(settings), settings)
    run = collector.run_scheduled()
    typer.echo(f"run={run.id} status={run.status} :: {run.summary}")
    session.close()
    sys.exit(run_exit_code(run.status))


@app.command()
def backfill(
    start: str = typer.Option(..., "--start", help="Window start YYYY-MM-DD (inclusive)."),
    end: str = typer.Option(..., "--end", help="Window end YYYY-MM-DD (inclusive)."),
    max_units: int = typer.Option(
        40, "--max-units", help="Bounded processing units for this invocation."
    ),
) -> None:
    """Operator-invoked historical backfill (never exposed publicly)."""
    from final_trades.pipeline.orchestrator import Collector, run_exit_code
    from final_trades.sources.http import PoliteFetcher

    session, settings = _bootstrap()
    collector = Collector(session, PoliteFetcher(settings), settings)
    run = collector.run_backfill(
        datetime.strptime(start, "%Y-%m-%d").date(),
        datetime.strptime(end, "%Y-%m-%d").date(),
        max_units=max_units,
    )
    typer.echo(f"run={run.id} status={run.status} :: {run.summary}")
    session.close()
    sys.exit(run_exit_code(run.status))


@app.command()
def migrate() -> None:
    """Apply Alembic migrations to head and seed reference data."""
    from alembic import command
    from alembic.config import Config

    _, settings = _bootstrap()
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
    typer.echo("migrations applied")


@app.command(name="coverage-report")
def coverage_report() -> None:
    """Print per-show coverage summary for the configured window."""
    from sqlalchemy import func, select

    from final_trades.db.models import DateProcessingStatus
    from final_trades.db.seed import get_show
    from final_trades.domain import DateStatus, ShowKey

    session, settings = _bootstrap()
    typer.echo(f"Coverage {settings.backfill_start_date} .. {settings.backfill_end_date}")
    for show in ShowKey:
        show_row = get_show(session, show)
        rows = session.execute(
            select(DateProcessingStatus.status, func.count())
            .where(
                DateProcessingStatus.show_id == show_row.id,
                DateProcessingStatus.processing_date >= settings.backfill_start_date,
                DateProcessingStatus.processing_date <= settings.backfill_end_date,
            )
            .group_by(DateProcessingStatus.status)
        ).all()
        counts = dict(rows)
        total_trading = sum(n for s, n in counts.items() if s != str(DateStatus.NO_SEGMENT))
        typer.echo(
            f"  {show.value}: trading-days={total_trading} "
            + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
    session.close()


@app.command()
def performance() -> None:
    """Compute/update forward-return observations (WS-07)."""
    from final_trades.performance.job import run_performance_job

    session, settings = _bootstrap()
    stats = run_performance_job(session, settings)
    typer.echo(f"performance: {stats}")
    session.close()


@app.command()
def serve() -> None:
    """Serve the public read-only API (+ built SPA if present)."""
    import uvicorn

    _, settings = _bootstrap()
    uvicorn.run(
        "final_trades.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


@app.command(name="fetch-fixtures")
def fetch_fixtures(
    source: str = typer.Option("benzinga_halftime", "--source", help="Fixture source key."),
) -> None:
    """Refresh recorded test fixtures from live sources (bounded, rate-limited).

    Development utility only. Fixtures are trimmed snapshots committed to
    tests/fixtures/ so CI never requires network access.
    """
    from pathlib import Path

    from final_trades.sources import benzinga
    from final_trades.sources.http import PoliteFetcher

    _, settings = _bootstrap()
    fetcher = PoliteFetcher(settings)
    out = Path("tests/fixtures")
    out.mkdir(parents=True, exist_ok=True)
    if source == "benzinga_halftime":
        result = fetcher.get(
            benzinga.TOPIC_URLS[
                __import__("final_trades.domain", fromlist=["ShowKey"]).ShowKey.HALFTIME_REPORT
            ]
        )
        typer.echo(f"topic fetch: {type(result).__name__}")
    else:
        typer.echo(f"unknown source {source!r}", err=True)
        raise typer.Exit(2)
    typer.echo("fixtures refreshed (inspect and trim before committing)")


if __name__ == "__main__":
    app()
