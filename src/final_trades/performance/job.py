"""Performance computation job (WS-07).

Placeholder wiring so the CLI boots; the real implementation (price
providers, forward returns, benchmark-relative math) lands in this module.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from final_trades.config import Settings


def run_performance_job(session: Session, settings: Settings) -> dict[str, int]:
    """Compute/update forward-return observations. Returns run statistics."""
    from final_trades.performance.returns import compute_all

    return compute_all(session, settings)
