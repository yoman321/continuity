# Agentic Cinema Hackathon — Working Context

Carry-forward summary for re-prompting. Everything below was established in a prior
conversation. Sources: `agentic-cinema.devpost.com` Rules and Resources pages (fetched
directly), plus vendor documentation.

---

## 1. Eligibility — cleared

**Quebec residents are ineligible** — the official rules list Quebec among the excluded
jurisdictions and state the contest is void there. Standard Quebec contest-law carve-out.

**Does not apply: based in Miami.** Checked Aug 11, 2026. This was the one blocker that would
have invalidated everything below, so it is recorded rather than deleted — but it is closed,
and nothing downstream is waiting on it.

---

## 2. The hackathon

**Agentic Cinema: The Blockbuster Hackathon** — Google Cloud x Devpost.

| | |
|---|---|
| Opened | July 27, 2026 |
| Deadline | **Sept 7, 2026, 2:00 PM PT** (= 5 PM ET) |
| Judging | Sept 23 – Oct 7, 2026 |
| Team size | Max 4 people |
| Cloud credits | $100 via form, **request by Aug 31, 2026** |

### What must be built
> "A functional, production-ready AI agent or multi-agent network — powered by Gemini and
> Google Cloud Agent Builder — that integrates a Partner Entity's product or MCP server to
> solve critical bottlenecks across the entertainment and media value chain, specifically
> targeting the workflows of filmmakers, screenwriters, studio crews, or fans."

**Not** an AI-generated-film competition. The "3-Minute Trailer" is just their name for a
demo video showing the agent functioning as built.

### Hard requirements
- Gemini + Google Cloud Agent Builder, **imported and called at runtime**
  - Accepted GCP packages: `google-adk`, `google-genai`, `google-generativeai`,
    `google-cloud-aiplatform`
- Exactly **one** partner track, also called at runtime
- Public repo (GitHub/GitLab/Bitbucket) with all source, assets, run instructions
- **Open-source license file detectable in the repo About section**
- Hosted project URL (a concept or tech demo alone fails)
- Demo video ≤3 min, YouTube or Vimeo, public, English or English subtitles
- Text description: features, tech used, data sources, findings and learnings
- Runs on web, Android, or iOS
- **New project only** — not an extension of prior work

### The AI-usage restriction (easy to trip on)
Only Google Cloud AI tools + the built-in AI features of **your chosen track's** partner.
No OpenAI, Anthropic, AWS, Microsoft AI, or third-party agent frameworks. Non-AI
third-party services (hosting, databases, web frameworks) are unrestricted.

Implication: a second partner used as **plain infrastructure** is fine. A second partner
used for its **AI features** is not.

### Judging (equal weight, after a pass/fail viability screen)
1. Technological Implementation
2. Design — coherent product, not a proof of concept
3. Potential Impact — specific problem, specific audience
4. Quality of the Idea — non-obvious use, genuine domain understanding

### Prizes (judged only within your track)
| Track | 1st | 2nd | 3rd |
|---|---|---|---|
| IBM | $7,500 | $4,500 | $3,000 |
| Grafana / Parallel / ClickHouse / Replit | $7,500 | $3,000 | $2,000 |

---

## 3. Partner tracks

Two are **build-time** requirements, three are **runtime** integrations.

| Partner | Type | Requirement |
|---|---|---|
| **Parallel** | Runtime | Search API at runtime — `parallel-web` SDK, Vercel AI SDK tools, LangChain `ParallelWebSearchTool`, or Grounding config using Parallel as search provider |
| **ClickHouse** | Runtime | Official MCP server (`mcp-clickhouse`) against ClickHouse Cloud or self-hosted. Agent Skills optional |
| **Grafana** | Runtime | Grafana Cloud MCP server (`grafana/mcp-grafana` or hosted endpoint). AI Observability alone does **not** satisfy it |
| **IBM** | Build-time | Must build using IBM Bob. Confluent optional but encouraged for event-driven workflows |
| **Replit** | Build-time | Built with Replit Agent **and** deployed on a `replit.app` / `replit.dev` domain |

**Parallel** = a web search engine built for AI agents rather than humans (Parag Agrawal's
company, own web index). Agents pass natural-language semantic objectives; it returns
token-dense excerpts sized for context windows. Free tier ~16k requests. Other products:
Extract, Monitor, Task, FindAll — but the **Search API** is what the rules require.

---

## 4. What "agentic" means here

Litmus test: **if you could replace the agent with hardcoded `stepA(); stepB(); stepC()`
and get the same result every time, it's a pipeline, not an agent.**

Requirements:
1. Goal-level input, not step-level
2. Plan chosen at runtime, varying by input
3. Closed observe→decide loop — step N's output changes whether step N+1 happens
4. Tools that touch real state
5. Self-verification against a criterion
6. Error recovery (explicitly in the judging notes)
7. Persistent state across steps
8. Bounded autonomy — step budgets, cost ceilings, human checkpoints

Quiet failures: RAG + a good prompt; a chatbot calling three tools once each; a demo where
nothing ever goes wrong.

**Proving it on video:** surface the reasoning trace, break something on camera and show
recovery, run two different inputs to prove the plan isn't hardcoded.

---

## 5. Chosen project — wiki maintainer agent

**Audience:** wiki maintainers (the "fans" lane, read as *people whose job is fans*).

**Problem:** when a film releases, one event ripples across many pages — character pages,
story arcs, timelines, filmographies, "appearances in" lists, disambiguation pages.
Sources contradict each other. Maintaining this by hand is slow and error-prone.

**Chosen track: Parallel.** Live web research is the core of the work, so the integration
is honest rather than bolted on. Runner-up: ClickHouse (as a claim/provenance store).

