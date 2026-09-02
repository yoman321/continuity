"""FastAPI shell tests — the guard on the tick route, and the cold-start rule.

Two of these cover invariants rather than behaviour, and are the reason this file exists:

* `/internal/tick` is public (judging requires `--allow-unauthenticated`), so the shared-secret
  compare is the whole of its security. Every way of getting past it without the token is a
  case below, including the unset-token path, which must fail closed rather than open.
* No vendor SDK may be imported at module level, or a cold container spends 5-15s on ADK before
  it can serve `index.html` (`AGENTS.md` §7). That is checked in a subprocess against
  `sys.modules`, because an intention stated in a comment is not a measurement.
* `POST /api/drafts/{id}/publish` writes to a wiki and is public for the same reason. What
  stops that being a write primitive is that the request decides *nothing*: it carries no body
  at all, and every argument the write is made from — page, section, anchor, text, and whether
  the change was even accepted — comes from the stored draft. The `TestPublish` cases below
  assert that against a recording stub, one argument at a time.

Unlike the ledger tests these need the venv — `app.py` imports FastAPI. The module skips
rather than fails on a bare interpreter so the dependency-free suite still runs there.
"""

import logging
import os
import subprocess
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover - exercised only on a bare interpreter
    raise unittest.SkipTest(f"app tests need the venv: {exc}") from exc

sys.path.insert(0, str(REPO_ROOT))

from backend import app as app_module  # noqa: E402  - after the path insert, deliberately
from backend.agent.tools import WikiWrite  # noqa: E402
from backend.core.ledger.drafts import (  # noqa: E402
    Change,
    Decision,
    ReviewDraft,
)
from backend.mongo import MongoDraftStore  # noqa: E402
from tests.mongo_support import MONGO_URI, requires_mongo  # noqa: E402

TOKEN = "correct-horse-battery-staple"

#: Shaped like `.env`, valued like nothing. No test here opens a socket.
WRITTEN = {
    "status": "written", "wiki": "Continuity Wiki", "resolved_title": "Deadpool & Wolverine",
    "base_revid": 100, "base_timestamp": "2026-08-15T12:00:00Z", "section_index": 2,
    "heading": "Plot", "new_revid": 101, "nochange": False,
}


DRAFT_ID = "draft-test-0001"


def change(edit_id: str, **kwargs: Any) -> Change:
    """One stored change. Defaults are the Gambit card, whose anchor is in the page lead."""
    fields: dict[str, Any] = {
        "edit_id": edit_id,
        "claim_id": "GAM-APP-01",
        "page": "Gambit",
        "page_slug": "Gambit",
        "section_index": 0,
        "section_heading": "",
        "before": "|movie = ''[[Deadpool & Wolverine]]''",
        "after": "|movie = ''[[Deadpool & Wolverine]]''<br>''[[Avengers: Doomsday]]''",
        "summary": "Gambit — appears in Doomsday",
        "rationale": "The infobox lists one film.",
        "confidence": 0.98,
    }
    fields.update(kwargs)
    return Change(**fields)


def stored(*changes: Change) -> ReviewDraft:
    return ReviewDraft(
        draft_id=DRAFT_ID,
        wiki="Continuity Wiki",
        created_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        changes=changes or (change("edit-a"),),
    )



def setUpModule() -> None:
    # Half of these tests deliberately trip the rejection paths; their warnings are expected
    # output, not signal, and they bury the gate's result.
    logging.disable(logging.CRITICAL)


def tearDownModule() -> None:
    logging.disable(logging.NOTSET)


def client() -> TestClient:
    # Errors are payloads to assert on here, not exceptions to propagate.
    return TestClient(app_module.app, raise_server_exceptions=False)


class TestTickAuth(unittest.TestCase):
    """The one route where a wrong answer costs money."""

    def test_no_token_configured_fails_closed(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "TICK_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True):
            r = client().post("/internal/tick", headers={"X-Tick-Token": TOKEN})
        self.assertEqual(r.status_code, 503)

    def test_missing_header_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"TICK_TOKEN": TOKEN}):
            r = client().post("/internal/tick")
        self.assertEqual(r.status_code, 401)

    def test_wrong_token_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"TICK_TOKEN": TOKEN}):
            r = client().post("/internal/tick", headers={"X-Tick-Token": "guess"})
        self.assertEqual(r.status_code, 401)

    def test_prefix_of_the_token_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"TICK_TOKEN": TOKEN}):
            r = client().post("/internal/tick", headers={"X-Tick-Token": TOKEN[:-1]})
        self.assertEqual(r.status_code, 401)

    def test_non_ascii_token_is_rejected_not_crashed(self) -> None:
        # Starlette decodes headers as latin-1, so a handler that fed the raw str to
        # hmac.compare_digest would hit its ASCII-only TypeError and answer 500 — telling an
        # attacker "malformed" apart from "wrong". Sent as bytes because that is what a real
        # request carries; httpx will not encode a non-ASCII str for us.
        with mock.patch.dict(os.environ, {"TICK_TOKEN": TOKEN}):
            r = client().post("/internal/tick", headers={"X-Tick-Token": "tökén".encode("latin-1")})
        self.assertEqual(r.status_code, 401)

    def test_header_name_is_case_insensitive(self) -> None:
        with mock.patch.dict(os.environ, {"TICK_TOKEN": TOKEN}):
            r = client().post("/internal/tick", headers={"x-tick-token": TOKEN})
        self.assertEqual(r.status_code, 501)  # authenticated; graph not wired yet

    def test_correct_token_gets_past_the_guard(self) -> None:
        with mock.patch.dict(os.environ, {"TICK_TOKEN": TOKEN}):
            r = client().post("/internal/tick", headers={"X-Tick-Token": TOKEN})
        self.assertEqual(r.status_code, 501)


