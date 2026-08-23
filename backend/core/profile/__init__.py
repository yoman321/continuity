"""Per-wiki configuration. Import the record from here; concrete profiles live in `known`."""

from .known import (
    ENCYCLOPEDIC_TIERS,
    ENTERTAINMENT_TIERS,
    MCU_FANDOM,
    PROFILES,
    USER_AGENT,
    WIKIPEDIA_EN,
)
from .schema import WikiProfile

__all__ = [
    "ENCYCLOPEDIC_TIERS", "ENTERTAINMENT_TIERS", "MCU_FANDOM", "PROFILES",
    "USER_AGENT", "WIKIPEDIA_EN", "WikiProfile",
]
