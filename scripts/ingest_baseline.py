"""Fill the ledger's baseline: read every monitored page and store its sections.

Step 1 of a run, and the only one that needs no model, no key and no network beyond the wiki's
own read API. Nothing is judged here — the sections are recorded verbatim so that everything
research later finds has something to be measured against.

    python3 scripts/ingest_baseline.py                 # from snapshots/, offline, no key
    python3 scripts/ingest_baseline.py --live          # from our own MediaWiki, needs the key
    python3 scripts/ingest_baseline.py --page Gambit   # one page

`--live` needs `MEDIAWIKI_API_URL` and `MEDIAWIKI_API_KEY` in `.env`. The wiki is treated as
external even though it is ours, so the agent has no unauthenticated path to it; `snapshots/`
is a committed corpus rather than a service, which is why the offline path needs nothing.

Idempotent: re-running an untouched page reports `unchanged` and rewrites the same bytes. The
`--live` path is the same call the deployed agent makes; pointing it at our instance rather
than at Fandom is a profile swap and nothing else.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agent.ingest import IngestResult, ingest_all, ingest_page  # noqa: E402
from backend.core.ledger.baseline import (  # noqa: E402
    DEFAULT_BASELINE_PATH,
    JsonFileBaselineStore,
)
from backend.core.ledger.documents import task_id_for  # noqa: E402
from backend.core.profile import WikiProfile, local_wiki  # noqa: E402
from backend.core.wiki import MediaWikiReader, PageSource, SnapshotPageSource  # noqa: E402


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


def build_source(live: bool) -> tuple[PageSource, WikiProfile, str]:
    """Live reads our own instance; the default reads the frozen corpus with nothing running."""
    if not live:
        profile = local_wiki("http://localhost/api.php")
        return SnapshotPageSource(REPO_ROOT, state="seed"), profile, "snapshots/seed"

    load_env(REPO_ROOT / ".env")
    api_url = os.environ.get("MEDIAWIKI_API_URL")
    if not api_url:
        raise SystemExit("MEDIAWIKI_API_URL is not set; run without --live to use snapshots/")
    api_key = os.environ.get("MEDIAWIKI_API_KEY")
    if not api_key:
        raise SystemExit(
            "MEDIAWIKI_API_KEY is not set. The wiki is treated as external even though it is "
            "ours, so a read needs a credential; any random string works locally."
        )
    profile = local_wiki(api_url)
    # Never printed: `where` is the endpoint, and the key stays out of every log line.
    return MediaWikiReader.for_profile(profile, api_key=api_key), profile, api_url


def report(results: tuple[IngestResult, ...], path: Path) -> None:
    for result in results:
        if not result.ok:
            print(f"  {result.page:<44} FAILED  {result.error}")
            continue
        state = "unchanged" if result.unchanged else (
            f"+{result.added} ~{result.changed} -{result.removed}"
        )
        print(f"  {result.resolved_title:<44} {result.sections:>3} sections  {state}")

    ok = [r for r in results if r.ok]
    sections = sum(r.sections for r in ok)
    failed = len(results) - len(ok)
    print(f"\n{len(ok)} pages, {sections} sections"
          + (f", {failed} FAILED" if failed else ""))
    print(f"wrote {path}")


def run(
    source: PageSource,
    profile: WikiProfile,
    store: JsonFileBaselineStore,
    page: str | None,
    task_id: str,
) -> tuple[IngestResult, ...]:
    """One page or the whole profile, in the shape `report` prints.

    A baseline pass is a task, so every section it stores names it — the same rule the graph's
    stages follow (`AGENTS.md` §2).
    """
    if page:
        return (ingest_page(source, profile, store, page, task_id=task_id),)
    return ingest_all(source, profile, store, task_id=task_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="read our own MediaWiki instead of snapshots/")
    parser.add_argument("--page", help="ingest one page rather than the whole profile")
    parser.add_argument("--path", default=str(DEFAULT_BASELINE_PATH),
                        help=f"baseline file (default {DEFAULT_BASELINE_PATH})")
    args = parser.parse_args()

    source, profile, where = build_source(args.live)
    store = JsonFileBaselineStore(REPO_ROOT / args.path)
    task_id = task_id_for(datetime.now(timezone.utc))
    print(f"reading {where} as {task_id}\n")

    # Transport failures propagate out of the library on purpose — a timeout is worth an ADK
    # retry, and swallowing one would turn an outage into an empty baseline. At a CLI boundary
    # a traceback is just noise, so it becomes a sentence here and nowhere else.
    try:
        results = run(source, profile, store, args.page, task_id)
    except URLError as exc:
        raise SystemExit(f"cannot reach {where}: {exc.reason}") from exc

    report(results, store.path.relative_to(REPO_ROOT))
    return 1 if any(not r.ok for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
