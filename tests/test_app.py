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

import contextlib
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
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
    JsonFileDraftStore,
    ReviewDraft,
)

TOKEN = "correct-horse-battery-staple"

#: Shaped like `.env`, valued like nothing. No test here opens a socket.
WIKI_ENV = {
    "MEDIAWIKI_API_URL": "http://wiki.invalid/api.php",
    "MEDIAWIKI_API_KEY": "not-a-real-key",
    "MEDIAWIKI_BOT_USER": "TestBot@tests",
    "MEDIAWIKI_BOT_PASSWORD": "not-a-real-password",
}

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


class StubWrite:
    """Stands in for `WikiWrite`, recording the call instead of making it."""

    def __init__(self, result: dict[str, Any] | list[dict[str, Any]]) -> None:
        self.result = result
        self.logins: list[tuple[str, str]] = []
        self.calls: list[dict[str, str]] = []

    def login(self, username: str, password: str) -> str:
        self.logins.append((username, password))
        return username

    def write_anchor(
        self, title: str, heading: str, anchor: str, replacement: str, summary: str
    ) -> dict[str, Any]:
        self.calls.append({
            "title": title, "heading": heading, "anchor": anchor,
            "replacement": replacement, "summary": summary,
        })
        if isinstance(self.result, list):
            # One outcome per write, so a partial failure can be staged.
            return self.result[min(len(self.calls), len(self.result)) - 1]
        return self.result


@contextlib.contextmanager
def wiki(
    result: dict[str, Any] | list[dict[str, Any]] | None = None,
    env: dict[str, str] | None = None,
) -> Iterator[tuple[StubWrite, mock.MagicMock]]:
    """The wiki, replaced. Yields the stub and the patched constructor, because half of what
    these tests assert is that the constructor was never reached at all."""
    stub = StubWrite(WRITTEN if result is None else result)
    with mock.patch.dict(os.environ, WIKI_ENV if env is None else env), \
            mock.patch.object(WikiWrite, "live", return_value=stub) as live:
        yield stub, live


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
    def test_state_is_unavailable_so_the_frontend_falls_back(self) -> None:
        r = client().get("/api/state")
        self.assertEqual(r.status_code, 503)
        msg = "the FE fallback keys off !r.ok; a 2xx here would claim 'live'"
        self.assertFalse(r.is_success, msg)