### Key framing decisions

**Wiki-agnostic by design — decided Aug 15, 2026.** The product is not a *Deadpool &
Wolverine* demo. It is an agent any wiki maintainer can point at their own wiki: give it an
endpoint and a profile, and it maintains their pages. D&W is the demo instance, not the
product.

This is cheaper than it sounds, because **MediaWiki is the common denominator** — it powers
Wikipedia, all of Fandom, and thousands of independent wikis, all exposing the same
`api.php`. Verified Aug 15, 2026: the existing `MediaWikiReader` pulled live *and* 2024
historical revisions from Wikipedia, MCU Fandom, Star Wars Fandom and Memory Alpha with **no
code changes** — only a different `api_url`. The read layer already generalizes.

What does *not* generalize is everything that encodes one wiki's conventions, and those are
currently hardcoded:

| Varies per wiki | Today | Elsewhere |
|---|---|---|
| Title conventions | `/` splits a variant subpage | Wikipedia disables mainspace subpages — `AC/DC` is a real 202KB article our parser splits into `AC` + `DC` |
| Section vocabulary | no Box office / Reception anywhere | Wikipedia has all three, so §5's "that claim has no home" reasoning inverts |
| Source tiers | entertainment trade press | meaningless on a medical or software wiki |
| Licence | Fandom CC BY-SA 3.0 | Wikipedia CC BY-SA 4.0 — different attribution |
| Write policy | our own instance | Wikipedia needs Bot Approval Group sign-off; stricter, not looser |

So the architectural unit is a **wiki profile**: endpoint, title grammar, section vocabulary,
tier table, licence, auth. The agent core stays wiki-agnostic and reads the profile. Anything
wiki-specific that leaks into the core is the bug (`AGENTS.md` §2).

**Build general, demo specific.** Generality is proved by a second profile running as a smoke
test, not by a broader video. The 3-minute demo still runs entirely on D&W, because a concrete
story about one page beats an abstract claim about all wikis — and §9's beats depend on
specific, verified staleness that only exists on a real instance.

**On MCP.** MCP is a *transport* for reaching a wiki, not the interface itself. Support it
where a wiki offers one, but `api.php` is the fallback and the default, because it is what
actually exists on every MediaWiki today — and `CLAUDE.md` §3 requires every external source
to have a deterministic fallback. A profile names its transport; the core does not care which.

**No source of truth exists, and that's the point.** Wikis run on *verifiability*, not
truth. The agent's output is a **sourced claim with a confidence level and a citation**,
plus an honest flag when sources disagree.

**Scripts are not an input.** Not public, rights problems, and shooting scripts contradict
the released film anyway. Real inputs: TMDB/Wikidata, press kits, official synopses, trade
press (Variety/THR/Deadline), reviews, interviews. Source-authority tiers are explicit
logic the agent reasons over.

**Division of labour:**
- **Parallel = eyes** — all outside-world retrieval, both discovery *and* re-verification
- **Gemini = brain** — comparison, contradiction detection, source weighting, ripple
  analysis, drafting
- **MediaWiki API = hands** — reading current page state and writing edits back

Gemini has no web access of its own. It processes what it's handed; it doesn't fetch.

**Use your own MediaWiki instance** on Cloud Run, seeded with pages. Never write to *any*
real wiki — unsanctioned bot edits get banned, and Wikipedia is stricter than Fandom, not
looser: automated editing there needs Bot Approval Group sign-off. Judges care that you write
to real state, not whose. Generalising the product widens what the agent can *read*; it does
not widen what it may write.

**Section-level edits, never full-page rewrites.** Full rewrites get reverted by wiki
communities and are unreadable in a 3-minute video. A diff view with per-change citations
is legible and proves the agent knew *why*.

**Rules note:** Vertex Grounding with Google Search would be a compliance risk. The Parallel
sub-page (read Aug 11, 2026) gives four ways to satisfy the track, any *one* of which counts:
the `parallel-web` SDK (Python or TS), Vercel AI SDK's `@parallel-web/ai-sdk-tools`,
LangChain's `ParallelWebSearchTool`, or a Grounding config with Parallel as search provider.

Take the direct `parallel-web` SDK path (`AGENTS.md` §2). Grounding is **not** required, and the LangChain
and Vercel routes sit badly against the "no third-party agent frameworks" restriction in §2 —
listed as acceptable for *this* requirement, but the AI-usage clause cuts the other way. Don't
take a compliance risk for an integration the plain SDK already satisfies.

Also explicit: *"Referencing Parallel in your README alone does not satisfy this requirement —
the integration must be present in your code."*

---

## 6. Architecture

### Control flow (7 stages, 2 feedback loops)

```
Audit page ──→ Research ──→ Classify
(ledger picks  (Parallel    (still true /
 due claims)    search)      new / conflicting)
    ▲               ▲            │
    │               └────────────┘  retry: thin retrieval
    │                            ▼
    │                         Fan-out
    │                    (add the claims a
    │                     new fact implicates)
    │                            │
Publish ←──── Verify ←──── Draft edit
(human edits  (check for    (section-level
 or approves)  conflicts)    diff)
                  └────────────→┘  retry: introduced conflict
```

The two return arrows and the fan-out are where the agentic behaviour lives — the arrows
because a stage's output decides whether the next one runs, the fan-out because it changes
the scope of the run in flight.

### The classify stage — decided Aug 22, 2026

Parallel returns a batch of excerpts, not an answer. The stage that consumes it is a Gemini
node that reads the batch **against the current page state** and sorts every claim it touches
into exactly three buckets:

| Bucket | Meaning | What the reviewer sees |
|---|---|---|
| **Still true** | the page already says this, and retrieval confirms it | the claim, its refreshed citation, and a bumped `last_verified` — no diff |
| **New** | retrieval carries something the page does not have | a drafted section-level insert with citations |
| **Conflicting** | page and sources disagree, or sources disagree with each other | both readings side by side, each with its tier and citation, and no auto-resolution |

**The buckets are not naturally disjoint, and that had to be measured to be believed.** As
worded above, "page and sources disagree" swallows "retrieval carries something the page
lacks" — an absence reads as a disagreement — so every model tested collapsed toward
*conflicting*, including on the Human Torch precision case. Two fixes, both verified in §12's
benchmark and both now rules in `AGENTS.md` §7: the classifier tests the buckets in precedence
order with "an absence is not a contradiction" said out loud, and ledger claims are phrased as
positive assertions rather than closed-world ones. The second matters more than it sounds — a
claim stored as "Gambit's appearances are *limited to* D&W" is contradicted by every new fact,
which is a correctly-working agent producing a useless review queue. The bucket a claim lands
in is partly a property of how the claim was written down.

**Retrieval quality is set by the source policy, not by the prompt — measured Aug 22, 2026.**
The tier table was designed to *score* what came back. Running claim #3 (the Human Torch
precision case, `seed-plan.md` §4) live showed it should also decide what comes back at all.
Unfiltered, Parallel returned one trade-press hit against seven unrecognised domains and two
Tumblr posts, and its top-ranked excerpt was a scraped cast table whose actor names had slipped
one row against their roles — a correct page rendered into a confidently wrong excerpt. Passing
the same tier <=3 domains as `source_policy.include_domains` returned Disney and Marvel stating
the fact plainly, in a third of the time. Two things follow. The tier table stops being a
scoring function and becomes the retrieval policy, which makes the per-wiki profile (§5) load-
bearing rather than cosmetic — swapping wikis swaps what the agent is allowed to read. And the
demo's own precision case only resolves correctly *with* the filter, so this was a latent
failure in the headline beat, found by running it and not visible in the spec.

**Why three buckets rather than a confidence score per claim.** A score answers "how sure am
I," which is the wrong question at a review gate — the reviewer needs to know *what kind of
decision they are being asked to make*, and those are genuinely different: nothing, an
addition, or a judgement call. Confidence still exists in the ledger and still gates what may
auto-apply; it just is not the organising axis of the review.

**"Still true" is surfaced, not silent.** Previously a no-change result only doubled
`next_check_at` and vanished. Showing it is what makes the decay ladder legible and what
proves the agent did the work — most rounds *should* end here (§7), and a review queue that
only ever shows edits hides the majority of what the agent does.

**Conflicts route to the human, not to a retry.** The agent's job ends at stating the
disagreement with both sources ranked; resolving it is the reviewer's. This replaces the
earlier framing where the agent marked `unresolved` and waited for the world to break the
tie — that still happens for anything the reviewer defers, but it is the fallback, not the
first move.

**The reviewer edits, not just approves.** Approve/reject alone forces a bad choice when a
draft is 90% right, and rejecting throws away correct research along with the bad sentence.
The gate accepts a hand-edited version of the draft as a third outcome.

### The fan-out stage — decided Aug 22, 2026

A confirmed fact rarely belongs to one claim. Gambit's *Doomsday* casting lands on `Gambit`,
on `Phase Six`, and on the film page's appearances context (`seed-plan.md` §4.1) — one search,
three pages. Fan-out is the stage that turns a single *new*-bucket result into the full set of
claims it implicates, and hands that widened set to Draft.

`ripple_targets[]` on the `Claim` record already stores the links the ledger knows about, so
the stage starts from a lookup, not a guess. What it adds on top is discovery: a fact can
implicate a claim nobody recorded a link for, and those edges get written back so the next run
starts better informed. The ledger gets denser with use.

**Why this is the stage that answers the pipeline objection.** A retry edge only says "try
again," which a `for` loop also does. Fan-out means the set of claims a run touches was not
knowable when the run started — Audit picked the due claims, and research findings added more.
That is §4's requirement 2 (plan chosen at runtime, varying by input) demonstrated rather than
asserted, and it is also the video's opening beat, so the most convincing evidence of autonomy
and the most legible thing on screen are the same feature.

**Bounded, like every other loop here.** Fan-out expands the working set, so it needs a ceiling
or one busy news day turns a tick into a full-wiki rewrite: cap the added claims per run, and
do not let a fanned-in claim fan out again in the same run. One hop, not transitive closure.

**The second hop happens next tick, not this one.** Capping at one hop does not lose the rest of
the cascade. A claim fanned into a run has been touched, so its `next_check_at` is pulled forward
and it fans out from *itself* on a later tick — the full graph still gets walked, just in bounded
steps with a human gate between each. The pull-forward is a rule rather than an implication (§7):
a fanned-in claim left to decay like a quiet one would double its interval and put the second hop
weeks away, which silently converts a cascade into an unrelated edit much later.

**What keeps this agentic (§4).** Fetch → classify → human is a linear pipeline on its own,
and §4's litmus test would fail it. Four things keep it from being one, and all four have
to survive implementation: the ledger decides *which* claims are fetched and when
(`next_check_at` is agent-chosen, §7); fan-out lets the findings widen the run; a thin or
off-target retrieval sends the graph back to Research with a broadened objective rather than
forward to a bad classification; and a draft that introduces a conflict elsewhere on the page
goes back to Draft. Cut them and this becomes RAG with a review screen — the exact quiet
failure §4 names.

### The claim ledger (central state)
One row per atomic claim:
`claim_id`, `page`, `section`, `text`, `status`, `confidence`, `sources[]`,
`last_verified`, `next_check_at`, `contradicts[]`

