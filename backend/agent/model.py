"""The Gemini perimeter — one call, one shape, and a replay behind it.

Every stage that needs a judgement goes through here: classify today, claim proposal and
drafting later. It is deliberately the narrowest thing that can serve all of them — a system
instruction, a prompt, and a JSON schema the answer must satisfy — because a perimeter that
knows what a claim is would put product logic where the vendor lives.

**Structured output, not prose parsed afterwards.** `response_schema` plus
`response_mime_type="application/json"` makes the model return a value in a shape we declared,
so a stage reads fields rather than regexing sentences. A model that cannot satisfy the schema
fails loudly here instead of producing text that parses into something plausible and wrong.

**Temperature 0.** The decay ladder and the gate are on camera; a stage that classifies
differently on a second run is not demonstrable. Determinism is not guaranteed by temperature
alone, which is exactly why `RecordedModel` exists.

The deterministic fallback is a cassette, like `RecordedSearch` (`CLAUDE.md` §3): a recorded
run replays byte-for-byte, so the whole graph is testable and the demo survives an expired
credential. Auth is ADC — there is no API key on this side (`AGENTS.md` §2) — so the live path
needs `gcloud auth application-default login` locally and nothing at all on Cloud Run.

Imports no ADK, and imports `google.genai` only inside the call: at module top it would land in
every cold start and in the dependency-free test path (`AGENTS.md` §7).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: One model everywhere, measured rather than assumed (`AGENTS.md` §2). No pro tier, no
#: per-stage split: a second model is a second thing to benchmark and to explain.
MODEL = "gemini-3.5-flash"

#: Judgements are reproducible or they are not evidence. See the module docstring.
TEMPERATURE = 0.0

#: A stage that hangs is worse than one that fails: the tick is hourly and a wedged run holds
#: the whole cycle. Generous enough for a long section, short enough to fail inside a tick.
TIMEOUT_SECONDS = 60.0

#: Where a recorded run lives. Not committed — it carries third-party excerpts inside the
#: prompts, same reason as `fixtures/searches.json` (`.gitignore`).
DEFAULT_CASSETTE = Path("fixtures") / "model.json"

#: Answers that mean "ask again later" rather than "this cannot work". 429 is the one that
#: actually happens: a propose pass calls once per section and arrives at the quota as a burst,
#: which is precisely the shape a rate limit is built to refuse — observed Sept 3, 2026, where
#: it killed a live pass eight claims in. 503 joins it because a backend that is momentarily
#: out of capacity is the same situation wearing a different number.
RETRY_CODES = frozenset({429, 503})

#: What to wait before each re-ask, in seconds. Three tries, ~23s of waiting in the worst case:
#: long enough to outlast the burst that caused it, short enough that a reader watching the
#: stepper on a demo does not conclude the run has hung.
RETRY_WAITS: tuple[float, ...] = (2.0, 6.0, 15.0)


class ModelError(Exception):
    """A model call that cannot be retried into success: a refusal, a malformed answer, a
    dead credential. Transport failures are not this — they propagate, so ADK retries them."""


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One judgement, in the form both the live model and the cassette understand."""

    system: str
    prompt: str
    schema: Mapping[str, Any]

    @property
    def key(self) -> str:
        """Stable identity, for recording and replay.

        Hashes everything that changes the answer — instruction, prompt and schema — so an
        edited prompt misses the cassette rather than silently replaying the old prompt's
        answer. That is the failure a recorded run is most likely to hide.
        """
        payload = json.dumps(
            {"system": self.system, "prompt": self.prompt, "schema": self.schema},
            sort_keys=True,
        )
        return hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()


@runtime_checkable
class ModelSource(Protocol):
    """Live or replayed, one method. Returns the raw JSON text the schema describes; parsing
    belongs to the stage that declared the schema, not here."""

    def run(self, request: ModelRequest) -> str: ...


