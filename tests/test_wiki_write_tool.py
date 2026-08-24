"""The section-write tool: what it re-resolves, and what it refuses to raise.

The failure this guards against is silent. MediaWiki addresses sections by position, so a
drafted edit that stores `section=3` writes to whatever the fourth heading happens to be at the
moment it lands — and a page gains headings between drafting and approval. Every test here is
about the gap between "the section I meant" and "the index that means it now".

The other half is which outcomes are values. A conflict and a vanished heading are instructions
to re-plan, so they come back as data; raising them would make ADK retry identical stale text
against a page that has already moved.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from backend.agent.tools import CONFLICT_CODE, WikiWrite
from backend.core.profile import MCU_FANDOM, local_wiki
from backend.core.wiki import MediaWikiReader, MediaWikiWriter, PageRevision, WikiError

API = "http://wiki.invalid/api.php"
OURS = local_wiki(API)
STAMP = datetime(2024, 8, 8, 23, 57, 40, tzinfo=timezone.utc)

PAGE = "intro text\n\n==Synopsis==\ns\n\n==Cast==\nold cast\n\n==Trivia==\nt\n"
# The same page after someone inserted a section above Cast: every index below it moved.
SHIFTED = "intro text\n\n==Synopsis==\ns\n\n==Plot==\np\n\n==Cast==\nold cast\n\n==Trivia==\nt\n"


class StubReader(MediaWikiReader):
    def __init__(self, content: str = PAGE, revid: int = 100) -> None:
        super().__init__(API, user_agent="test")
        self.content = content
        self.revid = revid
        self.reads = 0

    def revision(self, title: str, *, before: datetime | None = None) -> PageRevision:
        self.reads += 1
        return PageRevision(
            requested_title=title, resolved_title=title, redirected_from=None,
            pageid=1, revid=self.revid, timestamp=STAMP, user="u", comment="",
            content=self.content,
        )


class StubWriter(MediaWikiWriter):
    def __init__(self, raises: WikiError | None = None) -> None:
        super().__init__(API, user_agent="test")
        self.raises = raises
        self.edits: list[dict[str, Any]] = []

    def edit(self, title: str, text: str, **kwargs: Any) -> dict[str, Any]:
        self.edits.append({"title": title, "text": text, **kwargs})
        if self.raises is not None:
            raise self.raises
        return {"result": "Success", "newrevid": 101}


def tool(content: str = PAGE, raises: WikiError | None = None) -> WikiWrite:
    return WikiWrite(OURS, StubReader(content), StubWriter(raises))


class TestHeadingResolution(unittest.TestCase):
    def test_the_index_is_resolved_from_the_heading_at_write_time(self) -> None:
        written = tool()
        result = written.write_section("Gambit", "Cast", "==Cast==\nnew", summary="s")
        self.assertEqual(result["status"], "written")
        self.assertEqual(result["section_index"], 2)

    def test_a_section_inserted_above_moves_the_write_with_it(self) -> None:
        """The whole reason indices are never stored across a draft. Same heading, same call,
        different page state — and the write must follow the heading, not the number."""
        before = tool(PAGE).write_section("Gambit", "Cast", "x", summary="s")
        after = tool(SHIFTED).write_section("Gambit", "Cast", "x", summary="s")
        self.assertEqual(before["section_index"], 2)
        self.assertEqual(after["section_index"], 3)

    def test_the_lead_is_addressable_as_the_empty_heading(self) -> None:
        result = tool().write_section("Gambit", "", "new lead", summary="s")
        self.assertEqual(result["section_index"], 0)

    def test_the_page_is_read_again_for_every_write(self) -> None:
        """A cached parse is a stale parse; the point is the freshness, not the parsing."""
        written = tool()
        assert isinstance(written.reader, StubReader)
        written.write_section("Gambit", "Cast", "a", summary="s")
        written.write_section("Gambit", "Trivia", "b", summary="s")
        self.assertEqual(written.reader.reads, 2)


class TestConflictGuard(unittest.TestCase):
    def test_the_base_timestamp_comes_from_the_read_that_resolved_the_index(self) -> None:
        written = tool()
        written.write_section("Gambit", "Cast", "x", summary="s")
        assert isinstance(written.writer, StubWriter)
        self.assertEqual(written.writer.edits[0]["basetimestamp"], STAMP)

    def test_a_conflict_is_a_value_that_says_what_to_do_next(self) -> None:
        """Raising it would have ADK retry the same stale text against a page that moved."""
        result = tool(raises=WikiError("conflict", code=CONFLICT_CODE)).write_section(
            "Gambit", "Cast", "x", summary="s"
        )
        self.assertEqual(result["status"], "conflict")
        self.assertIn("Re-read", result["error"])
        self.assertEqual(result["base_revid"], 100)

    def test_other_failures_report_their_code_rather_than_being_conflated(self) -> None:
        result = tool(raises=WikiError("nope", code="protectedpage")).write_section(
            "Gambit", "Cast", "x", summary="s"
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "protectedpage")


class TestNeverCreatesASection(unittest.TestCase):
    def test_a_missing_heading_returns_the_ones_that_exist(self) -> None:
        result = tool().write_section("Gambit", "Reception", "x", summary="s")
        self.assertEqual(result["status"], "no_such_section")
        self.assertEqual(result["available"], ["Synopsis", "Cast", "Trivia"])

    def test_a_missing_heading_writes_nothing_at_all(self) -> None:
        """`AGENTS.md` §2: a section with no home on this wiki is out of scope, not a new
        heading. The guard is that nothing reached the writer."""
        written = tool()
        written.write_section("Gambit", "Reception", "x", summary="s")
        assert isinstance(written.writer, StubWriter)
        self.assertEqual(written.writer.edits, [])


class TestWriteGuard(unittest.TestCase):
    def test_a_read_only_profile_cannot_build_the_tool(self) -> None:
        with self.assertRaises(WikiError):
            WikiWrite.live(MCU_FANDOM)


class TestToolSurface(unittest.TestCase):
    def test_every_model_facing_argument_is_a_string(self) -> None:
        import inspect
        from typing import get_type_hints

        hints = get_type_hints(WikiWrite.write_section)
        names = [p for p in inspect.signature(WikiWrite.write_section).parameters if p != "self"]
        self.assertEqual(names, ["title", "heading", "text", "summary"])
        for name in names:
            self.assertIs(hints[name], str)

    def test_the_signature_offers_no_way_to_pass_an_index(self) -> None:
        """If a caller could pass one, a stale one would eventually be passed."""
        import inspect

        self.assertNotIn(
            "section", inspect.signature(WikiWrite.write_section).parameters
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
