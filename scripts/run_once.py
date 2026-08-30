#!/usr/bin/env python3
"""Run the graph once: due claims in, one reviewable draft out.

This is the tick, by hand. It joins the six stages that run before the human — Audit,
Research, Classify, Draft, Diff, Verify — as the ADK `Workflow` in `backend/agent/graph.py`,
and stops where the architecture says to stop: with a `ReviewDraft` in the store and nothing
written to the wiki. Publishing is the gate's button, not this script.

    python3 scripts/ingest_baseline.py     # what the pages say
    python3 scripts/seed_claims.py         # what the agent is tracking
    python3 scripts/run_once.py            # replayed: no key, no network, no billing
    python3 scripts/run_once.py --live     # Parallel and Gemini for real — this spends money
    python3 scripts/run_once.py --live --record   # ...and record both cassettes for replay
    python3 scripts/run_once.py --limit 1          # one claim
    python3 scripts/run_once.py --no-graph         # the same stages in order, without ADK

**A fresh clone cannot replay.** Both cassettes are gitignored — they carry third-party web
excerpts — so the first run has to be `--live --record`, after which the replayed run is
byte-for-byte reproducible. A replay whose prompt or queries have changed since the recording
*misses* rather than silently serving the old answer, which is the failure a deterministic
fallback is most likely to hide (`AGENTS.md` §7).

Live needs `PARALLEL_API_KEY` in `.env` and ADC for Gemini (`gcloud auth application-default
login`); there is no Gemini API key on either side.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agent.classify import Classifier  # noqa: E402
from backend.agent.draft import Drafter  # noqa: E402
from backend.agent.graph import RunReport, Stages, run, straight_through  # noqa: E402
from backend.agent.model import (  # noqa: E402
    DEFAULT_CASSETTE,
    GeminiModel,
    ModelRequest,
    ModelSource,
    RecordedModel,
    record,
)
from backend.agent.semantic_diff import Reviewer  # noqa: E402
from backend.agent.tools import Ledger, WebSearch  # noqa: E402
from backend.agent.tools.web_search import (  # noqa: E402
    ParallelSearch,
    RecordedSearch,
    SearchOutcome,
    SearchRequest,
    SearchSource,
)
from backend.core.ledger.baseline import DEFAULT_BASELINE_PATH, JsonFileBaselineStore  # noqa: E402
from backend.core.ledger.drafts import (  # noqa: E402
    DEFAULT_DRAFTS_PATH,
    DraftStore,
    JsonFileDraftStore,
)
from backend.core.ledger.judgements import (  # noqa: E402
    DEFAULT_JUDGEMENTS_PATH,
    JsonFileJudgementStore,
    JudgementStore,
)
from backend.core.ledger.store import DEFAULT_LEDGER_PATH  # noqa: E402
from backend.core.profile import local_wiki  # noqa: E402

DEFAULT_SEARCHES = Path("fixtures") / "searches.json"

#: The graph reads sections from the baseline and writes to the draft store, so it never opens
#: the wiki. The profile still needs an endpoint; this one is a placeholder and stays one.
API_URL = "http://wiki.invalid/api.php"


def load_env(path: Path) -> None:
    """Read `.env` without overriding what is already set. Same rule as `backend/app.py`."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class RecordingSearch:
    """A live search that writes what it got to the cassette on the way past."""

    def __init__(self, inner: SearchSource, path: Path) -> None:
        self.inner = inner
        self.path = path

    def run(self, request: SearchRequest) -> SearchOutcome:
        outcome = self.inner.run(request)
        RecordedSearch.record(self.path, request, outcome)
        return outcome


class RecordingModel:
    """The same, for judgements. Keyed on instruction + prompt + schema, like the reader."""

    def __init__(self, inner: ModelSource, path: Path) -> None:
        self.inner = inner
        self.path = path

    def run(self, request: ModelRequest) -> str:
        answer = self.inner.run(request)
        record(self.path, request, answer)
        return answer


def on_firestore() -> bool:
    """`DRAFT_STORE` picks the backend for *every* document store a run writes, not only the
    drafts one. One switch, because a run that put its judgements in a file and its draft in
    Firestore would have written half its provenance somewhere nothing reads."""
    return os.environ.get("DRAFT_STORE", "file").strip().lower() == "firestore"


