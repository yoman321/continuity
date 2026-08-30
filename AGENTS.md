# AGENTS.md — fandom wiki maintainer agent

Project-specific half of the working rules. Universal rules are in `CLAUDE.md`; product
truth and rationale are in `summary.md`. Nothing here restates either.

## 1. What this is

An agent that keeps a fandom wiki current. It decomposes wiki pages into atomic claims,
re-verifies them against the live web, adjudicates contradictory sources, and drafts
section-level edits with citations and a confidence level — flagging honestly when sources
disagree rather than always producing an answer. Audience: wiki maintainers.

Built for **Agentic Cinema: The Blockbuster Hackathon** (Google Cloud x Devpost).
Deadline **Sept 7, 2026, 2:00 PM PT**. Parallel track. Demo subject: *Deadpool & Wolverine*,
seeded from real MCU Wiki revision history frozen at 2024-08-09 (`seed-plan.md`).

## 2. Project invariants

Violating one of these means a rewrite, a ban, or a disqualification — not a patch.

- **Every `model=` string is `gemini-*`.** ADK ships adapters for the platform's non-Google
  catalog; the rules ban them outright. Never pin `gemini-2.5-flash` (shutdown 2026-10-16,
  judging ends Oct 07).
- **One model everywhere: `gemini-3.5-flash`.** No pro tier and no per-node split. Measured
  Aug 22 2026 on the Classify task against the seed corpus (4 cases, 6 reps): 3.5-flash 24/24
  at p50 3.78s, 3.6-flash 22/24, 3.7-flash 21/24, and `gemini-3.1-pro-preview` 12/24 — pro
  reads the claim sentence literally and returns `still_true` where retrieval carries an
  adjacent new fact. Single pin also keeps every model out of `-preview`, which cannot be
  relied on through judging (Sept 23 – Oct 7). Reasoning and the raw numbers: `summary.md` §12.
- **Parallel is the only path to the outside world.** All retrieval — discovery *and*
  re-verification — goes through the `parallel-web` SDK directly. Not LangChain's
  `ParallelWebSearchTool`, not the Vercel AI SDK tools: the Parallel page lists both as
  satisfying the track, but the AI-usage clause bans third-party agent frameworks and the
  plain SDK already satisfies it. Gemini never fetches. Exactly one partner track is
  permitted, so no second partner may be used for its AI features.
- **The publish request decides nothing. It has no body.** Judging requires
  `--allow-unauthenticated`, so `POST /api/drafts/{id}/publish` is public and there is no
  session to identify a reviewer by. Everything the write is made from — which changes were
  accepted, their text, their pages, their anchors and their edit summaries — is read from the
  stored draft, so the most a stranger who guesses a draft id can do is publish a review a
  person already accepted. An unknown id is a 404 before anything is read. Never add a
  parameter to that route: a page, a section or a text on the wire turns a review gate into a
  public write primitive. The decision route beside it takes a verdict and the reviewer's own
  text and nothing else, with unknown fields refused rather than ignored.
- **Never write to any real wiki.** Unsanctioned bot edits get banned, and Wikipedia is
  stricter than Fandom — automated editing needs Bot Approval Group sign-off. All writes go to
  our own seeded MediaWiki instance, whatever wiki the profile points reads at. This is a
  field, not a convention: `WikiProfile.writable` is `True` only for `local_wiki()`, the
  factory for our own instance, and a test asserts every shipped profile is `False`. The write
  path checks the field. `local_wiki()` takes its endpoint as a required argument with no
  default, because the URL is a deployment identifier and belongs in `.env` alone.
- **Wiki-specific behaviour lives in a profile, never in the core.** The product is
  plug-and-play across MediaWiki sites (`summary.md` §5), so title grammar, section
  vocabulary, source tiers, licence and auth are per-wiki config the core reads. A hardcoded
  Fandom assumption in shared code is a rewrite, not a patch — it silently produces confident
  wrong output on the next wiki. Built Aug 23, 2026: `backend.core.profile.WikiProfile` carries
  all six, and `MCU_FANDOM` / `WIKIPEDIA_EN` are the two shipped instances. The dependency
  runs one way: `profile/` imports the core, and the core must never import `profile/` **at
  runtime** — a `TYPE_CHECKING` reference for a signature is fine (`wiki/client.py` has one),
  an unguarded one is not. `tests/test_profile.py` asserts it, because an import direction is
  exactly the kind of thing that inverts by accident in a later refactor.
- **Section-level edits only, never full-page rewrites — and never create a section.** Full
  rewrites get reverted by wiki communities and are illegible in a 3-minute video. Adding a
  section the wiki's convention does not have (Box office, Reception, Accolades — absent from
  every MCU Wiki film page) gets reverted just as fast. Patch sections that exist; if a fact
  has no home on the page, it is out of scope, not a new heading.
- **Source tiers and decay intervals are deterministic code, not model output.** Tiers are a
  domain → tier lookup table; the poll interval is `double on no-change, halve on change,
  clamp [6h, 6mo]`. Gemini reasons *over* the tiers; it never invents them per call. Handing
  either to the model makes the headline behaviour unreproducible on camera.
- **The ledger store stays schema-flexible.** ADK 2.0 added `node_info` and `output` to the
  Event schema; rigid SQL columns fail on insert or ORM deserialize. Prefer Firestore, or
  migrate columns before first run.
- **The ledger runs local first and ports to Firestore; the document shape is what ports.**
  `JsonFileClaimStore` is the local database and `InMemoryClaimStore` the deterministic
  fallback, both writing the documents `core/ledger/documents.py` defines — the exact value
  types Firestore accepts, so the adapter hands a document to `.set()` untranslated. Two rules
  make the local store *behave* like the remote one rather than merely stand in for it, and
  both are asserted in `tests/test_ledger_store.py`: a stored claim always has a
  `next_check_at` (`require_scheduled`), and `due()` filters and orders on that one field
  only. Neither is a preference — see §6. Never let a store decide anything: `Claim.is_due`
  and the transitions in `schema.py` do the deciding, and this layer is storage.
- **Assume a single editor while the agent runs — decided Aug 29, 2026, and it is a hackathon
  assumption, not a property of the system.** Nobody else edits a page between the read that
  drafts an edit and the write that publishes it. What that buys: the page at publish time *is*
  the revision the draft was taken against, so there is no third side to reconcile and the
  review queue never has to ask a human to resolve a text conflict. The diff is two-way
  (`core/wiki/diff.py`), and "publish all approved edits" needs no atomicity story — MediaWiki
  has no transaction across pages, and under this assumption it does not need one. What it
  costs, if the assumption is wrong: `WikiWrite.write_section` still sends `basetimestamp` and
  still returns `conflict` as a value, so a concurrent edit fails loudly and is not overwritten
  — the guard stays, the *flow* is what was dropped. Publishing a batch after a real concurrent
  edit means some rows land and one comes back conflicted, and the reviewer re-drafts it. Do not
  build three-way merge, conflict markers or per-row rollback for the demo; do write the
  assumption into the submission description, because a judge editing the wiki mid-run is
  exactly how it gets discovered.
- **Verify is the human gate and holds no model call — decided Aug 30, 2026, a hackathon
  simplification.** No stage checks whether a drafted edit contradicts something elsewhere on the
  page; Verify used to and no longer does. What it is now: the run's HITL pause, where **every
  section with a diff is a card the reviewer accepts or rejects**, having read it beside the Diff
  stage's flags and **edited the draft text in place** if they wanted to. Publish is then a
  button —
  `POST /api/drafts/{id}/publish` — and remains the only thing that writes to the wiki. Putting a
  model back into Verify is a design change and not a patch: it reinstates a `Verify → Draft`
  backward edge, and termination currently rests on the one-hop fan-out rule alone. The accepted
  cost is written up in `summary.md` §6 — an edit clean at its anchor that contradicts a sentence
  three sections away ships unless a person sees it — and it belongs in the submission
  description for the same reason the single-editor assumption does.
- **The graph runs six stages and stops at Verify — decided Aug 30, 2026.** `agent/graph.py`
  is one ADK `Workflow`: Audit, Research, Classify, Draft, Diff, Verify. **Publish and Fan-out
  are not nodes and must not become them.** Publish is a button on a route, and a node that
  wrote to the wiki would make the gate optional — which is the one thing the whole publish
  path rests on; Fan-out has nothing to expand until an edit has actually been applied, and
  that happens after this run has ended. Verify does not *pause* the run either, which an
  earlier plan had it doing through `request_input`: Cloud Run scales to zero and the tick is
  hourly, so a coroutine waiting on a reviewer dies at the first idle timeout while a stored
  `ReviewDraft` survives the container, the reload and the week. Verify's node writes the draft
  and the invocation finishes — the pause is the store, and the resume is the publish route.
  One backward edge is in play, `Classify → Research`, and it fires on exactly one signal: a
  `conflicting` verdict where filtering dropped *every* excerpt, which is retrieval having gone
  off-subject rather than the world disagreeing with itself. A real conflict routes to a person
  and never to a retry. It is bounded in the Research node, which is the only thing anywhere
  that refuses a fourth round — `record_research` spends one without consulting the budget.
- **The gate reaches the wiki as a tab, not as an embedded panel — decided Aug 30, 2026.**
  `wiki-config/continuity-launcher.js` is installed onto our own instance as
  `MediaWiki:Common.js` and does exactly one thing: it puts a floating **Continuity** button in
  the article's bottom-right corner that opens `#/verify?page=…&rev=…` in a popup window. A
  corner button rather than skin chrome, because it stands in for the browser extension a real
  deployment would ship and survives a skin change. The gate itself renders on *our* origin,
  never inside MediaWiki's DOM, and that is the invariant: it keeps `/api/state` and the draft
  routes same-origin, so the app keeps the "one origin, no CORS, no second
  deploy" shape `backend/app.py` is built on (§3), and `FE/styles.css` never has to survive a
  collision with a skin's stylesheet. Rendering the gate in the page — a browser extension, an
  injected panel — means adding CORS to the API, and that is a deployment change, not a
  frontend one. The popup must keep `window.opener`: the gate reloads the article behind it
  after a publish, which is how the reviewer sees the write land. A bookmarklet firing the same
  URL is the supported path on a wiki we do not control; no extension exists or is planned.
