#!/usr/bin/env python3
"""Put the demo's drafted edits into the draft store, as one reviewable draft.

The gate reads drafts from a store, not from a file the browser happens to have. Until the ADK
graph runs there is nothing to *produce* one, so this converts the generated fixture's `queue`
into the document the store holds. The edits themselves are unchanged — same anchors, same
replacements, same confidences, all computed by `build_demo_state.py` from real `Claim` objects
— what changes is that they now live somewhere a decision can be written back to.

Overwrites the draft every run, which is what makes it a demo reset: re-seed the wiki, re-seed
the draft, and the run starts from three undecided cards again.

    python3 scripts/build_demo_state.py     # regenerate the fixture first, if it changed
    python3 scripts/seed_drafts.py          # then load it into the store
    python3 scripts/seed_drafts.py --show   # what the store holds now

`DRAFT_STORE=firestore` seeds Firestore instead of the local file, using the same documents.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.core.ledger.drafts import (  # noqa: E402  - after the path insert, deliberately
    Change,
    Decision,
    DraftStore,
    ReviewDraft,
)

FIXTURE = REPO_ROOT / "FE" / "data" / "demo-state.json"

#: One draft, one id, every run. The demo is a single review session, and a stable id is what
#: lets the popup be reopened on the same run rather than a copy of it.
DEMO_DRAFT_ID = "draft-demo-0001"


def store() -> DraftStore:
    """Same switch `backend/app.py` reads, so the seeder and the server never disagree."""
    if os.environ.get("DRAFT_STORE", "mongo").strip().lower() == "firestore":
        from backend.firestore import FirestoreDraftStore

        return FirestoreDraftStore(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
    from backend.mongo import MongoDraftStore

    return MongoDraftStore()


def build(fixture: dict[str, Any]) -> ReviewDraft:
    """The fixture's queue as one draft. Every change arrives undecided and unwritten."""
    queue: list[dict[str, Any]] = fixture["queue"]
    if not queue:
        raise SystemExit("the fixture has an empty queue; run scripts/build_demo_state.py first")
    return ReviewDraft(
        draft_id=DEMO_DRAFT_ID,
        wiki=fixture["profiles"][0]["label"],
        created_at=datetime.now(timezone.utc),
        changes=tuple(
            Change(
                edit_id=item["edit_id"],
                claim_id=item["claim_id"],
                page=item["page"],
                page_slug=item["page_slug"],
                section_index=item["section_index"],
                # The fixture writes "(lead)" for display; the stored heading is the real one,
                # and the lead's real heading is the empty string.
                section_heading=(
                    "" if item["section_index"] == 0 else item["section_heading"]
                ),
                before=item["before"],
                after=item["after"],
                summary=item["summary"],
                rationale=item["rationale"],
                confidence=item["confidence"],
                decision=Decision.UNDECIDED,
            )
            for item in queue
        ),
    )


def show(draft: ReviewDraft) -> None:
    print(f"{draft.draft_id}  {draft.wiki}  published={draft.published}")
    for change in draft.changes:
        where = f"{change.page} §{change.section_index}"
        wrote = f"rev {change.written_revid}" if change.written else "not written"
        print(f"  {change.edit_id:<20} {where:<28} {change.decision.value:<10} {wrote}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show", action="store_true", help="print what the store holds; write nothing"
    )
    args = parser.parse_args()

    drafts = store()
    if args.show:
        held = drafts.all()
        if not held:
            print("no drafts stored")
            return 0
        for draft in held:
            show(draft)
        return 0

    draft = build(json.loads(FIXTURE.read_text(encoding="utf-8")))
    drafts.put(draft)
    print(f"seeded {len(draft.changes)} changes")
    show(draft)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
