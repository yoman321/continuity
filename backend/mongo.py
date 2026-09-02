"""The ledger over MongoDB — a real document store, running locally.

This replaces the JSON file stores that stood in for a database until Sept 1, 2026. It is a
*perimeter* module: the five collections it serves are defined by protocols in
`backend.core.ledger`, and every document it reads or writes goes through the codecs that were
written for Firestore (`to_document` / `from_document`). Those emit only value types both
Firestore and MongoDB accept — `str`, `int`, `float`, `bool`, `None`, `datetime`, `list`,
`dict` — so this adapter is transport and nothing else, and the Firestore one stays a sibling
rather than a rewrite.

**No fallback, deliberately** (waived Sept 1, 2026 — `AGENTS.md` §2). `CLAUDE.md` §3 asks every
external source for a deterministic fallback; the ledger no longer has one, so a run needs
`mongod` up. The `InMemory*` stores still exist and are what the test suite uses, which is why
the suite still runs on an interpreter with nothing installed — but they are a test double now,
not a production path a demo can fall back onto.

Two constraints are carried over from Firestore even though MongoDB does not impose them,
because the point of this store is to behave like the one it ports to:

  * `put` refuses a claim with no `next_check_at` (`require_scheduled`). A null field is
    invisible to a Firestore inequality filter, so an unseeded claim would be due here and
    absent there.
  * `due()` filters and sorts on `next_check_at` alone, with `_id` only as a tiebreak.
    Firestore's implicit `order_by` tiebreak is the document id, so a limited query has to
    page identically in both.

Ids are the natural key in `_id`, so a re-`put` of the same claim replaces its document rather
than appending a second one, and identity is the ledger's rather than the driver's.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .core.ledger.baseline import SectionBaseline
from .core.ledger.baseline import from_document as baseline_from_document
from .core.ledger.baseline import to_document as baseline_to_document
from .core.ledger.documents import from_document as claim_from_document
from .core.ledger.documents import to_document as claim_to_document
from .core.ledger.drafts import ReviewDraft
from .core.ledger.drafts import from_document as draft_from_document
from .core.ledger.drafts import to_document as draft_to_document
from .core.ledger.judgements import Judgement
from .core.ledger.judgements import from_document as judgement_from_document
from .core.ledger.judgements import to_document as judgement_to_document
from .core.ledger.pages import PageRecord
from .core.ledger.pages import from_document as page_from_document
from .core.ledger.pages import to_document as page_to_document
from .core.ledger.schema import Claim
from .core.ledger.store import require_scheduled
from .core.wiki.client import slug_for

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pymongo.collection import Collection
    from pymongo.database import Database

DEFAULT_URI = "mongodb://127.0.0.1:27017"
DEFAULT_DB = "continuity"

PAGES = "pages"
CLAIMS = "claims"
SECTIONS = "sections"
JUDGEMENTS = "judgements"
DRAFTS = "drafts"


def mongo_uri() -> str:
    return os.environ.get("MONGO_URI") or DEFAULT_URI


def mongo_db_name() -> str:
    return os.environ.get("MONGO_DB") or DEFAULT_DB


def connect(uri: str | None = None, *, db_name: str | None = None) -> Database[dict[str, Any]]:
    """One client, one database.

    The driver is imported here rather than at module top for the same reason every other
    vendor import is deferred (`AGENTS.md` §7): a cold container must be able to serve
    `index.html` without paying for it.

    `serverSelectionTimeoutMS` is short and the ping is eager, because the failure this makes
    legible — mongod is not running — is otherwise reported thirty seconds later at whatever
    line happened to touch the database first.
    """
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    resolved = uri or mongo_uri()
    client: MongoClient[dict[str, Any]] = MongoClient(
        resolved, serverSelectionTimeoutMS=2000, tz_aware=True
    )
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        raise RuntimeError(
            f"cannot reach MongoDB at {resolved}: {exc}. "
            "Start it with `./scripts/mongo.sh start`."
        ) from exc
    return client[db_name or mongo_db_name()]


def _aware(value: Any) -> Any:
    """MongoDB hands back naive UTC datetimes unless the client is tz-aware; belt and braces.

    A naive datetime compares wrong against an aware one and raises rather than silently
    misordering, which is the good failure — but only if it never happens, so normalise here.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _restore(doc: dict[str, Any]) -> dict[str, Any]:
    """Strip `_id` and re-attach timezones, leaving exactly what the codec expects."""
    return {key: _aware(value) for key, value in doc.items() if key != "_id"}