- **Accepting a card writes nothing; the publish bar is the only writer — decided Aug 30,
  2026.** The gate has two levels on purpose. Per-card **Accept / Reject** decides *what* would
  go and is held in the browser; one **Publish** button at the foot of the run then writes the
  accepted set, and it only unlocks once every card has a decision — enforced by the route and
  not only by the button, because a gate that lives in a browser is not a gate. **A rejection is
  a discard, not a verdict on the claim**: the card drops out of the publishable set, and the
  claim behind it stays exactly as it was (see `ClaimStatus` below). Verdicts and hand-edits are
  written to the draft store as they are made, so the run survives a reload; what must never be
  written is a decision on the *claim*. That last press is the
  point of no return, and until it happens the reviewer can still discard the whole run — which
  is what makes a per-card accept safe to give quickly. A card that POSTs on accept is the bug
  this rules out: it removes the batch review the reviewer was promised. Publishing is one
  request over the draft, which the server turns into one `action=edit` per accepted change, in
  order, because MediaWiki has no cross-page transaction — a partial failure is a real outcome,
  is reported per change, and is never rolled back.
- **`ClaimStatus` is `verified` or `unresolved`, and nothing else.** It answers one question —
  does a human need to look at this — so a third value is always a different question wearing
  the same field. Where an edit sits in the publish pipeline is the *queue's* state; a rejected
  edit leaves the claim untouched, so the claim never needed to know. Age is `now >=
  next_check_at`, a comparison rather than a stored state. Adding `drafted`, `applied` or
  `exhausted` back is a rewrite, not a patch: `exhausted` collapsed into `unchanged` because no
  new data is no change, and a rejected draft is `unchanged` for the same reason — there is no
  `rejected` transition and there should not be one. Reasoning in `summary.md` §6.
- **A draft is one document, and it owns the whole review.** `ReviewDraft` holds every change a
  run proposes, the verdict on each, the revision each one wrote, and one `published_at` for the
  set. One document rather than one per change, because Publish is a single act over the
  accepted set and "every card decided" is a property of the set. Three consequences that are
  not negotiable: `written_revid` is stored, so a publish that partially failed retries only
  what is outstanding rather than rewriting what already landed; `published_at` is stamped only
  when every accepted change is written *and* at least one was accepted, so a fully discarded
  run never reads as published; and the diff is never stored, because it is a view of
  `before`/`after` that a hand-edit invalidates.
- **The ledger has four collections: `sections` (what the page says), `claims` (what the agent
  tracks), `judgements` (why each claim was routed as it was) and `drafts` (what a run proposed
  and what the reviewer decided).** They are written at different times by different things and must not be
  merged. The baseline is *deterministic* — read the page, split it, store the sections
  verbatim — so step 1 of a run needs no model, no key and no judgement, and a claim is later
  proposed *against* a baseline that already exists. Sections are replaced per page as one set,
  because indices are only meaningful relative to each other: insert a heading at the top and
  everything below renumbers, so merging a fresh read into old rows files one section's text
  under another's index, wrongly and silently. `content_hash` is stored rather than recomputed
  — the one exception to "derived values are never stored" — because Firestore filters on a
  field it holds and not on one it would have to hash first. `judgements` is the newest and the
  only one that is pure history: **one document per classification**, keyed by task, claim and
  attempt, never read back by any stage, and appended to rather than updated. A claim judged on
  two runs is two rows, and a claim reclassified *within* one run is two rows as well — what
  was said, when, and what replaced it *is* the record.
- **Every document names the task that wrote it — decided Aug 30, 2026.** A *task* is one pass
  of anything that writes to the ledger: a graph run, a baseline ingest, a seeding script. It
  mints one id (`core/ledger/documents.task_id_for`) and every document it creates or modifies
  carries it, across all four collections — so a row answers "where did this come from" without
  a log, and a run's whole footprint is one query. Three rules keep it honest. The id is minted
  **once per task, never per write**, at the start, from the same clock the task stamps its
  timestamps with. The value is **bound, never passed as an argument**: `Ledger` takes it at
  construction like the profile, because a task is not something a model may name, and every
  path to the claim store goes through one stamping helper so provenance cannot be remembered
  on three transitions and forgotten on the fourth. And it carries **milliseconds** — seeding
  the ledger and then running the graph takes well under a second, and at second resolution the
  two tasks came back with the same id, which would have had one silently overwriting the
  other's judgements. Nothing branches on a `task_id`: it is provenance, not state, and a stage
  that read one would be reading a copy of something `Claim` already holds.
- **A profile names the pages it monitors (`WikiProfile.pages`).** The agent is not a crawler:
  which pages we maintain is a decision, not something to infer from a category listing. It
  lives on the profile beside `section_vocabulary` because it is per-wiki config, and because
  an empty ledger with no page list is an agent with nothing to do.
- **No document states a tracked-claim count.** A claim is tracked
  once a full pipeline run has proposed it, checked it and written it back — so how many exist
  is an output, not an input. A planned total is a number no code produces: it goes stale the
  first time a run disagrees with it, and it makes a working demo read as under-populated
  against a target nothing ever committed to. Say what *kinds* of claim the seed carries
  (`seed-plan.md` §3) and which specific ones the video needs (§4); never how many there are.
  The six in `FE/data/demo-state.json` are the fixture described in §4 below, not a partial
  ledger.
- **The wiki is external, including our own — decided Aug 29, 2026.** The agent gets no
  privileged path to the instance it writes to. `local_wiki()` sets `requires_key=True`, both
  adapters refuse to *construct* without one (`MEDIAWIKI_API_KEY`), and the credential travels
  in an `X-API-Key` header — never a query parameter, because a URL is logged by every proxy it
  passes and lands in error messages. `requires_key` is a fact about the endpoint, so Fandom's
  open API stays keyless and must not start carrying a credential it never asked for. **Be
  honest about what this is:** MediaWiki does not validate the header today, so the gate is
  ours — what is real is that the endpoint is configured, the credential is required, the
  failure is at construction rather than at the first unauthorised request, and the secret
  flows through `.env`/Secret Manager like every other. Pointing this at a wiki that genuinely
  gates reads is then a value in `.env`, not a code change. If real enforcement is ever wanted,
  the upgrade is MediaWiki's own: `$wgGroupPermissions['*']['read'] = false` in
  `wiki-config/`, and the bot login the writer already performs. `snapshots/` needs no key
  because it is a committed corpus, not a service.
- **Secrets:** `.env` locally (gitignored), Secret Manager when deployed. Gemini uses ADC —
  no API key exists on either side. Parallel and MediaWiki credentials are real secrets.
- **Anything configured in `.env` is named only in `.env`.** The GCP project id, the wiki API
  URL and the bot user are not credentials, but the repo is public and they are deployment
  identifiers, not product facts — so docs, commit messages and code refer to "the project in
  `.env`" and read the value at runtime. `.env.example` lists the keys with empty values; that
  is the whole public surface.
- **The scheduler endpoint authenticates itself, because IAM cannot.** Judging requires the
  service be `--allow-unauthenticated`, which makes *every* route public — including the one
  Cloud Scheduler posts to. `/internal/tick` must compare a shared secret with
  `hmac.compare_digest` before doing any work. Without it, anyone who guesses the path can
  trigger unbounded agent runs against a metered Gemini account. This is not hardening to add
  later; an unguarded tick route is a live credit leak the moment the URL is published.

## 3. Stack

| Layer | Choice |
|---|---|
| Orchestration | ADK 2.x Workflow Runtime (`google-adk` ≥2.6.3) — stages as graph nodes |
| Model | `gemini-3.5-flash` everywhere — measured, not assumed (§2) — via `google-genai` |
| Auth | Enterprise/ADC — no API key. `GOOGLE_GENAI_USE_ENTERPRISE=true` (§5) |
| Retrieval | Parallel Search via `parallel-web`, wrapped as an ADK tool |
| Wiki I/O | MediaWiki API — `action=query&prop=revisions` reads raw wikitext, `action=edit` with section param writes it |
| Ledger | A local JSON file now, Firestore after the deploy weekend (§2). The Cloud SQL instance in the topology is MediaWiki's alone |
| Scheduling | Cloud Scheduler → Cloud Run endpoint, hourly; interval logic lives in the ledger |
| Secrets | Secret Manager — Parallel key, wiki bot credentials |
| Frontend | Vanilla HTML/CSS/JS in `FE/` — no framework, no build step, no dependencies |
| Hosting | One Cloud Run service: FastAPI serves `FE/` *and* runs the agent. Scale-to-zero |

Why each was chosen, and what was rejected: `summary.md` §6 and §12.

### Runtime topology

Two Cloud Run services, both scale-to-zero, both in `us-east1`, plus the one Cloud SQL
instance that cannot. Nothing else runs.

```text
  continuity                                  <-- the public project URL
    FastAPI, python:3.12-slim
      GET  /                 StaticFiles over FE/        (no build step; ships as-is)
      GET  /api/state        ledger + page text from Firestore
      GET  /api/drafts       the runs waiting at the gate; {id} for one, with its verdicts
      POST /api/drafts/{id}/changes/{edit_id}
                             a verdict, the reviewer's own text, or both. Writes no wiki
      POST /api/drafts/{id}/publish
                             Publish: the Verify gate's button. No body — the accepted
                             changes -> action=edit&section=N. The only route that writes
      POST /internal/tick    Cloud Scheduler, hourly, shared-secret header (§2)
    runtime SA: continuity-run@  — aiplatform.user, datastore.user, secretAccessor

  mediawiki                                   <-- the wiki the agent edits; never a real one
    MediaWiki on Cloud SQL (MySQL, shared-core), over the Cloud SQL connector
    --max-instances 1; the service scales to zero, its database does not

  Firestore (ledger: sections, claims, judgements, drafts)
  Cloud SQL (MediaWiki's DB, and nothing else)
  Secret Manager (Parallel key, tick token, bot password, wiki API key)
  Cloud Scheduler (1 job)   Artifact Registry (2 images)
```

