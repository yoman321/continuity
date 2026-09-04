"""The graph: what one run does to the ledger, and what it hands to the gate.

Two halves, tested apart on purpose. The stages are ordinary methods, so most of what matters
here — which claim gets researched, what a failed search costs, which bucket produces a card —
is asserted by calling them with no ADK anywhere. The graph itself then has exactly one thing
worth proving that a straight line cannot: the backward edge fires, and it stops.

The fakes are the same seams every other stage test uses. `SearchSource` and `ModelSource` are
protocols, so a class with one method satisfies them; nothing here opens a socket, bills a
search, or needs a wiki.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.agent import classify as classify_stage
from backend.agent import draft as draft_stage
from backend.agent import semantic_diff as diff_stage
from backend.agent.graph import (
    STAGES,
    Run,
    Stages,
    after_date_for,
    draft_id_for,
    edit_id_for,
    keywords,
    objective_for,
    queries_for,
    run,
    sources_for,
    survivors,
)
from backend.agent.model import ModelError, ModelRequest
from backend.agent.tools import Ledger, WebSearch
from backend.agent.tools.web_search import RawResult, SearchError, SearchOutcome, SearchRequest
from backend.core.ledger import Claim, ClaimKind, Wave
from backend.core.ledger.baseline import InMemoryBaselineStore, SectionBaseline
from backend.core.ledger.baseline import from_document as from_baseline_document
from backend.core.ledger.baseline import to_document as to_baseline_document
from backend.core.ledger.documents import task_id_for
from backend.core.ledger.drafts import InMemoryDraftStore
from backend.core.ledger.judgements import InMemoryJudgementStore
from backend.core.ledger.schema import MAX_RESEARCH_ROUNDS
from backend.core.profile import local_wiki

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
#: Well before any wave's seed interval, so a claim tracked at this instant is due at `NOW`.
LONG_AGO = NOW - timedelta(days=400)

PROFILE = local_wiki("http://wiki.invalid/api.php")

#: `GAM-APP-01` again — the demo's opening claim, and the anchor every other stage test uses.
ANCHOR = "|movie = ''[[Deadpool & Wolverine]]''"
APPENDED = (
    f"{ANCHOR}<br>''[[Avengers: Doomsday]]'' <small>(unreleased)</small>"
    "<ref>https://deadline.com/2024/07/doomsday</ref>"
)
SECTION = f"'''Gambit''' is a mutant.\n{{{{Infobox\n{ANCHOR}\n}}}}"
URL = "https://deadline.com/2024/07/doomsday"
OTHER_URL = "https://variety.com/2024/07/gambit"


# -- the seams ----------------------------------------------------------------------------


class FakeSearch:
    """One result unless told otherwise. Records what it was asked, so the retry is visible."""

    def __init__(
        self, *, results: int = 1, fails: bool = False, mentions: str = ""
    ) -> None:
        self.calls: list[SearchRequest] = []
        self.results = results
        self.fails = fails
        #: When set, the *second* claim's search returns a result naming this subject — the
        #: cross-claim evidence the second classification sweep exists to notice.
        self.mentions = mentions

    def run(self, request: SearchRequest) -> SearchOutcome:
        self.calls.append(request)
        if self.fails:
            raise SearchError("no key")
        extra = (
            (
                RawResult(
                    url=f"{OTHER_URL}-elsewhere",
                    excerpts=(f"A later report contradicts what the page says about "
                              f"{self.mentions}.",),
                    publish_date="2025-10-01",
                ),
            )
            if self.mentions and len(self.calls) > 1
            else ()
        )
        return SearchOutcome(
            results=tuple(
                RawResult(
                    url=f"{URL}-{i}" if i else URL,
                    excerpts=("Channing Tatum's Gambit joins Avengers: Doomsday.",),
                    publish_date="2024-07-27",
                )
                for i in range(self.results)
            ) + extra,
            usage=(("sku_search", 1),),
        )


class FakeModel:
    """One answer per stage, keyed on the system instruction the stage declared."""

    def __init__(
        self,
        *,
        bucket: str = "new",
        then: str = "",
        off_entity: tuple[str, ...] = (),
        after: str = APPENDED,
        dispositions: tuple[str, ...] = ("kept", "added"),
        draft_fails: bool = False,
        diff_fails: bool = False,
    ) -> None:
        self.bucket = bucket
        #: What it answers once it has been shown a PREVIOUS CLASSIFICATION — the revision.
        self.then = then
        self.off_entity = off_entity
        self.after = after
        self.dispositions = dispositions
        self.draft_fails = draft_fails
        self.diff_fails = diff_fails
        self.seen: list[str] = []

    def run(self, request: ModelRequest) -> str:
        if request.system == classify_stage.SYSTEM:
            self.seen.append("classify")
            revisiting = "PREVIOUS CLASSIFICATION" in request.prompt
            bucket = self.then if (revisiting and self.then) else self.bucket
            answer: dict[str, Any] = {
                "bucket": bucket,
                "reason": "Doomsday has been announced.",
                "off_entity": list(self.off_entity),
            }
            if bucket == "conflicting":
                answer["conflict"] = {
                    "note": "sources split", "source_a": URL, "source_b": OTHER_URL
                }
            return json.dumps(answer)
        if request.system == draft_stage.SYSTEM:
            self.seen.append("draft")
            if self.draft_fails:
                raise ModelError("refused")
            return json.dumps({"after": self.after, "summary": "Appended Doomsday to the field."})
        if request.system == diff_stage.SYSTEM:
            self.seen.append("diff")
            if self.diff_fails:
                raise ModelError("no credential")
            return json.dumps(
                {
                    "changes": [
                        {"assertion": f"assertion {i}", "disposition": disposition}
                        for i, disposition in enumerate(self.dispositions)
                    ]
                }
            )
        raise AssertionError(f"unexpected prompt: {request.system[:40]!r}")


def build(
    search: FakeSearch | None = None,
    model: FakeModel | None = None,
    *,
    baseline: bool = True,
    claims: int = 1,
) -> tuple[Stages, Ledger, InMemoryDraftStore]:
    """A run's worth of seams, with `claims` tracked and already due."""
    # Built directly: there is no `track_claim` and no proposal stage (removed Sept 1, 2026),
    # so a test states the claims it wants a run to find, the way `seed_claims.py` does.
    seeded = [
        Claim(
            claim_id=f"claim-{index + 1:04d}",
            page="Gambit",
            entity_ref=PROFILE.entity_ref("Gambit"),
            kind=ClaimKind.PROSE,
            wave=Wave.ANNOUNCEMENT_DRIVEN,
            text=f"Gambit appears in Deadpool & Wolverine ({index}).",
            wikitext_anchor=ANCHOR if index == 0 else f"{ANCHOR} {index}",
            section_index=0,
            section_heading="",
        ).seeded(LONG_AGO)
        for index in range(claims)
    ]
    ledger = Ledger.in_memory(PROFILE, seeded, clock=lambda: NOW)
    sections = (
        SectionBaseline(
            page="Gambit",
            section_index=0,
            section_heading="",
            text=SECTION,
            revid=1,
            fetched_at=NOW,
        ),
    )
    drafts = InMemoryDraftStore()
    stages = Stages(
        profile=PROFILE,
        ledger=ledger,
        baseline=InMemoryBaselineStore(sections if baseline else ()),
        search=WebSearch(PROFILE, search or FakeSearch()),
        classifier=classify_stage.Classifier(PROFILE, model or FakeModel()),
        drafter=draft_stage.Drafter(PROFILE, model or FakeModel()),
        reviewer=diff_stage.Reviewer(PROFILE, model or FakeModel()),
        drafts=drafts,
        judgements=InMemoryJudgementStore(),
        clock=lambda: NOW,
    )
    return stages, ledger, drafts


