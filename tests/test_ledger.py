"""Ledger core tests.

Assert on numbers, never on resemblance (`CLAUDE.md` §5). Every behaviour the docs promise
about tiers and decay is pinned here, because those are the two things the demo claims are
deterministic and a judge may well probe.

Stdlib only — the core has no dependencies, so its tests shouldn't either.
"""

import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.ledger import (
    AUTO_APPLY_THRESHOLD,
    CEILING,
    FLOOR,
    MAX_RESEARCH_ROUNDS,
    Claim,
    ClaimKind,
    ClaimStatus,
    Contradiction,
    Source,
    Wave,
    confidence_from,
    next_interval,
    seed_interval,
    tier_for,
)
from backend.core.profile import MCU_FANDOM

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

# The demo wiki's table. Tiers are per-wiki now, so every lookup names one.
TIERS = MCU_FANDOM.domain_tiers


def make_claim(**overrides: Any) -> Claim:
    base: dict[str, Any] = dict(
        claim_id="c1",
        page="Gambit",
        entity_ref=MCU_FANDOM.entity_ref("Gambit"),
        kind=ClaimKind.LIST_MEMBER,
        wave=Wave.ANNOUNCEMENT_DRIVEN,
        text="Gambit appears in Avengers: Doomsday",
        wikitext_anchor="*[[Avengers: Doomsday]]",
        section_index=3,
        section_heading="Appearances",
    )
    return Claim(**{**base, **overrides})


class TestTiers(unittest.TestCase):
    def test_known_domains_and_www_are_equivalent(self) -> None:
        self.assertEqual(tier_for("https://deadline.com/x", TIERS), 2)
        self.assertEqual(tier_for("https://www.deadline.com/x", TIERS), 2)

    def test_subdomain_resolves_to_registrable_domain(self) -> None:
        # The wiki we read from must tier as a fan wiki, not as an unknown domain.
        url = "https://marvelcinematicuniverse.fandom.com/wiki/Gambit"
        self.assertEqual(tier_for(url, TIERS), 6)

    def test_unknown_domain_gets_default_not_a_guess(self) -> None:
        self.assertEqual(tier_for("https://some-blog.example/post", TIERS), 4)

    def test_better_tier_beats_more_sources(self) -> None:
        one_primary = confidence_from([1])
        many_general = confidence_from([4, 4, 4, 4])
        self.assertGreater(one_primary, many_general)

    def test_corroboration_helps_but_is_capped(self) -> None:
        self.assertGreater(confidence_from([2, 2]), confidence_from([2]))
        self.assertEqual(confidence_from([2, 2, 2, 2, 2, 2]), confidence_from([2, 2, 2, 2]))

    def test_social_only_cannot_reach_the_auto_apply_gate(self) -> None:
        # `seed-plan.md` §5: a social citation corroborates, never carries.
        self.assertLess(confidence_from([5, 5, 5]), AUTO_APPLY_THRESHOLD)

    def test_contradiction_caps_confidence_below_the_gate(self) -> None:
        self.assertLess(confidence_from([1, 1], contradicted=True), AUTO_APPLY_THRESHOLD)

    def test_fan_wiki_alone_is_worth_nothing(self) -> None:
        self.assertEqual(confidence_from([6]), 0.0)

    def test_no_sources_is_zero(self) -> None:
        self.assertEqual(confidence_from([]), 0.0)


class TestDecay(unittest.TestCase):
    def test_settled_reaches_ceiling_in_two_runs(self) -> None:
        # The claim `seed-plan.md` §3 makes about the control set.
        interval = seed_interval(Wave.SETTLED)
        interval = next_interval(interval, changed=False)
        interval = next_interval(interval, changed=False)
        self.assertEqual(interval, CEILING)

    def test_change_halves_and_stops_at_the_floor(self) -> None:
        interval = seed_interval(Wave.ANNOUNCEMENT_DRIVEN)
        self.assertEqual(interval, timedelta(hours=24))
        for _ in range(10):
            interval = next_interval(interval, changed=True)
        self.assertEqual(interval, FLOOR)

    def test_ceiling_and_floor_are_never_exceeded(self) -> None:
        self.assertEqual(next_interval(CEILING, changed=False), CEILING)
        self.assertEqual(next_interval(FLOOR, changed=True), FLOOR)

    def test_naive_datetime_is_rejected(self) -> None:
        claim = make_claim()
        with self.assertRaises(ValueError):
            claim.seeded(datetime(2026, 8, 15, 12, 0))


class TestEntityRef(unittest.TestCase):
    def test_variant_subpage_is_split(self) -> None:
        ref = MCU_FANDOM.entity_ref("Human Torch/Void-Analyzing Fantastic Four")
        self.assertEqual(ref.base, "Human Torch")
        self.assertEqual(ref.variant, "Void-Analyzing Fantastic Four")
        self.assertTrue(ref.is_variant)

    def test_plain_page_has_no_variant(self) -> None:
        ref = MCU_FANDOM.entity_ref("Human Torch")
        self.assertEqual(ref.base, "Human Torch")
        self.assertIsNone(ref.variant)
        self.assertFalse(ref.is_variant)

    def test_variant_and_prime_are_distinct_subjects(self) -> None:
        # `seed-plan.md` §4.3 — conflating these is the failure mode worth guarding.
        self.assertNotEqual(
            MCU_FANDOM.entity_ref("Human Torch"),
            MCU_FANDOM.entity_ref("Human Torch/Void-Analyzing Fantastic Four"),
        )


