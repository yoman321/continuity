"""The diff stage: the case text cannot see, and the floor it falls back to.

One test here carries the argument for the whole stage — `test_an_appended_negation_is_a_
reversal`. The draft adds a clause and removes nothing, so containment holds and
`diff.shape()` returns `APPEND`; the assertion the page made is nonetheless gone. If that case
did not exist the stage would be an expensive way to re-derive arithmetic.

The rest is the perimeter: an empty reading refused, an unknown disposition refused, and a dead
model degrading to the textual shape instead of failing the run.

No SDK and no network: `ModelSource` is a protocol, so a fake satisfies it.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from backend.agent.draft import Draft
from backend.agent.model import ModelError, ModelRequest
from backend.agent.semantic_diff import (
    ADDED,
    ADDITIVE,
    DESTRUCTIVE,
    DROPPED,
    KEPT,
    REVERSED,
    SYSTEM,
    Change,
    Review,
    Reviewer,
    fallback,
    parse,
)
from backend.core.profile import MCU_FANDOM
from backend.core.wiki import APPEND, MODIFY

BEFORE = "Gambit appears in ''[[Deadpool & Wolverine]]''."

#: Nothing removed, one clause added — and the page no longer says what it said. `shape()`
#: cannot see this, which is the whole reason the stage is a model call.
NEGATED = (
    "Gambit appears in ''[[Deadpool & Wolverine]]''. Marvel later confirmed the character "
    "was cut from the final release."
)

#: The honest append: a second fact, the first untouched.
EXTENDED = (
    "Gambit appears in ''[[Deadpool & Wolverine]]'' and ''[[Avengers: Doomsday]]''."
)


def draft(after: str, *, bucket: str = "new", before: str = BEFORE) -> Draft:
    return Draft(
        claim_id="GAM-APP-01",
        page="Gambit",
        section_index=0,
        section_heading="",
        before=before,
        after=after,
        summary="Recorded the second film.",
        citation="https://deadline.com/2024/07/avengers-doomsday",
        bucket=bucket,
        confidence=0.8,
    )


class Fake:
    """A `ModelSource` that answers with what it was handed, or raises what it was handed."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.seen: ModelRequest | None = None

    def run(self, request: ModelRequest) -> str:
        self.seen = request
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


def reviewed(after: str, changes: list[dict[str, str]], *, bucket: str = "new") -> Review:
    fake = Fake({"changes": changes})
    return Reviewer(profile=MCU_FANDOM, source=fake).review(draft(after, bucket=bucket))


class TestTheCaseTextCannotSee(unittest.TestCase):
    """The stage's reason to exist."""

    def test_the_negation_is_textually_an_append(self) -> None:
        """Established first, so the next test is measuring something real: the string
        comparison genuinely passes this edit."""
        from backend.core.wiki import shape

        self.assertEqual(shape(BEFORE, NEGATED), APPEND)
        self.assertFalse(draft(NEGATED).overreached)
        self.assertEqual(draft(NEGATED).flags, ())

    def test_an_appended_negation_is_a_reversal(self) -> None:
        review = reviewed(
            NEGATED,
            [
                {"assertion": "Gambit appears in Deadpool & Wolverine.",
                 "disposition": REVERSED, "note": "'was cut from the final release'"},
                {"assertion": "The character was cut.", "disposition": ADDED},
            ],
        )
        self.assertEqual(review.verdict, DESTRUCTIVE)
        self.assertTrue(review.overreached)
        self.assertEqual(len(review.reversals), 1)

    def test_the_disagreement_between_the_two_readings_is_flagged(self) -> None:
        """`APPEND` and `DESTRUCTIVE` together. A reviewer trusting the green diff approves
        this, and the textual guard agrees with them — so the flag has to say otherwise."""
        review = reviewed(
            NEGATED,
            [{"assertion": "Gambit appears in D&W.", "disposition": REVERSED}],
        )
        self.assertEqual(review.text_shape, APPEND)
        self.assertTrue(review.hidden_by_text)
        self.assertIn("hidden_by_text", review.flags)

    def test_an_honest_append_is_additive(self) -> None:
        review = reviewed(
            EXTENDED,
            [
                {"assertion": "Gambit appears in Deadpool & Wolverine.", "disposition": KEPT},
                {"assertion": "Gambit appears in Avengers: Doomsday.", "disposition": ADDED},
            ],
        )
        self.assertEqual(review.verdict, ADDITIVE)
        self.assertFalse(review.overreached)
        self.assertFalse(review.hidden_by_text)
        self.assertEqual(review.flags, ())

    def test_rewording_that_keeps_the_idea_is_not_destructive(self) -> None:
        """The other direction the two readings come apart: text displaced, nothing lost.
        `shape()` flags it; the reading clears it."""
        rephrased = "Gambit appears in the 2024 film ''[[Deadpool & Wolverine]]''."
        review = reviewed(
            rephrased,
            [
                {"assertion": "Gambit appears in Deadpool & Wolverine.", "disposition": KEPT},
                {"assertion": "The film was released in 2024.", "disposition": ADDED},
            ],
        )
        self.assertEqual(review.text_shape, MODIFY)
        self.assertEqual(review.verdict, ADDITIVE)
        self.assertFalse(review.overreached)


