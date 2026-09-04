# Continuity

An agent that keeps a wiki current.

Wikis go stale in a way diffs never catch: the page doesn't change, the world does. A link
that pointed at the right character now resolves to a different one. A cast list that was
complete last year is missing a film announced since. Nobody edited anything — the claim just
stopped being true.

Continuity decomposes wiki pages into atomic **claims**, re-checks each one against the live
web on its own schedule, weighs the sources it finds by publisher authority, and drafts
**section-level** edits with citations and a confidence score. When credible sources disagree
it says so and declines to pick, rather than producing a confident answer.

It is built to be pointed at any MediaWiki site — Fandom, Wikipedia, Memory Alpha — not wired
to one. Per-wiki differences (title grammar, section vocabulary, source tiers, licence) are
configuration the core reads, not assumptions baked into it.

Built for **Agentic Cinema: The Blockbuster Hackathon** (Google Cloud × Devpost), Parallel
track. Demo subject: *Deadpool & Wolverine*, seeded from real MCU Wiki revision history frozen
at 2024-08-09.

> **Status: the pipeline runs end to end.** A reader on an article presses **Continuity** in the
> corner; a popup opens, starts a run, and narrates it stage by stage; the drafted edits arrive
> as cards to accept, edit or reject; one Publish button applies the accepted set and the
> article shows the change.
>
> One run goes: **Propose** reads the page and records what it asserts, **Audit** hands over the
> claims that are due, **Research** buys evidence through Parallel, **Classify** sorts each claim
> against it with Gemini — twice, so a claim can be revised by what the rest of the run found —
> **Draft** writes the edit that follows, **Diff** reads that edit for what it did to the ideas
> already on the page, and **Verify** stores it as cards. Publish is the button behind the gate.
>
> Everything a run decides is real state in MongoDB — pages, claims, judgements, sections,
> drafts — and every document names the run that wrote it, so a run's whole footprint is one
> query. Runs are numbered per page: the first run on a page creates its record, and the third
> is `run-Gambit-0003`. The wiki it edits is *not* real state: it lives in the browser and
> resets on reload.
>
> **Not built:** `/internal/tick`, so nothing runs on a schedule. Retrieval and model calls replay from
> cassettes, which are gitignored — a fresh clone records its own with `--live --record`.

---

## Running locally

Nothing here needs a cloud account, an API key, or a network connection.

### The frontend

```bash
python3 -m http.server 8000 --directory FE
```

Open <http://localhost:8000>. No install and no build step — it is static HTML, CSS and
JavaScript with no dependencies. Serve it rather than opening `index.html` directly; `file://`
blocks the fetch that loads state.

Two views:

| Route | Shows |
|---|---|
| `#/wiki/<slug>` | The wiki page as a reader sees it — no agent detail, just the **Continuity** button |
| `#/verify?page=…` | The gate the button opens, in a popup. Opens idle; **Run Continuity** starts the agent. Two tabs: **Process** (which stage the run is on) and **Changes** (each drafted edit as a diff, with rationale, citations and confidence — approve, edit in place, or reject, then publish) |

The header pill reads **fixture** when no backend is running and **live** when `/api/state`
answers. The wiki picker beside it is the plug-and-play surface.