class MongoClaimStore:
    """`ClaimStore` over one collection. Identity is `claim_id`, in `_id`.

    **`scope` seals a run off from every other one — added Sept 1, 2026.** Given a task id,
    every read filters on it and every write stamps it, so a run sees only the claims it
    proposed and nothing a previous run did to the ledger can reach it. Unscoped, the store
    behaves as it always did and sees everything, which is what `/api/state` and the ledger
    view want.

    **This is a deliberate trade and it costs the thing the ledger was for.** The decay ladder,
    "have I already checked this?", and a claim's history across ticks are all cross-run
    memory, and a scoped run has none of them: it proposes fresh claims, researches them once,
    and its schedule dies with it. What it buys is a demo that behaves the same on the tenth
    press as on the first — a previous run settling a claim to 90 days out cannot leave the
    next one with nothing to do. Reasoning: `summary.md` §10, "Runs are sealed".
    """

    def __init__(
        self, db: Database[dict[str, Any]] | None = None, *, scope: str = ""
    ) -> None:
        self.db = db if db is not None else connect()
        self.scope = scope
        self.col: Collection[dict[str, Any]] = self.db[CLAIMS]
        # The one index the due query needs. Single field, for the reason in the module
        # docstring: a composite index is something Firestore would demand be declared.
        self.col.create_index("next_check_at")

    def _where(self, **terms: Any) -> dict[str, Any]:
        """A query, narrowed to this run when there is one."""
        return {**terms, "task_id": self.scope} if self.scope else dict(terms)

    def get(self, claim_id: str) -> Claim | None:
        doc = self.col.find_one(self._where(_id=claim_id))
        return claim_from_document(_restore(doc)) if doc else None

    def put(self, claim: Claim) -> None:
        stored = require_scheduled(claim)
        if self.scope and not stored.task_id:
            stored = replace(stored, task_id=self.scope)
        document = claim_to_document(stored)
        self.col.replace_one({"_id": stored.claim_id}, {"_id": stored.claim_id, **document},
                             upsert=True)

    def put_all(self, claims: Iterable[Claim]) -> None:
        for claim in claims:
            self.put(claim)

    def due(self, now: datetime, *, limit: int | None = None) -> tuple[Claim, ...]:
        cursor = self.col.find(self._where(next_check_at={"$lte": now})).sort(
            [("next_check_at", 1), ("_id", 1)]
        )
        if limit is not None:
            cursor = cursor.limit(limit)
        return tuple(claim_from_document(_restore(doc)) for doc in cursor)

    def all(self) -> tuple[Claim, ...]:
        cursor = self.col.find(self._where()).sort([("_id", 1)])
        return tuple(claim_from_document(_restore(doc)) for doc in cursor)

    def for_page(self, page: str) -> tuple[Claim, ...]:
        cursor = self.col.find(self._where(page=page)).sort([("_id", 1)])
        return tuple(claim_from_document(_restore(doc)) for doc in cursor)

    def next_claim_id(self) -> str:
        """Max-plus-one, never count-plus-one: a removed claim must not free its number for a
        different claim to inherit (`AGENTS.md` §7)."""
        highest = 0
        for doc in self.col.find({}, {"_id": 1}):
            raw = str(doc["_id"]).removeprefix("claim-")
            if raw.isdigit():
                highest = max(highest, int(raw))
        return f"claim-{highest + 1:04d}"