This is what makes it stateful rather than a prompt chain, and what lets the agent answer
"have I already checked this?"

### Stack

The layer-by-layer table lives in `AGENTS.md` §3. What matters here is *why*: ADK because
Resources Phase 4 recommends it over external wrapper libraries and the rules' accepted-package
list leads with it; Parallel's own SDK because the wrapper routes carry compliance risk (§5);
Firestore because the ADK 2.0 Event schema keeps growing (§12); a human approval gate because
that is the judging criterion, not a nicety.

### Deployment shape — decided Aug 15, 2026

The topology itself is in `AGENTS.md` §3. What matters here is why it is one Python container
rather than the obvious two-tier web app.

**The agent decides the stack, not the frontend.** ADK is Python-only, so a Python process has
to exist no matter what the UI is written in. Next.js was the instinctive choice and is the
wrong one here: it would add a second runtime, a second deploy and a second cold start, plus
CORS between them, to host a UI that has no server-side work to do. React without Next was
rejected separately — a React SPA compiles to static files and would cost nothing extra to
*host*, but at three views it buys component structure this UI is too small to need while
costing a Node toolchain in the image and a build step in the gate. So: vanilla files, served
by the same FastAPI process that runs the agent.

**Scale-to-zero is what makes the budget work.** Idle cost is the whole game for a demo nobody
looks at between judging sessions. Cloud Run bills per request-second, so the app costs nothing
when unwatched; Firestore, Scheduler, Secret Manager and Artifact Registry all sit inside free
tiers at this size. The consequence is that the $100 credits are effectively a *Gemini token
budget*, not a hosting budget — which reframes cost control as "cap the agent's research", not
"cap the infrastructure".

**MediaWiki is the one piece that fights this.** It wants a database, and Cloud SQL cannot
scale to zero — the smallest instance bills around $9/mo whether or not anyone visits, which
over the run-up to judging is real money spent on an idle demo. MediaWiki supports SQLite, so
the DB file lives on a GCS bucket mounted as a Cloud Run volume with a single instance. One
writer, no idle bill.

**Two costs are deferred, not avoided.** Cold start is 5-15s if the container imports the
vendor SDKs at module load, which a judge would experience as a broken link; the fix is lazy
imports rather than a paid warm instance (`AGENTS.md` §7). And because judging requires the
service be publicly reachable without auth, IAM cannot protect the scheduler endpoint — the
tick route has to authenticate itself, which is an invariant rather than a nicety
(`AGENTS.md` §2).

### Guardrails (double as "bounded autonomy" judging points)
- Max 3 research rounds per claim
- Confidence threshold below which nothing auto-applies
- Dry-run by default
- Human approval gate before publish

### Error recovery to build *and* demo
- Parallel returns nothing useful → broaden the semantic objective, retry
- Sources irreconcilable → mark unresolved, publish the rest
- MediaWiki edit conflict (a human edited mid-run) → re-read, rebase, retry
  — **best thing to put on camera**: real, unglamorous, proves the loop works

---

## 7. Triggering

**It is polling all the way down.** The agent has no presence on any website; nothing
pushes to it. It wakes up, asks Parallel, compares the answer to the ledger. A mismatch
*is* the event — no one announced anything.

**One queue, one trigger for the hackathon: your own timer.**

- Cloud Scheduler → Cloud Run endpoint hourly
- Endpoint queries the ledger for claims where `next_check_at` has passed, enqueues them
- Scheduler is deliberately dumb; all intelligence is in what the agent wrote to
  `next_check_at` last run

**Self-decaying intervals per claim** (not per film, not hardcoded): nothing new → double
the interval; something changed → halve it. Floor ~6 hours, ceiling ~6 months. Produces a
daily → monthly → biannual ladder naturally. An agent choosing its own cadence reads as
more agentic than one obeying a cron table.

**Fan-out overrides decay.** A claim pulled into a run by fan-out (§6) is rescheduled as if it
changed — interval halved, `next_check_at` pulled forward — however small its own edit was, and
even if it got none. Sitting next to a fact that just moved is the best available signal that a
claim is about to move too, and it is what makes the second hop of a cascade arrive soon instead
of at the ceiling.

**Parallel Monitor = a second, independent schedule owned by Parallel.** Don't build it —
running both means duplicate work, duplicate cost, dedup logic, and webhook failure modes.
Give it one sentence in the writeup: *"at production scale, Monitor would replace the
polling loop for high-velocity claims."* Reads as good scoping.

### Claims mature in waves
Not the film's commercial lifecycle — this wiki does not track that (`seed-plan.md` §8).
What moves a claim is another release or another announcement.

| Wave | What moves it | Settles |
|---|---|---|
| Settled | nothing | immediately; decays to the 6-month ceiling in two runs |
| In-universe, slow | a later installment retcons it | rarely |
| Release-driven | a new film or series ships | re-tested each release, then quiet |
| Announcement-driven | casting and slate reporting | never fully — this is where `unresolved` lives |

So the question is never "is there enough data yet" — it's "which claims have enough data
*right now*," which the confidence threshold already answers. Claim counts per wave and the
mapping onto the 50-claim set are in `seed-plan.md` §3.

### Unresolved-claim revisit queue
When the reviewer defers a conflict rather than resolving it (§6), the claim keeps
`status: unresolved` plus the objective it was pursuing, and is re-attempted when new sources
appear. An agent that knows what it doesn't know yet and comes back is the strongest behaviour
in the design; since Aug 22, 2026 it is the fallback path rather than the first move, because
a conflict now goes to the human before it goes on this queue.

---

## 8. Monitoring scope

