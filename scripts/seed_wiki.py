#!/usr/bin/env python3
"""Seed our own MediaWiki with the 12 pages in `snapshots/seed/`.

The instance exists because `AGENTS.md` §2 forbids writing to a real wiki, and the demo has to
show an edit actually landing. Seeding it from the frozen corpus rather than from the live API
is what makes it reproducible: the snapshots are pinned to historical revision ids and
hash-checked, so this script produces the same wiki every time it runs.

`Special:Export` / `importDump.php` is not an option — Fandom puts a Cloudflare challenge in
front of the export endpoint (`AGENTS.md` §6), which is why the corpus was pulled through
`api.php` in the first place and why this posts wikitext through `action=edit`.

Idempotent: re-running re-posts identical text, which MediaWiki records as a null edit.

    python3 scripts/seed_wiki.py --check     # compare the instance against the profile
    python3 scripts/seed_wiki.py             # seed, then verify every page byte-for-byte
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.core.profile import WikiProfile, local_wiki  # noqa: E402  - after the path insert
from backend.core.wiki import MediaWikiReader, MediaWikiWriter, WikiError  # noqa: E402

MANIFEST = REPO_ROOT / "snapshots" / "manifest.json"

SUMMARY = (
    "Seeded from MCU Wiki revision {revid} ({timestamp}), CC BY-SA 3.0 — "
    "see snapshots/ATTRIBUTION.md"
)


def load_env(path: Path) -> None:
    """Read `.env` without overriding what is already set. Same rule as `backend/app.py`."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


def profile_from_env() -> WikiProfile:
    """The endpoint is a deployment identifier, so it comes from `.env` and never from code."""
    return local_wiki(require("MEDIAWIKI_API_URL"))


def api_key() -> str:
    """The instance is treated as external even though it is ours, so every adapter built here
    carries the key. It is never stored on the profile (`AGENTS.md` §2)."""
    return require("MEDIAWIKI_API_KEY")


def check_grammar(profile: WikiProfile) -> list[str]:
    """Ask the instance whether it agrees with the profile, rather than assuming it does.

    The profile says these pages use subpage titles; MediaWiki reports the real setting under
    `siprop=namespaces`. If the two disagree, `Human Torch/Void-Analyzing Fantastic Four` stops
    being a variant halfway through the pipeline and every claim about it silently attaches to
    the wrong subject — so this is checked before anything is written, not after.
    """
    reader = MediaWikiReader.for_profile(profile, api_key=api_key())
    query = reader.fetch({
        "action": "query", "meta": "siteinfo",
        "siprop": "general|namespaces|rightsinfo",
        "format": "json", "formatversion": "2",
    })["query"]

    problems = []
    mainspace = query["namespaces"]["0"]
    if bool(mainspace.get("subpages")) != profile.subpages:
        problems.append(
            f"subpages: instance says {bool(mainspace.get('subpages'))}, "
            f"profile says {profile.subpages} — set $wgNamespacesWithSubpages[NS_MAIN]"
        )
    declared = query.get("rightsinfo", {}).get("text", "")
    if declared != profile.licence:
        problems.append(f"licence: instance says {declared!r}, profile says {profile.licence!r}")
    print(f"  {query['general']['generator']} at {profile.api_url}")
    print(f"  sitename {query['general']['sitename']!r}, licence {declared!r}")
    print(f"  mainspace subpages: {bool(mainspace.get('subpages'))}")
    return problems


def seed(profile: WikiProfile, pages: list[dict[str, Any]]) -> None:
    writer = MediaWikiWriter.for_profile(profile, api_key=api_key())
    user = writer.login(require("MEDIAWIKI_BOT_USER"), require("MEDIAWIKI_BOT_PASSWORD"))
    print(f"  logged in as {user}")

    for entry in pages:
        seed_state = entry["seed"]
        text = (REPO_ROOT / seed_state["file"]).read_text(encoding="utf-8")
        result = writer.edit(
            entry["resolved_title"],
            text,
            summary=SUMMARY.format(revid=seed_state["revid"], timestamp=seed_state["timestamp"]),
        )
        change = (
            "no change" if result.get("nochange") is not None
            else f"rev {result.get('newrevid')}"
        )
        size = len(text.encode("utf-8"))  # bytes as MediaWiki counts them, not characters
        print(f"  {entry['resolved_title']:<45} {size:>7,} bytes  {change}")


def verify(profile: WikiProfile, pages: list[dict[str, Any]]) -> list[str]:
    """Read every page back and compare its hash to the manifest.

    Posting wikitext through the API is not obviously lossless — MediaWiki normalises line
    endings and strips trailing whitespace — so "the edit succeeded" is not the same claim as
    "the instance holds the corpus". This checks the second one.
    """
    reader = MediaWikiReader.for_profile(profile, api_key=api_key())
    problems = []
    for entry in pages:
        expected = entry["seed"]["sha256"]
        try:
            revision = reader.revision(entry["resolved_title"])
        except WikiError as exc:
            problems.append(f"{entry['resolved_title']}: {exc}")
            continue
        if revision.sha256 != expected:
            problems.append(
                f"{entry['resolved_title']}: content differs from the seed "
                f"({revision.size:,} bytes here, {entry['seed']['size']:,} expected)"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="only compare the instance against the profile; write nothing")
    args = parser.parse_args()

    load_env(REPO_ROOT / ".env")
    profile = profile_from_env()
    pages = json.loads(MANIFEST.read_text(encoding="utf-8"))["pages"]

    print(f"Instance: {profile.name} (writable={profile.writable})")
    problems = check_grammar(profile)
    if problems:
        print("\nThe instance does not match the profile:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    if args.check:
        print("\nInstance matches the profile.")
        return 0

    print(f"\nSeeding {len(pages)} pages:")
    seed(profile, pages)

    print("\nVerifying against snapshots/manifest.json:")
    mismatches = verify(profile, pages)
    if mismatches:
        for mismatch in mismatches:
            print(f"  - {mismatch}")
        return 1
    print(f"  all {len(pages)} pages match their seed hash byte-for-byte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
