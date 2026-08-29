"""Run the classify stage on one claim, live or replayed — and record the judgement.

The cassette is gitignored (it carries third-party excerpts inside the prompts), so a fresh
clone has no recording and this is how one is made. It is also the smallest end-to-end path
through the built half of the pipeline: baseline -> claim -> search -> classify -> ledger.

    python3 scripts/classify_once.py                # replay the cassette; no key, no network
    python3 scripts/classify_once.py --live         # call Gemini, and record the answer
    python3 scripts/classify_once.py --live --no-record

Live needs ADC (`gcloud auth application-default login`) and `GOOGLE_CLOUD_PROJECT` in `.env`.
There is no Gemini API key — auth is ADC on both sides (`AGENTS.md` §2).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agent.classify import RESPONSE_SCHEMA, SYSTEM, Classifier  # noqa: E402
from backend.agent.ingest import ingest_page  # noqa: E402
from backend.agent.model import (  # noqa: E402
    DEFAULT_CASSETTE,
    GeminiModel,
    ModelRequest,
    ModelSource,
    RecordedModel,
    record,
)
from backend.agent.tools import Ledger, WebSearch  # noqa: E402
from backend.core.ledger.baseline import InMemoryBaselineStore  # noqa: E402
from backend.core.profile import local_wiki  # noqa: E402
from backend.core.wiki import SnapshotPageSource  # noqa: E402

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

#: The lead beat (`seed-plan.md` §4.1). Hardcoded because this is a harness, not a stage: the
#: claim that a real run would have proposed, so classify can be exercised before the node that
#: proposes claims exists.
PAGE = "Gambit"
CLAIM_TEXT = "Gambit appears in Deadpool & Wolverine."
ANCHOR = "|movie = ''[[Deadpool & Wolverine]]''"
QUERIES = ["Gambit Avengers Doomsday cast", "Channing Tatum Gambit Doomsday",
           "Gambit MCU future appearances"]
OBJECTIVE = ("Has Gambit, played by Channing Tatum, been cast in any Marvel film after "
             "Deadpool & Wolverine, in particular Avengers: Doomsday?")


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="call Gemini instead of replaying")
    parser.add_argument("--no-record", action="store_true", help="do not write the cassette")
    parser.add_argument("--cassette", default=str(DEFAULT_CASSETTE))
    args = parser.parse_args()

    load_env(REPO_ROOT / ".env")
    profile = local_wiki("http://wiki.invalid/api.php")
    cassette = REPO_ROOT / args.cassette

    # 1. baseline — what the page says, from the committed corpus
    baseline = InMemoryBaselineStore()
    ingest_page(SnapshotPageSource(REPO_ROOT, state="seed"), profile, baseline, PAGE, now=NOW)
    section = baseline.for_page(PAGE)[0]

    # 2. a claim against it
    ledger = Ledger.in_memory(profile, clock=lambda: NOW)
    claim = ledger.track_claim(page=PAGE, text=CLAIM_TEXT, wikitext_anchor=ANCHOR,
                               section_heading=section.section_heading,
                               section_index=section.section_index,
                               kind="prose", wave="announcement_driven")

    # 3. research — replayed, so this never bills a search
    search = WebSearch.recorded(profile, REPO_ROOT / "fixtures" / "searches.json").search(
        search_queries=QUERIES, objective=OBJECTIVE)

    # 4. classify
    source: ModelSource = GeminiModel() if args.live else RecordedModel(cassette)
    classifier = Classifier(profile, source)
    prompt = classifier.prompt(claim, section.text, search)
    print(f"{PAGE}: {len(baseline.for_page(PAGE))} sections · {len(search['results'])} excerpts "
          f"· prompt {len(prompt)} chars · {'live' if args.live else 'replayed'}\n")
    verdict = classifier.classify(claim, section.text, search)

    print(f"  bucket      {verdict.bucket}  ->  record_outcome({verdict.outcome!r})")
    print(f"  reason      {verdict.reason}")
    print(f"  off-entity  {list(verdict.off_entity) or 'nothing dropped'}")
    if verdict.is_conflict:
        print(f"  conflict    {verdict.note}\n              {verdict.source_a}"
              f"\n              {verdict.source_b}")

    # 5. the ledger write the bucket implies
    stored = ledger.record_outcome(claim["claim_id"], verdict.outcome, note=verdict.note,
                                   source_a=verdict.source_a, source_b=verdict.source_b)
    print(f"\n  ledger      {stored['status']} · interval {stored['check_interval_hours']}h "
          f"· next {stored['next_check_at']}")

    if args.live and not args.no_record:
        record(cassette, ModelRequest(system=SYSTEM, prompt=prompt, schema=RESPONSE_SCHEMA),
               json.dumps({"bucket": verdict.bucket, "reason": verdict.reason,
                           "off_entity": list(verdict.off_entity),
                           **({"conflict": {"note": verdict.note, "source_a": verdict.source_a,
                                            "source_b": verdict.source_b}}
                              if verdict.is_conflict else {})}))
        print(f"  recorded    {cassette.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
