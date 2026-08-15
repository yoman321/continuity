# Agentic Cinema Hackathon — Working Context

Carry-forward summary for re-prompting. Everything below was established in a prior
conversation. Sources: `agentic-cinema.devpost.com` Rules and Resources pages (fetched
directly), plus vendor documentation.

---

## 1. BLOCKER — check this first

**Quebec residents are ineligible.** The official rules list Quebec among the excluded
jurisdictions, and state the contest is void there. Standard carve-out (Quebec contest
law), but it means no prize eligibility.

Options if this applies:
- Build it as a portfolio piece anyway
- Team up with an eligible Representative (prize is paid to the team's Representative)
- Verify against the current rules text before investing further

Everything below assumes this is resolved or accepted.

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

### Control flow (6 stages, 2 feedback loops)

```
Audit page ──→ Research ──→ Adjudicate
(flag at-risk  (Parallel   (weigh source
 claims)        search)     tiers)
    ▲               ▲            │
    │               └────────────┘  retry: unresolved
    │                            │
Publish ←──── Verify ←──── Draft edit
(human       (check for    (section-level
 approves)    conflicts)    diff)
                  └────────────→┘  retry: introduced conflict
```

The two return arrows are where the agentic behaviour lives.

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
When the agent can't adjudicate, it writes `status: unresolved` plus the objective it was
pursuing. That claim is re-attempted when new sources appear. **This is the strongest
behaviour in the design** — an agent that knows what it doesn't know yet and comes back.

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
6. **Close on the refusal** (§4.5): two credible outlets disagree, and the agent declines to
   resolve it, marking `unresolved` and queueing a revisit. The most trustworthy thing it does
7. Optionally: run twice on the same film (restricted vs full source set) to show
   confidence moving

---

## 10. Open next steps

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
- [ ] **Build the wiki profile** — endpoint + transport, title grammar, section vocabulary,
      tier table, licence, auth (§5). Lifts the hardcoded Fandom assumptions out of the core:
      `EntityRef.from_title`'s `/` split and `ledger/tiers.py`'s trade-press table are both
      wiki-specific today. Ship two profiles (MCU Fandom, one Wikipedia) so "plug and play" is
      demonstrated rather than asserted
- [ ] Define ADK tool signatures — Parallel search, MediaWiki read (built), MediaWiki
      section-write, ledger read/write. All take the profile; none hardcode a wiki
- [ ] Build the 6-stage ADK graph — nodes, the two backward edges, and the publish gate as
      the HITL pause (§6, `AGENTS.md` §7)
- [ ] Build the ledger persistence adapter — Firestore, importing *from* the pure core
- [ ] Stand up seeded MediaWiki on Cloud Run — create the 12 pages from `snapshots/seed/` via
      `action=edit`. Redirects are already resolved in the manifest, and `Special:Export` /
      `importDump.php` is not an option (Cloudflare), so the seeding script posts the wikitext
- [ ] **Build the review queue frontend — this is the hosted project URL**, which is pass/fail
      (§2: "a concept or tech demo alone fails"), and Design is one of four equally weighted
      judging criteria, so it carries real score rather than being plumbing. Two surfaces:
      the **queue** — each drafted edit with its diff, citations, confidence badge and
      approve/reject, which is the §6 publish gate made visible — and a **ledger view** over
      the 50 claims showing status, wave and next check, which is what demonstrates the agent
      is stateful rather than a prompt chain. Now also the surface where **plug-and-play**
      becomes visible: a wiki picker or profile input, so a judge sees the agent pointed at a
      wiki rather than wired to one (§5).
      *What does not need building:* MediaWiki renders wiki pages and native `?diff=` views
      itself, so link through to the seeded instance instead of reimplementing page display
- [ ] Deploy and confirm the hosted URL is publicly reachable, unauthenticated, on web
- [ ] Add a build step to the verification gate, in the same task as the frontend
      (`AGENTS.md` §5)
- [x] Pin the Fandom CC BY-SA version — done Aug 15, 2026. **CC BY-SA 3.0 Unported**, from
      the wiki's own `Project:Copyrights` (revision 3728), since `siprop=rightsinfo` reports it
      unversioned and the licensing page is JS-rendered. Notice written:
      `snapshots/ATTRIBUTION.md`. Share-alike carries onto the agent's own edits
- [ ] Pick the specific contested cameo for `seed-plan.md` §4.5 at ledger-seed time — it has
      to be one that is genuinely split in trade reporting that week
- [ ] Write `README.md` — setup, commands, routes, env vars (`CLAUDE.md` §2)
- [ ] Submission artifacts — ≤3-min video per the §9 beats, text description (features, tech,
      data sources, findings), and confirm the repo is public with the MIT licence detectable
      in the About section (§2)

**23 days left** as of Aug 15, 2026. The deterministic core and the seed corpus are real and
verified; what remains is the vendor perimeter — ADK graph, Parallel, wiki writes, frontend.
The build is the risk now, not the plan.

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

## 12. Verified vendor facts (Aug 11, 2026)

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

**Models.** `gemini-3.1-pro` and `gemini-3.6-flash` are current as of this date.
`gemini-2.5-flash` shuts down 2026-10-16 and judging runs Sept 23–Oct 7 — nine days of margin,
so it is unusable, yet the ADK README's own example still shows it. The pins that follow from
that are in `AGENTS.md` §2.

**ADK 2.0 = Workflow Runtime.** Graph execution engine; agents, tools and functions are
*nodes* (`BaseAgent` now subclasses `BaseNode`). `NodeInterruptedError` exists to pause a
workflow for human-in-the-loop input.

This is what makes §6 buildable as designed rather than a diagram: the 6-stage flow with two
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
