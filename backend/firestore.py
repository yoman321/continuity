"""Firestore behind the `DraftStore` protocol — the transport, and nothing else.

The shape a draft is stored in belongs to `core/ledger/drafts.py`, which emits only the value
types Firestore's document model accepts, so this adapter hands `to_document` straight to
`.set()` and reads `.to_dict()` straight back. That is the whole port: no field is named twice
and no logic lives here, which is what makes the local JSON store a rehearsal for this one
rather than a stand-in for it.

**The SDK is imported inside the constructor.** `backend/app.py` must not pull a vendor package
at module import — a cold Cloud Run container pays for it before it can serve `index.html`
(`AGENTS.md` §7) — and `google-cloud-firestore` is not a dependency yet, so importing it at
module level would break every run that uses the file store. A caller may also pass its own
`client`, which is how the tests exercise the wire without a database or the SDK.

STUB: not yet run against a real Firestore or the emulator — the emulator needs a JRE plus
`gcloud components install cloud-firestore-emulator` (`summary.md` §10). What *is* verified is
the document that goes on the wire and the calls made to put it there, which is the half this
module owns; `DRAFT_STORE=file` remains the default until it has been run for real.
"""

from __future__ import annotations

from typing import Any

from .core.ledger.drafts import ReviewDraft, from_document, to_document

#: One collection, keyed by `draft_id`. Named here rather than passed around, so a deployment
#: cannot end up reading one collection and writing another.
COLLECTION = "drafts"


class FirestoreDraftStore:
    """`DraftStore` over a Firestore collection.

    Ordering is done in Python rather than with `order_by`, deliberately: the query would need a
    composite index for `unpublished()`, the emulator does not enforce index requirements, and a
    missing index fails *only* in production — the same trap the claim store's due query avoids
    (`AGENTS.md` §6). One wiki's drafts are a handful of documents, so the sort is free.
    """

    def __init__(
        self, *, project: str | None = None, collection: str = COLLECTION, client: Any = None
    ) -> None:
        if client is None:
            # Imported here, not at module level — see the module docstring.
            # Untyped at the perimeter, relaxed here rather than globally (`pyproject.toml`).
            from google.cloud import firestore  # type: ignore[import-untyped]

            client = firestore.Client(project=project)
        self._collection = client.collection(collection)

    def get(self, draft_id: str) -> ReviewDraft | None:
        snapshot = self._collection.document(draft_id).get()
        if not snapshot.exists:
            return None
        return from_document(snapshot.to_dict())

    def put(self, draft: ReviewDraft) -> None:
        self._collection.document(draft.draft_id).set(to_document(draft))

    def all(self) -> tuple[ReviewDraft, ...]:
        drafts = [from_document(s.to_dict()) for s in self._collection.stream()]
        return tuple(sorted(drafts, key=lambda d: (-d.created_at.timestamp(), d.draft_id)))

    def unpublished(self) -> tuple[ReviewDraft, ...]:
        return tuple(d for d in self.all() if not d.published)