That is the target shape. `backend/app.py` serves `/` and runs the gate for real: the four
draft routes read and write a document store (`GET /api/drafts`, `GET /api/drafts/{id}`,
`POST /api/drafts/{id}/changes/{edit_id}`, `POST /api/drafts/{id}/publish`), and publishing
writes to our own MediaWiki through `WikiWrite`. `DRAFT_STORE` picks the store — the local JSON
file or Firestore, holding identical documents — so the port is a value in `.env` and not a code
path. `/api/state` and `/internal/tick` are written and guarded but have nothing behind them
yet, so they answer 503/501 (§4).

Rules that fall out of this shape:

- **One container serves the frontend and runs the agent.** `FE/` is static, so there is no
  second origin, no CORS and no second deploy. Do not split them.
- **Region is `us-east1` for Cloud Run, Firestore and Cloud SQL.** Gemini is the exception —
  `location="global"`, never a region (§5).
- **`--min-instances 0`, always — and `--max-instances 3`.** Zero is what makes idle cost
  nothing: Cloud Run bills per request-second, so an unwatched demo is free. Raising it to 1 to
  hide the cold start bills an instance around the clock and turns ~$1/mo into tens of dollars;
  the sanctioned fix for cold start is the lazy imports in §7. The ceiling stops a stuck
  research loop from draining the credits. Numbers in `summary.md` §6.
- **MediaWiki runs on Cloud SQL, and it is the only thing here that bills while idle.**
  SQLite on a mounted GCS bucket was the plan until Aug 23, 2026; it does not work. gcsfuse
  implements neither file locking nor partial random writes, which are the two things SQLite
  depends on, so the failure mode is a corrupted database found after seeding rather than an
  error at mount. Do not retry it, and do not reach for Firestore either — MediaWiki speaks
  MySQL, PostgreSQL or SQLite and nothing else. ~$16 through judging, covered by the credits
  (`summary.md` §6).
- **Gemini tokens are the only cost that can run away.** Cloud SQL is a fixed ~$16 through
  judging and every other line above sits inside a free tier at demo traffic; the per-item
  breakdown is in `summary.md` §6, and its figures are from recall rather than the console.
  Set the $25 budget alert before the first deploy, not after.

## 4. File map

<!-- One line per file: path # what it owns. Mark entry points "<-- read first".
     Update in the same task that moves a file. A stale map is worse than no map. -->

```text
  backend/                           # the whole Python app: core + perimeter, one package
    __init__.py                      # <-- read first: the pure/perimeter rule. Import-free
    app.py                           # the routes: state, drafts, publish, tick; FE/ last
    firestore.py                     # DraftStore over Firestore; SDK imported in the ctor
    core/                            # ===== the deterministic half. No vendor, no network =====
      ledger/
        schema.py                    # <-- read first: Claim, the record everything else serves
        judgements.py                # why a claim was routed as it was: one per claim per
                                     #   task. History; no stage ever reads one back
        drafts.py                    # the review draft: changes, verdicts, published_at,
                                     #   the document codec and the two local stores
        tiers.py                     # tier *mechanism*; the table itself is per-wiki
        decay.py                     # Wave, and the double/halve/clamp interval logic
        citations.py                 # which source may go in the <ref>; NOT which is best
        documents.py                 # the stored shape; Firestore types only, both stores read
                                     #   it. Also `task_id_for`: one id shape for every writer
        store.py                     # ClaimStore, the in-memory store, and the local JSON file
        baseline.py                  # SectionBaseline: what the page says now, per section
      profile/
        schema.py                    # <-- read first: WikiProfile, everything per-wiki
        known.py                     # MCU_FANDOM, WIKIPEDIA_EN, and local_wiki() — ours
      wiki/
        client.py                    # MediaWiki read + write adapters; network in fetch/post
        sections.py                  # wikitext -> the sections action=edit&section=N addresses,
                                     #   and the anchor substitution a published edit is
        snapshots.py                 # PageSource, and the offline reader over snapshots/
        diff.py                      # red/green rows for a drafted edit, and shape(); stdlib
                                     # ===== everything else under backend/ is perimeter =====
    agent/
      graph.py                       # <-- read first: the six stages as ADK nodes, the
                                     #   one backward edge, and where the run stops
      ingest.py                      # step 1 of a run: pages -> sections -> the baseline
      model.py                       # the Gemini perimeter: one call, JSON schema, a cassette
      classify.py                    # the classify stage: the prompt's four measured rules
      draft.py                       # the draft stage: rewrites the anchor, checks its shape
      semantic_diff.py               # the diff stage: what the edit did to the *ideas*
      tools/
        wiki_read.py                 # outline + section reads, live or from snapshots/
        web_search.py                # Parallel; the profile's tier table IS the source policy
        wiki_write.py                # action=edit by heading, whole section or one anchored
                                     #   line; conflict comes back as a value
        ledger.py                    # claim state; outcomes not schedules, ids from the store
  Dockerfile                         # the runtime image; copies pyproject/backend/FE only
  .gcloudignore                      # what Cloud Build does NOT receive; includes .gitignore
                                     #   rather than repeating it, so there is one secret list
  pyproject.toml                     # deps, ruff + mypy config, gate settings
  scripts/setup_wiki.sh              # installs the local MediaWiki natively; idempotent
  scripts/seed_wiki.py               # loads snapshots/seed/ into it, then verifies the hashes
  wiki-config/                       # the wiki's settings, version controlled
    LocalSettings.overrides.php      # subpages, licence, bot rights — required by the install
    continuity-launcher.js           # the floating Continuity button; -> MediaWiki:Common.js.
                                     #   Origin is a placeholder here — never a committed URL.
                                     #   Every injected CSS rule is prefixed; check.js proves it
  scripts/install_launcher.sh        # substitutes the origin, pushes it via maintenance/edit.php
  wiki/                              # GITIGNORED: the MediaWiki tree itself, a build artifact
  data/ledger.json                   # GITIGNORED: the local ledger's claims. Run state
  data/baseline.json                 # GITIGNORED: the local ledger's sections. Run state
  data/drafts.json                   # GITIGNORED: the local ledger's drafts. Run state
  data/judgements.json               # GITIGNORED: why each claim was routed. Run state
  scripts/seed_drafts.py             # fixture queue -> one reviewable draft; also the demo reset
  scripts/pull_snapshots.py          # rebuilds snapshots/ from the live API; re-runnable
  scripts/build_demo_state.py        # snapshots/ + ledger core -> FE/data/demo-state.json
  scripts/ingest_baseline.py         # fills data/baseline.json from snapshots/ or our wiki
  scripts/classify_once.py           # one claim through classify; records the cassette
  scripts/seed_claims.py             # the demo's claims -> the ledger, backdated so they
                                     #   are due. Stands in for the proposal stage
  scripts/run_once.py                # one tick by hand: the graph, replayed or live
  FE/
    index.html                       # <-- read first: shell, nav, mount point
    app.js                           # state loading, routing, the three views
    wikitext.js                      # deliberately partial wikitext -> HTML renderer
    styles.css                       # all styling; no framework, no external assets
    check.js                         # FE verification — counts, not eyeballing
    data/demo-state.json             # generated fallback state; never hand-edit
    README.md                        # routes, data flow, licensing scope, known limits
  snapshots/
    manifest.json                    # provenance: revid, sha256, size, drift, licence
    seed/*.wikitext                  # 12 pages frozen at 2024-08-09 — seeds our MediaWiki
    current/*.wikitext               # the same pages live — evidence only, never the target
    ATTRIBUTION.md                   # CC BY-SA 3.0 notice; the text here is not MIT
  tests/test_app.py                  # route guards, and the no-vendor-import proof (needs venv)
  tests/test_draft.py                # the drafted edit: its flags, and what it refuses
  tests/test_semantic_diff.py        # the Diff stage: what it reads out of an edit
  tests/test_drafts.py               # the draft lifecycle, and what survives a restart
  tests/test_firestore.py            # what the adapter puts on the wire, against a fake client
  tests/test_judgements.py           # the record that keeps history, and what makes it history
  tests/test_wiki_read.py            # the read tool: outline stays cheap, retry stays alive
  tests/test_web_search.py           # one call per claim, allowlist from the profile, wire body
  tests/test_citations.py            # the footnote filter, on the shapes that caused it
  tests/test_wiki_write.py           # the write guard, and what action=edit puts on the wire
  tests/test_wiki_write_tool.py      # heading re-resolution, and the outcomes that aren't raised
  tests/test_ledger.py               # stdlib unittest; no deps, runs today
  tests/test_ledger_store.py         # the codec round trip, and the two stores agreeing
  tests/test_ledger_tool.py          # what a node may decide, and what only the core may
  tests/test_ingest.py               # the baseline pass, against the committed corpus
  tests/test_graph.py                # what a run does to the ledger, and the edge that stops
  tests/test_model.py                # what identifies a judgement, and what a replay refuses
  tests/test_classify.py             # the prompt's four rules, pinned; and what it won't guess
  tests/test_profile.py              # the seam: one title, two wikis; plus the layout rules
  tests/test_wiki.py                 # query/parse, plus a hash check on committed snapshots
  tests/test_sections.py             # section numbering, incl. against real snapshots
  tests/test_diff.py                 # the diff rows rebuild both texts exactly
  LICENSE           # MIT, and it covers only the code — snapshots/ is CC BY-SA
  README.md         # what it is, local run, routes, env vars, the deploy procedure
  summary.md        # product truth, decision log, verified vendor facts (§12)
  seed-plan.md      # demo subject, page list, the 6 claims that carry the video
  .env.example      # required env vars, no values
```

