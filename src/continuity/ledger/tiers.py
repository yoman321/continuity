"""Source authority tiers and the confidence they produce.

`AGENTS.md` §2: tiers are a deterministic domain lookup, never model output. Gemini reasons
*over* a tier; it never assigns one. Handing tier assignment to the model makes the headline
adjudication behaviour unreproducible on camera.

Tier 1 is best. The table is the whole policy — to change how the agent weighs a source,
edit `DOMAIN_TIERS`, not a prompt.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Tier 1 — primary. The party that owns the fact is stating it.
# Tier 2 — trade press. Independent, professionally edited, names its sourcing.
# Tier 3 — structured databases. Accurate but derivative, and they lag.
# Tier 4 — general press. Usually rewriting tier 2.
# Tier 5 — social. Never sufficient alone (`seed-plan.md` §5).
# Tier 6 — fan wikis. Never citable: this is what we are trying to be.
DOMAIN_TIERS: dict[str, int] = {
    "marvel.com": 1,
    "disney.com": 1,
    "thewaltdisneycompany.com": 1,
    "press.disney.com": 1,
    "oscars.org": 1,
    "goldenglobes.com": 1,
    "variety.com": 2,
    "hollywoodreporter.com": 2,
    "deadline.com": 2,
    "themoviedb.org": 3,
    "wikidata.org": 3,
    "boxofficemojo.com": 3,
    "the-numbers.com": 3,
    "imdb.com": 4,
    "empireonline.com": 4,
    "collider.com": 4,
    "screenrant.com": 4,
    "x.com": 5,
    "twitter.com": 5,
    "instagram.com": 5,
    "facebook.com": 5,
    "fandom.com": 6,
    "wikipedia.org": 6,
}

UNKNOWN_TIER = 4

# Confidence contributed by the single best source backing a claim.
TIER_BASE: dict[int, float] = {1: 0.95, 2: 0.85, 3: 0.70, 4: 0.50, 5: 0.30, 6: 0.0}

# Independent corroboration is worth something, but never as much as a better source.
CORROBORATION_BONUS = 0.03
MAX_CORROBORATION = 0.09

# `summary.md` §6 guardrail: below this, nothing auto-applies and a human decides.
AUTO_APPLY_THRESHOLD = 0.75

# `seed-plan.md` §5: a social citation can corroborate but never carry a claim, even when
# the poster is the principal announcing their own project. Capped below the gate on purpose.
SOCIAL_ONLY_CAP = 0.60

# An open contradiction caps confidence regardless of how good the sources are. Two credible
# outlets disagreeing is precisely the case where the agent should decline (`summary.md` §7).
CONTRADICTED_CAP = 0.50


def registrable_domain(url: str) -> str:
    """Host of `url`, minus a leading `www.` and any subdomain we don't tier separately.

    `deadline.com` and `www.deadline.com` must tier identically, and a Fandom subdomain
    like `marvelcinematicuniverse.fandom.com` must resolve to the `fandom.com` entry.
    """
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host in DOMAIN_TIERS:
        return host
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in DOMAIN_TIERS:
            return candidate
    return host


def tier_for(url: str) -> int:
    """Authority tier of `url`. Unknown domains get `UNKNOWN_TIER`, never a guess."""
    return DOMAIN_TIERS.get(registrable_domain(url), UNKNOWN_TIER)


def confidence_from(tiers: list[int], *, contradicted: bool = False) -> float:
    """Deterministic confidence for a claim backed by sources at `tiers`.

    Best tier sets the base; each additional *independent* source at tier 3 or better adds a
    small bonus. Callers pass one tier per distinct domain — corroboration means two
    publishers, not two URLs from one.
    """
    if not tiers:
        return 0.0

    best = min(tiers)
    score = TIER_BASE.get(best, 0.0)

    corroborating = sum(1 for t in tiers if t <= 3) - (1 if best <= 3 else 0)
    score += min(max(corroborating, 0) * CORROBORATION_BONUS, MAX_CORROBORATION)

    if best >= 5:
        score = min(score, SOCIAL_ONLY_CAP)
    if contradicted:
        score = min(score, CONTRADICTED_CAP)

    return round(min(score, 1.0), 4)
