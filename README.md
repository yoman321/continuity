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

> **Status:** the deterministic core, the seed corpus, the frontend and the service shell are
> built and verified, and so are all four tools the agent works through — Parallel search,
> MediaWiki read and write, and the claim ledger, each with a deterministic offline path behind
> it. A local MediaWiki is up and seeded from the frozen corpus, and the ledger persists to a
> local JSON file holding the exact documents Firestore will later hold. **Not yet wired up:**
> the ADK graph that joins those tools, and the Firestore adapter behind the ledger — so the
> three API routes exist and are guarded but answer 503/501, and the frontend renders a
> labelled fixture rather than a live agent run. Four stages do run on their own: the baseline
> ingest fills the ledger with what the monitored pages currently say, Classify sorts a claim
> against retrieved evidence using real Gemini, Draft writes the edit that follows, and Diff
> reads that edit for what it did to the ideas already on the page —
> `scripts/classify_once.py` runs the classify path end to end, live or replayed from a
> cassette.

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

Three views:

| Route | Shows |
|---|---|
| `#/queue` | Drafted edits — diff, rationale, citations with authority tiers, confidence, approve/reject |
| `#/ledger` | Every tracked claim — status, volatility wave, confidence, recheck interval, next check |
| `#/wiki/<slug>` | The seeded wiki page, with each claim's anchor highlighted in place |

The header pill reads **fixture** when no backend is running and **live** when `/api/state`
answers. The wiki picker beside it is the plug-and-play surface.

### The Python side

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

The claim ledger has no runtime dependencies, so its tests run on a bare interpreter — the
install is only needed for the linters and, later, the vendor SDKs.

```bash
.venv/bin/python -m unittest discover -s tests         # the whole suite
.venv/bin/mypy                                         # strict
.venv/bin/ruff check .
node FE/check.js                                       # frontend render + wiring checks
```

All four must pass before anything is called done. Node checks the frontend; it is never
needed to build, serve or deploy it. Only the route tests and the ADK binding checks need
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
| `GET /api/state` | `503` | ledger + queue from the claim store, in the fixture's exact shape |
| `POST /api/queue/{edit_id}` | validates, then `501` | approve → `action=edit&section=N` |
| `POST /internal/tick` | authenticates, then `501` | hourly Cloud Scheduler run |

The 503 is deliberate: it is what makes the frontend fall back to the generated fixture and
label itself **fixture** rather than claiming to be live. `/internal/tick` compares
`X-Tick-Token` against `TICK_TOKEN` before doing anything, and refuses outright when that is
unset — the service is public when deployed, so the header is the only thing guarding it.

### The wiki the agent writes to

The agent must never edit a real wiki — unsanctioned bot edits get the account banned — so it
writes to a MediaWiki of its own, seeded from the same frozen corpus the tests use. It runs
natively rather than in a container; moving it into Docker is a later task.

```bash
brew install mariadb php && brew services start mariadb
./scripts/setup_wiki.sh                  # ~90s: downloads MediaWiki, installs, makes a bot
php -S localhost:8080 -t wiki            # serve it
python3 scripts/seed_wiki.py             # load the 12 pages, then verify every hash
```

`setup_wiki.sh` writes every credential it generates to `.env` and nothing to the terminal.
The MediaWiki tree lands in `wiki/`, which is gitignored — it is third-party GPL software and
a build artifact, reproducible from the script. The settings that are actually *ours* live in
`wiki-config/LocalSettings.overrides.php`, which is version controlled, and the installer's
generated file just requires it.

`seed_wiki.py --check` compares the running instance against the profile — mainspace subpages,
declared licence — and refuses to write if they disagree. That check matters: the profile says
these titles use subpage grammar, and if the instance disagreed then
`Human Torch/Void-Analyzing Fantastic Four` would stop being a variant halfway through the
pipeline and claims about it would silently attach to the wrong subject.

### Regenerating data