**The pure/perimeter line runs through `backend/`, not around it — restructured Aug 23, 2026.**
It used to be the `src/` ‖ `backend/` directory split; it is now `backend.core.*` versus
everything else under `backend/`, which puts the boundary in every import path instead of only
in the tree. What the line means did not change (`CLAUDE.md` §3): `backend.core` is
dependency-free — no Firestore, no ADK, no network — and its tests still run on an
interpreter with nothing installed. Storage and vendor calls arrive as adapters that import
*from* it, never the reverse. The wiki client is the first such adapter and shows the shape:
`fetch()` is the only method that opens a socket, so everything else is tested offline.

Three rules keep it from eroding, all asserted in `tests/test_profile.py` and
`tests/test_app.py` rather than trusted:

- `backend.core` never imports the perimeter — a `TYPE_CHECKING` reference is fine, an
  unguarded one is not.
- **`backend/__init__.py` stays import-free.** It executes before every `backend.core.*`
  import, so one vendor import there makes the dependency-free half require the SDKs and
  defeats the cold-start deferral at the same time. This risk did not exist under the old
  layout and is the one real cost of the move.
- `app.py` defers every vendor import into a handler, so a cold container serves
  `index.html` without paying for the SDKs.

Not yet written: the claim-proposal stage, Fan-out, and the claim/section stores' Firestore
adapter — so `/api/state` and `/internal/tick` are still guarded shells answering 503/501, and
`scripts/seed_claims.py` stands in for proposal by seeding the fixture's claims into the ledger.
Built: the six stages that run before the human, assembled as an ADK `Workflow` in
`agent/graph.py` and driven by `scripts/run_once.py`; the gate and its routes end to end; and
all four tools — wiki read, Parallel search, wiki section-write and the ledger — each binding a
profile and each with a deterministic path behind it, over stores that persist. The whole run
is therefore testable with no key, no network, no wiki running and no database; what it needs
before it can *say* anything true is a cassette, and a fresh clone records one (§5).

**`FE/data/demo-state.json` is generated, never hand-edited.** `build_demo_state.py` takes
page text verbatim from `snapshots/` and computes every status, confidence and interval by
driving real `Claim` objects through the real transitions — so the numbers on screen are the
core's output, not a fixture author's. It fails the build when a claim's `wikitext_anchor` is
absent from the seed, because an anchor that does not exist is an edit that could never apply.

**Its claim content is demo data, and its accuracy is not a property worth defending.** The six
claims exist so the frontend has something to render before the agent produces state — they are
not product truth, not a seed for the live ledger, and not a fixture any test asserts the wording
of. A claim there being stale, imprecise or slightly wrong costs nothing: the point of the
product is that a run re-checks a claim against the world and rewrites the page accordingly, so
wrong-and-then-corrected is the behaviour being demonstrated rather than a defect in the input.
What *is* asserted is the machinery around it — the numbers are the core's output and the anchors
resolve against the seed. Spend review effort there, not on the sentences.

**`snapshots/seed/` is immutable.** It is pinned to historical revision ids and hash-checked
by the test suite. Never hand-edit a file there — fix the puller and re-run.

## 5. Commands and the verification gate

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'   # setup (.venv is gitignored)

.venv/bin/python -m unittest discover -s tests               # test
.venv/bin/mypy                                               # typecheck — strict
.venv/bin/ruff check .                                       # lint
node FE/check.js                                             # frontend  — render + wiring

brew services start mariadb                                  # the wiki's database
./scripts/setup_wiki.sh                                      # install the wiki; idempotent
php -S localhost:8080 -t wiki                                # serve it (leave running)
python3 scripts/seed_wiki.py --check                         # does it match the profile?
python3 scripts/seed_wiki.py                                 # load the 12 pages, verify hashes
./scripts/install_launcher.sh                                # the Continuity button -> Common.js
python3 scripts/seed_drafts.py                               # the demo's draft -> the store
python3 scripts/seed_drafts.py --show                        # verdicts, and what each one wrote

python3 scripts/pull_snapshots.py                            # rebuild snapshots/ (~24 calls)
python3 scripts/pull_snapshots.py --only current             # refresh the live side alone
python3 scripts/build_demo_state.py                          # rebuild FE/data/demo-state.json
python3 scripts/ingest_baseline.py                           # fill the baseline from snapshots/
python3 scripts/ingest_baseline.py --live                    # ...from our own MediaWiki instead
python3 scripts/classify_once.py                             # one claim, replayed, no key
python3 scripts/classify_once.py --live                      # ...against Gemini, and record it
python3 scripts/seed_claims.py                               # the demo's claims -> the ledger
python3 scripts/run_once.py                                  # one tick: replayed, no key
python3 scripts/run_once.py --live --record                  # ...for real, and record it
.venv/bin/uvicorn backend.app:app --reload --port 8000       # serve FE *and* the API
python3 -m http.server 8000 --directory FE                   # serve the FE alone, no backend

docker build -t continuity .                                 # deploy pre-flight; not in the gate
```

**No document states a test count.** Not here, not in `README.md`, not in a `summary.md`
decision-log entry. A number written into prose is a number no command maintains: it is correct
for one commit, drifts silently after that, and the drift is only ever noticed by someone who
ran the suite and did not need the prose. Every entry in the log used to carry a running tally
and they disagreed with each other by the time anyone checked. Say the property instead — the
gate passes, the core's tests run bare — and let the command report the number.

**Live runs are sanctioned, and do not need asking for — decided Aug 30, 2026.** This is the
project-specific half of `CLAUDE.md` §4's "ask first ... spends money": the metered calls above
— `run_once.py --live`, `classify_once.py --live`, the Parallel and Gemini paths behind them —
may be run without checking first, because the pipeline is at the stage where the only thing
left to learn about it comes from calling the real services. What is still asked for is
anything *outside* that loop: a deploy, a Cloud Scheduler job, a snapshot re-pull against
Fandom, or a run against a wiki that is not ours. The bounds that make this safe are already in
the code and are not to be relaxed alongside it — three research rounds per claim, one billable
search per claim per round, `--limit` on what a run takes, and the $25 budget alert
(`README.md`). Prefer `--record` on a live run: a run that bills and records is one nobody has
to bill again.

The four gate commands must pass before claiming done (`CLAUDE.md` §4). The wiki commands are
not part of the gate: every test runs without it, because the read path has the snapshot corpus
behind it and the write path is tested against a stub. The wiki is needed to exercise the real
`action=edit` — which is how the edit-conflict path was verified — and to record the video.

**The wiki is a dev dependency, not a build one.** `setup_wiki.sh` writes every credential it
generates into `.env` and none to the terminal; `wiki/` is gitignored because it is third-party
GPL software and a build artifact; the settings that are *ours* live in version control at
`wiki-config/LocalSettings.overrides.php`, which the generated `LocalSettings.php` requires.

The test line moved to the venv interpreter when `backend/app.py` landed: `tests/test_app.py`
imports FastAPI, and on a bare interpreter it raises `SkipTest` rather than failing — which would
quietly drop the tick-token cases from the gate. The dependency-free core still runs anywhere:
`python3 -m unittest discover -s tests` from the repo root on any 3.10+. No
`PYTHONPATH` since the Aug 23 layout move — `backend/` sits at the repo root and `python -m`
puts the working directory on `sys.path` itself. The old `PYTHONPATH=src` still *appears* to
work because it is simply ignored; `src/` no longer exists.

The `docker build` line is the only command here that needs Docker running, and it is a
pre-flight for the deploy, not part of the gate — `gcloud run deploy --source .` builds on Cloud
Build regardless. Leave Docker off until then; it buys nothing before the deploy step.

Both serve commands answer on 8000; `uvicorn` is the one that exercises the real routes. Either
way the frontend shows *fixture*, because `/api/state` has no store behind it yet and returns
503 by design — that is what the fallback is for.

**There is no build step, and this is deliberate — do not add one.** The FE is vanilla
HTML/CSS/JS with no dependencies, so the container ships it as-is and Cloud Run serves it
through `StaticFiles` from the same Python process that runs the agent. Node is used only to
*check* the FE; it is never needed to build, serve or deploy it, and the runtime image
contains no JavaScript toolchain. A framework here would buy component structure this UI is
too small to need, and cost a second toolchain in the image and a fourth thing to break.

The ledger core has **no runtime dependencies**, and that is worth keeping: it is why its tests
run on any 3.10+ interpreter with nothing installed. The venv is needed by the
route tests, by the ones that wrap a tool in ADK to check its declared schema, and by the ones
that assert the Parallel request body against a mock transport — everything else, the
snapshot-backed wiki reads and the whole search tool included, runs bare.

Python ≥3.10; developed on 3.14.4. Resolved versions as of Aug 15, 2026: `google-adk` 2.7.0,
`google-genai` 2.18.1, `parallel-web` 1.3.0.

**Auth shape re-verified against the installed `google-genai` 2.18.1 on Aug 15, 2026**, not
from recall: `enterprise` is a real `Client.__init__` kwarg and `GOOGLE_GENAI_USE_ENTERPRISE`
is read by the package. The legacy `vertexai` / `GOOGLE_GENAI_USE_VERTEXAI` pair still exists
in the source, which is exactly why the §6 gotcha stays.

**Ruff and mypy conflict on frozen-dataclass mutation tests.** Ruff's B010 wants direct
assignment, which mypy rejects as a static read-only error. Scoped `# noqa: B010` on the
line, with a comment saying why — do not relax either tool globally.

**Auth.** One-time locally: `gcloud auth application-default login`. Deployed, the Cloud Run
service account supplies credentials via the metadata server — same client line either way:

```python
from google import genai
client = genai.Client(enterprise=True, project="…", location="global")
# or set GOOGLE_GENAI_USE_ENTERPRISE / GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION
# in .env, then call genai.Client() bare
```

`location` is `"global"` for model calls. The pick-one-region rule applies to Firestore and
Cloud Run, not to Gemini.