def only_claim(ledger: Ledger) -> Any:
    claim = ledger.store.get("claim-0001")
    assert claim is not None
    return claim


# -- what a run asks ----------------------------------------------------------------------

#: A claim about a subject that is nobody's variant, and one about a variant. The pair is the
#: whole difference the retry's extra query exists for.
PRIME: dict[str, Any] = {
    "entity": {"title": "Gambit", "base": "Gambit"},
    "page": "Gambit",
    "text": "Gambit appears in Deadpool & Wolverine.",
    "section_heading": "",
    "objective": "",
    "sources": [],
}
VARIANT: dict[str, Any] = {
    "entity": {
        "title": "Human Torch/Void-Analyzing Fantastic Four",
        "base": "Human Torch",
        "variant": "Void-Analyzing Fantastic Four",
    },
    "page": "Human Torch/Void-Analyzing Fantastic Four",
    "text": "This variant of Johnny Storm is killed by Cassandra Nova.",
    "section_heading": "",
    "objective": "",
    "sources": [],
}


class TestWhatARunAsks(unittest.TestCase):
    """The pure half: the queries, the objective and the date filter, all deterministic.

    They have to be. A recorded run replays on the request, so a query built from a set or a
    timestamp would miss its own cassette on the second run (`web_search.SearchRequest.key`).
    """

    claim = PRIME
    variant = VARIANT


    def test_keywords_drop_the_words_that_carry_no_signal(self) -> None:
        self.assertEqual(
            keywords("Gambit appears in Deadpool & Wolverine."),
            ["Gambit", "appears", "Deadpool", "Wolverine"],
        )

    def test_the_subject_leads_every_query(self) -> None:
        for query in queries_for(self.variant):
            self.assertTrue(query.startswith("Human Torch"), query)

    def test_the_same_claim_asks_the_same_thing_twice(self) -> None:
        self.assertEqual(queries_for(self.claim), queries_for(self.claim))

    def test_a_retry_adds_the_base_title_for_a_variant(self) -> None:
        """The failure the backward edge exists for is retrieval reading a variant as its
        prime, so the second pass names the prime explicitly."""
        self.assertNotIn("Human Torch variant Johnny", queries_for(self.variant, 1))
        self.assertIn("Human Torch variant Johnny", queries_for(self.variant, 2))

    def test_a_prime_subject_gains_no_keyword_on_the_retry(self) -> None:
        """There is nothing to disambiguate, and padding a query with words the claim does not
        contain would invent retrieval signal. The objective is what broadens."""
        self.assertEqual(queries_for(self.claim, 1), queries_for(self.claim, 2))
        self.assertNotEqual(objective_for(self.claim, 1), objective_for(self.claim, 2))

    def test_round_one_asks_what_the_ledger_holds(self) -> None:
        stored = {**self.claim, "objective": "Which films has Gambit been cast in?"}
        self.assertEqual(objective_for(stored, 1), stored["objective"])

    def test_a_retry_never_re_asks_the_stored_question(self) -> None:
        """Re-asking the question that came back empty is the one thing the edge exists to
        avoid — and deriving the broadening from the claim is what stops it compounding."""
        stored = {**self.claim, "objective": "Which films has Gambit been cast in?"}
        self.assertNotIn(str(stored["objective"]), objective_for(stored, 2))
        self.assertEqual(objective_for(stored, 2), objective_for(stored, 3))

    def test_the_date_filter_is_what_we_already_hold(self) -> None:
        sourced = {**self.claim, "sources": [{"as_of": "2024-07-27T00:00:00+00:00"}]}
        self.assertEqual(after_date_for(sourced, 1), "2024-07-27")

    def test_a_retry_drops_the_date_filter(self) -> None:
        """It is applied before ranking, so it is the first thing to relax on an empty batch."""
        sourced = {**self.claim, "sources": [{"as_of": "2024-07-27T00:00:00+00:00"}]}
        self.assertEqual(after_date_for(sourced, 2), "")

    def test_an_unresearched_claim_has_no_date_to_filter_on(self) -> None:
        self.assertEqual(after_date_for(self.claim, 1), "")

    def test_survivors_are_what_filtering_left(self) -> None:
        payload = {"results": [{"url": "a"}, {"url": "b"}]}
        verdict = classify_stage.Verdict(bucket="conflicting", reason="", off_entity=("a",))
        self.assertEqual(survivors(payload, verdict), ("b",))

    def test_sources_carry_no_tier(self) -> None:
        """Tier is resolved by the ledger from the wiki's own table; sending one would be a
        node deciding something the profile owns (`AGENTS.md` §7)."""
        payload = {"results": [{"url": URL, "excerpts": ["x"], "publish_date": "2024-07-27"}]}
        self.assertEqual(
            sources_for(payload),
            [{"url": URL, "excerpt": "x", "published": "2024-07-27"}],
        )

    def test_a_card_is_named_for_its_claim_and_a_draft_for_its_task(self) -> None:
        self.assertEqual(edit_id_for("GAM-APP-01"), "edit-gam-app-01")
        self.assertEqual(draft_id_for("task-20260830T120000-000"), "draft-20260830T120000-000")

    def test_a_page_run_names_its_draft_for_the_run_not_for_run_(self) -> None:
        # A run started from the article is `run-<page>-<n>` (`core/ledger/pages.py`), so the
        # draft is `draft-Gambit-0003` rather than `draft-run-Gambit-0003`.
        self.assertEqual(draft_id_for("run-Gambit-0003"), "draft-Gambit-0003")

    def test_two_tasks_in_the_same_second_are_two_tasks(self) -> None:
        """Seeding the ledger and then running the graph takes well under a second, and at
        second resolution the two came back with the same id — which would have one task
        overwriting the other's judgements."""
        self.assertNotEqual(
            task_id_for(NOW.replace(microsecond=1000)),
            task_id_for(NOW.replace(microsecond=9000)),
        )


