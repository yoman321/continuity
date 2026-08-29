"""The classify stage: the prompt's four rules, and what the stage refuses to guess.

Every rule in `SYSTEM` came from a measurement, and the harness that produced those numbers is
not in the repo — so the rules are pinned here by assertion. That is weaker than re-running the
benchmark and stronger than nothing: a prompt edit that drops the precedence order or the
absence rule fails a test instead of quietly costing accuracy on the case it was written for.

The rest is refusal. A malformed answer, an unknown bucket, a conflict with one side missing —
each is an error rather than a default, because a guessed judgement enters the ledger with the
same authority as a real one.

No SDK and no network: `ModelSource` is a protocol, so a fake satisfies it.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from backend.agent.classify import (
    BUCKETS,
    OUTCOME_FOR,
    RESPONSE_SCHEMA,
    SYSTEM,
    Classifier,
    Verdict,
    parse,
)
from backend.agent.model import ModelError, ModelRequest
from backend.core.profile import MCU_FANDOM

#: The prompt is wrapped for reading, so a rule can span a line break. Assert on the rule, not
#: on where the text happens to fold.
FLAT = " ".join(SYSTEM.split())

CLAIM: dict[str, Any] = {
    "claim_id": "claim-0001",
    "page": "Gambit",
    "entity": {"title": "Gambit", "base": "Gambit", "variant": None, "is_variant": False},
    "text": "Gambit appears in Deadpool & Wolverine.",
    "section_heading": "",
}

VARIANT_CLAIM: dict[str, Any] = {
    **CLAIM,
    "page": "Human Torch/Void-Analyzing Fantastic Four",
    "entity": {
        "title": "Human Torch/Void-Analyzing Fantastic Four",
        "base": "Human Torch",
        "variant": "Void-Analyzing Fantastic Four",
        "is_variant": True,
    },
}

SEARCH: dict[str, Any] = {
    "objective": "Has Gambit been cast in Avengers: Doomsday?",
    "results": [
        {"url": "https://deadline.com/a", "domain": "deadline.com", "tier": 2,
         "publish_date": "2025-03-26", "excerpts": ["Channing Tatum's Gambit returns."]},
        {"url": "https://variety.com/b", "domain": "variety.com", "tier": 2,
         "publish_date": None, "excerpts": ["Gambit is in the Doomsday cast."]},
    ],
}


class Fake:
    """A model that answers from a script and records what it was asked."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.requests: list[ModelRequest] = []

    def run(self, request: ModelRequest) -> str:
        self.requests.append(request)
        return self.answers.pop(0) if self.answers else "{}"


def answer(**overrides: Any) -> str:
    return json.dumps({"bucket": "still_true", "reason": "the page already says this",
                       "off_entity": [], **overrides})


class TestThePromptRules(unittest.TestCase):
    """Four rules, each measured. A prompt edit that loses one fails here."""

    def test_rule_1_states_the_precedence_order(self) -> None:
        self.assertIn("stopping at the first that fits", FLAT)
        # conflicting is tested first, still_true last — the order is the fix, not the list.
        self.assertLess(SYSTEM.index("`conflicting`"), SYSTEM.index("`new`"))
        self.assertLess(SYSTEM.index("`new`"), SYSTEM.index("`still_true`"))

    def test_rule_2_says_an_absence_is_not_a_contradiction(self) -> None:
        self.assertIn("AN ABSENCE ON THE PAGE IS NOT A CONTRADICTION", FLAT)

    def test_rule_3_puts_the_subject_and_the_variant_in_the_prompt(self) -> None:
        filled = Classifier(MCU_FANDOM, Fake()).prompt(VARIANT_CLAIM, "section text", SEARCH)
        self.assertIn("SUBJECT: Human Torch/Void-Analyzing Fantastic Four", filled)
        self.assertIn("VARIANT of Human Torch", filled)
        self.assertIn("different subjects", filled)

    def test_rule_3_also_says_when_a_subject_is_not_a_variant(self) -> None:
        # "this is not a variant" is information too; leaving it out asks the model to assume.
        filled = Classifier(MCU_FANDOM, Fake()).prompt(CLAIM, "section text", SEARCH)
        self.assertIn("prime subject, not a variant", filled)

    def test_rule_4_orders_filtering_before_classifying(self) -> None:
        self.assertLess(SYSTEM.index("STEP 1 — FILTER"), SYSTEM.index("STEP 2 — CLASSIFY"))
        self.assertIn(
            "not weak evidence and not a disagreement — it is not evidence at all", FLAT
        )

    def test_an_emptied_batch_is_the_only_other_route_to_conflicting(self) -> None:
        self.assertIn("STEP 1 dropped every excerpt so nothing is left to judge", FLAT)

    def test_the_schema_admits_exactly_three_buckets(self) -> None:
        enum = RESPONSE_SCHEMA["properties"]["bucket"]["enum"]
        self.assertEqual(enum, list(BUCKETS))

    def test_every_bucket_maps_to_a_real_ledger_outcome(self) -> None:
        from backend.agent.tools import OUTCOMES

        self.assertEqual(set(OUTCOME_FOR), set(BUCKETS))
        self.assertTrue(set(OUTCOME_FOR.values()) <= set(OUTCOMES))