Don't monitor the web. Monitor **the sources that carry the claims your page depends on** —
derived per claim from the sources already recorded in the ledger. Self-maintaining.

- Cast/crew and role identification → TMDB, official credits
- Casting and slate announcements → Variety, THR, Deadline
- Plot/canon and retcons → trade press, official studio channels
- Production news → Variety, THR, Deadline, studio principals' own accounts (lowest tier)
- Release dates and slate composition → studio announcements, trade press
- **Later installments themselves** → the release of a new film is the event that re-tests
  every cross-reference on the page (`seed-plan.md` §3, release-driven wave)

~12 domains covers most of a page. Plus one periodic broad Parallel search
("significant developments regarding [film] since [date]") for recall.

**Box office and awards bodies are not monitored.** MCU Wiki records neither, on any film
page — see `seed-plan.md` §8. Dropping them is a scope decision derived from the target
wiki's conventions, not an omission.

**Twitter: cut it.** Expensive/restricted API, bad signal-to-noise, weak wiki citation.
Say so explicitly — it reads as editorial judgment, not omission.

**Recheck the claim, not the source.** "Has Channing Tatum's Gambit been cast in a further
film?" is one call answering one question. Most claims never move and decay to a 6-month
interval within a couple of runs.

**Hackathon scope: one wiki, one film, ~12 source domains, ~50 tracked claims.**

---

## 9. Demo video plan (3 min max)

Beat order follows `seed-plan.md` §4, which names the specific claim behind each.

1. Audit picks ~14 claims out of ~300 — and says why
2. **The cascade** (§4.1): one confirmed announcement lands on three pages at once. Opens the
   video because it reads in seconds
3. **The claim that broke without an edit** (§4.2): a link that was right in 2024 and now
   points at the wrong character, because a later film took the name. No page diff would
   surface it — this is the case for the product
4. Diff queue with citations and confidence badges
5. **Break something live** — revoke the Parallel key, or edit the page underneath it —
   and show recovery
6. **Close on the conflicting bucket** (§6): the agent puts two readings side by side with
   their tiers and citations and declines to pick, handing the judgement to the reviewer. An
   agent that says *"these disagree and I am not resolving it"* reads as more trustworthy than
   one that always produces an answer. Which claim this is depends on the run — see §10
7. Optionally: run twice on the same film (restricted vs full source set) to show
   confidence moving

---

## 10. Open next steps

**Start here.** The list below is chronological, not ordered by priority — done and open items
interleave. As of Aug 22, 2026 the critical path is: **(1)** the 7-stage ADK graph, **(2)** the
SQLite-on-GCS check before seeding MediaWiki, **(3)** a first deploy. Both vendor perimeters —
Gemini/ADK and Parallel — are proven and the FastAPI shell is written, so what is left is the
agent itself plus the deployment shape. Nothing here is blocked on an unknown API. Everything
else is either downstream of those three or explicitly *if time permits*.

- [x] Confirm Quebec eligibility position — N/A, based in Miami. Re-read current rules text
      once to be certain; it's the one blocker that invalidates everything else
- [x] Request $100 GCP credits — requested Aug 11, 2026
- [x] Pick the demo film — Deadpool & Wolverine. See `seed-plan.md`
- [x] Pull the 2024-08-09 seed wikitext from MCU Wiki revision history — done Aug 15, 2026.
      Revision `2019481` (2024-08-08T23:57:40Z, 50,454 bytes), 17 minutes inside the freeze
      date. Templating worry closed: 15 distinct templates, nine clean `==` sections, so
      section-level edits work. Mechanics in `seed-plan.md` §7
- [x] Commit the whole seed corpus — done Aug 15, 2026. `snapshots/` holds both states of all
      12 pages (seed + live) with a manifest carrying `revid`, `sha256`, size and drift.
      Rebuilt by `scripts/pull_snapshots.py`; the seed side reproduces byte-for-byte and the
      test suite re-hashes it, so a corrupted fixture fails the gate. Every drift figure in
      `seed-plan.md` §2 was reproduced by the pull
- [x] Rebuild the claim set on evidence — done Aug 15, 2026. The original six carrying claims
      assumed box-office, budget and awards data that MCU Wiki does not record on any film
      page. Replaced with six verified-stale claims; reasoning in `seed-plan.md` §8, new set
      in §4
- [x] Read the Parallel sub-page under Phase 3 — done Aug 11, 2026. Grounding is optional;
      the `parallel-web` SDK alone satisfies the track. See §5
- [x] Decide Gemini backend — **Enterprise Agent Platform (ADC), no API key.** Verified
      Aug 11, 2026. Rules permit either; credits apply to the platform path and IAM keeps a
      key out of the public repo. See §12 for the verified call shape
- [x] Draft the claim ledger schema — done Aug 15, 2026. `src/continuity/ledger/`: the `Claim`
      record with `claim_kind` and `entity_ref`, the domain→tier table with deterministic
      confidence, and the double/halve/clamp decay logic. Dependency-free and frozen; 31 tests
      pass, mypy strict and ruff clean
- [x] Establish the verification gate — done Aug 15, 2026, with the first module. Commands in
      `AGENTS.md` §5
- [x] Prove the Gemini + ADK perimeter end to end — done Aug 22, 2026. ADC with `enterprise=True`
      at `location="global"` authenticates against the project in `.env`; `gemini-3.6-flash` and
      `gemini-3.1-pro-preview` both serve; a 4-node `Workflow` with a conditional backward edge
      and a real `LlmAgent` runs through `InMemoryRunner`. §6's control flow is buildable as
      drawn, and the retry loop was traced firing. Three API traps found and written to
      `AGENTS.md` §6; the model-ID correction is in §12 above