**Parallel search — verified live Aug 22, 2026** against `parallel-web` 1.3.0. `search` is a
method on the client, not a resource: `client.search(...)`, returning `SearchResult`.

```python
from parallel import Parallel
client = Parallel(api_key=os.environ["PARALLEL_API_KEY"])
r = client.search(
    search_queries=[...],          # 3-6 words each, 2-3 queries; required
    objective="…",                 # self-contained natural-language goal
    max_chars_total=6000,
    advanced_settings={"source_policy": {"include_domains": [...]}},   # see §7
)
# r.results: list[WebSearchResult] — .url, .excerpts (list[str], markdown), and the
#            OPTIONAL .title / .publish_date. Nothing else. No authority, no score.
# r.search_id / r.session_id / r.usage / r.warnings
```

`session_id` is echoed back and should be threaded through every call in one run so later
searches get contextual results. Measured latency 1.4-5.8s; `mode` defaults to `advanced`.

**Billing is two meters, not one — measured live Aug 23, 2026.** `sku_search` is one per
**call** regardless of how many queries it carries, so batching a claim's queries is free.
But a 20-result call also billed `sku_extract_excerpts: 10`, and that meter scales with what
comes back, so "one call costs one search" is only half the story. Read the real numbers off
`usage`, which `WebSearch.search` puts in its payload for exactly this reason.

**Unverified, and marked so deliberately:** that the Gemini IAM role is `roles/aiplatform.user`
after the Enterprise rebrand, and the free-tier limits quoted in `summary.md` §12. Both are
from recall, not from the console. Confirm before relying on either — a wrong role fails at the
first model call, not at deploy, which is the expensive place to find out.

## 6. Gotchas — don't repeat these

Symptom → fix. Append when something costs more than ten minutes and the cause was
non-obvious. Scar log only; anticipated vendor constraints go in `summary.md` §12.

- **Every adapter built against `local_wiki()` must be handed the API key.** The profile
  declares `requires_key`, so `for_profile` raises before any request is made — `seed_wiki.py`
  had been calling it bare and died on its first line with a message about `.env` rather than
  about the call → pass `api_key=` at every construction site, including readers.
- **A fragment-only `Page.navigate` does not reload the page.** Driving the gate over CDP from
  `#/queue` to `#/verify?…` keeps the same document, so the app kept its in-memory `published`
  map and reported writes it had not made — against a wiki that had just been re-seeded → send
  `Page.reload` after navigating, and confirm a write on the wiki's own API rather than from
  what the page says about it.
- **The seeder's bot cannot install the launcher.** `MediaWiki:Common.js` needs the
  `editinterface` right and the BotPassword created by `setup_wiki.sh` carries only
  `basic,editpage,createeditmovepage`, so an API write there fails as a permissions error long
  after it looks like a seeding problem → push it with `maintenance/edit.php --user` as the
  admin account, which is all `scripts/install_launcher.sh` does.
- **`el.hidden` does nothing to a flex element.** `.topbar` and `nav.main` set
  `display: flex`, which outranks the user agent's `[hidden] { display: none }` — so the popup
  gate set `hidden` on both, threw no error, and rendered the full site chrome anyway →
  `FE/styles.css` now carries `[hidden] { display: none !important; }` near the reset. The
  failure is invisible in code review and only shows up in a screenshot.
- **Vertex SDK names are one generation stale.** `vertexai=True` /
  `GOOGLE_GENAI_USE_VERTEXAI` are pre-rebrand and every pre-June-2026 tutorial uses them →
  `enterprise=True` / `GOOGLE_GENAI_USE_ENTERPRISE`, and `location="global"`, not a region.
- **`publish_date` is absent on roughly half of Parallel's results** (5-6 of 10 on both
  measured runs), so any "was this published after `as_of`" test silently passes claims it
  never actually checked → filter server-side with `source_policy.after_date`, which the API
  applies before ranking, rather than post-filtering on a field that is often `None`.
- **`.gcloudignore` replaces `.gitignore` for uploads rather than adding to it** — the moment
  the file exists it is the sole list, so a copied-out secret pattern is one that will drift
  → open it with `#!include:.gitignore`, which splices `.gitignore`'s entries in at that point
  (negations included: `!.env.example` survives). Never restate a `.gitignore` pattern in it.
  Deleting the file is not the fix either: with a `.git` directory present gcloud *writes its
  own* on the first deploy. Verified Aug 22, 2026 by running the SDK's own `FileChooser` over
  this repo — `.env` ignored, `.env.example` uploaded, `FE/`, `backend/`, `Dockerfile`
  and `pyproject.toml` uploaded, everything else dropped.
- **`grep -r` from `.` silently skips dotfiles on this machine.** A clean recursive sweep is
  not proof a secret is absent → enumerate files explicitly, or `grep` the dotfile by name.
- **MediaWiki titles silently resolve to the wrong page.** `Void` redirects to `Sentry`, not
  the D&W location; `Elektra Natchios` redirects to the 136KB Daredevil page, not the D&W
  variant → always pass `redirects=1` and read back the resolved title. D&W's cameo
  characters live on variant subpages (`Human Torch/Void-Analyzing Fantastic Four`), and the
  main character page is a different subject with different claims.
- **`/` means different things on different wikis.** Fandom uses it for variant subpages
  (`Human Torch/Void-Analyzing Fantastic Four`); Wikipedia disables mainspace subpages, so
  `AC/DC` and `Face/Off` are ordinary titles → never parse a title without the wiki's profile.
  Verified Aug 15, 2026: the old `EntityRef.from_title("AC/DC")` returned base `AC`, variant
  `DC` against a real 202KB article. Fixed Aug 23, 2026 — `from_title` now takes a required
  `subpages` keyword with no default, so the question cannot be skipped, and
  `WikiProfile.entity_ref` is the way to call it. The value is not a guess either: MediaWiki
  reports it per namespace under `siprop=namespaces`.
- **Fandom throttles anonymous `User-Agent`s.** Set a real one with contact info on every
  MediaWiki call, seeding included.
- **`siprop=rightsinfo` will not tell you the CC licence version.** It answers a bare
  `CC-BY-SA` and links `fandom.com/licensing`, which is JS-rendered and unreadable to a plain
  fetch → read the wiki's own `Project:Copyrights` through the API instead. MCU Wiki states
  **CC BY-SA 3.0 Unported** there (revision 3728), and `pull_snapshots.py` re-derives it every
  run rather than trusting this note.
- **A section's text ends at the next heading of *any* level.** `==Films==` on Phase Six is
  immediately followed by `===Film title===`, so slicing that section alone yields the heading
  line and nothing else → right for `action=edit&section=N`, useless for a reviewer. Use
  `sections.subtree()` when displaying, the bare index when writing.
- **`[[File:…]]` captions contain wikilinks, so `[^\]]*` cannot match them.** A regex strip
  stops at the first `]` of the *inner* link and leaves a trail of stray `]]` through every
  Plot section → brace-match the `[[`/`]]` pairs, same as templates.
- **`Special:Export` on Fandom is behind Cloudflare** — returns a "Just a moment…" HTML
  challenge, not XML, so `importDump.php` cannot be used to seed → pull content through
  `api.php` (unchallenged) and create pages on our instance with `action=edit`.
- **Model IDs must come from `client.models.list()`, never from docs or recall.** The served
  names carry suffixes the prose drops: `gemini-3.1-pro` 404s with `Publisher model ... was not
  found`, while `gemini-3.1-pro-preview` serves. Enumerate before pinning.
- **A `Workflow` with no `START` edge fails to construct**, with `Graph validation failed.
  START node (name: '__START__') not found in graph nodes` from a pydantic validator — the
  entry point is not inferred from the first edge → `from google.adk.workflow import START`
  and make `(START, first_node)` the first item in `edges`.
- **Nodes route by assigning `ctx.route`, not by returning a route key.** A node that returns
  `{"route": "thin"}` takes the default edge and the dict is just its output, so a conditional
  backward edge silently never fires → set `ctx.route = "thin"` inside the node body, and give
  the branching edge a routing map: `(classify, {"thin": research, "ok": draft})`.
- **`NodeInterruptedError` is internal and not exported from `google.adk.workflow`** (only
  `NodeTimeoutError` is) — its own docstring says "Internal" → drive the Verify gate with the
  public `google.adk.tools.request_input` tool and let the runtime raise it, rather than
  importing it from `workflow._errors` and raising it directly.
- **Setting `timeout=` on a Parallel call bounds nothing — the SDK retries timeouts.**
  `timeout` is a deadline for *one attempt*; `max_retries` (default 2) makes three of them,
  with exponential backoff in between, so the real ceiling is
  `(max_retries + 1) * timeout + backoff`. Left at the SDK's defaults that is **1801.5s** —
  600s per attempt, longer than the 900s Cloud Run request it runs inside. Setting `timeout=30`
  alone still gives 91.5s, which looks like 30 and is not → set **both**, and read the ceiling
  off `web_search.worst_case_seconds()` rather than off the timeout. Ours is 15s × 2 attempts
  = 30.5s, against a measured search latency of 1.4-5.8s. Retries are also not free: a search
  that timed out may still have been served, so each one risks a second `sku_search`.
- **A bare `dir/` in `.gitignore` matches that directory at every depth.** Adding `wiki/` for
  the local MediaWiki install also ignored `backend/core/wiki/` — and because the other files
  there were already tracked, only the newest one, `snapshots.py`, silently vanished from the
  commit. A half-built package, failing on someone else's clone rather than here → **anchor any
  pattern that names a directory the codebase also uses**: `/wiki/`, `/fixtures/`. Asserted by
  `tests/test_profile.py`, which fails if any file under `backend/`, `tests/` or `scripts/`
  is ignored. Found by copying `git ls-files` plus untracked-not-ignored into a temp dir and
  running the suite there; `git status` shows nothing, because an ignored file is not
  "untracked" — it is invisible.
