"""Cloud Run entry point: one process serves `FE/` and runs the agent.

The routes are the topology in `AGENTS.md` §3 and nothing more. `FE/` is static with no
build step, so it is mounted as-is from the same container the agent runs in — no second
origin, no CORS, no second deploy.

Three things here are load-bearing rather than incidental:

* **No vendor SDK is imported at module level.** Cloud Run scales to zero, so a cold container
  pays for every module import before it can serve `index.html` — 5-15s of ADK, `google-genai`
  and `parallel-web` (`AGENTS.md` §7). They are imported inside the handlers that need them,
  which is asserted by `tests/test_app.py` rather than left as an intention.
* **`/internal/tick` authenticates itself.** Judging requires `--allow-unauthenticated`, so IAM
  protects nothing and every route is public — including the one Cloud Scheduler posts to. The
  shared-secret compare below is the only thing between a guessed path and unbounded Gemini
  spend (`AGENTS.md` §2). It fails closed: no token configured means no tick, ever.
* **The interactive docs are off.** With `openapi_url=None` the public surface is exactly the
  routes below, which is the surface the deploy was reasoned about.

The draft routes are backed by a real store (`core/ledger/drafts.py`): the gate fetches a draft
by id, a verdict on one change is persisted as it is given, and publishing writes the accepted
changes to our own MediaWiki and stamps the draft published. `DRAFT_STORE` selects the local
JSON file or Firestore; both hold the same documents.

STUB: there is no graph and no claim-store adapter behind `/api/state`, so it answers 503 — and
that 503 is what makes the frontend fall back to `FE/data/demo-state.json` for the ledger and
page views and label itself *fixture*. Serving that file from `/api/state` would make the header
pill read *live*, which would be a lie. The queue is the exception: it comes from the draft
store, so what the gate shows and decides is real state, not a fixture.
"""

from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

# Pure core, so this costs a few milliseconds of stdlib imports and no vendor SDK.
from .core.ledger.drafts import (
    DEFAULT_DRAFTS_PATH,
    Change,
    Decision,
    DraftError,
    DraftStore,
    JsonFileDraftStore,
    ReviewDraft,
)
from .core.wiki.diff import diff, to_payload

# backend/app.py -> the repo root, which is also the container's WORKDIR.
REPO_ROOT = Path(__file__).resolve().parent.parent
FE_DIR = REPO_ROOT / "FE"

#: Header Cloud Scheduler carries the shared secret in. Matched case-insensitively.
TICK_HEADER = "X-Tick-Token"


#: A section edit is not a book. The decision route is public like everything else here, so
#: this is the bound on what a reviewer's hand-edit can carry into a wiki page.
MAX_DRAFT_CHARS = 20_000

log = logging.getLogger("continuity.app")


def load_dotenv(path: Path | None = None) -> None:
    """Read `.env` into the environment for local runs, without overriding what is set.

    Deployed there is no `.env` — Cloud Run injects the same keys from `--set-env-vars` and
    Secret Manager — so this is a no-op there, and `setdefault` guarantees the real deployment
    values win if a file ever does ship. Twenty lines instead of a dependency (`CLAUDE.md` §6).
    Values are never logged.
    """
    env_file = path if path is not None else REPO_ROOT / ".env"
    try:
        raw = env_file.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, _, value = entry.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


load_dotenv()

app = FastAPI(title="Continuity", openapi_url=None, docs_url=None, redoc_url=None)