# -- the stages ---------------------------------------------------------------------------


class TestResearch(unittest.TestCase):
    def test_a_search_that_ran_spends_a_round_even_if_it_found_nothing(self) -> None:
        """A round that established nothing still counts — that is what stops the agent
        searching forever."""
        stages, ledger, _ = build(FakeSearch(results=0))
        run = Run(stages)
        run.audit()
        run.research()
        self.assertEqual(only_claim(ledger).research_rounds, 1)

    def test_a_failed_search_is_discarded_whole(self) -> None:
        """No sources, no round spent, no schedule change: an infrastructure failure must
        never be recorded as a finding about the world (`AGENTS.md` §7)."""
        stages, ledger, _ = build(FakeSearch(fails=True))
        before = only_claim(ledger)
        run = Run(stages)
        run.audit()
        run.research()
        after = only_claim(ledger)
        self.assertEqual(after.research_rounds, 0)
        self.assertEqual(after.next_check_at, before.next_check_at)
        self.assertEqual(run.discarded, ["claim-0001"])

    def test_a_discarded_claim_is_still_due(self) -> None:
        stages, ledger, _ = build(FakeSearch(fails=True))
        run(stages)
        self.assertTrue(only_claim(ledger).is_due(NOW))

    def test_the_evidence_reaches_the_ledger(self) -> None:
        stages, ledger, _ = build(FakeSearch(results=2))
        run = Run(stages)
        run.audit()
        run.research()
        claim = only_claim(ledger)
        self.assertEqual(len(claim.sources), 2)
        self.assertGreater(claim.confidence, 0.0)