- **Homebrew's MariaDB refuses `-u root` whatever the password.** Root authenticates over
  `unix_socket`, so only the OS root can use it → connect as the installing user instead
  (`mariadb -e '...'` with no `-u`), which Homebrew grants. Applies to every setup command.
- **Main-account login via `action=login` is deprecated and refused.** A password that works
  in the browser fails at the API with no useful reason → create a BotPassword. Non-interactive
  and scriptable: `maintenance/run.php createBotPassword --appid=... <user>`, which removes the
  `Special:BotPasswords` web step entirely. The username becomes `User@appid`.
- **A csrf token fetched before logging in is silently useless.** It belongs to the anonymous
  session, so the edit fails later with `badtoken` and nothing points at the cause → discard
  any cached token on login. `MediaWikiWriter.login` does this; a test asserts it.
- **The default rate limit trips while seeding.** Twelve `action=edit` calls back to back
  exceed the per-account `edit` limit on a fresh wiki, and the failure looks like a permissions
  problem → raised in `wiki-config/LocalSettings.overrides.php`. Our instance has one client,
  so the limiter protects nothing here.
- **MediaWiki 1.43.9 runs on PHP 8.5** despite predating it — `composer.json` says `>=8.1.0`
  with no upper bound, and the CLI installer, API and maintenance scripts all work. Verified
  Aug 23, 2026, because the version match with the real MCU Wiki was worth more than staying
  on a blessed PHP.
- **`max_results` above 20 is silently reduced, not rejected.** Asking for 30 returns 20
  with `warnings: [Warning(message='Reducing max_results=30 to 20.', type=
  'input_validation_warning')]` — a 200, not an error, so nothing raises and the missing
  results look like the web being thin → read `result.warnings` when tuning retrieval; 20 is
  the ceiling.
- **`parallel.types.SourcePolicy` is the wrong `SourcePolicy`.** Two classes share the name:
  the response model under `types.shared` (re-exported at `parallel.types`) and the TypedDict
  param under `types.shared_params`. Only the second is accepted by `search()`, and passing a
  bare dict instead fails mypy strict rather than at runtime → import from
  `parallel.types.shared_params`.
- **`omit` is not `None` in the Parallel SDK.** The sentinel drops a field from the request
  body; `None` sends an explicit null. On `session_id` that is the difference between letting
  the server generate one and overriding it with nothing → `from parallel import omit`.
- **`google-genai` rewrites the schema you hand it, in place.** It adds `propertyOrdering` to
  nested objects while sending, and `GeminiModel.run` passed `dict(request.schema)` — shallow,
  so the nested dicts were still the stage's module-level `RESPONSE_SCHEMA`. The mutation
  therefore landed in the constant, a `ModelRequest.key` **changed during its own call**, and
  `record()` — which runs after — filed every answer under a key no later process could
  compute. Result: a cassette that looks full and misses on every lookup, reported as "the
  prompt or the schema changed". Found Aug 30, 2026 by diffing a replayed prompt against its
  recording and finding them byte-identical → `deepcopy` before the call, pinned by
  `tests/test_model.py`. Suspect this shape whenever a vendor takes a dict you also keep.
- **A replay only reproduces from the same ledger state.** `after_date_for` reads the claim's
  stored sources, so a claim that has already been researched asks a *narrower* search — a
  different request, and a cassette miss. That is correct behaviour on a second tick and a trap
  when re-running one: a crashed replay leaves rounds spent behind it, and the next attempt
  misses on retrieval rather than where it actually failed → re-run `scripts/seed_claims.py`
  before every replay, and read a discarded-search report as "the ledger moved", not "the
  cassette is wrong".
- **A null field is invisible to a Firestore inequality filter.** `Claim.is_due` treats
  `next_check_at is None` as due, so an unseeded claim is due in memory and *absent* from
  `where next_check_at <= now` — a divergence that passes every local test and only appears
  deployed → `ClaimStore.put` refuses a claim with no wake time (`require_scheduled`), so the
  fix lands at the write, where `Claim.seeded(now)` is one call away.
- **The Firestore emulator does not enforce composite-index requirements.** A query with a
  second filter or a second sort passes locally and fails deployed with a
  `FAILED_PRECONDITION` naming an index that does not exist → keep the due query to
  `next_check_at` alone and filter status in Python. `due()` orders by
  `(next_check_at, claim_id)` for the same reason: Firestore's implicit tiebreak on
  `order_by` is the document id, so a limited query must page identically in both stores.
- **Importing an ADK symbol from its package fails mypy while working at runtime.** ADK 2.7
  builds `google.adk.tools.__all__` at runtime from a lazy mapping, so under `strict` (which
  implies `no_implicit_reexport`) `from google.adk.tools import FunctionTool` is
  `Module ... does not explicitly export attribute "FunctionTool"` → import from the concrete
  module the mapping names, `google.adk.tools.function_tool`. Same shape for the other lazy
  packages; the mapping at the top of each `__init__.py` is the reference.

## 7. Code conventions

- **A stage is an ordinary method; the node is a wrapper.** Every stage in `agent/graph.py`
  takes no `Context` and returns a plain dict, and only `build()` imports the SDK — so the
  pipeline runs, and is tested, on an interpreter with no ADK installed. Same rule as the
  tools: the logic must not know it is in a graph, or the graph becomes the only way to
  exercise it. What that costs is that the run's typed intermediates live on the `Run` object
  rather than in `ctx.state`, which is deliberate — `Draft` is not JSON, and a codec between
  two halves of one run is somewhere for them to disagree. State carries each stage's summary,
  which is what the event stream is for; the durable artifact is the stored draft.
- **Catch narrowly inside ADK tools.** ADK 2.0 catches exceptions to drive automatic retry;
  a broad `except Exception:` masks the failure and permanently disables retry for that step.
  `except BaseException:` also traps `NodeInterruptedError` and breaks the HITL approval gate.
  The line to draw is *domain error versus transport error*: a missing page or a missing
  heading is an answer, so return it as a value the model can act on — retrying it just burns
  a round trip on something that will never succeed. A timeout, a refused socket or a 5xx is
  worth retrying, so let it propagate. Concretely: catch `WikiError`, never `URLError`.
- **A tool binds its `WikiProfile`; it never takes one as an argument.** A profile is not
  JSON, so a model could not pass one — and a tool that let it choose the wiki would hand back
  the decision the profile exists to take away (§2). Every model-facing parameter is
  JSON-expressible — a scalar, or a list of them — because that is what ADK's schema builder
  turns into a declaration. Build with a classmethod (`WikiRead.live`,
  `WebSearch.recorded`) and hand the bound method to `FunctionTool`.
- **Every search a claim needs rides one call, and one call is enough.** `sku_search` is
  billed per *call*, not per query, so `search_queries` is a list and the signature enforces
  the batching; a single-query tool would make fan-out cost four searches for the same
  evidence. Splitting retrieval into per-domain or per-tier calls is the tempting mistake, and
  it was measured on Aug 23, 2026 and is not worth it: one default call on demo claim #1
  returned **6 distinct publishers spanning tiers 1, 2 and 3**, against a confidence model that
  saturates at 3. Doubling `max_results` to 20 returned **the same 6 domains** — deeper coverage
  of the same publishers (variety 3->9, deadline 2->4), not a wider set — while roughly doubling
  the `sku_extract_excerpts` meter. Corollary: never call search to "check" something already
  retrieved — convert the payload you have with `sources_in` rather than asking again.
- **A citation is filtered by wording, never chosen by tier — `ledger/citations.py`.** Tier
  orders *authority*, not *completeness*, and the two come apart. Measured Aug 23, 2026:
  `marvel.com` and `disney.com` (tier 1) list Channing Tatum in the *Doomsday* cast **without
  naming the character**, so they support "Tatum is in the film" and not the claim, which is
  about Gambit; the character is named only by `deadline.com` and `variety.com` prose (tier 2)
  and a `themoviedb.org` table (tier 3). "Cite your best source" therefore footnotes the
  sentence to a page that does not contain it — and nothing catches it, because the claim is
  true, six publishers agree and confidence scores 1.0. So: `supporting()` keeps only sources
  whose excerpt contains every required term, *then* ranks by tier. `best_citation()` returns
  `None` rather than falling back, and `uncited()` is the state a reviewer must see.
  **Filtering costs no evidence** — `recompute_confidence` still counts every source, so
  `marvel.com` corroborates without being the footnote. The default required term is
  `entity_ref.base`; the Draft stage should pass the wording it actually wrote, which on the
  measured batch narrows five citable sources to two.
- **Draft rewrites the anchor, never the section.** `Claim.wikitext_anchor` is an exact
  substring of the page so an edit can stay surgical, and every consumer is built for that
  size: `diff.py` elides no context because its inputs are one infobox line or one sentence.
  The section goes in the prompt as *context* and is never what comes back — a stage that
  returns a whole section hands the reviewer a diff they cannot read and a write that touches
  text nobody proposed changing.
- **A stage never reports on its own output; the core computes the check.** `diff.shape()`
  returns `append` or `modify` from the strings alone, and Draft holds it against the Classify
  bucket: a `new` claim — the page is incomplete, not wrong — whose draft displaced existing
  text is `overreached` and the queue says so. Do not ask the model whether its edit was
  conservative. Verify holds no model call at all (§2), so wording an edit silently took away is
  caught by this check and by the Diff stage, or nowhere.
- **`shape()` is containment, and it fails toward `modify`.** `before in after`, not a token
  or character-subsequence test, and the demo's own fixtures are why: `GAM-APP-01` glues
  `<br>''[[Avengers: Doomsday]]''` onto the end of the infobox value with no space, so a token
  test calls a pure append a rewrite; retargeting `[[Void]]` inserts characters *inside* the
  anchor, so a subsequence test calls a rewrite an append. Reflowing scores as `modify` even
  when no word moved — keep it that way. A false alarm costs one careful read; a miss is a
  silent overwrite.
