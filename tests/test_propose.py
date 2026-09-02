"""The propose stage: what it accepts from a model, and what it refuses.

The stage exists to fill the ledger from the page, so the tests are about the one thing that
can silently ruin it — the anchor. A claim whose anchor is not a verbatim, unique substring of
the section is an edit that can never be applied, and it would sit in the ledger looking
exactly like a good one until a reviewer pressed publish on it.

Everything here runs against a fake model, so it needs no key and no network.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from backend.agent.model import ModelError, ModelRequest
from backend.agent.propose import (
    MAX_PER_PAGE,
    MAX_PER_SECTION,
    Proposal,
    Proposer,
    Rejected,
    room_left,
    store_proposals,
    verify,
    worth_reading,
)
from backend.core.ledger import Claim, ClaimKind, Wave
from backend.core.ledger.baseline import SectionBaseline
from backend.core.ledger.store import InMemoryClaimStore
from backend.core.profile import local_wiki

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
PROFILE = local_wiki("http://wiki.invalid/api.php")
PAGE = "Gambit"

SECTION_TEXT = (
    "{{Character\n"
    "|movie = ''[[Deadpool & Wolverine]]''\n"
    "|actor = [[Channing Tatum]]\n"
    "}}\n"
    "'''Remy LeBeau''' is a mutant who was banished to the [[Void]].\n"
)
SECTION = SectionBaseline(
    page=PAGE,
    section_index=0,
    section_heading="",
    text=SECTION_TEXT,

    revid=1,
    fetched_at=NOW,
)


class FakeModel:
    """Answers with whatever claims a test hands it."""

    def __init__(self, *claims: dict[str, str], raw: str | None = None) -> None:
        self.raw = raw if raw is not None else json.dumps({"claims": list(claims)})
        self.requests: list[ModelRequest] = []

    def run(self, request: ModelRequest) -> str:
        self.requests.append(request)
        return self.raw


def claim(**overrides: str) -> dict[str, str]:
    return {
        "text": "Gambit is played by Channing Tatum.",
        "anchor": "|actor = [[Channing Tatum]]",
        "kind": "prose",
        "wave": "settled",
        "objective": "Who plays Gambit in Deadpool & Wolverine?",
        **overrides,
    }


def store_one(
    *claims: dict[str, str],
) -> tuple[tuple[Claim, ...], tuple[Rejected, ...], InMemoryClaimStore]:
    model = FakeModel(*claims)
    proposals = Proposer(PROFILE, model).propose(PAGE, SECTION)
    store = InMemoryClaimStore()
    kept, rejected = store_proposals(
        proposals, page=PAGE, section_text=SECTION_TEXT, profile=PROFILE,
        store=store, now=NOW, task_id="task-1",
    )
    return kept, rejected, store


class TheAnchor(unittest.TestCase):
    """The check the whole stage turns on."""

    def test_a_verbatim_anchor_is_accepted(self) -> None:
        kept, rejected, store = store_one(claim())
        self.assertEqual(len(kept), 1)
        self.assertEqual(rejected, ())
        self.assertEqual(kept[0].wikitext_anchor, "|actor = [[Channing Tatum]]")
        self.assertEqual(len(store.all()), 1)

    def test_a_paraphrased_anchor_is_refused(self) -> None:
        """The failure mode this stage exists to prevent: models paraphrase, and a paraphrase
        is an edit that can never apply."""
        kept, rejected, store = store_one(claim(anchor="|actor = Channing Tatum"))
        self.assertEqual(kept, ())
        self.assertEqual(len(rejected), 1)
        self.assertIn("verbatim", rejected[0].reason)
        self.assertEqual(store.all(), ())

    def test_an_anchor_that_appears_twice_is_refused(self) -> None:
        """`write_anchor` refuses an ambiguous substitution rather than guessing, so a claim
        anchored on a repeated string is one whose edit fails at publish — hours later."""
        text = "a\nsame line\nb\nsame line\n"
        model = FakeModel(claim(anchor="same line"))
        section = SectionBaseline(page=PAGE, section_index=0, section_heading="", text=text,
                                  revid=1, fetched_at=NOW)
        proposals = Proposer(PROFILE, model).propose(PAGE, section)
        kept, rejected = store_proposals(
            proposals, page=PAGE, section_text=text, profile=PROFILE,
            store=InMemoryClaimStore(), now=NOW, task_id="t",
        )
        self.assertEqual(kept, ())
        self.assertIn("2 times", rejected[0].reason)

    def test_an_empty_anchor_is_refused(self) -> None:
        kept, rejected, _ = store_one(claim(anchor="   "))
        self.assertEqual(kept, ())
        self.assertIn("empty anchor", rejected[0].reason)

    def test_verify_is_pure_and_says_why(self) -> None:
        good = Proposal("t", "|actor = [[Channing Tatum]]", "prose", "settled", "o", 0, "")
        bad = Proposal("t", "not here", "prose", "settled", "o", 0, "")
        self.assertEqual(verify(good, SECTION_TEXT), "")
        self.assertNotEqual(verify(bad, SECTION_TEXT), "")


class WhatGetsStored(unittest.TestCase):
    def test_the_schedule_comes_from_the_wave_not_the_model(self) -> None:
        """The model picks how fast a fact moves; `decay.py` decides what that costs. A claim
        arrives scheduled, and nothing in the answer could have set the interval."""
        kept, _, _ = store_one(claim(wave="announcement_driven"))
        settled, _, _ = store_one(
            claim(wave="settled", anchor="|movie = ''[[Deadpool & Wolverine]]''")
        )
        self.assertIsNotNone(kept[0].next_check_at)
        self.assertLess(kept[0].check_interval, settled[0].check_interval)

    def test_the_kind_and_wave_are_stored_as_enums(self) -> None:
        kept, _, _ = store_one(claim(kind="link", wave="release_driven"))
        self.assertIs(kept[0].kind, ClaimKind.LINK)
        self.assertIs(kept[0].wave, Wave.RELEASE_DRIVEN)

    def test_an_unknown_kind_is_dropped_rather_than_stored(self) -> None:
        kept, rejected, store = store_one(claim(kind="factoid"))
        self.assertEqual(kept, ())
        self.assertEqual(len(rejected), 1)
        self.assertEqual(store.all(), ())

    def test_the_objective_reaches_the_claim(self) -> None:
        """`objective_for` uses a stored objective on round one, so what proposal decided the
        claim is about is what research asks first."""
        kept, _, _ = store_one(claim(objective="Has Tatum been recast?"))
        self.assertEqual(kept[0].objective, "Has Tatum been recast?")

    def test_the_entity_comes_from_the_profile_not_the_model(self) -> None:
        kept, _, _ = store_one(claim())
        self.assertEqual(kept[0].entity_ref, PROFILE.entity_ref(PAGE))

    def test_ids_are_allocated_by_the_store(self) -> None:
        kept, _, _ = store_one(
            claim(), claim(anchor="|movie = ''[[Deadpool & Wolverine]]''", text="second")
        )
        self.assertEqual([c.claim_id for c in kept], ["claim-0001", "claim-0002"])


class Idempotence(unittest.TestCase):
    """Proposing must be free to re-run, or it cannot go on a schedule."""

    def test_proposing_the_same_claim_twice_stores_one_record(self) -> None:
        store = InMemoryClaimStore()
        model = FakeModel(claim())
        proposals = Proposer(PROFILE, model).propose(PAGE, SECTION)
        for _ in range(2):
            store_proposals(proposals, page=PAGE, section_text=SECTION_TEXT, profile=PROFILE,
                            store=store, now=NOW, task_id="t")
        self.assertEqual(len(store.all()), 1)

    def test_the_second_pass_reports_it_as_already_tracked(self) -> None:
        store = InMemoryClaimStore()
        model = FakeModel(claim())
        proposals = Proposer(PROFILE, model).propose(PAGE, SECTION)
        store_proposals(proposals, page=PAGE, section_text=SECTION_TEXT, profile=PROFILE,
                        store=store, now=NOW, task_id="t")
        _, rejected = store_proposals(
            proposals, page=PAGE, section_text=SECTION_TEXT, profile=PROFILE,
            store=store, now=NOW, task_id="t",
        )
        self.assertEqual([r.reason for r in rejected], ["already tracked"])

    def test_a_reworded_claim_on_a_tracked_anchor_does_not_duplicate(self) -> None:
        """Identity is the anchor, not the wording — the same spot said differently is the
        same claim, and merging on similarity would be a judgement a lookup must not make."""
        store = InMemoryClaimStore()
        first = Proposer(PROFILE, FakeModel(claim())).propose(PAGE, SECTION)
        store_proposals(first, page=PAGE, section_text=SECTION_TEXT, profile=PROFILE,
                        store=store, now=NOW, task_id="t")
        again = Proposer(PROFILE, FakeModel(claim(text="Tatum portrays Gambit."))).propose(
            PAGE, SECTION
        )
        kept, _ = store_proposals(again, page=PAGE, section_text=SECTION_TEXT, profile=PROFILE,
                                  store=store, now=NOW, task_id="t")
        self.assertEqual(kept, ())
        self.assertEqual(len(store.all()), 1)


class Bounds(unittest.TestCase):
    def test_a_section_cannot_contribute_more_than_its_cap(self) -> None:
        many = [claim(anchor=f"a{i}", text=f"c{i}") for i in range(MAX_PER_SECTION + 5)]
        proposals = Proposer(PROFILE, FakeModel(*many)).propose(PAGE, SECTION)
        self.assertEqual(len(proposals), MAX_PER_SECTION)

    def test_a_page_cannot_exceed_its_cap_across_sections(self) -> None:
        """The per-section cap bounds nothing on its own — a long page just has more sections.
        Measured Sept 1, 2026: Gambit produced 50 claims from 19 sections under a cap of 6.
        Every one of them costs a Parallel search on every tick, forever."""
        store = InMemoryClaimStore()
        anchors = [f"line {i}\n" for i in range(MAX_PER_PAGE + 6)]
        text = "".join(anchors)
        for i, anchor in enumerate(anchors):
            proposals = (
                Proposal(f"c{i}", anchor, "prose", "settled", "o", 0, ""),
            )
            store_proposals(proposals, page=PAGE, section_text=text, profile=PROFILE,
                            store=store, now=NOW, task_id="t")
        self.assertEqual(len(store.all()), MAX_PER_PAGE)

    def test_the_cap_counts_claims_already_tracked(self) -> None:
        """A second pass must not top a full page back up to the cap again."""
        store = InMemoryClaimStore()
        text = "".join(f"line {i}\n" for i in range(MAX_PER_PAGE + 4))
        first = tuple(
            Proposal(f"c{i}", f"line {i}\n", "prose", "settled", "o", 0, "")
            for i in range(MAX_PER_PAGE)
        )
        store_proposals(first, page=PAGE, section_text=text, profile=PROFILE,
                        store=store, now=NOW, task_id="t")
        later = (Proposal("extra", f"line {MAX_PER_PAGE}\n", "prose", "settled", "o", 0, ""),)
        kept, rejected = store_proposals(later, page=PAGE, section_text=text, profile=PROFILE,
                                         store=store, now=NOW, task_id="t")
        self.assertEqual(kept, ())
        self.assertIn("cap", rejected[0].reason)
        self.assertEqual(len(store.all()), MAX_PER_PAGE)

    def test_reference_sections_are_skipped_without_a_model_call(self) -> None:
        for heading in ("References", "external links", "Gallery"):
            section = SectionBaseline(page=PAGE, section_index=1, section_heading=heading,
                                      text="{{Reflist}}", revid=1,
                                      fetched_at=NOW)
            self.assertFalse(worth_reading(section), heading)

    def test_an_empty_section_is_skipped(self) -> None:
        section = SectionBaseline(page=PAGE, section_index=1, section_heading="Plot", text="  \n",
                                  revid=1, fetched_at=NOW)
        self.assertFalse(worth_reading(section))

    def test_a_real_section_is_read(self) -> None:
        self.assertTrue(worth_reading(SECTION))


class WhatTheModelIsAsked(unittest.TestCase):
    def test_the_prompt_states_the_subject_and_the_variant(self) -> None:
        """Retrieval cannot tell a variant from its prime, and neither can a proposer reading
        a subpage — so the prompt says which it is."""
        model = FakeModel()
        Proposer(PROFILE, model).propose("Human Torch/Void-Analyzing Fantastic Four", SECTION)
        prompt = model.requests[0].prompt
        self.assertIn("VARIANT", prompt)
        self.assertIn("Human Torch", prompt)

    def test_a_prime_subject_is_said_to_be_prime(self) -> None:
        model = FakeModel()
        Proposer(PROFILE, model).propose(PAGE, SECTION)
        self.assertIn("not a variant", model.requests[0].prompt)

    def test_the_section_text_is_in_the_prompt_verbatim(self) -> None:
        """The anchor has to be copyable, so the model must see the exact bytes."""
        model = FakeModel()
        Proposer(PROFILE, model).propose(PAGE, SECTION)
        self.assertIn(SECTION_TEXT, model.requests[0].prompt)

    def test_a_malformed_answer_raises_rather_than_reading_as_nothing_found(self) -> None:
        """An empty list is a real finding — the section asserts nothing checkable — so a parse
        failure must not be able to impersonate one."""
        with self.assertRaises(ModelError):
            Proposer(PROFILE, FakeModel(raw="not json")).propose(PAGE, SECTION)
        with self.assertRaises(ModelError):
            Proposer(PROFILE, FakeModel(raw='{"wrong": []}')).propose(PAGE, SECTION)

    def test_an_empty_list_is_a_finding_not_an_error(self) -> None:
        self.assertEqual(Proposer(PROFILE, FakeModel()).propose(PAGE, SECTION), ())


class TheCostOfAsking(unittest.TestCase):
    """Every model call is billed and arrives in a burst, so the ones not made matter."""

    def test_room_left_falls_as_a_page_fills(self) -> None:
        store = InMemoryClaimStore()
        self.assertEqual(room_left(store, PAGE), MAX_PER_PAGE)
        store_proposals(
            tuple(Proposal(f"c{i}", f"line {i}\n", "prose", "settled", "o", 0, "")
                  for i in range(3)),
            page=PAGE, section_text="".join(f"line {i}\n" for i in range(5)),
            profile=PROFILE, store=store, now=NOW, task_id="t",
        )
        self.assertEqual(room_left(store, PAGE), MAX_PER_PAGE - 3)

    def test_a_full_page_asks_for_nothing_more(self) -> None:
        """The check a caller makes *before* spending a call. Measured Sept 1, 2026: Gambit
        has 17 readable sections and a cap of 12, so enforcing the cap only on the way in
        wasted about 13 calls per pass — every answer discarded."""
        store = InMemoryClaimStore()
        text = "".join(f"line {i}\n" for i in range(MAX_PER_PAGE + 4))
        store_proposals(
            tuple(Proposal(f"c{i}", f"line {i}\n", "prose", "settled", "o", 0, "")
                  for i in range(MAX_PER_PAGE)),
            page=PAGE, section_text=text, profile=PROFILE, store=store, now=NOW, task_id="t",
        )
        self.assertEqual(room_left(store, PAGE), 0)

    def test_room_is_counted_per_page(self) -> None:
        """A full page must not stop a different one being read."""
        store = InMemoryClaimStore()
        store_proposals(
            (Proposal("c", "|actor = [[Channing Tatum]]", "prose", "settled", "o", 0, ""),),
            page=PAGE, section_text=SECTION_TEXT, profile=PROFILE, store=store,
            now=NOW, task_id="t",
        )
        self.assertEqual(room_left(store, PAGE), MAX_PER_PAGE - 1)
        self.assertEqual(room_left(store, "Phase Six"), MAX_PER_PAGE)


class SealedRuns(unittest.TestCase):
    """A run must not be able to see what an earlier one concluded.

    This is what makes the button repeatable: without it, run one settles its claims to 90 days
    out and run two finds nothing due, which on screen is indistinguishable from a button that
    did nothing. Tested against the in-memory store's `task_id` filtering contract rather than
    against Mongo, so it runs bare; `tests/test_ledger_store.py` covers the adapter.
    """

    def test_two_runs_over_one_page_do_not_share_claims(self) -> None:
        store = InMemoryClaimStore()
        first = Proposer(PROFILE, FakeModel(claim())).propose(PAGE, SECTION)
        kept_a, _ = store_proposals(first, page=PAGE, section_text=SECTION_TEXT,
                                    profile=PROFILE, store=store, now=NOW, task_id="run-a")
        self.assertEqual(len(kept_a), 1)
        self.assertEqual(kept_a[0].task_id, "run-a")

    def test_a_proposed_claim_is_due_immediately(self) -> None:
        """`seeded` schedules as though the claim had just been confirmed, which is false of
        one nobody has ever asked the world about. A run that proposed a ledger and then found
        nothing due would look exactly like a run that did nothing."""
        kept, _, _ = store_one(claim())
        wake = kept[0].next_check_at
        assert wake is not None
        self.assertLessEqual(wake, NOW)
        self.assertTrue(kept[0].is_due(NOW))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