class TestClassify(unittest.TestCase):
    def test_a_still_true_claim_produces_no_card(self) -> None:
        """Its citation is refreshed and its interval doubles; there is no diff to show."""
        stages, ledger, drafts = build(model=FakeModel(bucket="still_true"))
        report = run(stages)
        self.assertEqual(report.drafted, 0)
        self.assertEqual(drafts.all(), ())
        self.assertGreater(only_claim(ledger).check_interval, timedelta(hours=24))

    def test_a_real_conflict_goes_to_a_person_and_not_to_a_retry(self) -> None:
        """Both sides survived filtering, so the disagreement is about the world. The agent's
        job ends at stating it (`summary.md` §6)."""
        stages, ledger, _ = build(model=FakeModel(bucket="conflicting"))
        report = run(stages)
        self.assertEqual(report.rounds, 1)
        self.assertEqual(report.unresolved, ("claim-0001",))
        self.assertTrue(only_claim(ledger).is_contradicted)

    def test_a_claim_with_no_baseline_is_never_judged(self) -> None:
        """Judging it would be judging a claim nobody re-read the page for."""
        stages, _, _ = build(baseline=False)
        report = run(stages)
        self.assertEqual(report.skipped, ("claim-0001",))
        self.assertEqual(report.buckets, {})


