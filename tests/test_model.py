"""The Gemini perimeter: what identifies a judgement, and what a replay must refuse.

The cassette is the whole reason this file matters. A recording keyed loosely would replay
yesterday's answer to today's prompt — the failure a deterministic fallback is most likely to
hide, and one that looks like everything working. So the key covers the instruction, the prompt
and the schema, and a miss raises rather than returning something.

No SDK: `GeminiModel.run` imports `google.genai` inside the call, so this module is importable
and testable with nothing installed.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.agent.model import (
    MODEL,
    RETRY_WAITS,
    TEMPERATURE,
    GeminiModel,
    ModelError,
    ModelRequest,
    ModelSource,
    RecordedModel,
    record,
)

SCHEMA = {"type": "object", "properties": {"bucket": {"type": "string"}}}


def request(**overrides: object) -> ModelRequest:
    base: dict[str, object] = dict(system="be exact", prompt="classify this", schema=SCHEMA)
    return ModelRequest(**{**base, **overrides})  # type: ignore[arg-type]


class TestRequestIdentity(unittest.TestCase):
    def test_the_same_judgement_has_the_same_key(self) -> None:
        self.assertEqual(request().key, request().key)

    def test_an_edited_prompt_is_a_different_judgement(self) -> None:
        self.assertNotEqual(request().key, request(prompt="classify that").key)

    def test_an_edited_instruction_is_a_different_judgement(self) -> None:
        # The rules in `classify.SYSTEM` were each measured. Editing one and replaying the old
        # answer would hide exactly the regression the cassette is supposed to make visible.
        self.assertNotEqual(request().key, request(system="be vague").key)

    def test_an_edited_schema_is_a_different_judgement(self) -> None:
        other = {"type": "object", "properties": {"verdict": {"type": "string"}}}
        self.assertNotEqual(request().key, request(schema=other).key)


class TestRecordedModel(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "model.json"
        self.addCleanup(self.dir.cleanup)

    def test_a_recorded_judgement_replays_exactly(self) -> None:
        record(self.path, request(), '{"bucket": "still_true"}')
        self.assertEqual(RecordedModel(self.path).run(request()), '{"bucket": "still_true"}')

    def test_a_miss_raises_rather_than_answering(self) -> None:
        record(self.path, request(), '{"bucket": "still_true"}')
        with self.assertRaises(ModelError) as caught:
            RecordedModel(self.path).run(request(prompt="something else"))
        self.assertIn("Re-record, or run live", str(caught.exception))

    def test_an_edited_prompt_misses_instead_of_replaying_the_old_answer(self) -> None:
        record(self.path, request(), '{"bucket": "still_true"}')
        with self.assertRaises(ModelError):
            RecordedModel(self.path).run(request(system="rewritten rules"))

    def test_the_recording_keeps_the_prompt_beside_the_answer(self) -> None:
        # A recording nobody can read is one nobody can check.
        record(self.path, request(), '{"bucket": "new"}')
        entry = next(iter(json.loads(self.path.read_text())["judgements"].values()))

        self.assertEqual(entry["system"], "be exact")
        self.assertEqual(entry["prompt"], "classify this")
        self.assertEqual(entry["schema"], SCHEMA)

    def test_recording_twice_keeps_both(self) -> None:
        record(self.path, request(), '{"bucket": "new"}')
        record(self.path, request(prompt="another"), '{"bucket": "still_true"}')

        self.assertEqual(len(RecordedModel(self.path).keys), 2)

    def test_a_recorded_model_satisfies_the_protocol(self) -> None:
        record(self.path, request(), "{}")
        self.assertIsInstance(RecordedModel(self.path), ModelSource)


class TestSettings(unittest.TestCase):
    def test_one_model_everywhere(self) -> None:
        self.assertTrue(MODEL.startswith("gemini-"))

    def test_judgements_are_deterministic_by_setting(self) -> None:
        # The decay ladder and the review queue are filmed; a stage that reclassifies on a
        # second run is not demonstrable.
        self.assertEqual(TEMPERATURE, 0.0)


class TestTheCallLeavesTheRequestAlone(unittest.TestCase):
    """The bug that made every recording unreplayable, pinned.

    `google-genai` rewrites the schema it is handed *in place* while sending — it adds
    `propertyOrdering` to nested objects. A stage's `RESPONSE_SCHEMA` is a module constant and
    a shallow `dict()` shares its nested dicts, so the mutation landed in the constant, the
    request's own `key` changed mid-call, and `record()` filed the answer under a key no later
    process could compute. Every replay missed, and the miss looked like a stale prompt.

    Verified against the live API on Aug 30, 2026 and reproduced here with a fake client that
    mutates the same way, so the fix is held without a credential or a call.
    """

    def call(self) -> tuple[dict[str, Any], str]:
        try:
            from unittest.mock import patch
        except ImportError as exc:  # pragma: no cover - stdlib
            raise unittest.SkipTest(str(exc)) from exc
        try:
            from google import genai  # noqa: F401  - presence check only
        except ImportError as exc:  # pragma: no cover - only on a bare interpreter
            raise unittest.SkipTest(f"needs the venv: {exc}") from exc

        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"conflict": {"type": "object", "properties": {"note": {}}}},
        }
        request = ModelRequest(system="s", prompt="p", schema=schema)
        before = request.key

        class Models:
            @staticmethod
            def generate_content(*, model: str, contents: str, config: Any) -> Any:
                # What the SDK does to the dict it was given.
                config.response_schema["properties"]["conflict"]["propertyOrdering"] = ["note"]
                return type("R", (), {"text": '{"ok": true}'})()

        client = type("C", (), {"models": Models()})()
        with patch("google.genai.Client", return_value=client):
            GeminiModel().run(request)
        return schema, before

    def test_the_schema_the_caller_holds_is_unchanged(self) -> None:
        schema, _ = self.call()
        self.assertNotIn("propertyOrdering", schema["properties"]["conflict"])

    def test_a_request_keys_the_same_after_it_has_been_run(self) -> None:
        """The property that actually matters: `record()` runs after the call, so a key that
        moved during it writes an entry nothing can ever look up."""
        schema, before = self.call()
        self.assertEqual(ModelRequest(system="s", prompt="p", schema=schema).key, before)


class TestARateLimitCostsAWaitNotTheRun(unittest.TestCase):
    """A 429 arrives as a vendor exception, not `ModelError`, so it used to sail past every
    `except ModelError` a stage has and kill the whole run — observed Sept 3, 2026, eight claims
    into a live propose pass. Held here with a fake client, so no quota is spent proving it."""

    def run_with(self, codes: list[int]) -> tuple[str | None, int]:
        """Answer after failing with `codes` in order. Returns the text and the call count."""
        try:
            from unittest.mock import patch

            from google.genai import errors
        except ImportError as exc:  # pragma: no cover - only on a bare interpreter
            raise unittest.SkipTest(f"needs the venv: {exc}") from exc

        calls = {"n": 0}
        pending = list(codes)

        class Models:
            @staticmethod
            def generate_content(*, model: str, contents: str, config: Any) -> Any:
                calls["n"] += 1
                if pending:
                    code = pending.pop(0)
                    raise errors.ClientError(code, {"error": {"message": "no"}}, None)
                return type("R", (), {"text": '{"ok": true}'})()

        client = type("C", (), {"models": Models()})()
        # Waiting for real would put ~23s of sleep in the suite to prove arithmetic.
        with patch("google.genai.Client", return_value=client), \
             patch("backend.agent.model.time.sleep") as slept:
            try:
                text = GeminiModel().run(ModelRequest(system="s", prompt="p", schema={}))
            finally:
                self.slept = [c.args[0] for c in slept.call_args_list]
        return text, calls["n"]

    def test_a_rate_limited_call_is_asked_again(self) -> None:
        text, calls = self.run_with([429])
        self.assertEqual(text, '{"ok": true}')
        self.assertEqual(calls, 2)

    def test_it_waits_longer_each_time(self) -> None:
        # Backing off matters more than the exact numbers: re-asking immediately is what the
        # quota just refused.
        self.run_with([429, 429])
        self.assertEqual(self.slept, list(RETRY_WAITS[:2]))
        self.assertEqual(sorted(self.slept), self.slept)

    def test_an_overloaded_backend_is_the_same_situation(self) -> None:
        self.assertEqual(self.run_with([503])[0], '{"ok": true}')

    def test_giving_up_raises_what_the_stages_catch(self) -> None:
        # The whole point: a stage skips one section on `ModelError` and keeps its other work.
        with self.assertRaises(ModelError):
            self.run_with([429] * (len(RETRY_WAITS) + 1))

    def test_it_stops_asking_rather_than_waiting_forever(self) -> None:
        with self.assertRaises(ModelError):
            self.run_with([429] * (len(RETRY_WAITS) + 1))
        self.assertEqual(len(self.slept), len(RETRY_WAITS))

    def test_a_failure_waiting_cannot_fix_is_not_retried(self) -> None:
        """A dead credential or a malformed request is not a quota problem, and burning 23
        seconds before reporting it helps nobody."""
        try:
            from google.genai import errors
        except ImportError as exc:  # pragma: no cover - only on a bare interpreter
            raise unittest.SkipTest(f"needs the venv: {exc}") from exc
        with self.assertRaises(errors.ClientError):
            self.run_with([403])
        self.assertEqual(self.slept, [])


if __name__ == "__main__":
    unittest.main()
