"""The diff stage — what the edit did to the *ideas*, which text cannot tell you.

`core/wiki/diff.py` answers whether the characters on the page survived. That is a real
question and a cheap one, and it is not the question a reviewer is actually asking. The two
come apart in both directions:

* **Textually additive, semantically destructive.** A draft appends `…, however this was later
  denied.` to the sentence it was extending. Every original character is intact, containment
  holds, `shape()` returns `APPEND` — and the assertion the page made has been reversed. No
  string comparison finds this, because nothing was removed.
* **Textually destructive, semantically additive.** A draft threads `(2024)` into the middle of
  an infobox value. Containment fails and `shape()` returns `MODIFY`, but not one idea was
  dropped.

So the shape is the floor, not the answer. This stage reads `before` and `after` as *claims*
and reports, assertion by assertion, what happened to each: kept, dropped, reversed, or added.
`DESTRUCTIVE` means at least one assertion the page used to make is gone or negated — which,
held against a `new` classification, is the same overreach guard as the textual one and catches
the cases it cannot.

**It is its own node, and deliberately not part of Draft.** A stage that writes an edit and
then rules on whether the edit was conservative is reporting on itself, and that report is the
one thing it cannot be used to check. This is a separate model call, with its own system
instruction and its own schema, that never sees the sources or the objective — only the two
texts. Withholding the motive is the point: a reader told why the edit was made will explain
the edit rather than examine it.

**And it is not Verify.** Verify reads the drafted section against the *rest of the page*, for
a contradiction the edit introduced elsewhere; this reads `before` against `after` of the same
anchor, for what the edit did to what was already there. Verify cannot catch the appended
negation above — the page reads as coherent prose afterwards, because it is.

**The deterministic fallback is the textual shape** (`CLAUDE.md` §3, `AGENTS.md` §7). When the
model is unavailable the stage degrades to `diff.shape()` and says so in the flags, so a run
with a dead credential still gates edits — more coarsely, and never silently.

The rules below are reasoned, not measured. The classify prompt's four rules each came from a
benchmark, and these have not had one yet; the open item that rebuilds that harness covers this
stage too (`summary.md` Phase 1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..core.profile import WikiProfile
from ..core.wiki.diff import APPEND
from ..core.wiki.diff import shape as edit_shape
from .draft import Draft
from .model import ModelError, ModelRequest, ModelSource

#: What happened to one assertion. `reversed` is the value the stage exists for: the assertion
#: is still on the page and the page now denies it.
KEPT = "kept"
ADDED = "added"
DROPPED = "dropped"
REVERSED = "reversed"

DISPOSITIONS = (KEPT, ADDED, DROPPED, REVERSED)

#: Whether the edit took an idea away. The counterpart to `diff.APPEND` / `diff.MODIFY`, one
#: level up: those describe the text, these describe what it asserts.
ADDITIVE = "additive"
DESTRUCTIVE = "destructive"

SYSTEM = """\
You compare two versions of one passage from a wiki page and report what changed about what
the passage ASSERTS. You are not judging whether the edit is good, and you are not being told
why it was made.

Work in this order:

STEP 1 — List every factual assertion the BEFORE text makes. One assertion per entry, in the
passage's own terms. A passage usually makes more than one.

STEP 2 — For each, say what the AFTER text does with it:

  `kept`     — AFTER still asserts it. Rewording, reordering and added detail are all `kept`;
               you are tracking the assertion, not the sentence.
  `dropped`  — AFTER no longer asserts it, and does not deny it either. It is simply gone.
  `reversed` — AFTER denies it, contradicts it, or qualifies it into no longer holding.

STEP 3 — List assertions AFTER makes that BEFORE did not, as `added`.

THE RULE THAT MATTERS MOST: text that was only ADDED can still REVERSE an assertion. If AFTER
keeps the original sentence intact and appends "but this was denied", "this was later
corrected", or any clause that takes the original assertion back, that assertion is `reversed`
— never `kept`, and the appended clause is not merely `added`. Nothing was deleted and the
meaning was still overturned. This is the case you are here to find.

Do not report an assertion twice. Do not evaluate the sources — you have not been shown any.
`note` is one short clause naming the words that decided it.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "assertion": {"type": "string"},
                    "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
                    "note": {"type": "string"},
                },
                "required": ["assertion", "disposition"],
            },
        },
    },
    "required": ["changes"],
}


