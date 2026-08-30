"""What the classify stage decided about one claim, in one task — the fourth collection.

The ledger records what a claim *is* and when to look at it again. Until this it recorded
nothing about **why** it was routed the way it was: `record_outcome` stores `unchanged`,
`changed` or `unresolved`, and the sentence the model gave for that judgement lived only in the
model cassette, which is gitignored and regenerated. So the one artefact that explains a run
was the one artefact nobody could read afterwards.

A judgement is that explanation, stored: the bucket, the sentence behind it, what retrieval was
asked, which urls were dropped as off-subject, and the conflict when there is one. One document
per classification — keyed by task, claim *and* round — so the same claim classified on two
different days is two rows, and a claim **reclassified within one run** is two rows as well.
That second case is the one worth naming: a claim whose first batch came back off-subject is
researched again and judged again, and the agent may reach a different bucket the second time.
Overwriting there would leave a record of the conclusion with no trace of the revision, which
is the half that explains it.

**It is a record, never an input.** Nothing reads a judgement to make a decision; the ledger's
own state does that. A stage that branched on a stored judgement would be branching on a copy
of something `Claim` already holds, and the two would drift.

Pure, like the rest of `core/ledger`: no vendor SDK, no I/O beyond a local file, and the
document holds only the value types Firestore accepts (`documents.py`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .documents import as_datetime
from .store import write_json

#: Local judgement file. Beside `ledger.json` and `baseline.json`, gitignored for the same
#: reason: it is run state, and it carries third-party excerpt urls.
DEFAULT_JUDGEMENTS_PATH = Path("data") / "judgements.json"

#: Bumped when a stored field changes meaning, like `documents.DOCUMENT_VERSION`.
JUDGEMENT_VERSION = 1

#: The Firestore collection. Named here so a deployment cannot read one and write another.
COLLECTION = "judgements"


@dataclass(frozen=True, slots=True)
class Judgement:
    """One claim, classified once, by one task.

    `bucket` is the stage's answer and `outcome` is the ledger transition it implied. Both are
    stored even though one determines the other, because they are two different statements —
    what the model said, and what the ledger did about it — and a later change to the mapping
    must not silently rewrite the history of what was said.
    """

    task_id: str
    claim_id: str
    page: str
    bucket: str
    outcome: str
    reason: str
    decided_at: datetime
    #: Which classification of this claim, in this task, this is. A claim revised in light of
    #: evidence another claim's search turned up keeps both rows; the highest attempt is what
    #: the ledger acted on.
    attempt: int = 1
    objective: str = ""  # what this round of retrieval was asked
    considered: tuple[str, ...] = ()  # urls the stage was shown
    off_entity: tuple[str, ...] = ()  # of those, the ones it dropped as a different subject
    note: str = ""  # the conflict, when the bucket is `conflicting`
    source_a: str = ""
    source_b: str = ""

    @property
    def judgement_id(self) -> str:
        """Document id: one per classification. Not the claim id alone — a claim judged on two
        runs must produce two rows, or the ledger forgets it ever said anything else — and not
        task-plus-claim either, or a reclassification erases the judgement it revised."""
        return f"{self.task_id}--{self.claim_id}--a{self.attempt}"

    @property
    def is_conflict(self) -> bool:
        return bool(self.note or self.source_a or self.source_b)

    @property
    def survivors(self) -> tuple[str, ...]:
        """What was left to judge after filtering. Empty means retrieval went off-subject
        entirely, which is the signal the graph's backward edge fires on (`agent/graph.py`)."""
        dropped = set(self.off_entity)
        return tuple(url for url in self.considered if url not in dropped)


def to_document(judgement: Judgement) -> dict[str, Any]:
    """Firestore-native types only, same contract as `documents.to_document`."""
    return {
        "v": JUDGEMENT_VERSION,
        "judgement_id": judgement.judgement_id,
        "task_id": judgement.task_id,
        "claim_id": judgement.claim_id,
        "page": judgement.page,
        "bucket": judgement.bucket,
        "outcome": judgement.outcome,
        "reason": judgement.reason,
        "attempt": judgement.attempt,
        "objective": judgement.objective,
        "considered": list(judgement.considered),
        "off_entity": list(judgement.off_entity),
        "note": judgement.note,
        "source_a": judgement.source_a,
        "source_b": judgement.source_b,
        "decided_at": judgement.decided_at,
    }


