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
- **Never write to any real wiki.** Unsanctioned bot edits get banned, and Wikipedia is
  stricter than Fandom — automated editing needs Bot Approval Group sign-off. All writes go to
  our own seeded MediaWiki instance, whatever wiki the profile points reads at.
- **Wiki-specific behaviour lives in a profile, never in the core.** The product is
  plug-and-play across MediaWiki sites (`summary.md` §5), so title grammar, section
  vocabulary, source tiers, licence and auth are per-wiki config the core reads. A hardcoded
  Fandom assumption in shared code is a rewrite, not a patch — it silently produces confident
  wrong output on the next wiki. Built Aug 23, 2026: `continuity.profile.WikiProfile` carries
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
| Wiki I/O | MediaWiki API — `action=parse` to read, `action=edit` with section param to write |
| Ledger | Firestore. The Cloud SQL instance in the topology is MediaWiki's alone |
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
      GET  /api/state        ledger + queue from Firestore
      POST /api/queue/{id}   approve/reject -> action=edit&section=N
      POST /internal/tick    Cloud Scheduler, hourly, shared-secret header (§2)
    runtime SA: continuity-run@  — aiplatform.user, datastore.user, secretAccessor

  mediawiki                                   <-- the wiki the agent edits; never a real one
    MediaWiki on Cloud SQL (MySQL, shared-core), over the Cloud SQL connector
    --max-instances 1; the service scales to zero, its database does not

  Firestore (ledger)   Cloud SQL (MediaWiki's DB, and nothing else)
  Secret Manager (Parallel key, tick token, bot password)
  Cloud Scheduler (1 job)   Artifact Registry (2 images)
```

That is the target shape. `backend/app.py` serves `/` for real; the other three are written and
guarded but have nothing behind them yet, so they answer 503/501 (§4).

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
    app.py                           # the four routes; FE/ mounted last
    core/                            # ===== the deterministic half. No vendor, no network =====
      ledger/
        schema.py                    # <-- read first: Claim, the record everything else serves
        tiers.py                     # tier *mechanism*; the table itself is per-wiki
        decay.py                     # Wave, and the double/halve/clamp interval logic
      profile/
        schema.py                    # <-- read first: WikiProfile, everything per-wiki
        known.py                     # MCU_FANDOM and WIKIPEDIA_EN, and their tier tables
      wiki/
        client.py                    # MediaWiki read adapter; network confined to fetch()
        sections.py                  # wikitext -> the sections action=edit&section=N addresses
                                     # ===== everything else under backend/ is perimeter =====
  Dockerfile                         # the runtime image; copies pyproject/backend/FE only
  .gcloudignore                      # what Cloud Build does NOT receive; includes .gitignore
                                     #   rather than repeating it, so there is one secret list
  pyproject.toml                     # deps, ruff + mypy config, gate settings
  scripts/pull_snapshots.py          # rebuilds snapshots/ from the live API; re-runnable
  scripts/build_demo_state.py        # snapshots/ + ledger core -> FE/data/demo-state.json
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
  tests/test_ledger.py               # stdlib unittest; no deps, runs today
  tests/test_profile.py              # the seam: one title, two wikis; plus the layout rules
  tests/test_wiki.py                 # query/parse, plus a hash check on committed snapshots
  tests/test_sections.py             # section numbering, incl. against real snapshots
  README.md         # what it is, local run, routes, env vars, the deploy procedure
  summary.md        # product truth, decision log, verified vendor facts (§12)
  seed-plan.md      # demo subject, page list, the 6 claims that carry the video
  .env.example      # required env vars, no values
```

**The pure/perimeter line runs through `backend/`, not around it — restructured Aug 23, 2026.**
It used to be the `src/` ‖ `backend/` directory split; it is now `backend.core.*` versus
everything else under `backend/`, which puts the boundary in every import path instead of only
in the tree. What the line means did not change (`CLAUDE.md` §3): `backend.core` is
dependency-free — no Firestore, no ADK, no network — and 81 of the 96 tests still run on an
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

Not yet written: the ADK tool signatures, the 7-stage graph, `action=edit` section writes,
and the Firestore adapter — so all three API routes are guarded shells answering 503/501.

**`FE/data/demo-state.json` is generated, never hand-edited.** `build_demo_state.py` takes
page text verbatim from `snapshots/` and computes every status, confidence and interval by
driving real `Claim` objects through the real transitions — so the numbers on screen are the
core's output, not a fixture author's. It fails the build when a claim's `wikitext_anchor` is
absent from the seed, because an anchor that does not exist is an edit that could never apply.

**`snapshots/seed/` is immutable.** It is pinned to historical revision ids and hash-checked
by the test suite. Never hand-edit a file there — fix the puller and re-run.

## 5. Commands and the verification gate

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'   # setup (.venv is gitignored)

.venv/bin/python -m unittest discover -s tests               # test     — 96 passing
.venv/bin/mypy                                               # typecheck — strict
.venv/bin/ruff check .                                       # lint
node FE/check.js                                             # frontend  — render + wiring

python3 scripts/pull_snapshots.py                            # rebuild snapshots/ (~24 calls)
python3 scripts/pull_snapshots.py --only current             # refresh the live side alone
python3 scripts/build_demo_state.py                          # rebuild FE/data/demo-state.json
.venv/bin/uvicorn backend.app:app --reload --port 8000       # serve FE *and* the API
python3 -m http.server 8000 --directory FE                   # serve the FE alone, no backend

docker build -t continuity .                                 # deploy pre-flight; not in the gate
```

All four must pass before claiming done (`CLAUDE.md` §4).

The test line moved to the venv interpreter when `backend/app.py` landed: `tests/test_app.py`
imports FastAPI, and on a bare interpreter it raises `SkipTest` rather than failing — which would
quietly drop the tick-token cases from the gate. The dependency-free core still runs anywhere:
`python3 -m unittest discover -s tests` from the repo root on any 3.10+, 81 of the 96. No
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

The ledger core has **no runtime dependencies**, and that is worth keeping: it is why 81 of
the 96 tests run on any 3.10+ interpreter with nothing installed. Only the route tests need
the venv, because only the perimeter imports a third-party package.

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
searches get contextual results. `usage` bills one `sku_search` per **call**, not per query,
so batching queries into one call is free. Measured latency 1.4-5.8s; `mode` defaults to
`advanced`.

**Unverified, and marked so deliberately:** that the Gemini IAM role is `roles/aiplatform.user`
after the Enterprise rebrand, and the free-tier limits quoted in `summary.md` §12. Both are
from recall, not from the console. Confirm before relying on either — a wrong role fails at the
first model call, not at deploy, which is the expensive place to find out.

## 6. Gotchas — don't repeat these

Symptom → fix. Append when something costs more than ten minutes and the cause was
non-obvious. Scar log only; anticipated vendor constraints go in `summary.md` §12.

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
  `NodeTimeoutError` is) — its own docstring says "Internal" → drive the publish gate with the
  public `google.adk.tools.request_input` tool and let the runtime raise it, rather than
  importing it from `workflow._errors` and raising it directly.

## 7. Code conventions

- **Catch narrowly inside ADK tools.** ADK 2.0 catches exceptions to drive automatic retry;
  a broad `except Exception:` masks the failure and permanently disables retry for that step.
  `except BaseException:` also traps `NodeInterruptedError` and breaks the HITL approval gate.
- **Never append to `context.session.events`.** It circumvents the 2.0 graph engine and
  breaks determinism. Return values; let the runner emit.
- **Import ADK, `google-genai` and `parallel-web` inside the route handlers, never at module
  top.** Cloud Run scales to zero, so the first request after an idle period pays for whatever
  the module imports — 5-15s of vendor SDK before `index.html` can be served. Deferring the
  imports keeps the frontend fast on a cold container without paying for a warm one.
- **Stages are graph nodes, not hand-rolled sub-agent calls.** The 7-stage flow with two
  backward edges is an ADK 2.0 Workflow Runtime graph; the publish gate is its HITL pause.
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
- **Fan-out is capped and non-transitive.** It expands the run's working set, so cap the claims
  it may add per run and never let a fanned-in claim fan out again in the same run. One hop, or
  a busy news day turns a tick into a full-wiki rewrite.
- **Fanned-in claims reschedule as changed.** Halve the interval and pull `next_check_at`
  forward for every claim fan-out added to a run, whatever the size of its own edit and even if
  it got none. Letting it decay like a quiet claim pushes the cascade's second hop out to the
  ceiling, which is how a one-hop cap turns into a lost cascade.
- Typing strictness, design system and state rules: TBD with the first module.