@dataclass(frozen=True, slots=True)
class Change:
    """One assertion, and what the edit did to it."""

    assertion: str
    disposition: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class Review:
    """The idea-level reading of one draft, beside the text-level one.

    Both shapes are carried because their disagreement is information: an edit that is `APPEND`
    and `DESTRUCTIVE` is precisely the one no string comparison could have caught.
    """

    claim_id: str
    bucket: str
    text_shape: str
    changes: tuple[Change, ...]
    text_only: bool = False  # the model was unavailable; this is the shape alone

    # -- derived -----------------------------------------------------------------

    @property
    def verdict(self) -> str:
        """`destructive` when any assertion was dropped or reversed."""
        return (
            DESTRUCTIVE
            if any(c.disposition in (DROPPED, REVERSED) for c in self.changes)
            else ADDITIVE
        )

    @property
    def reversals(self) -> tuple[Change, ...]:
        return tuple(c for c in self.changes if c.disposition == REVERSED)

    @property
    def overreached(self) -> bool:
        """A `new` claim whose edit took an idea away.

        Same guard as `Draft.overreached`, one level up. The bucket said the page was
        incomplete rather than wrong, so there was nothing to drop or deny.
        """
        return self.bucket == "new" and self.verdict == DESTRUCTIVE

    @property
    def hidden_by_text(self) -> bool:
        """The edit reads as a pure append and still took an idea away.

        The reason this stage is a model call. A reviewer who trusts the green diff approves
        this one, and `shape()` agrees with them.
        """
        return self.text_shape == APPEND and self.verdict == DESTRUCTIVE

    @property
    def flags(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, raised in (
                ("overreached", self.overreached),
                ("hidden_by_text", self.hidden_by_text),
                ("text_only", self.text_only),
            )
            if raised
        )

    def payload(self) -> dict[str, Any]:
        """What the queue card carries beside the diff rows."""
        return {
            "verdict": self.verdict,
            "text_shape": self.text_shape,
            "changes": [
                {"assertion": c.assertion, "disposition": c.disposition, "note": c.note}
                for c in self.changes
            ],
            "flags": list(self.flags),
        }


@dataclass(frozen=True, slots=True)
class Reviewer:
    """One wiki's diff stage. A specialised node: it holds one prompt, answers one question,
    and is never handed the orchestration's other context (`AGENTS.md` §7)."""

    profile: WikiProfile
    source: ModelSource

    def review(self, draft: Draft) -> Review:
        """Read one draft for what it did to the ideas already on the page.

        Falls back to the textual shape when the model is unavailable, rather than failing the
        run: a coarser gate is a gate, and `text_only` says which one the reviewer is looking
        at. A malformed *answer* is not unavailability and is not caught here — it means the
        schema and the model disagree, which is a defect to fix rather than degrade around.
        """
        request = ModelRequest(
            system=SYSTEM, prompt=self.prompt(draft), schema=RESPONSE_SCHEMA
        )
        try:
            raw = self.source.run(request)
        except ModelError:
            return fallback(draft)
        return Review(
            claim_id=draft.claim_id,
            bucket=draft.bucket,
            text_shape=draft.shape,
            changes=parse(raw),
        )

    def prompt(self, draft: Draft) -> str:
        """The filled prompt. No sources, no objective, no classification — see the module
        docstring on why the motive is withheld."""
        return (
            f"BEFORE:\n{draft.before}\n\n"
            f"AFTER:\n{draft.after}\n"
        )


def fallback(draft: Draft) -> Review:
    """The deterministic reading: the text shape, with no assertion-level detail.

    `MODIFY` becomes one unnamed `dropped` so the verdict is honest — something was displaced
    and nothing read it — rather than an empty change list that would score `additive`.
    """
    displaced = edit_shape(draft.before, draft.after) != APPEND
    return Review(
        claim_id=draft.claim_id,
        bucket=draft.bucket,
        text_shape=draft.shape,
        changes=(
            (Change("(not read — text displaced)", DROPPED, "textual shape only"),)
            if displaced
            else ()
        ),
        text_only=True,
    )


def parse(answer: str) -> tuple[Change, ...]:
    """Read the shape we declared, refusing anything else.

    An empty change list is refused: every passage asserts something, so a reader that found
    nothing did not read. Scored as `additive` it would wave the edit through.
    """
    try:
        payload = json.loads(answer)
    except json.JSONDecodeError as exc:
        raise ModelError(f"model answer was not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelError(f"model answer was {type(payload).__name__}, expected an object")

    raw = payload.get("changes")
    if not isinstance(raw, list) or not raw:
        raise ModelError("model reported no assertions; every passage asserts something")

    changes: list[Change] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ModelError(f"change was {type(entry).__name__}, expected an object")
        disposition = entry.get("disposition")
        if disposition not in DISPOSITIONS:
            raise ModelError(
                f"unknown disposition {disposition!r}; expected one of {list(DISPOSITIONS)}"
            )
        assertion = entry.get("assertion")
        if not isinstance(assertion, str) or not assertion.strip():
            raise ModelError("change carried no assertion text")
        note = entry.get("note")
        changes.append(
            Change(assertion, disposition, note if isinstance(note, str) else "")
        )
    return tuple(changes)
