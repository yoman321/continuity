"""The MediaWiki section-write tool — the only thing in this system that changes a page.

Writing is addressed by *heading*, never by index, and that is the whole design. MediaWiki
addresses sections by position, so `section=3` means "the fourth heading in document order" and
inserting anything above it silently renumbers everything below. A drafted edit may be minutes
old by the time a reviewer approves it. So the index is re-resolved from the stored heading
against a fresh read, immediately before the write, every time — and the read that resolves it
also supplies the `basetimestamp` that makes a concurrent edit fail loudly instead of being
overwritten.

Five outcomes, and they are deliberately not all exceptions:

* **written** — the edit landed, with the new revision id.
* **conflict** — somebody edited the page since the text was drafted. A value, not an error,
  because it is an instruction: re-read, re-draft, try again. Raising it would make ADK retry
  the identical stale text against the same page, which cannot succeed.
* **the heading is gone** — also a value, listing the headings that do exist. A section that
  vanished is a reason to re-plan, never a reason to create it: `AGENTS.md` §2 forbids adding
  a section to a wiki, and writing to a resolved existing heading is what keeps that true.
* **the anchor is gone** — the same answer one level down, for `write_anchor`. A drafted edit
  names the text it replaces; if that text is no longer in the section, or is in it twice,
  nothing is written and the caller is told which.
* **already applied** — also `write_anchor`. A draft that *adds* to a line keeps the line it
  anchored on, so approving the same edit twice would find the anchor again and append the
  same text a second time. Checked before the substitution, which makes a repeat publish a
  no-op instead of a duplication.

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
    Section,
    WikiError,
    find_section,
    format_timestamp,
    replace_anchor,
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
    def live(cls, profile: WikiProfile, *, timeout: float = 30.0,
             api_key: str | None = None) -> WikiWrite:
        """Build against `profile.api_url`. Raises unless the profile is writable.

        The key is handed to both adapters and never stored on the profile. Our own instance
        declares `requires_key`, so omitting it raises here rather than building a tool that
        would 403 on its first call.
        """
        return cls(
            profile,
            MediaWikiReader.for_profile(profile, timeout=timeout, api_key=api_key),
            MediaWikiWriter.for_profile(profile, timeout=timeout, api_key=api_key),
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
        resolved = self._resolve(title, heading)
        if isinstance(resolved, dict):
            return resolved
        revision, found = resolved
        return self._edit(revision, found, text, summary)

    def write_anchor(
        self, title: str, heading: str, anchor: str, replacement: str, summary: str
    ) -> dict[str, Any]:
        """Replace one line of a section, leaving the rest of the section as it stands now.

        This is the write behind the review gate. A drafted edit names the text it changes,
        not the section that text lives in, and an approval can land long after the draft was
        written — so the section is re-read here and the substitution applied to what it says
        *now*. Sending the drafted section wholesale would quietly revert every other change
        made to it in the meantime, which is the same silent overwrite `basetimestamp` exists
        to prevent, one level down.

        Args:
          title: page title as written on the wiki.
          heading: exact heading of the section to write to, `""` for the lead.
          anchor: the text being replaced. Must appear exactly once in the section.
          replacement: what the anchor becomes — the reviewer's text, not necessarily the
            agent's draft.
          summary: edit summary. Say what changed and cite the source, as a human editor would.
        """
        resolved = self._resolve(title, heading)
        if isinstance(resolved, dict):
            return resolved
        revision, found = resolved

        if replacement in found.text:
            # Already there. Worth its own outcome because the substitution would otherwise
            # succeed and append it a second time: a draft that adds to a line keeps the line
            # it anchors on, so the anchor is still found after the edit has landed.
            return {
                "status": "already_applied",
                "error": (
                    f"{revision.resolved_title} §{found.index}: that text is already on the "
                    f"page. Nothing was written."
                ),
                **self._provenance(revision),
                "section_index": found.index,
                "heading": found.heading,
            }

        text = replace_anchor(found, anchor, replacement)
        if text is None:
            # A value, like a vanished heading: the draft was built on text that is no longer
            # there, or is there twice. Either way the edit is stale, not broken.
            return {
                "status": "no_such_anchor",
                "error": (
                    f"{revision.resolved_title} §{found.index}: the drafted text does not "
                    f"appear exactly once in {found.heading or '(lead)'!r} any more "
                    f"({found.text.count(anchor)} occurrences). Re-read and re-draft."
                ),
                **self._provenance(revision),
                "section_index": found.index,
                "heading": found.heading,
                "occurrences": found.text.count(anchor),
            }
        return self._edit(revision, found, text, summary)

    # -- shared ---------------------------------------------------------------------

    def _resolve(
        self, title: str, heading: str
    ) -> tuple[PageRevision, Section] | dict[str, Any]:
        """Read the page and find the section by heading — the read every write starts with.

        Returns the revision alongside the section so the caller writes against the same read
        that resolved the index, or an outcome dict when there is nothing to write to.
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
        return revision, found

    def _edit(
        self, revision: PageRevision, found: Section, text: str, summary: str
    ) -> dict[str, Any]:
        """Send the write, against the revision the index was resolved from."""
        try:
            result = self.writer.edit(
                revision.resolved_title,
                text,
                summary=summary,
                section=found.index,
                # From the read that resolved the index, so the window a conflict can hide in
                # is as small as this process can make it.
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

    def _provenance(self, revision: PageRevision) -> dict[str, Any]:
        """The revision the write was based on. Same shape the read tool returns, so a graph
        node can carry one forward into the other without translating."""
        return {
            "wiki": self.profile.name,
            "resolved_title": revision.resolved_title,
            "base_revid": revision.revid,
            "base_timestamp": format_timestamp(revision.timestamp),
        }
