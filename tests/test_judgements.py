"""The judgement: one claim, classified once, by one task.

The collection exists to answer "why was this claim routed that way" after the fact, so the
cases that matter are the ones about *keeping* history rather than about reading it: the same
claim judged twice must be two rows, and the sentence behind a verdict must survive a restart.

Pure and dependency-free, like the ledger beside it: these run on a bare interpreter.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backend.core.ledger.documents import is_firestore_safe, task_id_for
from backend.core.ledger.judgements import (
    InMemoryJudgementStore,
    Judgement,
    from_document,
    to_document,
)
from backend.mongo import MongoJudgementStore
from tests.mongo_support import MongoTestCase, requires_mongo

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
TASK = task_id_for(NOW)
URL_A = "https://deadline.com/2024/07/doomsday"
URL_B = "https://variety.com/2024/07/gambit"


def judgement(**over: object) -> Judgement:
    fields: dict[str, object] = {
        "task_id": TASK,
        "claim_id": "GAM-APP-01",
        "page": "Gambit",
        "bucket": "new",
        "outcome": "changed",
        "reason": "Retrieval carries a film the infobox does not list.",
        "decided_at": NOW,
        "objective": "Which announced films does Gambit appear in?",
        "considered": (URL_A, URL_B),
    }
    fields.update(over)
    return Judgement(**fields)  # type: ignore[arg-type]


class TestWhatOneRecords(unittest.TestCase):
    def test_a_claim_judged_twice_is_two_rows(self) -> None:
        """The whole reason the id carries both. Keyed by claim alone, a second run would
        erase the record of what the first one said — which is the history itself."""
        later = task_id_for(NOW + timedelta(days=1))
        store = InMemoryJudgementStore([judgement(), judgement(task_id=later)])
        self.assertEqual(len(store.for_claim("GAM-APP-01")), 2)

    def test_re_recording_one_attempt_is_a_correction(self) -> None:
        """Same task, same claim, same attempt: one row, corrected."""
        store = InMemoryJudgementStore()
        store.put(judgement())
        store.put(judgement(bucket="still_true", outcome="unchanged"))
        self.assertEqual(len(store.all()), 1)
        self.assertEqual(store.all()[0].bucket, "still_true")

    def test_a_reclassification_keeps_what_it_revised(self) -> None:
        """The case the attempt exists for: evidence another claim's search turned up moved
        this one to a different bucket, and both readings stay on the record."""
        store = InMemoryJudgementStore()
        store.put(judgement(bucket="still_true", outcome="unchanged"))
        store.put(judgement(attempt=2, bucket="conflicting", outcome="unresolved"))
        history = store.for_claim("GAM-APP-01")
        self.assertEqual([j.attempt for j in history], [2, 1])
        self.assertEqual(history[0].bucket, "conflicting")

    def test_the_newest_attempt_reads_first(self) -> None:
        """A revision and what it revised share one clock — the run's — so the attempt is what
        orders them, or a superseded judgement sits above the one that replaced it."""
        store = InMemoryJudgementStore([judgement(attempt=2), judgement()])
        self.assertEqual(store.all()[0].attempt, 2)

    def test_bucket_and_outcome_are_two_statements(self) -> None:
        """What the model said, and what the ledger did about it. They diverge exactly once —
        a budget exhausted with nothing to judge settles `unchanged` whatever the bucket was —
        and a record that stored only one of them could not show that happening."""
        overruled = judgement(bucket="conflicting", outcome="unchanged")
        self.assertNotEqual(overruled.bucket, overruled.outcome)

    def test_survivors_are_what_filtering_left(self) -> None:
        self.assertEqual(judgement(off_entity=(URL_A,)).survivors, (URL_B,))

    def test_nothing_surviving_is_the_off_target_signal(self) -> None:
        """Empty survivors is retrieval having gone off-subject, not the world disagreeing —
        the distinction the graph's backward edge turns on."""
        self.assertEqual(judgement(off_entity=(URL_A, URL_B)).survivors, ())

    def test_a_conflict_names_both_sides(self) -> None:
        plain = judgement()
        conflicted = judgement(bucket="conflicting", note="sources split", source_a=URL_A,
                               source_b=URL_B)
        self.assertFalse(plain.is_conflict)
        self.assertTrue(conflicted.is_conflict)


class TestTheStoredShape(unittest.TestCase):
    def test_a_judgement_round_trips(self) -> None:
        original = judgement(off_entity=(URL_A,), note="n", source_a=URL_A, source_b=URL_B)
        self.assertEqual(from_document(to_document(original)), original)

    def test_only_firestore_value_types_are_emitted(self) -> None:
        self.assertTrue(is_firestore_safe(to_document(judgement())))

    def test_a_version_this_build_does_not_read_is_refused(self) -> None:
        document = to_document(judgement())
        document["v"] = 99
        with self.assertRaises(ValueError):
            from_document(document)

    def test_the_document_is_keyed_by_task_claim_and_attempt(self) -> None:
        self.assertEqual(to_document(judgement())["judgement_id"], f"{TASK}--GAM-APP-01--a1")


class TestStores(unittest.TestCase):
    def test_newest_first(self) -> None:
        later = judgement(task_id=task_id_for(NOW + timedelta(days=1)),
                          decided_at=NOW + timedelta(days=1))
        store = InMemoryJudgementStore([judgement(), later])
        self.assertEqual(store.all()[0].decided_at, later.decided_at)

    def test_a_task_can_be_read_back_whole(self) -> None:
        store = InMemoryJudgementStore(
            [judgement(), judgement(claim_id="DW-VOID-01"),
             judgement(task_id=task_id_for(NOW + timedelta(days=1)))]
        )
        self.assertEqual({j.claim_id for j in store.for_task(TASK)},
                         {"GAM-APP-01", "DW-VOID-01"})


@requires_mongo
class TestMongoJudgementStore(MongoTestCase):
    """The record has to survive the run that wrote it — that is what makes it history."""

    def store(self) -> MongoJudgementStore:
        return MongoJudgementStore(self.db)

    def test_the_reason_survives_the_process(self) -> None:
        """The point of storing it at all: the sentence behind a verdict used to live only in
        the model cassette, which is gitignored and regenerated."""
        self.store().put(judgement())
        reopened = self.store().for_claim("GAM-APP-01")
        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0].task_id, TASK)

    def test_an_empty_collection_reads_empty(self) -> None:
        self.assertEqual(self.store().all(), ())

    def test_the_same_task_claim_and_attempt_corrects_one_row(self) -> None:
        """Re-running the same attempt corrects one row rather than filing a second opinion:
        a genuinely different judgement already has a different id."""
        store = self.store()
        store.put(judgement())
        store.put(judgement())
        self.assertEqual(len(store.all()), 1)

    def test_for_task_selects(self) -> None:
        store = self.store()
        store.put(judgement())
        self.assertEqual(len(store.for_task(TASK)), 1)
        self.assertEqual(store.for_task("task-nope"), ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
