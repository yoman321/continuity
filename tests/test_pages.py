"""Page records — the document a page gets on its first run, and the counter that names runs.

Two halves, and the split is the same one `test_ledger_store.py` makes. The codec and the
in-memory store are pure and run on a bare interpreter; the assertions that only mean something
against a real database — a counter that survives the process, and two presses that arrive
together — run against mongod and skip without it.

The test that matters most is the concurrent one. Every other property here would pass just as
well with a read-then-write counter, and that counter would hand two runs the same number the
first time a reader double-clicked.
"""

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.ledger.documents import is_firestore_safe
from backend.core.ledger.pages import (
    InMemoryPageStore,
    PageRecord,
    PageStore,
    from_document,
    run_id_for,
    to_document,
)
from backend.mongo import MongoPageStore
from tests.mongo_support import MongoTestCase, requires_mongo

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
GAMBIT = "Gambit (Marvel Comics)"


class TestRunId(unittest.TestCase):
    def test_the_id_names_the_page_and_the_number(self) -> None:
        self.assertEqual(run_id_for("Gambit", 3), "run-Gambit-0003")

    def test_a_title_is_slugged_by_the_one_slug_rule(self) -> None:
        # Whatever `slug_for` does to punctuation, the id and the document key do it the same
        # way — they are the same call.
        self.assertEqual(run_id_for(GAMBIT, 1), "run-Gambit_Marvel_Comics-0001")

    def test_ids_sort_in_run_order_as_strings(self) -> None:
        # The reason for the zero padding: these are sorted as strings in every store and in
        # every listing, and run 10 before run 2 is a listing nobody trusts twice.
        ids = [run_id_for("Gambit", n) for n in (2, 10, 1)]
        self.assertEqual(sorted(ids), [run_id_for("Gambit", n) for n in (1, 2, 10)])

    def test_run_zero_is_refused_rather_than_written(self) -> None:
        # There is no run 0. A caller reaching this passed a count where an ordinal belonged.
        with self.assertRaises(ValueError):
            run_id_for("Gambit", 0)


class TestDocumentRoundTrip(unittest.TestCase):
    def record(self, **overrides: Any) -> PageRecord:
        base: dict[str, Any] = dict(
            page=GAMBIT, created_at=NOW, runs=3, last_run_at=NOW + timedelta(hours=2)
        )
        base.update(overrides)
        return PageRecord(**base)

    def test_every_field_survives(self) -> None:
        self.assertEqual(from_document(to_document(self.record())), self.record())

    def test_a_fresh_record_survives(self) -> None:
        fresh = PageRecord(page=GAMBIT, created_at=NOW)
        self.assertEqual(from_document(to_document(fresh)), fresh)

    def test_document_holds_only_firestore_types(self) -> None:
        # The portability claim: this adapter is transport, and the same document goes to
        # Firestore untranslated.
        self.assertTrue(all(is_firestore_safe(v) for v in to_document(self.record()).values()))

    def test_derived_values_are_not_stored(self) -> None:
        # `last_run_id` is a function of the title and the counter. Stored, it would be a
        # second answer able to disagree with the first — and a second write to make.
        self.assertNotIn("last_run_id", to_document(self.record()))

    def test_unknown_version_is_refused_not_guessed(self) -> None:
        doc = to_document(self.record())
        doc["v"] = 99
        with self.assertRaises(ValueError):
            from_document(doc)

    def test_timestamps_read_back_aware(self) -> None:
        restored = from_document(to_document(self.record()))
        assert restored.last_run_at is not None
        self.assertEqual(restored.created_at.tzinfo, timezone.utc)
        self.assertEqual(restored.last_run_at, NOW + timedelta(hours=2))


class TestRecord(unittest.TestCase):
    def test_a_page_nobody_has_run_on_has_no_run_id(self) -> None:
        self.assertEqual(PageRecord(page=GAMBIT, created_at=NOW).last_run_id, "")

    def test_opening_numbers_the_next_run(self) -> None:
        opened = PageRecord(page=GAMBIT, created_at=NOW, runs=2).opening(NOW)
        self.assertEqual(opened.runs, 3)
        self.assertEqual(opened.last_run_id, run_id_for(GAMBIT, 3))

    def test_opening_leaves_the_creation_moment_alone(self) -> None:
        later = NOW + timedelta(days=5)
        opened = PageRecord(page=GAMBIT, created_at=NOW, runs=1).opening(later)
        self.assertEqual(opened.created_at, NOW)
        self.assertEqual(opened.last_run_at, later)

    def test_the_slug_is_the_document_key(self) -> None:
        self.assertEqual(PageRecord(page=GAMBIT, created_at=NOW).slug, "Gambit_Marvel_Comics")


