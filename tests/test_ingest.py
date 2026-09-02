"""The baseline pass: what the page said, recorded so the world can be measured against it.

Two properties carry everything else. **Sections are replaced as a set**, because their indices
are only meaningful relative to each other — merge a fresh read into old rows and one section's
text ends up filed under another's index, wrongly and silently. And **a re-ingest of an
unchanged page is visibly a no-op**, because the run has to be able to say "nothing moved here"
rather than assume it.

Stdlib only, and no wiki: `SnapshotPageSource` reads the committed corpus, so this exercises
the real path against real pages with nothing running.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.agent.ingest import ingest_all, ingest_page
from backend.core.ledger.baseline import (
    InMemoryBaselineStore,
    SectionBaseline,
    from_document,
    to_document,
)
from backend.core.ledger.store import LedgerError
from backend.core.profile import local_wiki
from backend.core.wiki import PageRevision, SnapshotPageSource, WikiError
from backend.mongo import MongoBaselineStore
from tests.mongo_support import MongoTestCase, requires_mongo

REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
PROFILE = local_wiki("http://wiki.invalid/api.php")


def seed_source() -> SnapshotPageSource:
    return SnapshotPageSource(REPO_ROOT, state="seed")


def section(**overrides: object) -> SectionBaseline:
    base: dict[str, object] = dict(
        page="Gambit", section_index=1, section_heading="Biography",
        text="==Biography==\nHe is a mutant.", revid=2019481, fetched_at=NOW,
    )
    return SectionBaseline(**{**base, **overrides})  # type: ignore[arg-type]


class Missing:
    """A source where every page is absent — the answer a run must survive."""

    def revision(self, title: str, *, before: datetime | None = None) -> PageRevision:
        raise WikiError(f"no page {title!r}", code="missingtitle")


class Broken:
    """A source whose transport fails. Distinct from missing, and must not be swallowed."""

    def revision(self, title: str, *, before: datetime | None = None) -> PageRevision:
        raise TimeoutError("connection timed out")


class TestIngest(unittest.TestCase):
    def test_a_page_lands_as_its_sections(self) -> None:
        store = InMemoryBaselineStore()
        result = ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW)

        self.assertTrue(result.ok)
        self.assertEqual(result.sections, len(store.for_page("Gambit")))
        self.assertGreater(result.sections, 1)
        self.assertEqual(result.added, result.sections)

    def test_the_lead_is_section_zero_with_no_heading(self) -> None:
        store = InMemoryBaselineStore()
        ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW)
        lead = store.for_page("Gambit")[0]

        self.assertEqual(lead.section_index, 0)
        self.assertEqual(lead.section_heading, "")

    def test_sections_come_back_in_document_order(self) -> None:
        store = InMemoryBaselineStore()
        ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW)

        indices = [s.section_index for s in store.for_page("Gambit")]
        self.assertEqual(indices, sorted(indices))

    def test_the_text_is_verbatim(self) -> None:
        # It is what `action=edit&section=N` round-trips. Normalising it here would make every
        # later diff a diff against a copy rather than against the page.
        store = InMemoryBaselineStore()
        ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW)
        revision = seed_source().revision("Gambit")

        self.assertEqual("".join(s.text for s in store.for_page("Gambit")), revision.content)

    def test_re_ingesting_an_untouched_page_changes_nothing(self) -> None:
        store = InMemoryBaselineStore()
        ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW)
        again = ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW + timedelta(days=1))

        self.assertTrue(again.unchanged)
        self.assertEqual((again.added, again.changed, again.removed), (0, 0, 0))

    def test_real_drift_is_detected_against_the_current_corpus(self) -> None:
        # Two years of real edits between the two committed states — not a synthetic change.
        store = InMemoryBaselineStore()
        ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW)
        drifted = ingest_page(
            SnapshotPageSource(REPO_ROOT, state="current"), PROFILE, store, "Gambit", now=NOW
        )

        self.assertFalse(drifted.unchanged)
        self.assertGreater(drifted.changed, 0)

    def test_a_missing_page_is_a_result_not_an_exception(self) -> None:
        store = InMemoryBaselineStore()
        result = ingest_page(Missing(), PROFILE, store, "Nonexistent", now=NOW)

        self.assertFalse(result.ok)
        self.assertIn("Nonexistent", str(result.error))
        self.assertEqual(len(store), 0)

    def test_a_transport_failure_still_propagates(self) -> None:
        # Narrow catching, same rule as the read tool: a timeout is worth retrying, a missing
        # page is not, and swallowing the first turns an outage into an empty baseline.
        with self.assertRaises(TimeoutError):
            ingest_page(Broken(), PROFILE, InMemoryBaselineStore(), "Gambit", now=NOW)

    def test_ingest_all_covers_every_page_the_profile_names(self) -> None:
        store = InMemoryBaselineStore()
        results = ingest_all(seed_source(), PROFILE, store, now=NOW)

        self.assertEqual(len(results), len(PROFILE.pages))
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(store.pages(), tuple(sorted(PROFILE.pages)))

    def test_one_pass_carries_one_timestamp(self) -> None:
        store = InMemoryBaselineStore()
        ingest_all(seed_source(), PROFILE, store, now=NOW)

        stamps = {s.fetched_at for page in store.pages() for s in store.for_page(page)}
        self.assertEqual(stamps, {NOW})


class TestBaselineStore(unittest.TestCase):
    def test_replacing_a_page_drops_sections_that_are_gone(self) -> None:
        store = InMemoryBaselineStore((section(section_index=0), section(section_index=1)))
        store.replace_page("Gambit", (section(section_index=0),))

        self.assertEqual(len(store.for_page("Gambit")), 1)

    def test_replacing_one_page_leaves_the_others_alone(self) -> None:
        store = InMemoryBaselineStore((section(), section(page="Deadpool")))
        store.replace_page("Gambit", ())

        self.assertEqual(store.pages(), ("Deadpool",))

    def test_a_section_from_another_page_is_refused(self) -> None:
        # The whole set is one page's, or the atomicity claim is false.
        with self.assertRaises(LedgerError):
            InMemoryBaselineStore().replace_page("Gambit", (section(page="Deadpool"),))

    def test_the_hash_is_the_text(self) -> None:
        self.assertEqual(section().content_hash, section().content_hash)
        self.assertNotEqual(section().content_hash, section(text="different").content_hash)

    def test_a_document_round_trips(self) -> None:
        self.assertEqual(from_document(to_document(section())), section())

    def test_a_document_refuses_an_unknown_version(self) -> None:
        doc = {**to_document(section()), "v": 99}
        with self.assertRaises(ValueError):
            from_document(doc)


@requires_mongo
class TestMongoBaselineStore(MongoTestCase):
    def store(self) -> MongoBaselineStore:
        return MongoBaselineStore(self.db)

    def test_the_baseline_survives_a_new_process(self) -> None:
        ingest_page(seed_source(), PROFILE, self.store(), "Gambit", now=NOW)
        reopened = self.store()
        self.assertGreater(len(reopened.for_page("Gambit")), 1)
        self.assertEqual(reopened.pages(), ("Gambit",))

    def test_an_empty_collection_opens_empty(self) -> None:
        self.assertEqual(self.store().pages(), ())

    def test_the_store_and_memory_agree(self) -> None:
        memory, stored = InMemoryBaselineStore(), self.store()
        for store in (memory, stored):
            ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW)
        self.assertEqual(memory.for_page("Gambit"), self.store().for_page("Gambit"))

    def test_a_page_is_replaced_as_a_set_never_merged(self) -> None:
        """Indices are only meaningful relative to each other, so a merge would file one
        section's text under another's index."""
        store = self.store()
        ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW)
        first = len(store.for_page("Gambit"))
        ingest_page(seed_source(), PROFILE, store, "Gambit", now=NOW)
        self.assertEqual(len(store.for_page("Gambit")), first)

if __name__ == "__main__":
    unittest.main()
