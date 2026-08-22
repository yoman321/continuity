"""FastAPI shell tests — the guard on the tick route, and the cold-start rule.

Two of these cover invariants rather than behaviour, and are the reason this file exists:

* `/internal/tick` is public (judging requires `--allow-unauthenticated`), so the shared-secret
  compare is the whole of its security. Every way of getting past it without the token is a
  case below, including the unset-token path, which must fail closed rather than open.
* No vendor SDK may be imported at module level, or a cold container spends 5-15s on ADK before
  it can serve `index.html` (`AGENTS.md` §7). That is checked in a subprocess against
  `sys.modules`, because an intention stated in a comment is not a measurement.

Unlike the ledger tests these need the venv — `app.py` imports FastAPI. The module skips
rather than fails on a bare interpreter so the dependency-free suite still runs there.
"""

import logging
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover - exercised only on a bare interpreter
    raise unittest.SkipTest(f"app tests need the venv: {exc}") from exc

sys.path.insert(0, str(REPO_ROOT))

from backend import app as app_module  # noqa: E402  - after the path insert, deliberately

TOKEN = "correct-horse-battery-staple"


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

    def test_queue_rejects_an_unknown_verdict(self) -> None:
        r = client().post("/api/queue/edit-gam-app-01", json={"decision": "maybe"})
        self.assertEqual(r.status_code, 422)

    def test_queue_accepts_the_contract_the_frontend_codes_against(self) -> None:
        for decision in ("approve", "reject"):
            with self.subTest(decision=decision):
                r = client().post("/api/queue/edit-gam-app-01", json={"decision": decision})
                self.assertEqual(r.status_code, 501)


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
