"""The draft stage: what it refuses, and the check it runs on its own output.

Two things are worth testing here and they are not the prose the model writes. The first is
refusal — a bucket that produces no edit, an answer that would delete the anchor, a summary a
reviewer cannot read. The second is the arithmetic guard: `shape` held against the bucket, so
a `new` claim whose draft quietly rewrote the passage is flagged rather than approved-looking.

The guard is the point of the stage's design, so the test that matters most is the one where
the model returns a *plausible* edit that displaced text it was not asked to touch. Nothing
about that answer is malformed; it parses, it cites, it reads well, and it is wrong.

No SDK and no network: `ModelSource` is a protocol, so a fake satisfies it.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from typing import Any

from backend.agent.classify import Verdict
from backend.agent.draft import (
    DRAFTABLE,
    RESPONSE_SCHEMA,
    SYSTEM,
    Draft,
    Drafter,
    parse,
)
from backend.agent.model import ModelError, ModelRequest
from backend.core.ledger.decay import Wave
from backend.core.ledger.schema import Claim, ClaimKind, Source
from backend.core.profile import MCU_FANDOM
from backend.core.wiki import APPEND, MODIFY

NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)

#: `GAM-APP-01` from `scripts/build_demo_state.py` — the demo's opening claim, and the one the
#: shape rule was written against.
ANCHOR = "|movie = ''[[Deadpool & Wolverine]]''"
APPENDED = (
    "|movie = ''[[Deadpool & Wolverine]]''<br>''[[Avengers: Doomsday]]'' "
    "<small>(unreleased)</small><ref>https://deadline.com/2024/07/avengers-doomsday</ref>"
)
#: The failure the guard exists for: a well-formed answer that rewrote the field instead of
#: extending it. The released film is gone, and the diff still renders green.
REWRITTEN = "|movie = ''[[Avengers: Doomsday]]''<ref>https://deadline.com/2024/07/x</ref>"

SECTION = "'''Gambit''' is a mutant.\n{{Infobox\n|movie = ''[[Deadpool & Wolverine]]''\n}}"

EXCERPTS = {
    "https://deadline.com/2024/07/avengers-doomsday": (
        "Channing Tatum's Gambit joins 'Avengers: Doomsday' as cameras roll"
    ),
    "https://www.marvel.com/movies/avengers-doomsday": (
        "Robert Downey Jr., Chris Evans, Channing Tatum"
    ),
}

FINDING = Verdict(bucket="new", reason="The infobox lists one film; a second is announced.")


def claim(*, urls: tuple[str, ...] | None = None) -> Claim:
    chosen = urls if urls is not None else tuple(EXCERPTS)
    return Claim(
        claim_id="GAM-APP-01",
        page="Gambit",
        entity_ref=MCU_FANDOM.entity_ref("Gambit"),
        kind=ClaimKind.PROSE,
        wave=Wave.ANNOUNCEMENT_DRIVEN,
        text="Gambit's only film appearance is Deadpool & Wolverine.",
        wikitext_anchor=ANCHOR,
        section_index=0,
        section_heading="",
        sources=tuple(
            Source.create(url, EXCERPTS[url], NOW, domain_tiers=MCU_FANDOM.domain_tiers)
            for url in chosen
        ),
    )


class Fake:
    """A `ModelSource` that answers with whatever it was handed, and keeps the request."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer if isinstance(answer, str) else json.dumps(answer)
        self.seen: ModelRequest | None = None

    def run(self, request: ModelRequest) -> str:
        self.seen = request
        return self.answer


def drafted(after: str, *, summary: str = "Added Avengers: Doomsday to the film list.") -> Draft:
    fake = Fake({"after": after, "summary": summary})
    return Drafter(profile=MCU_FANDOM, source=fake).draft(claim(), SECTION, FINDING)


class TestTheGuard(unittest.TestCase):
    """The arithmetic the model does not get to report on."""

    def test_an_append_carries_no_flags(self) -> None:
        draft = drafted(APPENDED)
        self.assertEqual(draft.shape, APPEND)
        self.assertFalse(draft.overreached)
        self.assertEqual(draft.flags, ())

    def test_a_rewrite_of_a_new_claim_is_flagged(self) -> None:
        """The whole reason the stage checks itself. This answer parses, cites and reads
        well; the only thing wrong with it is that the released film is gone."""
        draft = drafted(REWRITTEN)
        self.assertEqual(draft.shape, MODIFY)
        self.assertTrue(draft.overreached)
        self.assertIn("overreached", draft.flags)

    def test_a_rewrite_is_not_flagged_when_the_bucket_expected_one(self) -> None:
        """`conflicting` reaches this stage after a human picked a side, and replacing the
        old reading is exactly the edit that resolution implies."""
        fake = Fake({"after": REWRITTEN, "summary": "Resolved in favour of the trade report."})
        resolved = Verdict(bucket="conflicting", reason="Sources disagree on the film list.")
        draft = Drafter(profile=MCU_FANDOM, source=fake).draft(claim(), SECTION, resolved)
        self.assertEqual(draft.shape, MODIFY)
        self.assertFalse(draft.overreached)

    def test_an_unchanged_anchor_is_flagged_as_empty(self) -> None:
        draft = drafted(ANCHOR)
        self.assertTrue(draft.is_empty)
        self.assertIn("empty", draft.flags)

    def test_a_claim_with_no_citable_source_is_flagged(self) -> None:
        """`marvel.com` names the actor and never the character, so nothing survives the
        citability filter and the edit would go out with no footnote (`citations.py`)."""
        fake = Fake({"after": APPENDED, "summary": "Added the second film."})
        only_marvel = claim(urls=("https://www.marvel.com/movies/avengers-doomsday",))
        draft = Drafter(profile=MCU_FANDOM, source=fake).draft(only_marvel, SECTION, FINDING)
        self.assertEqual(draft.citation, "")
        self.assertTrue(draft.uncited)
        self.assertIn("uncited", draft.flags)


