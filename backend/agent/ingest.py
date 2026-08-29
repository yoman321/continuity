"""The baseline pass — step 1 of a run, and the only one that needs no model and no key.

Before the agent can ask whether the world still matches the page, the ledger has to hold what
the page says. This reads every monitored page and records its sections verbatim. That is all
it does: no claims are proposed here, nothing is judged, and no external service is called
beyond the wiki's own read API — which on MCU Fandom and on our seeded instance is open and
unauthenticated, so this runs with no credential of any kind.

Idempotent, and cheap to re-run. A page's sections are replaced as one set, because their
indices are only meaningful relative to each other: insert a heading at the top and everything
below renumbers, so merging a fresh read into old rows would file one section's text under
another's index. `IngestResult` reports what actually moved by comparing `content_hash` before
and after, so re-ingesting an unchanged page is visibly a no-op rather than assumed to be one.

Simulation is not a special case. `PageSource` is satisfied by the live reader and by the
snapshot corpus, so pointing this at our own seeded MediaWiki is the same call as pointing it
at Fandom — a different profile, nothing else (`CLAUDE.md` §3). The offline path exists so the
whole baseline can be built with no wiki running at all.

Perimeter, not core: it reads a wiki. It imports no ADK — a graph node wraps it, the way one
wraps the tools (`AGENTS.md` §7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..core.ledger.baseline import BaselineStore, SectionBaseline
from ..core.profile import WikiProfile
from ..core.wiki import PageSource, WikiError, split_sections


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one page's ingest did, in counts rather than prose (`CLAUDE.md` §5)."""

    page: str
    resolved_title: str
    revid: int
    sections: int
    changed: int  # sections whose text differs from what was stored before
    added: int  # sections that did not exist in the previous baseline
    removed: int  # sections that existed before and are gone now
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def unchanged(self) -> bool:
        """A re-ingest of a page nobody touched. The common case, and it should be visible."""
        return self.ok and not (self.changed or self.added or self.removed)


def ingest_page(
    source: PageSource,
    profile: WikiProfile,
    store: BaselineStore,
    title: str,
    *,
    now: datetime | None = None,
) -> IngestResult:
    """Read one page and replace its baseline.

    A missing page is a result, not an exception, for the same reason it is in the read tool:
    the run should record which pages it could not reach and carry on with the rest. Transport
    failures still propagate — a timeout is worth retrying, a missing page is not.
    """
    fetched_at = now or datetime.now(timezone.utc)
    try:
        revision = source.revision(title)
    except WikiError as exc:
        return IngestResult(title, title, 0, 0, 0, 0, 0, error=str(exc))

    before = {s.section_index: s.content_hash for s in store.for_page(revision.resolved_title)}
    sections = tuple(
        SectionBaseline(
            page=revision.resolved_title,
            section_index=section.index,
            section_heading=section.heading,
            text=section.text,
            revid=revision.revid,
            fetched_at=fetched_at,
        )
        for section in split_sections(revision.content)
    )
    store.replace_page(revision.resolved_title, sections)

    now_hashes = {s.section_index: s.content_hash for s in sections}
    return IngestResult(
        page=title,
        resolved_title=revision.resolved_title,
        revid=revision.revid,
        sections=len(sections),
        changed=sum(1 for i, h in now_hashes.items() if i in before and before[i] != h),
        added=sum(1 for i in now_hashes if i not in before),
        removed=sum(1 for i in before if i not in now_hashes),
    )


def ingest_all(
    source: PageSource,
    profile: WikiProfile,
    store: BaselineStore,
    *,
    now: datetime | None = None,
) -> tuple[IngestResult, ...]:
    """Every page the profile monitors, in the order it lists them.

    One clock for the whole pass, so every section in one baseline carries the same
    `fetched_at` and "when was this page last read" is one value rather than twelve.
    """
    fetched_at = now or datetime.now(timezone.utc)
    return tuple(
        ingest_page(source, profile, store, title, now=fetched_at)
        for title in profile.pages
    )
