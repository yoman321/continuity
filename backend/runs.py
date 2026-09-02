"""Runs started from the page, and watched while they happen.

Until now a run was a command somebody typed and the gate met its output afterwards, so the
verify view's stage rail described a finished run — its own comment said a rail that animated a
run nobody performed "would be the most convincing lie on the page". This is the live run that
makes the rail honest: the reader presses a button on the article, a run starts, and the popup
watches it advance stage by stage.

**Progress is read, not reported.** `Run.visited` already records each stage as it completes,
so this holds the `Run` object and reads that list from the polling thread rather than
threading a callback through six stages. Nothing in the pipeline had to learn it is being
watched, which is the same rule the stages follow about the orchestrator (`AGENTS.md` §7).

**One run at a time, and that is a cost guard rather than a concurrency shortcut.** A run
spends one Parallel search per due claim and several model calls; `AGENTS.md` §2 requires the
scheduled trigger to authenticate because "an unguarded tick route is a live credit leak the
moment the URL is published", and a button that starts a run has the same shape. Refusing a
second run while one is in flight bounds what a page-load loop or an impatient reader can
spend. Deployed on a public URL this needs the same shared-secret treatment the tick has —
that is written up rather than done here, because the demo runs on localhost.

**The registry is process-local and dies with the container, but the id is not.** A run is
ephemeral by design: what has to survive it is the `ReviewDraft` in Mongo, which is exactly
what Verify writes and what the gate re-opens. A run whose process died is a run whose draft
either exists or does not, and neither answer needs a registry to hold it. What *is* durable
is the run's identity — `run-Gambit-0003`, allocated from the page's own record before the
thread starts (`core/ledger/pages.py`) — so the id in this handle, the `task_id` on every
claim the run proposed and the draft it ends with are one string. This module no longer mints
anything: the caller passes the id in, because only the caller knows the page.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

#: Stage names in the order a run visits them, matching `agent/graph.STAGES`. Duplicated as
#: strings rather than imported, because importing the graph would drag ADK-era vendor imports
#: into module scope and break the cold-start rule (`AGENTS.md` §7); a test pins them equal.
STAGES = ("audit", "research", "classify", "draft", "diff", "verify")


@dataclass
class RunHandle:
    """One run in flight, as the popup sees it."""

    run_id: str
    page: str
    #: This run's number on its page — 3 for `run-Gambit-0003`. Counts attempts rather than
    #: successes, so a failed run still spent one (`core/ledger/pages.py`).
    ordinal: int
    live: bool
    started_at: datetime
    #: The `Run` object itself, so `visited` can be read while it works. `None` until the
    #: worker has built it, which is why `stages_done` tolerates that.
    run: Any = None
    finished: bool = False
    error: str = ""
    draft_id: str = ""
    #: Claims this run proposed for itself before Audit ran.
    proposed: int = 0
    #: Anything worth telling the reader that is not fatal — a section whose proposal could
    #: not be read back, most often.
    notes: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def stages_done(self) -> list[str]:
        visited = getattr(self.run, "visited", None)
        return list(visited) if visited else []

    @property
    def current(self) -> str:
        """The stage being worked on: the one after the last completed, or `""` when done."""
        if self.finished:
            return ""
        done = len(self.stages_done)
        return STAGES[done] if done < len(STAGES) else STAGES[-1]

    def payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "page": self.page,
            "ordinal": self.ordinal,
            "live": self.live,
            "started_at": self.started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stages": list(STAGES),
            "stages_done": self.stages_done,
            "current": self.current,
            "finished": self.finished,
            "error": self.error,
            "draft_id": self.draft_id,
            "proposed": self.proposed,
            "notes": list(self.notes),
            "report": self.report,
        }


class Registry:
    """Every run this process has started. One may be in flight at a time."""

    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}
        self._lock = threading.Lock()

    def in_flight(self) -> RunHandle | None:
        with self._lock:
            for handle in self._runs.values():
                if not handle.finished:
                    return handle
        return None

    def get(self, run_id: str) -> RunHandle | None:
        with self._lock:
            return self._runs.get(run_id)

    def start(
        self,
        page: str,
        *,
        live: bool,
        work: Any,
        run_id: str,
        ordinal: int,
        started_at: datetime | None = None,
    ) -> RunHandle:
        """Begin a run in a worker thread and hand back its handle immediately.

        `work` is a callable taking the handle — the caller supplies it so this module never
        imports the graph, the stores or a vendor SDK, which is what keeps it importable at
        module scope in `app.py` (`AGENTS.md` §7). `run_id` and `ordinal` come from the page's
        record for the same reason: reaching the page store from here would be that import.

        `started_at` is the caller's clock rather than this one's, because the page record was
        stamped with it a moment ago and two clocks for one run is two answers to when it began.
        """
        handle = RunHandle(
            run_id=run_id,
            page=page,
            ordinal=ordinal,
            live=live,
            started_at=started_at or datetime.now(timezone.utc),
        )
        with self._lock:
            self._runs[handle.run_id] = handle

        def worker() -> None:
            try:
                work(handle)
            except Exception as exc:
                # Broad on purpose: this is the top of a thread, so an exception that escapes
                # is one nobody would ever see. It becomes the run's reported error instead,
                # which is what the popup shows rather than spinning forever.
                handle.error = f"{type(exc).__name__}: {exc}"
            finally:
                handle.finished = True

        threading.Thread(target=worker, name=handle.run_id, daemon=True).start()
        return handle


#: Process-wide, like the runs it holds.
RUNS = Registry()
