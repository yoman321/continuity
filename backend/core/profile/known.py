"""The profiles we ship.

MCU Fandom is the demo instance (`seed-plan.md`). The Wikipedia profile exists to prove the
core is wiki-agnostic rather than to be demoed — `summary.md` §5, "build general, demo
specific". Two profiles is the smallest number that can demonstrate anything: with one, every
hardcoded assumption still passes its own tests.

Neither is writable. All writes go to our own seeded instance (`AGENTS.md` §2).
"""

from __future__ import annotations

from .schema import WikiProfile

# Fandom throttles anonymous defaults, so this must identify us and offer a contact route.
# The repo URL is that route, deliberately — the issue tracker reaches the operator without
# publishing a personal address in a public repo. Do not "improve" this by adding an email.
USER_AGENT = (
    "continuity-wiki-agent/0.1 "
    "(+https://github.com/yoman321/continuity) python-urllib"
)

# Tier 1 — primary. The party that owns the fact is stating it.
# Tier 2 — trade press. Independent, professionally edited, names its sourcing.
# Tier 3 — structured databases. Accurate but derivative, and they lag.
# Tier 4 — general press. Usually rewriting tier 2.
# Tier 5 — social. Never sufficient alone (`seed-plan.md` §5).
# Tier 6 — fan wikis. Never citable: this is what we are trying to be.
ENTERTAINMENT_TIERS: dict[str, int] = {
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
    "tumblr.com": 5,
    "reddit.com": 5,
    "youtube.com": 5,
    "tiktok.com": 5,
    "threads.net": 5,
    "bsky.app": 5,
    "fandom.com": 6,
    "wikipedia.org": 6,
}

# Wikipedia weighs the same story differently: it cites the trade press but treats a studio
# press release as primary-and-interested rather than authoritative, and it has structured
# reference works the fan wiki does not use. Illustrative rather than exhaustive — the point
# is that swapping profiles swaps what the agent may read, not that this table is complete.
ENCYCLOPEDIC_TIERS: dict[str, int] = {
    "bfi.org.uk": 1,
    "loc.gov": 1,
    "oscars.org": 1,
    "afi.com": 1,
    "variety.com": 2,
    "hollywoodreporter.com": 2,
    "deadline.com": 2,
    "nytimes.com": 2,
    "theguardian.com": 2,
    "bbc.co.uk": 2,
    "britannica.com": 3,
    "wikidata.org": 3,
    "themoviedb.org": 3,
    "marvel.com": 4,
    "disney.com": 4,
    "imdb.com": 4,
    "x.com": 5,
    "twitter.com": 5,
    "instagram.com": 5,
    "reddit.com": 5,
    "youtube.com": 5,
    "fandom.com": 6,
    "wikipedia.org": 6,
}

# Read off the seed corpus rather than imagined: these are the top-level headings that
# actually occur across the 12 pages in `snapshots/seed/`. Box office, Reception and
# Accolades are absent from every one, which is the scope decision in `summary.md` §8 —
# not an omission.
MCU_FANDOM_SECTIONS = frozenset({
    "Appearances", "Behind the Scenes", "Biography", "Cast", "Equipment",
    "Equipment and Technology", "External Links", "Facilities", "Films", "Gallery",
    "History", "Logos", "Members", "Music", "Overview", "Personality",
    "Powers and Abilities", "Production", "Plot", "References", "Relationships",
    "Residents", "See also", "Synopsis", "Television Series", "Trivia", "Videos",
    # Page-specific headings are still part of the wiki's vocabulary — a claim about a
    # pruned object has a home on the TVA page even though no other page has one.
    "Notable Pruned Objects", "Time Variance Authority Files",
})

# Wikipedia film articles carry all three of the sections MCU Wiki lacks, which is exactly
# why §5 says the "that claim has no home" reasoning inverts between wikis.
WIKIPEDIA_SECTIONS = frozenset({
    "Plot", "Cast", "Production", "Music", "Marketing", "Release",
    "Box office", "Reception", "Accolades", "Themes", "Sequel",
    "See also", "References", "External links", "Notes", "Bibliography",
})

MCU_FANDOM = WikiProfile(
    name="Marvel Cinematic Universe Wiki",
    api_url="https://marvelcinematicuniverse.fandom.com/api.php",
    subpages=True,
    section_vocabulary=MCU_FANDOM_SECTIONS,
    domain_tiers=ENTERTAINMENT_TIERS,
    # From the wiki's own `Project:Copyrights` (revision 3728), because `siprop=rightsinfo`
    # answers a bare `CC-BY-SA` (`AGENTS.md` §6). Share-alike carries onto our own edits.
    licence="CC BY-SA 3.0 Unported",
    licence_url="https://creativecommons.org/licenses/by-sa/3.0/",
    user_agent=USER_AGENT,
)

WIKIPEDIA_EN = WikiProfile(
    name="English Wikipedia",
    api_url="https://en.wikipedia.org/w/api.php",
    # Mainspace subpages are disabled here, so `/` is an ordinary character in a title.
    subpages=False,
    section_vocabulary=WIKIPEDIA_SECTIONS,
    domain_tiers=ENCYCLOPEDIC_TIERS,
    licence="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    user_agent=USER_AGENT,
)

PROFILES: dict[str, WikiProfile] = {
    "mcu-fandom": MCU_FANDOM,
    "wikipedia-en": WIKIPEDIA_EN,
}


def local_wiki(api_url: str, *, name: str = "Continuity Wiki") -> WikiProfile:
    """Our own MediaWiki instance — the only wiki this agent may write to.

    A factory rather than a constant because the endpoint is a deployment identifier and the
    repo is public: `AGENTS.md` §2 keeps those in `.env` and nowhere else, so the caller reads
    `MEDIAWIKI_API_URL` and passes it in. That the URL cannot be hardcoded is the invariant;
    that this reads like every other profile is the point of having profiles at all.

    Everything except `writable` mirrors `MCU_FANDOM`, and not by coincidence — this instance
    is *seeded from* `snapshots/seed/`, so it holds that wiki's pages under that wiki's title
    grammar and section vocabulary. Give it Wikipedia's grammar and `Blade/Universe Defender
    Blade` would stop being a variant of `Blade` halfway through the pipeline.

    Pointing the agent at a different wiki is this function and nothing else: no branch, no
    flag, no code path that knows which instance it is talking to.
    """
    return WikiProfile(
        name=name,
        api_url=api_url,
        subpages=MCU_FANDOM.subpages,
        section_vocabulary=MCU_FANDOM.section_vocabulary,
        domain_tiers=MCU_FANDOM.domain_tiers,
        # Share-alike carries onto a copy: the seed text is CC BY-SA 3.0 and so is this
        # instance, whatever the software's default footer says (`snapshots/ATTRIBUTION.md`).
        licence=MCU_FANDOM.licence,
        licence_url=MCU_FANDOM.licence_url,
        user_agent=USER_AGENT,
        writable=True,
    )