### The Python side

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
./scripts/mongo.sh start          # the ledger's database — a run needs it
```

**The ledger is a real database with no fallback.** The JSON file stores were removed on
Sept 1, 2026: if mongod is not running, a run fails rather than quietly starting from an empty
ledger, which would look like an agent that found nothing. `./scripts/mongo.sh status` says
whether it is up; `stop` shuts it down. The test suite does not need it — it runs against the
in-memory stores and skips the handful of persistence tests when the server is absent.

The claim ledger has no runtime dependencies, so its tests run on a bare interpreter — the
install is only needed for the linters and, later, the vendor SDKs.

```bash
.venv/bin/python -m unittest discover -s tests         # the whole suite
.venv/bin/mypy                                         # strict
.venv/bin/ruff check .
node FE/check.js                                       # frontend render + wiring checks
```

All four must pass before anything is called done. Node checks the frontend; it is never
needed to build, serve or deploy it. Only the route tests and the tool-schema checks need
the venv — everything else is dependency-free, so `python3 -m unittest discover -s tests` from
the repo root still runs the rest on a bare 3.10+ interpreter with nothing installed.
That includes the snapshot-backed wiki reads, which is what lets the demo's fallback path be
exercised offline.

### The whole service

```bash
.venv/bin/uvicorn backend.app:app --reload --port 8000
```

Same three views, plus the API the agent will answer on:

| Route | Now | Eventually |
|---|---|---|
| `GET /` | serves `FE/` | unchanged |
| `GET /api/state` | the ledger from Mongo — claims, pages, profiles. 503 when the store is unreachable or empty | unchanged |
| `POST /api/runs` | starts a run on one page and returns its id — `run-Gambit-0003`. 422 with no page, 404 with no baseline for it, and the run already in flight if there is one | unchanged |
| `GET /api/runs/{id}` | how far that run has got: stages done, current stage, notes, report | unchanged |
| `GET /api/drafts` | the stored drafts, newest first | unchanged |
| `GET /api/drafts/{id}` | one draft: its changes, verdicts, hand-edits and flags | unchanged |
| `POST /api/drafts/{id}/changes/{edit_id}` | records a verdict, the reviewer's text, or both | unchanged |
| `POST /api/drafts/{id}/publish` | records the outcome of each write the gate performed, then stamps the draft published | unchanged |
| `POST /internal/tick` | authenticates, then `501` | hourly Cloud Scheduler run |

**A run is named for its page and its number on that page.** The first run on a page creates
that page's record in Mongo; every run after it takes the next number, and the number is the
id — so `run-Gambit-0003` is the third run on Gambit, and the same string is the `task_id` on
every claim it proposed and the name of the draft it produced (`draft-Gambit-0003`). One at a
time: a second press while a run is in flight gets the run already going, because a route that
starts billable work is a credit leak if anything can call it in a loop.

`/api/state` answers from the store or it fails: a 503 is what makes the frontend fall back to
the generated fixture and label itself **fixture** rather than claiming to be live. It never
serves the fixture itself. And it carries no page text — the article view reads that from the
browser's own wiki, so the bytes are never served twice.

**The publish request reports outcomes and steers nothing.** The wiki is in the browser, so
the gate performs each `action=edit` itself and this route records the result — a list of
`{edit_id, status, revid, error}`. It may never carry a page, section, anchor or text: unknown
fields are refused, the status vocabulary is closed, and an `edit_id` the draft is not awaiting
is a 422, so the most a caller can do is mark a review a person already accepted as published
(`AGENTS.md` §2). `/internal/tick` compares
`X-Tick-Token` against `TICK_TOKEN` before doing anything, and refuses outright when that is
unset — the service is public when deployed, so the header is the only thing guarding it.

### The wiki

The agent must never edit a real wiki — unsanctioned bot edits get the account banned — so it
edits one of its own. As of Sept 1, 2026 that wiki lives **in the browser**: `FE/wiki-api.js`
loads `FE/data/wiki-db.json` and answers MediaWiki's action API from memory. There is nothing
to install and no server to start.

```bash
python3 scripts/build_wiki_db.py     # snapshots/seed/ -> the tables, for both destinations
```

| File | What it is |
|---|---|
| `snapshots/wiki-db.dummy.json` | Canonical, committed, regenerated only by the builder |
| `FE/data/wiki-db.json` | The same bytes, where the browser fetches them. Written together so they cannot drift |

The rows are MediaWiki's own shape — `page`, `revision`, `text`, `redirect` — so a read is a
page joined to its latest revision joined to its text, and a write appends a revision and moves
`page_latest`. Calls go through `WikiAPI.request()`, which takes action-API parameters and
resolves to the JSON `api.php` would return, so callers are written as though there were a
server; putting a real one back means changing that one function.

**Reloading the page is the reset.** A browser cannot write to a file, so an edit lives as long
as the tab does. That is enough: the article and the review gate are two routes in one app, so
publishing re-renders the article rather than reloading it, and you watch the edit land. The one
deviation from the real schema is `rev_sha256` where MediaWiki has `rev_sha1`, because the
manifest already pins sha256 and a second digest could disagree with the first.

### One run of the agent

```bash
python3 scripts/ingest_baseline.py       # what the pages say — the run reads sections from here
python3 scripts/propose_claims.py        # read the pages and propose what they assert
python3 scripts/propose_claims.py --live --record   # ...against Gemini, and record it
python3 scripts/propose_claims.py --show # the ledger: what the agent decided to track
python3 scripts/run_once.py              # one tick, replayed from cassettes: no key, no billing
python3 scripts/run_once.py --live --record   # ...for real, and record it so the replay works
```

Nothing in a run reaches the wiki: it ends with a `ReviewDraft` in the draft store, which the
Verify gate then shows as cards. Publishing is the gate's button and is the only thing that
writes. A replayed run with no matching recording reports every round **discarded** and writes
nothing — a failed retrieval establishes nothing about the world, so it is never recorded as
one.

---

### Regenerating data

```bash
python3 scripts/pull_snapshots.py        # re-pull snapshots/ from the live wiki (~24 calls)
python3 scripts/build_wiki_db.py         # rebuild the wiki's tables from snapshots/seed/
python3 scripts/build_demo_state.py      # rebuild FE/data/demo-state.json from snapshots/
python3 scripts/seed_drafts.py           # reload the draft store from that fixture
python3 scripts/seed_drafts.py --show    # what the store holds: verdicts and written revisions
python3 scripts/ingest_baseline.py       # fill the ledger baseline from snapshots/ (no key)
python3 scripts/classify_once.py         # one claim through classify, replayed (no key)
python3 scripts/classify_once.py --live  # ...against Gemini, recording the judgement
```

`snapshots/seed/` is pinned to historical revision ids and hash-checked by the test suite —
it reproduces byte-for-byte. Never hand-edit it; fix the puller and re-run.

---

## Environment variables

Copy `.env.example` to `.env` and fill it in. `.env` is gitignored and must stay that way.

| Variable | Purpose |
|---|---|
| `PARALLEL_API_KEY` | Parallel Search — the only route to the outside world |
| `GOOGLE_GENAI_USE_ENTERPRISE` | `true`. Gemini uses ADC; **no API key exists** |
| `GOOGLE_CLOUD_PROJECT` | Project holding the credits |
| `GOOGLE_CLOUD_LOCATION` | `global` for model calls — not a region |
| `TICK_TOKEN` | Shared secret for `/internal/tick`. Unset ⇒ the tick refuses to run |
| `DRAFT_STORE` | `mongo` (default) or `firestore`. Picks the backend for every store a run writes. Both hold the same documents |
| `MONGO_URI` / `MONGO_DB` | Where the ledger lives locally. Defaults `mongodb://127.0.0.1:27017` and `continuity` |

