# FE — review queue, ledger and page views

The hosted project URL. Three views over one JSON document:

| View | Route | What it shows |
|---|---|---|
| Review queue | `#/queue` | Each drafted edit as a git-style diff — removed lines red, added green, changed words marked — with its rationale, citations and confidence. **The Verify gate** (`summary.md` §6): approve, edit the draft in place, or reject |
| Claim ledger | `#/ledger` | Every tracked claim: status, wave, confidence, recheck interval and next check |
| Wiki pages | `#/wiki/<slug>` | The seeded page as a reader sees it, with each claim's anchor highlighted in place |
| Run view | `#/verify?page=…&rev=…` | The eight stages of the run with their counts, then the queue filtered to one page, then the publish bar. Site chrome stripped. What the floating **Continuity** button on the wiki opens, in a popup |

The wiki picker in the header is the plug-and-play surface: the agent is pointed at a wiki,
not wired to one.

`#/verify` is how the gate is reached from the wiki itself. `wiki-config/continuity-launcher.js`
is installed onto our instance as `MediaWiki:Common.js` and puts a floating **Continuity**
button in the article's bottom-right corner; clicking it opens this route in a 960×980 popup,
passing the page and the revision the reader was on.

The view stacks three things. The **rail** is the eight stages of `summary.md` §6 as a stepper,
ticked through Diff with a count under each — and every count is derived from the claims and
queue being rendered, so it describes the run that produced what is on screen rather than
animating a fiction. The stagger is a CSS `animation-delay`, not a timer driving a fake state
machine. The **cards** are the drafted edits. The **publish bar** is the last gate: per-card
Accept/Reject writes nothing, and one button over the accepted set does. Rejecting is a
*discard* — the card drops out of the run and nothing about it is sent anywhere, so what
survives the discards is the final draft and the bar publishes exactly that. The request body
is the reviewer's text and nothing else; the route reads the page and section from the queue
entry the id points at (`AGENTS.md` §2). The gate renders here rather than inside MediaWiki so that
the draft routes stay same-origin (`AGENTS.md` §2) — that is the reason it is a popup and
not a panel. `window.opener` is kept on purpose: after a successful publish the gate reloads the
article behind it. The same URL works from a bookmarklet on a wiki we do not control.

## Running it

No build step, no toolchain, no dependencies. Any static server:

```bash
python3 -m http.server 8000 --directory FE     # then open http://localhost:8000
```

Deployed, the same files are served by `StaticFiles` from the Python container that runs the
agent — one Cloud Run service, no second origin, no CORS.

## Where the data comes from

`app.js` fetches `/api/state` for the ledger and page views and falls back to
`data/demo-state.json` when there is no backend. Same shape either way; the pill in the header
says which one is live. That fallback is the rule in `CLAUDE.md` §3 — a demo must not break
because a key expired.

**The queue is different: it comes from a store.** `/api/drafts` lists the runs,
`/api/drafts/{id}` returns one with its verdicts and hand-edits, and every accept, reject and
edit is written straight back to `/api/drafts/{id}/changes/{edit_id}`. So a reload lands on the
run exactly as it was left, and a discarded card is not offered again. When no draft is
reachable the fixture's queue still renders — the cards are worth showing — but the publish bar
says there is nothing to publish rather than offering a button that would post into the void.

Rebuild the fixture, then load it into the store:

```bash
python3 scripts/build_demo_state.py
python3 scripts/seed_drafts.py
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
every class used actually styled, and no external requests. The diff rows get their own check:
concatenating the context and removed rows must reproduce `before` exactly and the context and
added rows `after`, because a diff that cannot round-trip its own input is not something a
reviewer can approve on. The gate gets its own: `#/verify` shows exactly the cards for the page
it was opened from and no others, its textarea is seeded with the agent's text character for
character, and the launcher keeps the contract the popup depends on — no committed origin, no
`noopener` on the `window.open` that would silently sever the reload, and every CSS rule it
injects into a skin we do not own scoped to our own button. The rail is checked against the
state it claims to describe rather than against a screenshot: eight stages, five ticks, and
claim/source/conflict counts recomputed from the payload. Three checks guard the two-level gate
— `decide()` must not mention `/publish`, it *must* write its verdict back to the store, and
exactly one `/publish` call may exist in the whole file, inside `publishAll`. One more asserts
that call has no body at all: everything the write is made from comes from the stored draft.

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
- **Publishing writes, and the failures are shown rather than swallowed.** One request
  publishes the draft; the server writes each accepted change into the section as the page reads
  *now*, and answers with an outcome per change. Anything that is not `written` — the page
  moved, the drafted line is gone, the edit is already there — is named in the bar in the route's
  own words, because a gate that hid that would be claiming a write it did not make. Pressing it
  again writes only what is still outstanding. What is still missing is the *other* direction:
  fan-out runs after the gate, so an applied edit should also **add** cards for the claims it
  implicates on other pages, and today the queue only shrinks.
- **The scoped run view publishes the whole draft.** `#/verify?page=…` filters the cards to one
  page, but the draft is the unit of publication, so the bar counts the whole run and says how
  many more are waiting elsewhere. That is deliberate — publishing half a reviewed run is what
  the gate exists to prevent — but it means the popup opened from one article can be held up by
  a card on another.
- **The queue shows the diff but not the verdicts on it.** This is the same gap as above seen
  from the rendering side. `Draft.payload()` carries `bucket`,
  `shape` and `flags`, and `Review.payload()` carries the idea-level `verdict` and its
  per-assertion changes (`summary.md` §6). The queue renders none of them, so a card flagged
  `overreached`, `uncited` or `hidden_by_text` currently looks exactly like a clean one — which
  defeats the point of computing the flag. `hidden_by_text` matters most: the diff renders green
  and the edit reversed what the passage asserted, so the rendering a reviewer trusts is the one
  actively misleading them.
- **The diff is two-way, and there is no merge UI.** The project assumes a single editor while
  the agent runs (`AGENTS.md` §2), so the page at publish time is the revision the draft was
  taken against and a text conflict cannot arise. There are no conflict markers and no
  keep-ours/keep-theirs control; if the assumption is violated, the write is refused by
  `basetimestamp` and the claim is re-drafted. The only conflict a reviewer resolves is the
  semantic one — two sources disagreeing — and that is a choice between readings, not text.