class TestApiRoutes(unittest.TestCase):
    def test_an_empty_or_unreachable_ledger_is_a_503_never_a_fixture(self) -> None:
        """The frontend decides live-vs-fixture from this one response, so anything but a
        failure here would put a *live* pill above data no run produced. An empty database is
        the same answer as an unreachable one on purpose: neither is state worth labelling."""
        with mock.patch.dict(os.environ, {"MONGO_DB": f"continuity_empty_{uuid.uuid4().hex[:8]}"}):
            r = client().get("/api/state")
        self.assertEqual(r.status_code, 503)
        msg = "the FE fallback keys off !r.ok; a 2xx here would claim 'live'"
        self.assertFalse(r.is_success, msg)


@requires_mongo
class DraftCase(unittest.TestCase):
    """Every draft test runs against a real store, not a mock of one.

    The store is the thing under test as much as the routes are: a verdict that does not
    survive the write is the failure the whole change exists to prevent. Each test gets its
    own database so a run never sees another run's rows, and never the demo's.
    """

    def setUp(self) -> None:
        import uuid

        import pymongo

        name = f"continuity_test_{uuid.uuid4().hex[:12]}"
        patch = mock.patch.dict(os.environ, {"MONGO_DB": name, "DRAFT_STORE": "mongo"})
        patch.start()
        self.addCleanup(patch.stop)
        client: object = pymongo.MongoClient(MONGO_URI)
        self.addCleanup(client.drop_database, name)  # type: ignore[attr-defined]

    def store(self) -> "MongoDraftStore":
        from backend.mongo import MongoDraftStore

        return MongoDraftStore()

    def seed(self, draft: ReviewDraft | None = None) -> ReviewDraft:
        draft = draft if draft is not None else stored()
        self.store().put(draft)
        return draft

    def reread(self) -> ReviewDraft:
        """What the *next* process would see. Asserting on this rather than on the response is
        what makes these tests about persistence and not about a return value."""
        held = self.store().get(DRAFT_ID)
        assert held is not None
        return held