```bash
python3 scripts/pull_snapshots.py        # re-pull snapshots/ from the live wiki (~24 calls)
python3 scripts/build_demo_state.py      # rebuild FE/data/demo-state.json from snapshots/
python3 scripts/ingest_baseline.py       # fill the ledger baseline from snapshots/ (no key)
python3 scripts/ingest_baseline.py --live  # ...from the running wiki instead
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
| `MEDIAWIKI_API_URL` | Our own seeded instance. **Never a real wiki** |
| `MEDIAWIKI_API_KEY` | Generated by `setup_wiki.sh`. The wiki is treated as external even though it is ours, so reads and writes carry it in an `X-API-Key` header and refuse to run without it |
| `MEDIAWIKI_BOT_USER` / `_PASSWORD` | From `Special:BotPasswords` on that instance |
| `TICK_TOKEN` | Shared secret for `/internal/tick`. Unset ⇒ the tick refuses to run |

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

One Cloud Run service serves the frontend and runs the agent; MediaWiki is a second. Both
scale to zero — but MediaWiki's Cloud SQL database does not, and is the only thing in the
project that bills while idle (~$16 through judging). The topology and the rules it implies
are in `AGENTS.md` §3; the reasoning is in `summary.md` §6.

<details>
<summary>One-time project setup</summary>

```bash
brew install --cask google-cloud-sdk
gcloud init && gcloud config set run/region us-east1

gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com \
  aiplatform.googleapis.com sqladmin.googleapis.com

PROJECT=$(gcloud config get-value project)
SA=continuity-run@$PROJECT.iam.gserviceaccount.com
gcloud iam service-accounts create continuity-run --display-name="Continuity Cloud Run"
for ROLE in roles/aiplatform.user roles/datastore.user roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="$ROLE"
done

gcloud firestore databases create --location=us-east1
printf '%s' "$PARALLEL_API_KEY" | gcloud secrets create parallel-api-key --data-file=-
printf '%s' "$(openssl rand -hex 24)" | gcloud secrets create tick-token --data-file=-

# MediaWiki's database. Shared-core is the cheapest tier that exists; confirm the tier name
# is still served before trusting it, then check the first bill against `summary.md` §6.
gcloud sql instances create continuity-wiki \
  --database-version=MYSQL_8_0 --tier=db-f1-micro --region=us-east1
gcloud sql databases create mediawiki --instance=continuity-wiki
```

`continuity-run` deliberately has no `roles/cloudsql.client`: the agent reaches the wiki over
`api.php`, never over its database. Only the `mediawiki` service connects to Cloud SQL.

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
backend/app.py           the four routes; FE/ is mounted last so it cannot shadow them
backend/agent/tools/     what the graph's nodes call; each binds a profile, none imports ADK
wiki-config/             our MediaWiki settings; the generated LocalSettings.php requires them
wiki/                    gitignored: the MediaWiki install, rebuilt by scripts/setup_wiki.sh
fixtures/                gitignored: recorded search + model cassettes, third-party text
backend/core/ledger/     claims + the page baseline, tiers, decay, the local stores — no deps
backend/agent/ingest.py  step 1 of a run: read the monitored pages, store their sections
backend/agent/model.py   the Gemini perimeter: one call, a declared schema, a cassette
backend/agent/classify.py  the classify stage — still true / new / conflicting
backend/agent/draft.py   the draft stage — rewrites one anchor, with its citation
backend/agent/semantic_diff.py  the diff stage — what the edit did to the ideas
backend/core/profile/    per-wiki config: title grammar, tier table, sections, licence
backend/core/wiki/       MediaWiki read adapter, section splitting, snapshots, edit diffs
Dockerfile               python:3.12-slim; copies pyproject.toml, backend/ and FE/
scripts/                 snapshot puller and demo-state generator; both re-runnable
snapshots/               12 pages in two states, with a provenance manifest
FE/                      the review queue, ledger and page views — see FE/README.md
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
