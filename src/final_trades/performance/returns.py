"""Forward-return computation (WS-07).

Placeholder until the price-provider and return-calculation implementation
lands; keeps the CLI wiring honest (import works, returns empty stats).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from final_trades.config import Settings


def compute_all(session: Session, settings: Settings) -> dict[str, int]:
    raise NotImplementedError("WS-07: performance computation not yet implemented")
