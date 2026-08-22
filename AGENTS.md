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
  wrong output on the next wiki. `EntityRef.from_title` splitting on `/` is the live example:
  correct for Fandom subpages, wrong for `AC/DC` on Wikipedia.
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
| Ledger | Firestore (or Cloud SQL if ripple queries need joins) |
| Scheduling | Cloud Scheduler → Cloud Run endpoint, hourly; interval logic lives in the ledger |
| Secrets | Secret Manager — Parallel key, wiki bot credentials |
| Frontend | Vanilla HTML/CSS/JS in `FE/` — no framework, no build step, no dependencies |
| Hosting | One Cloud Run service: FastAPI serves `FE/` *and* runs the agent. Scale-to-zero |

Why each was chosen, and what was rejected: `summary.md` §6 and §12.

### Runtime topology

Two Cloud Run services, both scale-to-zero, both in `us-east1`. Nothing else runs.

```text
  continuity                                  <-- the public project URL
    FastAPI, python:3.12-slim
      GET  /                 StaticFiles over FE/        (no build step; ships as-is)
      GET  /api/state        ledger + queue from Firestore
      POST /api/queue/{id}   approve/reject -> action=edit&section=N
      POST /internal/tick    Cloud Scheduler, hourly, shared-secret header (§2)
    runtime SA: continuity-run@  — aiplatform.user, datastore.user, secretAccessor

  mediawiki                                   <-- the wiki the agent edits; never a real one
    MediaWiki on SQLite, DB file on a GCS volume (gen2 execution environment)
    --max-instances 1, because SQLite has one writer

  Firestore (ledger)   Secret Manager (Parallel key, tick token, bot password)
  Cloud Scheduler (1 job)   Artifact Registry (2 images)
```

Rules that fall out of this shape:

- **One container serves the frontend and runs the agent.** `FE/` is static, so there is no
  second origin, no CORS and no second deploy. Do not split them.
- **Region is `us-east1` for Cloud Run, Firestore and the bucket.** Gemini is the exception —
  `location="global"`, never a region (§5).
- **`--min-instances 0` and `--max-instances 3`.** Zero is what makes idle cost nothing; the
  ceiling is what stops a stuck research loop from draining the credits.
- **MediaWiki uses SQLite on a mounted bucket, not Cloud SQL.** Cloud SQL cannot scale to
  zero, so the cheapest instance bills ~$9/mo to serve a demo nobody is looking at. Unverified
  as of Aug 22, 2026 — SQLite needs POSIX locking a GCS FUSE mount may not give it, and the
  failure mode is write corruption, not an error. Prove a write-read-restart cycle before
  seeding pages onto it (`summary.md` §10).
- **Gemini tokens are the only meaningful cost.** Every other line above sits inside a free
  tier at demo traffic — verify current figures before relying on that (`summary.md` §12).

## 4. File map

<!-- One line per file: path # what it owns. Mark entry points "<-- read first".
     Update in the same task that moves a file. A stale map is worse than no map. -->

```text
  pyproject.toml                     # deps, ruff + mypy config, gate settings
  src/continuity/ledger/
    schema.py                        # <-- read first: Claim, the record everything else serves
    tiers.py                         # domain -> authority tier, and confidence from tiers
    decay.py                         # Wave, and the double/halve/clamp interval logic
  src/continuity/wiki/
    client.py                        # MediaWiki read adapter; network confined to fetch()
    sections.py                      # wikitext -> the sections action=edit&section=N addresses
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
  tests/test_ledger.py               # stdlib unittest; no deps, runs today
  tests/test_wiki.py                 # query/parse, plus a hash check on committed snapshots
  tests/test_sections.py             # section numbering, incl. against real snapshots
  README.md         # what it is, local run, routes, env vars, the deploy procedure
  summary.md        # product truth, decision log, verified vendor facts (§12)  [gitignored]
  seed-plan.md      # demo subject, page list, the 6 claims that carry the video [gitignored]
  .env.example      # required env vars, no values
```

The ledger core is deliberately dependency-free: no Firestore, no ADK, no network. Storage
and vendor calls arrive later as adapters that import *from* it (`CLAUDE.md` §3). The wiki
client is the first such adapter and follows the same shape — `fetch()` is the only method
that opens a socket, so everything else is tested offline. Not yet written: the ADK tool
signatures, the 7-stage graph, `action=edit` section writes, the Firestore adapter, and
`app.py` + `Dockerfile` (the FastAPI shell that serves `FE/` and hosts the agent).

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

PYTHONPATH=src python3 -m unittest discover -s tests         # test     — 67 passing
.venv/bin/mypy                                               # typecheck — strict
.venv/bin/ruff check .                                       # lint
node FE/check.js                                             # frontend  — render + wiring

python3 scripts/pull_snapshots.py                            # rebuild snapshots/ (~24 calls)
python3 scripts/pull_snapshots.py --only current             # refresh the live side alone
python3 scripts/build_demo_state.py                          # rebuild FE/data/demo-state.json
python3 -m http.server 8000 --directory FE                   # serve the FE locally
```

All four must pass before claiming done (`CLAUDE.md` §4).

**There is no build step, and this is deliberate — do not add one.** The FE is vanilla
HTML/CSS/JS with no dependencies, so the container ships it as-is and Cloud Run serves it
through `StaticFiles` from the same Python process that runs the agent. Node is used only to
*check* the FE; it is never needed to build, serve or deploy it, and the runtime image
contains no JavaScript toolchain. A framework here would buy component structure this UI is
too small to need, and cost a second toolchain in the image and a fourth thing to break.

The ledger core has **no runtime dependencies**, so its tests run on a bare interpreter —
that is why `test` needs no venv and no install. The setup line pulls the vendor SDKs too,
which the core does not use and the adapters will.

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
  Verified Aug 15, 2026: `EntityRef.from_title("AC/DC")` returns base `AC`, variant `DC`
  against a real 202KB article.
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
- **Fan-out is capped and non-transitive.** It expands the run's working set, so cap the claims
  it may add per run and never let a fanned-in claim fan out again in the same run. One hop, or
  a busy news day turns a tick into a full-wiki rewrite.
- **Fanned-in claims reschedule as changed.** Halve the interval and pull `next_check_at`
  forward for every claim fan-out added to a run, whatever the size of its own edit and even if
  it got none. Letting it decay like a quiet claim pushes the cascade's second hop out to the
  ceiling, which is how a one-hop cap turns into a lost cascade.
- Typing strictness, design system and state rules: TBD with the first module.
