"""Build the wiki's simulated database: `snapshots/seed/` -> MediaWiki-shaped tables.

There is no MariaDB and no server (`AGENTS.md` §2). This lays out the rows the browser-side
wiki loads: a read is a `page` row joined to its latest `revision` joined to its `text`, and a
write appends a revision and moves `page_latest` — what the real schema does, so the rows stay
portable if a database ever comes back.

Two files, and the difference between them is the whole reset story:

    snapshots/wiki-db.dummy.json    forever dummy. Committed, never written to, regenerated
                                    only by this script, and the canonical copy.
    FE/data/wiki-db.json            what the browser fetches at boot. Same bytes; written
                                    together so the two cannot drift.

    python3 scripts/build_wiki_db.py            # rebuild both from snapshots/seed/

The wiki lives in the browser now (`FE/wiki-api.js`) and holds its edits in memory, so there
is no live file to reset: reloading the page *is* the reset.

The seed wikitext is hash-checked against `snapshots/manifest.json` as it is read, because a
corpus that silently drifted would seed a wiki nobody could reproduce — the same guard
`SnapshotPageSource` applies on every read.

Deliberate deviation from the real schema, stated rather than hidden: MediaWiki stores
`rev_sha1` as base36 SHA-1, and this carries `rev_sha256` instead, because the manifest already
pins sha256 and inventing a second digest would give the corpus two hashes that could disagree.
Everything else — column names, underscored titles, the `text` indirection through `old_id` —
is the real shape.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MANIFEST = Path("snapshots/manifest.json")
DUMMY_PATH = Path("snapshots/wiki-db.dummy.json")
#: The frontend fetches this at boot — it is the wiki now, served as a static file alongside
#: the rest of `FE/`. Written with the dummy so the two cannot drift.
FE_PATH = Path("FE/data/wiki-db.json")

SCHEMA = "mediawiki-subset/1"
MAIN_NAMESPACE = 0


def page_title(title: str) -> str:
    """MediaWiki stores titles underscored and without the namespace prefix."""
    return title.replace(" ", "_")


def build_tables(repo_root: Path, *, state: str = "seed") -> dict[str, Any]:
    """Read the manifest and the seed wikitext, and lay them out as rows.

    `text` is a separate table rather than a column on `revision` for the same reason MediaWiki
    separates them: a revision points at its content, so appending a revision never rewrites
    the content of the one before it.
    """
    manifest: dict[str, Any] = json.loads(
        (repo_root / MANIFEST).read_text(encoding="utf-8")
    )
    if state not in manifest["states"]:
        raise SystemExit(f"no such snapshot state: {state!r}")

    pages: list[dict[str, Any]] = []
    revisions: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    redirects: list[dict[str, Any]] = []

    for old_id, entry in enumerate(manifest["pages"], start=1):
        snapshot = entry.get(state)
        if not snapshot:
            raise SystemExit(f"{entry['resolved_title']}: no {state} snapshot")

        content = (repo_root / snapshot["file"]).read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest != snapshot["sha256"]:
            raise SystemExit(
                f"{snapshot['file']}: sha256 {digest} does not match the manifest "
                f"({snapshot['sha256']}). Fix the puller and re-run; never hand-edit the corpus."
            )

        pages.append(
            {
                "page_id": entry["pageid"],
                "page_namespace": MAIN_NAMESPACE,
                "page_title": page_title(entry["resolved_title"]),
                "page_latest": snapshot["revid"],
                "page_len": snapshot["size"],
                "page_touched": snapshot["timestamp"],
                "page_is_redirect": 0,
            }
        )
        revisions.append(
            {
                "rev_id": snapshot["revid"],
                "rev_page": entry["pageid"],
                "rev_parent_id": 0,
                "rev_timestamp": snapshot["timestamp"],
                "rev_user_text": snapshot["user"],
                "rev_comment": snapshot["comment"],
                "rev_len": snapshot["size"],
                "rev_sha256": snapshot["sha256"],
                "rev_text_id": old_id,
            }
        )
        texts.append({"old_id": old_id, "old_text": content, "old_flags": "utf-8"})

        if entry.get("redirected_from"):
            redirects.append(
                {
                    "rd_from_title": page_title(entry["redirected_from"]),
                    "rd_namespace": MAIN_NAMESPACE,
                    "rd_title": page_title(entry["resolved_title"]),
                }
            )

    return {
        "schema": SCHEMA,
        "generated_from": f"{MANIFEST.as_posix()} @ {state}",
        "source": manifest["source"],
        "licence": "CC BY-SA 3.0 Unported — see snapshots/ATTRIBUTION.md",
        "next_rev_id": max(r["rev_id"] for r in revisions) + 1,
        "next_text_id": len(texts) + 1,
        "tables": {
            "page": pages,
            "revision": revisions,
            "text": texts,
            "redirect": redirects,
        },
    }


def write_json(path: Path, tables: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tables, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def summarise(tables: dict[str, Any]) -> str:
    counts = {name: len(rows) for name, rows in tables["tables"].items()}
    bytes_ = sum(len(t["old_text"].encode("utf-8")) for t in tables["tables"]["text"])
    return (
        f"{counts['page']} pages, {counts['revision']} revisions, "
        f"{counts['redirect']} redirects, {bytes_:,} bytes of wikitext"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("--state", default="seed", help="snapshot state to build from")
    args = parser.parse_args(argv)

    dummy = REPO_ROOT / DUMMY_PATH

    tables = build_tables(REPO_ROOT, state=args.state)
    write_json(dummy, tables)
    print(f"wrote  {DUMMY_PATH}  ({summarise(tables)})")
    write_json(REPO_ROOT / FE_PATH, tables)
    print(f"wrote  {FE_PATH}  — what the browser loads the wiki from")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
