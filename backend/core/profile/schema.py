"""Per-wiki configuration — everything the agent must not assume.

`summary.md` §5: the product is plug-and-play across MediaWiki sites, so title grammar,
section vocabulary, source tiers, licence and auth are per-wiki data the core reads rather
than constants it carries. `AGENTS.md` §2 makes a hardcoded Fandom assumption in shared code
a rewrite rather than a patch, because it silently produces confident wrong output on the
next wiki instead of failing.

Pure data. This package imports *from* the ledger core and never the other way round, so the
core stays profile-agnostic and there is no cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..ledger.schema import EntityRef


@dataclass(frozen=True, slots=True)
class WikiProfile:
    """One wiki's conventions. Everything here varies between MediaWiki sites."""

    name: str
    api_url: str

    # Title grammar. MediaWiki reports this per namespace as `subpages` under
    # `siprop=namespaces`; verified Aug 23, 2026 that en.wikipedia returns it absent for
    # mainspace while MCU Fandom returns it present. Never guess: with subpages off,
    # `AC/DC` is one 202KB article and splitting it invents a subject called `AC`.
    subpages: bool

    # Headings this wiki actually uses. `AGENTS.md` §2 forbids creating a section, so a fact
    # with no home here is out of scope rather than a new heading.
    section_vocabulary: frozenset[str]

    # Domain -> authority tier. Also the retrieval policy, not only the confidence score:
    # tier <=3 entries become Parallel's `source_policy.include_domains` (`AGENTS.md` §7).
    domain_tiers: Mapping[str, int]

    # The pages this wiki is monitored on. Config, not discovery: the agent is not a crawler,
    # and "which pages do we maintain" is a decision someone made, not something to infer from
    # a category listing. It lives here because it is per-wiki exactly like `section_vocabulary`,
    # and because the ingest pass has to start somewhere — an empty ledger and no page list is
    # an agent with nothing to do.
    pages: tuple[str, ...]

    licence: str
    licence_url: str
    #: Where an article lives for a reader, so a wikilink can be rendered as a real link. Per
    #: wiki because it does not follow from `api_url`: Fandom serves `api.php` from the root
    #: and articles from `/wiki/`, while Wikipedia serves the API from `/w/`. Deriving it would
    #: be a guess about a convention the profile exists to state.
    article_base: str

    # Fandom throttles anonymous User-Agents (`AGENTS.md` §6), so every profile carries one.
    user_agent: str

    # `api.php` is the default and the fallback because it is what every MediaWiki exposes;
    # a profile may name another transport, and the core does not care which (`summary.md` §5).
    transport: str = "api.php"

    # `AGENTS.md` §2: never write to any real wiki. Only our own seeded instance sets this,
    # which makes the invariant a value the write path can check rather than prose it can
    # violate silently.
    writable: bool = False

    # Whether this endpoint demands a credential. A fact about the endpoint, not a preference:
    # Fandom's action API is open, ours is gated. The *value* never lives on a profile — the
    # repo is public and a profile is source (§2) — so the caller reads it from `.env` or
    # Secret Manager and passes it to the adapter, exactly as it already does for the bot
    # password. Our own wiki sets this so the agent reaches it the way it reaches anything
    # external: through a configured endpoint, with a credential, failing closed without one.
    requires_key: bool = False

    def entity_ref(self, title: str) -> EntityRef:
        """Which subject `title` names, under this wiki's title grammar."""
        return EntityRef.from_title(title, subpages=self.subpages)

    def has_section(self, heading: str) -> bool:
        """Whether this wiki uses `heading`. False means the fact has no home here."""
        return heading in self.section_vocabulary

    @property
    def include_domains(self) -> tuple[str, ...]:
        """Tier 1-3 domains, shaped for Parallel's `source_policy.include_domains`."""
        return tuple(sorted(d for d, t in self.domain_tiers.items() if t <= 3))