- [x] Pick the model on measurement, not assumption — done Aug 22, 2026. **`gemini-3.5-flash`
      everywhere**; the planned pro/flash split is dropped. Benchmarked on the Classify task
      against the seed corpus: 3.5-flash 24/24, `gemini-3.1-pro-preview` 12/24. Numbers and
      reasoning in §12; the pin is `AGENTS.md` §2. Nothing now depends on a `-preview` model
      surviving to judging
- [x] Fix the two spec defects the benchmark exposed — done Aug 22, 2026. §6's three buckets
      were not disjoint (an absence read as a contradiction, so every model collapsed toward
      *conflicting*), and closed-world claim phrasing turned every new fact into a false
      conflict. Both are now rules in `AGENTS.md` §7 and reasoning in §6. Neither was
      discoverable by reading the spec — both surfaced only by running it
- [x] **Make one live Parallel call** — done Aug 22, 2026. `client.search(...)` works on the
      key in `.env`; shape recorded in `AGENTS.md` §5. The response carries **no authority or
      score field** — just `url`, `excerpts`, and an optional `title` / `publish_date` — so
      tier assignment stays ours, which is what `ledger/tiers.py` already assumes. Three
      findings changed the design rather than confirming it, all now invariants in
      `AGENTS.md` §7 and reasoned below in §6
- [ ] **Prove SQLite-on-GCS actually works for MediaWiki** — §6 assumes the DB file lives on a
      GCS bucket mounted as a Cloud Run volume so the wiki scales to zero. That is an
      assumption, not a verified fact: SQLite needs POSIX locking that a GCS FUSE mount may not
      provide, and the failure mode is corruption on write rather than a clean error. Test a
      write-read-restart cycle before seeding 12 pages onto it. If it fails, the fallback is a
      Cloud SQL instance at ~$9/mo, which is affordable but has to be decided, not discovered
- [ ] **Build the wiki profile** — endpoint + transport, title grammar, section vocabulary,
      tier table, licence, auth (§5). Lifts the hardcoded Fandom assumptions out of the core:
      `EntityRef.from_title`'s `/` split and `ledger/tiers.py`'s trade-press table are both
      wiki-specific today. Ship two profiles (MCU Fandom, one Wikipedia) so "plug and play" is
      demonstrated rather than asserted
- [ ] Define ADK tool signatures — Parallel search, MediaWiki read (built), MediaWiki
      section-write, ledger read/write. All take the profile; none hardcode a wiki
- [ ] Build the 7-stage ADK graph — nodes, fan-out, the two backward edges, and the publish gate as
      the HITL pause (§6, `AGENTS.md` §7). The API shape is now verified rather than assumed:
      `Workflow(edges=[(START, n1), (n1, n2), (n2, {"route": n1, ...})])`, nodes route by
      assigning `ctx.route`, and the publish gate goes through `google.adk.tools.request_input`
      — all three traps are in `AGENTS.md` §6. The fan-out reschedule rule needs no core change:
      `decay.next_interval(..., changed=True)` already exists, so the node just calls it for every
      claim it fanned in
- [ ] Build the ledger persistence adapter — Firestore, importing *from* the pure core
- [ ] Stand up seeded MediaWiki on Cloud Run — create the 12 pages from `snapshots/seed/` via
      `action=edit`. Redirects are already resolved in the manifest, and `Special:Export` /
      `importDump.php` is not an option (Cloudflare), so the seeding script posts the wikitext
- [x] **Build the review queue frontend** — done Aug 15, 2026. `FE/`: the **queue** (each
      drafted edit with its diff, citations, tier badges, confidence and approve/reject — the
      §6 publish gate made visible), the **ledger view** (status, wave, confidence, interval,
      next check, which is what shows the agent is stateful rather than a prompt chain), a
      **page view** rendering the seeded wikitext with each claim's anchor highlighted in
      place, and a **wiki picker** so plug-and-play is visible rather than asserted (§5).
      Vanilla HTML/CSS/JS, no framework and no build step — reasoning below. Page text is
      verbatim from `snapshots/` and every number on screen is computed by the ledger core,
      not typed into a fixture. `node FE/check.js` verifies it by counting, not eyeballing
- [x] **Write `backend/app.py` + `Dockerfile` + `.gcloudignore`** — done Aug 22, 2026. Four
      routes and nothing else, with `FE/` mounted last so it cannot shadow them. The service
      layer lives in `backend/` rather than beside the core, because `src/continuity/` is the
      pure half and everything with a vendor import belongs on the other side of a directory
      boundary. Two calls worth recording.
      `/api/state` answers **503 rather than serving the fixture**: the frontend decides
      live-vs-fixture from that one response, so answering it with `demo-state.json` would put a
      *live* pill above an agent run that never happened. And the cold-start rule stopped being a
      comment — a test imports `app` in a subprocess and asserts no ADK, `google-genai` or
      `parallel` module reached `sys.modules`, because "we remembered to defer the imports" is
      not a property anyone can keep by intention. The tick guard has seven cases, including the
      unset-token one, which must fail closed. The image is **deliberately not built yet**: the
      wheel builds from exactly the four paths the `Dockerfile` copies, which retires the one
      non-obvious risk in it, and everything past that is Cloud Build's job. Docker stays off
      until the deploy step below — it is the last thing that needs it, and starting it earlier
      buys a slow local build of an image nothing is waiting on
- [ ] **Deploy** — start Docker and `docker build -t continuity .` first as a pre-flight: local
      Docker is *not* required to deploy (Cloud Build builds remotely from `--source .`), but a
      typo in the `Dockerfile` found locally is a two-minute fix instead of a Cloud Build round
      trip. Then deploy, confirm the hosted URL is publicly reachable and unauthenticated from a
      browser, and make one model call from the deployed service — the service account's Gemini
      role is still unverified and fails at the first call, not at deploy (`README.md`)