Deployed, the Cloud Run service account supplies Gemini auth through the metadata server; the
client line is identical either way. Locally it is five commands, and `gcloud init` alone is
not enough — it sets up the *CLI* login, while the SDK reads Application Default Credentials,
which is a separate step:

```bash
brew install --cask google-cloud-sdk
gcloud init                                    # log in, create or pick the project
gcloud billing projects link $(gcloud config get-value project) --billing-account=ACCOUNT_ID
gcloud services enable aiplatform.googleapis.com
gcloud auth application-default login          # the one the Python client actually reads
```

Billing must be linked even when credits cover the spend — credits are drawn down *through* a
billing account, they do not replace one, and `aiplatform` will not enable without it.
`aiplatform.googleapis.com` is the right API despite the Enterprise rebrand: with
`location="global"` the client resolves to `https://aiplatform.googleapis.com/`, confirmed in
`google/genai/_api_client.py`.

---

## Deploying

One Cloud Run service serves the frontend and runs the agent. It scales to zero, and since the
wiki moved into the browser **nothing in the project bills while idle** — there is no second
service and no Cloud SQL. The topology is in `AGENTS.md` §3; the reasoning is in `summary.md` §6.

The ledger is the one thing that still needs a database when deployed: `DRAFT_STORE=firestore`
selects the Firestore adapter, which holds the same documents MongoDB does. It has never been
run against a real instance.

<details>
<summary>One-time project setup</summary>

```bash
brew install --cask google-cloud-sdk
gcloud init && gcloud config set run/region us-east1

gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com \
  aiplatform.googleapis.com

PROJECT=$(gcloud config get-value project)
SA=continuity-run@$PROJECT.iam.gserviceaccount.com
gcloud iam service-accounts create continuity-run --display-name="Continuity Cloud Run"
for ROLE in roles/aiplatform.user roles/datastore.user roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="$ROLE"
done

gcloud firestore databases create --location=us-east1
printf '%s' "$PARALLEL_API_KEY" | gcloud secrets create parallel-api-key --data-file=-
printf '%s' "$(openssl rand -hex 24)" | gcloud secrets create tick-token --data-file=-

```

