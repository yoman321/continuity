"""Ledger store tests — the document shape, and the two local stores that hold it.

The point of building local first is that the *behaviour* ports, not just the data. So most
of what is pinned here is agreement: the file store and the in-memory store return the same
order, the codec round-trips every field, and a stored document contains nothing Firestore
would need translated. The one test that matters most is the null wake time — it is the
failure that would pass every other local test and only appear deployed.

Stdlib only; the core has no dependencies and its tests shouldn't either.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.core.ledger import (
    Claim,
    ClaimKind,
    ClaimStatus,
    ClaimStore,
    Contradiction,
    InMemoryClaimStore,
    JsonFileClaimStore,
    LedgerError,
    Source,
    Wave,
    from_document,
    is_firestore_safe,
    to_document,
)
from backend.core.profile import MCU_FANDOM

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
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


def scheduled(**overrides: Any) -> Claim:
    """A claim the store will accept — i.e. one that has been through `seeded`."""
    return make_claim(**overrides).seeded(NOW)


def loaded_claim() -> Claim:
    """Every optional field populated, so a round trip has something to lose."""
    claim = scheduled(
        claim_id="c-full",
        entity_ref=MCU_FANDOM.entity_ref("Human Torch/Void-Analyzing Fantastic Four"),
        kind=ClaimKind.LINK,
        wave=Wave.SETTLED,
        ripple_targets=("c-other", "c-third"),
    )
    sources = (
        Source.create(
            "https://deadline.com/story",
            "excerpt one",
            NOW,
            as_of=NOW - timedelta(days=3),
            domain_tiers=TIERS,
        ),
        Source.create(
            "https://variety.com/story", "excerpt two", NOW, domain_tiers=TIERS
        ),
    )
    return claim.researched("who plays Gambit", sources).unresolved(
        NOW, Contradiction("dates disagree", "https://deadline.com/story",
                          "https://variety.com/story")
    )


class TestDocumentRoundTrip(unittest.TestCase):
    def test_every_field_survives(self) -> None:
        original = loaded_claim()
        self.assertEqual(from_document(to_document(original)), original)

    def test_bare_claim_survives(self) -> None:
        original = scheduled()
        self.assertEqual(from_document(to_document(original)), original)

    def test_document_holds_only_firestore_types(self) -> None:
        # The portability claim, asserted rather than trusted: if this fails, the Firestore
        # adapter needs a converter and the two stores stop agreeing.
        self.assertTrue(is_firestore_safe(to_document(loaded_claim())))

    def test_timestamps_are_datetimes_not_strings(self) -> None:
        # Firestore stores a native timestamp; only the JSON file needs the string form.
        doc = to_document(loaded_claim())
        self.assertIsInstance(doc["next_check_at"], datetime)
        self.assertIsInstance(doc["sources"][0]["retrieved_at"], datetime)

    def test_interval_stores_as_whole_seconds(self) -> None:
        claim = scheduled(wave=Wave.SETTLED)
        doc = to_document(claim)
        self.assertEqual(doc["check_interval_seconds"], 45 * 24 * 3600)
        self.assertEqual(from_document(doc).check_interval, timedelta(days=45))

    def test_iso_strings_read_back_as_the_same_instant(self) -> None:
        # What the file store hands back. A Firestore read gives datetimes; both must land
        # on the same value or a local run and a deployed run disagree.
        doc = to_document(scheduled())
        doc["next_check_at"] = doc["next_check_at"].isoformat()
        self.assertEqual(from_document(doc).next_check_at, scheduled().next_check_at)

    def test_offset_timestamps_normalise_to_utc(self) -> None:
        doc = to_document(scheduled())
        doc["next_check_at"] = "2026-09-01T08:00:00-04:00"
        self.assertEqual(
            from_document(doc).next_check_at,
            datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        )

    def test_zulu_suffix_parses_on_the_declared_python_floor(self) -> None:
        # `fromisoformat` only learned `Z` in 3.11 and pyproject allows 3.10.
        doc = to_document(scheduled())
        doc["next_check_at"] = "2026-09-01T12:00:00Z"
        self.assertEqual(
            from_document(doc).next_check_at,
            datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        )

    def test_unknown_version_is_refused_not_guessed(self) -> None:
        doc = to_document(scheduled())
        doc["v"] = 99
        with self.assertRaises(ValueError):
            from_document(doc)

    def test_derived_fields_are_not_stored(self) -> None:
        doc = to_document(loaded_claim())
        for derived in ("auto_appliable", "is_contradicted", "budget_spent"):
            self.assertNotIn(derived, doc)


class TestStoreContract(unittest.TestCase):
    """Run against the in-memory store; `TestJsonFileStore` re-runs the ones that can drift."""

    def test_unscheduled_claim_is_refused(self) -> None:
        # The Firestore null trap: a claim with no wake time is due in memory and invisible
        # to an inequality filter. Caught on write, where it can still be fixed.
        with self.assertRaises(LedgerError):
            InMemoryClaimStore().put(make_claim())

    def test_the_error_names_the_fix(self) -> None:
        with self.assertRaises(LedgerError) as caught:
            InMemoryClaimStore().put(make_claim())
        self.assertIn("seeded", str(caught.exception))

    def test_batch_is_all_or_nothing(self) -> None:
        store = InMemoryClaimStore()
        with self.assertRaises(LedgerError):
            store.put_all([scheduled(claim_id="good"), make_claim(claim_id="bad")])
        self.assertEqual(len(store), 0)

    def test_put_replaces_by_claim_id(self) -> None:
        store = InMemoryClaimStore([scheduled()])
        store.put(scheduled().unchanged(NOW))
        self.assertEqual(len(store), 1)
        stored = store.get("c1")
        assert stored is not None
        self.assertEqual(stored.last_verified, NOW)

    def test_get_missing_is_none_not_an_error(self) -> None:
        self.assertIsNone(InMemoryClaimStore().get("nope"))

    def test_due_excludes_claims_not_yet_ready(self) -> None:
        store = InMemoryClaimStore([scheduled()])
        # Seeded announcement-driven: 24h out, so due tomorrow and not now.
        self.assertEqual(store.due(NOW), ())
        self.assertEqual(len(store.due(NOW + timedelta(hours=25))), 1)

    def test_due_orders_soonest_first(self) -> None:
        store = InMemoryClaimStore([
            scheduled(claim_id="slow", wave=Wave.SETTLED),
            scheduled(claim_id="fast", wave=Wave.ANNOUNCEMENT_DRIVEN),
            scheduled(claim_id="mid", wave=Wave.RELEASE_DRIVEN),
        ])
        ready = store.due(NOW + timedelta(days=200))
        self.assertEqual([c.claim_id for c in ready], ["fast", "mid", "slow"])

    def test_due_breaks_ties_by_claim_id(self) -> None:
        # Firestore's implicit tiebreak on `order_by` is the document id; match it, or a
        # limited query returns a different page locally than deployed.
        store = InMemoryClaimStore([
            scheduled(claim_id="c-b"), scheduled(claim_id="c-a"), scheduled(claim_id="c-c"),
        ])
        ready = store.due(NOW + timedelta(days=2))
        self.assertEqual([c.claim_id for c in ready], ["c-a", "c-b", "c-c"])

    def test_due_limit_takes_the_soonest(self) -> None:
        store = InMemoryClaimStore([
            scheduled(claim_id="slow", wave=Wave.SETTLED),
            scheduled(claim_id="fast", wave=Wave.ANNOUNCEMENT_DRIVEN),
        ])
        ready = store.due(NOW + timedelta(days=200), limit=1)
        self.assertEqual([c.claim_id for c in ready], ["fast"])

    def test_all_is_stable_and_ignores_the_schedule(self) -> None:
        store = InMemoryClaimStore([scheduled(claim_id="c-b"), scheduled(claim_id="c-a")])
        self.assertEqual([c.claim_id for c in store.all()], ["c-a", "c-b"])

    def test_both_stores_satisfy_the_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsInstance(InMemoryClaimStore(), ClaimStore)
            self.assertIsInstance(JsonFileClaimStore(Path(tmp) / "l.json"), ClaimStore)


class TestIdentityAndLookup(unittest.TestCase):
    """Ids are the store's to hand out, and a claim is found by where it sits."""

    def test_ids_are_a_counter(self) -> None:
        store = InMemoryClaimStore()
        self.assertEqual(store.next_claim_id(), "claim-0001")

        store.put(scheduled(claim_id=store.next_claim_id()))
        self.assertEqual(store.next_claim_id(), "claim-0002")

    def test_the_counter_resumes_from_what_is_stored(self) -> None:
        store = InMemoryClaimStore((scheduled(claim_id="claim-0007"),))

        self.assertEqual(store.next_claim_id(), "claim-0008")

    def test_a_number_is_never_reused_after_a_gap(self) -> None:
        store = InMemoryClaimStore((
            scheduled(claim_id="claim-0001"),
            scheduled(claim_id="claim-0009", wikitext_anchor="other"),
        ))

        # Max plus one, not count plus one: a removed claim must not free its number, or two
        # different claims end up sharing an id and the second overwrites the first.
        self.assertEqual(store.next_claim_id(), "claim-0010")

    def test_hand_written_ids_do_not_disturb_the_sequence(self) -> None:
        # `build_demo_state.py` uses mnemonics like `GAM-APP-01`; they simply sit outside it.
        store = InMemoryClaimStore((scheduled(claim_id="GAM-APP-01"),))

        self.assertEqual(store.next_claim_id(), "claim-0001")

    def test_for_page_returns_only_that_page(self) -> None:
        store = InMemoryClaimStore((
            scheduled(claim_id="c1", page="Gambit"),
            scheduled(claim_id="c2", page="Phase Six"),
            scheduled(claim_id="c3", page="Gambit", wikitext_anchor="another"),
        ))

        self.assertEqual([c.claim_id for c in store.for_page("Gambit")], ["c1", "c3"])

    def test_for_page_is_empty_for_an_unaudited_page(self) -> None:
        self.assertEqual(InMemoryClaimStore().for_page("Blade"), ())


class TestJsonFileStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "nested" / "ledger.json"

    def test_claims_survive_a_new_process(self) -> None:
        # The property the whole ledger exists for: the next run is not the same run.
        JsonFileClaimStore(self.path).put(loaded_claim())
        reopened = JsonFileClaimStore(self.path)
        self.assertEqual(reopened.get("c-full"), loaded_claim())

    def test_missing_file_opens_empty_rather_than_failing(self) -> None:
        self.assertEqual(len(JsonFileClaimStore(self.path)), 0)
        self.assertFalse(self.path.exists())

    def test_interval_carries_across_runs_so_the_ladder_climbs(self) -> None:
        # A purging store would restart every claim at its wave seed and the ladder would
        # never leave 45d. This is that regression, pinned.
        store = JsonFileClaimStore(self.path)
        store.put(scheduled(wave=Wave.SETTLED))

        first = JsonFileClaimStore(self.path)
        due = first.due(NOW + timedelta(days=46))
        first.put(due[0].unchanged(NOW + timedelta(days=46)))

        second = JsonFileClaimStore(self.path)
        stored = second.get("c1")
        assert stored is not None
        self.assertEqual(stored.check_interval, timedelta(days=90))

    def test_the_id_counter_survives_a_new_process(self) -> None:
        # Without this the second run reissues the first run's numbers and each new claim
        # silently overwrites an existing one — a data-loss bug with no error anywhere.
        first = JsonFileClaimStore(self.path)
        first.put(scheduled(claim_id=first.next_claim_id()))

        second = JsonFileClaimStore(self.path)
        self.assertEqual(second.next_claim_id(), "claim-0002")

    def test_for_page_survives_a_new_process(self) -> None:
        JsonFileClaimStore(self.path).put(scheduled(page="Gambit"))

        self.assertEqual(len(JsonFileClaimStore(self.path).for_page("Gambit")), 1)

    def test_file_is_readable_json_keyed_by_claim_id(self) -> None:
        JsonFileClaimStore(self.path).put_all([scheduled(claim_id="c-b"),
                                               scheduled(claim_id="c-a")])
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(list(payload["claims"]), ["c-a", "c-b"])
        self.assertEqual(payload["claims"]["c-a"]["claim_id"], "c-a")

    def test_write_leaves_no_temp_file_behind(self) -> None:
        JsonFileClaimStore(self.path).put(scheduled())
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["ledger.json"])

    def test_a_refused_write_does_not_touch_the_file(self) -> None:
        store = JsonFileClaimStore(self.path)
        store.put(scheduled())
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(LedgerError):
            store.put_all([scheduled(claim_id="ok"), make_claim(claim_id="bad")])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_status_and_enums_survive_the_file(self) -> None:
        store = JsonFileClaimStore(self.path)
        store.put(scheduled().changed(NOW))
        stored = JsonFileClaimStore(self.path).get("c1")
        assert stored is not None
        self.assertIs(stored.status, ClaimStatus.UNRESOLVED)
        self.assertIs(stored.kind, ClaimKind.LIST_MEMBER)
        self.assertIs(stored.wave, Wave.ANNOUNCEMENT_DRIVEN)

    def test_file_and_memory_return_the_same_order(self) -> None:
        claims = [scheduled(claim_id="c-b", wave=Wave.SETTLED),
                  scheduled(claim_id="c-a", wave=Wave.SETTLED),
                  scheduled(claim_id="c-c", wave=Wave.RELEASE_DRIVEN)]
        on_disk = JsonFileClaimStore(self.path)
        on_disk.put_all(claims)
        later = NOW + timedelta(days=200)
        self.assertEqual(
            [c.claim_id for c in on_disk.due(later)],
            [c.claim_id for c in InMemoryClaimStore(claims).due(later)],
        )


if __name__ == "__main__":
    unittest.main()