- **If retrieval carried something the page does not say, it goes to the reviewer — decided
  Aug 30, 2026.** `still_true` is the only bucket that produces no card: a confirmed claim has
  no edit to show, so its citation is refreshed and its interval doubles. Both of the others
  are drafted. A `conflicting` claim used to be withheld pending a resolution that nothing
  performed, which meant a disagreement the agent had found reached nobody — it sat in the
  ledger as `unresolved` and the run reported a claim id. It is now drafted as an edit that
  makes the disagreement *visible* rather than settling it, and the card carries the note and
  both urls so the reviewer can see what was contested without opening the ledger. `DRAFTABLE`
  is the list; an unlisted bucket raises before the model is called, so a bad route costs
  nothing.
- **A claim may be reclassified for as long as it is in the classify phase — decided Aug 30,
  2026.** One run researches every due claim, and the excerpt that contradicts one claim is
  very often the one a *different* claim's search went and fetched. Classifying each claim
  against its own batch alone threw that away: the run would reach a verdict with the
  contradiction sitting in its own memory. So Classify runs **two sweeps** — every claim
  against what its own search returned, then every claim against what the rest of the run found
  about its subject, with its previous verdict in the prompt and explicit permission to
  disagree with itself. Three rules hold it together. **Settling happens once**: the ledger
  transition reschedules the claim, so a second one would apply the decay ladder twice to a
  single run's evidence — and settling, not classifying, is what ends the phase for a claim.
  **Every classification is recorded**, superseded ones included, because a record of the
  conclusion with no trace of the revision is the half that explains it. And the match that
  offers a claim someone else's evidence is **deterministic and generous** — a case-insensitive
  mention of the subject, capped — because the stage already has a filtering step whose whole
  job is dropping off-subject excerpts, and paying a model call to decide what to show a model
  is a stage checking itself. The sweep costs one call per claim that actually gained evidence
  and nothing for the rest.
- **A conflict card is decided with the same two buttons as any other, and they mean the same
  thing.** Accept publishes the edit; reject discards it and leaves the claim exactly as it
  was. This is what keeps the gate uniform and `AGENTS.md` §2 intact — **a card's verdict never
  writes a decision on the claim**, so accepting a conflict card is not "picking a side" and
  `ClaimStatus` still needs no third value. The claim stays `unresolved` and comes back on its
  own schedule whatever the reviewer does with the edit. The draft prompt is told to show a
  disagreement and never to resolve one; a stage that chose between readings would be making
  the judgement the whole bucket exists to decline.
- **Draft returns one candidate, never a list.** The gate is uniform — every section with a diff
  is a card the reviewer accepts or rejects (§2) — so the decision is *whether* this edit, never
  *which* of several. A picker would be a second decision surface for the same click, and
  drafting alternatives would multiply model calls to produce options nobody asked to compare.
  Every card carries a diff, including a `conflicting` one: the edit it proposes is what makes
  the disagreement visible on the page, and the note and both urls ride beside it. The earlier
  design — a diff-less card showing two readings, where accepting one resolved the claim — was
  dropped on Aug 30, 2026, because it needed a verdict that meant something different from
  every other card's and a write to the claim that §2 forbids.
- **The Diff stage reads ideas; `shape()` is only its floor.** Text and meaning come apart in
  both directions — an appended `, however this was later denied` keeps every character and
  reverses the assertion, and threading `(2024)` into a value displaces text while dropping
  nothing. So `semantic_diff.Reviewer` reports per-assertion `kept` / `added` / `dropped` /
  `reversed`, and any drop or reversal is `DESTRUCTIVE`. Never treat a clean `shape()` as
  clearance; `Review.hidden_by_text` — textually `append`, semantically destructive — is the
  case the whole stage exists for.
- **Do not give the Diff stage the motive.** Its prompt carries `before` and `after` and
  nothing else: no sources, no objective, no bucket. A reader handed the reason for the edit
  explains it rather than examines it. The bucket is applied afterwards, in the deterministic
  core, when the verdict is held against it.
- **The Diff stage degrades, it does not fail.** A `ModelError` from the source falls back to
  the textual shape with `text_only` set, so a run with a dead credential still gates edits
  (`CLAUDE.md` §3). Displaced text that nothing read comes back `DESTRUCTIVE`, never clean — the
  honest reading of "no one looked" is not "nothing happened". A *malformed answer* is not
  unavailability: that means schema and model disagree, and it must raise rather than degrade
  silently forever.
- **Tier is attached where the results arrive, from the profile's table, and the vendor is
  never asked.** Parallel returns no authority or confidence field, which is what makes this
  safe: there is no vendor number for a model to anchor on. The same URL is tier 1 to the MCU
  wiki and tier 4 to Wikipedia, and that is correct — tier is the wiki's policy, not a
  property of the publisher.
- **A model call declares the shape of its answer — `agent/model.py`.** `response_schema` plus
  `response_mime_type="application/json"`, so a stage reads fields instead of regexing prose
  and a model that cannot satisfy the shape fails loudly rather than emitting something
  plausible and wrong. `temperature=0`, because the ladder and the queue are on camera and a
  stage that reclassifies on a second run is not demonstrable. AFC is explicitly disabled: the
  stages call tools themselves, and a model invoking one from inside a judgement would be a
  second, unlogged control path. Parsing refuses rather than defaults — a guessed judgement
  enters the ledger with the authority of a real one.
- **The model cassette is keyed on instruction + prompt + schema.** An edited prompt must
  *miss* the recording, not replay the old prompt's answer — that is the failure a
  deterministic fallback is most likely to hide, and it looks exactly like everything working.
  A miss raises, for the same reason a failed search does.
- **The classify prompt's rules are pinned by test, because their benchmark is not in the
  repo.** Each of the four rules in `classify.SYSTEM` came from a measurement, and the harness
  that produced those numbers was never committed — so `tests/test_classify.py` asserts each
  rule is present. That is weaker than re-running the benchmark and much stronger than nothing:
  a prompt edit that drops the precedence order or the absence rule fails a test instead of
  quietly costing accuracy on the case it was written for. Rebuild the harness before tuning
  the prompt — it is the last engineering item in `summary.md`'s Phase 1, with the case set
  and the two run modes specified.
- **A failed search is discarded, never recorded.** A search that errored established nothing
  about the world, so nothing about it reaches the ledger: no research round is spent, the
  schedule is untouched, and the claim comes due again. The reason this needs saying is that
  the safe-looking alternative is wrong — converting an error into zero sources routes to
  `unchanged`, which *doubles* the recheck interval, so an expired key or a cassette miss would
  make the agent look at that claim less often and report nothing. `sources_in` raises on an
  errored payload rather than returning `()`, which is a deliberate reversal of its earlier
  contract; the reversal is the collapse to two statuses (§2) giving "no new evidence" a side
  effect it did not used to have. A search that *ran* and found nothing is a real answer and
  still spends a round: the two cases are distinguishable in the payload and must stay so.
- **The ledger tool takes an *outcome*, never a schedule — `agent/tools/ledger.py`.** A
  passthrough over `ClaimStore.put` would let a model write `next_check_at`, `check_interval`
  and `confidence` directly, which are exactly the three numbers the deterministic core exists
  to compute: a claim could then be scheduled for never, or score 0.95 behind one blog post,
  and every figure the demo rests on would be model output wearing the ladder's clothes. So the
  write side takes `unchanged` / `changed` / `unresolved` and calls the matching
  `Claim` transition; the interval doubles or halves because `decay.py` says so. For the same
  reason `record_research` takes urls and excerpts and looks the tier up itself. The test that
  guards this asserts no write method has a schedule-shaped parameter at all.
- **A claim id is allocated by the store and never derived from the claim — `claim-0001`.** Two
  wrong answers were tried before this one. A *model-chosen* id is phrased differently every
  cycle, so re-auditing the same page doubles the ledger instead of recognising it. An id
  *derived* from page + anchor fixes that and breaks something worse: applying an edit rewrites
  the anchor by definition, so the record is re-keyed on every successful edit and every
  `ripple_targets` entry pointing at it dangles silently. Identity is assigned once by
  `ClaimStore.next_claim_id` and never recomputed; *finding* a claim is `for_page` plus an exact
  anchor match, which is one equality filter and therefore no composite index (§6). The anchor
  is where a claim sits, not what it is — treating it as identity is the mistake to not make a
  third time. Match anchors exactly and never loosely: deciding two wordings mean the same claim
  is the audit model's judgement, and a lookup that guessed would merge two real claims.
- **`result` is what a call did; `status` is what the claim *is*.** Every ledger tool call
  returns the claim's own view, so the two would collide on one key — and the collision is
  silent, because both values are plausible strings. The claim keeps `status`
  (`verified` or `unresolved`), which is the name the stored document and the ledger view
  already use; the call's outcome goes under `result`. The wiki tools have no such clash and
  keep using `status` for the outcome.
- **A diff is computed and never stored — `core/wiki/diff.py`.** Git holds snapshots and
  computes `git diff` on demand, and the reason applies here with more force: a stored diff is
  correct only while the page it was taken against stays put, and the Verify gate exists
  precisely so that hours pass first. Persist `before` and `after`; render the rows. Line-level
  first, then word-level inside a changed pair, which is what git and MediaWiki's own diff view
  both do. Two rules the tests pin: the rows must rebuild both texts byte for byte — context +
  removed is `before`, context + added is `after`, and a diff that cannot round-trip its own
  input is not evidence a reviewer can approve on — and whitespace is its own token, never
  attached to the word before it, or the last word of a line reads as different from the same
  word mid-line. The similarity floor that decides "edited line" from "different line" is
  measured on words alone: count the spaces two unrelated sentences share and every line clears
  it.
- **Tool logic imports no ADK.** Wrapping happens where the graph is constructed. This keeps
  the cold-start deferral above honest and keeps every tool — and therefore the demo's
  deterministic fallback — runnable on an interpreter with nothing installed.
