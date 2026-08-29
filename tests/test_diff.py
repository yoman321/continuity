"""The drafted-edit diff: what a reviewer is shown, and what it must never lose.

The invariant that matters most is the round trip. A diff is evidence a human approves an edit
on, so the rows have to *be* the two texts — concatenate the context and removed rows and you
have `before`, context and added and you have `after`. Anything less and the reviewer approved
something other than what gets written, which is the one failure this whole gate exists to
prevent.

Stdlib only; `difflib` is in it, so the core stays dependency-free.
"""

from __future__ import annotations

import unittest

from backend.core.wiki import counts, diff, to_payload
from backend.core.wiki.diff import SIMILARITY_FLOOR

ANCHOR = "|movie = ''[[Deadpool & Wolverine]]''"
EDITED = "|movie = ''[[Deadpool & Wolverine]]''<br>''[[Avengers: Doomsday]]''"


def rebuild(before_text: str, after_text: str) -> tuple[str, str]:
    rows = diff(before_text, after_text)
    old = "\n".join(r.text for r in rows if r.kind in ("context", "removed"))
    new = "\n".join(r.text for r in rows if r.kind in ("context", "added"))
    return old, new


def marked(before_text: str, after_text: str, kind: str) -> str:
    """The changed words of one side, so a test can assert on what is highlighted."""
    return "".join(
        s.text
        for row in diff(before_text, after_text)
        if row.kind == kind
        for s in row.segments
        if s.changed
    )


class TestRoundTrip(unittest.TestCase):
    """The rows are the texts. Nothing may be dropped, reordered or re-spaced."""

    def test_the_rows_rebuild_both_sides(self) -> None:
        self.assertEqual(rebuild(ANCHOR, EDITED), (ANCHOR, EDITED))

    def test_a_multi_line_edit_rebuilds(self) -> None:
        before = "* [[Blade]]\n* [[Deadpool]]\n* [[Wolverine]]"
        after = "* [[Blade]]\n* [[Deadpool & Wolverine]]\n* [[Gambit]]\n* [[Wolverine]]"
        self.assertEqual(rebuild(before, after), (before, after))

    def test_whitespace_survives_exactly(self) -> None:
        # Wikitext is whitespace-sensitive: `|movie = x` is not `|movie=x` to a template.
        before = "|movie  =   x"
        after = "|movie  =   y"
        self.assertEqual(rebuild(before, after), (before, after))

    def test_empty_before_is_a_pure_insertion(self) -> None:
        # "" has no lines at all, so there is nothing to show as removed.
        self.assertEqual([r.kind for r in diff("", "a new line")], ["added"])
        self.assertEqual(rebuild("", "a new line"), ("", "a new line"))

    def test_identical_text_has_nothing_marked(self) -> None:
        rows = diff(ANCHOR, ANCHOR)
        self.assertEqual({r.kind for r in rows}, {"context"})
        self.assertFalse(any(r.changed for r in rows))


class TestWordLevel(unittest.TestCase):
    def test_an_appended_phrase_is_the_only_thing_marked(self) -> None:
        self.assertEqual(marked("two", "two point five", "added"), " point five")

    def test_a_word_that_did_not_move_is_not_marked(self) -> None:
        # The regression that made this file worth writing: with whitespace attached to the
        # word before it, `billion` at end-of-line did not match `billion` mid-line, so an
        # untouched word came back highlighted.
        self.assertEqual(marked("grossed 1.3 billion", "grossed 1.34 billion", "added"), "1.34")

    def test_both_sides_mark_their_own_half_of_a_change(self) -> None:
        self.assertEqual(marked("released in July", "released in August", "removed"), "July")
        self.assertEqual(marked("released in July", "released in August", "added"), "August")

    def test_adjacent_changed_words_are_one_highlight(self) -> None:
        rows = [r for r in diff("a b c", "a x y c") if r.kind == "added"]
        changed = [s for s in rows[0].segments if s.changed]
        # Two changed tokens and the space between them are one run, not three highlights.
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].text, "x y")

    def test_wholly_different_lines_are_not_word_marked(self) -> None:
        # Below the similarity floor these are two different lines, not one line edited, and
        # marking words inside them produces confetti.
        rows = diff("Cast and characters", "Nothing whatsoever alike here")
        self.assertFalse(any(r.changed for r in rows))

    def test_the_floor_is_a_ratio_not_a_count(self) -> None:
        self.assertGreater(SIMILARITY_FLOOR, 0.0)
        self.assertLess(SIMILARITY_FLOOR, 1.0)


class TestLineLevel(unittest.TestCase):
    def test_an_unchanged_line_is_context(self) -> None:
        kinds = [r.kind for r in diff("keep\ndrop", "keep")]
        self.assertEqual(kinds, ["context", "removed"])

    def test_three_lines_becoming_one_removes_the_leftovers_outright(self) -> None:
        rows = diff("a\nb\nc", "z")
        # One pair is an edit; the other two lines were dropped, and saying they were "edited"
        # would mark half a sentence as changed when it was deleted.
        self.assertEqual([r.kind for r in rows], ["removed", "added", "removed", "removed"])

    def test_counts_are_the_gutter_numbers(self) -> None:
        self.assertEqual(counts(diff("a\nb", "a\nb\nc")), (0, 1))
        self.assertEqual(counts(diff("a\nb\nc", "a")), (2, 0))


class TestDeterminism(unittest.TestCase):
    def test_the_same_edit_diffs_the_same_way_twice(self) -> None:
        # It is on screen during a recorded demo; a diff that reshuffles is not evidence.
        self.assertEqual(diff(ANCHOR, EDITED), diff(ANCHOR, EDITED))


class TestPayload(unittest.TestCase):
    def test_the_payload_is_json_shaped(self) -> None:
        payload = to_payload(diff(ANCHOR, EDITED))
        self.assertEqual({k for row in payload for k in row}, {"kind", "segments"})
        for row in payload:
            for segment in row["segments"]:  # type: ignore[attr-defined]
                self.assertEqual(set(segment), {"text", "changed"})
                self.assertIsInstance(segment["changed"], bool)

    def test_the_payload_carries_the_text_the_rows_carry(self) -> None:
        rows = diff(ANCHOR, EDITED)
        payload = to_payload(rows)
        for row, out in zip(rows, payload, strict=True):
            self.assertEqual(
                row.text, "".join(s["text"] for s in out["segments"])  # type: ignore[attr-defined]
            )


if __name__ == "__main__":
    unittest.main()
