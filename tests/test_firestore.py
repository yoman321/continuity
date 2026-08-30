"""The Firestore adapter: what it puts on the wire, and what it refuses to do in Python.

Run against a fake client rather than the emulator, for the same reason `test_wiki_write.py`
asserts on the request `action=edit` builds instead of editing a wiki: the adapter's whole job
is the call it makes, and a test that needs a JRE and `gcloud components install` is a test that
does not run. What this cannot prove is that Firestore accepts the document — that is why
`DRAFT_STORE=file` stays the default until it has been run for real (`backend/firestore.py`).
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.ledger.drafts import Change, Decision, ReviewDraft, to_document
from backend.core.ledger.judgements import COLLECTION as JUDGEMENTS_COLLECTION
from backend.core.ledger.judgements import Judgement
from backend.core.ledger.judgements import to_document as judgement_to_document
from backend.firestore import COLLECTION, FirestoreDraftStore, FirestoreJudgementStore

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def change(edit_id: str = "edit-a") -> Change:
    return Change(
        edit_id=edit_id,
        claim_id="GAM-APP-01",
        page="Gambit",
        page_slug="Gambit",
        section_index=0,
        section_heading="",
        before="before",
        after="after",
        summary="s",
        rationale="r",
        confidence=0.9,
    )


def draft(draft_id: str = "draft-0001", created_at: datetime = NOW) -> ReviewDraft:
    return ReviewDraft(draft_id, "Continuity Wiki", created_at, (change(),))


class FakeSnapshot:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return self._data


class FakeDocument:
    def __init__(self, collection: FakeCollection, doc_id: str) -> None:
        self._collection = collection
        self._id = doc_id

    def get(self) -> FakeSnapshot:
        self._collection.reads.append(self._id)
        return FakeSnapshot(self._collection.docs.get(self._id))

    def set(self, document: dict[str, Any]) -> None:
        self._collection.docs[self._id] = document


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.reads: list[str] = []
        self.streamed = 0

    def document(self, doc_id: str) -> FakeDocument:
        return FakeDocument(self, doc_id)

    def stream(self) -> list[FakeSnapshot]:
        self.streamed += 1
        return [FakeSnapshot(d) for d in self.docs.values()]


class FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def collection(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def store() -> tuple[FirestoreDraftStore, FakeCollection]:
    client = FakeClient()
    return FirestoreDraftStore(client=client), client.collection(COLLECTION)


class TestTheWire(unittest.TestCase):
    def test_the_document_stored_is_the_one_the_core_emits(self) -> None:
        """No field is named twice. If this adapter built its own shape, the local store and the
        deployed one would drift and only production would notice."""
        drafts, collection = store()
        drafts.put(draft())
        self.assertEqual(collection.docs["draft-0001"], to_document(draft()))

    def test_a_draft_is_keyed_by_its_own_id(self) -> None:
        drafts, collection = store()
        drafts.put(draft("draft-0007"))
        self.assertEqual(list(collection.docs), ["draft-0007"])

    def test_a_read_is_one_document_get_not_a_scan(self) -> None:
        drafts, collection = store()
        drafts.put(draft())
        drafts.get("draft-0001")
        self.assertEqual(collection.reads, ["draft-0001"])
        self.assertEqual(collection.streamed, 0)

    def test_a_draft_round_trips_through_the_fake(self) -> None:
        drafts, _ = store()
        original = draft().decide("edit-a", Decision.ACCEPTED).mark_written("edit-a", 101)
        drafts.put(original)
        self.assertEqual(drafts.get("draft-0001"), original)

    def test_a_missing_draft_is_none(self) -> None:
        drafts, _ = store()
        self.assertIsNone(drafts.get("draft-nope"))

    def test_it_uses_the_collection_the_module_names(self) -> None:
        client = FakeClient()
        FirestoreDraftStore(client=client).put(draft())
        self.assertEqual(list(client.collections), [COLLECTION])


class TestOrderingIsDoneInPython(unittest.TestCase):
    """`order_by` plus a filter needs a composite index, the emulator does not enforce index
    requirements, and a missing one fails only in production (`AGENTS.md` §6). So the sort and
    the unpublished filter happen here, where they cannot be missing."""

    def test_newest_first(self) -> None:
        drafts, _ = store()
        drafts.put(draft("draft-0001", NOW - timedelta(days=1)))
        drafts.put(draft("draft-0002", NOW))
        self.assertEqual([d.draft_id for d in drafts.all()], ["draft-0002", "draft-0001"])

    def test_unpublished_is_filtered_after_the_read(self) -> None:
        drafts, collection = store()
        drafts.put(draft("draft-0001"))
        drafts.put(
            draft("draft-0002").decide("edit-a", Decision.ACCEPTED)
            .mark_written("edit-a", 101)
            .settled(NOW)
        )
        self.assertEqual([d.draft_id for d in drafts.unpublished()], ["draft-0001"])
        self.assertGreater(collection.streamed, 0)


class TestTheJudgementCollection(unittest.TestCase):
    """The fourth collection, on the same fake client and for the same reason."""

    def store(self) -> tuple[FirestoreJudgementStore, FakeClient]:
        client = FakeClient()
        return FirestoreJudgementStore(client=client), client

    def judgement(self, task: str = "task-0001", claim: str = "GAM-APP-01") -> Judgement:
        return Judgement(
            task_id=task, claim_id=claim, page="Gambit", bucket="new", outcome="changed",
            reason="Retrieval carries a film the page does not list.", decided_at=NOW,
        )

    def test_the_document_stored_is_the_one_the_core_emits(self) -> None:
        judgements, client = self.store()
        judgements.put(self.judgement())
        collection = client.collection(JUDGEMENTS_COLLECTION)
        self.assertEqual(
            collection.docs["task-0001--GAM-APP-01--a1"],
            judgement_to_document(self.judgement()),
        )

    def test_it_uses_its_own_collection_not_the_drafts_one(self) -> None:
        judgements, client = self.store()
        judgements.put(self.judgement())
        self.assertEqual(list(client.collections), [JUDGEMENTS_COLLECTION])
        self.assertNotEqual(JUDGEMENTS_COLLECTION, COLLECTION)

    def test_a_reclassification_is_its_own_document(self) -> None:
        """Same task, same claim, second reading — two rows, or the revision erases what it
        revised (`core/ledger/judgements.py`)."""
        judgements, client = self.store()
        judgements.put(self.judgement())
        judgements.put(replace(self.judgement(), attempt=2, bucket="conflicting"))
        self.assertEqual(len(client.collection(JUDGEMENTS_COLLECTION).docs), 2)

    def test_a_claim_judged_by_two_tasks_is_two_documents(self) -> None:
        judgements, client = self.store()
        judgements.put(self.judgement())
        judgements.put(self.judgement(task="task-0002"))
        self.assertEqual(len(client.collection(JUDGEMENTS_COLLECTION).docs), 2)
        self.assertEqual(len(judgements.for_claim("GAM-APP-01")), 2)

    def test_filtering_happens_in_python(self) -> None:
        """`for_task` and `for_claim` would each need their own index, and a missing index
        fails only in production (`AGENTS.md` §6)."""
        judgements, client = self.store()
        judgements.put(self.judgement())
        judgements.put(self.judgement(task="task-0002", claim="DW-VOID-01"))
        self.assertEqual([j.claim_id for j in judgements.for_task("task-0002")], ["DW-VOID-01"])
        self.assertGreater(client.collection(JUDGEMENTS_COLLECTION).streamed, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