class TestReclassification(unittest.TestCase):
    """The second sweep: a claim revised by evidence another claim's search went and fetched.

    Six claims are six searches, and the excerpt that contradicts one is very often the one a
    *different* claim's search returned. Classifying each in isolation threw that away — the
    run would reach a verdict with the contradiction sitting in its own memory.
    """

    def stages_where_one_search_names_the_other_subject(
        self,
    ) -> tuple[Stages, Ledger, FakeModel]:
        """Two claims. The second's search mentions the first's subject, so the first gains
        evidence it never asked for."""
        model = FakeModel(bucket="still_true", then="conflicting")
        stages, ledger, _ = build(FakeSearch(mentions="Gambit"), model, claims=2)
        return stages, ledger, model

    def test_evidence_from_elsewhere_reaches_a_claim(self) -> None:
        stages, _ledger, _model = self.stages_where_one_search_names_the_other_subject()
        run = Run(stages)
        run.audit()
        run.research()
        found = run.corroborating("claim-0001")
        self.assertTrue(found)
        self.assertNotIn(found[0]["url"], {r["url"] for r in run.searches["claim-0001"]["results"]})

    def test_a_claim_can_change_bucket_within_one_run(self) -> None:
        stages, _ledger, _model = self.stages_where_one_search_names_the_other_subject()
        report = run(stages)
        # Only the claim that gained something is re-asked: the other one already held that
        # excerpt, because its own search is where it came from.
        self.assertEqual(report.reclassified, ("claim-0001",))
        self.assertEqual(report.buckets, {"conflicting": 1, "still_true": 1})

    def test_both_readings_stay_on_the_record(self) -> None:
        """The revision and what it revised. A conclusion with no trace of the revision is the
        half that explains it."""
        stages, _ledger, _model = self.stages_where_one_search_names_the_other_subject()
        run(stages)
        history = stages.judgements.for_claim("claim-0001")
        self.assertEqual([j.attempt for j in history], [2, 1])  # newest reading first
        self.assertEqual([j.bucket for j in history], ["conflicting", "still_true"])

    def test_the_ledger_hears_the_revision_and_not_the_draft(self) -> None:
        """Settling is what ends the phase, and it happens once — on the verdict the claim
        ended with, never on the one it started with."""
        stages, ledger, _model = self.stages_where_one_search_names_the_other_subject()
        run(stages)
        self.assertTrue(only_claim(ledger).is_contradicted)

    def test_a_claim_nothing_new_bears_on_is_not_re_asked(self) -> None:
        """The sweep costs a model call per claim that actually gained evidence, and none for
        the rest — so a run of unrelated claims pays nothing for the capability."""
        model = FakeModel()
        stages, _, _ = build(FakeSearch(), model, claims=1)
        run(stages)
        self.assertEqual(model.seen.count("classify"), 1)


