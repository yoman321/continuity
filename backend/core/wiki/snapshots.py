"""Snapshot-backed page reads — the deterministic fallback for the wiki perimeter.

`CLAUDE.md` §3 wants every external source to have a fallback that cannot fail, because a demo
must not break on an expired key or a network blip. For the wiki that fallback is already on
disk: `snapshots/seed/` is 12 pages pinned to historical revision ids, hash-checked and
byte-reproducible (`AGENTS.md` §4). It just had no reader.

So this serves the same `PageRevision` records `client.py` does, out of files instead of
`api.php`, behind the same protocol. Three things follow. The graph is buildable and testable
before a local MediaWiki exists. Every stage that reads a page can be tested offline and
deterministically. And the demo has a path that survives the network being unplugged.

Pure: filesystem only. No network, no vendor SDK.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .client import PageRevision, WikiError, parse_timestamp

#: Where the provenance record lives, relative to the repo root.
MANIFEST = Path("snapshots") / "manifest.json"


@runtime_checkable
class PageSource(Protocol):
    """One revision of one page — the whole of what the agent needs to read a wiki.

    `MediaWikiReader` and `SnapshotPageSource` both satisfy this, which is what lets a stage
    be written once and run against either. Keeping it to a single method is deliberate: the
    narrower this is, the less a fallback has to fake.
    """

    def revision(self, title: str, *, before: datetime | None = None) -> PageRevision: ...


class SnapshotPageSource:
    """Reads pages out of `snapshots/`, keyed by the manifest rather than by filename.

    Titles are indexed both as requested and as resolved, because the puller records both and
    a caller may hold either. What this cannot do is *follow* a redirect: resolution happened
    at pull time against the live API, so a title outside the manifest is a miss even when the
    real wiki would redirect it onto a page that is in here. As of the current corpus no page
    redirects at all — all 12 requested titles resolved to themselves — so the fallback is
    exact for everything it covers, and the limitation only bites if a claim is later written
    against an alias.
    """

    def __init__(self, repo_root: Path, *, state: str = "seed") -> None:
        self.repo_root = repo_root
        self.state = state
        manifest: dict[str, Any] = json.loads(
            (repo_root / MANIFEST).read_text(encoding="utf-8")
        )
        if state not in manifest["states"]:
            raise WikiError(f"no such snapshot state: {state!r}")

        index: dict[str, dict[str, Any]] = {}
        for entry in manifest["pages"]:
            index[entry["requested_title"]] = entry
            index[entry["resolved_title"]] = entry
        self._index = index

    @property
    def titles(self) -> tuple[str, ...]:
        """Every title this source can answer, resolved and requested alike."""
        return tuple(sorted(self._index))

    def revision(self, title: str, *, before: datetime | None = None) -> PageRevision:
        entry = self._index.get(title)
        if entry is None:
            raise WikiError(f"{title}: not in the snapshot corpus")
        state = entry.get(self.state)
        if not state:
            raise WikiError(f"{title}: no {self.state} snapshot")

        content = (self.repo_root / state["file"]).read_text(encoding="utf-8")
        revision = PageRevision(
            requested_title=title,
            resolved_title=entry["resolved_title"],
            redirected_from=entry["redirected_from"],
            pageid=entry["pageid"],
            revid=state["revid"],
            timestamp=parse_timestamp(state["timestamp"]),
            user=state["user"],
            comment=state["comment"],
            content=content,
        )

        # The suite hash-checks these too, but a fallback that silently serves edited seed
        # text is the failure this corpus exists to prevent — so it is checked on the read
        # path as well, not only in a test that a demo does not run.
        if revision.sha256 != state["sha256"]:
            raise WikiError(f"{title}: {state['file']} does not match its manifest hash")

        # Same answer the live API gives when history does not reach back that far.
        if before is not None and revision.timestamp > before:
            raise WikiError(f"{title}: no revision at the requested point in history")
        return revision
