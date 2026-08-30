"""The review draft: the lifecycle, the stored shape, and what survives a restart.

The gate's whole promise is that a decision outlives the tab it was made in, so the cases here
are about the three fields that carry it — the verdict on a change, the revision a change
actually wrote, and the stamp that says the set is published. Two of them exist for the same
reason: a publish can partially fail, and the retry has to know what already landed.

Pure and dependency-free, like the claim ledger beside it: these run on a bare interpreter.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.ledger.drafts import (
    Change,
    Decision,
    DraftError,
    InMemoryDraftStore,
    JsonFileDraftStore,
    ReviewDraft,
    from_document,
    to_document,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def change(edit_id: str = "edit-a", **kwargs: object) -> Change:
    fields: dict[str, object] = {
        "edit_id": edit_id,
        "claim_id": "GAM-APP-01",
        "page": "Gambit",
        "page_slug": "Gambit",
        "section_index": 0,
        "section_heading": "",
        "before": "|movie = ''[[Deadpool & Wolverine]]''",
        "after": "|movie = ''[[Deadpool & Wolverine]]''<br>''[[Avengers: Doomsday]]''",
        "summary": "Gambit — appears in Doomsday",
        "rationale": "The infobox lists one film; a second is announced.",
        "confidence": 0.98,
    }
    fields.update(kwargs)
    return Change(**fields)  # type: ignore[arg-type]


def draft(*changes: Change, published_at: datetime | None = None) -> ReviewDraft:
    return ReviewDraft(
        draft_id="draft-0001",
        wiki="Continuity Wiki",
        created_at=NOW,
        changes=changes or (change(),),
        published_at=published_at,
    )


class TestVerdicts(unittest.TestCase):
    def test_a_change_starts_undecided(self) -> None:
        self.assertIs(change().decision, Decision.UNDECIDED)
        self.assertFalse(draft().is_decided)

    def test_deciding_returns_a_new_draft(self) -> None:
        """Immutable like `Claim`: a caller cannot half-apply a transition."""
        before = draft()
        after = before.decide("edit-a", Decision.ACCEPTED)
        self.assertIs(before.changes[0].decision, Decision.UNDECIDED)
        self.assertIs(after.changes[0].decision, Decision.ACCEPTED)

    def test_the_gate_opens_once_every_change_has_a_verdict(self) -> None:
        two = draft(change("edit-a"), change("edit-b"))
        self.assertFalse(two.decide("edit-a", Decision.ACCEPTED).is_decided)
        self.assertTrue(
            two.decide("edit-a", Decision.ACCEPTED).decide("edit-b", Decision.REJECTED).is_decided
        )

    def test_a_rejection_takes_the_change_out_of_the_publishable_set(self) -> None:
        """Rejecting is a discard, not a verdict on the claim (`AGENTS.md` §2). Nothing here
        touches the claim, and the change simply stops being something to write."""
        rejected = draft().decide("edit-a", Decision.REJECTED)
        self.assertEqual(rejected.accepted, ())
        self.assertEqual(rejected.publishable, ())
        self.assertTrue(rejected.is_decided)

    def test_changing_your_mind_is_a_verdict_and_not_a_delete(self) -> None:
        back = draft().decide("edit-a", Decision.ACCEPTED).decide("edit-a", Decision.UNDECIDED)
        self.assertIs(back.changes[0].decision, Decision.UNDECIDED)
        self.assertEqual(len(back.changes), 1)

    def test_an_unknown_change_is_refused(self) -> None:
        with self.assertRaises(DraftError):
            draft().decide("edit-nope", Decision.ACCEPTED)


class TestTheReviewersOwnText(unittest.TestCase):
    def test_a_hand_edit_replaces_the_after_text(self) -> None:
        edited = draft().revise("edit-a", "what the reviewer settled on")
        self.assertEqual(edited.changes[0].after, "what the reviewer settled on")

    def test_the_edit_is_what_publishes(self) -> None:
        """`AGENTS.md` §7: the text a reviewer approved is what goes on the wiki. Storing it is
        what makes that survive the reload the store exists for."""
        edited = draft().revise("edit-a", "mine").decide("edit-a", Decision.ACCEPTED)
        self.assertEqual(edited.publishable[0].after, "mine")

    def test_an_empty_replacement_is_refused(self) -> None:
        # `parse()` in the draft stage refuses this from the model for the same reason: an
        # empty replacement deletes the anchor if anyone approves it.
        with self.assertRaises(DraftError):
            draft().revise("edit-a", "   ")


class TestPublishing(unittest.TestCase):
    def test_a_draft_is_unpublished_until_every_accepted_change_is_written(self) -> None:
        two = draft(change("edit-a"), change("edit-b"))
        two = two.decide("edit-a", Decision.ACCEPTED).decide("edit-b", Decision.ACCEPTED)
        one_written = two.mark_written("edit-a", 101).settled(NOW)
        self.assertFalse(one_written.published)
        both = one_written.mark_written("edit-b", 102).settled(NOW)
        self.assertTrue(both.published)
        self.assertEqual(both.published_at, NOW)

    def test_a_retry_writes_only_what_is_outstanding(self) -> None:
        """The reason `written_revid` is stored. MediaWiki has no cross-page transaction, so a
        partial failure is real — and the second press must not rewrite what already landed."""
        two = draft(change("edit-a"), change("edit-b"))
        two = two.decide("edit-a", Decision.ACCEPTED).decide("edit-b", Decision.ACCEPTED)
        after_failure = two.mark_written("edit-a", 101)
        self.assertEqual([c.edit_id for c in after_failure.publishable], ["edit-b"])

    def test_a_rejected_change_never_becomes_publishable(self) -> None:
        mixed = draft(change("edit-a"), change("edit-b"))
        mixed = mixed.decide("edit-a", Decision.ACCEPTED).decide("edit-b", Decision.REJECTED)
        self.assertEqual([c.edit_id for c in mixed.publishable], ["edit-a"])

    def test_a_draft_where_everything_was_discarded_is_not_published(self) -> None:
        """It wrote nothing, so saying `published` would put the flag on a run that never
        touched the wiki. It stays open instead."""
        discarded = draft().decide("edit-a", Decision.REJECTED).settled(NOW)
        self.assertFalse(discarded.published)

    def test_publishing_is_stamped_once(self) -> None:
        later = NOW + timedelta(hours=1)
        done = draft().decide("edit-a", Decision.ACCEPTED).mark_written("edit-a", 101)
        first = done.settled(NOW)
        self.assertEqual(first.settled(later).published_at, NOW)

    def test_a_published_draft_refuses_further_decisions(self) -> None:
        done = draft().decide("edit-a", Decision.ACCEPTED).mark_written("edit-a", 101).settled(NOW)
        with self.subTest("a new verdict"), self.assertRaises(DraftError):
            done.decide("edit-a", Decision.REJECTED)
        with self.subTest("a late hand-edit"), self.assertRaises(DraftError):
            done.revise("edit-a", "too late")


class TestTheStoredShape(unittest.TestCase):
    def test_a_draft_round_trips(self) -> None:
        original = (
            draft(change("edit-a"), change("edit-b"))
            .decide("edit-a", Decision.ACCEPTED)
            .revise("edit-a", "mine")
            .mark_written("edit-a", 101)
            .decide("edit-b", Decision.REJECTED)
        )
        self.assertEqual(from_document(to_document(original)), original)

    def test_only_firestore_value_types_are_emitted(self) -> None:
        """The adapter hands this straight to `.set()`, so anything else would fail deployed
        and pass locally — JSON would have encoded it on the way out."""
        allowed = (str, int, float, bool, type(None), datetime, list, dict)
        document = to_document(draft().decide("edit-a", Decision.ACCEPTED))

        def walk(value: object) -> None:
            self.assertIsInstance(value, allowed)
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertIsInstance(key, str)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(document)

    def test_the_disagreement_round_trips(self) -> None:
        """A conflicting card is only readable if what the sources fell out over survives the
        store — the gate renders one draft, not the ledger behind it."""
        contested = draft(
            change("edit-a", bucket="conflicting", conflict="One says Doomsday, one Secret Wars",
                   conflict_sources=("https://deadline.com/a", "https://variety.com/b"))
        )
        restored = from_document(to_document(contested)).changes[0]
        self.assertEqual(restored.conflict, "One says Doomsday, one Secret Wars")
        self.assertEqual(len(restored.conflict_sources), 2)

    def test_an_ordinary_card_carries_no_disagreement(self) -> None:
        self.assertEqual(from_document(to_document(draft())).changes[0].conflict, "")

    def test_the_diff_is_not_stored(self) -> None:
        """It is a view of `before`/`after`, and a stored view is one a hand-edit invalidates."""
        self.assertNotIn("diff", to_document(draft())["changes"][0])

    def test_a_version_this_build_does_not_read_is_refused(self) -> None:
        document = to_document(draft())
        document["version"] = 99
        with self.assertRaises(DraftError):
            from_document(document)

    def test_timestamps_come_back_aware(self) -> None:
        """A naive datetime compares wrong against `now(timezone.utc)`, and the local file
        stores an ISO string where Firestore stores an instant."""
        document = to_document(draft())
        document["created_at"] = "2026-08-30T12:00:00"  # naive, as a bad writer might leave it
        self.assertIsNotNone(from_document(document).created_at.tzinfo)


class TestStores(unittest.TestCase):
    def test_the_memory_store_returns_newest_first(self) -> None:
        older = ReviewDraft("draft-0001", "w", NOW - timedelta(days=1), (change(),))
        newer = ReviewDraft("draft-0002", "w", NOW, (change(),))
        store = InMemoryDraftStore([older, newer])
        self.assertEqual([d.draft_id for d in store.all()], ["draft-0002", "draft-0001"])

    def test_unpublished_is_the_work_still_waiting(self) -> None:
        done = ReviewDraft("draft-0001", "w", NOW, (change(),), published_at=NOW)
        open_one = ReviewDraft("draft-0002", "w", NOW, (change(),))
        store = InMemoryDraftStore([done, open_one])
        self.assertEqual([d.draft_id for d in store.unpublished()], ["draft-0002"])

    def test_a_decision_survives_the_process(self) -> None:
        """The whole point of the store. Written by one instance, read by the next."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "drafts.json"
            first = JsonFileDraftStore(path)
            first.put(draft().decide("edit-a", Decision.ACCEPTED).revise("edit-a", "mine"))

            reopened = JsonFileDraftStore(path).get("draft-0001")
            assert reopened is not None
            self.assertIs(reopened.changes[0].decision, Decision.ACCEPTED)
            self.assertEqual(reopened.changes[0].after, "mine")

    def test_a_missing_file_is_an_empty_store_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(JsonFileDraftStore(Path(tmp) / "nothing.json").all(), ())

    def test_the_file_is_replaced_atomically(self) -> None:
        # An interrupted publish must leave the previous draft readable, not a truncated file.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "drafts.json"
            store = JsonFileDraftStore(path)
            store.put(draft())
            self.assertFalse(path.with_name(path.name + ".tmp").exists())
            self.assertIn("drafts", json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
