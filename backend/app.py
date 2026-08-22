"""Cloud Run entry point: one process serves `FE/` and runs the agent.

The four routes are the topology in `AGENTS.md` §3 and nothing more. `FE/` is static with no
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

STUB: the three API routes are wired and guarded but have no implementation behind them yet —
there is no Firestore adapter, no publish path and no graph. Each answers with the status that
says so. `/api/state` returning 503 is what makes the frontend fall back to
`FE/data/demo-state.json` and label itself *fixture*; serving the fixture from `/api/state`
instead would make the header pill read *live*, which would be a lie.
"""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# backend/app.py -> the repo root, which is also the container's WORKDIR.
REPO_ROOT = Path(__file__).resolve().parent.parent
FE_DIR = REPO_ROOT / "FE"

#: Header Cloud Scheduler carries the shared secret in. Matched case-insensitively.
TICK_HEADER = "X-Tick-Token"

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


class QueueDecision(BaseModel):
    """A reviewer's verdict on one drafted edit. `approve` is what triggers a wiki write."""

    decision: Literal["approve", "reject"]


@app.get("/api/state")
def get_state() -> Response:
    """Ledger + queue, in the shape `scripts/build_demo_state.py` writes.

    STUB: no Firestore adapter yet. 503 is also the honest answer if the store is unreachable
    later, and the frontend handles both the same way — it falls back to the generated fixture.
    """
    raise HTTPException(
        status_code=503,
        detail="No ledger store configured; the frontend serves FE/data/demo-state.json.",
    )


@app.post("/api/queue/{edit_id}")
def decide_queued_edit(edit_id: str, body: QueueDecision) -> Response:
    """Approve or reject a drafted edit; approval publishes it as `action=edit&section=N`.

    STUB: the publish path does not exist. The route validates the body so the contract the
    frontend codes against is fixed now — an unknown verdict is a 422 here, not a silent
    no-op later.
    """
    raise HTTPException(
        status_code=501,
        detail=f"Publish stage not wired; cannot {body.decision} {edit_id}.",
    )


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
