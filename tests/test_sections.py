"""Section splitting, including against the committed snapshots.

The synthetic cases pin the numbering rule; the snapshot cases pin it against real MCU Wiki
wikitext, which is the only thing that proves the rule survives 15 templates and a 50KB page.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, ClassVar

from continuity.wiki import find_section, split_sections, subtree, top_level

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = REPO_ROOT / "snapshots"


class TestSplit(unittest.TestCase):
    def test_lead_exists_even_with_no_headings(self) -> None:
        sections = split_sections("just prose")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].index, 0)
        self.assertTrue(sections[0].is_lead)
        self.assertEqual(sections[0].heading, "")

    def test_empty_page_still_has_section_zero(self) -> None:
        # A caller resolving section=0 must not hit an IndexError on a blank page.
        sections = split_sections("")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].text, "")

    def test_numbering_counts_every_level_in_document_order(self) -> None:
        # MediaWiki does not restart numbering per level: a === under a == is the next index.
        sections = split_sections("lead\n==A==\nx\n===A1===\ny\n==B==\nz\n")
        self.assertEqual([s.index for s in sections], [0, 1, 2, 3])
        self.assertEqual([s.heading for s in sections], ["", "A", "A1", "B"])
        self.assertEqual([s.level for s in sections], [0, 2, 3, 2])

    def test_section_text_includes_its_heading_line(self) -> None:
        # action=edit&section=N returns the heading too; a round-trip must not drop it.
        sections = split_sections("lead\n==A==\nbody\n")
        self.assertTrue(sections[1].text.startswith("==A=="))
        self.assertEqual(sections[1].body.strip(), "body")

    def test_concatenating_every_section_rebuilds_the_page(self) -> None:
        raw = "lead\n\n==A==\nx\n\n===A1===\ny\n\n==B==\nz\n"
        self.assertEqual("".join(s.text for s in split_sections(raw)), raw)

    def test_equals_inside_a_line_does_not_open_a_section(self) -> None:
        # Template parameters are full of `=`, and one opening a section would shift every
        # index below it — the exact failure `Claim.section_heading` exists to catch.
        raw = "{{Character\n|real name = Remy LeBeau\n|status = Alive}}\nprose\n"
        self.assertEqual(len(split_sections(raw)), 1)

    def test_heading_whitespace_is_stripped_but_inner_markup_is_kept(self) -> None:
        sections = split_sections("lead\n==  ''[[Avengers: Doomsday]]''  ==\n")
        self.assertEqual(sections[1].heading, "''[[Avengers: Doomsday]]''")


class TestSubtree(unittest.TestCase):
    def test_subtree_gathers_nested_subsections(self) -> None:
        sections = split_sections("lead\n==A==\nx\n===A1===\ny\n===A2===\nz\n==B==\nw\n")
        self.assertEqual([s.heading for s in subtree(sections, 1)], ["A", "A1", "A2"])

    def test_subtree_stops_at_the_next_peer(self) -> None:
        sections = split_sections("lead\n==A==\nx\n===A1===\ny\n==B==\nw\n")
        self.assertNotIn("B", [s.heading for s in subtree(sections, 1)])

    def test_subtree_of_a_leaf_is_just_itself(self) -> None:
        sections = split_sections("lead\n==A==\nx\n==B==\nw\n")
        self.assertEqual([s.heading for s in subtree(sections, 1)], ["A"])

    def test_a_section_alone_can_be_just_its_heading(self) -> None:
        # Why subtree exists. Phase Six's ==Films== is immediately followed by ===Film===
        # headings, so slicing the section alone yields the heading line and nothing else —
        # correct for a write, useless for a reviewer.
        raw = "lead\n==Films==\n===''First Steps'' (2025)===\n''To be added''\n"
        sections = split_sections(raw)
        self.assertEqual(sections[1].body.strip(), "")
        self.assertIn("To be added", "".join(s.text for s in subtree(sections, 1)))


class TestFind(unittest.TestCase):
    def test_find_returns_the_current_index_not_the_stored_one(self) -> None:
        # The whole point: a heading inserted above moves "Cast" from 1 to 2.
        before = split_sections("lead\n==Cast==\nx\n")
        after = split_sections("lead\n==Synopsis==\ny\n==Cast==\nx\n")
        self.assertEqual(find_section(before, "Cast").index, 1)  # type: ignore[union-attr]
        self.assertEqual(find_section(after, "Cast").index, 2)  # type: ignore[union-attr]

    def test_missing_heading_is_none_not_a_fallback(self) -> None:
        self.assertIsNone(find_section(split_sections("lead\n==A==\n"), "Cast"))


class TestAgainstSnapshots(unittest.TestCase):
    """Real wikitext. Numbers here were measured from the corpus, not assumed."""

    manifest: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((SNAPSHOTS / "manifest.json").read_text(encoding="utf-8"))

    def _seed(self, requested_title: str) -> str:
        entry = next(p for p in self.manifest["pages"] if p["requested_title"] == requested_title)
        text: str = (REPO_ROOT / entry["seed"]["file"]).read_text(encoding="utf-8")
        return text

    def test_trunk_page_has_the_nine_sections_the_plan_claims(self) -> None:
        # `seed-plan.md` §7 rests on this: nine clean `==` sections means section-level
        # edits are viable on the demo page.
        trunk = split_sections(self._seed("Deadpool & Wolverine"))
        headings = [s.heading for s in top_level(trunk)]
        self.assertEqual(
            headings,
            ["Synopsis", "Plot", "Cast", "Appearances", "Production",
             "Videos", "Music", "References", "External Links"],
        )

    def test_every_seed_page_round_trips(self) -> None:
        for entry in self.manifest["pages"]:
            raw = (REPO_ROOT / entry["seed"]["file"]).read_text(encoding="utf-8")
            with self.subTest(page=entry["requested_title"]):
                self.assertEqual("".join(s.text for s in split_sections(raw)), raw)

    def test_no_seed_page_puts_content_only_in_the_lead(self) -> None:
        # A page the splitter failed on would present as one giant lead section.
        for entry in self.manifest["pages"]:
            raw = (REPO_ROOT / entry["seed"]["file"]).read_text(encoding="utf-8")
            with self.subTest(page=entry["requested_title"]):
                self.assertGreater(len(split_sections(raw)), 1)

    def test_phase_six_renamed_its_films_section(self) -> None:
        # The live example of why a stored index is not enough, and of `AGENTS.md` §2's
        # "never create a section": editors renamed Films -> Projects between the two states.
        entry = next(p for p in self.manifest["pages"] if p["requested_title"] == "Phase Six")
        seed = top_level(split_sections((REPO_ROOT / entry["seed"]["file"]).read_text("utf-8")))
        live = top_level(split_sections((REPO_ROOT / entry["current"]["file"]).read_text("utf-8")))
        self.assertIn("Films", [s.heading for s in seed])
        self.assertNotIn("Films", [s.heading for s in live])
        self.assertIn("Projects", [s.heading for s in live])


if __name__ == "__main__":
    unittest.main()