class DraftCase(unittest.TestCase):
    """Every draft test runs against a real store in a temp file, not a mock of one.

    The store is the thing under test as much as the routes are: a verdict that does not
    survive the write is the failure the whole change exists to prevent.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "drafts.json"
        patch = mock.patch.dict(os.environ, {"DRAFT_STORE_PATH": str(self.path)})
        patch.start()
        self.addCleanup(patch.stop)

    def seed(self, draft: ReviewDraft | None = None) -> ReviewDraft:
        draft = draft if draft is not None else stored()
        JsonFileDraftStore(self.path).put(draft)
        return draft

    def reread(self) -> ReviewDraft:
        """What the *next* process would see. Asserting on this rather than on the response is
        what makes these tests about persistence and not about a return value."""
        held = JsonFileDraftStore(self.path).get(DRAFT_ID)
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
        nothing else — no write, and no wiki session even opened."""
        self.seed()
        with wiki() as (stub, live):
            client().post(
                f"/api/drafts/{DRAFT_ID}/changes/edit-a", json={"decision": "rejected"}
            )
        self.assertFalse(live.called)
        self.assertEqual(stub.calls, [])
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
    """The write. Every case is about what the request is *not* allowed to decide."""

    def accepted(self, *edit_ids: str) -> ReviewDraft:
        draft = stored(*[change(edit_id) for edit_id in edit_ids])
        for edit_id in edit_ids:
            draft = draft.decide(edit_id, Decision.ACCEPTED)
        return self.seed(draft)

    def test_everything_the_write_is_made_from_comes_from_the_store(self) -> None:
        draft = self.accepted("edit-a")
        with wiki() as (stub, _):
            r = client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(stub.calls, [{
            "title": draft.changes[0].page,
            "heading": "",  # the lead has no heading of its own
            "anchor": draft.changes[0].before,
            "replacement": draft.changes[0].after,
            "summary": draft.changes[0].summary,
        }])

    def test_the_reviewers_own_text_is_what_publishes(self) -> None:
        self.accepted("edit-a")
        client().post(f"/api/drafts/{DRAFT_ID}/changes/edit-a", json={"text": "mine"})
        with wiki() as (stub, _):
            client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual(stub.calls[0]["replacement"], "mine")

    def test_a_rejected_change_is_never_written(self) -> None:
        draft = stored(change("edit-a"), change("edit-b"))
        self.seed(
            draft.decide("edit-a", Decision.ACCEPTED).decide("edit-b", Decision.REJECTED)
        )
        with wiki() as (stub, _):
            client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual([c["anchor"] for c in stub.calls], [draft.changes[0].before])

    def test_publishing_stamps_the_draft(self) -> None:
        self.accepted("edit-a")
        with wiki():
            r = client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertTrue(r.json()["published"])
        self.assertTrue(self.reread().published)
        self.assertEqual(self.reread().changes[0].written_revid, 101)

    def test_an_undecided_card_holds_the_whole_publish(self) -> None:
        """The gate's rule, enforced where it matters rather than only in the browser."""
        self.seed(stored(change("edit-a"), change("edit-b")).decide("edit-a", Decision.ACCEPTED))
        with wiki() as (stub, live):
            r = client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual(r.status_code, 409)
        self.assertFalse(live.called)
        self.assertEqual(stub.calls, [])

    def test_a_second_press_writes_nothing_again(self) -> None:
        self.accepted("edit-a")
        with wiki():
            client().post(f"/api/drafts/{DRAFT_ID}/publish")
        with wiki() as (stub, _):
            r = client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(stub.calls, [])

    def test_a_partial_failure_keeps_what_landed_and_retries_the_rest(self) -> None:
        """MediaWiki has no cross-page transaction, so this is the case that decides whether
        `written_revid` earns its place: the retry must write one change, not two."""
        self.accepted("edit-a", "edit-b")
        stale = {"status": "conflict", "error": "Re-read the section and re-draft."}
        with wiki(result=[WRITTEN, stale]) as (stub, _):
            r = client().post(f"/api/drafts/{DRAFT_ID}/publish")

        self.assertEqual(len(stub.calls), 2)
        self.assertEqual([x["status"] for x in r.json()["results"]], ["written", "conflict"])
        self.assertFalse(r.json()["published"])
        self.assertFalse(self.reread().published)

        with wiki() as (stub, _):
            retry = client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual([c["anchor"] for c in stub.calls], [change("edit-b").before])
        self.assertTrue(retry.json()["published"])

    def test_a_failure_is_reported_per_change_rather_than_as_one_status(self) -> None:
        self.accepted("edit-a")
        refused = {"status": "error", "error": "protected page", "code": "protectedpage"}
        with wiki(result=refused):
            r = client().post(f"/api/drafts/{DRAFT_ID}/publish")
        # 200: the request was carried out. What happened to each change is in the body, which
        # is the only shape that can describe two writes with different outcomes.
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"][0]["error"], "protected page")
        self.assertFalse(r.json()["published"])

    def test_a_publish_without_credentials_writes_nothing(self) -> None:
        self.accepted("edit-a")
        with wiki(env=dict.fromkeys(WIKI_ENV, "")) as (_, live):
            r = client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual(r.status_code, 503)
        self.assertFalse(live.called)

    def test_an_unknown_draft_never_reaches_the_wiki(self) -> None:
        with wiki() as (stub, live):
            r = client().post("/api/drafts/draft-nope/publish")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(live.called)
        self.assertEqual(stub.calls, [])

    def test_a_draft_with_nothing_accepted_is_not_published(self) -> None:
        self.seed(stored().decide("edit-a", Decision.REJECTED))
        with wiki() as (_, live):
            r = client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual(r.status_code, 409)
        self.assertFalse(live.called)
        self.assertFalse(self.reread().published)

    def test_the_key_and_the_bot_credentials_reach_the_tool(self) -> None:
        self.accepted("edit-a")
        with wiki() as (stub, live):
            client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual(live.call_args.kwargs["api_key"], WIKI_ENV["MEDIAWIKI_API_KEY"])
        self.assertEqual(
            stub.logins,
            [(WIKI_ENV["MEDIAWIKI_BOT_USER"], WIKI_ENV["MEDIAWIKI_BOT_PASSWORD"])],
        )

    def test_one_login_serves_the_whole_draft(self) -> None:
        self.accepted("edit-a", "edit-b")
        with wiki() as (stub, _):
            client().post(f"/api/drafts/{DRAFT_ID}/publish")
        self.assertEqual(len(stub.logins), 1)

    def test_a_published_draft_refuses_a_new_verdict(self) -> None:
        self.accepted("edit-a")
        with wiki():
            client().post(f"/api/drafts/{DRAFT_ID}/publish")
        r = client().post(
            f"/api/drafts/{DRAFT_ID}/changes/edit-a", json={"decision": "rejected"}
        )
        self.assertEqual(r.status_code, 409)


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