- **A write addresses a section by heading; the index is re-resolved immediately before it.**
  MediaWiki addresses sections by position, so `section=3` means "the fourth heading right now"
  and anything inserted above silently renumbers the rest. A drafted edit can be minutes old at
  approval, so `WikiWrite.write_section` takes a heading, re-reads the page, resolves the index,
  and uses that same read's timestamp as `basetimestamp`. There is deliberately no way to pass
  an index — if there were, a stale one eventually would be. A heading that no longer exists is
  a reason to re-plan and never to create one (§2), so it comes back with the headings that do.
- **A published edit is substituted into the section, never sent as a section.** A drafted edit
  names the text it replaces (`before`) and what that becomes (`after`), so `write_anchor`
  re-reads the section and swaps the one for the other in whatever it says *now*. Sending the
  drafted section wholesale would revert every other change made to it while the edit sat at the
  gate — the same silent overwrite `basetimestamp` guards against, one level down and invisible
  to it. An anchor that is missing or appears twice is refused, and so is one whose replacement
  is already on the page: a draft that *adds* to a line leaves that line intact, so a second
  approval would find the anchor again and append the same text twice.
- **Publish writes the text the reviewer approved, never the agent's proposal.** The Verify
  gate accepts a hand-edited version (§2), so the edit is saved onto the change as it is made and
  the write reads *that*. Publishing the model's original `after` instead would silently discard
  every edit a reviewer made and would look exactly like it worked — the draft is a proposal, and
  what a person approved is what goes on the wiki. Publish is also the only caller of
  `WikiWrite`: nothing upstream of the gate touches the wiki, no stage writes without a button
  press behind it, and a `conflict` comes back as a value for the reviewer to re-draft, never as
  an exception. The request decides nothing at all (§2); a stale draft, a vanished anchor and an
  edit already on the page come back as that change's outcome, in the tool's own words, which the
  gate prints verbatim.
- **An edit conflict is a return value, not an exception — and under §2's single-editor
  assumption it is a guard, not a flow.** Nothing in the review queue asks a human to resolve
  one; the write is simply refused and the claim re-drafted. It means "re-read and re-draft",
  which is an instruction; raising it makes ADK retry the identical stale text against a page
  that has already moved, which cannot succeed. Match on `WikiError.code == "editconflict"`,
  never on the message — MediaWiki distinguishes `editconflict`, `protectedpage` and `badtoken`
  by code and they need different responses. Verified against the real API on Aug 23, 2026.
- **Reading a page is two calls, never one.** An outline (sections, sizes, revision, no text)
  and then one section by heading. A single "read the page" tool puts 50KB of wikitext in
  front of the model to answer a structural question, and the corpus holds a 202KB page.
  Reads return the subtree; writes target the heading's own index — `core/wiki/sections.py`
  is the reason those differ, so surface both rather than making the caller guess.
- **Read raw wikitext, never rendered HTML — `action=query&prop=revisions`, never
  `action=parse`.** We hold API access, so the source is available directly and there is no
  reason to take the rendered form. Wikitext is also the only form the rest of the design
  operates on: `action=edit&section=N` addresses source sections, `sections.py` numbers them by
  parsing `==` headings, the seed corpus is stored as wikitext and hash-checked as such, and a
  claim's `wikitext_anchor` is a literal source substring. Reading HTML would mean mapping every
  finding back to the source before anything could be written, and the mapping is not total —
  templates expand, references renumber. `parse` appears nowhere in the codebase; keep it that
  way.
- **Never append to `context.session.events`.** It circumvents the 2.0 graph engine and
  breaks determinism. Return values; let the runner emit.
- **Import ADK, `google-genai` and `parallel-web` inside the route handlers, never at module
  top.** Cloud Run scales to zero, so the first request after an idle period pays for whatever
  the module imports — 5-15s of vendor SDK before `index.html` can be served. Deferring the
  imports keeps the frontend fast on a cold container without paying for a warm one.
- **Stages are graph nodes, not hand-rolled sub-agent calls.** The 8-stage flow with **two**
  backward edges is an ADK 2.0 Workflow Runtime graph; **Verify** is its HITL pause, and because
  Fan-out follows the gate the run hits that pause twice. The two edges are
  `Classify → Research` and `Fan-out → Research`; nothing after Draft routes backwards, so the
  one-hop fan-out rule is the whole termination argument (§2).
- **The orchestrator routes and holds no opinion.** Every judgement belongs to a specialised
  node with its own system instruction, its own response schema and one question to answer —
  `classify.py`, `draft.py`, `semantic_diff.py`, and claim proposal when it lands. Verify is not
  on this list and must not join it: it is a pause, not a judgement (§2). Do not put reasoning
  in the graph itself, and do not let one node answer two questions: a model asked to both run
  the pipeline and evaluate its output has no separate position to evaluate it from. This is
  also why the Diff stage is not a method on Draft.
- **Ledger claims are positive assertions, never closed-world ones.** Store "Gambit appears in
  *Deadpool & Wolverine*", never "Gambit's appearances are limited to *Deadpool & Wolverine*".
  A claim that asserts an absence is contradicted by every new fact, so a correctly-working
  agent routes it to `conflicting` and the review queue fills with false conflicts. Measured:
  rephrasing two benchmark claims from closed- to open-world moved every model from 50% to
  ≥88% on the Classify task.
- **The three buckets are tested in precedence order, and the prompt must say so.** `conflicting`
  first (page contradicted, sources disagree, or sources are about a different entity), then
  `new`, then `still_true` — with "an absence on the page is NOT a contradiction" stated
  explicitly. Left unordered, the definitions in `summary.md` §6 overlap and every model
  collapses toward `conflicting`; adding the order took the precision case from 0/3 to 3/3 on
  every model tested.
- **The classify prompt carries `entity_ref`, and off-entity excerpts are filtered before
  classification rather than classified.** A claim about `Human Torch/Void-Analyzing Fantastic
  Four` is about a different subject from `Human Torch`, and retrieval cannot tell them apart —
  Parallel returns excerpts about "the Human Torch" with nothing marking which one. So the
  prompt must state the subject, including the variant, and say that prime and variant are
  distinct subjects. Without that the model is being asked for a judgement it has no input for,
  which is a missing-information bug and not a prompting one.
  Then two operations, in order, never one: **drop excerpts that cannot be tied to this
  subject, then classify what remains.** An off-entity excerpt is neither corroboration nor
  contradiction — it is not evidence about this claim at all, and treating it as a
  disagreement fills the review queue with noise the same way closed-world phrasing did. Fall
  through to `conflicting` only when filtering empties the batch, because *that* means
  retrieval went off-target and a human should see it. This is the guard on `seed-plan.md`
  §4.3, the variant-vs-prime precision case, which is benchmark case #4 precisely because it
  is where this fails.
- **The profile's `domain_tiers` drives Parallel's `source_policy`, not just the confidence
  score.** Use `WikiProfile.include_domains`, which is exactly the tier <=3 slice. Every
  search passes it. This is not an optimisation
  — measured Aug 22 2026 on the Human Torch precision case, the same query with and without
  it: unfiltered returned tiers `{2:1, 4:7, 6:2}` in 5.79s with two Tumblr posts and a
  scraped cast table whose role labels were offset by one row, so the top-ranked excerpt
  asserted the wrong actor; allowlisted returned `{1:4, 2:6}` in **1.80s** with Disney and
  Marvel stating the fact directly. Filtering is faster *and* better. `exclude_domains` alone
  is near-useless — the junk that shows up is not in our table, so denying what we already
  distrust changes almost nothing.
- **A social domain missing from a profile's `domain_tiers` scores as general press.**
  Unknown falls to `UNKNOWN_TIER = 4`, which skips the `best >= 5` social cap: measured, a
  Tumblr-only claim scores 0.50 instead of 0.30. Neither clears the 0.75 auto-apply gate, so
  this mis-states a number rather than approving a bad edit — but the number is on screen in
  the ledger view. Add social hosts to the table as they appear; the default itself is sound,
  because `confidence_from` already gates corroboration at tier <=3 and an unknown domain
  therefore never corroborates anything.
- **Never trust the structure of an excerpt.** Excerpts are markdown scraped from the page and
  table alignment does not survive: a real Fantastic Four cast list came back with every actor
  under the *previous* row's role. The page was right and the excerpt was wrong, which no
  amount of prompting detects. Prefer tier 1-2 prose over any tabular source.
- **`/api/state` never serves the fixture.** It answers from the store or it fails — 503 when
  there is no store, 503 when the store is down. The frontend decides *live* vs *fixture* from
  that one response and falls back to `FE/data/demo-state.json` itself, so a server-side
  fallback would put a **live** pill above a fixture. This outlives the stub: when Firestore
  lands, a read error is still a 503, never last-known-good demo data.
- **Fan-out runs after Publish, and reads the applied revision — never the draft.** Order is
  `… → Verify → Publish → Fan-out → Research`. What implicates other pages is what the wiki now
  says, and the gate is allowed to change that: a rejection means the dependents should never
  have been researched, and a hand-edit — which is now the whole point of the Verify gate (§2) —
  means every dependent drafted from the pre-gate text overstates its premise, which nothing
  downstream catches. Seed the fan-out from the published text, not from the classification.
- **Fan-out is capped and non-transitive, and that is what terminates the graph.** It expands the
  run's working set, so cap the claims it may add per run and never let a fanned-in claim fan out
  again in the same run. `Fan-out → Research` is a real cycle: the one-hop rule is the only thing
  that breaks it, so enforce it in the node, not in a config a run could raise. One hop, or a busy
  news day turns a tick into a full-wiki rewrite that never ends.
- **Fanned-in claims reschedule as changed.** Halve the interval and pull `next_check_at`
  forward for every claim fan-out named, whatever the size of its own edit, even if it got none,
  and even if the per-run cap kept it out of this run. Letting it decay like a quiet claim pushes
  the cascade's second hop out to the ceiling, which is how a one-hop cap turns into a lost
  cascade.
- Typing strictness, design system and state rules: TBD with the first module.