class ChangeDecision(BaseModel):
    """A verdict on one change, the reviewer's own text for it, or both.

    Both fields are optional because the gate produces them at different moments: the text is
    saved when the reviewer stops typing, the verdict when they press a button. Sending neither
    is a request that means nothing, and is refused rather than answered with a no-op.

    Extra fields are forbidden, not ignored: nothing in this body may name a page, a section or
    a wiki (`AGENTS.md` §2), and a misspelled field must fail loudly rather than silently
    leaving the stored decision as it was.
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["undecided", "accepted", "rejected"] | None = None
    text: str | None = None


def draft_store() -> DraftStore:
    """The store this deployment reads drafts from.

    `DRAFT_STORE=firestore` selects Firestore, anything else the local JSON file — one switch,
    read per call so a test can set it, and both sides hold the identical documents
    (`core/ledger/drafts.py`). The Firestore adapter is imported inside the branch that uses it,
    because the SDK is not a dependency of the file path and a cold container must not pay for
    an import it will not use.
    """
    if os.environ.get("DRAFT_STORE", "file").strip().lower() == "firestore":
        from .firestore import FirestoreDraftStore

        return FirestoreDraftStore(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
    return JsonFileDraftStore(os.environ.get("DRAFT_STORE_PATH") or REPO_ROOT / DEFAULT_DRAFTS_PATH)


def load_draft(draft_id: str) -> tuple[DraftStore, ReviewDraft]:
    """The store and the draft `draft_id` names. 404 if there is no such draft."""
    store = draft_store()
    draft = store.get(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"No draft {draft_id}.")
    return store, draft


def change_payload(change: Change) -> dict[str, Any]:
    """One card, in the shape `FE/app.js` renders.

    The diff rows are computed here rather than in the browser and rather than stored: the core
    owns the derivation, so what a reviewer sees and what a test asserts cannot disagree
    (`AGENTS.md` §4), and a stored diff would be a view of text that has since been edited.
    """
    return {
        "edit_id": change.edit_id,
        "claim_id": change.claim_id,
        "page": change.page,
        "page_slug": change.page_slug,
        "section_index": change.section_index,
        # "(lead)" is a label, not a heading. The index is what says which section it is, and
        # the publish path below reads the index rather than this string.
        "section_heading": change.section_heading or "(lead)",
        "before": change.before,
        "after": change.after,
        "diff": to_payload(diff(change.before, change.after)),
        "summary": change.summary,
        "rationale": change.rationale,
        "confidence": change.confidence,
        "citation": change.citation,
        "bucket": change.bucket,
        "conflict": change.conflict,
        "conflict_sources": list(change.conflict_sources),
        "flags": list(change.flags),
        "decision": change.decision.value,
        "written_revid": change.written_revid,
    }


def draft_payload(draft: ReviewDraft) -> dict[str, Any]:
    """A whole draft: its changes, and the flags the gate reads."""
    return {
        "draft_id": draft.draft_id,
        "wiki": draft.wiki,
        "created_at": draft.created_at.isoformat(),
        "published": draft.published,
        "published_at": draft.published_at.isoformat() if draft.published_at else None,
        "is_decided": draft.is_decided,
        "changes": [change_payload(c) for c in draft.changes],
        "counts": {
            "changes": len(draft.changes),
            "accepted": len(draft.accepted),
            "undecided": len(draft.undecided),
            "written": sum(1 for c in draft.changes if c.written),
        },
    }


@app.get("/api/state")
def get_state() -> Response:
    """Ledger + page text, in the shape `scripts/build_demo_state.py` writes.

    STUB: no claim-store adapter yet. 503 is also the honest answer if the store is unreachable
    later, and the frontend handles both the same way — it falls back to the generated fixture
    and labels itself. The *queue* no longer comes from here: the gate reads `/api/drafts`.
    """
    raise HTTPException(
        status_code=503,
        detail="No ledger store configured; the frontend serves FE/data/demo-state.json.",
    )


@app.get("/api/drafts")
def list_drafts() -> dict[str, Any]:
    """Every draft, newest first, with the counts the gate needs to pick one.

    Summaries rather than whole drafts: the changes are what make a draft big, and a list that
    carried them would make opening the gate pay for every run ever made.
    """
    drafts = draft_store().all()
    return {
        "drafts": [
            {
                "draft_id": d.draft_id,
                "wiki": d.wiki,
                "created_at": d.created_at.isoformat(),
                "published": d.published,
                "is_decided": d.is_decided,
                "counts": {
                    "changes": len(d.changes),
                    "accepted": len(d.accepted),
                    "undecided": len(d.undecided),
                },
            }
            for d in drafts
        ]
    }


@app.get("/api/drafts/{draft_id}")
def get_draft(draft_id: str) -> dict[str, Any]:
    """One draft, fetched back exactly as it was left — verdicts, hand-edits and all."""
    _, draft = load_draft(draft_id)
    return draft_payload(draft)


@app.post("/api/drafts/{draft_id}/changes/{edit_id}")
def decide_change(draft_id: str, edit_id: str, body: ChangeDecision) -> dict[str, Any]:
    """Record a verdict on one change, the reviewer's text for it, or both.

    Persisted as it is given rather than accumulated in the browser, which is the point of the
    store: a reviewer who reloads the popup finds the run where they left it, and a card they
    discarded is not offered again. Writing nothing to the wiki, ever — publishing is a separate
    act over the accepted set (`AGENTS.md` §2).
    """
    if body.decision is None and body.text is None:
        raise HTTPException(status_code=422, detail="Send a decision, a text, or both.")
    if body.text is not None and len(body.text) > MAX_DRAFT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"That replacement is longer than {MAX_DRAFT_CHARS} characters.",
        )

    store, draft = load_draft(draft_id)
    try:
        if body.text is not None:
            draft = draft.revise(edit_id, body.text)
        if body.decision is not None:
            draft = draft.decide(edit_id, Decision(body.decision))
    except DraftError as exc:
        # A published draft or an unknown change: both are "that is not a thing you can do to
        # this draft", and the message says which.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    store.put(draft)
    change = draft.change(edit_id)
    assert change is not None  # decide/revise raised above if it were missing
    return {"draft_id": draft_id, "change": change_payload(change), "published": draft.published}


@app.post("/api/drafts/{draft_id}/publish")
def publish_draft(draft_id: str) -> dict[str, Any]:
    """Write every accepted change that is not on the wiki yet, then stamp the draft published.

    **The request body is empty, and that is the security property.** Judging requires
    `--allow-unauthenticated`, so this route is public and there is no session to identify a
    reviewer by. Nothing in the request decides what is written or where: the changes, their
    text, their pages and their verdicts all come from the stored draft, and
    `MediaWikiWriter.for_profile` refuses any profile but our own seeded instance. The most a
    stranger who guesses a draft id can do is publish a review a person already accepted.

    Sequential, one `action=edit` per change, because MediaWiki has no cross-page transaction —
    so a partial failure is a real outcome and is reported as one rather than rolled back. Each
    success is stored before the next write starts, so a crash mid-publish loses nothing and the
    retry writes only what is still outstanding: `written_revid` is what makes publishing safe
    to press twice.
    """
    store, draft = load_draft(draft_id)
    if draft.published:
        raise HTTPException(status_code=409, detail=f"{draft_id} is already published.")
    if not draft.is_decided:
        raise HTTPException(
            status_code=409,
            detail=f"{len(draft.undecided)} change(s) still undecided; the gate opens once "
            f"every card has a verdict.",
        )
    pending = draft.publishable
    if not pending:
        raise HTTPException(
            status_code=409, detail=f"{draft_id} has no accepted change left to write."
        )

    api_url = os.environ.get("MEDIAWIKI_API_URL", "")
    api_key = os.environ.get("MEDIAWIKI_API_KEY", "")
    user = os.environ.get("MEDIAWIKI_BOT_USER", "")
    password = os.environ.get("MEDIAWIKI_BOT_PASSWORD", "")
    if not (api_url and api_key and user and password):
        log.error("A publish arrived but the wiki write credentials are not configured.")
        raise HTTPException(status_code=503, detail="Wiki writes are not configured.")

    # Imported here, never at module level: this drags in the profiles and the HTTP adapters,
    # and a cold container must not pay for them before it can serve `index.html`.
    from .agent.tools import WikiWrite
    from .core.profile import local_wiki
    from .core.wiki import WikiError

    try:
        tool = WikiWrite.live(local_wiki(api_url), api_key=api_key)
        # Once for the whole draft; the session is reused across every write below.
        tool.login(user, password)
    except WikiError as exc:
        log.warning("Could not open a wiki session for %s: %s", draft_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    results = []
    for change in pending:
        try:
            outcome = tool.write_anchor(
                change.page,
                # The lead is index 0 and has no heading of its own.
                "" if change.section_index == 0 else change.section_heading,
                change.before,
                change.after,
                change.summary,
            )
        except WikiError as exc:  # pragma: no cover - the tool returns rather than raises
            outcome = {"status": "error", "error": str(exc)}

        if outcome.get("status") == "written":
            draft = draft.mark_written(change.edit_id, int(outcome.get("new_revid") or 0))
            store.put(draft)
        results.append({
            "edit_id": change.edit_id,
            "page": change.page,
            "status": str(outcome.get("status", "error")),
            "revid": outcome.get("new_revid"),
            "error": str(outcome["error"]) if outcome.get("error") else None,
        })

    draft = draft.settled(now())
    store.put(draft)
    return {
        "draft_id": draft_id,
        "published": draft.published,
        "results": results,
        "draft": draft_payload(draft),
    }


def now() -> datetime:
    """UTC, aware. Firestore stores an instant, and a naive one compares wrong."""
    return datetime.now(timezone.utc)


@app.post("/internal/tick")
def tick(request: Request) -> Response:
    """Hourly Cloud Scheduler hook: pick up claims whose `next_check_at` has passed.

    The token compare happens before any work, on every path. Fails closed when `TICK_TOKEN`
    is unset, because an unguarded tick on a public URL is a live credit leak (`AGENTS.md` §2).
    """
    expected = os.environ.get("TICK_TOKEN", "")
    if not expected:
        log.error("TICK_TOKEN is not set; refusing to tick.")
        raise HTTPException(status_code=503, detail="Tick is not configured.")

    provided = request.headers.get(TICK_HEADER)
    if provided is None or not hmac.compare_digest(provided.encode(), expected.encode()):
        log.warning("Rejected a tick with a bad or missing %s header.", TICK_HEADER)
        raise HTTPException(status_code=401, detail="Bad or missing tick token.")

    # STUB: authenticated, but there is no graph to run yet. ADK gets imported *here* when
    # there is — never at module level.
    raise HTTPException(status_code=501, detail="Agent graph not wired.")


# Mounted last: Starlette matches in order, so this must not shadow the routes above.
# `html=True` serves index.html at `/`; the frontend's own routes are hash fragments, so the
# server never sees them.
app.mount("/", StaticFiles(directory=FE_DIR, html=True), name="frontend")
