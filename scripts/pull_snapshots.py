#!/usr/bin/env python3
"""Pull the seed corpus from MCU Wiki into `snapshots/`.

Two states of every page (`seed-plan.md` §1): the revision frozen at 2024-08-09, which is
what our own MediaWiki gets seeded with, and the live revision, which is only evidence — the
agent is never scored against it (`seed-plan.md` §1, "the direction of work").

Re-runnable. `seed/` is pinned to a revision id and must come back byte-identical forever;
`current/` moves whenever editors touch the wiki, and its churn is the point.

    python3 scripts/pull_snapshots.py                # both states
    python3 scripts/pull_snapshots.py --only seed    # just the frozen side
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from continuity.wiki import MCU_WIKI_API, MediaWikiReader, PageRevision, WikiError

FREEZE = datetime(2024, 8, 9, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parent.parent
COURTESY_DELAY = 0.4  # seconds between calls; we are an unauthenticated guest here

# `seed-plan.md` §2. Titles are the *requested* ones — the client resolves redirects and the
# manifest records where each landed, which is how the two title traps stay visible.
SEED_PAGES: tuple[tuple[str, str], ...] = (
    ("Deadpool & Wolverine", "trunk"),
    ("Gambit", "lead beat — cast in Avengers: Doomsday"),
    ("Void (End of Time)", "disambiguation cascade"),
    ("Human Torch", "variant-vs-prime precision test"),
    ("Human Torch/Void-Analyzing Fantastic Four", "the variant half of that test"),
    ("Phase Six", "slate composition"),
    ("Deadpool", "character ripple from the trunk"),
    ("Blade/Universe Defender Blade", "variant subpage"),
    ("Wolverine", "control"),
    ("Cassandra Nova", "control"),
    ("Time Variance Authority", "control"),
    ("Phase Five", "control"),
)


def record(rev: PageRevision, path: Path) -> dict[str, Any]:
    return {
        "revid": rev.revid,
        "timestamp": rev.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user": rev.user,
        "comment": rev.comment,
        "size": rev.size,
        "sha256": rev.sha256,
        "file": str(path.relative_to(REPO_ROOT)),
    }


def licence(reader: MediaWikiReader) -> dict[str, Any]:
    """Licence, pinned to a version.

    `siprop=rightsinfo` answers a bare "CC-BY-SA" and points at a JS-rendered page, so it
    cannot settle 3.0 vs 4.0 on its own (`seed-plan.md` §7). The wiki's own `Project:Copyrights`
    can, and it is a normal page, so the answer comes back with a revision id behind it.
    """
    rights: dict[str, Any] = reader.rights_info()
    time.sleep(COURTESY_DELAY)
    info: dict[str, Any] = {
        "declared": rights.get("rightsinfo", {}),
        "generator": rights.get("general", {}).get("generator"),
        "sitename": rights.get("general", {}).get("sitename"),
    }
    try:
        page = reader.revision("Project:Copyrights")
    except (WikiError, OSError) as exc:
        info["copyright_page_error"] = str(exc)
        return info
    finally:
        time.sleep(COURTESY_DELAY)

    info["copyright_page"] = {
        "title": page.resolved_title,
        "revid": page.revid,
        "text": page.content.strip(),
    }
    # Pin from the text itself rather than asserting a version we hope is right.
    for version in ("4.0", "3.0"):
        if f"by-sa/{version}" in page.content or f"License {version}" in page.content:
            info["version"] = version
            break
    return info


def pull(out_dir: Path, states: tuple[str, ...]) -> dict[str, Any]:
    reader = MediaWikiReader()
    rights_meta = licence(reader)

    pages: list[dict[str, Any]] = []
    failures: list[str] = []

    for title, role in SEED_PAGES:
        entry: dict[str, Any] = {"requested_title": title, "role": role}
        revisions: dict[str, PageRevision] = {}

        for state in states:
            try:
                rev = reader.revision(title, before=FREEZE if state == "seed" else None)
            except (WikiError, OSError) as exc:
                print(f"  !! {title} [{state}]: {exc}", file=sys.stderr)
                failures.append(f"{title} [{state}]")
                continue
            finally:
                time.sleep(COURTESY_DELAY)

            state_dir = out_dir / state
            state_dir.mkdir(parents=True, exist_ok=True)
            path = state_dir / f"{rev.slug}.wikitext"
            path.write_text(rev.content, encoding="utf-8")

            revisions[state] = rev
            entry.setdefault("resolved_title", rev.resolved_title)
            entry.setdefault("redirected_from", rev.redirected_from)
            entry.setdefault("pageid", rev.pageid)
            entry.setdefault("slug", rev.slug)
            entry[state] = record(rev, path)
            print(f"  {rev.slug:<44} {state:<7} r{rev.revid:<9} {rev.size:>7,} B")

        # The number `seed-plan.md` §2 quotes, recomputed rather than retyped.
        if "seed" in revisions and "current" in revisions:
            seed_size = revisions["seed"].size
            entry["drift_bytes"] = revisions["current"].size - seed_size
            entry["drift_pct"] = round(100 * entry["drift_bytes"] / seed_size, 1)

        pages.append(entry)

    if failures:
        print(f"\n{len(failures)} pull(s) failed: {', '.join(failures)}", file=sys.stderr)

    return {
        "source": {
            "wiki": rights_meta.get("sitename", "Marvel Cinematic Universe Wiki"),
            "api": MCU_WIKI_API,
            "generator": rights_meta.get("generator"),
            "licence": rights_meta,
        },
        "freeze": FREEZE.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pulled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "states": list(states),
        "pages": pages,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "snapshots")
    parser.add_argument("--only", choices=("seed", "current"), default=None,
                        help="pull one state instead of both")
    args = parser.parse_args()

    states = (args.only,) if args.only else ("seed", "current")
    args.out.mkdir(parents=True, exist_ok=True)

    manifest = pull(args.out, states)
    manifest_path = args.out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {manifest_path.relative_to(REPO_ROOT)}")

    return 1 if manifest["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