class MongoPageStore:
    """`PageStore` over one collection, keyed by slug. This is where a run gets its number.

    `open_run` is a single `find_one_and_update`: `$inc` allocates the ordinal server-side and
    `$setOnInsert` writes the record the first time anyone runs on the page, so two presses
    that arrive together take two different numbers rather than both reading 2 and both
    writing 3. That atomicity is the reason the *counter* is stored and the run id is not —
    the id is derived from the counter, so there is nothing left to write back afterwards and
    no second round trip that could fail on its own (`core/ledger/pages.py`).

    No index and no `create_index`: every query here is by `_id`.
    """

    def __init__(self, db: Database[dict[str, Any]] | None = None) -> None:
        self.db = db if db is not None else connect()
        self.col: Collection[dict[str, Any]] = self.db[PAGES]

    def get(self, page: str) -> PageRecord | None:
        doc = self.col.find_one({"_id": slug_for(page)})
        return page_from_document(_restore(doc)) if doc else None

    def open_run(self, page: str, *, now: datetime) -> PageRecord:
        from pymongo import ReturnDocument

        # The created half of the document comes from the codec rather than being spelled out
        # here, so a field added to `to_document` is a field a new page gets. The two the
        # operators below own are dropped, because MongoDB refuses an update naming one field
        # in two operators.
        seed = page_to_document(PageRecord(page=page, created_at=now))
        seed.pop("runs")
        seed.pop("last_run_at")
        doc = self.col.find_one_and_update(
            {"_id": slug_for(page)},
            {"$inc": {"runs": 1}, "$set": {"last_run_at": now}, "$setOnInsert": seed},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        # `upsert=True` with `ReturnDocument.AFTER` always answers with a document: there is no
        # path where the record was neither found nor created. Asserted rather than branched,
        # because a `None` here would be the driver breaking its own contract, and inventing a
        # record to return would hand a second run the number the first one took.
        assert doc is not None
        return page_from_document(_restore(doc))

    def all(self) -> tuple[PageRecord, ...]:
        cursor = self.col.find().sort([("_id", 1)])
        return tuple(page_from_document(_restore(doc)) for doc in cursor)


class MongoBaselineStore:
    """`BaselineStore`. A page's sections are one set: replaced together, never merged.

    Merging is the bug this shape prevents — indices are only meaningful relative to each
    other, so inserting a heading at the top renumbers everything below it, and a merge would
    file one section's text under another's index.
    """

    def __init__(self, db: Database[dict[str, Any]] | None = None) -> None:
        self.db = db if db is not None else connect()
        self.col: Collection[dict[str, Any]] = self.db[SECTIONS]
        self.col.create_index("page")

    def for_page(self, page: str) -> tuple[SectionBaseline, ...]:
        cursor = self.col.find({"page": page}).sort([("section_index", 1)])
        return tuple(baseline_from_document(_restore(doc)) for doc in cursor)

    def replace_page(self, page: str, sections: Iterable[SectionBaseline]) -> None:
        rows = [baseline_to_document(section) for section in sections]
        self.col.delete_many({"page": page})
        if rows:
            self.col.insert_many([{"_id": row["key"], **row} for row in rows])

    def pages(self) -> tuple[str, ...]:
        return tuple(sorted(str(page) for page in self.col.distinct("page")))


class MongoJudgementStore:
    """`JudgementStore`. Append-only in practice; `_id` is the judgement's own id, so
    re-running the same task, claim and attempt corrects one row instead of adding a second."""

    def __init__(self, db: Database[dict[str, Any]] | None = None) -> None:
        self.db = db if db is not None else connect()
        self.col: Collection[dict[str, Any]] = self.db[JUDGEMENTS]
        self.col.create_index("task_id")
        self.col.create_index("claim_id")

    def put(self, judgement: Judgement) -> None:
        document = judgement_to_document(judgement)
        self.col.replace_one(
            {"_id": judgement.judgement_id},
            {"_id": judgement.judgement_id, **document},
            upsert=True,
        )

    def all(self) -> tuple[Judgement, ...]:
        cursor = self.col.find().sort([("decided_at", 1), ("_id", 1)])
        return tuple(judgement_from_document(_restore(doc)) for doc in cursor)

    def for_task(self, task_id: str) -> tuple[Judgement, ...]:
        cursor = self.col.find({"task_id": task_id}).sort([("_id", 1)])
        return tuple(judgement_from_document(_restore(doc)) for doc in cursor)

    def for_claim(self, claim_id: str) -> tuple[Judgement, ...]:
        cursor = self.col.find({"claim_id": claim_id}).sort([("_id", 1)])
        return tuple(judgement_from_document(_restore(doc)) for doc in cursor)


class MongoDraftStore:
    """`DraftStore`. One document per run, which is what `published_at` is a property of."""

    def __init__(self, db: Database[dict[str, Any]] | None = None) -> None:
        self.db = db if db is not None else connect()
        self.col: Collection[dict[str, Any]] = self.db[DRAFTS]
        self.col.create_index("published_at")

    def get(self, draft_id: str) -> ReviewDraft | None:
        doc = self.col.find_one({"_id": draft_id})
        return draft_from_document(_restore(doc)) if doc else None

    def put(self, draft: ReviewDraft) -> None:
        document = draft_to_document(draft)
        self.col.replace_one({"_id": draft.draft_id}, {"_id": draft.draft_id, **document},
                             upsert=True)

    def all(self) -> tuple[ReviewDraft, ...]:
        cursor = self.col.find().sort([("_id", 1)])
        return tuple(draft_from_document(_restore(doc)) for doc in cursor)

    def unpublished(self) -> tuple[ReviewDraft, ...]:
        """Filtered in Python rather than in the query, matching the Firestore adapter: a
        filter plus a sort is what needs a composite index there, and the emulator does not
        enforce that requirement, so it would fail only in production."""
        return tuple(draft for draft in self.all() if draft.published_at is None)
