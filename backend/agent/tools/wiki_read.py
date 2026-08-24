"""The MediaWiki read tool — how a graph node sees a page.

Reading is two operations, not one, and splitting them is the whole design. `read_page_outline`
is cheap and structural: which sections exist, how big each is, what revision they came from.
`read_section` is the expensive one and is only ever called for a section the caller has
already decided it needs. Collapsing them into a single "read the page" tool would put 50KB of
wikitext into the model's context to answer a question about one paragraph — and the corpus
holds a 202KB page.

Three things this returns are load-bearing rather than informational:

* **`revid` and `timestamp`, on both calls.** `action=edit` takes `basetimestamp` to detect an
  edit conflict; without the revision the read came from there is nothing to send, and the
  write silently clobbers whatever landed in between.
* **`section_index` next to `text`.** They are not the same section. `text` is the subtree —
  `==Cast==` plus the `===...===` headings under it, which is what a reviewer has to see —
  while `section_index` addresses the heading alone, which is what a write must target
  (`core/wiki/sections.py`). Returning only one of them makes the other a guess.
* **`available` on a missing heading.** Section indices shift when anything is inserted above,
  so a heading is re-resolved before every write and "the heading is gone" is a real answer
  (`AGENTS.md` §2). Listing what *is* there lets the caller recover in one turn instead of
  guessing at a second.

Imports no ADK: the graph wraps these methods in `FunctionTool` where it is constructed, which
keeps the cold-start rule intact (`AGENTS.md` §7) and keeps the tool testable with nothing
installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.profile import WikiProfile
from ...core.wiki import (
    MediaWikiReader,
    PageRevision,
    PageSource,
    SnapshotPageSource,
    WikiError,
    find_section,
    format_timestamp,
    split_sections,
    subtree,
)


@dataclass(frozen=True, slots=True)
class WikiRead:
    """Read access to one wiki, under one profile's rules.

    The profile is bound here and never appears in a tool signature, so the model picks the
    page and the deployment picks the wiki. Swapping `source` swaps live reads for the
    snapshot corpus without any node knowing (`CLAUDE.md` §3).
    """

    profile: WikiProfile
    source: PageSource

    @classmethod
    def live(cls, profile: WikiProfile, *, timeout: float = 30.0) -> WikiRead:
        """Reads `profile.api_url` over `api.php`."""
        return cls(profile, MediaWikiReader.for_profile(profile, timeout=timeout))

    @classmethod
    def from_snapshots(
        cls, profile: WikiProfile, repo_root: Path, *, state: str = "seed"
    ) -> WikiRead:
        """The deterministic fallback: the hash-checked corpus in `snapshots/`, offline.

        `seed` rather than `current` because the seed state is what our own MediaWiki instance
        is built from, so this and the deployed wiki answer with the same bytes.
        """
        return cls(profile, SnapshotPageSource(repo_root, state=state))

    # -- the tools ------------------------------------------------------------------

    def read_page_outline(self, title: str) -> dict[str, Any]:
        """Structure of one wiki page: its sections, sizes and current revision — no text.

        Call this first. Use it to decide which section to read in full, then call
        `read_section` for that one heading.

        `in_vocabulary` says whether this wiki conventionally uses that heading, and is null
        for the lead and for subsections — the vocabulary is a top-level list, so it makes no
        claim about them.

        Args:
          title: page title as written on the wiki, e.g. "Deadpool & Wolverine".
        """
        try:
            revision = self.source.revision(title)
        except WikiError as exc:
            # Narrow on purpose (`AGENTS.md` §7): a missing page is an answer and retrying it
            # wastes a round trip, while a timeout or a socket error is worth ADK retrying and
            # is therefore left to propagate.
            return {"error": str(exc), "requested_title": title}

        sections = split_sections(revision.content)
        return {
            **self._provenance(revision),
            "size_bytes": revision.size,
            "sections": [
                {
                    "section_index": section.index,
                    "level": section.level,
                    "heading": section.heading,
                    "chars": len(section.text),
                    "in_vocabulary": self._in_vocabulary(section.level, section.heading),
                }
                for section in sections
            ],
        }

    def read_section(self, title: str, heading: str) -> dict[str, Any]:
        """Full wikitext of one section of one page, resolved by heading rather than by index.

        Returns the section together with any subsections nested under it, because that is
        what the section means to a reader — but `section_index` addresses the heading alone,
        which is what an edit must target.

        Args:
          title: page title as written on the wiki.
          heading: exact section heading, without the `==` markers. "" for the lead.
        """
        try:
            revision = self.source.revision(title)
        except WikiError as exc:
            return {"error": str(exc), "requested_title": title}

        sections = split_sections(revision.content)
        found = sections[0] if heading == "" else find_section(sections, heading)
        if found is None:
            return {
                "error": f"{revision.resolved_title}: no section {heading!r}",
                **self._provenance(revision),
                "available": [s.heading for s in sections if s.heading],
            }

        tree = subtree(sections, found.index)
        return {
            **self._provenance(revision),
            "section_index": found.index,
            "level": found.level,
            "heading": found.heading,
            "in_vocabulary": self._in_vocabulary(found.level, found.heading),
            "subsections": [s.heading for s in tree[1:]],
            # Not truncated, deliberately. Cutting wikitext mid-template hands the model
            # syntax that parses to something else; `chars` in the outline is there so the
            # caller can decide not to ask rather than be given a broken answer.
            "text": "".join(s.text for s in tree),
        }

    # -- shared ---------------------------------------------------------------------

    def _in_vocabulary(self, level: int, heading: str) -> bool | None:
        """Whether this wiki uses `heading` — `None` where the question does not apply.

        A profile's `section_vocabulary` is a list of `==` headings, because that is the level
        at which a wiki has conventions; `===` headings are subdivisions of one and the lead
        has no heading at all. Answering `False` for those would read as "this wiki does not
        use that heading", which is a claim the vocabulary does not make.
        """
        if level != 2:
            return None
        return self.profile.has_section(heading)

    def _provenance(self, revision: PageRevision) -> dict[str, Any]:
        """Which page, which revision, whose subject — on every return, error or not.

        `entity` is here because retrieval cannot tell a variant from its prime and the
        classify prompt has to state the subject it is judging against (`AGENTS.md` §7). It is
        computed by the profile, so `Human Torch/Void-Analyzing Fantastic Four` is one subject
        on Fandom and a page with a slash in its name on Wikipedia.
        """
        entity = self.profile.entity_ref(revision.resolved_title)
        return {
            "wiki": self.profile.name,
            "requested_title": revision.requested_title,
            "resolved_title": revision.resolved_title,
            "redirected_from": revision.redirected_from,
            "entity": {
                "title": entity.title,
                "base": entity.base,
                "variant": entity.variant,
                "is_variant": entity.is_variant,
            },
            "revid": revision.revid,
            "timestamp": format_timestamp(revision.timestamp),
        }