`continuity-run` needs no database role beyond `datastore.user`: the wiki is a static file the
browser loads, and the ledger is Firestore.

`roles/aiplatform.user` is still unverified **for the service account**. Local model calls are
proven working (Aug 22, 2026) but they run on user ADC, which says nothing about what a
service account needs. A wrong role fails at the first model call, not at deploy — so make a
model call from the deployed service before assuming it works.
</details>

<details>
<summary>Deploy and schedule</summary>

```bash
gcloud run deploy continuity \
  --source . --service-account $SA --allow-unauthenticated \
  --memory 1Gi --cpu 1 --min-instances 0 --max-instances 3 --concurrency 40 --timeout 900 \
  --set-env-vars GOOGLE_GENAI_USE_ENTERPRISE=true,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global \
  --set-secrets PARALLEL_API_KEY=parallel-api-key:latest,TICK_TOKEN=tick-token:latest

URL=$(gcloud run services describe continuity --format='value(status.url)')
gcloud scheduler jobs create http continuity-tick \
  --location us-east1 --schedule "0 * * * *" \
  --uri "$URL/internal/tick" --http-method POST \
  --update-headers "X-Tick-Token=$(gcloud secrets versions access latest --secret=tick-token)"
```

Cloud Build builds the image remotely — no local Docker needed. Re-run the same command to
redeploy to the same URL. If Docker is running, `docker build -t continuity .` first is worth
the minute: it is the same `Dockerfile`, and it fails locally faster than a Cloud Build round
trip. That is the only thing in this project Docker is for, so there is no reason to start it
before deploying.

**Set a $25 budget alert.** The service is public, so IAM cannot protect `/internal/tick`;
the shared-secret header is the only thing between a guessed path and unbounded token spend
(`AGENTS.md` §2). `--max-instances 3` is the other half of that guardrail.
</details>

---

## Repository layout

```text
backend/app.py           the routes: state, runs, drafts, publish; FE/ mounted last
backend/runs.py          runs started from the button, and their progress
backend/mongo.py         the ledger's five collections over MongoDB
backend/agent/graph.py   the six stages in order, and the one backward edge as a loop
backend/agent/propose.py the propose stage — page -> claims, anchors verified
backend/agent/tools/     what the stages call; each binds a profile, none imports an SDK
fixtures/                gitignored: recorded search + model cassettes, third-party text
backend/core/ledger/     claims, judgements, drafts, page records, the page baseline,
                         tiers, decay — no deps
backend/agent/ingest.py  the baseline pass: read the monitored pages, store their sections
backend/agent/model.py   the Gemini perimeter: one call, a declared schema, a cassette
backend/agent/classify.py  the classify stage — still true / new / conflicting
backend/agent/draft.py   the draft stage — rewrites one anchor, with its citation
backend/agent/semantic_diff.py  the diff stage — what the edit did to the ideas
backend/core/profile/    per-wiki config: title grammar, tier table, sections, licence
backend/core/wiki/       section splitting, snapshots, edit diffs
Dockerfile               python:3.12-slim; copies pyproject.toml, backend/ and FE/
scripts/                 mongo.sh, the wiki-db builder, ingest, propose, one run; re-runnable
snapshots/               12 pages in two states, with a provenance manifest
FE/                      the wiki, the gate, and wiki-api.js — see FE/README.md
tests/                   stdlib unittest; no test dependencies
```

Working rules are in `CLAUDE.md` (universal) and `AGENTS.md` (this project — stack, file map,
invariants, gotchas). Read `AGENTS.md` before writing code.

---

## Licence

Application code is **MIT** — see `LICENSE`. It covers `backend/`, `tests/`, `scripts/`, `FE/`
and the documentation.

It does **not** cover the wiki text. Everything under `snapshots/`, and the page text the
frontend displays, comes from the Marvel Cinematic Universe Wiki and is reproduced under
[CC BY-SA 3.0 Unported](https://creativecommons.org/licenses/by-sa/3.0/). Share-alike carries
onto edits the agent generates from it. Full notice: `snapshots/ATTRIBUTION.md`.