def draft_store() -> DraftStore:
    """The same switch `backend/app.py` and `seed_drafts.py` read, so a run and the gate that
    reviews it never disagree about where drafts live."""
    if on_firestore():
        from backend.firestore import FirestoreDraftStore

        return FirestoreDraftStore(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
    return JsonFileDraftStore(os.environ.get("DRAFT_STORE_PATH") or REPO_ROOT / DEFAULT_DRAFTS_PATH)


def judgement_store() -> JudgementStore:
    """Where classify writes what it decided, and why."""
    if on_firestore():
        from backend.firestore import FirestoreJudgementStore

        return FirestoreJudgementStore(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
    return JsonFileJudgementStore(REPO_ROOT / DEFAULT_JUDGEMENTS_PATH)


def build(args: argparse.Namespace) -> Stages:
    """Every seam a run needs, live or replayed. Nothing below this line knows which."""
    profile = local_wiki(API_URL)
    searches = REPO_ROOT / args.searches
    cassette = REPO_ROOT / args.cassette

    source: SearchSource
    model: ModelSource
    if args.live:
        load_env(REPO_ROOT / ".env")
        source, model = ParallelSearch(), GeminiModel()
        if args.record:
            source = RecordingSearch(source, searches)
            model = RecordingModel(model, cassette)
    else:
        for path, what in ((searches, "searches"), (cassette, "judgements")):
            if not path.exists():
                raise SystemExit(
                    f"no {what} cassette at {path.relative_to(REPO_ROOT)}. Cassettes are "
                    "gitignored, so a fresh clone records one first: --live --record."
                )
        source, model = RecordedSearch(searches), RecordedModel(cassette)

    return Stages(
        profile=profile,
        ledger=Ledger.local(profile, REPO_ROOT / args.ledger),
        baseline=JsonFileBaselineStore(REPO_ROOT / args.baseline),
        search=WebSearch(profile, source),
        classifier=Classifier(profile, model),
        drafter=Drafter(profile, model),
        reviewer=Reviewer(profile, model),
        drafts=draft_store(),
        judgements=judgement_store(),
        limit=args.limit,
    )


def report(result: RunReport, *, graph: bool) -> None:
    how = "ADK graph" if graph else "straight through"
    print(f"{result.wiki} · {how} · {result.started_at:%Y-%m-%d %H:%M} UTC")
    print(f"{result.task_id} — every document this run wrote names it\n")
    print(f"  audit       {result.due} claim(s) due")
    print(
        f"  research    {result.researched} searched over {result.rounds} round(s)"
        + (f" · {result.discarded} discarded" if result.discarded else "")
        + (f" · {result.out_of_budget} out of budget" if result.out_of_budget else "")
    )
    buckets = " · ".join(f"{name} {count}" for name, count in sorted(result.buckets.items()))
    revised = f" · {len(result.reclassified)} reclassified" if result.reclassified else ""
    print(f"  classify    {buckets or 'nothing classified'}{revised}")
    failed = f" · {len(result.failed)} failed" if result.failed else ""
    print(f"  draft       {result.drafted} edit(s){failed}")
    print(f"  diff        read {result.drafted}")
    if result.stored:
        print(f"  verify      {result.draft_id} · {result.changes} card(s) waiting")
    else:
        print("  verify      nothing to review; no draft stored")
    for claim_id in result.unresolved:
        print(f"  ! {claim_id} left unresolved — the sources disagree, and its card says so")
    for claim_id in result.skipped:
        print(f"  ! {claim_id} has no baseline section; run scripts/ingest_baseline.py")
    for claim_id in result.failed:
        print(f"  ! {claim_id} produced no edit the schema accepted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="call Parallel and Gemini for real")
    parser.add_argument("--record", action="store_true", help="with --live, write the cassettes")
    parser.add_argument("--limit", type=int, default=25, help="how many due claims to take")
    parser.add_argument("--no-graph", action="store_true", help="run the stages without ADK")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER_PATH))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE_PATH))
    parser.add_argument("--searches", default=str(DEFAULT_SEARCHES))
    parser.add_argument("--cassette", default=str(DEFAULT_CASSETTE))
    args = parser.parse_args()

    if args.record and not args.live:
        raise SystemExit("--record only means something with --live: a replay has nothing new")

    stages = build(args)
    result = straight_through(stages) if args.no_graph else run(stages)
    report(result, graph=not args.no_graph)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