class TestTheBackwardEdge(unittest.TestCase):
    """`Classify → Research`, and the two things that make it safe to have at all."""

    def empty_batch(self) -> tuple[Stages, Ledger, FakeSearch]:
        search = FakeSearch()
        model = FakeModel(bucket="conflicting", off_entity=(URL,))
        stages, ledger, _ = build(search, model)
        return stages, ledger, search

    def test_a_batch_that_filtering_emptied_is_researched_again(self) -> None:
        stages, _, search = self.empty_batch()
        run = Run(stages)
        run.audit()
        run.research()
        run.classify()
        self.assertEqual(run.pending, ("claim-0001",))
        self.assertEqual(len(search.calls), 1)

    def test_the_retry_asks_a_broader_question(self) -> None:
        stages, _, search = self.empty_batch()
        run = Run(stages)
        run.audit()
        run.research()
        run.classify()
        run.research()
        first, second = search.calls
        self.assertNotEqual(first.objective, second.objective)

    def test_nothing_is_recorded_for_a_claim_that_will_be_retried(self) -> None:
        """The round is not concluded, and recording an outcome would reschedule a claim
        mid-decision."""
        stages, ledger, _ = self.empty_batch()
        before = only_claim(ledger).check_interval
        run = Run(stages)
        run.audit()
        run.research()
        run.classify()
        self.assertEqual(only_claim(ledger).check_interval, before)

    def test_the_budget_is_what_stops_it(self) -> None:
        """`record_research` spends a round without consulting the budget, so the Research
        node is the only thing standing between this edge and an unbounded loop."""
        stages, _ledger, search = self.empty_batch()
        report = straight_through_graph(stages)
        self.assertEqual(len(search.calls), MAX_RESEARCH_ROUNDS)
        self.assertEqual(report.rounds, MAX_RESEARCH_ROUNDS)

    def test_a_claim_out_of_budget_settles_as_unchanged(self) -> None:
        """No new data is no change (`AGENTS.md` §7) — and `unchanged` clears the spent rounds,
        so the next tick may research it again rather than finding it stuck."""
        stages, ledger, _ = self.empty_batch()
        straight_through_graph(stages)
        claim = only_claim(ledger)
        self.assertEqual(claim.research_rounds, 0)
        self.assertFalse(claim.is_contradicted)


class TestWhatReachesTheReviewer(unittest.TestCase):
    """Anything retrieval carried that the page does not say becomes a card.

    The rule the run turns on (`AGENTS.md` §7): `still_true` is the only bucket that produces
    nothing, because there is nothing to show. A conflict is not withheld pending a resolution
    — it is drafted as an edit that makes the disagreement visible, and the reviewer takes it
    or discards it.
    """

    def test_a_conflict_becomes_a_card(self) -> None:
        stages, _, drafts = build(model=FakeModel(bucket="conflicting"))
        report = run(stages)
        self.assertEqual(report.drafted, 1)
        self.assertEqual(len(drafts.all()[0].changes), 1)

    def test_the_card_carries_the_disagreement(self) -> None:
        """Without it the reviewer is being asked to take an edit on trust."""
        stages, _, drafts = build(model=FakeModel(bucket="conflicting"))
        run(stages)
        change = drafts.all()[0].changes[0]
        self.assertEqual(change.bucket, "conflicting")
        self.assertEqual(change.conflict, "sources split")
        self.assertEqual(change.conflict_sources, (URL, OTHER_URL))

    def test_the_claim_is_still_unresolved(self) -> None:
        """Drafting a conflict is not resolving it. The card is a proposal; the claim stays
        contradicted until a human does something about it, and accepting the card publishes an
        edit rather than picking a side (`AGENTS.md` §2)."""
        stages, ledger, _ = build(model=FakeModel(bucket="conflicting"))
        report = run(stages)
        self.assertTrue(only_claim(ledger).is_contradicted)
        self.assertEqual(report.unresolved, ("claim-0001",))

    def test_a_confirmed_claim_still_produces_nothing(self) -> None:
        stages, _, drafts = build(model=FakeModel(bucket="still_true"))
        self.assertEqual(run(stages).drafted, 0)
        self.assertEqual(drafts.all(), ())


class TestDraftAndDiff(unittest.TestCase):
    def test_one_bad_answer_does_not_cost_the_others_their_review(self) -> None:
        """A `ModelError` is a domain failure — a refusal, a malformed answer — so it is caught
        per claim. A timeout is not this, and still propagates for ADK to retry."""
        stages, _, drafts = build(model=FakeModel(draft_fails=True), claims=2)
        report = run(stages)
        self.assertEqual(len(report.failed), 2)
        self.assertEqual(report.drafted, 0)
        self.assertEqual(drafts.all(), ())

    def test_the_card_carries_both_readings(self) -> None:
        """`shape()` is the floor and the Diff stage is the reading; a card that dropped either
        would misrepresent what was checked."""
        stages, _, drafts = build(
            model=FakeModel(after="|movie = ''[[Avengers: Doomsday]]''", dispositions=("dropped",))
        )
        run(stages)
        change = drafts.all()[0].changes[0]
        self.assertIn("overreached", change.flags)
        self.assertEqual(len(change.flags), len(set(change.flags)))

    def test_an_unavailable_diff_model_flags_the_card_rather_than_failing_the_run(self) -> None:
        stages, _, drafts = build(model=FakeModel(diff_fails=True))
        run(stages)
        self.assertIn("text_only", drafts.all()[0].changes[0].flags)