def from_document(doc: Mapping[str, Any]) -> Judgement:
    """Rebuild a judgement. Refuses a version it does not know rather than guessing."""
    version = doc.get("v")
    if version != JUDGEMENT_VERSION:
        # `ValueError`, matching the other two collection codecs: a version this build
        # cannot read is a bad value, and refusing beats guessing at the shape.
        raise ValueError(
            f"judgement document version {version!r}; this build reads {JUDGEMENT_VERSION}"
        )
    decided_at = as_datetime(doc["decided_at"])
    if decided_at is None:
        raise ValueError(f"{doc.get('judgement_id')!r} has no decided_at")
    return Judgement(
        task_id=str(doc["task_id"]),
        claim_id=str(doc["claim_id"]),
        page=str(doc.get("page", "")),
        bucket=str(doc["bucket"]),
        outcome=str(doc.get("outcome", "")),
        reason=str(doc.get("reason", "")),
        decided_at=decided_at,
        attempt=int(doc.get("attempt", 1)),
        objective=str(doc.get("objective", "")),
        considered=tuple(str(u) for u in doc.get("considered", ())),
        off_entity=tuple(str(u) for u in doc.get("off_entity", ())),
        note=str(doc.get("note", "")),
        source_a=str(doc.get("source_a", "")),
        source_b=str(doc.get("source_b", "")),
    )


@runtime_checkable
class JudgementStore(Protocol):
    """Append-only in practice: a judgement is what was decided, and the past does not change.

    `put` still overwrites by id, because re-running the *same* task, claim and attempt is a
    correction of one row rather than a second opinion. Every genuinely different judgement —
    another run, or another round inside one run — has its own id already, so the two cases are
    distinguishable without a rule.
    """

    def put(self, judgement: Judgement) -> None: ...

    def all(self) -> tuple[Judgement, ...]: ...

    def for_task(self, task_id: str) -> tuple[Judgement, ...]: ...

    def for_claim(self, claim_id: str) -> tuple[Judgement, ...]: ...


@dataclass
class InMemoryJudgementStore:
    """The deterministic path: no file, no database (`CLAUDE.md` §3)."""

    _rows: dict[str, Judgement] = field(default_factory=dict)

    def __init__(self, judgements: Iterable[Judgement] = ()) -> None:
        self._rows = {j.judgement_id: j for j in judgements}

    def __len__(self) -> int:
        return len(self._rows)

    def put(self, judgement: Judgement) -> None:
        self._rows[judgement.judgement_id] = judgement

    def all(self) -> tuple[Judgement, ...]:
        """Newest first, then by id so the order is total and a test can assert on it.

        A reclassification and the judgement it revised share a `decided_at` — one run, one
        clock — so the id breaks the tie, and `--a2` sorts after `--a1`. Reversing that would
        put a superseded judgement above the one that replaced it.
        """
        return tuple(
            sorted(
                self._rows.values(),
                key=lambda j: (-j.decided_at.timestamp(), j.claim_id, -j.attempt),
            )
        )

    def for_task(self, task_id: str) -> tuple[Judgement, ...]:
        return tuple(j for j in self.all() if j.task_id == task_id)

    def for_claim(self, claim_id: str) -> tuple[Judgement, ...]:
        return tuple(j for j in self.all() if j.claim_id == claim_id)


class JsonFileJudgementStore(InMemoryJudgementStore):
    """The local database: one JSON file of the documents Firestore holds.

    Read whole and rewritten whole, like the other local stores — one wiki's judgements are a
    small file, and an atomic replace is what stops a killed run leaving a truncated one.
    """

    def __init__(self, path: Path | str = DEFAULT_JUDGEMENTS_PATH) -> None:
        self.path = Path(path)
        super().__init__(_read(self.path))

    def put(self, judgement: Judgement) -> None:
        super().put(judgement)
        self._flush()

    def _flush(self) -> None:
        write_json(
            self.path,
            {"judgements": [to_document(j) for j in self.all()]},
        )


def _read(path: Path) -> tuple[Judgement, ...]:
    if not path.exists():
        return ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(from_document(doc) for doc in raw.get("judgements", ()))
