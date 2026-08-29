"""Red/green diffs for a drafted edit — the same idea git shows, over wikitext.

A reviewer approving an edit is answering "is this change right?", and two blocks of text side
by side do not answer it: the eye has to find the difference before it can judge it. So the
queue shows what git shows — removed lines in red, added lines in green, and *within* a changed
line the exact words that moved.

**The diff is computed, never stored.** Git holds snapshots and computes `git diff` on demand,
and the reason applies here with more force: a stored diff is correct only while the page it
was taken against stays put, and the whole point of the publish gate is that hours pass before
someone clicks. `Draft.before` and `Draft.after` are the content; this module is the view.

Two-way, not three-way. Git's merge machinery exists because two branches edit a common
ancestor concurrently; this project assumes a single editor while the agent runs
(`AGENTS.md` §2), so the page at publish time *is* the base and there is no third side to
reconcile. `WikiWrite` still detects a real edit conflict and returns it as a value — that is a
guard against the assumption being wrong, not a flow a reviewer is asked to resolve.

Line-level first, then word-level inside a changed pair, which is what both git and MediaWiki's
own diff view do. No context elision: the inputs here are anchor-sized — one infobox line, one
sentence, one list item — not whole pages.

Pure and stdlib-only (`CLAUDE.md` §3): `difflib` is in the standard library, so a dependency
would buy nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Words and whitespace as *separate* tokens, so joining the segments reproduces the input byte
#: for byte. Wikitext is whitespace-sensitive — `|movie = x` is not `|movie=x` to a template —
#: and a diff that cannot round-trip its own input is not evidence. Whitespace has to be its own
#: token rather than ride along with the word before it: attached, the last word of a line reads
#: as different from the same word mid-line, and a word that did not move gets marked as changed.
_WORDS = re.compile(r"\S+|\s+")

#: Below this, two lines are different lines rather than one line edited, and marking words
#: inside them produces confetti. Chosen to match how git's own `--word-diff` reads in practice.
#: Measured on the words alone: counting the spaces two unrelated sentences share scores them
#: similar for no reason, and a floor that never fires is not a floor.
SIMILARITY_FLOOR = 0.3


@dataclass(frozen=True, slots=True)
class Segment:
    """A run of text inside one row, flagged as changed or not."""

    text: str
    changed: bool


@dataclass(frozen=True, slots=True)
class Row:
    """One line of a unified diff. `kind` is git's gutter: ` `, `-` or `+`."""

    kind: str  # "context" | "removed" | "added"
    segments: tuple[Segment, ...]

    @property
    def text(self) -> str:
        """The line itself. Concatenating the segments always reproduces it."""
        return "".join(s.text for s in self.segments)

    @property
    def changed(self) -> bool:
        return any(s.changed for s in self.segments)


def diff(before: str, after: str) -> tuple[Row, ...]:
    """Unified rows taking `before` to `after`.

    Deterministic: same inputs, same rows, every time — the numbers on screen have to be
    reproducible on camera (`AGENTS.md` §5).
    """
    old, new = before.splitlines(), after.splitlines()
    rows: list[Row] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new).get_opcodes():
        if tag == "equal":
            rows.extend(_plain("context", old[i1:i2]))
        elif tag == "delete":
            rows.extend(_plain("removed", old[i1:i2]))
        elif tag == "insert":
            rows.extend(_plain("added", new[j1:j2]))
        else:
            rows.extend(_replaced(old[i1:i2], new[j1:j2]))
    return tuple(rows)


def counts(rows: tuple[Row, ...]) -> tuple[int, int]:
    """`(removed, added)` line counts — git's `-N +M`, and what a test can assert on."""
    return (
        sum(1 for r in rows if r.kind == "removed"),
        sum(1 for r in rows if r.kind == "added"),
    )


def to_payload(rows: tuple[Row, ...]) -> list[dict[str, object]]:
    """The rows as JSON the frontend renders directly.

    Computed here rather than in the browser for the reason every other number is: the core
    owns it, so what a reviewer sees and what a test asserts cannot disagree (`AGENTS.md` §4).
    """
    return [
        {
            "kind": row.kind,
            "segments": [{"text": s.text, "changed": s.changed} for s in row.segments],
        }
        for row in rows
    ]


# -- pieces ---------------------------------------------------------------------------


def _plain(kind: str, lines: list[str]) -> list[Row]:
    """Whole lines with nothing marked inside them: every word of an added or removed line is
    already accounted for by the gutter."""
    return [Row(kind, (Segment(line, False),)) for line in lines]


def _replaced(old: list[str], new: list[str]) -> list[Row]:
    """A replaced block: pair the lines up and mark words inside each pair.

    Leftovers on either side are a pure delete or insert — three lines becoming one means two
    of them were removed outright, and pretending otherwise would mark half a sentence as
    "edited" when it was dropped.
    """
    rows: list[Row] = []
    paired = min(len(old), len(new))
    for line_old, line_new in zip(old[:paired], new[:paired], strict=True):
        removed, added = _words(line_old, line_new)
        rows.append(Row("removed", removed))
        rows.append(Row("added", added))
    rows.extend(_plain("removed", old[paired:]))
    rows.extend(_plain("added", new[paired:]))
    return rows


def _words(before: str, after: str) -> tuple[tuple[Segment, ...], tuple[Segment, ...]]:
    """Word segments for one changed line, as `(removed, added)`."""
    old, new = _WORDS.findall(before), _WORDS.findall(after)
    if _similarity(old, new) < SIMILARITY_FLOOR:
        return (Segment(before, False),), (Segment(after, False),)

    matcher = SequenceMatcher(None, old, new)

    removed: list[Segment] = []
    added: list[Segment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "delete", "replace"):
            _append(removed, "".join(old[i1:i2]), changed=tag != "equal")
        if tag in ("equal", "insert", "replace"):
            _append(added, "".join(new[j1:j2]), changed=tag != "equal")
    return tuple(removed), tuple(added)


def _similarity(old: list[str], new: list[str]) -> float:
    """How alike two tokenised lines are, ignoring whitespace.

    Whitespace is in the token stream so the segments round-trip, but it must not vote: two
    unrelated sentences share their spaces, which is enough to clear a 0.3 floor on its own.
    """
    return SequenceMatcher(
        None, [t for t in old if t.strip()], [t for t in new if t.strip()]
    ).ratio()


def _append(segments: list[Segment], text: str, *, changed: bool) -> None:
    """Add `text`, merging into the previous segment when it carries the same flag — adjacent
    runs with one flag are one run, and splitting them would render as two highlights."""
    if not text:
        return
    if segments and segments[-1].changed == changed:
        segments[-1] = Segment(segments[-1].text + text, changed)
        return
    segments.append(Segment(text, changed))