class TestReadingADraft(DraftCase):
    def test_a_draft_is_fetched_back_by_id(self) -> None:
        self.seed()
        r = client().get(f"/api/drafts/{DRAFT_ID}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["draft_id"], DRAFT_ID)
        self.assertEqual(len(r.json()["changes"]), 1)

    def test_an_unknown_draft_is_a_404(self) -> None:
        self.assertEqual(client().get("/api/drafts/draft-nope").status_code, 404)

    def test_the_card_carries_a_diff_the_browser_did_not_compute(self) -> None:
        """`AGENTS.md` §4: the core owns every derivation. The diff is *not* stored, so serving
        it proves it is computed from the text as it stands now — including a hand-edit."""
        self.seed()
        rows = client().get(f"/api/drafts/{DRAFT_ID}").json()["changes"][0]["diff"]
        self.assertEqual([row["kind"] for row in rows], ["removed", "added"])

    def test_the_list_carries_counts_but_not_the_changes(self) -> None:
        # A list that carried them would make opening the gate pay for every run ever made.
        self.seed(stored(change("edit-a"), change("edit-b")))
        listed = client().get("/api/drafts").json()["drafts"]
        self.assertEqual(listed[0]["counts"], {"changes": 2, "accepted": 0, "undecided": 2})
        self.assertNotIn("changes", listed[0])


class TestDecidingOneChange(DraftCase):
    def test_a_verdict_survives_the_request_that_made_it(self) -> None:
        self.seed()
        r = client().post(
            f"/api/drafts/{DRAFT_ID}/changes/edit-a", json={"decision": "accepted"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertIs(self.reread().changes[0].decision, Decision.ACCEPTED)

    def test_a_hand_edit_survives_too_and_is_what_would_publish(self) -> None:
        self.seed()
        client().post(f"/api/drafts/{DRAFT_ID}/changes/edit-a", json={"text": "mine"})
        self.assertEqual(self.reread().changes[0].after, "mine")

    def test_rejecting_writes_nothing_to_the_wiki(self) -> None:
        """A discard, not a verdict on the claim (`AGENTS.md` §2). It changes the draft and
        nothing else — and no writer is constructed, which is what "writes nothing" means now
        that the write itself happens in the browser."""
        self.seed()
        with mock.patch.object(WikiWrite, "live") as live:
            client().post(
                f"/api/drafts/{DRAFT_ID}/changes/edit-a", json={"decision": "rejected"}
            )
        live.assert_not_called()
        self.assertIs(self.reread().changes[0].decision, Decision.REJECTED)

    def test_an_empty_body_is_refused_rather_than_answered_with_a_no_op(self) -> None:
        self.seed()
        r = client().post(f"/api/drafts/{DRAFT_ID}/changes/edit-a", json={})
        self.assertEqual(r.status_code, 422)

    def test_the_body_cannot_name_a_target(self) -> None:
        """`AGENTS.md` §2. Ignoring an unknown field would make this a 200 that changed nothing
        the caller asked for, and the next reader would think the field had worked."""
        self.seed()
        for body in ({"page": "Main Page"}, {"section_index": 5}, {"decision": "approve"}):
            with self.subTest(body=body):
                r = client().post(f"/api/drafts/{DRAFT_ID}/changes/edit-a", json=body)
                self.assertEqual(r.status_code, 422)

    def test_an_oversized_hand_edit_is_refused(self) -> None:
        self.seed()
        r = client().post(
            f"/api/drafts/{DRAFT_ID}/changes/edit-a",
            json={"text": "x" * (app_module.MAX_DRAFT_CHARS + 1)},
        )
        self.assertEqual(r.status_code, 413)

    def test_an_unknown_change_is_a_conflict_not_a_silent_no_op(self) -> None:
        self.seed()
        r = client().post(
            f"/api/drafts/{DRAFT_ID}/changes/edit-nope", json={"decision": "accepted"}
        )
        self.assertEqual(r.status_code, 409)


class TestPublish(DraftCase):
    """The route records what the browser wrote. Every case is about what the request is
    *not* allowed to decide.

    The wiki moved into the browser on Sept 1, 2026 (`AGENTS.md` §2), so the server performs
    no `action=edit` at all any more — which is itself asserted below, because a route that
    quietly kept a write path would make the gate optional.
    """

    def accepted(self, *edit_ids: str) -> ReviewDraft:
        draft = stored(*[change(edit_id) for edit_id in edit_ids])
        for edit_id in edit_ids:
            draft = draft.decide(edit_id, Decision.ACCEPTED)
        return self.seed(draft)

    def publish(self, *results: dict[str, Any]) -> Any:
        return client().post(
            f"/api/drafts/{DRAFT_ID}/publish", json={"results": list(results)}
        )

    def test_a_reported_write_is_recorded_and_the_draft_is_stamped(self) -> None:
        self.accepted("edit-a")
        r = self.publish({"edit_id": "edit-a", "status": "written", "revid": 4242})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["published"])

        held = self.reread()
        self.assertEqual(held.changes[0].written_revid, 4242)
        self.assertIsNotNone(held.published_at)

    def test_the_server_never_writes_to_a_wiki(self) -> None:
        """The gate does the writing. If this route ever constructs a writer again, the
        browser and the server would both be publishing and neither would know."""
        self.accepted("edit-a")
        with mock.patch.object(WikiWrite, "live") as live:
            self.publish({"edit_id": "edit-a", "status": "written", "revid": 1})
        live.assert_not_called()

    def test_a_body_that_names_a_target_is_refused(self) -> None:
        """The security property, now that the body is not empty: outcomes may travel, write
        targets may not. `extra="forbid"` is what makes this a 422 and not a silent ignore."""
        self.accepted("edit-a")
        r = client().post(f"/api/drafts/{DRAFT_ID}/publish", json={"results": [
            {"edit_id": "edit-a", "status": "written", "revid": 1,
             "page": "Main Page", "after": "anything"}
        ]})
        self.assertEqual(r.status_code, 422)
        self.assertIsNone(self.reread().published_at)

    def test_reporting_a_change_the_draft_is_not_awaiting_is_refused(self) -> None:
        """A rejected, unknown or already-written id must not be honoured — the gate and the
        store disagreeing about what happened is the bug worth failing on."""
        draft = stored(change("edit-a"), change("edit-b"))
        self.seed(draft.decide("edit-a", Decision.ACCEPTED)
                       .decide("edit-b", Decision.REJECTED))
        for edit_id in ("edit-b", "edit-nope"):
            r = self.publish({"edit_id": edit_id, "status": "written", "revid": 9})
            self.assertEqual(r.status_code, 422, edit_id)
        self.assertIsNone(self.reread().published_at)

    def test_an_undecided_card_shuts_the_gate(self) -> None:
        self.seed(stored(change("edit-a"), change("edit-b"))
                  .decide("edit-a", Decision.ACCEPTED))
        r = self.publish({"edit_id": "edit-a", "status": "written", "revid": 1})
        self.assertEqual(r.status_code, 409)
        self.assertIsNone(self.reread().published_at)

    def test_a_draft_with_nothing_accepted_is_not_published(self) -> None:
        """A run the reviewer discarded whole published nothing, and must not read as
        published — that would be the demo lying about its own headline moment."""
        self.seed(stored(change("edit-a")).decide("edit-a", Decision.REJECTED))
        r = self.publish()
        self.assertEqual(r.status_code, 409)
        self.assertIsNone(self.reread().published_at)

    def test_a_published_draft_refuses_a_second_publish(self) -> None:
        self.accepted("edit-a")
        self.publish({"edit_id": "edit-a", "status": "written", "revid": 1})
        r = self.publish({"edit_id": "edit-a", "status": "written", "revid": 2})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.reread().changes[0].written_revid, 1)

    def test_a_partial_failure_keeps_what_landed_and_leaves_the_rest_outstanding(self) -> None:
        """No cross-page transaction, so a partial publish is a real outcome. What landed is
        recorded; what did not is still awaiting a write."""
        self.accepted("edit-a", "edit-b")
        r = self.publish(
            {"edit_id": "edit-a", "status": "written", "revid": 7},
            {"edit_id": "edit-b", "status": "conflict", "error": "Edit conflict."},
        )
        self.assertEqual(r.status_code, 200)

        held = self.reread()
        by_id = {c.edit_id: c for c in held.changes}
        self.assertEqual(by_id["edit-a"].written_revid, 7)
        self.assertIsNone(by_id["edit-b"].written_revid)

    def test_a_failure_is_reported_per_change_rather_than_as_one_status(self) -> None:
        self.accepted("edit-a", "edit-b")
        r = self.publish(
            {"edit_id": "edit-a", "status": "written", "revid": 7},
            {"edit_id": "edit-b", "status": "missing", "error": "anchor gone"},
        )
        statuses = {row["edit_id"]: row["status"] for row in r.json()["results"]}
        self.assertEqual(statuses, {"edit-a": "written", "edit-b": "missing"})

    def test_an_unknown_status_is_refused(self) -> None:
        """The status vocabulary is closed, so a typo cannot become a new outcome nobody
        handles."""
        self.accepted("edit-a")
        r = self.publish({"edit_id": "edit-a", "status": "probably-fine"})
        self.assertEqual(r.status_code, 422)

    def test_an_unknown_draft_is_a_404_before_anything_is_read(self) -> None:
        r = client().post("/api/drafts/draft-nope/publish", json={"results": []})
        self.assertEqual(r.status_code, 404)


class TestStaticFrontend(unittest.TestCase):
    def test_root_serves_index_html(self) -> None:
        r = client().get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<title>", r.text)

    def test_the_fallback_fixture_is_reachable(self) -> None:
        r = client().get("/data/demo-state.json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["generated_by"], "scripts/build_demo_state.py")


class TestColdStart(unittest.TestCase):
    """Importing `backend.app` must not drag in a vendor SDK (`AGENTS.md` §7)."""

    def test_no_vendor_sdk_at_module_import(self) -> None:
        probe = (
            "import sys; import backend.app; "
            "print([m for m in sys.modules "
            "if m.split('.')[0] == 'parallel' or m.startswith(('google.adk', 'google.genai'))])"
        )
        out = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        self.assertEqual(out.stdout.strip(), "[]", "a vendor SDK is imported at module level")


class TestDotenv(unittest.TestCase):
    def test_existing_environment_wins_over_the_file(self) -> None:
        env_file = REPO_ROOT / "tests" / "_tmp.env"
        env_file.write_text('SET_BY_FILE=from-file\nALREADY_SET="from-file"\n', encoding="utf-8")
        self.addCleanup(env_file.unlink)
        with mock.patch.dict(os.environ, {"ALREADY_SET": "from-deploy"}):
            app_module.load_dotenv(env_file)
            self.assertEqual(os.environ["ALREADY_SET"], "from-deploy")
            self.assertEqual(os.environ["SET_BY_FILE"], "from-file")

    def test_a_missing_file_is_not_an_error(self) -> None:
        app_module.load_dotenv(REPO_ROOT / "tests" / "does-not-exist.env")


if __name__ == "__main__":
    unittest.main()