- [x] Decide the hosting shape — **one Cloud Run service, Python, serving `FE/` and the agent
      from the same container**; MediaWiki a second service on SQLite. Decided Aug 15, 2026.
      Reasoning and the rejected alternatives in §6; the topology in `AGENTS.md` §3
- [x] Resolve the build-step question — **there is no build step, deliberately.** Recorded in
      `AGENTS.md` §5 with the reasoning, replacing the earlier "add one with the frontend" TODO,
      which assumed a framework. Node checks the FE; it never builds or serves it
- [x] Pin the Fandom CC BY-SA version — done Aug 15, 2026. **CC BY-SA 3.0 Unported**, from
      the wiki's own `Project:Copyrights` (revision 3728), since `siprop=rightsinfo` reports it
      unversioned and the licensing page is JS-rendered. Notice written:
      `snapshots/ATTRIBUTION.md`. Share-alike carries onto the agent's own edits
- [x] **Specify the classify stage** — decided Aug 22, 2026. Parallel's batch chains into a
      Gemini node that sorts claims into *still true / new / conflicting* against current page
      state, and the review gate accepts a hand-edited draft as a third outcome alongside
      approve and reject. Reasoning and the agentic-risk caveat in §6. This retires the
      "contested cameo" claim entirely: the conflicting bucket is a generic output of the
      classifier, so no specific fact has to be pre-picked and nothing takes a cameo identity
      as input
- [x] **Add a fan-out stage** — decided Aug 22, 2026. Between Classify and Draft: a *new*-bucket
      result expands into the claims it implicates, seeded from `ripple_targets[]` and widened by
      discovery, with the new edges written back. Capped per run and one hop only. Reasoning in §6.
      This is the cascade beat (`seed-plan.md` §4.1) becoming a stage instead of an aspiration —
      the field existed on the record and nothing consumed it. Fanned-in claims reschedule as
      *changed* so the capped second hop still arrives soon (§7)
- [ ] *If time permits* — **an explicit retrieval-sufficiency criterion.** Gives the "retry: thin
      retrieval" edge a trigger anyone can implement: N sources at or above the claim's tier floor,
      and for a moving claim at least one published after its `as_of`. Fails → broaden the objective
      and retry, bounded by `research_rounds` (already capped at 3). Deterministic, so it belongs in
      the pure core beside the tier table. Satisfies §4's requirement 5, which nothing currently does
- [ ] *If time permits* — **split *still true* into confirmed vs unchallenged.** A qualifier inside
      the bucket, not a fourth bucket, so the review split stays three-way. Confirmed = retrieval
      corroborated it; unchallenged = retrieval found nothing against it. Treating them alike is how
      the ledger rots quietly: absence of evidence bumps `last_verified` and doubles the interval, so
      a claim no one can source gets checked ever less often. Fix lands in `decay.py` — unchallenged
      grows the interval by a smaller factor, or not at all
- [ ] **Rework `FE/` for the three buckets** — the queue is approve/reject over drafted edits
      today; it needs the bucket split, a *still true* view that shows confirmations rather
      than hiding them, a side-by-side conflict view, and an editable draft. `build_demo_state.py`
      has to emit the bucket per claim. This is rework of a passing component, so re-run
      `node FE/check.js`
- [ ] Before recording, confirm the run actually produced at least one conflict — §9 beat 6
      depends on it. Not a decision, a check: if the week is quiet, widen the research
      objective or close on a different beat
- [x] Write `README.md` — done Aug 15, 2026. What the product is, local run for both halves,
      routes, env vars, the deploy procedure (which until now lived only in conversation), repo
      layout and the MIT/CC BY-SA split
- [ ] Submission artifacts — ≤3-min video per the §9 beats, text description (features, tech,
      data sources, findings), and confirm the repo is public with the MIT licence detectable
      in the About section (§2)

**16 days left** as of Aug 22, 2026. The deterministic core, the seed corpus, the frontend and
the service shell are real and verified. What remains is the vendor perimeter — ADK graph,
Parallel, wiki writes — behind routes that already exist. The build is the risk now, not the
plan.

The frontend landing first was not the planned order, and it changed what the remaining work
looks like: the queue and ledger views define the shape the backend has to serve, so
`/api/state` is now specified by a working consumer rather than designed in the abstract.
The same JSON that `build_demo_state.py` writes is what Firestore has to produce.

---

## 11. Resources-tab phases (build guide, not competition stages)

1. **Core frameworks** — low-code Agent Builder vs custom SDK; credits form
2. **Action mechanisms & data connectivity** — script/PDF parsing, RAG with BigQuery,
   video transcription and captioning, Imagen, Lyria, TTS, sentiment analysis.
   *A capabilities menu, not an idea list — and skippable entirely*
3. **Partner integration** — five sub-pages, one per partner. Where the disqualification
   teeth are
4. **Reasoning, state & logic hosting** — ADK explicitly recommended over external wrapper
   libraries; function calling, forced function calling, MCP Database Toolbox, Agent Engine
   deployment
5. **Deployment & safety** — Cloud Run, Secret Manager, Gemini safety settings

**Phase 1 links resolved (Aug 11, 2026).** The four are a stack, not a menu — and the titles
are stale relative to what they point at:

