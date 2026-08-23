"""Claim ledger: the agent's persistent state.

Deterministic and dependency-free by design (`CLAUDE.md` §3). Storage adapters import from
here; nothing here imports a vendor SDK.
"""

from .decay import CEILING, FLOOR, Wave, next_check_at, next_interval, seed_interval
from .schema import (
    MAX_RESEARCH_ROUNDS,
    Claim,
    ClaimKind,
    ClaimStatus,
    Contradiction,
    EntityRef,
    Source,
)
from .tiers import AUTO_APPLY_THRESHOLD, confidence_from, tier_for

__all__ = [
    "AUTO_APPLY_THRESHOLD", "CEILING", "FLOOR", "MAX_RESEARCH_ROUNDS",
    "Claim", "ClaimKind", "ClaimStatus", "Contradiction", "EntityRef", "Source", "Wave",
    "confidence_from", "next_check_at", "next_interval", "seed_interval", "tier_for",
]
