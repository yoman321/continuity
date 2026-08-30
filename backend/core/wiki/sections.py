"""Split wikitext into the sections MediaWiki addresses by index.

Every write this agent makes is `action=edit&section=N` (`AGENTS.md` §2), and `N` is a
position, not a name — inserting a heading above renumbers everything below it. That is why
`Claim` stores `section_heading` next to `section_index` (`ledger/schema.py`); this module is
what re-resolves one from the other before a write, and what slices a section out for review.

Pure. No network and no MediaWiki install — the numbering rule is reimplemented, not queried:
section 0 is the lead, then every heading in document order regardless of level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Line-anchored so a `==` inside a template parameter or a URL cannot open a section.
# MediaWiki accepts levels 2-6 in the section index; a single `=` is a page title, not used.
_HEADING = re.compile(r"^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Section:
    """One addressable section. `text` is what `action=edit&section=N` hands back — the
    heading line included, so a round-trip through here changes nothing."""

    index: int
    level: int  # 0 for the lead, which has no heading of its own
    heading: str  # "" for the lead
    text: str

    @property
    def is_lead(self) -> bool:
        return self.index == 0

    @property
    def body(self) -> str:
        """Content below the heading line. The lead has no heading, so it is all body."""
        if self.is_lead:
            return self.text
        _, _, rest = self.text.partition("\n")
        return rest


def split_sections(wikitext: str) -> tuple[Section, ...]:
    """Every section of `wikitext`, in MediaWiki's own index order.

    Always returns at least the lead, even for an empty page — index 0 exists whether or not
    anything is in it, and a caller resolving `section=0` must not get an IndexError.
    """
    matches = list(_HEADING.finditer(wikitext))

    lead_end = matches[0].start() if matches else len(wikitext)
    sections = [Section(index=0, level=0, heading="", text=wikitext[:lead_end])]

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(wikitext)
        sections.append(
            Section(
                index=i + 1,
                level=len(match.group(1)),
                heading=match.group(2),
                text=wikitext[match.start() : end],
            )
        )
    return tuple(sections)


def find_section(sections: tuple[Section, ...], heading: str) -> Section | None:
    """Re-resolve a section by its heading. `None` means the heading is gone, which is a
    reason to re-read the page — never a reason to fall back to the stored index."""
    return next((s for s in sections if s.heading == heading), None)


def replace_anchor(section: Section, anchor: str, replacement: str) -> str | None:
    """`section.text` with its one occurrence of `anchor` swapped for `replacement`.

    A drafted edit stores the line it changes and what that line becomes, not the section the
    line sits in — so this is what turns that pair back into the whole-section text an
    `action=edit&section=N` write needs. Substituting into the section *as read* is the point:
    sending the section as it looked when the draft was written would silently revert anything
    else that changed in it while the edit sat at the gate.

    `None`, never a guess, when the anchor is missing or appears more than once. The first
    means the line is already gone; the second means the draft does not say which of them it
    meant. Both are reasons to re-read the page and re-draft, and neither is a reason to write.
    """
    if not anchor or section.text.count(anchor) != 1:
        return None
    return section.text.replace(anchor, replacement)


def subtree(sections: tuple[Section, ...], index: int) -> tuple[Section, ...]:
    """A section together with the subsections nested under it.

    Distinct from `sections[index]` on purpose. MediaWiki addresses `==Films==` and the
    `===Film title===` headings beneath it as separate indices, which is right for a write and
    wrong for a read: slicing `Films` alone yields the heading and nothing else, because its
    text ends where the first subsection begins. Reviewers need the whole subtree; the write
    path still targets one index.

    The lead is its own subtree and nothing else. Its level is 0 — a sentinel, not a heading
    depth — so the "deeper than me" rule below would swallow every section on the page and
    hand a caller who asked for the infobox the entire article instead.
    """
    head = sections[index]
    if head.is_lead:
        return (head,)
    kept = [head]
    for section in sections[index + 1 :]:
        if section.level <= head.level:
            break
        kept.append(section)
    return tuple(kept)


def top_level(sections: tuple[Section, ...]) -> tuple[Section, ...]:
    """The `==` sections. These are the page's real structure; `===` and below are
    subdivisions of one, and the wiki's section vocabulary is written at this level."""
    return tuple(s for s in sections if s.level == 2)