class TestThePrompt(unittest.TestCase):
    def test_the_excerpts_carry_their_publisher_and_tier(self) -> None:
        # The model reasons *over* a tier and never assigns one (`AGENTS.md` §2), so the tier
        # has to be in front of it.
        filled = Classifier(MCU_FANDOM, Fake()).prompt(CLAIM, "text", SEARCH)
        self.assertIn("deadline.com (tier 2)", filled)

    def test_the_section_text_is_included_verbatim(self) -> None:
        section = "==Biography==\nGambit is a mutant thief."
        filled = Classifier(MCU_FANDOM, Fake()).prompt(CLAIM, section, SEARCH)
        self.assertIn(section, filled)

    def test_an_empty_result_set_says_so_rather_than_being_blank(self) -> None:
        filled = Classifier(MCU_FANDOM, Fake()).prompt(CLAIM, "text", {"objective": "o",
                                                                       "results": []})
        self.assertIn("(none returned)", filled)


class TestClassify(unittest.TestCase):
    def test_a_verdict_comes_back_in_ledger_terms(self) -> None:
        verdict = Classifier(MCU_FANDOM, Fake(answer(bucket="new"))).classify(
            CLAIM, "section", SEARCH)

        self.assertEqual(verdict.bucket, "new")
        self.assertEqual(verdict.outcome, "changed")
        self.assertFalse(verdict.is_conflict)

    def test_still_true_maps_to_unchanged(self) -> None:
        verdict = Classifier(MCU_FANDOM, Fake(answer())).classify(CLAIM, "section", SEARCH)
        self.assertEqual(verdict.outcome, "unchanged")

    def test_a_conflict_carries_both_sides(self) -> None:
        verdict = Classifier(MCU_FANDOM, Fake(answer(
            bucket="conflicting",
            conflict={"note": "July vs August", "source_a": "https://a", "source_b": "https://b"},
        ))).classify(CLAIM, "section", SEARCH)

        self.assertEqual(verdict.outcome, "unresolved")
        self.assertEqual((verdict.source_a, verdict.source_b), ("https://a", "https://b"))

    def test_dropped_excerpts_are_reported(self) -> None:
        verdict = Classifier(MCU_FANDOM, Fake(answer(
            off_entity=["https://variety.com/b"]))).classify(CLAIM, "section", SEARCH)

        self.assertEqual(verdict.off_entity, ("https://variety.com/b",))

    def test_the_stage_writes_nothing_and_declares_the_schema_it_reads(self) -> None:
        fake = Fake(answer())
        Classifier(MCU_FANDOM, fake).classify(CLAIM, "section", SEARCH)

        self.assertEqual(fake.requests[0].schema, RESPONSE_SCHEMA)
        self.assertEqual(fake.requests[0].system, SYSTEM)

    def test_a_failed_search_is_never_classified(self) -> None:
        # Judging an empty batch would produce `conflicting` — an infrastructure failure
        # dressed as a finding about the world.
        fake = Fake(answer())
        with self.assertRaises(ModelError) as caught:
            Classifier(MCU_FANDOM, fake).classify(CLAIM, "section", {"error": "no key"})

        self.assertIn("Discard the round", str(caught.exception))
        self.assertEqual(fake.requests, [])  # and it never reached the model


class TestRefusals(unittest.TestCase):
    """A guessed judgement enters the ledger with the authority of a real one."""

    def test_a_non_json_answer_raises(self) -> None:
        with self.assertRaises(ModelError):
            parse("I think this is still true.")

    def test_an_unknown_bucket_raises_and_names_the_real_ones(self) -> None:
        with self.assertRaises(ModelError) as caught:
            parse(json.dumps({"bucket": "probably_fine", "reason": "r", "off_entity": []}))
        self.assertIn("still_true", str(caught.exception))

    def test_a_conflict_missing_a_side_raises(self) -> None:
        with self.assertRaises(ModelError) as caught:
            parse(json.dumps({"bucket": "conflicting", "reason": "r", "off_entity": [],
                              "conflict": {"note": "n", "source_a": "https://a"}}))
        self.assertIn("not reviewable", str(caught.exception))

    def test_a_bare_list_is_refused(self) -> None:
        with self.assertRaises(ModelError):
            parse("[]")

    def test_a_verdict_has_no_way_to_set_a_schedule(self) -> None:
        # The stage decides the bucket; `decay.py` decides what the bucket costs.
        forbidden = {"next_check_at", "check_interval", "confidence", "status"}
        self.assertEqual(set(Verdict.__dataclass_fields__) & forbidden, set())
        self.assertEqual(set(RESPONSE_SCHEMA["properties"]) & forbidden, set())


if __name__ == "__main__":
    unittest.main()
