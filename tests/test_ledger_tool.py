"""The ledger tool: what a node may decide, and what only the core may.

The tool is the seam where a language model touches persistent state, so most of what is
pinned here is refusal. A model reports an outcome; it never writes an interval, a wake time
or a confidence, and there is deliberately no argument that would let it. The rest is the
audit stage's arithmetic — proposing the same claim twice is a no-op, because the alternative
is a ledger that doubles in size every cycle.

Stdlib only, and no ADK: the graph wraps these methods in `FunctionTool` where it is built,
so the tool itself is testable with nothing installed.
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.agent.tools import DEFAULT_DUE_LIMIT, Ledger
from backend.core.ledger import (
    MAX_RESEARCH_ROUNDS,
    Claim,
    ClaimKind,
    ClaimStatus,
    Wave,
)
from backend.core.profile import MCU_FANDOM

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

GAMBIT: dict[str, Any] = {
    "page": "Gambit",
    "text": "Gambit appears in Deadpool & Wolverine.",
    "wikitext_anchor": "|movie = ''[[Deadpool & Wolverine]]''",
    "section_heading": "",
    "section_index": 0,
    "kind": "prose",
    "wave": "announcement_driven",
}


class Clock:
    """A hand-wound clock. Time is load-bearing here — every interval is measured from it —
    so it is injected rather than read off the wall."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def ledger(clock: Clock | None = None, claims: tuple[Claim, ...] = ()) -> Ledger:
    return Ledger.in_memory(MCU_FANDOM, claims, clock=clock or Clock())


def tracked(tool: Ledger, **overrides: Any) -> dict[str, Any]:
    return tool.track_claim(**{**GAMBIT, **overrides})


class TestClaimIdentity(unittest.TestCase):
    """Ids are allocated and never move; recognising a claim is a lookup, not a recomputation."""

    def test_ids_are_a_counter_and_carry_no_meaning(self) -> None:
        tool = ledger()
        first = tracked(tool, wikitext_anchor="a")["claim_id"]
        second = tracked(tool, wikitext_anchor="b")["claim_id"]

        self.assertEqual([first, second], ["claim-0001", "claim-0002"])

    def test_the_counter_resumes_rather_than_reusing_a_number(self) -> None:
        tool = ledger()
        tracked(tool, wikitext_anchor="a")
        tracked(tool, wikitext_anchor="b")
        reopened = Ledger.in_memory(MCU_FANDOM, tool.store.all(), clock=Clock())

        self.assertEqual(tracked(reopened, wikitext_anchor="c")["claim_id"], "claim-0003")

    def test_tracking_the_same_claim_twice_stores_one_record(self) -> None:
        tool = ledger()
        first = tracked(tool)
        again = tracked(tool, text="Gambit is in Deadpool & Wolverine.")

        self.assertEqual(first["result"], "tracked")
        self.assertEqual(again["result"], "already_tracked")
        self.assertEqual(again["claim_id"], first["claim_id"])
        self.assertEqual(len(tool.store.all()), 1)
        # The stored record is the first one: re-proposing does not overwrite research
        # already attached to it.
        self.assertEqual(again["text"], GAMBIT["text"])

    def test_the_same_anchor_on_another_page_is_another_claim(self) -> None:
        tool = ledger()
        first = tracked(tool)
        other = tracked(tool, page="Phase Six")

        self.assertNotEqual(other["claim_id"], first["claim_id"])
        self.assertEqual(len(tool.store.all()), 2)

    def test_an_anchor_is_matched_exactly_and_never_loosely(self) -> None:
        tool = ledger()
        first = tracked(tool)
        # One character apart. Deciding that two wordings mean the same claim is the audit
        # model's judgement; a lookup that guessed would silently merge two real claims.
        near = tracked(tool, wikitext_anchor=GAMBIT["wikitext_anchor"] + " ")

        self.assertNotEqual(near["claim_id"], first["claim_id"])

    def test_an_id_survives_the_anchor_being_rewritten(self) -> None:
        # The whole reason identity is allocated rather than derived: applying an edit rewrites
        # the anchor, and a content-derived id would re-key the record and dangle every
        # `ripple_targets` entry pointing at it.
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]
        stored = tool.store.get(claim_id)
        assert stored is not None

        tool.store.put(replace(stored, wikitext_anchor="|movie = something else"))

        self.assertEqual(tool.read_claim(claim_id)["claim_id"], claim_id)
        self.assertEqual(len(tool.store.all()), 1)