class TestVerify(unittest.TestCase):
    def test_the_run_hands_over_one_draft_holding_every_change(self) -> None:
        stages, _, drafts = build(claims=2)
        report = run(stages)
        stored = drafts.all()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].draft_id, report.draft_id)
        self.assertEqual(len(stored[0].changes), 2)

    def test_every_change_arrives_undecided_and_unpublished(self) -> None:
        stages, _, drafts = build()
        run(stages)
        stored = drafts.all()[0]
        self.assertFalse(stored.published)
        self.assertFalse(stored.is_decided)

    def test_a_run_that_proposed_nothing_stores_nothing(self) -> None:
        """An empty draft is a card set with no cards, and it would sit at the head of the
        gate's unpublished list saying so."""
        stages, _, drafts = build(model=FakeModel(bucket="still_true"))
        report = run(stages)
        self.assertEqual(drafts.all(), ())
        self.assertFalse(report.stored)

    def test_the_change_is_addressed_at_the_anchor_not_the_section(self) -> None:
        stages, _, drafts = build()
        run(stages)
        change = drafts.all()[0].changes[0]
        self.assertEqual(change.before, ANCHOR)
        self.assertIn(ANCHOR, change.after)
        self.assertNotIn("Infobox", change.after)


def straight_through_graph(stages: Stages) -> Any:
    """`straight_through` cannot express the backward edge, so the tests that need it drive
    the loop the way the graph does: Classify hands back to Research until it stops."""
    run = Run(stages)
    run.audit()
    while True:
        run.research()
        run.classify()
        if not run.pending:
            break
    run.draft()
    run.diff()
    run.verify()
    return run.report


class TestProvenance(unittest.TestCase):
    """Every document a run writes names the task that wrote it (`AGENTS.md` §2).

    The rule is only worth having if it holds on *all* of them: a `task_id` that is present on
    two collections and empty on the third is worse than none, because it reads as "no task
    touched this" rather than "nobody stamped it".
    """

    def run_one(self) -> tuple[Any, Ledger, InMemoryDraftStore, InMemoryJudgementStore]:
        stages, ledger, drafts = build()
        report = run(stages)
        judgements = stages.judgements
        assert isinstance(judgements, InMemoryJudgementStore)
        return report, ledger, drafts, judgements

    def test_the_task_id_is_minted_once_and_shared(self) -> None:
        report, ledger, drafts, judgements = self.run_one()
        self.assertTrue(report.task_id.startswith("task-"))
        self.assertEqual(only_claim(ledger).task_id, report.task_id)
        self.assertEqual(drafts.all()[0].task_id, report.task_id)
        self.assertEqual(judgements.all()[0].task_id, report.task_id)

    def test_the_draft_is_named_for_its_task(self) -> None:
        report, _, drafts, _ = self.run_one()
        self.assertEqual(drafts.all()[0].draft_id, report.draft_id)
        self.assertEqual(report.draft_id, report.task_id.replace("task-", "draft-"))

    def test_a_judgement_is_stored_for_every_claim_classified(self) -> None:
        stages, _, _ = build(claims=2)
        report = run(stages)
        stored = stages.judgements.for_task(report.task_id)
        self.assertEqual(len(stored), 2)
        self.assertEqual({j.bucket for j in stored}, {"new"})

    def test_the_judgement_carries_the_reason_the_ledger_does_not(self) -> None:
        """`record_outcome` stores `changed`; *why* it changed lived only in the cassette."""
        _, _, _, judgements = self.run_one()
        stored = judgements.all()[0]
        self.assertEqual(stored.outcome, "changed")
        self.assertIn("Doomsday", stored.reason)
        # The question the round actually asked, derived by the run because the claim carried
        # none — stored so a later reader knows what was pursued, not just what came back.
        self.assertIn("Gambit", stored.objective)
        self.assertTrue(stored.considered)

    def test_a_second_run_adds_a_row_rather_than_replacing_one(self) -> None:
        """Two tasks, one claim, two records — which is what makes the collection a history."""
        stages, ledger, _ = build()
        first = run(stages)
        later = replace(
            stages, clock=lambda: NOW + timedelta(days=1), ledger=Ledger(
                PROFILE, ledger.store, clock=lambda: NOW + timedelta(days=1)
            )
        )
        second = run(later)
        self.assertNotEqual(first.task_id, second.task_id)
        self.assertEqual(len(stages.judgements.for_claim("claim-0001")), 2)

    def test_the_run_overruling_the_model_is_visible_in_the_record(self) -> None:
        """A budget exhausted with nothing to judge settles `unchanged` whatever the bucket
        said. Storing only the outcome would hide the override; only the bucket would claim a
        conflict the ledger never recorded.

        Every attempt is a row, so what the claim looks like afterwards is its whole history:
        judged `conflicting` on each round, and overruled to `unchanged` on the last."""
        stages, _, _ = build(FakeSearch(), FakeModel(bucket="conflicting", off_entity=(URL,)))
        report = straight_through_graph(stages)
        stored = sorted(stages.judgements.for_task(report.task_id), key=lambda j: j.attempt)
        self.assertEqual([j.attempt for j in stored], [1, 2, MAX_RESEARCH_ROUNDS])
        self.assertEqual({j.bucket for j in stored}, {"conflicting"})
        self.assertEqual(stored[-1].outcome, "unchanged")
        self.assertEqual({j.outcome for j in stored[:-1]}, {"unresolved"})

    def test_the_baseline_a_run_reads_names_its_own_pass(self) -> None:
        """Ingest is outside the graph but is still a task, so the rule reaches it too."""
        section = SectionBaseline(page="Gambit", section_index=0, section_heading="",
                                  text=SECTION, revid=1, fetched_at=NOW, task_id="task-x")
        self.assertEqual(from_baseline_document(to_baseline_document(section)).task_id, "task-x")