class TestWhatItRefuses(unittest.TestCase):
    def test_a_bucket_with_no_edit_is_refused(self) -> None:
        fake = Fake({"after": APPENDED, "summary": "x"})
        still_true = Verdict(bucket="still_true", reason="The page already says this.")
        with self.assertRaises(ModelError):
            Drafter(profile=MCU_FANDOM, source=fake).draft(claim(), SECTION, still_true)
        self.assertIsNone(fake.seen, "the model must not be called for an undraftable bucket")

    def test_still_true_is_not_draftable(self) -> None:
        self.assertNotIn("still_true", DRAFTABLE)

    def test_a_blank_replacement_is_refused(self) -> None:
        """Not flagged — approved, this deletes the passage outright."""
        with self.assertRaises(ModelError):
            parse(json.dumps({"after": "   ", "summary": "Removed it."}))

    def test_a_missing_summary_is_refused(self) -> None:
        with self.assertRaises(ModelError):
            parse(json.dumps({"after": APPENDED}))

    def test_a_non_json_answer_is_refused(self) -> None:
        with self.assertRaises(ModelError):
            parse("here is your edit")

    def test_a_json_array_is_refused(self) -> None:
        with self.assertRaises(ModelError):
            parse(json.dumps([{"after": APPENDED, "summary": "x"}]))


class TestThePrompt(unittest.TestCase):
    """The rules that make the guard meaningful, pinned so an edit to `SYSTEM` fails loudly."""

    def setUp(self) -> None:
        self.flat = " ".join(SYSTEM.split())

    def test_it_says_add_do_not_rewrite(self) -> None:
        self.assertIn("ADD, DO NOT REWRITE", self.flat)
        self.assertIn("unchanged and unbroken", self.flat)

    def test_it_forbids_inventing_a_citation(self) -> None:
        self.assertIn("Never write a url that was not handed to you", self.flat)

    def test_it_forbids_a_new_section(self) -> None:
        """`AGENTS.md` §2: a fact with no home in the wiki's headings is out of scope."""
        self.assertIn("new section", self.flat)

    def test_it_does_not_ask_for_confidence(self) -> None:
        """Confidence is the core's, from the tier table. A model-assigned score would sit in
        the same field as a measured one."""
        self.assertNotIn("confidence", RESPONSE_SCHEMA["properties"])
        self.assertIn("Do not report your own confidence", self.flat)

    def test_the_anchor_and_the_section_are_both_in_the_prompt_and_distinguishable(self) -> None:
        """The anchor is what gets rewritten and the section is context. A prompt that blurs
        them gets the section back as the replacement."""
        fake = Fake({"after": APPENDED, "summary": "x"})
        Drafter(profile=MCU_FANDOM, source=fake).draft(claim(), SECTION, FINDING)
        assert fake.seen is not None
        self.assertIn("ANCHOR (rewrite exactly this):", fake.seen.prompt)
        self.assertIn(", for context:", fake.seen.prompt)
        self.assertIn(SECTION, fake.seen.prompt)

    def test_the_citation_excerpt_travels_with_its_url(self) -> None:
        """A url alone cannot tell the model what sentence the footnote will support."""
        fake = Fake({"after": APPENDED, "summary": "x"})
        Drafter(profile=MCU_FANDOM, source=fake).draft(claim(), SECTION, FINDING)
        assert fake.seen is not None
        self.assertIn(EXCERPTS["https://deadline.com/2024/07/avengers-doomsday"], fake.seen.prompt)


class TestTheRecord(unittest.TestCase):
    def test_confidence_comes_from_the_tiers_not_the_model(self) -> None:
        draft = drafted(APPENDED)
        self.assertEqual(draft.confidence, claim().recompute_confidence())

    def test_before_is_the_anchor_not_the_section(self) -> None:
        self.assertEqual(drafted(APPENDED).before, ANCHOR)

    def test_the_payload_is_the_shape_the_queue_renders(self) -> None:
        payload = drafted(APPENDED).payload(edit_id="edit-gam-app-01", page_slug="Gambit")
        for key in ("edit_id", "claim_id", "page", "page_slug", "section_index",
                    "section_heading", "before", "after", "diff", "summary", "rationale",
                    "confidence"):
            self.assertIn(key, payload)
        self.assertEqual(payload["section_heading"], "(lead)")

    def test_the_payload_rows_rebuild_both_sides(self) -> None:
        """The same round-trip `test_diff.py` asserts, through the record the FE is handed."""
        payload = drafted(APPENDED).payload(edit_id="e", page_slug="Gambit")
        rows: Any = payload["diff"]
        for side, kinds in (("before", ("context", "removed")), ("after", ("context", "added"))):
            rebuilt = "\n".join(
                "".join(s["text"] for s in row["segments"])
                for row in rows
                if row["kind"] in kinds
            )
            self.assertEqual(rebuilt, payload[side])


if __name__ == "__main__":
    unittest.main()
