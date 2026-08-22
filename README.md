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

> **Status:** the deterministic core, the seed corpus and the frontend are built and verified.
> The agent itself — the ADK graph, Parallel retrieval and wiki writes — is not yet wired up.
> The frontend currently renders a labelled fixture, not a live agent run.

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
PYTHONPATH=src python3 -m unittest discover -s tests   # 67 tests
.venv/bin/mypy                                         # strict
.venv/bin/ruff check .
node FE/check.js                                       # frontend render + wiring checks
```

All four must pass before anything is called done. Node checks the frontend; it is never
needed to build, serve or deploy it.

### Regenerating data

```bash
python3 scripts/pull_snapshots.py        # re-pull snapshots/ from the live wiki (~24 calls)
python3 scripts/build_demo_state.py      # rebuild FE/data/demo-state.json from snapshots/
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
| `MEDIAWIKI_BOT_USER` / `_PASSWORD` | From `Special:BotPasswords` on that instance |

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
scale to zero. The topology and the rules it implies are in `AGENTS.md` §3; the reasoning is
in `summary.md` §6.

> Not deployable yet — `app.py`, `Dockerfile` and `.gcloudignore` are still to be written.

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
redeploy to the same URL.

**Set a $25 budget alert.** The service is public, so IAM cannot protect `/internal/tick`;
the shared-secret header is the only thing between a guessed path and unbounded token spend
(`AGENTS.md` §2). `--max-instances 3` is the other half of that guardrail.
</details>

---

## Repository layout

```text
src/continuity/ledger/   the claim record, source tiers, decay intervals — pure, no deps
src/continuity/wiki/     MediaWiki read adapter and wikitext section splitting
scripts/                 snapshot puller and demo-state generator; both re-runnable
snapshots/               12 pages in two states, with a provenance manifest
FE/                      the review queue, ledger and page views — see FE/README.md
tests/                   stdlib unittest; no test dependencies
```

Working rules are in `CLAUDE.md` (universal) and `AGENTS.md` (this project — stack, file map,
invariants, gotchas). Read `AGENTS.md` before writing code.

---

## Licence

Application code is **MIT** — see `LICENSE`. It covers `src/`, `tests/`, `scripts/`, `FE/`
and the documentation.

It does **not** cover the wiki text. Everything under `snapshots/`, and the page text the
frontend displays, comes from the Marvel Cinematic Universe Wiki and is reproduced under
[CC BY-SA 3.0 Unported](https://creativecommons.org/licenses/by-sa/3.0/). Share-alike carries
onto edits the agent generates from it. Full notice: `snapshots/ATTRIBUTION.md`.
