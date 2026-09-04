# FE — the article, and the gate beside it

The hosted project URL. Two views over one JSON document:

| View | Route | What it shows |
|---|---|---|
| Wiki page | `#/wiki/<slug>` *(the default)* | The article, and only the article. **No agent detail at all** — just the floating **Continuity** button in the corner |
| The gate | `#/verify?page=…&live=1` | What the button opens, in a popup, and the only tool view there is. Opens idle with a **Run Continuity** button; two tabs — **Process** (the stages advancing) and **Changes** (each drafted edit as a git-style diff, with rationale, citations and confidence, then the publish bar) |

**The chrome belongs to the tool, not to the wiki.** A reader on `#/wiki/…` is looking at a wiki
page, and a toolbar belonging to the agent sitting on top of it would say this is the agent's
site — it is not. The only thing the agent puts on an article is the corner button. Everything
that is the tool — the run rail, the cards, the wiki picker and the
live/fixture pill — lives in the window that button opens. The footer stays on both, because it
carries the CC BY-SA attribution the wiki text is reproduced under.

**And chrome is not the only way agent detail leaks onto an article.** The article used to
highlight every tracked claim, stamp claim ids into the infobox, print the revision it was read
at, and carry a "Claims on this page" rail — none of which is a toolbar, all of which told a
reader what the agent had already concluded before they pressed anything. It is gone: a reader
arriving at an article sees a wiki page, presses the button, and *then* learns what the agent
thinks. `check.js` asserts the absence per page, because this is the kind of rule that decays
one convenient annotation at a time.

The wiki picker, in the popup's header, is the plug-and-play surface: the agent is pointed at a
wiki, not wired to one.

**The article's button opens the gate; the gate's button starts the run.** `renderWiki` puts
the corner button on the article; clicking it opens `#/verify?page=…&live=1` in a 960×980 popup
on this same origin. The popup opens **idle** — an untouched stepper, no cards, and a **Run
Continuity** button — and POSTs to `/api/runs` only when that is pressed, so the run and the
review it produces have one owner and one window.

**Opening is not asking.** The launcher used to pass `start=1` and the view fired a run on
sight, so every open spent a search per claim and several model calls before the reader had
decided they wanted one — and there was no way to reread a finished run without starting
another. Two presses, two meanings: open the gate, then run the agent.

**The press bills, and that is the point.** It used to run replayed by default, which meant the
button re-served a verdict recorded in `fixtures/` about claims it had not re-examined — on
screen that is indistinguishable from having just worked it out, so the one question the gate
exists to answer (*is anything wrong with this page now?*) could not come back "no" or come back
different. Pressing it spends a Parallel search per due claim and several model calls, and the
button says so beside itself. `&live=0` still replays, and replay remains the default for
`scripts/run_once.py`, where determinism is the point.

**Cards belong to a run.** The gate shows none until it has a draft of its own — it does not
adopt the newest stored one on the way in, `?draft=<id>` is how you reopen a particular run, and
pressing *Run again* clears the board first. An earlier run's answer sitting under a running
stepper reads as this run's finding, and there is no way to tell them apart on screen.

The view stacks three things. The **rail** is the stages as a stepper, and it now narrates a
run that is actually happening: `GET /api/runs/{id}` is polled once a second and each tick means
that stage *returned*, not that a timer reached it. With no live run it falls back to describing
the stored draft. A tick repaints the seven stage nodes **in place** (`paintRail`) rather than
re-rendering the view — `.stage` carries an entrance animation, so rebuilding them once a second
replayed it once a second, and the progress indicator strobed for the length of every run. The **cards** are the drafted edits. The **publish bar** is the last gate: per-card
Accept/Reject writes nothing, and one button over the accepted set does. Rejecting is a
*discard* — the card drops out of the run and nothing about it is sent anywhere, so what
survives the discards is the final draft and the bar publishes exactly that. The request body
is the reviewer's text and nothing else; the route reads the page and section from the queue
entry the id points at (`AGENTS.md` §2). The gate renders on our own origin, which is what keeps
`/api/*` same-origin with no CORS. **Publishing reloads nothing** — the wiki lives in the tab
(`wiki-api.js`), so a full page load would discard the very edits just published; it re-renders
instead.