| Link text | Target | Use it? |
|---|---|---|
| Agent Platform API Setup | `cloud.google.com/vertex-ai/docs` (generic root) | Enable API, move on |
| Agent Builder Guide (low-code) | **Dialogflow CX** docs | No — see §12 |
| Agent Platform SDK for Python | `googleapis/python-genai` = `google-genai` | Yes |
| Agent Engine Getting Started | a `generative-ai` repo notebook | Dated; now "Agent Runtime" |

---

## 12. Verified vendor facts (Aug 11 and Aug 22, 2026)

Primary sources only. Re-verify against installed packages before writing code (CLAUDE.md §1).

**The rebrand.** Vertex AI became the **Gemini Enterprise Agent Platform** at Cloud Next on
Apr 22, 2026. Old Vertex SDK modules stopped receiving updates after Jun 24, 2026. Pre-rebrand
tutorials, blog posts and model recall are all one naming generation behind.

Compliance is unaffected — rules verbatim: *"Accepted Google Cloud packages/SDKs: google-adk,
google-genai, google-generativeai, or google-cloud-aiplatform (any generation — legacy
libraries count equally)."*

**Auth — verified call shape.** Read from the `googleapis/python-genai` README, not recall:
the kwarg is `enterprise=True`, **not** `vertexai=True`; the env var is
`GOOGLE_GENAI_USE_ENTERPRISE`, **not** `GOOGLE_GENAI_USE_VERTEXAI`; `location` is `"global"`.
The working code is in `AGENTS.md` §5; the trap it replaced is `AGENTS.md` §6.

**Models.** `gemini-2.5-flash` shuts down 2026-10-16 and judging runs Sept 23–Oct 7 — nine days
of margin, so it is unusable, yet the ADK README's own example still shows it. The pins that
follow from that are in `AGENTS.md` §2.

**Parallel Search — verified live Aug 22, 2026.** `client.search()` on `parallel-web` 1.3.0
returns per result only `url`, `excerpts` (markdown), and an optional `title` and
`publish_date`. There is no authority, relevance or confidence field, which confirms the §6
design rather than contradicting it: tier is ours to assign from the domain, deterministically,
and the model never sees a number it could have influenced. Billing is one `sku_search` per
*call* regardless of how many queries it carries, so batching a claim's queries into one call
costs the same as one query — which is what makes the fan-out stage affordable. The settings
that matter are `source_policy.include_domains` (the tier table as a retrieval filter — see §6)
and `source_policy.after_date` (server-side recency, more reliable than the optional
`publish_date`). Measured latency 1.4-5.8s.

Verified live Aug 22, 2026 by enumerating `client.models.list()` on our own project rather
than trusting the names written here: `gemini-3.1-pro` does **not** exist — it 404s, and the
served name is `gemini-3.1-pro-preview`. Also available and newer than assumed:
`gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3.7-flash`.

**One model, `gemini-3.5-flash`, everywhere — decided Aug 22, 2026 on measurement.** The
planned two-tier split (pro to adjudicate, flash for throughput) assumed the hard node needs
the expensive model. Benchmarked on the Classify task against the real seed corpus — four
cases from `seed-plan.md` §4 including the Human Torch precision test, six reps at
temperature 0:

| Model | Correct | p50 | Note |
|---|---|---|---|
| `gemini-3.5-flash` | **24/24** | **3.78s** | |
| `gemini-3.6-flash` | 22/24 | 4.50s | missed `new` twice |
| `gemini-3.7-flash` | 21/24 | 3.99s | newest ≠ best |
| `gemini-3.1-pro-preview` | 12/24 | 5.88s | see below |

Pro loses because it reads the claim sentence *literally*: asked whether "Gambit appears in
*Deadpool & Wolverine*" is still true, it answers `still_true` and disregards the *Doomsday*
casting sitting in the same retrieval batch. That is a defensible reading of the question, but
it is not the one §6 specifies — `new` is defined against what the **page** lacks, not against
what the claim sentence asserts. Flash follows the stated rule; pro substitutes a narrower one.

Three consequences. The **preview risk disappears** — nothing in the build depends on a
`-preview` model through judging. The **cost model gets simpler**: §7's decay ladder was
designed around pro calls being the expensive scarce thing, and they are now not in the
system. And there is no per-node model routing to build or explain.

*Scope of the claim:* four cases, one stage. It measures Classify, the node whose errors
propagate silently; Draft output is human-gated at Publish, so a weaker draft costs a reviewer
edit rather than a wrong page. Revisit if Draft quality disappoints — the model is named in one
place. Raw script: `bench_classify.py` (scratchpad, not committed).

**ADK 2.0 = Workflow Runtime.** Graph execution engine; agents, tools and functions are
*nodes* (`BaseAgent` now subclasses `BaseNode`). `NodeInterruptedError` exists to pause a
workflow for human-in-the-loop input.

This is what makes §6 buildable as designed rather than a diagram: the 7-stage flow with two
backward edges maps onto a workflow graph, and the publish approval gate onto HITL. Nothing
about the product changed — see `AGENTS.md` §7 for the construction rule.

**Low-code path rejected on evidence.** The "Agent Builder Guide" link resolves to Dialogflow
CX — the conversational-agent surface. No way to express the graph, and its managed grounding
means Google Search as provider, which §5 already rules out on the Parallel track.

**Open inference, flagged.** Whether ADK satisfies the rules' "Google Cloud Agent Builder"
has no verbatim confirmation. Supporting it: `google-adk` heads the accepted-package list, and
Resources Phase 4 recommends ADK over external wrapper libraries. Inference, not quotation.

**Hard exclusion.** ADK ships adapters for non-Google models, and the platform catalogs 200+
of them (Claude included) — so the wrong `model=` string is one autocomplete away while
staying perfectly valid ADK. The §2 AI restriction bans them outright; the invariant that
guards it is `AGENTS.md` §2.
