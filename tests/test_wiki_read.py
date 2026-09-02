"""The MediaWiki read tool, and the snapshot source that makes it runnable offline.

Two things here are invariants rather than behaviour, and are why the file exists:

* **The outline carries no wikitext.** It is the cheap call — the whole point of splitting the
  read in two — and a section body leaking into it puts 50KB in front of the model to answer a
  structural question. Asserted on real corpus bytes, not on a fixture.
* **A missing page is a return value; a network failure is an exception.** ADK 2.0 drives
  retry off exceptions (`AGENTS.md` §7), so swallowing the second permanently disables retry
  and raising the first burns a round trip on a page that will never exist.

No vendor SDK is imported, so these run on a bare interpreter — which is also the proof that
the fallback path itself does.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, get_type_hints

from backend.agent.tools import WikiRead
from backend.core.profile import MCU_FANDOM, WIKIPEDIA_EN
from backend.core.wiki import (
    MediaWikiReader,
    PageRevision,
    PageSource,
    SnapshotPageSource,
    WikiError,
    split_sections,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TRUNK = "Deadpool & Wolverine"
VARIANT = "Human Torch/Void-Analyzing Fantastic Four"


def reader(profile: Any = MCU_FANDOM) -> WikiRead:
    return WikiRead.from_snapshots(profile, REPO_ROOT)


class Unreachable:
    """A source whose network is down. Not a `WikiError` — that is the point."""

    def revision(self, title: str, *, before: datetime | None = None) -> PageRevision:
        raise urllib.error.URLError("connection refused")


class TestOutline(unittest.TestCase):
    def test_the_outline_carries_no_wikitext(self) -> None:
        outline = reader().read_page_outline(TRUNK)
        for section in outline["sections"]:
            self.assertNotIn("text", section)
        # 50KB page; the structural answer has to stay a small fraction of it.
        self.assertLess(len(json.dumps(outline)), outline["size_bytes"] / 10)

    def test_the_outline_indices_are_mediawikis_own(self) -> None:
        raw = (REPO_ROOT / "snapshots/seed/Deadpool_Wolverine.wikitext").read_text("utf-8")
        expected = [(s.index, s.level, s.heading) for s in split_sections(raw)]
        got = [
            (s["section_index"], s["level"], s["heading"])
            for s in reader().read_page_outline(TRUNK)["sections"]
        ]
        self.assertEqual(got, expected)

    def test_in_vocabulary_is_null_where_the_vocabulary_makes_no_claim(self) -> None:
        by_heading = {
            (s["level"], s["heading"]): s["in_vocabulary"]
            for s in reader().read_page_outline(TRUNK)["sections"]
        }
        self.assertIs(by_heading[(2, "Cast")], True)  # a heading this wiki uses
        self.assertIsNone(by_heading[(0, "")])  # the lead has no heading
        self.assertIsNone(by_heading[(3, "Locations")])  # vocabulary is top-level only


class TestSectionRead(unittest.TestCase):
    def test_the_text_is_the_subtree_and_the_index_is_the_heading_alone(self) -> None:
        """The distinction `sections.py` exists to keep: read wide, write narrow.

        `==Appearances==` on the trunk is a heading with nothing under it directly — all of
        its content sits in `===Locations===` and its peers. Returning `sections[index].text`
        would hand a reviewer a bare heading.
        """
        outline = reader().read_page_outline(TRUNK)
        listed = next(s for s in outline["sections"] if s["heading"] == "Appearances")
        section = reader().read_section(TRUNK, "Appearances")

        self.assertEqual(section["section_index"], listed["section_index"])
        self.assertGreater(len(section["text"]), listed["chars"] * 10)
        self.assertIn("Locations", section["subsections"])

    def test_reading_the_lead_does_not_return_the_page(self) -> None:
        raw = (REPO_ROOT / "snapshots/seed/Deadpool_Wolverine.wikitext").read_text("utf-8")
        lead = reader().read_section(TRUNK, "")
        self.assertEqual(lead["section_index"], 0)
        self.assertEqual(lead["text"], split_sections(raw)[0].text)
        self.assertLess(len(lead["text"]), len(raw) / 2)

    def test_a_missing_heading_names_the_ones_that_exist(self) -> None:
        answer = reader().read_section(TRUNK, "Reception")
        self.assertIn("Reception", answer["error"])
        self.assertIn("Cast", answer["available"])
        self.assertNotIn("text", answer)

    def test_every_return_carries_the_revision_it_came_from(self) -> None:
        """`action=edit` needs `basetimestamp` to detect a conflict, including after a miss."""
        for answer in (
            reader().read_page_outline(TRUNK),
            reader().read_section(TRUNK, "Cast"),
            reader().read_section(TRUNK, "Reception"),
        ):
            self.assertEqual(answer["revid"], 2019481)
            self.assertEqual(answer["timestamp"], "2024-08-08T23:57:40Z")

    def test_returns_survive_json_round_trip(self) -> None:
        """ADK hands these to the model as JSON; a stray dataclass fails at call time."""
        for answer in (
            reader().read_page_outline(TRUNK),
            reader().read_section(TRUNK, "Cast"),
            reader().read_section(TRUNK, "Reception"),
            reader().read_page_outline("No Such Page"),
        ):
            self.assertEqual(json.loads(json.dumps(answer)), answer)


class TestFailureModes(unittest.TestCase):
    """`AGENTS.md` §7: catch narrowly inside ADK tools, or retry breaks."""

    def test_a_missing_page_is_an_answer_not_an_exception(self) -> None:
        answer = reader().read_page_outline("No Such Page")
        self.assertIn("error", answer)
        self.assertEqual(answer["requested_title"], "No Such Page")

    def test_a_network_failure_propagates_so_adk_can_retry(self) -> None:
        broken = WikiRead(MCU_FANDOM, Unreachable())
        with self.assertRaises(urllib.error.URLError):
            broken.read_page_outline(TRUNK)
        with self.assertRaises(urllib.error.URLError):
            broken.read_section(TRUNK, "Cast")


class TestProfileBinding(unittest.TestCase):
    """The plug-and-play seam: same bytes, different wiki, different subject."""

    def test_the_same_title_is_a_variant_on_one_wiki_and_a_page_on_another(self) -> None:
        fandom = reader(MCU_FANDOM).read_page_outline(VARIANT)["entity"]
        wikipedia = reader(WIKIPEDIA_EN).read_page_outline(VARIANT)["entity"]

        self.assertEqual(fandom["base"], "Human Torch")
        self.assertEqual(fandom["variant"], "Void-Analyzing Fantastic Four")
        self.assertTrue(fandom["is_variant"])

        self.assertEqual(wikipedia["base"], VARIANT)
        self.assertIsNone(wikipedia["variant"])
        self.assertFalse(wikipedia["is_variant"])

    def test_every_model_facing_argument_is_a_plain_string(self) -> None:
        """A model cannot pass a `WikiProfile` — it is not JSON — and must not choose the wiki
        anyway (`AGENTS.md` §2). ADK builds the tool schema from these hints, so anything that
        is not a scalar here becomes a schema the model cannot fill."""
        for tool in (WikiRead.read_page_outline, WikiRead.read_section):
            hints = get_type_hints(tool)
            names = [p for p in inspect.signature(tool).parameters if p != "self"]
            self.assertTrue(names)
            for name in names:
                self.assertIs(hints[name], str, f"{tool.__name__}({name}) is not a string")


class TestNoVendorImport(unittest.TestCase):
    """The tool bodies import no ADK, `google-genai` or `parallel-web`.

    Wrapping happens where the graph is built, not here. That keeps the cold-start rule
    (`AGENTS.md` §7) intact and — the reason it is asserted rather than intended — keeps the
    demo's deterministic fallback runnable on an interpreter with nothing installed.
    """

    def test_importing_the_tool_pulls_in_no_sdk(self) -> None:
        probe = (
            "import sys; import backend.agent.tools as t; "
            "print([m for m in sys.modules if m.split('.')[0] "
            "in {'google', 'parallel', 'fastapi'}])"
        )
        out = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        self.assertEqual(out.stdout.strip(), "[]", out.stdout)


class TestSnapshotSource(unittest.TestCase):
    def test_both_readers_satisfy_the_protocol(self) -> None:
        self.assertIsInstance(SnapshotPageSource(REPO_ROOT), PageSource)
        self.assertIsInstance(MediaWikiReader("http://x/api.php", user_agent="ua"), PageSource)

    def test_an_edited_snapshot_is_refused_not_served(self) -> None:
        """The corpus is immutable (`AGENTS.md` §4); a fallback serving edited text silently
        is the exact failure the hashes exist to prevent."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO_ROOT / "snapshots", root / "snapshots")
            target = root / "snapshots/seed/Deadpool_Wolverine.wikitext"
            target.write_text(target.read_text("utf-8") + "\ntampered\n", encoding="utf-8")
            with self.assertRaises(WikiError):
                SnapshotPageSource(root).revision(TRUNK)

    def test_before_answers_as_the_live_api_does(self) -> None:
        source = SnapshotPageSource(REPO_ROOT)
        pinned = source.revision(TRUNK).timestamp
        self.assertEqual(source.revision(TRUNK, before=pinned).revid, 2019481)
        with self.assertRaises(WikiError):
            source.revision(TRUNK, before=pinned - timedelta(seconds=1))

    def test_current_is_reachable_and_is_not_the_seed(self) -> None:
        seed = SnapshotPageSource(REPO_ROOT, state="seed").revision(TRUNK)
        current = SnapshotPageSource(REPO_ROOT, state="current").revision(TRUNK)
        self.assertNotEqual(seed.revid, current.revid)
        self.assertGreater(current.timestamp, seed.timestamp)

    def test_an_unknown_state_fails_at_construction(self) -> None:
        with self.assertRaises(WikiError):
            SnapshotPageSource(REPO_ROOT, state="latest")

    def test_the_corpus_is_reachable_by_every_title_the_manifest_records(self) -> None:
        source = SnapshotPageSource(REPO_ROOT)
        self.assertEqual(len(source.titles), 12)
        for title in source.titles:
            self.assertTrue(source.revision(title).content)


