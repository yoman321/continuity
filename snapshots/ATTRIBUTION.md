# Attribution — wiki text in this directory

Every `.wikitext` file under `seed/` and `current/` is **not** original work and is **not**
covered by this repository's MIT licence. It is verbatim article text from the Marvel
Cinematic Universe Wiki, redistributed here under the licence that wiki publishes it under.

| | |
|---|---|
| Source | [Marvel Cinematic Universe Wiki](https://marvelcinematicuniverse.fandom.com) (Fandom), MediaWiki 1.43.9 |
| Authors | The wiki's contributors — per-revision authorship is in `manifest.json` (`user`) and the full history is at each page's `?action=history` |
| Licence | [Creative Commons Attribution-ShareAlike 3.0 Unported (CC BY-SA 3.0)](https://creativecommons.org/licenses/by-sa/3.0/) |
| Licence evidence | [`Marvel Cinematic Universe Wiki:Copyrights`](https://marvelcinematicuniverse.fandom.com/wiki/Project:Copyrights), revision 3728 — quoted in full in `manifest.json` |
| Retrieved via | `api.php`, `action=query&prop=revisions`; see `scripts/pull_snapshots.py` |

The version matters and was not assumed. `siprop=rightsinfo` reports only a bare `CC-BY-SA`
and links to a JS-rendered page, so it cannot distinguish 3.0 from 4.0; the wiki's own
`Project:Copyrights` states **3.0 Unported** explicitly, and that page is quoted verbatim in
the manifest so the claim is checkable without re-running anything.

## Modifications

`seed/` and `current/` are **unmodified** — byte-for-byte as the API returned them, each
pinned to the `revid` and `sha256` recorded in `manifest.json`.

Text this project *generates* — the agent's drafted section edits, and the seeded MediaWiki
instance built from `seed/` — **is** a modification of CC BY-SA 3.0 material. It therefore
carries the same licence, and any deployed instance must credit the MCU Wiki and link the
licence on the page. Share-alike is inherited, not optional.

## What is MIT

Everything else: `src/`, `tests/`, `scripts/`, and the project documentation. The code that
reads and rewrites the text is ours; the text is not.

## Reproducing

```bash
python3 scripts/pull_snapshots.py
```

`seed/` is pinned to historical revision ids and must come back byte-identical indefinitely
(verified). `current/` tracks the live wiki and is expected to change whenever editors touch
a page — that drift is the point, not a defect.