class TestInMemoryStore(unittest.TestCase):
    def test_the_first_run_creates_the_record(self) -> None:
        store = InMemoryPageStore()
        self.assertIsNone(store.get(GAMBIT))
        record = store.open_run(GAMBIT, now=NOW)
        self.assertEqual(record.runs, 1)
        self.assertEqual(store.get(GAMBIT), record)

    def test_runs_on_a_page_are_numbered_in_order(self) -> None:
        store = InMemoryPageStore()
        ids = [store.open_run(GAMBIT, now=NOW).last_run_id for _ in range(3)]
        self.assertEqual(ids, [run_id_for(GAMBIT, n) for n in (1, 2, 3)])

    def test_each_page_counts_its_own_runs(self) -> None:
        # The whole point of the record: a run on Rogue is not run #4 because Gambit had three.
        store = InMemoryPageStore()
        for _ in range(3):
            store.open_run(GAMBIT, now=NOW)
        self.assertEqual(store.open_run("Rogue", now=NOW).last_run_id, run_id_for("Rogue", 1))

    def test_the_creation_moment_is_the_first_run_not_the_latest(self) -> None:
        store = InMemoryPageStore()
        store.open_run(GAMBIT, now=NOW)
        record = store.open_run(GAMBIT, now=NOW + timedelta(days=1))
        self.assertEqual(record.created_at, NOW)

    def test_the_store_satisfies_the_protocol(self) -> None:
        self.assertIsInstance(InMemoryPageStore(), PageStore)


@requires_mongo
class TestMongoPageStore(MongoTestCase):
    """The real store. These are the assertions that only mean something against persistence."""

    def store(self) -> MongoPageStore:
        return MongoPageStore(self.db)

    def test_the_counter_survives_a_new_process(self) -> None:
        # Without this every restart re-issues run #1, and two different runs share an id —
        # which is one run's claims silently landing in another's scope.
        self.store().open_run(GAMBIT, now=NOW)
        self.assertEqual(self.store().open_run(GAMBIT, now=NOW).runs, 2)

    def test_a_page_never_run_on_has_no_record(self) -> None:
        self.assertIsNone(self.store().get(GAMBIT))
        self.assertEqual(self.store().all(), ())

    def test_the_first_run_creates_the_document(self) -> None:
        record = self.store().open_run(GAMBIT, now=NOW)
        self.assertEqual(self.store().get(GAMBIT), record)
        self.assertEqual(record.last_run_id, run_id_for(GAMBIT, 1))

    def test_the_creation_moment_is_written_once(self) -> None:
        # `$setOnInsert`, pinned: a later run must not restamp the page as newly discovered.
        self.store().open_run(GAMBIT, now=NOW)
        later = self.store().open_run(GAMBIT, now=NOW + timedelta(days=30))
        self.assertEqual(later.created_at, NOW)
        self.assertEqual(later.last_run_at, NOW + timedelta(days=30))

    def test_each_page_counts_its_own_runs(self) -> None:
        store = self.store()
        for _ in range(2):
            store.open_run(GAMBIT, now=NOW)
        self.assertEqual(store.open_run("Rogue", now=NOW).runs, 1)
        self.assertEqual({r.slug for r in store.all()}, {"Gambit_Marvel_Comics", "Rogue"})

    def test_simultaneous_runs_take_different_numbers(self) -> None:
        # The one that a read-then-write counter fails. A reader double-clicking the button, or
        # two containers serving the same page, must not both be run #1 — the id is what seals
        # a run's claims off from every other run's.
        store = self.store()
        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(lambda _: store.open_run(GAMBIT, now=NOW), range(8)))
        self.assertEqual(sorted(r.runs for r in records), list(range(1, 9)))
        self.assertEqual(len({r.last_run_id for r in records}), 8)

    def test_the_store_satisfies_the_protocol(self) -> None:
        self.assertIsInstance(self.store(), PageStore)


if __name__ == "__main__":
    unittest.main()