class TestClaimTransitions(unittest.TestCase):
    def test_seeding_schedules_from_the_wave(self) -> None:
        claim = make_claim(wave=Wave.SETTLED).seeded(NOW)
        self.assertEqual(claim.check_interval, seed_interval(Wave.SETTLED))
        self.assertEqual(claim.next_check_at, NOW + seed_interval(Wave.SETTLED))

    def test_unchanged_doubles_the_interval_and_clears_the_budget(self) -> None:
        claim = make_claim().seeded(NOW)
        claim = claim.researched("has Gambit been cast further?", ())
        claim = claim.unchanged(NOW)
        self.assertEqual(claim.status, ClaimStatus.VERIFIED)
        self.assertEqual(claim.check_interval, timedelta(hours=48))
        self.assertEqual(claim.research_rounds, 0)

    def test_changed_halves_the_interval_and_marks_stale(self) -> None:
        claim = make_claim().seeded(NOW).changed(NOW)
        self.assertEqual(claim.status, ClaimStatus.STALE)
        self.assertEqual(claim.check_interval, timedelta(hours=12))

    def test_is_due_respects_the_schedule(self) -> None:
        claim = make_claim().seeded(NOW)
        self.assertFalse(claim.is_due(NOW + timedelta(hours=1)))
        self.assertTrue(claim.is_due(NOW + timedelta(days=2)))

    def test_unseeded_claim_is_due_immediately(self) -> None:
        self.assertTrue(make_claim().is_due(NOW))

    def test_research_counts_against_the_budget(self) -> None:
        claim = make_claim()
        for _ in range(MAX_RESEARCH_ROUNDS):
            self.assertFalse(claim.budget_spent)
            claim = claim.researched("objective", ())
        self.assertTrue(claim.budget_spent)

    def test_confidence_is_recomputed_from_sources(self) -> None:
        claim = make_claim().researched("objective", (
            Source.create("https://deadline.com/a", "…", NOW, domain_tiers=TIERS),
            Source.create("https://variety.com/b", "…", NOW, domain_tiers=TIERS),
        ))
        self.assertEqual(claim.confidence, confidence_from([2, 2]))
        self.assertGreater(claim.confidence, AUTO_APPLY_THRESHOLD)

    def test_two_urls_from_one_publisher_are_not_corroboration(self) -> None:
        claim = make_claim().researched("objective", (
            Source.create("https://deadline.com/a", "…", NOW, domain_tiers=TIERS),
            Source.create("https://www.deadline.com/b", "…", NOW, domain_tiers=TIERS),
        ))
        self.assertEqual(claim.confidence, confidence_from([2]))

    def test_unresolved_keeps_the_objective_and_stays_scheduled(self) -> None:
        claim = make_claim().seeded(NOW).researched("is the cameo confirmed?", (
            Source.create("https://deadline.com/a", "confirmed", NOW, domain_tiers=TIERS),
            Source.create("https://variety.com/b", "in talks", NOW, domain_tiers=TIERS),
        ))
        claim = claim.unresolved(NOW, Contradiction(
            note="confirmed vs in talks",
            source_a="https://deadline.com/a",
            source_b="https://variety.com/b",
        ))
        self.assertEqual(claim.status, ClaimStatus.UNRESOLVED)
        self.assertEqual(claim.objective, "is the cameo confirmed?")
        self.assertIsNotNone(claim.next_check_at)  # revisit queue, `summary.md` §7
        self.assertLess(claim.confidence, AUTO_APPLY_THRESHOLD)

    def test_exhausted_is_distinct_from_unresolved(self) -> None:
        claim = make_claim().seeded(NOW).exhausted(NOW)
        self.assertEqual(claim.status, ClaimStatus.EXHAUSTED)
        self.assertFalse(claim.is_contradicted)


class TestAutoApplyGate(unittest.TestCase):
    def test_high_confidence_stale_claim_is_appliable(self) -> None:
        claim = make_claim().researched("objective", (
            Source.create("https://marvel.com/a", "…", NOW, domain_tiers=TIERS),
        )).changed(NOW)
        self.assertTrue(claim.auto_appliable)

    def test_contradicted_claim_is_never_appliable(self) -> None:
        claim = make_claim().researched("objective", (
            Source.create("https://marvel.com/a", "…", NOW, domain_tiers=TIERS),
        )).unresolved(NOW, Contradiction(note="n", source_a="a", source_b="b"))
        self.assertFalse(claim.auto_appliable)

    def test_low_confidence_claim_is_not_appliable(self) -> None:
        claim = make_claim().researched("objective", (
            Source.create("https://x.com/someone/status/1", "…", NOW, domain_tiers=TIERS),
        )).changed(NOW)
        self.assertFalse(claim.auto_appliable)


class TestImmutability(unittest.TestCase):
    def test_transitions_do_not_mutate_the_original(self) -> None:
        original = make_claim().seeded(NOW)
        original.changed(NOW)
        self.assertEqual(original.status, ClaimStatus.VERIFIED)

    def test_records_are_frozen(self) -> None:
        claim = make_claim()
        # Dynamic on purpose: direct assignment is a *static* error mypy already catches, so
        # writing it that way would fail typecheck. This pins the runtime guarantee too.
        with self.assertRaises(FrozenInstanceError):
            setattr(claim, "status", ClaimStatus.APPLIED)  # noqa: B010


if __name__ == "__main__":
    unittest.main()
