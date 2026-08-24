"""The MediaWiki section-write tool — the only thing in this system that changes a page.

Writing is addressed by *heading*, never by index, and that is the whole design. MediaWiki
addresses sections by position, so `section=3` means "the fourth heading in document order" and
inserting anything above it silently renumbers everything below. A drafted edit may be minutes
old by the time a reviewer approves it. So the index is re-resolved from the stored heading
against a fresh read, immediately before the write, every time — and the read that resolves it
also supplies the `basetimestamp` that makes a concurrent edit fail loudly instead of being
overwritten.

Three outcomes, and they are deliberately not all exceptions:

* **written** — the edit landed, with the new revision id.
* **conflict** — somebody edited the page since the text was drafted. A value, not an error,
  because it is an instruction: re-read, re-draft, try again. Raising it would make ADK retry
  the identical stale text against the same page, which cannot succeed.
* **the heading is gone** — also a value, listing the headings that do exist. A section that
  vanished is a reason to re-plan, never a reason to create it: `AGENTS.md` §2 forbids adding
  a section to a wiki, and writing to a resolved existing heading is what keeps that true.

Only our own instance is reachable from here — `MediaWikiWriter.for_profile` refuses a profile
whose `writable` is false, which is every profile we ship except `local_wiki()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...core.profile import WikiProfile
from ...core.wiki import (
    MediaWikiReader,
    MediaWikiWriter,
    PageRevision,
    WikiError,
    find_section,
    format_timestamp,
    split_sections,
)

#: MediaWiki's code for "the page moved under you". The one failure that is worth re-drafting
#: rather than reporting, so it is matched on the code and never on the message.
CONFLICT_CODE = "editconflict"


@dataclass(frozen=True, slots=True)
class WikiWrite:
    """Section writes against one wiki, under one profile's rules.

    Holds a reader as well as a writer because a write is a read first: the heading has to be
    re-resolved and the base revision captured before anything is sent.
    """

    profile: WikiProfile
    reader: MediaWikiReader
    writer: MediaWikiWriter

    @classmethod
    def live(cls, profile: WikiProfile, *, timeout: float = 30.0) -> WikiWrite:
        """Build against `profile.api_url`. Raises unless the profile is writable."""
        return cls(
            profile,
            MediaWikiReader.for_profile(profile, timeout=timeout),
            MediaWikiWriter.for_profile(profile, timeout=timeout),
        )

    def login(self, username: str, password: str) -> str:
        """Log in with a BotPassword. Call once; the session is reused for every edit."""
        return self.writer.login(username, password)

    # -- the tool -------------------------------------------------------------------

    def write_section(
        self, title: str, heading: str, text: str, summary: str
    ) -> dict[str, Any]:
        """Replace one section of a wiki page with `text`.

        The section must already exist — this never creates one. `text` is the complete
        replacement wikitext for that section, heading line included.

        Args:
          title: page title as written on the wiki.
          heading: exact heading of the section to replace, without the `==` markers.
          text: full replacement wikitext for the section, starting with its heading line.
          summary: edit summary. Say what changed and cite the source, as a human editor would.
        """
        try:
            revision = self.reader.revision(title)
        except WikiError as exc:
            return {"status": "error", "error": str(exc), "requested_title": title}

        sections = split_sections(revision.content)
        found = sections[0] if heading == "" else find_section(sections, heading)
        if found is None:
            # Never fall through to creating it (`AGENTS.md` §2). The headings that do exist
            # let the caller re-plan in one turn instead of guessing.
            return {
                "status": "no_such_section",
                "error": f"{revision.resolved_title}: no section {heading!r}",
                **self._provenance(revision),
                "available": [s.heading for s in sections if s.heading],
            }

        try:
            result = self.writer.edit(
                revision.resolved_title,
                text,
                summary=summary,
                section=found.index,
                # From the read three lines up, so the window a conflict can hide in is as
                # small as this process can make it.
                basetimestamp=revision.timestamp,
            )
        except WikiError as exc:
            if exc.code == CONFLICT_CODE:
                return {
                    "status": "conflict",
                    "error": (
                        f"{revision.resolved_title} changed since it was read "
                        f"(revision {revision.revid}). Re-read the section and re-draft "
                        f"against the current text before writing again."
                    ),
                    **self._provenance(revision),
                    "section_index": found.index,
                    "heading": found.heading,
                }
            # Everything else is terminal for this edit — a protected page, a bad token, a
            # rejected title. Returned rather than raised for the same reason a missing page
            # is: ADK retrying the identical request cannot change the answer.
            return {
                "status": "error",
                "error": str(exc),
                "code": exc.code,
                **self._provenance(revision),
            }

        return {
            "status": "written",
            **self._provenance(revision),
            "section_index": found.index,
            "heading": found.heading,
            "new_revid": result.get("newrevid"),
            # MediaWiki reports a null edit rather than failing when the text is unchanged.
            # Worth surfacing: "written" and "identical to what was already there" are
            # different outcomes to a reviewer watching a queue.
            "nochange": "nochange" in result,
        }

    # -- shared ---------------------------------------------------------------------

    def _provenance(self, revision: PageRevision) -> dict[str, Any]:
        """The revision the write was based on. Same shape the read tool returns, so a graph
        node can carry one forward into the other without translating."""
        return {
            "wiki": self.profile.name,
            "resolved_title": revision.resolved_title,
            "base_revid": revision.revid,
            "base_timestamp": format_timestamp(revision.timestamp),
        }