class GeminiModel:
    """Live Gemini over `google-genai`, on Application Default Credentials.

    `enterprise=True` is the verified kwarg on 2.18.1 — the legacy `vertexai` pair still
    exists in the source and is the wrong one (`AGENTS.md` §6). `location` is `"global"` for
    model calls; the pick-one-region rule is about Firestore and Cloud Run.
    """

    def __init__(
        self,
        *,
        model: str = MODEL,
        project: str | None = None,
        location: str = "global",
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self.project = project  # None => the SDK reads GOOGLE_CLOUD_PROJECT itself
        self.location = location
        self.timeout = timeout

    def run(self, request: ModelRequest) -> str:
        # Deferred for the cold-start rule; see the module docstring.
        from google import genai
        from google.genai import types

        client = genai.Client(enterprise=True, project=self.project, location=self.location)
        config = types.GenerateContentConfig(
            system_instruction=request.system,
            temperature=TEMPERATURE,
            response_mime_type="application/json",
            # Deep-copied, and it has to be: the SDK rewrites the schema it is handed *in
            # place* — it adds `propertyOrdering` to nested objects while sending — so a
            # shallow `dict()` leaves the caller's nested dicts shared with it. A stage's
            # `RESPONSE_SCHEMA` is a module constant, so the mutation lands there, the
            # request's own `key` changes mid-call, and the recording is filed under a key
            # nothing can compute again. Silent, and fatal to every replay (`AGENTS.md` §6).
            response_schema=deepcopy(dict(request.schema)),
            http_options=types.HttpOptions(timeout=int(self.timeout * 1000)),
            # We pass no tools — the stages call tools themselves, and a model that could
            # invoke one from inside a judgement would be a second, unlogged control path.
            # Saying so explicitly also silences the SDK's AFC advisory on every call.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._ask(client, request.prompt, config)
        text: str | None = response.text
        if not text:
            # A blocked or empty candidate is a refusal, not a transport failure: retrying the
            # identical prompt cannot change it, so it is a domain error the stage must handle.
            raise ModelError(
                f"{self.model} returned no content "
                f"(finish reason: {_finish_reason(response)})"
            )
        return text

    def _ask(self, client: Any, prompt: str, config: Any) -> Any:
        """One judgement, waiting out a rate limit rather than losing the run to one.

        The SDK retries transport failures itself and gives up on a 429, raising it at us as a
        vendor exception — which is not `ModelError`, so it sails past every `except ModelError`
        a stage has and takes the whole run with it. A propose pass is a burst of one call per
        section, so this is not a rare shape: it is the shape.

        Waited-out and still refused becomes `ModelError`, because that is the exception the
        callers already handle claim-by-claim and section-by-section. The cost of getting this
        wrong is asymmetric — a skipped section is a smaller claim set, a raised `ClientError`
        is a dead run — and the stage above knows which of its work is still worth doing.
        """
        from google.genai import errors

        last: BaseException | None = None
        for attempt in range(len(RETRY_WAITS) + 1):
            try:
                return client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
            except errors.APIError as exc:
                # Anything outside the retry set is a real failure — a dead credential, a bad
                # request — and waiting cannot improve it. Let it propagate untouched.
                if exc.code not in RETRY_CODES:
                    raise
                last = exc
                if attempt < len(RETRY_WAITS):
                    time.sleep(RETRY_WAITS[attempt])
        raise ModelError(
            f"{self.model} stayed rate limited through {len(RETRY_WAITS)} waits "
            f"({sum(RETRY_WAITS):.0f}s); the quota is the problem, not the prompt"
        ) from last


class RecordedModel:
    """Replays a cassette of past judgements — the deterministic fallback.

    Keyed by the request, so an edited prompt is a miss rather than a stale hit. A miss raises
    for the same reason a failed search does: an infrastructure gap must never be recorded as
    a finding about the world (`AGENTS.md` §7).
    """

    def __init__(self, path: Path | str = DEFAULT_CASSETTE) -> None:
        self.path = Path(path)
        raw: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        self._entries: dict[str, Any] = raw.get("judgements", {})

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def run(self, request: ModelRequest) -> str:
        entry = self._entries.get(request.key)
        if entry is None:
            raise ModelError(
                f"no recording for this judgement ({request.key}); the prompt or the schema "
                f"changed, or the run was never recorded. Re-record, or run live."
            )
        answer: str = entry["answer"]
        return answer


def record(path: Path | str, request: ModelRequest, answer: str) -> None:
    """Append one judgement to a cassette, so a live run can be replayed afterwards.

    Stores the prompt beside the answer: a recording nobody can read is one nobody can check,
    and the whole point of the cassette is that the demo's judgements are inspectable.
    """
    target = Path(path)
    raw: dict[str, Any] = (
        json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    )
    entries: dict[str, Any] = raw.setdefault("judgements", {})
    entries[request.key] = {
        "system": request.system,
        "prompt": request.prompt,
        "schema": dict(request.schema),
        "answer": answer,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")


def _finish_reason(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "no candidates"
    return str(getattr(candidates[0], "finish_reason", "unknown"))
