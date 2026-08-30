"""The review draft — what the gate reads, and where a decision is remembered.

A run produces one draft: a document holding every change it proposes, the reviewer's verdict on
each, and one flag for whether the set has been published. It is the review queue made durable.
Before it, the drafted edits were a generated fixture and every decision lived in a browser tab,
so closing the popup lost the review and reloading it re-offered cards that had been rejected.

**One document, not one per change.** The gate is a batch: Publish is a single act over the
accepted set and only unlocks once every change has a verdict, so the set is what the reviewer
is deciding about and the set is what gets stored. It is also what keeps the published flag
truthful — `published_at` is a fact about a draft rather than a number reconstructed by counting
rows that might disagree.

Three fields carry the whole lifecycle:

* **`Change.decision`** — `undecided`, `accepted` or `rejected`. Rejecting is a discard, not a
  verdict on the claim (`AGENTS.md` §2): the change drops out of the set and the claim behind it
  is untouched, which is why nothing here writes back to `claims`.
* **`Change.written_revid`** — the revision a change actually created, or `None`. Stored because
  a publish can partially fail: MediaWiki has no cross-page transaction, so the second attempt
  has to know what already landed instead of writing it again.
* **`ReviewDraft.published_at`** — set once every accepted change has been written. `published`
  reads it as a boolean. Nothing else about the lifecycle is stored, because a stored derivation
  that disagrees with what it was derived from is the failure `documents.py` exists to avoid.

Vocabulary: a *change* is one before/after pair — one card to the reviewer, one `action=edit` on
the wiki. Its id is `edit_id`, the name the routes, the frontend and the fixture already use.

Pure: filesystem only, like the claim store beside it. No network and no vendor SDK.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: Local draft file, relative to the repo root. Gitignored: it is run state, not source.
DEFAULT_DRAFTS_PATH = Path("data") / "drafts.json"

#: Bumped when a stored field changes meaning. `from_document` refuses anything else rather than
#: guessing, for the same reason the claim ledger does: a draft read wrong is a wrong edit.
DRAFT_DOCUMENT_VERSION = 1


class DraftError(Exception):
    """A write the store or a transition refuses. Raised rather than returned — there is no
    model on the other side of this call to re-plan from a value."""


class Decision(str, Enum):
    """The reviewer's verdict on one change. Three values, and the third is not a verdict.

    `REJECTED` means *discarded from this draft*, which is why it sits here and not on the
    claim: `ClaimStatus` has no `rejected` value and must not grow one (`AGENTS.md` §2). A
    discarded change leaves the claim exactly as it was, to be drafted again on a later run.
    """

    UNDECIDED = "undecided"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Change:
    """One before/after pair, with the verdict on it and what it wrote.

    `before` is the anchor — an exact substring of the section, never the section itself — and
    `after` is what it becomes. Publishing substitutes one for the other in whatever the page
    says at that moment, so neither field is ever a copy of a page (`agent/draft.py`).

    The diff is not stored. It is a view of `before` and `after` computed when the card is
    rendered, because the gate's whole purpose is to let hours pass before someone clicks.
    """

    edit_id: str
    claim_id: str
    page: str
    page_slug: str
    section_index: int
    section_heading: str
    before: str
    after: str
    summary: str  # the edit summary that goes on the wiki
    rationale: str  # why the agent proposes it, for the reviewer
    confidence: float
    citation: str = ""
    bucket: str = ""
    flags: tuple[str, ...] = ()
    decision: Decision = Decision.UNDECIDED
    written_revid: int | None = None

    @property
    def written(self) -> bool:
        return self.written_revid is not None

    @property
    def publishable(self) -> bool:
        """Accepted and not yet on the wiki — what a publish still has to do."""
        return self.decision is Decision.ACCEPTED and not self.written


@dataclass(frozen=True, slots=True)
class ReviewDraft:
    """One run's proposed changes, and whether they have been published.

    Immutable, like `Claim`: every transition returns a new draft, so a caller cannot half-apply
    one. The store is what makes the new value durable.
    """

    draft_id: str
    wiki: str  # the profile the run was made under, so a draft names its own instance
    created_at: datetime
    changes: tuple[Change, ...]
    published_at: datetime | None = None

    # -- reading ------------------------------------------------------------------

    @property
    def published(self) -> bool:
        """The flag the gate shows. True once every accepted change has been written."""
        return self.published_at is not None

    @property
    def accepted(self) -> tuple[Change, ...]:
        return tuple(c for c in self.changes if c.decision is Decision.ACCEPTED)

    @property
    def undecided(self) -> tuple[Change, ...]:
        return tuple(c for c in self.changes if c.decision is Decision.UNDECIDED)

    @property
    def publishable(self) -> tuple[Change, ...]:
        """Accepted and unwritten, in the order the reviewer read them. A retry after a partial
        failure publishes exactly this, which is what stops a second attempt rewriting the
        changes that already landed."""
        return tuple(c for c in self.changes if c.publishable)

    @property
    def is_decided(self) -> bool:
        """Every change has a verdict — what unlocks the publish button (`AGENTS.md` §2)."""
        return not self.undecided

    def change(self, edit_id: str) -> Change | None:
        return next((c for c in self.changes if c.edit_id == edit_id), None)

    # -- transitions --------------------------------------------------------------

    def decide(self, edit_id: str, decision: Decision) -> ReviewDraft:
        """Record a verdict on one change. Undoing one is `Decision.UNDECIDED`, not a delete."""
        return self._replace_change(
            edit_id, lambda change: replace(change, decision=decision), "decide"
        )

    def revise(self, edit_id: str, after: str) -> ReviewDraft:
        """Store the reviewer's own text over the agent's.

        The gate lets a draft be edited in place, and that edit has to survive the reload this
        store exists for — otherwise the text a reviewer accepted and the text that publishes
        are different strings (`AGENTS.md` §7).
        """
        if not after.strip():
            raise DraftError(f"{edit_id}: an empty replacement would delete the anchor")
        return self._replace_change(edit_id, lambda change: replace(change, after=after), "edit")

    def mark_written(self, edit_id: str, revid: int) -> ReviewDraft:
        """Record the revision one change created. Idempotent by construction: a written change
        is no longer `publishable`, so the next publish skips it."""
        return self._replace_change(
            edit_id, lambda change: replace(change, written_revid=revid), "write"
        )

    def settled(self, now: datetime) -> ReviewDraft:
        """Stamp `published_at` if the draft is finished, otherwise return it unchanged.

        Finished means every accepted change is on the wiki *and* at least one was accepted: a
        draft whose every card was discarded published nothing, and saying otherwise would put a
        published flag on a run that never touched the wiki.
        """
        if self.published or not self.accepted or self.publishable:
            return self
        return replace(self, published_at=now)

    def _replace_change(
        self, edit_id: str, apply: Any, verb: str
    ) -> ReviewDraft:
        if self.published:
            raise DraftError(f"{self.draft_id} is published; cannot {verb} {edit_id}")
        if self.change(edit_id) is None:
            raise DraftError(f"{self.draft_id} has no change {edit_id}")
        return replace(
            self,
            changes=tuple(apply(c) if c.edit_id == edit_id else c for c in self.changes),
        )


# -- the stored shape -----------------------------------------------------------------


def to_document(draft: ReviewDraft) -> dict[str, Any]:
    """Emit only the value types Firestore's document model accepts, so the adapter hands the
    result straight to `.set()`. The local store pays the difference, because JSON has no
    timestamp type (`store.py`)."""
    return {
        "version": DRAFT_DOCUMENT_VERSION,
        "draft_id": draft.draft_id,
        "wiki": draft.wiki,
        "created_at": draft.created_at,
        "published_at": draft.published_at,
        "changes": [
            {
                "edit_id": c.edit_id,
                "claim_id": c.claim_id,
                "page": c.page,
                "page_slug": c.page_slug,
                "section_index": c.section_index,
                "section_heading": c.section_heading,
                "before": c.before,
                "after": c.after,
                "summary": c.summary,
                "rationale": c.rationale,
                "confidence": c.confidence,
                "citation": c.citation,
                "bucket": c.bucket,
                "flags": list(c.flags),
                "decision": c.decision.value,
                "written_revid": c.written_revid,
            }
            for c in draft.changes
        ],
    }


def from_document(document: Mapping[str, Any]) -> ReviewDraft:
    """Rebuild a draft. Refuses a version it does not know rather than guessing at the shape."""
    version = document.get("version")
    if version != DRAFT_DOCUMENT_VERSION:
        raise DraftError(
            f"draft document version {version!r}; this build reads {DRAFT_DOCUMENT_VERSION}"
        )
    raw: Sequence[Mapping[str, Any]] = document.get("changes", ())
    return ReviewDraft(
        draft_id=str(document["draft_id"]),
        wiki=str(document["wiki"]),
        created_at=_timestamp(document["created_at"]),
        published_at=(
            _timestamp(document["published_at"]) if document.get("published_at") else None
        ),
        changes=tuple(
            Change(
                edit_id=str(c["edit_id"]),
                claim_id=str(c["claim_id"]),
                page=str(c["page"]),
                page_slug=str(c["page_slug"]),
                section_index=int(c["section_index"]),
                section_heading=str(c["section_heading"]),
                before=str(c["before"]),
                after=str(c["after"]),
                summary=str(c["summary"]),
                rationale=str(c.get("rationale", "")),
                confidence=float(c["confidence"]),
                citation=str(c.get("citation", "")),
                bucket=str(c.get("bucket", "")),
                flags=tuple(str(f) for f in c.get("flags", ())),
                decision=Decision(c.get("decision", Decision.UNDECIDED.value)),
                written_revid=(
                    int(c["written_revid"]) if c.get("written_revid") is not None else None
                ),
            )
            for c in raw
        ),
    )


def _timestamp(value: Any) -> datetime:
    """Firestore returns a `datetime` subclass; the local file returns the ISO string it wrote.
    Both land here, and both come back timezone-aware — a naive one would compare wrong."""
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


# -- the stores -----------------------------------------------------------------------


@runtime_checkable
class DraftStore(Protocol):
    """Four operations, and deliberately no more.

    `get` is how the gate fetches back the exact draft it was opened on, `put` is how a verdict
    or a write is remembered, `all` serves the list, and `unpublished` is the one query with a
    meaning — the work still waiting for a reviewer. Every store that satisfies this — in-memory,
    file, Firestore — is interchangeable.
    """

    def get(self, draft_id: str) -> ReviewDraft | None: ...

    def put(self, draft: ReviewDraft) -> None: ...

    def all(self) -> tuple[ReviewDraft, ...]: ...

    def unpublished(self) -> tuple[ReviewDraft, ...]: ...


class InMemoryDraftStore:
    """The deterministic store: a dict, so the gate can be exercised with no database at all."""

    def __init__(self, drafts: Iterable[ReviewDraft] = ()) -> None:
        self._drafts: dict[str, ReviewDraft] = {d.draft_id: d for d in drafts}

    def __len__(self) -> int:
        return len(self._drafts)

    def get(self, draft_id: str) -> ReviewDraft | None:
        return self._drafts.get(draft_id)

    def put(self, draft: ReviewDraft) -> None:
        self._drafts[draft.draft_id] = draft

    def all(self) -> tuple[ReviewDraft, ...]:
        """Newest first, tie-broken by id — the order Firestore returns for
        `order_by("created_at", DESCENDING)`, whose implicit tiebreak is the document id."""
        return tuple(sorted(self._drafts.values(), key=_newest_first))

    def unpublished(self) -> tuple[ReviewDraft, ...]:
        return tuple(d for d in self.all() if not d.published)


class JsonFileDraftStore(InMemoryDraftStore):
    """The local database: an in-memory store that survives the process.

    Inherits rather than reimplements, so ordering cannot drift from the semantics the gate is
    tested against. The file holds `{"drafts": {draft_id: document}}`, and every write rewrites
    it through a temp file and `Path.replace` — an interrupted publish leaves the previous draft
    intact rather than a truncated one.
    """

    def __init__(self, path: Path | str = DEFAULT_DRAFTS_PATH) -> None:
        self.path = Path(path)
        super().__init__(_read_drafts(self.path))

    def put(self, draft: ReviewDraft) -> None:
        super().put(draft)
        self._flush()

    def _flush(self) -> None:
        write_json(
            self.path,
            {"drafts": {d.draft_id: to_document(d) for d in sorted(self._drafts.values(),
                                                                   key=lambda x: x.draft_id)}},
        )


def _read_drafts(path: Path) -> tuple[ReviewDraft, ...]:
    if not path.exists():
        return ()
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return tuple(from_document(doc) for doc in payload.get("drafts", {}).values())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomic write, same contract as the claim store's — the two collections must not disagree
    about durability."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_encode), encoding="utf-8"
    )
    temp.replace(path)


def _encode(value: Any) -> str:
    """JSON has no timestamp type; Firestore does. The only place the two stores differ."""
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot store {type(value).__name__} in the draft file")


def _newest_first(draft: ReviewDraft) -> tuple[float, str]:
    return (-draft.created_at.timestamp(), draft.draft_id)
