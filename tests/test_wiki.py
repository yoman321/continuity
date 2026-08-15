"""MediaWiki read-adapter tests.

Everything here is offline. The network call is one method (`MediaWikiReader.fetch`); these
cover the request we build, the response we parse, and the integrity of what got committed.

The last class is the one that matters most: it re-hashes the committed snapshots against the
manifest, so a corrupted or hand-edited fixture fails the gate rather than quietly becoming
the seed (`CLAUDE.md` §5 — measure, don't eyeball).
"""

import hashlib
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from continuity.wiki import (
    WikiError,
    build_query,
    parse_revision,
    parse_timestamp,
    slug_for,
)

SNAPSHOTS = Path(__file__).resolve().parent.parent / "snapshots"
FREEZE = datetime(2024, 8, 9, tzinfo=timezone.utc)


def response(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": {
            "pages": [{
                "pageid": 320659,
                "title": "Deadpool & Wolverine",
                "revisions": [{
                    "revid": 2019481,
                    "timestamp": "2024-08-08T23:57:40Z",
                    "user": "SomeEditor",
                    "comment": "typo",
                    "slots": {"main": {"content": "{{Movie}} text"}},
                }],
            }]
        }
    }
    payload["query"].update(overrides)
    return payload


class TestSlug(unittest.TestCase):
    def test_awkward_titles_become_shell_safe_stems(self) -> None:
        # Ampersands, slashes and parens all appear in the real page list.
        self.assertEqual(slug_for("Deadpool & Wolverine"), "Deadpool_Wolverine")
        self.assertEqual(slug_for("Void (End of Time)"), "Void_End_of_Time")
        self.assertEqual(
            slug_for("Blade/Universe Defender Blade"), "Blade_Universe_Defender_Blade"
        )

    def test_hyphens_survive(self) -> None:
        self.assertEqual(
            slug_for("Human Torch/Void-Analyzing Fantastic Four"),
            "Human_Torch_Void-Analyzing_Fantastic_Four",
        )

    def test_seed_page_slugs_are_unique(self) -> None:
        titles = ["Human Torch", "Human Torch/Void-Analyzing Fantastic Four", "Phase Five",
                  "Phase Six", "Deadpool", "Deadpool & Wolverine"]
        self.assertEqual(len({slug_for(t) for t in titles}), len(titles))


class TestQuery(unittest.TestCase):
    def test_redirects_are_always_resolved(self) -> None:
        # `AGENTS.md` §6: the trap that silently seeds the wrong page.
        self.assertEqual(build_query("Void")["redirects"], "1")

    def test_content_comes_from_the_main_slot(self) -> None:
        # Required since MediaWiki 1.32; without it the response carries no text.
        query = build_query("Gambit")
        self.assertEqual(query["rvslots"], "main")
        self.assertIn("content", query["rvprop"])

    def test_latest_revision_is_unbounded(self) -> None:
        query = build_query("Gambit")
        self.assertNotIn("rvstart", query)
        self.assertNotIn("rvdir", query)

    def test_historical_revision_walks_backwards_from_the_freeze(self) -> None:
        query = build_query("Gambit", before=FREEZE)
        self.assertEqual(query["rvstart"], "2024-08-09T00:00:00Z")
        self.assertEqual(query["rvdir"], "older")


class TestParse(unittest.TestCase):
    def test_happy_path(self) -> None:
        rev = parse_revision(response(), "Deadpool & Wolverine")
        self.assertEqual(rev.revid, 2019481)
        self.assertEqual(rev.timestamp, datetime(2024, 8, 8, 23, 57, 40, tzinfo=timezone.utc))
        self.assertIsNone(rev.redirected_from)

    def test_redirect_source_is_recorded(self) -> None:
        payload = response(redirects=[{"from": "Void", "to": "Deadpool & Wolverine"}])
        self.assertEqual(parse_revision(payload, "Void").redirected_from, "Void")

    def test_missing_page_raises(self) -> None:
        payload = {"query": {"pages": [{"title": "Nope", "missing": True}]}}
        with self.assertRaises(WikiError):
            parse_revision(payload, "Nope")

    def test_no_revision_in_range_raises(self) -> None:
        payload = {"query": {"pages": [{"pageid": 1, "title": "X", "revisions": []}]}}
        with self.assertRaises(WikiError):
            parse_revision(payload, "X")

    def test_missing_content_raises_rather_than_writing_an_empty_snapshot(self) -> None:
        payload = response()
        del payload["query"]["pages"][0]["revisions"][0]["slots"]
        with self.assertRaises(WikiError):
            parse_revision(payload, "Deadpool & Wolverine")

    def test_timestamp_is_timezone_aware(self) -> None:
        # The ledger rejects naive datetimes, so the adapter must never produce one.
        self.assertIsNotNone(parse_timestamp("2024-08-08T23:57:40Z").tzinfo)


class TestPageRevision(unittest.TestCase):
    def test_size_counts_utf8_bytes_not_characters(self) -> None:
        # MediaWiki reports bytes; the drift percentages in `seed-plan.md` §2 depend on it.
        text = "Cassandra Nova — an em dash"
        rev = replace(parse_revision(response(), "Deadpool & Wolverine"), content=text)
        self.assertEqual(rev.size, len(text.encode("utf-8")))
        self.assertGreater(rev.size, len(text))

    def test_sha256_is_of_the_content_alone(self) -> None:
        rev = replace(parse_revision(response(), "Deadpool & Wolverine"), content="abc")
        self.assertEqual(
            rev.sha256,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )


class TestCommittedSnapshots(unittest.TestCase):
    """The manifest is the provenance claim; this is what makes it checkable."""

    def setUp(self) -> None:
        manifest_path = SNAPSHOTS / "manifest.json"
        if not manifest_path.exists():
            self.skipTest("snapshots not pulled; run scripts/pull_snapshots.py")
        self.manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_every_page_pulled(self) -> None:
        self.assertEqual(self.manifest["failures"], [])
        self.assertEqual(len(self.manifest["pages"]), 12)

    def test_recorded_hashes_match_the_files_on_disk(self) -> None:
        checked = 0
        for page in self.manifest["pages"]:
            for state in self.manifest["states"]:
                entry = page.get(state)
                if entry is None:
                    continue
                blob = (SNAPSHOTS.parent / entry["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(blob).hexdigest(), entry["sha256"],
                                 f"{page['resolved_title']} [{state}] does not match manifest")
                self.assertEqual(len(blob), entry["size"])
                checked += 1
        self.assertGreater(checked, 0)

    def test_seed_predates_the_freeze(self) -> None:
        if "seed" not in self.manifest["states"]:
            self.skipTest("seed state not pulled")
        for page in self.manifest["pages"]:
            stamp = parse_timestamp(page["seed"]["timestamp"])
            self.assertLess(stamp, FREEZE, f"{page['resolved_title']} seed is after the freeze")

    def test_licence_version_is_pinned(self) -> None:
        # Blocks the attribution notice if it ever stops resolving.
        self.assertEqual(self.manifest["source"]["licence"]["version"], "3.0")


if __name__ == "__main__":
    unittest.main()
