"""Which source goes in the footnote — and the guarantee that filtering costs no evidence.

The case this exists for was measured live on Aug 23, 2026. Retrieval for "Gambit appears in
*Avengers: Doomsday*" returned six publishers. The two tier-1 sources, `marvel.com` and
`disney.com`, list the cast as actor names and never write the word Gambit: they establish
that Channing Tatum is in the film, not that the character is. "Cite your best source" would
footnote the sentence to a page that does not contain it, and nothing would catch that — the
claim is true, six publishers agree, and confidence scores 1.0.

The excerpts below are shortened but keep the shape that caused it: an official cast list of
actor names, against trade-press prose naming both.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.core.ledger import (
    Claim,
    ClaimKind,
    Wave,
    best_citation,
    mentions,
    supporting,
    supports,
    uncited,
)
from backend.core.ledger.schema import Source
from backend.core.profile import MCU_FANDOM

NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)

# The real shapes, trimmed. marvel/disney name the actor; the rest name the character too.
EXCERPTS = {
    "https://www.marvel.com/movies/avengers-doomsday": (
        "Robert Downey Jr., Chris Evans, Chris Hemsworth, Pedro Pascal, Paul Rudd, "
        "Anthony Mackie, Florence Pugh, Wyatt Russell, Channing Tatum, Simu Liu"
    ),
    "https://www.disney.com/movies/avengers-doomsday": (
        "* Cast\nRobert Downey Jr., Chris Evans, Chris Hemsworth, Channing Tatum"
    ),
    "https://deadline.com/2025/03/avengers-doomsday-cast": (
        "'Avengers: Doomsday' Cast Includes 'X-Men' OGs Patrick Stewart, Ian McKellen; "
        "Gambit Channing Tatum & More Set As Cameras Roll"
    ),
    "https://variety.com/2025/film/news/channing-tatum-gambit": (
        "How He's Reviving Gambit for 'Avengers: Doomsday'"
    ),
    "https://www.themoviedb.org/movie/avengers-doomsday/cast": (
        "Channing Tatum\nChanning Tatum\nGambit\n12."
    ),
}


def claim(*, title: str = "Gambit", urls: tuple[str, ...] | None = None) -> Claim:
    chosen = urls if urls is not None else tuple(EXCERPTS)
    return Claim(
        claim_id="gambit-doomsday",
        page=title,
        entity_ref=MCU_FANDOM.entity_ref(title),
        kind=ClaimKind.PROSE,
        wave=Wave.ANNOUNCEMENT_DRIVEN,
        text="Gambit appears in Avengers: Doomsday.",
        wikitext_anchor="Gambit",
        section_index=1,
        section_heading="Appearances",
        sources=tuple(
            Source.create(url, EXCERPTS[url], NOW, domain_tiers=MCU_FANDOM.domain_tiers)
            for url in chosen
        ),
    )


class TestTheMeasuredFailure(unittest.TestCase):
    def test_the_best_tier_source_is_not_the_footnote(self) -> None:
        """The whole point. marvel.com is tier 1 and does not state the claim."""
        best = best_citation(claim())
        assert best is not None
        self.assertEqual(best.domain, "deadline.com")
        self.assertEqual(best.tier, 2)

    def test_an_official_cast_list_naming_only_the_actor_is_rejected(self) -> None:
        citable = {s.domain for s in supporting(claim())}
        self.assertNotIn("marvel.com", citable)
        self.assertNotIn("disney.com", citable)
        self.assertEqual(citable, {"deadline.com", "variety.com", "themoviedb.org"})

    def test_filtering_citations_costs_no_evidence(self) -> None:
        """The guarantee: every source still counts toward confidence. Rejecting a source as a
        footnote is not the same as discarding it."""
        subject = claim()
        without_marvel = claim(
            urls=tuple(u for u in EXCERPTS if "marvel.com" not in u and "disney.com" not in u)
        )
        self.assertEqual(subject.recompute_confidence(), 1.0)
        self.assertLess(without_marvel.recompute_confidence(), 1.0)
        self.assertEqual(len(subject.sources), 5)


class TestTermMatching(unittest.TestCase):
    def test_matching_is_case_insensitive(self) -> None:
        self.assertTrue(mentions("GAMBIT joins the cast", "Gambit"))

    def test_a_term_split_across_a_line_break_still_matches(self) -> None:
        """Excerpts are scraped markdown; the publisher never wrote that break."""
        self.assertTrue(mentions("Reviving Gambit for 'Avengers:\nDoomsday'", "Avengers: Doomsday"))

    def test_a_term_inside_a_longer_word_does_not_match(self) -> None:
        self.assertFalse(mentions("a series of gambits", "Gambit"))

    def test_punctuation_around_a_term_does_not_block_it(self) -> None:
        self.assertTrue(mentions("...'Avengers: Doomsday' cast...", "Avengers: Doomsday"))
        self.assertTrue(mentions("Gambit's return", "Gambit"))

    def test_an_empty_term_matches_nothing(self) -> None:
        self.assertFalse(mentions("anything at all", "  "))

    def test_every_term_is_required_not_just_one(self) -> None:
        """A footnote supports the whole sentence. Half of it is corroboration, not a citation."""
        source = Source.create(
            "https://variety.com/x", "Gambit is a mutant", NOW,
            domain_tiers=MCU_FANDOM.domain_tiers,
        )
        self.assertTrue(supports(source, ("Gambit",)))
        self.assertFalse(supports(source, ("Gambit", "Avengers: Doomsday")))


class TestExplicitWording(unittest.TestCase):
    def test_the_drafted_sentence_narrows_the_field_further(self) -> None:
        """Only the Draft stage knows the wording it wrote, so it may pass its own terms."""
        drafted = ("Gambit", "Avengers: Doomsday")
        citable = {s.domain for s in supporting(claim(), drafted)}
        self.assertEqual(citable, {"deadline.com", "variety.com"})
        # TMDB names Gambit but never the film title in the same excerpt.
        self.assertNotIn("themoviedb.org", citable)

    def test_the_default_term_is_the_subject_and_comes_off_the_record(self) -> None:
        self.assertEqual(
            {s.domain for s in supporting(claim())},
            {s.domain for s in supporting(claim(), ("Gambit",))},
        )

    def test_a_variant_subpage_requires_the_base_not_the_wiki_suffix(self) -> None:
        """`Human Torch/Void-Analyzing Fantastic Four` is a wiki naming convention. No
        publisher writes it, so requiring it would reject every source that exists."""
        variant = claim(title="Human Torch/Void-Analyzing Fantastic Four")
        self.assertEqual(variant.entity_ref.base, "Human Torch")
        source = Source.create(
            "https://variety.com/x", "the Human Torch appears", NOW,
            domain_tiers=MCU_FANDOM.domain_tiers,
        )
        self.assertTrue(supports(source, ("Human Torch",)))


class TestNothingSupportsIt(unittest.TestCase):
    def test_an_unsupported_claim_returns_no_citation_rather_than_the_best_source(self) -> None:
        """`None` is a real answer. Rounding it up to "cite the best one anyway" is the bug."""
        official_only = claim(
            urls=(
                "https://www.marvel.com/movies/avengers-doomsday",
                "https://www.disney.com/movies/avengers-doomsday",
            )
        )
        self.assertIsNone(best_citation(official_only))
        self.assertEqual(supporting(official_only), ())
        self.assertTrue(uncited(official_only))

    def test_a_claim_with_no_sources_is_not_uncited(self) -> None:
        """Distinct states: nothing retrieved yet, versus retrieval that missed the claim."""
        self.assertFalse(uncited(claim(urls=())))

    def test_an_unsupported_claim_keeps_its_confidence(self) -> None:
        """Two tier-1 sources still score 0.98 — they are evidence, just not citable ones.
        The reviewer needs both facts: strongly corroborated, and not directly stated."""
        official_only = claim(
            urls=(
                "https://www.marvel.com/movies/avengers-doomsday",
                "https://www.disney.com/movies/avengers-doomsday",
            )
        )
        self.assertGreater(official_only.recompute_confidence(), 0.9)
        self.assertTrue(uncited(official_only))


class TestRanking(unittest.TestCase):
    def test_survivors_are_ordered_by_tier(self) -> None:
        tiers = [s.tier for s in supporting(claim())]
        self.assertEqual(tiers, sorted(tiers))

    def test_ties_keep_retrieval_order_so_footnotes_are_stable(self) -> None:
        """Parallel ranks by relevance; once tier is spent that is the best signal left, and a
        stable sort means a rebuild does not reshuffle citations."""
        subject = claim()
        tier_two = [s.url for s in supporting(subject) if s.tier == 2]
        retrieved = [s.url for s in subject.sources if s.tier == 2]
        self.assertEqual(tier_two, retrieved)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
