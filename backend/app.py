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
MongoDB or Firestore; both hold the same documents.

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
    Change,
    Decision,
    DraftError,
    DraftStore,
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

    `DRAFT_STORE=firestore` selects Firestore, anything else the local MongoDB — one switch,
    read per call so a test can set it, and both sides hold the identical documents
    (`core/ledger/drafts.py`). Each driver is imported inside the branch that uses it, because
    a cold container must not pay for an import it will not use.

    There is no file fallback and no in-memory one: the ledger requires a running database
    (`AGENTS.md` §2, waived from `CLAUDE.md` §3 on Sept 1, 2026). If mongod is down this
    raises, which is the honest answer — a gate that silently served an empty queue would look
    like a run that proposed nothing.
    """
    if os.environ.get("DRAFT_STORE", "mongo").strip().lower() == "firestore":
        from .firestore import FirestoreDraftStore

        return FirestoreDraftStore(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
    from .mongo import MongoDraftStore

    return MongoDraftStore()


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


#: Page provenance — title, slug, and how far the live wiki has drifted from the seed. Read
#: from the committed manifest rather than from the ledger, because it is a fact about the
#: corpus rather than about a run, and it is what the article view's nav and meta line show.
MANIFEST = REPO_ROOT / "snapshots" / "manifest.json"


def pages_payload(tracked: tuple[str, ...]) -> dict[str, Any]:
    """The monitored pages, keyed by slug, for the nav and the page meta line.

    No `sections`: the article view reads its text from the browser's own wiki, so shipping
    wikitext here would be a second copy of the same bytes, immediately able to disagree with
    the one on screen.
    """
    import json as _json

    manifest = _json.loads(MANIFEST.read_text(encoding="utf-8"))
    seen = set(tracked)
    pages: dict[str, Any] = {}
    for entry in manifest["pages"]:
        if seen and entry["resolved_title"] not in seen:
            continue
        pages[entry["slug"]] = {
            "title": entry["resolved_title"],
            "slug": entry["slug"],
            "pageid": entry["pageid"],
            "revid": entry["seed"]["revid"],
            "timestamp": entry["seed"]["timestamp"],
            "role": entry["role"],
            "seed_size": entry["seed"]["size"],
            "current_size": entry["current"]["size"],
            "drift_pct": entry.get("drift_pct"),
        }
    return pages


def profiles_payload() -> list[dict[str, Any]]:
    """The wikis this build can be pointed at — the plug-and-play surface, off the profiles
    themselves rather than a hand-kept list."""
    from .core.profile import PROFILES

    return [
        {
            "id": key,
            "label": profile.name,
            "api": profile.api_url,
            "article_base": profile.article_base,
            "licence": profile.licence,
            "subpages": profile.subpages,
            "seeded": profile.writable,
        }
        for key, profile in PROFILES.items()
    ]


def claim_payload(claim: Any) -> dict[str, Any]:
    """One claim as the ledger view reads it.

    A *view* payload, not the stored document — `core/ledger/documents.to_document` owns that
    and is Firestore-shaped. This one carries derived fields the browser should not compute
    (`page_slug`, `check_interval_hours`) and matches what `build_demo_state.py` writes, so the
    live route and the fixture stay interchangeable (`AGENTS.md` §7).

    Three fields the fixture carries are absent here and that is correct: `rationale`,
    `conflict_note` and `pending_selection` are demo texture an author wrote, and no run
    produces them. The view renders a claim without them.
    """
    from .core.wiki import slug_for

    def iso(value: datetime | None) -> str | None:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None

    return {
        "claim_id": claim.claim_id,
        "page": claim.page,
        "page_slug": slug_for(claim.page),
        "entity_ref": {
            "title": claim.entity_ref.title,
            "base": claim.entity_ref.base,
            "variant": claim.entity_ref.variant,
        },
        "kind": claim.kind.value,
        "wave": claim.wave.value,
        "text": claim.text,
        "wikitext_anchor": claim.wikitext_anchor,
        "section_index": claim.section_index,
        "section_heading": claim.section_heading or "(lead)",
        "status": claim.status.value,
        "confidence": claim.confidence,
        "auto_appliable": claim.auto_appliable,
        "objective": claim.objective,
        "research_rounds": claim.research_rounds,
        "last_verified": iso(claim.last_verified),
        "next_check_at": iso(claim.next_check_at),
        "check_interval_hours": round(claim.check_interval.total_seconds() / 3600),
        "sources": [
            {"url": s.url, "domain": s.domain, "tier": s.tier, "excerpt": s.excerpt,
             "as_of": iso(s.as_of)}
            for s in claim.sources
        ],
        "contradictions": [
            {"note": c.note, "source_a": c.source_a, "source_b": c.source_b}
            for c in claim.contradicts
        ],
        # The fixture carries these three and the view reads them, so they are emitted rather
        # than omitted — a live payload that is missing keys the fixture has is a shape the
        # frontend renders `undefined` into. `conflict_note` is real and derived from the
        # claim's own contradiction; the other two are demo texture no run produces, so they
        # are honestly empty rather than invented.
        "conflict_note": claim.contradicts[0].note if claim.contradicts else "",
        "rationale": "",
        "pending_selection": None,
    }


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    """The agent's own state: what it tracks, and the pages it tracks them on.

    **This serves the agent half only.** The wiki half — page text — lives in the browser
    (`FE/wiki-api.js`), so nothing here carries wikitext: the split is that wiki data ships
    with the frontend and is thrown away on reload, while what the agent decided is real state
    in a real database (`AGENTS.md` §2).

    **It answers from the store or it fails.** 503 when the ledger is unreachable, never the
    fixture: the frontend decides live-vs-fixture from this one response, so serving
    `demo-state.json` from here would put a *live* pill above an agent run that never happened.
    """
    try:
        from .mongo import MongoBaselineStore, MongoClaimStore
    except ImportError as exc:  # pragma: no cover - the driver is a hard dependency
        raise HTTPException(status_code=503, detail=f"No ledger driver: {exc}") from exc

    try:
        claims = MongoClaimStore().all()
        pages_seen = MongoBaselineStore().pages()
    except Exception as exc:
        log.warning("The ledger store is unreachable: %s", exc)
        raise HTTPException(
            status_code=503, detail="The ledger store is unreachable."
        ) from exc

    if not claims and not pages_seen:
        raise HTTPException(
            status_code=503,
            detail="The ledger is empty; run scripts/ingest_baseline.py and seed_claims.py.",
        )

    return {
        "generated_by": "backend/app.py",
        "generated_at": now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stub": False,
        "stub_note": "",
        "profiles": profiles_payload(),
        "pages": pages_payload(pages_seen),
        "claims": [claim_payload(c) for c in claims],
        # The gate reads `/api/drafts`; this key stays so the payload matches the fixture's
        # shape, and the frontend overwrites it the moment a draft loads.
        "queue": [],
        "counts": {"claims": len(claims), "queued": 0},
    }


class StartRun(BaseModel):
    """What a reader may decide when pressing the button on an article.

    Deliberately two fields. `page` is the article they were reading and is required: a run is
    named for its page and its number on that page (`core/ledger/pages.py`), so a run with no
    page has no id and nothing to propose against. `live` is opt-in because a live run spends a
    Parallel search per due claim and several model calls, and a button that bills by default
    is one a page-refresh loop can drain.
    """

    model_config = ConfigDict(extra="forbid")

    page: str
    live: bool = False


@app.post("/api/runs")
def start_run(body: StartRun) -> dict[str, Any]:
    """Start a run on one page and hand back its id, so the popup can watch it.

    **The page is opened before the thread is.** The first run on a page creates that page's
    record; every run after it takes the next number from that record, and the number *is* the
    run's id — `run-Gambit-0003` (`core/ledger/pages.py`). The same string is the `task_id`
    stamped on every claim the run proposes, the scope the ledger is sealed to, and the name of
    the draft it ends with, so a stored claim says which run on which page made it without a
    join. It is allocated here rather than in the worker because the response carries it: the
    popup begins polling before the run has done anything.

    **A page the agent has never read is refused rather than run on.** Claims are proposed
    against a baseline, so a run on a page with no sections would propose nothing, draft
    nothing, and still burn a run number and a page record on a page that does not exist here.

    **One at a time.** A second request while a run is in flight gets the run already going
    rather than starting another — a cost guard, for the same reason `/internal/tick`
    authenticates (`AGENTS.md` §2): a route that starts billable work is a credit leak if
    anything can call it in a loop. Deployed on a public URL this needs the tick's
    shared-secret treatment too; on localhost the single-flight rule is the bound.

    Returns immediately. The run happens on a worker thread and `GET /api/runs/{id}` is how
    its progress is read.
    """
    from .runs import RUNS

    existing = RUNS.in_flight()
    if existing is not None:
        return {**existing.payload(), "already_running": True}

    page = body.page.strip()
    if not page:
        raise HTTPException(status_code=422, detail="A run names the page it runs on.")

    try:
        from .mongo import MongoBaselineStore, MongoPageStore

        # One client for the whole run: every store below is handed this database rather than
        # opening its own, so a run costs one connection instead of four.
        pages = MongoPageStore()
        baseline = MongoBaselineStore(pages.db)
    except RuntimeError as exc:
        # `connect()` pings eagerly, so this is "mongod is not running" and nothing subtler.
        # 503 rather than 500: the same answer `/api/state` gives to the same cause.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not baseline.for_page(page):
        raise HTTPException(
            status_code=404,
            detail=f"No baseline for {page!r}. Run scripts/ingest_baseline.py first.",
        )

    started = now()
    record = pages.open_run(page, now=started)
    task_id = record.last_run_id

    def work(handle: Any) -> None:
        # Imported inside the worker, never at module scope: these drag in the vendor SDKs and
        # a cold container must serve `index.html` without paying for them (`AGENTS.md` §7).
        from .agent.classify import Classifier
        from .agent.draft import Drafter
        from .agent.graph import Run, Stages
        from .agent.model import DEFAULT_CASSETTE, GeminiModel, ModelError, RecordedModel
        from .agent.propose import Proposer, room_left, store_proposals, worth_reading
        from .agent.semantic_diff import Reviewer
        from .agent.tools import Ledger, WebSearch
        from .agent.tools.web_search import RecordedSearch
        from .core.profile import local_wiki
        from .mongo import MongoClaimStore, MongoJudgementStore

        profile = local_wiki(os.environ.get("MEDIAWIKI_API_URL") or "http://localhost/api.php")
        cassette = REPO_ROOT / DEFAULT_CASSETTE
        searches = REPO_ROOT / "fixtures" / "searches.json"
        if handle.live:
            from .agent.tools.web_search import ParallelSearch

            source: Any = ParallelSearch()
            model: Any = GeminiModel()
        else:
            source = RecordedSearch(searches)
            model = RecordedModel(cassette)

        # `task_id` is the run's id, allocated from the page's record before this thread
        # started. Everything below agrees on it: the claims are proposed *into* this run and
        # the store is sealed to it, so a run never sees what an earlier one concluded
        # (`AGENTS.md` §2). Pressing the button twice gives run 3 and run 4 of the same page,
        # independent of each other.
        claims = MongoClaimStore(baseline.db, scope=task_id)

        # -- propose: this run's own claims, from the page the reader was on ----------------
        proposer = Proposer(profile, model)
        proposed = 0
        for section in (s for s in baseline.for_page(page) if worth_reading(s)):
            # Ask before spending: past the page cap every answer is discarded, and a burst
            # of wasted calls is exactly what a rate limit punishes.
            if room_left(claims, page) <= 0:
                break
            try:
                found = proposer.propose(page, section)
            except ModelError as exc:
                handle.notes.append(f"propose {page} §{section.section_index}: {exc}")
                continue
            kept, _ = store_proposals(
                found, page=page, section_text=section.text, profile=profile,
                store=claims, now=started, task_id=task_id,
            )
            proposed += len(kept)
        handle.proposed = proposed

        run = Run(
            Stages(
                profile=profile,
                ledger=Ledger(profile, claims, task_id=task_id),
                baseline=baseline,
                search=WebSearch(profile, source),
                classifier=Classifier(profile, model),
                drafter=Drafter(profile, model),
                reviewer=Reviewer(profile, model),
                drafts=draft_store(),
                judgements=MongoJudgementStore(baseline.db),
            ),
            task_id=task_id,
        )
        # Held before executing, so the poller can read `visited` as the stages complete.
        handle.run = run
        report = run.execute()
        handle.draft_id = report.draft_id or ""
        handle.report = {
            "proposed": proposed,
            "due": report.due,
            "researched": report.researched,
            "rounds": report.rounds,
            "buckets": dict(report.buckets),
            "drafted": report.drafted,
            "unjudged": list(report.unjudged),
            "skipped": list(report.skipped),
        }

    handle = RUNS.start(
        page, live=body.live, work=work,
        run_id=task_id, ordinal=record.runs, started_at=started,
    )
    return {**handle.payload(), "already_running": False}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """How far a run has got. Polled by the popup while the rail advances."""
    from .runs import RUNS

    handle = RUNS.get(run_id)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id!r}")
    return handle.payload()


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


class PublishedEdit(BaseModel):
    """One change's outcome, as the browser reports it.

    Deliberately tiny. The body carries *what happened*, never *where to write* — no page, no
    section, no anchor, no text — so the invariant that made this route safe to leave public
    survives the wiki moving into the browser: the most a stranger who guesses a draft id can
    do is mark a review a person already accepted as published.
    """

    model_config = ConfigDict(extra="forbid")

    edit_id: str
    status: Literal["written", "nochange", "conflict", "missing", "error"]
    revid: int | None = None
    error: str | None = None


class PublishReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[PublishedEdit]


@app.post("/api/drafts/{draft_id}/publish")
def publish_draft(draft_id: str, body: PublishReport) -> dict[str, Any]:
    """Record what the browser wrote, then stamp the draft published.

    **The wiki write does not happen here any more.** The wiki is `FE/wiki-api.js` and lives in
    the browser (`AGENTS.md` §2), so the gate performs each `action=edit` itself and this route
    records the outcome against the stored draft in Mongo. What is still true is the important
    half: a change is only ever marked written if the draft already held it as *accepted*, so a
    body naming an `edit_id` that was rejected, undecided or unknown is refused rather than
    honoured.

    Sequential and non-atomic remains a real outcome: the gate writes one edit at a time and a
    partial failure is reported per change rather than rolled back. `written_revid` is what
    makes pressing publish twice safe — a change that already landed is not offered again.
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

    # Only changes this draft is actually waiting on may be reported. An id that was rejected,
    # already written or never existed is a 422, not a silent no-op — the gate and the store
    # disagreeing about what happened is exactly the bug worth failing on.
    outstanding = {change.edit_id for change in pending}
    unknown = [r.edit_id for r in body.results if r.edit_id not in outstanding]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"not awaiting publication on {draft_id}: {', '.join(sorted(unknown))}",
        )

    results = []
    for reported in body.results:
        if reported.status == "written":
            draft = draft.mark_written(reported.edit_id, reported.revid or 0)
            store.put(draft)
        results.append({
            "edit_id": reported.edit_id,
            "status": reported.status,
            "revid": reported.revid,
            "error": reported.error,
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