class TestTracking(unittest.TestCase):
    def test_a_tracked_claim_is_scheduled_by_its_wave(self) -> None:
        clock = Clock()
        view = tracked(ledger(clock))

        # ANNOUNCEMENT_DRIVEN seeds at 24h. The tool schedules on the way in, which is what
        # satisfies the store's "never store a null wake time" contract.
        self.assertEqual(view["check_interval_hours"], 24.0)
        self.assertEqual(view["next_check_at"], (NOW + timedelta(hours=24)).isoformat())

    def test_the_entity_comes_from_the_profile_not_the_caller(self) -> None:
        view = tracked(ledger(), page="Blade/Universe Defender Blade")

        # MCU Fandom enables mainspace subpages, so this is a variant of Blade — a distinction
        # the model is never asked to make.
        self.assertEqual(view["entity"]["base"], "Blade")
        self.assertEqual(view["entity"]["variant"], "Universe Defender Blade")
        self.assertTrue(view["entity"]["is_variant"])

    def test_an_unknown_kind_is_a_value_listing_the_real_ones(self) -> None:
        view = tracked(ledger(), kind="factoid")

        self.assertIn("factoid", view["error"])
        self.assertEqual(view["allowed"], [k.value for k in ClaimKind])

    def test_an_unknown_wave_is_a_value_listing_the_real_ones(self) -> None:
        view = tracked(ledger(), wave="fast")

        self.assertIn("fast", view["error"])
        self.assertEqual(view["allowed"], [w.value for w in Wave])

    def test_what_the_call_did_and_what_the_claim_is_are_different_keys(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        view = tool.record_outcome(claim_id, "changed")

        # `result` is the call's; `status` is the claim's. They collided once, silently.
        self.assertEqual(view["result"], "recorded")
        self.assertEqual(view["status"], ClaimStatus.UNRESOLVED.value)

    def test_a_rejected_claim_is_not_stored(self) -> None:
        tool = ledger()
        tracked(tool, kind="factoid")

        self.assertEqual(len(tool.store.all()), 0)


class TestTheModelCannotWriteTheSchedule(unittest.TestCase):
    """The reason this tool exists instead of a passthrough over `ClaimStore.put`."""

    def test_no_write_method_accepts_a_schedule_or_a_confidence(self) -> None:
        forbidden = {"next_check_at", "check_interval", "confidence", "status", "tier"}
        for name in ("track_claim", "record_research", "record_outcome", "link_ripple_targets"):
            with self.subTest(method=name):
                args = set(getattr(Ledger, name).__code__.co_varnames)
                self.assertEqual(args & forbidden, set())

    def test_unchanged_doubles_the_interval(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        claim_id = tracked(tool)["claim_id"]

        clock.advance(timedelta(hours=24))
        view = tool.record_outcome(claim_id, "unchanged")

        self.assertEqual(view["check_interval_hours"], 48.0)
        self.assertEqual(view["status"], ClaimStatus.VERIFIED.value)
        self.assertEqual(view["next_check_at"], (NOW + timedelta(hours=72)).isoformat())

    def test_changed_halves_it_and_hands_the_claim_to_the_draft_stage(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        claim_id = tracked(tool)["claim_id"]

        view = tool.record_outcome(claim_id, "changed")

        self.assertEqual(view["check_interval_hours"], 12.0)
        # An edit now needs a reviewer, which is the only thing `status` records.
        self.assertEqual(view["status"], ClaimStatus.UNRESOLVED.value)

    def test_the_ladder_climbs_over_repeated_quiet_runs(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        claim_id = tracked(tool, wave="settled")["claim_id"]

        intervals = []
        for _ in range(3):
            clock.advance(timedelta(days=200))
            intervals.append(tool.record_outcome(claim_id, "unchanged")["check_interval_hours"])

        # 45d -> 90d -> 180d, then held at the six-month ceiling rather than growing forever.
        self.assertEqual(intervals, [90 * 24.0, 180 * 24.0, 180 * 24.0])

    def test_an_unknown_outcome_is_a_value_listing_the_real_ones(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        view = tool.record_outcome(claim_id, "probably_fine")

        self.assertIn("probably_fine", view["error"])
        self.assertEqual(view["allowed"], ["unchanged", "changed", "unresolved"])


class TestResearch(unittest.TestCase):
    def test_the_tier_is_looked_up_here_and_not_taken_from_the_caller(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        view = tool.record_research(
            claim_id,
            "Which films does Gambit appear in?",
            # A model claiming tier 1 for its own blog. The key is ignored: `Source.create`
            # resolves the tier against the profile's table and nothing else.
            [{"url": "https://blog.invalid/scoop", "excerpt": "...", "tier": 1}],
        )

        self.assertEqual(view["sources"][0]["tier"], 4)
        self.assertEqual(view["confidence"], 0.5)

    def test_confidence_counts_publishers_not_urls(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        one = tool.record_research(claim_id, "objective", [
            {"url": "https://www.marvel.com/a", "excerpt": "a"},
            {"url": "https://marvel.com/b", "excerpt": "b"},
        ])
        self.assertEqual(one["confidence"], 0.95)

        two = tool.record_research(claim_id, "objective", [
            {"url": "https://variety.com/c", "excerpt": "c"},
        ])
        self.assertEqual(two["confidence"], 0.98)

    def test_a_published_date_becomes_the_source_as_of(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        view = tool.record_research(claim_id, "objective", [
            {"url": "https://variety.com/c", "excerpt": "c", "published": "2024-07-27"},
        ])

        self.assertEqual(view["sources"][0]["as_of"], "2024-07-27T00:00:00+00:00")

    def test_a_malformed_date_is_unknown_rather_than_an_error(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        view = tool.record_research(claim_id, "objective", [
            {"url": "https://variety.com/c", "excerpt": "c", "published": "last summer"},
        ])

        self.assertIsNone(view["sources"][0]["as_of"])

    def test_a_source_with_no_url_is_a_value_not_a_crash(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        view = tool.record_research(claim_id, "objective", [{"excerpt": "no url here"}])

        self.assertIn("url", view["error"])
        self.assertEqual(tool.store.get(claim_id).research_rounds, 0)  # type: ignore[union-attr]

    def test_every_round_spends_budget_whether_or_not_it_helped(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        for spent in range(1, MAX_RESEARCH_ROUNDS + 1):
            view = tool.record_research(claim_id, "objective", [])
            self.assertEqual(view["research_rounds"], spent)
            self.assertEqual(view["rounds_remaining"], MAX_RESEARCH_ROUNDS - spent)

        # The graph's retry edge branches on this rather than counting for itself.
        self.assertTrue(view["budget_spent"])

    def test_a_settled_run_clears_the_budget_for_next_time(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        claim_id = tracked(tool)["claim_id"]
        tool.record_research(claim_id, "objective", [])

        view = tool.record_outcome(claim_id, "unchanged")

        self.assertEqual(view["research_rounds"], 0)
        self.assertEqual(view["rounds_remaining"], MAX_RESEARCH_ROUNDS)


class TestDeclining(unittest.TestCase):
    """Declining to pick is the deliverable, so it has to be recorded properly."""

    def test_unresolved_keeps_both_sides(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]
        tool.record_research(claim_id, "objective", [
            {"url": "https://variety.com/a", "excerpt": "a"},
            {"url": "https://deadline.com/b", "excerpt": "b"},
        ])

        view = tool.record_outcome(
            claim_id,
            "unresolved",
            note="Variety says July, Deadline says August.",
            source_a="https://variety.com/a",
            source_b="https://deadline.com/b",
        )

        self.assertEqual(view["status"], ClaimStatus.UNRESOLVED.value)
        self.assertTrue(view["is_contradicted"])
        self.assertEqual(view["contradicts"][0]["source_a"], "https://variety.com/a")
        # An open contradiction caps confidence, so nothing can auto-apply over it.
        self.assertLessEqual(view["confidence"], 0.5)
        self.assertFalse(view["auto_appliable"])

    def test_unresolved_without_both_sides_is_refused(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        view = tool.record_outcome(claim_id, "unresolved", note="they disagree")

        self.assertIn("source_a", view["error"])
        self.assertEqual(tool.store.get(claim_id).status, ClaimStatus.VERIFIED)  # type: ignore[union-attr]

    def test_there_is_no_exhausted_outcome(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        view = tool.record_outcome(claim_id, "exhausted")

        # Spending the budget without finding anything is `unchanged`: no new data is no
        # change. A node asking for a fourth outcome is told the three that exist.
        self.assertIn("exhausted", view["error"])
        self.assertEqual(view["allowed"], ["unchanged", "changed", "unresolved"])

    def test_a_spent_budget_with_nothing_found_leaves_the_page_standing(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        claim_id = tracked(tool)["claim_id"]
        for _ in range(MAX_RESEARCH_ROUNDS):
            tool.record_research(claim_id, "objective", [])

        view = tool.record_outcome(claim_id, "unchanged")

        self.assertEqual(view["status"], ClaimStatus.VERIFIED.value)
        self.assertEqual(view["sources"], [])
        self.assertEqual(view["check_interval_hours"], 48.0)

    def test_a_rejected_draft_restores_the_claim_without_a_separate_outcome(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        claim_id = tracked(tool)["claim_id"]
        tool.record_outcome(claim_id, "changed")

        # What discarding a change at the gate does: the old text stands, so it is
        # `unchanged`. There is no `rejected` transition and there must not be one.
        view = tool.record_outcome(claim_id, "unchanged")

        self.assertEqual(view["status"], ClaimStatus.VERIFIED.value)
        self.assertEqual(view["check_interval_hours"], 24.0)


class TestReading(unittest.TestCase):
    def test_due_claims_returns_what_the_clock_says_is_due(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        tracked(tool)

        self.assertEqual(tool.due_claims()["count"], 0)
        clock.advance(timedelta(hours=24))
        self.assertEqual(tool.due_claims()["count"], 1)

    def test_due_claims_come_back_soonest_first(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        tracked(tool, wave="settled", wikitext_anchor="slow")
        tracked(tool, wave="announcement_driven", wikitext_anchor="fast")

        clock.advance(timedelta(days=100))
        pages = [c["wikitext_anchor"] for c in tool.due_claims()["claims"]]

        self.assertEqual(pages, ["fast", "slow"])

    def test_the_limit_is_honoured_and_the_rest_stay_due(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        for i in range(4):
            tracked(tool, wikitext_anchor=f"anchor-{i}")

        clock.advance(timedelta(days=1))
        self.assertEqual(tool.due_claims(limit=2)["count"], 2)
        self.assertEqual(tool.due_claims()["count"], 4)

    def test_a_claim_view_carries_no_source_excerpts(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]
        tool.record_research(claim_id, "objective", [
            {"url": "https://variety.com/a", "excerpt": "x" * 5000},
        ])

        view = tool.read_claim(claim_id)

        self.assertNotIn("excerpt", view["sources"][0])
        self.assertNotIn("x" * 100, repr(view))

    def test_an_unknown_id_is_a_value_not_an_exception(self) -> None:
        view = ledger().read_claim("nope")

        self.assertIn("nope", view["error"])


class TestRippleTargets(unittest.TestCase):
    def test_targets_are_deduped_and_never_include_the_claim_itself(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]
        other = tracked(tool, page="Phase Six", wikitext_anchor="films")["claim_id"]

        view = tool.link_ripple_targets(claim_id, [other, other, claim_id])

        self.assertEqual(view["ripple_targets"], [other])

    def test_linking_twice_accumulates_rather_than_replaces(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        tool.link_ripple_targets(claim_id, ["a"])
        view = tool.link_ripple_targets(claim_id, ["b"])

        self.assertEqual(view["ripple_targets"], ["a", "b"])

    def test_untracked_targets_are_kept_and_reported(self) -> None:
        tool = ledger()
        claim_id = tracked(tool)["claim_id"]

        view = tool.link_ripple_targets(claim_id, ["not-audited-yet"])

        # The page holding it may simply not have been audited, so this is information for
        # the fan-out node rather than a rejection.
        self.assertEqual(view["untracked"], ["not-audited-yet"])
        self.assertEqual(view["ripple_targets"], ["not-audited-yet"])


class TestPersistence(unittest.TestCase):
    """The whole reason the store exists: a run has to find last run's ladder."""

    def test_the_interval_survives_a_new_process(self) -> None:
        clock = Clock()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"

            first = Ledger.local(MCU_FANDOM, path, clock=clock)
            claim_id = tracked(first)["claim_id"]

            clock.advance(timedelta(hours=24))
            second = Ledger.local(MCU_FANDOM, path, clock=clock)
            view = second.record_outcome(claim_id, "unchanged")

            self.assertEqual(view["check_interval_hours"], 48.0)

            clock.advance(timedelta(hours=48))
            third = Ledger.local(MCU_FANDOM, path, clock=clock)
            self.assertEqual(third.due_claims()["count"], 1)

    def test_the_default_clock_is_a_function_not_a_bound_method(self) -> None:
        # `slots=True` keeps the callable default an instance attribute; were it a class
        # attribute, `self.clock()` would pass `self` and every timestamp would raise.
        self.assertIsInstance(Ledger.in_memory(MCU_FANDOM).clock(), datetime)


class TestDefaults(unittest.TestCase):
    def test_the_due_limit_is_bounded_below(self) -> None:
        clock = Clock()
        tool = ledger(clock)
        tracked(tool)
        clock.advance(timedelta(days=1))

        # A model sending 0 or a negative would otherwise silently return nothing due and the
        # run would conclude the wiki was up to date.
        self.assertEqual(tool.due_claims(limit=0)["count"], 1)

    def test_the_default_limit_is_the_documented_one(self) -> None:
        self.assertEqual(Ledger.due_claims.__defaults__, (DEFAULT_DUE_LIMIT,))


if __name__ == "__main__":
    unittest.main()