**And the gate is a different window from the article, which the wiki has to know about.** The
popup is its own browsing context with its own copy of `wiki-api.js` and its own tables, so a
publish used to land in the popup's wiki and die with it while the article window — the one
being looked at — never saw the edit. That is indistinguishable from publish doing nothing. A
write is now announced on a `BroadcastChannel`, every other window applies it to its own tables,
and the article view drops its cached copy and repaints. Still no persistence: reload is still
the reset.

## Running it

No build step, no toolchain, no dependencies. Any static server:

```bash
python3 -m http.server 8000 --directory FE     # then open http://localhost:8000
```

Deployed, the same files are served by `StaticFiles` from the Python container that runs the
agent — one Cloud Run service, no second origin, no CORS.

## Where the data comes from

`app.js` fetches `/api/state` for claim counts and page provenance and falls back to
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
python3 scripts/build_wiki_db.py       # the wiki's tables, from snapshots/seed/
python3 scripts/ingest_baseline.py     # what the pages say -> mongo
python3 scripts/propose_claims.py      # what they assert -> mongo
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
reviewer can approve on. **The renderer is checked twice, and the second one is the one that
matters:** once over `demo-state.json`, which carries a display sample, and once over every
section of `data/wiki-db.json` — the article view's actual source. The corpus pass asserts on
the reader's text with tags stripped, and it exists because the sample pass was green while a
fifth of the real corpus printed `<small>`, `<br>`, `<gallery>` and raw table syntax at the
reader. The gate gets its own: `#/verify` shows exactly the cards for the page
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
wiki-api.js     # THE WIKI: MediaWiki's action API over in-memory tables
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
  dropped. `{{Quote}}` and `{{WPS}}` survive because they are content rather than layout.
- **HTML is a closed set of two.** `<br>` and `<small>` are kept; `<ref>`, `<gallery>`,
  `<nowiki>`, comments and everything else are removed before rendering rather than escaped,
  because an escaped tag is one the reader sees. `{| … |}` tables do render — six exist in the
  corpus doing three different jobs (data, two-column layout, collapsible lists) and a cell
  may hold a list, so cells re-enter the block renderer.
- **Page display is a convenience, not a product.** MediaWiki renders its own pages and its
  own `?diff=` views. Once the seeded instance is up, link through to it rather than growing
  this renderer.
- **Publishing writes, and the failures are shown rather than swallowed.** The wiki is
  `wiki-api.js` and lives here, so *the gate* performs each `action=edit` itself against the
  section as the page reads **now**, and reports an outcome per change to the server, which
  records it. Anything that is not `written` — the page
  moved, the drafted line is gone, the edit is already there — is named in the bar in the route's
  own words, because a gate that hid that would be claiming a write it did not make. Pressing it
  again writes only what is still outstanding. The queue only ever shrinks: publishing is the
  end of a run, and nothing downstream of it adds cards.
- **The scoped run view publishes the whole draft.** `#/verify?page=…` filters the cards to one
  page, but the draft is the unit of publication, so the bar counts the whole run and says how
  many more are waiting elsewhere. That is deliberate — publishing half a reviewed run is what
  the gate exists to prevent — but it means the popup opened from one article can be held up by
  a card on another.
- **The card shows the verdicts, and one thing it deliberately does not flag.** `bucket`,
  `shape` and every flag render as chips above the diff, and a `conflicting` card carries the
  disagreement itself — the note and both sources — in a callout above it, so a reviewer
  deciding whether to take the edit can see what was contested without opening the ledger.
  What is *not* flagged is a plain destructive edit on a conflicting claim: `overreached` fires
  only for a `new` claim, because a conflicting one's page may legitimately be wrong, so an
  edit that replaces text arrives with no warning beyond the red rows in the diff. That is a
  decision rather than a gap — the diff is the warning, and the reviewer rejects what makes no
  sense (Aug 30, 2026).
- **The diff is two-way, and there is no merge UI.** The project assumes a single editor while
  the agent runs (`AGENTS.md` §2), so the page at publish time is the revision the draft was
  taken against and a text conflict cannot arise. There are no conflict markers and no
  keep-ours/keep-theirs control; if the assumption is violated, the write is refused by
  `basetimestamp` and the claim is re-drafted. The only conflict a reviewer resolves is the
  semantic one — two sources disagreeing — and that is a choice between readings, not text.