# -- the run ------------------------------------------------------------------------------


class TestTheRun(unittest.TestCase):
    """What only the assembled run can be asked.

    These used to inspect an ADK `Workflow` — its START edge, its forward edges, its routing
    map. The orchestrator is a plain method now (`Run.execute`), so the questions are the same
    and the answers come from behaviour rather than from a graph object: does it visit the
    stages in order, does the backward edge fire, does it stop, and is Publish still absent.
    They need no SDK, so unlike the old ones they run on a bare interpreter.
    """

    def test_the_stages_run_in_the_order_the_architecture_draws_them(self) -> None:
        stages, _, _ = build()
        report = run(stages)
        self.assertEqual(report.stages, STAGES)

    def test_publishing_is_not_a_stage(self) -> None:
        """Publish is a button on a route, so it cannot be reached from here. A stage that
        wrote to the wiki would make the gate optional."""
        self.assertNotIn("publish", STAGES)
        stages, _, _ = build()
        self.assertNotIn("publish", run(stages).stages)

    def test_a_run_reaches_the_stored_draft(self) -> None:
        stages, _, drafts = build()
        report = run(stages)
        self.assertEqual(report.drafted, 1)
        self.assertEqual(drafts.all()[0].draft_id, report.draft_id)

    def test_the_backward_edge_fires_and_stops(self) -> None:
        """The one thing a straight line cannot express, and the one thing that could hang a
        tick if the budget check were ever moved out of the Research node. The loop is bounded
        by the per-claim research budget, not by the backstop constant."""
        search = FakeSearch()
        stages, _, _ = build(search, FakeModel(bucket="conflicting", off_entity=(URL,)))
        report = run(stages)
        self.assertEqual(report.rounds, MAX_RESEARCH_ROUNDS)
        self.assertEqual(len(search.calls), MAX_RESEARCH_ROUNDS)

    def test_a_run_that_never_needs_a_second_round_researches_once(self) -> None:
        search = FakeSearch()
        stages, _, _ = build(search)
        self.assertEqual(run(stages).rounds, 1)
        self.assertEqual(len(search.calls), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