class TestTheGuardIsBucketAware(unittest.TestCase):
    def test_a_destructive_edit_on_a_resolved_conflict_is_expected(self) -> None:
        review = reviewed(
            "Gambit does not appear in ''[[Deadpool & Wolverine]]''.",
            [{"assertion": "Gambit appears in Deadpool & Wolverine.", "disposition": REVERSED}],
            bucket="conflicting",
        )
        self.assertEqual(review.verdict, DESTRUCTIVE)
        self.assertFalse(review.overreached)


class TestTheFallback(unittest.TestCase):
    """A dead credential degrades the gate; it never removes it (`CLAUDE.md` §3)."""

    def test_an_unavailable_model_falls_back_to_the_text_shape(self) -> None:
        fake = Fake(ModelError("no recording for this judgement"))
        review = Reviewer(profile=MCU_FANDOM, source=fake).review(draft(NEGATED))
        self.assertTrue(review.text_only)
        self.assertIn("text_only", review.flags)

    def test_the_fallback_calls_displaced_text_destructive(self) -> None:
        """Nothing read it, so the honest verdict is that something went. An empty change
        list would have scored `additive` and waved the edit through."""
        review = fallback(draft("Gambit appears in ''[[Avengers: Doomsday]]''."))
        self.assertEqual(review.text_shape, MODIFY)
        self.assertEqual(review.verdict, DESTRUCTIVE)
        self.assertEqual(review.changes[0].disposition, DROPPED)

    def test_the_fallback_clears_a_textual_append(self) -> None:
        review = fallback(draft(NEGATED))
        self.assertEqual(review.verdict, ADDITIVE)
        self.assertTrue(review.text_only)

    def test_the_fallback_cannot_see_the_negation_and_says_so(self) -> None:
        """The limit, asserted rather than assumed: degraded, this stage is exactly as blind
        as the arithmetic it fell back to. `text_only` is what tells the reviewer."""
        review = fallback(draft(NEGATED))
        self.assertFalse(review.hidden_by_text)
        self.assertIn("text_only", review.flags)


class TestWhatItRefuses(unittest.TestCase):
    def test_an_empty_reading_is_refused(self) -> None:
        """Scored as written it would be `additive`, which is a pass."""
        with self.assertRaises(ModelError):
            parse(json.dumps({"changes": []}))

    def test_an_unknown_disposition_is_refused(self) -> None:
        with self.assertRaises(ModelError):
            parse(json.dumps({"changes": [{"assertion": "x", "disposition": "softened"}]}))

    def test_an_assertion_with_no_text_is_refused(self) -> None:
        with self.assertRaises(ModelError):
            parse(json.dumps({"changes": [{"assertion": "  ", "disposition": KEPT}]}))

    def test_a_non_json_answer_is_refused(self) -> None:
        with self.assertRaises(ModelError):
            parse("the edit looks fine")

    def test_a_malformed_answer_is_not_degraded_around(self) -> None:
        """Unavailability is a fallback; a schema disagreement is a defect. Swallowing it
        would leave the stage permanently degraded and silent about it."""
        fake = Fake("not json at all")
        with self.assertRaises(ModelError):
            Reviewer(profile=MCU_FANDOM, source=fake).review(draft(NEGATED))


class TestThePrompt(unittest.TestCase):
    def setUp(self) -> None:
        self.flat = " ".join(SYSTEM.split())

    def test_it_states_the_appended_negation_rule(self) -> None:
        self.assertIn("text that was only ADDED can still REVERSE an assertion", self.flat)

    def test_it_says_rewording_is_kept(self) -> None:
        self.assertIn("you are tracking the assertion, not the sentence", self.flat)

    def test_the_motive_is_withheld(self) -> None:
        """No sources, no objective, no classification — a reader told why the edit was made
        explains it instead of examining it."""
        fake = Fake({"changes": [{"assertion": "x", "disposition": KEPT}]})
        Reviewer(profile=MCU_FANDOM, source=fake).review(draft(EXTENDED))
        assert fake.seen is not None
        self.assertNotIn("deadline.com", fake.seen.prompt)
        self.assertNotIn("new", fake.seen.prompt.lower().split())
        self.assertIn("BEFORE:", fake.seen.prompt)
        self.assertIn("AFTER:", fake.seen.prompt)


class TestThePayload(unittest.TestCase):
    def test_it_carries_both_readings(self) -> None:
        review = Review(
            claim_id="GAM-APP-01",
            bucket="new",
            text_shape=APPEND,
            changes=(Change("Gambit appears in D&W.", REVERSED, "'was cut'"),),
        )
        payload = review.payload()
        self.assertEqual(payload["verdict"], DESTRUCTIVE)
        self.assertEqual(payload["text_shape"], APPEND)
        self.assertIn("hidden_by_text", payload["flags"])
        self.assertEqual(payload["changes"][0]["disposition"], REVERSED)


if __name__ == "__main__":
    unittest.main()