class TestToolSurface(unittest.TestCase):
    """What a model would be shown, and what it must never be shown.

    These used to wrap the methods in ADK's `FunctionTool` and read the declaration it built.
    ADK went on Sept 1, 2026 with the orchestrator, so the assertions are made against the
    signature directly — which is what the SDK was reading anyway, and which means they no
    longer need the venv.

    The property is unchanged and still matters: the profile is *bound*, never a parameter, so
    a model cannot choose which wiki to read (`AGENTS.md` §7); and every parameter a model can
    fill is a plain scalar, because that is all a JSON schema can carry.
    """

    def methods(self) -> list[Any]:
        wiki = reader()
        return [wiki.read_page_outline, wiki.read_section]

    def test_each_tool_is_a_named_method_with_a_description(self) -> None:
        self.assertEqual(
            [m.__name__ for m in self.methods()], ["read_page_outline", "read_section"]
        )
        for method in self.methods():
            self.assertTrue((method.__doc__ or "").strip(), method.__name__)

    def test_the_signature_hides_self_and_the_profile(self) -> None:
        """A bound method drops `self`, and no tool takes a profile — the two things a
        declaration must not expose."""
        params = [set(inspect.signature(m).parameters) for m in self.methods()]
        self.assertEqual(params, [{"title"}, {"title", "heading"}])

    def test_every_model_facing_argument_is_json_expressible(self) -> None:
        """A scalar, or a list of them. Anything else could not survive a schema.

        Compared by name because `from __future__ import annotations` makes every annotation a
        string — resolving them would import the module's namespace to learn what the source
        already says plainly.
        """
        allowed = {"str", "int", "float", "bool", "list[str]", "tuple[str, ...]"}
        for method in self.methods():
            for name, param in inspect.signature(method).parameters.items():
                self.assertIn(str(param.annotation), allowed, f"{method.__name__}.{name}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
