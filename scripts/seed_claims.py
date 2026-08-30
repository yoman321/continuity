#!/usr/bin/env python3
"""Put the demo's claims into the ledger, so a run has something due.

A run starts at Audit, which hands over the claims whose `next_check_at` has passed — and the
stage that *proposes* claims is the one piece of the pipeline still unbuilt. This stands in for
it: the six claims `seed-plan.md` §4 describes, tracked against the baseline, scheduled in the
past so the very next tick finds all of them due.

STUB: the claims are a hand-built fixture, not the output of an audit. What is real is
everything around them — the anchors are checked against the stored baseline and the build
fails on one that is missing, the entity refs come from the profile's title grammar, and the
schedule comes from `decay.py`. No sources and no outcome are seeded: those are what a run
produces, and seeding them would be seeding the answer.

    python3 scripts/ingest_baseline.py      # the baseline first — this reads it
    python3 scripts/seed_claims.py          # then the claims
    python3 scripts/seed_claims.py --show   # what the ledger holds now

Overwrites each claim every run, which is what makes it a demo reset: re-seed, and the next
`run_once.py` starts from six untouched claims again.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_demo_state import DEMO_CLAIMS, DemoClaim  # noqa: E402  - after the path insert

from backend.core.ledger.baseline import (  # noqa: E402
    DEFAULT_BASELINE_PATH,
    BaselineStore,
    JsonFileBaselineStore,
)
from backend.core.ledger.documents import task_id_for  # noqa: E402
from backend.core.ledger.schema import Claim  # noqa: E402
from backend.core.ledger.store import DEFAULT_LEDGER_PATH, JsonFileClaimStore  # noqa: E402
from backend.core.profile import WikiProfile, local_wiki  # noqa: E402

#: Far enough back that every wave's seed interval has already elapsed, so every claim is due
#: now. The alternative — writing `next_check_at` directly — would put a scheduling decision
#: somewhere other than `decay.py`.
BACKDATE = timedelta(days=400)

#: The run needs no wiki: it reads sections from the baseline and writes to the draft store.
#: The endpoint is still required by the profile, so this is a placeholder and stays one.
API_URL = "http://wiki.invalid/api.php"


def section_index(baseline: BaselineStore, demo: DemoClaim) -> int:
    """Where this claim's anchor lives, from the baseline the run will read.

    Resolved here rather than stored on the fixture so the index cannot disagree with the text
    the stages are handed — and a heading that moved fails now rather than mid-run.
    """
    for section in baseline.for_page(demo.page):
        if section.section_heading == demo.section_heading:
            if demo.anchor not in section.text:
                where = f"{demo.page}#{demo.section_heading or '(lead)'}"
                raise SystemExit(f"{demo.claim_id}: anchor not found in {where}")
            return section.section_index
    raise SystemExit(
        f"{demo.claim_id}: no section {demo.section_heading or '(lead)'!r} for {demo.page}. "
        "Run scripts/ingest_baseline.py first."
    )


def build(
    demo: DemoClaim, profile: WikiProfile, index: int, now: datetime, task_id: str
) -> Claim:
    """One fixture claim as the ledger holds it before anything has researched it."""
    return Claim(
        claim_id=demo.claim_id,
        page=demo.page,
        entity_ref=profile.entity_ref(demo.page),
        kind=demo.kind,
        wave=demo.wave,
        text=demo.text,
        wikitext_anchor=demo.anchor,
        section_index=index,
        section_heading=demo.section_heading,
        # The question this claim is about. A proposal stage would have written it; the
        # research stage reads it on the first round and broadens it on a retry.
        objective=demo.objective,
        ripple_targets=demo.ripple_targets,
        # Seeding is a task like any other, so the claims say which pass wrote them. When the
        # proposal stage exists it will stamp its own run's id here instead.
        task_id=task_id,
    ).seeded(now - BACKDATE)


def show(store: JsonFileClaimStore, now: datetime) -> None:
    for claim in store.all():
        due = "due" if claim.is_due(now) else f"due {claim.next_check_at:%Y-%m-%d}"
        print(
            f"  {claim.claim_id:<14} {claim.page:<24} §{claim.section_index:<3} "
            f"{claim.status.value:<11} rounds {claim.research_rounds}  {due:<18} "
            f"{claim.task_id or '(no task)'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="print the ledger; write nothing")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER_PATH))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE_PATH))
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    store = JsonFileClaimStore(REPO_ROOT / args.ledger)
    if args.show:
        if not store.all():
            print("no claims tracked")
            return 0
        show(store, now)
        return 0

    profile = local_wiki(API_URL)
    baseline = JsonFileBaselineStore(REPO_ROOT / args.baseline)
    if not baseline.pages():
        raise SystemExit(
            f"{args.baseline} holds no sections. Run scripts/ingest_baseline.py first — a claim "
            "is proposed against a baseline that already exists."
        )

    task_id = task_id_for(now)
    claims = [build(d, profile, section_index(baseline, d), now, task_id) for d in DEMO_CLAIMS]
    store.put_all(claims)
    print(f"seeded {len(claims)} claims as {task_id}, all due now")
    show(store, now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
