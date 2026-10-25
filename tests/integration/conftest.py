"""Integration fixtures — see helpers/pipeline_env.py for the environment builder."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from helpers.pipeline_env import Env, build_env


@pytest.fixture()
def env() -> Iterator[Env]:
    e = build_env()
    yield e
    e.session.close()


@pytest.fixture()
def collector(env: Env):
    from final_trades.pipeline.orchestrator import Collector
    from helpers.pipeline_env import TODAY

    return Collector(env.session, env.make_fetcher(), env.settings, today=TODAY)
