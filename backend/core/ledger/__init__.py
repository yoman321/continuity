"""Claim ledger: the agent's persistent state.

Deterministic and dependency-free by design (`CLAUDE.md` §3). Storage adapters import from
here; nothing here imports a vendor SDK.
"""

from .baseline import (
    BASELINE_VERSION,
    DEFAULT_BASELINE_PATH,
    BaselineStore,
    InMemoryBaselineStore,
    JsonFileBaselineStore,
    SectionBaseline,
)
from .citations import best_citation, mentions, supporting, supports, uncited
from .decay import CEILING, FLOOR, Wave, next_check_at, next_interval, seed_interval
from .documents import DOCUMENT_VERSION, from_document, is_firestore_safe, to_document
from .schema import (
    MAX_RESEARCH_ROUNDS,
    Claim,
    ClaimKind,
    ClaimStatus,
    Contradiction,
    EntityRef,
    Source,
)
from .store import (
    DEFAULT_LEDGER_PATH,
    ClaimStore,
    InMemoryClaimStore,
    JsonFileClaimStore,
    LedgerError,
    require_scheduled,
)
from .tiers import AUTO_APPLY_THRESHOLD, confidence_from, tier_for

__all__ = [
    "AUTO_APPLY_THRESHOLD", "BASELINE_VERSION", "CEILING", "DEFAULT_BASELINE_PATH",
    "DEFAULT_LEDGER_PATH", "DOCUMENT_VERSION", "FLOOR", "MAX_RESEARCH_ROUNDS",
    "BaselineStore", "Claim", "ClaimKind", "ClaimStatus", "ClaimStore", "Contradiction",
    "EntityRef", "InMemoryBaselineStore", "InMemoryClaimStore", "JsonFileBaselineStore",
    "JsonFileClaimStore", "LedgerError", "SectionBaseline", "Source", "Wave",
    "best_citation", "confidence_from", "from_document", "is_firestore_safe", "mentions",
    "next_check_at", "next_interval", "require_scheduled", "seed_interval", "supporting",
    "supports", "tier_for", "to_document", "uncited",
]
