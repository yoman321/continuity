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


if __name__ == "__main__":
    unittest.main()
