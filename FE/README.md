# FE — review queue, ledger and page views

The hosted project URL. Three views over one JSON document:

| View | Route | What it shows |
|---|---|---|
| Review queue | `#/queue` | Each drafted edit with its diff, rationale, citations and confidence — the publish gate, with approve/reject |
| Claim ledger | `#/ledger` | Every tracked claim: status, wave, confidence, recheck interval and next check |
| Wiki pages | `#/wiki/<slug>` | The seeded page as a reader sees it, with each claim's anchor highlighted in place |

The wiki picker in the header is the plug-and-play surface: the agent is pointed at a wiki,
not wired to one.

## Running it

No build step, no toolchain, no dependencies. Any static server:

```bash
python3 -m http.server 8000 --directory FE     # then open http://localhost:8000
```

Deployed, the same files are served by `StaticFiles` from the Python container that runs the
agent — one Cloud Run service, no second origin, no CORS.

## Where the data comes from

`app.js` fetches `/api/state` and falls back to `data/demo-state.json` when there is no
backend. Same shape either way; the pill in the header says which one is live. That fallback
is the rule in `CLAUDE.md` §3 — a demo must not break because a key expired.

Rebuild the fixture with:

```bash
python3 scripts/build_demo_state.py
```

That script reads `snapshots/`, so **page text is verbatim from the committed corpus** —
nothing here is retyped. It also builds real `Claim` objects and drives them through the real
transitions in `backend/core/ledger/`, so every status, confidence score and recheck
interval on screen is computed by the core rather than typed into a fixture. It fails the
build if a claim's `wikitext_anchor` is not present in the seed snapshot, because an anchor
that does not exist is an edit that could never apply.

**STUB:** the claims and their citations are hand-built and stand in for an agent run that has
not happened. The fixture is marked `"stub": true` and the page shows a banner saying so.
Citations are real URLs drawn from the corpus with real tier lookups, but their excerpts are
placeholders — no research has been performed.

## Checking it

```bash
node FE/check.js
```

Node is used to *check* the FE, never to build or serve it — the container ships these files
as-is. The checks are counts and equalities, not eyeballing (`CLAUDE.md` §5): balanced block
tags, no wikitext leaking into rendered output, every claim anchor highlighted exactly once,
one queue card per drafted edit, every element `app.js` looks up present in `index.html`,
every class used actually styled, and no external requests.

## Files

```text
index.html      # shell: header, nav, mount point
styles.css      # all styling; no framework, no external fonts
wikitext.js     # a deliberately partial wikitext -> HTML renderer
app.js          # state loading, routing, the three views
check.js        # verification (see above)
data/           # demo-state.json, generated — do not hand-edit
```

## Licensing

Application code here is MIT, like the rest of `backend/`, `tests/` and `scripts/`.

The **wiki text it displays is not ours.** It comes from the Marvel Cinematic Universe Wiki
and is reproduced under [CC BY-SA 3.0 Unported](https://creativecommons.org/licenses/by-sa/3.0/).
The full notice, including how the licence carries onto the agent's own edits, is in
`snapshots/ATTRIBUTION.md`. Every rendered page carries an attribution line, and so does the
site footer.

The layout borrows the *conventions* of a wiki article — one reading column, an infobox card
at the top right, headings with a rule beneath. None of Fandom's stylesheet, colours, logos or
images are used or reproduced; `styles.css` is written from scratch and the page loads no
external asset of any kind.

## Deliberate limits

- **Templates are not expanded.** There is no template store, and a half-expanded template
  reads worse than none. Infobox values are flattened to their parameters; everything else is
  dropped. `{{Quote}}` survives because it is content.
- **Page display is a convenience, not a product.** MediaWiki renders its own pages and its
  own `?diff=` views. Once the seeded instance is up, link through to it rather than growing
  this renderer.
- **Approve/reject is in-memory.** It marks the card and nothing else. The publish stage that
  turns an approval into `action=edit&section=N` is not built yet.
