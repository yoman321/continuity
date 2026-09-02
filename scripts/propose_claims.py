"""Fill the ledger: read the monitored pages and propose what they assert.

Step 2 of a cold start, between the baseline ingest and a run. The baseline records what each
page *says*; this decides what it *asserts*, which is what everything downstream re-checks.

    python3 scripts/propose_claims.py                 # replayed from the cassette, no key
    python3 scripts/propose_claims.py --live --record # against Gemini, and record it
    python3 scripts/propose_claims.py --page Gambit   # one page
    python3 scripts/propose_claims.py --show          # what is tracked, without proposing

This replaces `scripts/seed_claims.py`, which seeded six hand-written claims from
`build_demo_state.py` and is deleted. The difference is the point: the agent now finds the
claims it tracks rather than being handed them, so a page nobody wrote a fixture for is still
covered.

**Idempotent.** A claim already tracked at the same `(page, anchor)` is left alone, so running
this twice proposes nothing the second time and never duplicates a record. That is what lets it
run on a schedule rather than only on a cold start.

**Bounded.** `MAX_PER_PAGE` claims per page per pass, and sections that hold no assertions —
references, galleries — are skipped without a model call. Every claim costs a search on every
tick forever, so the cap is a cost decision, not a formatting one.
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

from backend.agent.model import (  # noqa: E402
    DEFAULT_CASSETTE,
    GeminiModel,
    ModelError,
    ModelSource,
    RecordedModel,
    record,
)
from backend.agent.propose import (  # noqa: E402
    MAX_PER_PAGE,
    RESPONSE_SCHEMA,
    SYSTEM,
    ModelRequest,
    Proposer,
    room_left,
    store_proposals,
    worth_reading,
)
from backend.core.ledger.documents import task_id_for  # noqa: E402
from backend.core.profile import local_wiki  # noqa: E402
from backend.mongo import MongoBaselineStore, MongoClaimStore  # noqa: E402

#: The endpoint is a deployment identifier, and the wiki is in the browser anyway — nothing
#: here opens a connection to it. The profile is what supplies title grammar and the tier table.
API_URL = "http://localhost:8000/wiki/api.php"


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


def show(store: MongoClaimStore) -> int:
    claims = store.all()
    if not claims:
        print("the ledger holds no claims; run without --show to propose some")
        return 1
    by_page: dict[str, int] = {}
    for claim in claims:
        by_page[claim.page] = by_page.get(claim.page, 0) + 1
    for claim in claims:
        print(f"  {claim.claim_id:<14} {claim.page:<34} §{claim.section_index:<3} "
              f"{claim.kind.value:<12} {claim.wave.value:<20} {claim.text[:60]}")
    print(f"\n{len(claims)} claims over {len(by_page)} pages")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="call Gemini instead of replaying")
    parser.add_argument("--record", action="store_true", help="write answers to the cassette")
    parser.add_argument("--page", help="one page rather than every page in the profile")
    parser.add_argument("--show", action="store_true", help="print the ledger and stop")
    parser.add_argument("--limit", type=int, default=0, help="stop after N pages")
    args = parser.parse_args()

    load_env(REPO_ROOT / ".env")
    profile = local_wiki(API_URL)
    claims = MongoClaimStore()
    if args.show:
        return show(claims)

    baseline = MongoBaselineStore()
    pages = [args.page] if args.page else list(baseline.pages())
    if not pages:
        raise SystemExit(
            "the baseline holds no sections. Run scripts/ingest_baseline.py first — a claim is "
            "proposed against a page that has already been read."
        )
    if args.limit:
        pages = pages[: args.limit]

    cassette = REPO_ROOT / DEFAULT_CASSETTE
    source: ModelSource = GeminiModel() if args.live else RecordedModel(cassette)
    proposer = Proposer(profile, source)
    now = datetime.now(timezone.utc)
    task_id = task_id_for(now)
    print(f"proposing as {task_id} · {'live' if args.live else 'replayed'}\n")

    total_kept = 0
    total_rejected = 0
    for page in pages:
        sections = [s for s in baseline.for_page(page) if worth_reading(s)]
        kept_here: list[str] = []
        for section in sections:
            if room_left(claims, page) <= 0:
                print(f"  {page:<40} full at {MAX_PER_PAGE} claims; "
                      f"{len(sections) - len(kept_here)} section(s) not read")
                break
            try:
                proposals = proposer.propose(page, section)
            except ModelError as exc:
                # A miss is not a finding about the page: say so and move on, rather than
                # recording "this section asserts nothing" for a call that never happened.
                print(f"  {page} §{section.section_index}: {exc}")
                continue

            if args.live and args.record:
                # Rebuilt from what was parsed rather than captured raw, the same way
                # `classify_once.py` does it: the cassette stores an answer that satisfies the
                # declared schema, and a replay of it must produce these same proposals.
                request = ModelRequest(
                    system=SYSTEM, schema=RESPONSE_SCHEMA,
                    prompt=proposer.prompt(page, section),
                )
                record(cassette, request, json.dumps({"claims": [
                    {"text": p.text, "anchor": p.anchor, "kind": p.kind,
                     "wave": p.wave, "objective": p.objective}
                    for p in proposals
                ]}))

            kept, rejected = store_proposals(
                proposals, page=page, section_text=section.text, profile=profile,
                store=claims, now=now, task_id=task_id,
            )
            total_kept += len(kept)
            total_rejected += len(rejected)
            kept_here.extend(f"{c.claim_id} {c.text[:52]}" for c in kept)
            for bad in rejected:
                if bad.reason != "already tracked":
                    print(f"    dropped: {bad.reason} — {bad.text[:50]}")

        print(f"  {page:<40} {len(sections):>3} sections read, {len(kept_here):>2} new claim(s)")
        for line in kept_here:
            print(f"      {line}")

    print(f"\n{total_kept} claims tracked, {total_rejected} proposals dropped")
    print(f"{len(claims.all())} claims in the ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
