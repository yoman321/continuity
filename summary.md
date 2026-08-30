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

What does *not* generalize is everything that encodes one wiki's conventions:

| Varies per wiki | The demo profile | Elsewhere |
|---|---|---|
| Title conventions | `/` splits a variant subpage | Wikipedia disables mainspace subpages — `AC/DC` is a real 202KB article our parser splits into `AC` + `DC` |
| Section vocabulary | no Box office / Reception anywhere | Wikipedia has all three, so §5's "that claim has no home" reasoning inverts |
| Source tiers | entertainment trade press | meaningless on a medical or software wiki |
| Licence | Fandom CC BY-SA 3.0 | Wikipedia CC BY-SA 4.0 — different attribution |
| Write policy | our own instance | Wikipedia needs Bot Approval Group sign-off; stricter, not looser |

So the architectural unit is a **wiki profile**: endpoint, title grammar, section vocabulary,
tier table, licence, auth, and the pages it monitors. Built Aug 23, 2026 — `WikiProfile` carries
them and the core reads them, so the middle column above is what a profile *holds*, not something
compiled in. The agent core stays wiki-agnostic. Anything wiki-specific that leaks into the core
is the bug (`AGENTS.md` §2).

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

### Control flow (8 stages, 2 backward edges)

```
Audit ──→ Research ──→ Classify ──→ Draft ──→ Diff ──→ Verify ──→ Publish ──→ Fan-out
          ▲  ▲            │                            (human)    (button)       │
          │  └────────────┘                                                      │
          │    thin retrieval                                                    │
          └──────────────────────────────────────────────────────────────────────┘
               one hop, capped, and only for an edit a human approved
```

| Stage | What it does |
|---|---|
| **Audit** | hands over the claims whose `next_check_at` has passed, and says why it passed over the rest |
| **Research** | one batched Parallel search per claim set, against the objective the ledger holds |
| **Classify** | Gemini reads the excerpts against the page and sorts each claim: still true / new / conflicting |
| **Draft** | a section-level edit, rendered as a diff, with citations and a confidence score |
| **Diff** | reads the edit for what it did to the *ideas* already on the page — kept, added, dropped or reversed |
| **Verify** | the human gate. Every section with a diff is a card: the reviewer reads it beside the Diff stage's flags, edits the text in place if they want to, and accepts or rejects. Accepting writes nothing. No model call |
| **Publish** | the write, and the second gate. One button over the accepted set, unlocked only once every card has a decision, so the run can still be discarded whole. The API then applies each approved text with `action=edit&section=N`. The only stage that touches the wiki |
| **Fan-out** | takes the edit that was *actually applied* and expands it into the claims it implicates on other pages |

**Before Audit, and outside the graph:** the baseline ingest reads every page in
`WikiProfile.pages`, splits it, and stores the sections verbatim. It is deterministic — no model
call and no judgement — so it is a pre-pass rather than a stage, and everything above runs
against a baseline that already exists. Keeping it separate is what stops Audit doing double
duty; the reasoning is under the claim ledger below.

Neither Diff nor Verify adds a backward edge, so **Draft has no automatic retry path at all.**
What Diff finds arrives at Verify as a flag on the card; what Verify decides, a person types.
Both are cases where the fix is a human reading the edit rather than a second machine attempt,
and an automatic-retry edge into Draft would double the termination surface the one-hop fan-out
rule already has to carry. This is the Aug 30, 2026 simplification recorded below.

The two backward edges are where the agentic behaviour lives — `Classify → Research` because a
stage's output decides whether the next one runs, and `Fan-out → Research` because it decides
how much of the wiki this run touches at all. The run ends at Fan-out; the next tick re-enters
at Audit.

### The classify stage — decided Aug 22, 2026

Parallel returns a batch of excerpts, not an answer. The stage that consumes it is a Gemini
node that reads the batch **against the current page state** and sorts every claim it touches
into exactly three buckets:

| Bucket | Meaning | What the reviewer sees |
|---|---|---|
| **Still true** | the page already says this, and retrieval confirms it | the claim, its refreshed citation, and a bumped `last_verified` — no diff |
| **New** | retrieval carries something the page does not have | a drafted section-level insert with citations |
| **Conflicting** | page and sources disagree, or sources disagree with each other | both readings side by side, each with its tier and citation, and no auto-resolution |

**The queue reads like a git review, and that is deliberate.** A drafted edit is shown as a
diff — removed lines in red, added in green, and inside a line that was edited rather than
replaced, the exact words that moved. A reviewer approving an edit is answering "is this change
right?", and two blocks of text side by side do not answer it: the eye has to find the
difference before it can judge it. The one rule borrowed outright from git is that **the diff is
computed, never stored** — git holds snapshots and computes `git diff` on demand, and here a
stored diff would be correct only until the page moved, which the gate's whole purpose is to
allow time for. A conflicting claim is the one row that is not a diff: it is a choice between
readings of the world, each with its tier and citation, and resolving it is what produces the
diff rather than something the diff can express.

**One "conflict" here, not two.** Git's merge conflicts come from two branches editing a common
ancestor concurrently; this project assumes a single editor while the agent runs (`AGENTS.md`
§2), so the
page at publish time is the revision the draft was taken against and a *text* conflict cannot
arise. The only conflict a reviewer resolves is the semantic one: two sources disagreeing about
the world.

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

### The draft stage — decided Aug 29, 2026

Classify says *what* is true; this is the stage that decides what the page should say instead.
It rewrites one anchor — the exact substring the ledger already holds — and returns the
replacement, one sentence for the reviewer, and the source that becomes the footnote. The
section it sits in goes into the prompt as context and never comes back as the answer: the
anchor is what the ledger tracks, what the diff was sized for, and what a reviewer can read
without scrolling.

**The diff is the check, not the input — and working out which took an argument.** The
intuition is that Draft should compare the old text against the researched text and decide
from the comparison whether this is an addition or a contradiction. It cannot: retrieval
returns prose excerpts from the web, not a candidate revision of the wikitext, so there is no
second version to diff until something has written one. What *is* true is the other half of
that intuition, and it turned out to be the more useful half. Once a draft exists, comparing
it against what the page said is exactly how to catch a draft that overreached — and that
comparison is a stage of its own, described next.

What Draft carries is the cheap half of it. Whether the edit displaced any *text* is a fact
about two strings, computed in the deterministic core, and it is held against the bucket:
a claim sorted `new` means the page is incomplete rather than wrong, so a draft for it had
nothing to take away. This costs nothing, runs with no key, and is never wrong about text. It
is a floor, not the answer — the reading that matters happens in the Diff stage.

**Two of our own fixtures decided how that floor is computed**, pulling in opposite directions.
`GAM-APP-01` appends a second film by gluing `<br>''[[Avengers: Doomsday]]''` onto the end of
`|movie = ''[[Deadpool & Wolverine]]''` with no space between — a pure append that changes the
last token, so any word- or line-level test reports a rewrite of something that lost nothing.
`DW-VOID-01` retargets `[[Void]]` by inserting characters *inside* the anchor — a real rewrite
that a character-subsequence test threads straight through and calls an append. What separates
them is whether the old text survives whole and unbroken, so the test is containment. It errs
toward flagging: reindenting scores as a rewrite even when no word moved, which costs a
reviewer one careful read, where the opposite error costs a silent overwrite.

**The stage never revisits the bucket.** Classify already tested the excerpts against the page
and ordered the three buckets to make that judgement reproducible; asking a second model
whether the fact conflicts buys an opinion nothing can adjudicate, and the decay ladder has
already been driven off the first one. Draft is told `new` and writes an insert.

Confidence is not asked for and not accepted. It comes from the tier table over the distinct
domains backing the claim, like every other number on screen — a model-assigned score would
sit in the same field as a measured one and read identically.

### The diff stage — decided Aug 29, 2026

The textual shape answers whether the characters survived. That is not the question a reviewer
is asking, and the two come apart in both directions.

Take a draft that appends `, however Marvel later confirmed the character was cut` to the
sentence it was extending. Every original character is intact. Containment holds, the shape is
a clean `append`, the diff renders green, and the assertion the page used to make is gone.
Nothing was deleted and the meaning was still overturned — so no string comparison can find it,
because there is nothing for a string comparison to look at. The mirror case is just as real:
threading `(2024)` into the middle of an infobox value fails containment and scores as a
rewrite, while not one idea was dropped.

So the edit has to be read, not measured, and **reading is what an agent is for**. This stage
takes `before` and `after` and reports, assertion by assertion, what the edit did to each one:
kept, added, dropped, or *reversed*. `reversed` is the value it exists for — the assertion is
still sitting there on the page and the page now denies it. Any drop or reversal makes the edit
`destructive`, which held against a `new` classification is the same overreach guard as the
textual one, catching the cases the textual one structurally cannot.

**It is a specialised node, not something the orchestrator does.** Two separations are
deliberate. It is not part of Draft, because a stage that writes an edit and then rules on
whether the edit was conservative is reporting on itself, and that report is the one thing it
cannot be used to check. And it is not the orchestrator's own reasoning: the graph routes,
holds no opinion, and delegates every judgement to a node with one prompt, one schema and one
question. A model asked to both run the pipeline and evaluate its output has no separate
position to evaluate it from.

**It is deliberately not told why the edit was made.** No sources, no research objective, no
classification bucket — only the two texts. A reader handed the motive explains the edit; a
reader handed only the before and after examines it. The bucket comes back in afterwards, in
the deterministic core, when the verdict is held against it.

**And it is not Verify.** Since Aug 30, 2026 Verify is the human gate and holds no model call at
all, so what it puts on screen is largely *this* stage's output — the per-assertion verdict and
its flags, rendered beside the diff. Diff is the last reading the machine does; Verify is where
a person acts on it. The page-coherence check Verify used to be is gone, and what it would have
caught is named as an accepted gap in that decision.

**What it does when it finds one:** flags the card, and the run continues to the gate. It gets
no backward edge, and after this stage nothing else does either. An overreach is precisely the
thing a person should see rather than have quietly re-attempted on their behalf — and the
reviewer can now fix it in place at Verify rather than wait for a second draft.

**The fallback is the floor it sits on** (`CLAUDE.md` §3). With no model — expired credential,
no quota, no network — the stage degrades to the textual shape and marks the card `text_only`,
so a degraded run still gates edits, more coarsely and never silently. A displaced-text edit
that nothing read is reported as destructive rather than as clean: the honest reading of "no
one looked" is not "nothing happened".

Its rules are reasoned rather than measured, which is the difference between this stage and
Classify — the classify prompt's four rules each came from a benchmark. The harness that
produces those numbers is the open item in Phase 1, and it now has a second stage to cover.

### The fan-out stage — decided Aug 22, 2026; moved after Publish Aug 29, 2026

A confirmed fact rarely belongs to one claim. Gambit's *Doomsday* casting lands on `Gambit`,
on `Phase Six`, and on the film page's appearances context (`seed-plan.md` §4.1) — one search,
three pages. Fan-out is the stage that turns an *applied* edit into the full set of claims it
implicates, and hands that widened set back to Research.

**It runs after the gate and the write, not before them — corrected Aug 29, 2026.** The original design
put Fan-out between Classify and Draft, so a *new*-bucket classification widened the run and one
Draft pass covered the trunk claim and its dependents together. That is wrong about what causes a
ripple. What implicates other pages is not what the agent proposed; it is what the wiki now says,
and the two differ in two ordinary ways. The reviewer rejects, and the run has already spent
research and drafts on the dependents of a fact that never landed. The reviewer hand-edits — which
since Aug 30, 2026 is the whole purpose of the Verify gate, so "cast in *Doomsday*" can leave the
queue as "in talks for *Doomsday*" — and every dependent drafted from the pre-gate text now
overstates its premise, which nothing downstream catches. Reading the published revision instead
of the proposal removes both by construction rather than by another check.

It also fixes the gate itself. Under the old order a reviewer met the trunk edit and its
dependents in one queue, and approving a dependent meant approving a premise still sitting
unapproved two cards above. Now the premise is settled before its consequences are drafted, and
the causality is visible: approving an edit is what puts the next cards in the queue.

**What it costs** is a second pass through the gate inside one run — the trunk edit, then what it
implicates. That is the same `request_input` pause the graph already has to survive once, so it is
not new machinery, and the run being long-lived across a human decision is what the HITL gate
means in the first place.

`ripple_targets[]` on the `Claim` record already stores the links the ledger knows about, so
the stage starts from a lookup, not a guess. What it adds on top is discovery: a fact can
implicate a claim nobody recorded a link for, and those edges get written back so the next run
starts better informed. The ledger gets denser with use.

**Why this is the stage that answers the pipeline objection.** A retry edge only says "try
again," which a `for` loop also does. Fan-out means the set of claims a run touches was not
knowable when the run started — Audit picked the due claims, and what happened at the gate added
more. Moving it after Publish strengthens that rather than weakening it: the working set is now
decided by a human answer mid-run, which is a plan chosen at runtime in the least arguable way
available. That is §4's requirement 2 (plan chosen at runtime, varying by input) demonstrated
rather than asserted, and it is also the video's opening beat, so the most convincing evidence of
autonomy and the most legible thing on screen are the same feature.

**Bounded, like every other loop here.** Fan-out expands the working set, so it needs a ceiling
or one busy news day turns a tick into a full-wiki rewrite: cap the added claims per run, and
do not let a fanned-in claim fan out again in the same run. One hop, not transitive closure.

That cap now carries a second job. `Fan-out → Research` is a genuine cycle in the graph, and the
non-transitive rule is the only thing that breaks it: a fanned-in claim runs Research → Classify →
Draft → Diff → Verify → Publish and stops there. Before the move the rule was a cost control; now
termination depends on it, so it belongs in the node rather than in a config a future run could
raise.

**The second hop happens next tick, not this one.** Capping at one hop does not lose the rest of
the cascade. A claim fanned into a run has been touched, so its `next_check_at` is pulled forward
and it fans out from *itself* on a later tick — and so is a claim the cap excluded from this run,
which is what keeps the ceiling a deferral rather than a drop — the full graph still gets walked, just in bounded
steps with a human gate between each. The pull-forward is a rule rather than an implication (§7):
a fanned-in claim left to decay like a quiet one would double its interval and put the second hop
weeks away, which silently converts a cascade into an unrelated edit much later.

**What keeps this agentic (§4).** Fetch → classify → human is a linear pipeline on its own,
and §4's litmus test would fail it. **Three** things keep it from being one, and all three have
to survive implementation: the ledger decides *which* claims are fetched and when
(`next_check_at` is agent-chosen, §7); fan-out lets an approved edit widen the run; and a thin
or off-target retrieval sends the graph back to Research with a broadened objective rather than
forward to a bad classification.

A fourth was cut on Aug 30, 2026 — a draft that introduced a conflict elsewhere on the page used
to go back to Draft — so the remaining three now carry this argument alone. Fan-out is the
strongest of them: after the gate move the working set is decided by a human answer mid-run,
which is a plan chosen at runtime in the least arguable way available. Cut these three as well
and this becomes RAG with a review screen — the exact quiet failure §4 names.

### The claim ledger (central state)

**Two collections carry the agent's memory, written at different times** — and a third,
`drafts`, carries the review that follows them (see the decision log entry "The review draft is
a stored document"). `sections` is the baseline — what each
monitored page says right now, recorded verbatim by an ingest pass that reads the wiki, splits
it and stores it. `claims` is what the agent tracks. The split exists because the two need
different things: deciding what a page *asserts* is a judgement and needs the model, while
recording what a page *says* is deterministic and needs nothing. So step 1 of a run has no key,
no model call and no failure mode beyond the wiki being unreachable — and everything research
later finds is measured against a baseline that already exists rather than against a claim set
being invented in the same breath.

A page's sections are replaced as one set, never merged, because their indices are only
meaningful relative to each other; and `WikiProfile.pages` names what to ingest, because the
agent is not a crawler and which pages we maintain is a decision somebody made.

One row per atomic claim:
`claim_id`, `page`, `section`, `text`, `status`, `confidence`, `sources[]`,
`last_verified`, `next_check_at`, `contradicts[]`

This is what makes it stateful rather than a prompt chain, and what lets the agent answer
"have I already checked this?"

**`status` has two values, and answers one question: does a human need to look at this.**
`verified` means the page stands and there is nothing for a reviewer to do. `unresolved` means
a person decides — either sources conflict and the agent declined to pick, or an edit is
drafted and waiting at the Verify gate. Those two are one status on purpose: both are rows in
the review queue, and `contradicts[]` is what tells them apart, derived rather than stored.

Two things deliberately *not* on the record. **Where an edit sits in the publish pipeline** is
the queue's state, not the claim's — drafted, approved and applied describe an edit, and a
rejected edit leaves the claim exactly as it was, so the claim never needed to know. **Age** is
not a status either: a claim goes stale by the clock passing `next_check_at`, which is a
comparison, not a state to write down. One run turns a stale record back into `verified` or
`unresolved`, and that is the only thing that ever writes `status`.

**Claims are filled by runs, never by hand.** The baseline arrives first, from the ingest pass;
a claim is tracked only once a run has proposed it against that baseline, checked it and written
it back. The six claims in `FE/data/demo-state.json` are a fixture standing in for state no run
has produced yet (`AGENTS.md` §4). So no target count appears anywhere in these documents — how
many claims exist is an output of the pipeline, and `seed-plan.md` §3 describes the kinds the
seed carries rather than a quota.

**Local now, Firestore after the deploy weekend.** The store is a JSON file on disk today and a
Firestore collection in Phase 2, and the port is deliberately boring: one module owns the
document shape, both stores write it, and the adapter is a transport swap. Building it this way
round is what lets the graph be assembled and tested with no database, no emulator and no cloud
project — the same argument that put `SnapshotPageSource` behind the wiki reads. The rules that
make the local store *behave* like Firestore rather than merely stand in for it are invariants
now, in `AGENTS.md` §2, because getting either wrong is a failure that appears only after deploy.

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

**What that works out to.** The load is the hourly tick plus a handful of judge visits. At
1 vCPU / 1 GiB with a 60-second tick, 720 ticks a month is roughly 43k vCPU-seconds and 43k
GiB-seconds — inside Cloud Run's monthly free allowance, and about **$1** even if it were
billed in full. Firestore (50k reads / 20k writes a day), Cloud Scheduler (3 jobs) and Secret
Manager (6 active versions) are all far below their free thresholds at one job and a handful of
secrets. Artifact Registry is the only *free-tier* line that plausibly overruns: 0.5 GB is
free and `google-adk` makes the app image fat enough to pass it, for something like $0.10/mo.
Everything except Gemini and the Cloud SQL instance below is rounding error.

*These rates and thresholds are from recall, not the console* — same standing as the other
unverified figures below. The conclusion does not depend on their precision, but check them
against a real bill before trusting a number, and set the $25 budget alert (`README.md`) before
the first deploy rather than after.

**Two things would turn that into a real bill, and both are self-inflicted.** Setting
`--min-instances 1` bills an instance around the clock instead of per request — roughly 2.6M
vCPU-seconds a month, which is tens of dollars rather than one. The temptation is cold start,
5-15s, which a judge experiences as a broken link; the free fix is the lazy imports already
required by `AGENTS.md` §7, not a warm instance. The other is a tick that runs long: `--timeout
900` means a stuck research loop can burn fifteen minutes of CPU *and* tokens, 720 times a
month. `--max-instances 3` and the timeout bound the damage, but the research-round cap is what
actually prevents it.

**MediaWiki is the one piece that fights this — and it wins. Decided Aug 23, 2026.** It wants
a relational database, and Cloud SQL cannot scale to zero: the smallest shared-core instance
bills ~$8-10/mo whether or not anyone visits. The plan was to dodge that by putting the SQLite
file on a GCS bucket mounted as a Cloud Run volume. That does not work. gcsfuse implements
neither file locking nor partial random writes, which are exactly the two things SQLite depends
on, and Google's own guidance puts databases out of scope for it — so the failure mode is a
corrupted DB discovered some time after seeding, not a clean error at mount. Firestore is not an
escape either: MediaWiki speaks MySQL, PostgreSQL or SQLite, and a document store cannot back
it. Firebase Storage is not one at all — it *is* a GCS bucket, so it fails identically.

So the wiki's database is the one line that bills while idle, and two free routes were weighed
and rejected. A third-party Postgres on a free tier (Neon, Supabase) is permitted — §2's
AI-usage clause leaves non-AI services unrestricted — but it puts MediaWiki on its
less-travelled DB path and moves the demo's data off GCP. An always-free `e2-micro` VM running
MediaWiki and MariaDB also costs nothing, but it is a VM to babysit two weeks out and it trades
the scale-to-zero story for a machine that is always on. Both spend scarce engineering time to
save ~$16 through judging, against $100 of credits confirmed received Aug 23, 2026. Cloud SQL is
the boring answer and the right one.

**Two costs are deferred, not avoided.** Cold start is 5-15s if the container imports the
vendor SDKs at module load, which a judge would experience as a broken link; the fix is lazy
imports rather than a paid warm instance (`AGENTS.md` §7). And because judging requires the
service be publicly reachable without auth, IAM cannot protect the scheduler endpoint — the
tick route has to authenticate itself, which is an invariant rather than a nicety
(`AGENTS.md` §2).

### Guardrails (double as "bounded autonomy" judging points)
- Max 3 research rounds per claim. `MAX_RESEARCH_ROUNDS` and `Claim.budget_spent` are in the
  core, but **nothing refuses a fourth round yet**: `record_research` spends a round without
  consulting the budget, so the Research node is where the check has to land
- Confidence threshold below which nothing auto-applies — `Claim.auto_appliable`, against
  `tiers.AUTO_APPLY_THRESHOLD`, and never a bypass of the gate below
- Dry-run by default: nothing reaches the wiki that has not passed the gate
- Human approval gate before publish — the **Verify** stage, where the run pauses and the
  reviewer accepts or rejects each diff, editing its text first if they want to. One card per
  section with a change; Publish fires only on a button press. Since fan-out follows it (§6),
  the gate also decides whether the run widens at all
- **An edit may not take away what it was not asked to take away.** A claim classified `new`
  means the page is incomplete, not wrong, so a draft for it has nothing to remove. Two readings
  enforce that: `diff.shape()` on the text, free and deterministic, and the Diff stage on the
  ideas — which is the one that catches an appended clause reversing the sentence it extended.
  Either verdict flags the card; neither blocks it, because which stage was wrong takes a person

### Error recovery to build *and* demo
- Parallel returns nothing useful → broaden the semantic objective, retry
- Parallel *errors* — no key, a quota, retries exhausted → discard the round outright: no
  sources, no budget spent, no schedule change, and the claim simply comes due again. Not the
  same case as the line above, and the distinction is load-bearing: recording an error as zero
  sources routes to `unchanged`, which **doubles** the interval, so a broken key would make the
  agent check that claim less and less often while reporting nothing (`AGENTS.md` §7)
- Sources irreconcilable → mark unresolved, publish the rest
- MediaWiki edit conflict (a human edited mid-run) → re-read, rebase, retry
  — **best thing to put on camera**: real, unglamorous, proves the loop works.
  Note the relationship to the single-editor assumption (`AGENTS.md` §2): the assumption is
  what lets the *review queue* skip text conflicts, and this is the guard that catches the
  assumption being wrong. Demonstrating it means deliberately breaking the assumption on
  camera, which is the honest way to show a guard — the recovery is re-draft, not a merge UI

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

**Fan-out overrides decay.** A claim named by fan-out (§6) is rescheduled as if it changed —
interval halved, `next_check_at` pulled forward — however small its own edit was, even if it got
none, and even if the per-run cap kept it out of this run entirely. Sitting next to a fact that
just moved is the best available signal that a claim is about to move too, and it is what makes
the second hop of a cascade arrive soon instead of at the ceiling. Because fan-out now runs after
the gate, the signal is stronger than it was: the fact next door did not merely get proposed, it
got published.

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
*right now*," which the confidence threshold already answers. What kinds of claim each wave
carries is in `seed-plan.md` §3; how many exist is an output of the pipeline and never a target
(`AGENTS.md` §2).

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

**Hackathon scope: one wiki, one film, ~12 source domains.**

---

## 9. Demo video plan (3 min max)

Beat order follows `seed-plan.md` §4, which names the specific claim behind each.

1. Audit picks the claims that are due — and says why it passed over the rest
2. **The cascade** (§4.1): one confirmed announcement lands on three pages at once. Opens the
   video because it reads in seconds. Since Fan-out moved after the gate (§6) this beat now shows
   the *approval* as the cause — approve the trunk edit and the queue repopulates with the two
   pages it implicates, on camera. That folds a first look at the diff queue into beat 2; beat 4
   still earns its place on citations and confidence, which this beat does not stop to read
3. **The claim that broke without an edit** (§4.2): a link that was right in 2024 and now
   points at the wrong character, because a later film took the name. No page diff would
   surface it — this is the case for the product
4. Diff queue with citations and confidence badges
5. **Break something live** — revoke the Parallel key, or edit the page underneath it —
   and show recovery. Editing the page underneath is deliberately breaking the single-editor
   assumption (`AGENTS.md` §2): `basetimestamp` catches it, the write is refused rather than
   overwriting the human, and the claim is re-drafted. Showing a guard fire is worth more than
   claiming the case cannot happen
6. **Close on the conflicting bucket** (§6): the agent puts two readings side by side with
   their tiers and citations and declines to pick, handing the judgement to the reviewer. An
   agent that says *"these disagree and I am not resolving it"* reads as more trustworthy than
   one that always produces an answer. Which claim this is depends on the run — see §10
7. Optionally: run twice on the same film (restricted vs full source set) to show
   confidence moving

---

## 10. Open next steps

**Start here.** The `[x]` log below is chronological and records what was decided and when. It
is not the plan — the plan is the two ordered phases after it.

**Everything buildable locally is built locally first — decided Aug 23, 2026.** MediaWiki cannot
tell a MariaDB container from Cloud SQL, `.env` already stands in for Secret Manager by design
(`AGENTS.md` §2), and the ledger is a JSON file holding the documents Firestore will later
hold — so no item in Phase 1 needs a cloud resource to exist, and the Cloud SQL meter does not
start until the instance does. The Firestore *emulator* covers none of this and was never available:
it needs a JRE and a `gcloud` component that are not installed, which is why the store ports by
document shape instead (Aug 29, 2026 entry below).
The one thing local work genuinely cannot prove is whether `continuity-run@`'s three roles are
sufficient, because local ADC runs as the project Owner and therefore always succeeds; service
account impersonation closes even that, and it is Phase 2's first item.

As of Aug 30, 2026 the critical path is **(1)** the 8-stage ADK graph, **(2)** recording the
demo video, **(3)** the deploy weekend. Four of the graph's eight stages now have working
implementations underneath them — the baseline half of Audit, Classify against real Gemini,
Draft with the `Draft` record it writes to, and Diff — so what is left of (1) is the wiring,
claim proposal (now the only stage that still needs a model), and the Verify gate, which since
Aug 30 needs no model at all and is FE work plus the publish route. The local MediaWiki, which
held item (2) until Aug 29, is up, seeded and verified, so the agent now has somewhere it is
allowed to write.
Both vendor perimeters — Gemini/ADK and Parallel — are proven and the FastAPI shell is written,
so what is left is the agent itself. Nothing here is blocked on an unknown API.

**The wiki and the graph swapped places on Aug 23, 2026,** once the read tool landed with a
snapshot-backed `PageSource` behind it. Every read stage — audit, classify, draft, verify —
now runs against the hash-checked corpus in `snapshots/`, so the graph can be built and tested
with no MediaWiki anywhere. What still genuinely needs the instance is the write half: the
`action=edit` section write, the edit-conflict recovery path, and the video beats that show a
page changing. That is a smaller surface than the whole graph, and it means a slow Docker
afternoon can no longer stall the largest remaining item.

**The video is Phase 1 work, and that is a correction — decided Aug 23, 2026.** It was filed
under the deploy weekend, which was wrong twice over: it is the largest single task remaining,
and it has no dependency on deployment at all. All seven §9 beats run against localhost —
including beat 5, breaking something live, which is *easier* locally, since editing a page
underneath a run is a one-line change against your own instance. Leaving it in Phase 2 would
have put recording, editing and writing the description on the same two days as provisioning
Cloud SQL and standing up two services. The only submission item that genuinely needs the deploy
is pasting a URL into a form.

- [x] Confirm Quebec eligibility position — N/A, based in Miami. Re-read current rules text
      once to be certain; it's the one blocker that invalidates everything else
- [x] Request $100 GCP credits — requested Aug 11, 2026, **confirmed received Aug 23, 2026**.
      General-purpose Google Cloud billing credits; the hackathon's resources page states no
      product restriction, so they cover Cloud SQL as readily as Gemini
- [x] **Public repo with an MIT licence** — done Aug 11, 2026, re-verified Aug 23, 2026.
      `github.com/yoman321/continuity` answers unauthenticated and `git ls-remote` succeeds with
      credentials disabled, so it is genuinely public, and `LICENSE` is MIT at the repo root —
      which is what §2's "detectable in the About section" is asking for. Not verified from here:
      that GitHub's sidebar actually renders the licence badge (its API was unreachable on Aug
      23) — a ten-second look at the repo page settles it. The **content** licence is separate
      and stricter: `snapshots/` is CC BY-SA 3.0 and carries onto the agent's own edits, see
      `snapshots/ATTRIBUTION.md`
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
- [x] Draft the claim ledger schema — done Aug 15, 2026. `backend/core/ledger/` (then
      `src/continuity/ledger/`): the `Claim`
      record with `claim_kind` and `entity_ref`, the domain→tier table with deterministic
      confidence, and the double/halve/clamp decay logic. Dependency-free and frozen; tests
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
- [x] **Settle the MediaWiki database** — decided Aug 23, 2026, and it did not need the test.
      SQLite-on-GCS is dead on the documented behaviour of gcsfuse: no file locking, no partial
      random writes, databases explicitly out of scope. The failure mode would have been a
      corrupted DB after seeding rather than an error at mount, so this was worth closing on
      the docs rather than on a write-read-restart cycle. **Cloud SQL, MySQL, shared-core** —
      ~$16 through judging against credits now confirmed. Firestore cannot back MediaWiki at
      all; the two free routes both cost engineering time to save $16. Reasoning and rejected
      alternatives in §6
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
      layer lives in `backend/` rather than beside the core, because the pure half and
      everything with a vendor import belong on opposite sides of a boundary. That boundary
      was a directory split until Aug 23, 2026, when the core moved to `backend/core/` and the
      split became an import-path one instead — same rule, more visible (`AGENTS.md` §4). Two calls worth recording.
      `/api/state` answers **503 rather than serving the fixture**: the frontend decides
      live-vs-fixture from that one response, so answering it with `demo-state.json` would put a
      *live* pill above an agent run that never happened. And the cold-start rule stopped being a
      comment — a test imports `app` in a subprocess and asserts no ADK, `google-genai` or
      `parallel` module reached `sys.modules`, because "we remembered to defer the imports" is
      not a property anyone can keep by intention. The tick guard has seven cases, including the
      unset-token one, which must fail closed. The image is **deliberately not built yet**: the
      wheel builds from exactly the paths the `Dockerfile` copies — re-verified Aug 23, 2026
      after the layout move, now `pyproject.toml` + `backend/` — which retires the one
      non-obvious risk in it, and everything past that is Cloud Build's job. Docker stays off
      until the deploy step below — it is the last thing that needs it, and starting it earlier
      buys a slow local build of an image nothing is waiting on
- [x] Decide the hosting shape — **one Cloud Run service, Python, serving `FE/` and the agent
      from the same container**; MediaWiki a second service, on Cloud SQL since Aug 23, 2026 (§6).
      Decided Aug 15, 2026.
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
      *changed* so the capped second hop still arrives soon (§7). **Position superseded Aug 29,
      2026** — the stage stands, but it runs after Publish rather than before Draft; see the
      entry below
- [x] Write `README.md` — done Aug 15, 2026. What the product is, local run for both halves,
      routes, env vars, the deploy procedure (which until now lived only in conversation), repo
      layout and the MIT/CC BY-SA split

- [x] **Close the variant-vs-prime hole in Classify** — decided Aug 23, 2026. `entity_ref` has
      been on the `Claim` since Aug 15 and `AGENTS.md` already routed "sources are about a
      different entity" to `conflicting`, but nothing said the classifier is *given* the entity —
      so the rule asked the model for a judgement it had no input for. Two rules now in
      `AGENTS.md` §7: the prompt states the subject including the variant and that prime and
      variant are distinct subjects, and off-entity excerpts are **filtered out before**
      classification rather than classified. The second matters more: an excerpt about Johnny
      Storm is not evidence for or against a claim about the *Void-Analyzing* variant — it is
      not evidence at all, and routing it to `conflicting` per-excerpt would fill the review
      queue with noise exactly as closed-world phrasing did (§6). `conflicting` is now reserved
      for the case where filtering empties the batch, which is the honest signal that retrieval
      missed. Guards `seed-plan.md` §4.3, benchmark case #4

- [x] **Build the wiki profile** — done Aug 23, 2026. `backend/core/profile/` holds
      `WikiProfile` (endpoint, transport, title grammar, section vocabulary, tier table,
      licence, User-Agent, writability) plus the two shipped instances, `MCU_FANDOM` and
      `WIKIPEDIA_EN`. The dependency runs one way — `profile/` imports the ledger core and
      never the reverse — so the core stayed profile-agnostic instead of gaining a config
      import. Four things left the core: `EntityRef.from_title` now takes a required
      `subpages` keyword **with no default**, because a default is how the wrong grammar gets
      used silently; `tiers.py` kept the mechanism and gave up the table; `Source` resolves its
      domain once at creation and stores it, so `recompute_confidence` still needs no profile;
      and `MediaWikiReader` lost its MCU endpoint and User-Agent defaults in favour of
      `for_profile()`. Two things came out better than planned. **`writable` turns
      `AGENTS.md` §2's "never write to a real wiki" from prose into a field a test asserts** —
      neither shipped profile has it. And the section vocabulary is read off `snapshots/seed/`
      rather than imagined, which caught two headings I had dropped when transcribing
      (`Notable Pruned Objects`, `Time Variance Authority Files`) — the test found them, not a
      re-read. Tests pass — `tests/test_profile.py` is new — mypy strict and ruff
      clean, and `build_demo_state.py` regenerates `demo-state.json` byte-identically, which is
      the evidence that a refactor this wide changed no computed output

- [x] **Move the core into `backend/`** — done Aug 23, 2026, at your call: it is all one
      Python process, so one package. `src/continuity/` became `backend/core/`, imports became
      `backend.core.*`, `src/` is gone, and `pyproject.toml` now discovers `backend*` from the
      repo root. The concern going in was that this dissolves the pure/perimeter boundary
      `CLAUDE.md` §3 requires, since that boundary *was* the `src/` ‖ `backend/` split. It did
      not: the property is about what modules import, not where they sit, so it moved into the
      import path — `backend.core.*` is the deterministic half, everything else under
      `backend/` is perimeter — which is more visible than a directory split because it shows
      at every call site rather than only in the tree. The core's tests still run with nothing
      installed, which is what would have broken if the boundary had actually eroded.
      **One new risk, which did not exist before and is the real cost:** `backend/__init__.py`
      now executes before every `backend.core.*` import, so a single vendor import there would
      make the dependency-free half require the SDKs *and* defeat `app.py`'s cold-start
      deferral at once. It is asserted import-free by a test rather than left as a convention,
      and written up in `AGENTS.md` §4 beside the two other direction rules. Also re-verified:
      the wheel still builds from exactly what the `Dockerfile` copies before installing, now
      `pyproject.toml` + `backend/`

- [x] **Build the MediaWiki read tool** — done Aug 23, 2026, the first of the four tool
      signatures. Two decisions carried it. **Reading is two calls, not one:**
      `read_page_outline` is structural and cheap (sections, sizes, revision, no text) and
      `read_section` is only ever asked for a heading the caller already chose — a single
      "read the page" tool would have put 50KB of wikitext in front of the model to answer a
      question about one paragraph, and the corpus holds a 202KB page. And **the profile is
      bound, never passed:** a `WikiProfile` is not JSON so a model could not send one anyway,
      but the real reason is that a tool taking a wiki as an argument hands back the choice
      §5's plug-and-play design exists to remove. Both are now rules in `AGENTS.md` §7.
      The failure contract is the third: a missing page or a missing heading comes back as a
      *value* (with the headings that do exist, so the model recovers in one turn), while a
      timeout or a refused socket propagates, because ADK drives retry off exceptions and
      catching those would disable it permanently.
      Two things fell out that were not planned. `backend/core/wiki/snapshots.py` gives the
      hash-checked seed corpus the same `PageSource` interface the live client has, which is
      `CLAUDE.md` §3's required fallback and also means **the graph can be built and tested
      before a local MediaWiki exists** — the next item stops being a blocker. And using
      `subtree()` for real surfaced a bug in it: the lead is level 0, a sentinel rather than a
      depth, so `subtree(sections, 0)` counted every section as nested under it and returned
      50,326 of a 50,454-byte page to a caller who asked for the infobox. Fixed in the core
      with a guard and two tests rather than worked around in the one caller that found it.
      Tests pass, the core's still on an interpreter with nothing installed; mypy
      strict, ruff and `node FE/check.js` all clean

- [x] **Build the Parallel search tool** — done Aug 23, 2026, the second of the four. The
      signature encodes what §12 measured rather than leaving it to a caller. **`search_queries`
      is a list because Parallel bills per *call*, not per query** — a single-query tool would
      have made fan-out cost four searches for the same evidence, so batching is now a property
      of the type rather than a discipline. **`include_domains` is never a parameter**: it comes
      off the profile every call, which is what makes the tier table the retrieval policy and
      not just a scoring function. And **tier is attached on arrival by table lookup** — the
      same `marvel.com` URL is tier 1 to the MCU wiki and tier 4 to Wikipedia, which is correct
      and is now a test.
      Reading `parallel-web` 1.3.0 rather than trusting §12's notes turned up three things worth
      keeping, all in `AGENTS.md` §6. **Setting a timeout bounds nothing**, which is the one
      that mattered: `timeout` is a per-*attempt* deadline and the SDK retries timeouts twice by
      default, so the ceiling is `(retries + 1) x timeout + backoff` — 1801.5s untouched, longer
      than the 900s Cloud Run request it runs inside, and still 91.5s after setting only
      `timeout=30`. Both are now set, and the ceiling is computed by `worst_case_seconds()` and
      asserted rather than described: 15s x 2 attempts = 30.5s, against a measured search
      latency of 1.4-5.8s. Retries are not free either — a search that timed out may still have
      been served, so each one risks a second `sku_search`, which is why one retry and not two.
      The other two: `parallel.types.SourcePolicy` is the response model and *not* the param
      type `search()` accepts, which fails typecheck rather than at runtime; and `omit` is not
      `None` — the first drops a field, the second sends an explicit null, which on `session_id`
      is the difference between the server generating one and being handed nothing.
      **The wire body is asserted without spending a `sku_search`.** The call was written from
      the SDK source, not from running it, so five tests drive it through an `httpx` mock
      transport and check the real serialised request — chiefly that `include_domains` lands
      inside `advanced_settings.source_policy`, because if it silently did not, retrieval would
      degrade to the unfiltered results §12 measured as actively wrong rather than merely worse.
      `RecordedSearch` is the `CLAUDE.md` §3 fallback: a live run records a cassette and replays
      it byte-for-byte, so every stage downstream of Research is testable offline and the demo
      survives an expired key. Cassettes hold third-party web excerpts, so `fixtures/` is
      gitignored — a public MIT repo is not the place for them (`CLAUDE.md` §6), and a fresh
      clone runs live or records its own. **No live call has been made yet**, so the mock
      transport is the only evidence the request is accepted; the first real one both confirms
      that and seeds the cassette.
      Tests pass, the core's with nothing installed; mypy strict, ruff and
      `node FE/check.js` clean. One bug caught by its own test: `tier_counts` was keyed by int,
      which JSON silently stringifies — the model would have been shown a dict the node never
      built

- [x] **First live search — and it settled the "split the search" question against splitting**
      — Aug 23, 2026, two calls on demo claim #1. The proposal was to partition retrieval into
      several smaller calls, each over a tightly related slice of the web, and assemble
      afterwards. The measurement says no: one default call returned **6 distinct publishers
      across tiers 1, 2 and 3**, against a confidence model that saturates at 3, and doubling
      `max_results` to 20 returned **the same 6 domains** — deeper coverage of variety and
      deadline, not a wider set. Partitioning would have multiplied `sku_search` by the number
      of partitions to buy nothing measurable. Full numbers in §12.
      Three things the run exposed that no amount of reading the SDK would have. **Billing is
      two meters, not one:** the 20-result call billed `sku_search: 1` *and*
      `sku_extract_excerpts: 10`, so cost scales with results as well as with calls — and the
      tool was throwing that away, which is now fixed (`SearchOutcome` carries usage and
      `search()` reports it, because a metered perimeter that hides its own bill is a defect).
      **`max_results` above 20 is silently reduced** to 20 with a warning and a 200, so a
      too-thin result set looks like a thin web. And **the top tier was the least complete
      source**: `marvel.com` and `disney.com` list Channing Tatum in the *Doomsday* cast
      without naming Gambit, so the claim itself is carried by tier-2 trade prose and a tier-3
      table. Tier orders authority, not completeness — a Draft node citing only its best source
      would cite one that does not contain the fact. That is now a §7 rule, and it is a genuine
      gap in §6's tier design rather than a detail.
      Retrieval quality itself is good: 6 of 10 results carry the target fact, and the tier-3
      hit is `AGENTS.md` §7's "never trust the structure of an excerpt" in the flesh — its role
      mapping is a scraped table while the tier-2 headline states it in prose. The call is
      recorded to `fixtures/searches.json` (gitignored) so the tool is now also proven live and
      the cassette has its first entry

- [x] **Citations are filtered by wording, not chosen by tier** — done Aug 23, 2026, in
      `backend/core/ledger/citations.py`, closing the gap the live search exposed. The tier
      design has always answered "which source is most authoritative"; a footnote answers a
      different question — "which source actually says this" — and on the demo's opening claim
      those give different answers. `marvel.com` and `disney.com` are tier 1 and never write
      the word Gambit, so "cite your best source" would have footnoted the video's first edit
      to a page that does not contain it, with nothing to catch it: the claim is true, six
      publishers agree, and confidence is 1.0.
      The rule is two steps. `supporting()` keeps only sources whose excerpt contains every
      required term, then ranks what survives by tier — which on the real batch moves the
      footnote from `marvel.com` to `deadline.com` and, if the Draft stage passes the full
      wording it wrote, narrows five citable sources to two — which it does not yet: Draft
      picks its footnote with the claim's own terms before the model writes anything, so the
      second narrowing is available and unclaimed. `best_citation()` returns `None`
      when nothing states the claim rather than falling back to the best source, and
      `uncited()` is a state the reviewer sees; that is the same instinct as declining to
      resolve a conflict, applied to citation. Deliberately string comparison and not a model
      call — a citation a reviewer cannot check by eye is not worth having.
      **Filtering costs no evidence, and that is asserted rather than intended.**
      `recompute_confidence` is untouched and still counts every source, so `marvel.com`
      corroborates the claim without being its footnote; the test drops it and watches
      confidence fall to prove the two paths are actually separate. The default required term
      is `entity_ref.base` rather than the full title, because a variant subpage's suffix is a
      wiki naming convention no publisher writes — requiring it would reject every source in
      existence, and telling a variant from its prime is the classify stage's job.
      Tests pass bare; `demo-state.json` still regenerates
      byte-identically, which is the evidence this added a path rather than changing one

- [x] **The local wiki is up and seeded** — Aug 23, 2026. MediaWiki **1.43.9** on PHP 8.5 and
      MariaDB 12.3, installed natively rather than in a container, holding all 12 seed pages
      verified byte-for-byte against `snapshots/manifest.json`. Two choices, both yours and both
      right. **Native first:** containers are packaging, and packaging a stack new to the project
      before it runs is how a day disappears — the Docker move is its own item below. **MariaDB
      over MySQL:** it is what real wikis run, Wikimedia included, so it is what the agent meets
      in the wild; and since we never open a connection to it, fidelity beats local/deployed
      engine parity.
      1.43 turned out to be the LTS *and* the exact version the MCU Wiki runs, so the instance
      answers `generator: MediaWiki 1.43.9` — the same string the manifest recorded off Fandom.
      It also self-reports `CC BY-SA 3.0 Unported` and mainspace subpages enabled, which are the
      profile's two substantive claims about it; `seed_wiki.py --check` compares the two and
      refuses to write when they disagree, because a subpage-grammar mismatch would quietly turn
      `Human Torch/Void-Analyzing Fantastic Four` into a page rather than a variant and attach
      every claim about it to the wrong subject.
      **The agnosticism is now demonstrated rather than designed.** The instance gets a profile
      like any other wiki — `local_wiki()` in `backend/core/profile/known.py` — and the same
      `WikiRead` reads it and the frozen corpus and returns identical section text, identical
      section indices and identical entity parsing. One profile swap, no branch, no flag, no
      code that knows which wiki it is talking to. Two things about that factory are invariants
      rather than style. It is **the only writable profile**, and a test asserts every shipped
      profile is not — which is what lets `MediaWikiWriter.for_profile` refuse Fandom outright,
      turning `AGENTS.md` §2's "never write to a real wiki" into a raised exception rather than
      a line in a document. And it takes its **endpoint as a required argument with no
      default**, because the URL is a deployment identifier and the repo is public, so the value
      lives in `.env` alone. It inherits Fandom's title grammar and section vocabulary
      deliberately: it holds those pages, so anything else would make the profile describe a
      wiki that does not exist.
      Everything is reproducible: `scripts/setup_wiki.sh` does the whole install idempotently and
      writes every generated credential to `.env` and none to the terminal, `wiki/` is gitignored
      as the build artifact it is, and the settings that are actually ours live in version
      control at `wiki-config/LocalSettings.overrides.php`. Five gotchas went to `AGENTS.md` §6,
      of which two cost real time: Homebrew's MariaDB refuses `-u root` whatever the password
      because root authenticates over `unix_socket`, and main-account API login is deprecated
      and refused so a BotPassword is the only way in — scriptable, as it turns out, via
      `createBotPassword.php`, which removes the manual `Special:BotPasswords` step the plan had
      assumed

- [x] **Build the MediaWiki section-write tool** — done Aug 23, 2026, the third of the four, and
      the first thing in this project that changes a page. **It addresses sections by heading and
      offers no way to pass an index.** MediaWiki addresses them by position, so `section=3` means
      "the fourth heading as of right now" and anything inserted above silently renumbers the
      rest — while a drafted edit may be minutes old when a reviewer approves it. So the tool
      takes a heading, re-reads the page, resolves the index, and writes, every time; the same
      read supplies `basetimestamp`, which shrinks the window a concurrent edit can hide in to
      the length of one function. The absence of an index parameter is the design: if one
      existed, a stale one would eventually be passed.
      **Two outcomes are values rather than exceptions**, for the same reason a missing page is
      in the read tool. A `conflict` is an instruction — re-read, re-draft, retry — and raising
      it would have ADK retry identical stale text against a page that has already moved. A
      vanished heading comes back with the headings that do exist, because `AGENTS.md` §2 forbids
      creating a section and a test asserts nothing reached the writer in that case.
      **The conflict path finally has a real test**, which is what the local wiki was for. Run
      against the live instance: a section write landed (rev 3 -> 14, heading `Trivia` resolving
      to index 15, which is not a number anyone would have guessed); a write to a non-existent
      `Reception` created nothing; and a deliberately stale `basetimestamp` came back from real
      MediaWiki as code `editconflict`, matching what the tool matches on. Re-running the seeder
      restored the page and reported "no change" for the other 11, so idempotence is measured
      too. Matching on the code rather than the message matters — `editconflict`, `protectedpage`
      and `badtoken` all arrive as failures and need different responses, so `WikiError` now
      carries MediaWiki's own code

- [x] **Drop every tracked-claim count** — Aug 29, 2026. `seed-plan.md` committed to 50 claims
      across 8 pages, §9 beat 1 here said "~14 out of ~300" and §8 said "~50 tracked": three
      numbers that disagreed with each other, against a repo holding six — hand-written fixture
      literals in `build_demo_state.py`, driven through the real transitions and dumped to JSON.
      Nothing in Phase 1 authored the rest, and nothing was going to: the ledger tool is storage
      by design, and the graph consumes claims rather than writing new ones. The fix is to stop
      treating a count as a commitment. Claims are an *output* of a full pipeline run, and a
      claim is tracked only once a run has written it back — so the numbers are gone from
      `seed-plan.md` §1/§2/§3 and §8/§9 here, the page list keeps its measured drift and loses
      its Claims column, `build_demo_state.py` no longer emits `planned_claims`, and `AGENTS.md`
      §2 forbids restating a total. The volatility waves stay as what they always were — a
      description of the kinds of claim the seed carries — and the six in `seed-plan.md` §4 stay
      as the beats the video needs. Nothing about the seeded wiki changes: 8 pages, 12 files,
      freeze at 2024-08-09

- [x] **Build the ledger local-first, port it to Firestore later** — Aug 29, 2026. Firestore was
      always the target (`AGENTS.md` §3) but nothing could be built against it: the emulator needs
      a JRE and a `gcloud` component neither installed, and a cloud project is Phase 2 work. The
      alternative to waiting is to make the *shape* the portable thing rather than the storage.
      So `documents.py` emits only value types Firestore's document model accepts — `str`, `int`,
      `float`, `bool`, `None`, `datetime`, `list`, `dict` — and the adapter will hand a document
      to `.set()` with nothing in between; a test asserts that property directly rather than
      trusting it. JSON's lack of a timestamp type is the single difference, and the local store
      is what pays for it. Two behaviours are guarded because they diverge *silently*: a
      Firestore inequality filter does not match null-valued fields, so `put` refuses a claim
      whose `next_check_at` is `None` — otherwise an unseeded claim is due in memory and
      invisible deployed, passing every local test. And `due()` orders by
      `(next_check_at, claim_id)` because Firestore's implicit `order_by` tiebreak is the
      document id, so a limited query pages the same way in both. The file store *inherits* the
      in-memory one rather than reimplementing it, so `due` and `all` cannot drift from the
      semantics the graph is tested against. What this buys immediately: the 8-stage graph can
      be written and run end to end with no database, no emulator, no cloud project and no
      network — the same argument that put `SnapshotPageSource` behind the wiki reads. Rejected:
      SQLite, which contradicts the schema-flexibility rule above for no gain a JSON document
      store does not already give at this scale

- [x] **Drop every test count too** — Aug 29, 2026. Nine decision-log entries carried a running
      tally (`31 tests`, `96 tests pass (was 82)`, `198 tests, 173 of them bare`) and `AGENTS.md`
      and `README.md` each restated a current one. Two of the `AGENTS.md` figures were already
      stale by two commits, in a file whose whole job is to be current. The tally is the same
      mistake as the claim count above in a different costume: a number written into prose is a
      number no command maintains, correct for one commit and quietly wrong after. It is also
      unverifiable in retrospect — nobody can re-measure what the suite held on Aug 23, so the
      figure in a dated entry is an assertion the repo cannot back. What the entries were
      actually claiming is that the gate passed and the core still ran bare, and that survives
      the numbers being gone. `AGENTS.md` §5 now forbids restating a count anywhere; the command
      reports it.

- [x] **The ledger tool reports outcomes; it does not write the schedule** — Aug 29, 2026.
      The last of the four tool signatures, and the one where the design question was real.
      Written as a passthrough over `ClaimStore.put` it would have been ten lines — and it would
      have handed the model `next_check_at`, `check_interval` and `confidence`, which are the
      three numbers the deterministic core exists to compute. A model could then schedule a
      claim for never or assert 0.95 behind one blog post, and the decay ladder on camera would
      be model output wearing the ladder's clothes. So the write side takes an *outcome* —
      `unchanged`, `changed`, `unresolved`, `exhausted` — and calls the matching `Claim`
      transition; `record_research` takes urls and excerpts and looks the tier up against the
      profile's own table rather than accepting one; and `track_claim` does not let the model
      name the claim, because the audit stage re-reads the same eight pages every cycle and a
      model-chosen id would be phrased differently each time — the ledger would double in size
      per run rather than recognise what it already tracks. (It first *derived* the id from page
      + anchor, which was wrong for a different reason; see the Aug 29 entry below.) The rule is
      one line: **the model reports what it found, the core decides what that means.** Pinned by a test that asserts no write method has a
      schedule-shaped parameter at all.

      **Six operations, not the two this was scoped as.** Due claims and write-back were the
      two named when the ledger was still a design; a claims collection that starts empty
      (`seed-plan.md` §3) also has to be *filled*, so the audit stage needs `track_claim`, evidence has to arrive
      without the model setting tiers so research needs `record_research`, the fan-out stage has
      to record `ripple_targets`, and `read_claim` is how those targets are followed. Each one is
      storage plus a core call; none of them decides anything.

      **Two gaps this exposed, both left open deliberately.** `ClaimStatus` has `DRAFTED` and
      `APPLIED` but `schema.py` has no transition that produces either, so the draft and publish
      stages have nothing to call — that is a core change and belongs to whoever writes those
      nodes, not to the tool. And because the claim id hashes the anchor, an edit that rewrites
      the anchor yields a new id on the next audit, orphaning the old record; closing it needs
      the publish-stage transition that does not exist yet, which is the same gap.

      *Both were closed the same day, and not the way this entry expected.* `DRAFTED` and
      `APPLIED` were deleted rather than given transitions, and the id stopped being derived at
      all — the two entries below.

- [x] **Two claim statuses, not six** — Aug 29, 2026. `ClaimStatus` was `verified`, `stale`,
      `drafted`, `applied`, `unresolved`, `exhausted`, and the ledger tool's gaps exposed why
      that was wrong: no transition produced `drafted` or `applied`, `build_demo_state.py` was
      already reaching past the state machine with `replace(claim, status=DRAFTED)` to fake one,
      and `auto_appliable` gated on a value nothing could reach. The six were answering three
      different questions on one field — what the agent concluded, where an edit sits in the
      publish pipeline, and how old the data is. Only the first belongs on the claim. So:
      **`verified` and `unresolved`, answering "does a human need to look at this".** A drafted
      edit awaiting the gate is `unresolved` for the same reason a conflict is — both are rows
      in the review queue — and `contradicts[]` distinguishes them, derived rather than stored.
      Where an edit sits belongs to the queue. Staleness is `now >= next_check_at`, a comparison
      rather than a state, and one run resolves it back to one of the two.

      **Three consequences fell out, and two of them deleted code.** `exhausted` collapsed into
      `unchanged`: if three rounds of research found nothing, there is no new data, which is no
      change — and the record still distinguishes "confirmed" from "found nothing", because the
      confirmed one gained sources. A rejected draft is also `unchanged`, since the reviewer
      keeping the existing text means the page stands; there is no separate `rejected`
      transition to drift from it, and the doubling is right because a human just affirmed the
      claim. The tool's outcomes went from four to three.

      **The cost, accepted knowingly:** treating "confirmed" and "nothing found" alike is
      exactly the rot the parked *confirmed vs unchallenged* item below describes — a claim
      nobody can source has its interval doubled like one that was corroborated, so it is asked
      about ever less often. That item is now the mitigation for a decision rather than a
      refinement of one. `DOCUMENT_VERSION` went to 2; a v1 ledger is refused rather than
      migrated, because `drafted` and `applied` have no honest mapping onto the new pair.

- [x] **Claim ids are a counter, not a hash of the claim** — Aug 29, 2026. The ledger tool
      first derived the id from page + anchor, so that re-auditing a page would recognise a
      claim it already tracked rather than proposing a duplicate. That solved the duplicate and
      created a worse one: an applied edit rewrites the anchor by definition, so the record
      would be re-keyed on every successful edit — and `ripple_targets` holds claim ids as
      strings on *other* claims, so each re-key would silently dangle every reference to it. A
      cascade the fan-out stage recorded would quietly stop working, with no error anywhere.

      **So identity is allocated and never recomputed.** `ClaimStore.next_claim_id` hands out
      `claim-0001`, `claim-0002`, … — max-plus-one rather than count-plus-one, so a removed
      claim never frees its number for a different claim to inherit. Recognising an existing
      claim moved to a lookup: `for_page(page)` plus an exact anchor match. That is one equality
      filter, which Firestore serves from its automatic single-field index, so it adds no
      composite index and nothing the emulator would fail to catch. The anchor is *where* a
      claim sits; the id is *what it is*; conflating them was the bug.

      The alternative considered and rejected was retiring the old record and inserting a fresh
      one on every applied edit. It loses the sources that justified the edit, so a claim would
      show 0.0 confidence in the ledger view immediately after the agent applied a well-cited
      change to it — on camera, right after the strongest beat — and it resets the interval to
      the wave seed, which is backwards for a claim that just proved it moves.

      **What this does not fix:** a *third-party* edit. If a human rewrites the anchor on the
      wiki, our publish stage never runs, the lookup misses and the next audit tracks a
      duplicate. Closing that means the audit stage comparing proposed claims against the claims
      already on that page and judging which are the same — a matching decision for the model,
      not an id scheme, and it belongs to whoever writes the audit node.

- [x] **Assume a single editor while the agent runs, and build the review queue as a git diff**
      — Aug 29, 2026. Two decisions, and the first is what makes the second simple.

      **The assumption:** nobody else edits a page between the read that drafts an edit and the
      write that publishes it. This is a hackathon assumption, taken knowingly, and it is now an
      invariant in `AGENTS.md` §2 so it is not silently relied on. It removes an entire class of
      work: git's three-way merge machinery exists because two branches edit a common ancestor
      concurrently, and with one editor the page at publish time *is* the base, so there is no
      third side, no conflict markers, and no "keep ours / keep theirs" row in the queue. It
      also means "publish all approved edits" needs no atomicity story — MediaWiki has no
      transaction across pages, and under this assumption it does not need one. The guard
      survives the assumption: `WikiWrite` still sends `basetimestamp` and still returns
      `conflict` as a value, so a real concurrent edit fails loudly instead of overwriting
      someone. What was dropped is the *flow*, not the safety. It belongs in the submission
      description, because a judge editing the wiki mid-run is exactly how it gets found.

      **The diff:** `core/wiki/diff.py`, stdlib `difflib`, pure. Line-level first, then
      word-level inside a changed pair — what git and MediaWiki's own diff view both do. The
      rows are computed in the core and shipped in the payload rather than derived in the
      browser, for the same reason every other number on screen is: what a reviewer sees and
      what a test asserts cannot be allowed to disagree. `FE/check.js` now verifies the shipped
      rows rebuild `before` and `after` byte for byte — a diff that cannot round-trip its own
      input is not evidence anyone can approve on.

      **Two bugs the tests caught while writing it,** both the kind that would have shipped
      looking fine: whitespace attached to the word before it made the last word of a line read
      as different from the same word mid-line, so untouched words came back highlighted; and
      the similarity floor that separates "edited line" from "different line" was measured over
      a token stream containing whitespace, so two unrelated sentences scored 0.33 on their
      shared spaces alone and cleared a 0.3 floor. A floor that never fires is not a floor.

- [x] **Step 1 of a run: the deterministic baseline pass** — Aug 29, 2026. The ledger now has
      two collections. `sections` holds what each monitored page says, read verbatim and split
      by `split_sections`; `claims` holds what the agent tracks. Ingest is
      `backend/agent/ingest.py`, driven by `scripts/ingest_baseline.py`, and it runs against
      `snapshots/` offline or against our own MediaWiki with `--live` — the same call either
      way, because both satisfy `PageSource`. Measured on the committed corpus: **12 pages, 284
      sections**, and a second run reports every page `unchanged`. Pointed at the `current`
      corpus instead — two years of real drift — it reports the drift per page rather than
      being told about it.

      **Why the baseline is not claims.** Extracting atomic claims is a judgement about what a
      page asserts, so it needs the model, and there is still no Gemini adapter in the repo —
      the perimeter was proven by ad-hoc benchmark runs and nothing was committed. *(Both halves
      of that were overtaken later the same day: `agent/model.py` landed, and the live read now
      requires a key. Offline against `snapshots/` it still needs neither.)* Recording
      what a page *says* needs nothing. Splitting them means step 1 works today, and claims get
      proposed against a baseline that
      already exists instead of being the only thing the ledger holds. It also settles the Audit
      ambiguity noted below: baseline-fill and due-claim selection are two passes, not one
      stage doing double duty.

      **Two rules the tests pin.** A page's sections are replaced as a set, never merged —
      indices are only meaningful relative to each other, so inserting a heading at the top
      renumbers everything below and a merge would file one section's text under another's
      index, silently. And a missing page is a result while a transport failure propagates:
      the same narrow-catching rule as the read tool, because swallowing a timeout turns an
      outage into an empty baseline.

      `WikiProfile.pages` closes the "no page list" gap — the agent is not a crawler, and which
      pages we maintain is config, sitting beside `section_vocabulary` where the rest of the
      per-wiki decisions live.

- [x] **The wiki is an external service, including our own** — Aug 29, 2026. The agent had an
      unauthenticated path to the instance it writes to, purely because we happen to own it.
      That is the wrong shape: every other perimeter in this system is a configured endpoint
      plus a credential that fails closed, and the one we control was the exception. Now
      `local_wiki()` carries `requires_key=True`, both adapters refuse to construct without
      `MEDIAWIKI_API_KEY`, `setup_wiki.sh` generates it, and it rides an `X-API-Key` header —
      not a query parameter, because a URL is logged by every proxy it passes.

      **What is real and what is not.** MediaWiki ignores the header; the gate is ours. What
      the change actually buys is that the endpoint is configured, the credential is required,
      the failure happens at construction rather than as an unauthorised request mid-run, and
      the secret flows through `.env` and Secret Manager like every other. Pointing the agent
      at a wiki that genuinely gates reads becomes a value in `.env` rather than a code change.
      The upgrade to real enforcement is MediaWiki's own — `$wgGroupPermissions['*']['read'] =
      false` plus the bot login the writer already performs — and it is recorded in
      `AGENTS.md` §2 so nobody mistakes the dummy for authentication.

      `requires_key` describes the *endpoint*, not a preference, so Fandom's genuinely open API
      stays keyless and is tested not to start sending a credential it never asked for. The
      `snapshots/` path needs no key at all: it is a committed corpus, not a service, which is
      why the whole baseline can still be built offline.

- [x] **A failed search is discarded, not recorded** — Aug 29, 2026. Found by running the
      research path end to end after the status collapse: a cassette miss returned an errored
      payload, `sources_in` converted it to zero sources exactly as documented, and downstream
      that is indistinguishable from "retrieval found nothing" — which now routes to
      `unchanged` and *doubles* the recheck interval. So an expired Parallel key would make the
      agent check every affected claim progressively less often, silently, while looking
      healthy. The old contract ("a failed search is a claim with no new evidence, not a crash")
      was correct when `exhausted` was its own status and wrong the moment that collapsed;
      `sources_in` now raises instead. Nothing about a failed search reaches the ledger: no
      round spent, schedule untouched, claim comes due again. A search that ran and found
      nothing still spends a round — that is a real answer about the world, and the two cases
      stay distinguishable in the payload.

- [x] **Classify runs, on real Gemini** — Aug 29, 2026. There was no model adapter in the repo
      at all: the perimeter had been proven by ad-hoc benchmark runs in August and nothing was
      committed, so every stage needing a judgement was a design. Two modules close that.

      **`agent/model.py` — the Gemini perimeter**, shaped like the search one: a request is a
      system instruction, a prompt and a JSON schema; `ModelSource` is the protocol; `GeminiModel`
      is live over `google-genai` on ADC; `RecordedModel` replays a cassette. Structured output
      rather than prose parsed afterwards, `temperature=0` because the ladder is filmed, AFC
      disabled because the stages call tools themselves and a model invoking one mid-judgement
      would be a second unlogged control path. The cassette key covers instruction + prompt +
      schema, so an edited prompt *misses* rather than replaying the old prompt's answer — the
      failure a deterministic fallback is most likely to hide, and the one that looks like
      everything working.

      **`agent/classify.py` — the stage and its prompt.** The four rules from `AGENTS.md` §7 are
      now text in `SYSTEM` rather than a specification: precedence order stated out loud, "an
      absence on the page is not a contradiction" in capitals, the subject including its variant,
      and filter-then-classify as two ordered steps. The output surface is deliberately tiny —
      one bucket, plus a note and two urls when conflicting — and every number that follows is
      computed by `decay.py` from that one word, so a bad judgement produces a wrong bucket and
      never a corrupted schedule. A `Verdict` has no field that could carry an interval, and a
      test asserts it.

      **Measured, not asserted.** `scripts/classify_once.py` runs the built half of the pipeline
      end to end — baseline → claim → replayed search → classify → ledger write. Against real
      Gemini on the lead beat it returns `new`: *"Channing Tatum will reprise his role as Gambit
      in Avengers: Doomsday, which is not currently mentioned in the section."* That is rule 2
      working — the page does not contradict the fact, it lacks it — and it is the bucket the
      demo depends on. Replaying the cassette gives the identical verdict with no key and no
      network.

      **The gap this leaves open, stated plainly.** The benchmark behind those four rules is
      still not in the repo, so the rules are pinned by asserting their presence in `SYSTEM`
      rather than by re-measuring their effect — a prompt edit can be caught for *dropping* a
      rule but not for weakening one. Rebuilding it is now the last engineering item in Phase 1
      below, with the case set and the two run modes written out.

- [x] **Fan-out moves after the publish gate** — Aug 29, 2026. It sat between Classify and Draft
      since Aug 22, so a *new*-bucket classification widened the run and one Draft pass covered a
      claim and everything it implicated. That ordering assumes the agent's proposal is what
      ripples. It is not: what ripples is what the wiki ends up saying, and the gate is allowed to
      change that — reject (dependents researched and drafted for a fact that never landed),
      hand-edit (dependents that overstate a premise the reviewer softened, caught by nothing,
      because Verify only reads the page it is editing), or a Verify bounce that redrafts the
      trunk after the fan-out already fired. Reading the published revision removes all three by
      construction. It also un-inverts the queue, where approving a dependent used to mean
      approving a premise sitting unapproved two cards above.

      **Three structural consequences, all recorded.** The graph gains a third backward edge,
      `Fan-out → Research`, so §6's diagram, the "two backward edges" count everywhere it
      appeared, and `AGENTS.md` §7's construction rule all change. The run pauses at Publish twice
      — the same `request_input` machinery, used once more. And the one-hop rule stops being a
      cost control and becomes the termination argument: `Fan-out → Research` is a real cycle, and
      a fanned-in claim not fanning out again is the only thing that breaks it, so the cap belongs
      in the node rather than in a config.

      **Nothing built has to change**, which is why this is cheap now and would not have been in a
      week: the graph is the one unbuilt piece, `link_ripple_targets` never cared when it was
      called, and `decay.next_interval(..., changed=True)` still supplies the pull-forward. What
      does change is the video: beat 2 (§9) now shows the approval as the visible cause of the
      cascade, which is a better shot than the one it replaces.

      *Two details of this entry were overtaken on Aug 30, 2026, and are left as written because
      they record the reasoning at the time.* The third backward edge it added, `Verify → Draft`,
      was removed when Verify stopped being a model stage, so the graph is back to two; and the
      "Verify bounce" it lists as the third way a proposal and a publication diverge can no
      longer happen. Its "the run pauses at Publish twice" is now "pauses at Verify twice" —
      Publish became the write alone, fired by a button. The entry's conclusion is unaffected:
      the other two ways, rejection and hand-edit, are what the gate move was for, and hand-edit
      is now the gate's whole purpose.

- [x] **Build the draft stage, and let the diff check it** — Aug 29, 2026. `agent/draft.py`,
      `diff.shape()`, and the `Draft` record that had no home. The stage rewrites the anchor
      rather than the section, takes the Classify bucket as an input rather than re-asking the
      question, and refuses `still_true` before the model is called.

      **The question that shaped it was whether Draft could decide append-versus-conflict by
      diffing.** Not as an input — retrieval returns web prose, not a candidate revision, so
      there is nothing to diff until something has written one. But as a *check* on the draft,
      yes, and better than a model could: once `after` exists, whether it added to the page or
      displaced part of it is arithmetic over two strings, and it can be held against the
      bucket. `new` means incomplete rather than wrong, so a `new` draft that removed text is
      `overreached` and the queue flags it. That failure had no other catcher — Verify looks
      for a contradiction the edit *introduced*, not for wording it took away. *(Verify stopped
      being a model stage on Aug 30, 2026, so that catcher is now the Diff stage alone.)*

      **Containment, because our own fixtures rule out the alternatives.** `GAM-APP-01` appends
      with no whitespace and breaks every token-level test; `DW-VOID-01` inserts inside the
      anchor and defeats character-subsequence. Both are pinned in `tests/test_diff.py`. The
      test errs toward `modify` — reindenting reads as a rewrite — because a false alarm costs
      a read and a miss costs a silent overwrite.

      **What it deliberately does not do:** it never revisits the bucket. The diff sees the
      draft against the page and nothing else, so sources disagreeing while the page is silent
      is invisible to it — half of what `conflicting` means, and Classify's measured precedence
      order is what finds it. Two other gaps stay open: the citation is chosen from the claim's
      terms before the model writes, so `citations.py`'s second narrowing is unclaimed; and
      nothing persists a `Draft` yet, so a drafted edit lives for one process. Both land with
      the graph.

- [x] **Add the diff stage — an agent, not the arithmetic** — Aug 29, 2026.
      `agent/semantic_diff.py`. The graph goes to eight stages: `… → Draft → Diff → Verify → …`,
      no new backward edge.

      **`diff.shape()` answers the wrong question, and correcting that was the point.** It
      reports whether the *characters* survived. A draft that appends `, however Marvel later
      confirmed the character was cut` keeps every one of them — containment holds, the shape
      is a clean `append`, the diff renders green — and the assertion the page made is gone.
      Nothing was deleted and the meaning was still overturned, so there is nothing for a
      string comparison to look at. It fails the other way too: threading `(2024)` into an
      infobox value scores as a rewrite while dropping no idea at all. Text and meaning come
      apart in both directions, so the edit has to be *read*.

      The stage reports per assertion — `kept`, `added`, `dropped`, `reversed` — and any drop
      or reversal is `DESTRUCTIVE`. `Review.hidden_by_text` names the case that justifies the
      whole stage: textually an append, semantically destructive, which is the one a reviewer
      trusting the green diff approves.

      **Specialised, and separated twice.** Not a method on Draft, because a stage that writes
      an edit and then rules on whether it was conservative is reporting on itself. And not the
      orchestrator's own reasoning — the graph routes and holds no opinion; every judgement is a
      node with one prompt, one schema and one question (`AGENTS.md` §7). It is also not told
      *why* the edit was made: no sources, no objective, no bucket, because a reader handed the
      motive explains the edit instead of examining it. The bucket is applied afterwards, in the
      core, when the verdict is held against it.

      **The arithmetic stays as the floor.** `shape()` is not replaced — it is the deterministic
      fallback (`CLAUDE.md` §3), so a run with a dead credential still gates edits, coarsely and
      flagged `text_only`. Displaced text that nothing read comes back destructive rather than
      clean.

      **Not measured.** Classify's four rules each came from a benchmark; these are reasoned.
      The harness rebuild in Phase 1 now has a second stage to cover, and the appended-negation
      case is the one to score first.

- [x] **Verify becomes the human gate, not a model stage** — decided Aug 30, 2026, and it is a
      hackathon simplification taken knowingly. Verify was specified as a Gemini node that
      re-read the drafted section against the rest of the page, looking for a contradiction the
      edit introduced *elsewhere*, and bounced the draft back to Draft when it found one. It is
      now four things, none of which is a model call: no agent checks whether a statement
      contradicts another; **every section with a diff is a card the reviewer accepts or
      rejects**; it is where the reviewer **edits the draft text in place**, which is the
      outcome the old design listed and had nowhere to put; and it ends with a button that hits
      the publish API. Diff scaffolds the change and renders it — Verify is where a person
      changes it.

      **Publish and the gate stop being one stage.** The table in §6 used to give Publish all
      three jobs — pause, decide, write. Now Verify holds the pause and the decision and
      Publish is the write, fired by `POST /api/queue/{edit_id}`. That is also where
      `google.adk.tools.request_input` goes (`AGENTS.md` §6), and it is a better fit than the
      old placement: the run has to survive a human editing text, not just clicking yes.

      **Three structural consequences.** The `Verify → Draft` backward edge is gone, so the
      graph is **eight stages and two backward edges** — `Classify → Research` and
      `Fan-out → Research` — and every count in these documents changes with it. Draft therefore
      has *no* automatic retry path, which is a simplification and not a loss: the reviewer
      fixes the draft rather than waiting for a second one, and the one-hop fan-out rule is now
      the sole termination argument. And §6's "what keeps this agentic" list drops from four
      items to three.

      **The cost, stated plainly: page-level coherence is now nobody's job.** An edit that is
      clean at its anchor and contradicts a sentence three sections away ships unless the
      reviewer notices. Nothing else catches it — Classify reads the world against the page,
      Diff reads `after` against `before` of the same anchor, and neither looks at the rest of
      the page. This is accepted rather than mitigated. Three things make it survivable for a
      demo: the reviewer is reading the drafted section anyway, edits are anchor-sized so the
      blast radius is one sentence, and §4's requirement 5 was never carried by Verify — it
      belongs to the retrieval-sufficiency item still open below. The strongest agentic evidence,
      fan-out deciding the working set from a human answer mid-run, is untouched.

      **What it buys** is that Verify becomes buildable this week and needs no model, no prompt
      and no benchmark: it is the FE queue rework already on the list, plus one route that
      already exists as a guarded shell. It converts the largest unbuilt stage into work whose
      shape is known.

      **One candidate per change, and the reviewer decides per diff — settled the same day.**
      The open question was whether Draft should emit several candidates for the reviewer to
      choose between. It should not: **Draft returns exactly one candidate and keeps doing so.**
      There is no picker and no multi-candidate machinery. What replaces it is a uniform gate —
      **every section with a diff is a card, and the reviewer accepts or rejects that card**,
      having edited its text first if they want to. One candidate is enough precisely because
      the decision is not *which* edit but *whether* this edit.

      This makes a `conflicting` claim unexceptional at the gate: it is another card with the
      same two buttons, which is what "it acts the same as when there is a conflict" means.
      Nothing about conflict handling is a separate interaction mode, so the side-by-side
      readings are a matter of what the card *displays* — both readings with their tiers and
      citations — rather than a second control. Rejecting such a card leaves the claim
      `unresolved` for the revisit queue (§7) rather than picking a side on the reviewer's
      behalf, which is the behaviour §9's closing beat depends on and it needs no new stage

- [x] **The gate reaches the wiki as a corner button that opens the run in a popup** — decided
      and built Aug 30, 2026. The Verify gate had no way in from the thing it edits: a reviewer
      had to know the app existed and go to it. Three options were real. A **browser extension**
      works on wikis we do not own, but costs a manifest, a content script and a "load unpacked"
      step on camera, and it renders our gate inside MediaWiki's DOM. A **MediaWiki PHP
      extension** is days of work and buys nothing site JS does not. **Site JS opening a popup**
      won: `wiki-config/continuity-launcher.js` is installed as `MediaWiki:Common.js` and puts a
      floating **Continuity** button in the article's bottom-right corner, which opens
      `#/verify?page=…&rev=…` in a 960×980 window. `$wgUseSiteJs` defaults true, so it runs for
      every reader including anonymous ones, and there is nothing to install.

      **A corner button rather than a tab in the skin's own bar**, which is what it was for the
      first hour. The button is the affordance a reader already reads as "something else is
      watching this page" — it stands in for the browser extension a real deployment would ship,
      it owes nothing to the skin's chrome so it survives a skin change, and it is the shape the
      demo needs: visible in a wide shot without pointing at it.

      **The deciding argument was origin, not effort.** The popup is served from our own host,
      so `/api/state` and `/api/queue/{edit_id}` stay same-origin and the deploy keeps the "one
      origin, no CORS, no second deploy" property it was designed around (§6, "Deployment
      shape"). Every option that renders the gate *inside* the article — extension or injected
      panel — makes both fetches cross-origin and puts `FE/styles.css` next to a skin's
      stylesheet. That is a deployment change wearing a frontend change's clothes. The rule is
      now an invariant in `AGENTS.md` §2.

      **The plug-and-play claim survives it.** The launcher is a *trigger*, not the integration:
      the integration is the URL. A bookmarklet firing the same `#/verify?page=…` works on a
      wiki we do not control and needs no install either, which is the honest version of "the
      agent is pointed at a wiki, not wired to one" — one contract, two ways to fire it. No
      extension exists or is planned.

      **What it also closed.** Building the popup meant building the gate, so two of the four
      missing pieces below landed with it: the draft is **editable in place** — a changed card
      says the diff above it is now only the agent's proposal — and publishing **POSTs the text
      the reviewer settled on**, never the stored draft. The publish route still answered 501 at
      that point and the gate printed it verbatim rather than implying a write happened; the
      entry below is where it became a real write. `window.opener` is deliberately preserved so
      that the article behind the popup reloads and the reviewer watches the edit land instead
      of being told it did.

- [x] **The popup shows the run, and the gate has two levels** — decided and built Aug 30, 2026,
      same session. The popup opens on a **rail of the eight stages** (§6) as a stepper: ticked
      through Diff, standing on Verify, with a count under each — claims audited, sources
      retrieved, conflicts found, edits drafted, checks read, cards decided. It is the
      architecture diagram made into the run's own progress, which is the thing a judge has to
      understand in the first ten seconds of the video and the thing a static queue never said.

      **Every count is derived from the payload on screen, and that is the constraint.** The
      rail describes the run that produced the cards below it; it does not simulate one. The
      sequential reveal is a CSS `animation-delay` per node, not a timer walking a fake state
      machine, and when the backend is a fixture the rail says so under itself. A rail that
      animated a run nobody performed would be the most convincing lie on the page — `CLAUDE.md`
      §6 asks motion to reflect real state, and this is the case that rule exists for.

      **The gate now has two levels: per-card, then per-run.** Accept / Reject on a card decides
      *what* would go and writes nothing. One **Publish** button at the foot writes the accepted
      set, and it only unlocks once every card has a decision — so the reviewer reads everything
      before anything happens, and can still discard the whole run at that point. That is the
      "final check" a person asked for and it is worth the extra click: a per-card accept that
      wrote immediately would mean the batch review never existed, and the reviewer would be
      committing one card at a time without ever seeing the set.

- [x] **The publish route writes, and it writes by substitution** — decided and built Aug 30,
      2026, same session. `POST /api/queue/{edit_id}` was the last shell in the gate. It now
      logs in with the BotPassword, re-reads the section and applies the approved text, and
      answers with the revision id it created. The demo's three edits were published through it
      end to end and the wiki re-seeded byte-for-byte afterwards.

      **A queued edit is applied as a substitution, not as a section.** The draft names the text
      it replaces (`before`) and what that text becomes (`after`), so the route re-reads the
      section and swaps the one for the other in whatever the page says *now*. Writing the
      drafted section wholesale would have reverted anything else that changed in it while the
      edit sat at the gate — the same silent overwrite `basetimestamp` exists to catch, one
      level down, and invisible to it because the write would be a legitimate edit against a
      current base revision. `core/wiki/sections.py` decides it (pure, refusing an anchor that
      is missing or ambiguous) and `WikiWrite.write_anchor` performs it.

      **Publishing the same edit twice is refused rather than duplicated.** An edit that *adds*
      to a line leaves the line it anchored on, so the second approval finds the anchor again
      and appends the same text a second time — the Gambit card does exactly this, and it is
      invisible to every guard above it: the anchor resolves, the base revision is current, and
      MediaWiki accepts the edit. The tool checks whether the replacement is already in the
      section before substituting, and the route reports that as `409` alongside a conflict and
      a vanished anchor. The frontend's own guard is per-browser and does not survive a reload,
      so this had to be server-side.

      **The route is public, so the request decides as little as possible.** Judging requires
      `--allow-unauthenticated` and there is no session to identify a reviewer by, so the answer
      is not authentication but blast radius: the body carries a verdict and the reviewer's text,
      and every argument that decides *where* the write lands — page, heading, anchor, summary —
      is read from the stored queue entry `edit_id` names. An unknown id is a 404 before
      anything is read; a known one can only put text where our own agent already proposed a
      change, on a wiki `MediaWikiWriter.for_profile` will not let be anything but ours. The
      rule is now an invariant in `AGENTS.md` §2, because the way to lose it is to add one
      convenient parameter.

      **A rejection is a discard, not a verdict — clarified the same day.** It was briefly
      built as a 501: nowhere to record the rejection, so refuse it. That was the wrong model.
      Rejecting a card drops it out of the run, what survives the discards *is* the final draft,
      and the bar publishes that — so a rejection has nothing to send and no server state to
      change. The route therefore has one verb and no verdict field at all, and the body is the
      reviewer's text alone. This is the same fact `AGENTS.md` §2 already recorded on the ledger
      side, where a discarded draft leaves the claim `unchanged` and there is deliberately no
      `rejected` transition; the API had drifted from it. Extra fields are refused rather than
      ignored, so a body that tries to name a page is a 422 and not a quiet publish of the
      stored draft.

      **The queue itself still comes from the fixture.** The route reads the drafted edit from
      `FE/data/demo-state.json` because there is no Firestore adapter yet. That is a stub, and
      it is labelled one — but unlike `/api/state` it claims nothing to the frontend: it is the
      record of what the agent drafted, and swapping it for the store changes one function.

- [x] **The review draft is a stored document, and the queue stops being a fixture** — decided
      and built Aug 30, 2026, same session. Until this the drafted edits were a generated JSON
      file and every verdict lived in a browser tab: closing the popup lost the review, and
      reloading it re-offered the cards that had just been discarded. Now a run is one
      `ReviewDraft` in a document store — local JSON file, or Firestore with
      `DRAFT_STORE=firestore`, holding the identical documents — fetched back by id, with the
      verdict and any hand-edit written as it is made.

      **One document per run, not one per change.** Publish is a single act over the accepted
      set and "every card decided" is a property of the *set*, so the set is what gets stored
      and what carries the published flag. The alternative — a row per change and a flag
      reconstructed by counting them — puts the gate's central rule in a query rather than in a
      record, and gives two readers two ways to disagree about whether a run is finished.

      **Three fields carry the lifecycle, and each earns its place.** `decision` is the verdict
      on one change, and it lives on the change rather than on the claim because `ClaimStatus`
      has no `rejected` value and must not grow one (`AGENTS.md` §2) — a discarded change leaves
      its claim untouched, to be drafted again later. `written_revid` is the revision a change
      actually created: stored because MediaWiki has no cross-page transaction, so a publish can
      partially fail, and the retry has to write what is outstanding rather than what already
      landed. `published_at` is stamped only when every accepted change is written *and* at
      least one was accepted — a run where the reviewer discarded everything published nothing,
      and a flag saying otherwise would be the demo lying about its own headline moment.

      **The publish request lost its body entirely.** It used to carry the reviewer's text; the
      text now lives in the draft, so the request carries nothing at all and the route reads
      everything — pages, anchors, texts, verdicts — from the store. That is a strictly smaller
      public surface on a route that is `--allow-unauthenticated` by necessity, and it is the
      shape §2's invariant now fixes.

      **What is still a fixture, and what is not.** The *edits* are still hand-written demo
      claims driven through the real ledger core by `build_demo_state.py`, because no graph runs
      yet to produce one — `scripts/seed_drafts.py` loads them into the store and doubles as the
      demo reset. What is no longer a fixture is the review: the verdicts, the hand-edits, the
      revisions each change wrote and whether the run is published are real stored state, and
      `/api/state` still answers 503 so the ledger and page views stay honestly labelled.

      **The Firestore adapter is written and not yet run against Firestore.** It is transport
      only — `to_document` straight to `.set()`, `.to_dict()` straight back — and its tests use
      a fake client, the same way the wiki adapter's tests assert what `action=edit` puts on the
      wire rather than editing a wiki. The emulator still needs a JRE and
      `gcloud components install cloud-firestore-emulator`, so `DRAFT_STORE=file` stays the
      default until it has been run for real. Sorting and the unpublished filter are done in
      Python deliberately: `order_by` plus a filter needs a composite index, the emulator does
      not enforce index requirements, and a missing one fails only in production.

      Publishing was one POST per accepted edit at this point, in order, because MediaWiki has
      no cross-page transaction: the batch is not atomic and a partial failure is reported
      rather than rolled back. The non-atomicity is still true and is an invariant in
      `AGENTS.md` §2; the request shape is not — the entries below moved the whole set behind
      one call over a stored draft. The same entries answered "what happens to a rejection":
      nothing, by design. It is a discard, and the claim behind it is untouched.

### Phase 1 — local; nothing in the cloud has to exist

Ordered by dependency, with one deliberate exception: the last two items are writing, parked for
the final week — which puts the shot list below the recording session that needs it. That is a
scheduling choice, not a dependency claim. The video itself sits late because it needs a working
agent to film, not because it ranks low: it is both a hard requirement (§2) and impossible to
rush, so everything above it exists to serve it, and the two *if time permits* items are what
gets cut to protect it.

- [x] Define the last ADK tool signature — **the ledger tool** — Aug 29, 2026.
      `backend/agent/tools/ledger.py`, following the pattern the other three set: the profile is
      bound at construction and never appears in a signature, every model-facing argument is
      JSON-expressible, domain errors come back as values while transport errors raise
      (`AGENTS.md` §7). Six operations rather than the two this item first named — see the
      decision-log entry above for why the count grew and what the write side refuses to accept.
      The deterministic path is the in-memory store, so the whole graph is runnable with no
      database at all; the Firestore adapter lands behind the same protocol without a node
      noticing

- [ ] Build the 8-stage ADK graph — nodes, the two backward edges, and **Verify** as the HITL
      pause (§6, `AGENTS.md` §7). The API shape is now verified rather than assumed:
      `Workflow(edges=[(START, n1), (n1, n2), (n2, {"route": n1, ...})])`, nodes route by
      assigning `ctx.route`, and the Verify gate goes through `google.adk.tools.request_input`
      — all three traps are in `AGENTS.md` §6. Fan-out is the last node, not a middle one, and its
      backward edge to Research means the run pauses at the gate twice; the node must refuse to
      fan out a claim that was already fanned in, which is what terminates the cycle. The
      reschedule rule needs no core change: `decay.next_interval(..., changed=True)` already
      exists, so the node just calls it for every claim it named. The Draft and Diff nodes are
      written (`agent/draft.py`, `agent/semantic_diff.py`) and sit between Classify and Verify;
      wiring them needs a home for the `Draft` and its `Review`, since nothing persists either
      yet and the gate is where hours pass. Verify itself is no longer a model node (Aug 30) —
      it resumes the paused run with whatever text the reviewer approved
- [x] Build the ledger store, **locally first** — Aug 29, 2026. `core/ledger/documents.py` owns
      the stored shape and `core/ledger/store.py` the `ClaimStore` protocol plus two
      implementations: `InMemoryClaimStore` (the deterministic path, so the graph runs with no
      database at all) and `JsonFileClaimStore` (the local database, atomic writes, one file of
      the exact documents Firestore will hold). Both are pure — filesystem only, like
      `snapshots.py` — and their tests run bare. See the decision-log entry above for what
      the two portability guards are and why they are guards rather than preferences
- [ ] Port the store to Firestore — an adapter at the perimeter importing `to_document` /
      `from_document` and nothing else, so only the transport is new. **Half done Aug 30, 2026:**
      the *drafts* collection has one (`backend/firestore.py`, `DRAFT_STORE=firestore`), written
      against a fake client because the emulator is not installed; `claims` and `sections` still
      need theirs, and none of the three has been run against a real instance. `google-cloud-firestore`
      is not yet a dependency. Runs against the emulator locally, which needs a JRE plus
      `gcloud components install cloud-firestore-emulator` — neither present as of Aug 23, 2026.
      The emulator does not enforce composite-index requirements, so the due query stays on
      `next_check_at` alone (`AGENTS.md` §6)
- [ ] **Build the Verify gate — the `FE/` rework plus the publish route.** Since Aug 30, 2026
      this *is* the Verify stage (§6), not decoration on it, which moves it from cosmetic rework
      to a critical-path item. The queue already renders a drafted edit as a git-style diff and
      takes approve/reject over it. Four things are missing. **The bucket split**, with a *still
      true* view that shows confirmations rather than hiding them and a side-by-side conflict
      view; `build_demo_state.py` has to emit the bucket per claim. **The flags**, which are
      computed and invisible — `Draft.payload()` carries `bucket`, `shape` and `flags` and
      `Review.payload()` carries the idea-level `verdict` and its per-assertion changes, and the
      queue renders none of it, so an `overreached`, `uncited` or `hidden_by_text` card looks
      exactly like a clean one. `hidden_by_text` matters most: the diff renders green and the
      edit reversed what the passage asserted, so the rendering the reviewer trusts is the one
      misleading them. ~~**An editable draft**~~ and ~~**the publish button**~~ — both built
      Aug 30, 2026 with the launcher (entry above): the reviewer changes the text in place and
      approve publishes that text, not the agent's proposal. ~~**The server half**~~ landed the
      same day (entry above): the route re-reads the section, substitutes the approved text and
      answers with the revision it created — and the draft it works from is now stored, so the
      verdicts and the hand-edits survive a reload. What is left of this item is the two
      rendering gaps above: the bucket split, and the flags. Since fan-out runs after the gate,
      an approval also *adds* cards, so the queue has to handle growing and not only shrinking.
      Rework of a passing component, so re-run `node FE/check.js`
- [ ] Before recording, confirm the run actually produced at least one conflict — §9 beat 6
      depends on it. Not a decision, a check: if the week is quiet, widen the research
      objective or close on a different beat
- [ ] **Record and cut the demo video — the priority item in this phase.** ≤3 min, public on
      YouTube or Vimeo, English or subtitled (§2). Beats and their order are in §9, turned into
      a recording plan by the shot list at the end of this phase. Record against
      localhost with the URL bar cropped — a visible `localhost:8000` reads as unfinished, and
      nothing in the rules requires the video to show the hosted URL. Budget two passes: the
      first run always exposes a beat that does not read on camera
- [ ] **Move the local wiki into Docker** — after the native install works, not before. Same
      two services, same `LocalSettings.php`, same seeder pointed at a new endpoint; the value
      is that the deploy weekend then ships a container that has already been proven locally
      rather than one written on the day. Nothing on the agent side changes, which is the point
      — `MEDIAWIKI_API_URL` moves and no code does. Parked deliberately: it is a packaging
      task, and packaging a thing that does not yet run is how a day disappears
- [ ] *If time permits* — **an explicit retrieval-sufficiency criterion.** Gives the "retry: thin
      retrieval" edge a trigger anyone can implement: N sources at or above the claim's tier floor,
      and for a moving claim at least one published after its `as_of`. Fails → broaden the objective
      and retry, bounded by `research_rounds` — whose ceiling exists in the core
      (`MAX_RESEARCH_ROUNDS`, `Claim.budget_spent`) but is enforced nowhere, since
      `record_research` spends a round without checking it. This is the natural place to close
      that. Deterministic, so it belongs in the pure core beside the tier table. Satisfies §4's
      requirement 5, which nothing currently does
- [ ] *If time permits* — **split *still true* into confirmed vs unchallenged.** A qualifier inside
      the bucket, not a fourth bucket, so the review split stays three-way. Confirmed = retrieval
      corroborated it; unchallenged = retrieval found nothing against it. Treating them alike is how
      the ledger rots quietly: absence of evidence bumps `last_verified` and doubles the interval, so
      a claim no one can source gets checked ever less often. Fix lands in `decay.py` — unchallenged
      grows the interval by a smaller factor, or not at all
- [ ] **Rebuild the classify benchmark, as committed test cases.** The four rules in
      `classify.SYSTEM` each came from a measurement — precedence order took the precision case
      from 0/3 to 3/3, open-world phrasing moved every model from 50% to ≥88% — and the harness
      that produced those numbers was never committed. `tests/test_classify.py` asserts each
      rule is *present* in the prompt, which catches deleting one and cannot catch weakening
      one: a reworded prompt could drop the precision case back to 0/3 and every test would
      still pass. Nothing else in the repo protects a measured result this specific.

      **It has to cover the diff stage too**, whose rules are reasoned rather than measured
      (§6). The first case to score is the appended negation — `after` keeps every character of
      `before` and adds a clause that takes the assertion back — because that is the one the
      textual floor structurally cannot catch, so a weakened prompt there costs the guard
      entirely and no existing test would notice.

      **Shape it as cases, not as prose.** One case is a claim, a section, a search payload and
      the bucket it must land in — the same four inputs `Classifier.classify` already takes, so
      a case is data rather than a new harness. Four are already specified by the documents that
      recorded the failures: the variant-vs-prime precision case (`seed-plan.md` §4.3, the one
      referred to as benchmark case #4), an absence the page simply lacks that must come back
      `new` and not `conflicting`, a genuine two-source disagreement that must come back
      `conflicting` with both sides named, and a claim the page already states that must come
      back `still_true`. A fifth worth adding is a closed-world phrasing of an existing case,
      asserted to fail, so the ledger's positive-assertion rule is measured rather than trusted.

      **Two modes, and both are the point.** Against the cassette it is deterministic, free and
      belongs in the normal gate — a prompt edit that changes a verdict fails a test. With
      `--live` it re-measures against Gemini and reports a pass rate, which is the only thing
      that can tell you whether a rewrite helped or hurt. Live cannot be in the default suite:
      it needs ADC, it spends credits, and a non-deterministic assertion in the gate is worse
      than no assertion.

      **Ordered here deliberately.** It is engineering rather than writing, so it sits above the
      two writing items — but below the video, because it ships no behaviour a judge will see.
      If the week collapses, this is cuttable and the video is not. It is on this list rather
      than in Phase 2 because a prompt is far more likely to be tuned in the last week than
      after the deploy, which is exactly when the safety net matters most.

- [ ] **Write the shot list** — the §9 beats as an ordered recording plan: which view is on
      screen, what happens on it, how many seconds it gets. Three minutes is 180 seconds and the
      beats do not divide evenly, so this is where the cuts get decided rather than discovered in
      the edit; beat 7 (two runs, restricted vs full source set) is already optional in §9 and is
      the first to go. It also settles a contradiction in §9's own text, which numbers the cascade
      second but says it opens the video. Parked here as final-week writing, but it has to exist
      before the recording session above it, not after
- [ ] **Write the submission description** — features, tech used, data sources, findings and
      learnings (§2). Last of everything: it needs no code, no deploy and no agent run, so it
      absorbs whatever time is left rather than competing for time that is not. Unlike the two
      *if time permits* items above it, this one **cannot be cut** — it is a hard submission
      requirement

### Phase 2 — deploy weekend, Sept 5-6, 2026

Sept 7 is a Monday, so this is the last window. Ordered so the step with an unknown answer comes
first and the metered one comes late. The procedure itself is in `README.md`; this is the order.

- [ ] **Create `continuity-run@` and prove its Gemini role — before anything else.** Grant
      `aiplatform.user`, `datastore.user` and `secretmanager.secretAccessor`, then make one model
      call under `gcloud auth application-default login --impersonate-service-account=…`. Local
      ADC runs as the project Owner and therefore always succeeds, so nothing done so far says
      whether a three-role service account can call Gemini. Cheap to fix if the role name is
      wrong — Owner on an org-less project grants any role in seconds — but expensive to discover
      after a day spent on the wiki
- [ ] **Provision** — the eight APIs, Firestore in `us-east1`, the Cloud SQL instance and its
      `mediawiki` database, and the four Secret Manager entries. Cloud SQL bills from creation
      rather than from use, which is the whole reason it sits here and not in Phase 1.
      `--allow-unauthenticated` is already known to be available: the project has no parent
      organisation and no domain-restricted-sharing policy (checked Aug 23, 2026)
- [ ] **Deploy `mediawiki`, then seed it** — repoint `LocalSettings.php` at the Cloud SQL socket,
      deploy with `--add-cloudsql-instances` and `--max-instances 1`, create the bot password at
      `Special:BotPasswords`, and re-run `seed_wiki.py` against the new endpoint. The instance is
      rebuilt from `snapshots/seed/`, never migrated out of the local database — which is what
      makes the local-first split free rather than a detour
- [ ] **Deploy `continuity`** — `docker build -t continuity .` first as a pre-flight: local
      Docker is *not* required (Cloud Build builds remotely from `--source .`), but a typo in the
      `Dockerfile` found locally is a two-minute fix instead of a Cloud Build round trip. Then
      deploy with the MediaWiki endpoint and bot credentials in place, and confirm the hosted URL
      is publicly reachable and unauthenticated **from a private window** — your own session lies
- [ ] **Cloud Scheduler, then the budget alert** — create the hourly job with the tick token and
      the service URL, then set the $25 alert. Check the first day's bill against §6: those
      figures are from recall, and the deployed service is the cheapest place to find out they
      were wrong
- [ ] **Submit** — paste the hosted URL into the Devpost form alongside the video and the
      description already finished in Phase 1, and confirm the URL resolves for a logged-out
      visitor. Deadline **Sept 7, 2:00 PM PT** (= 5 PM ET, §2). This is the only submission
      step that ever needed the deploy

**8 days left** as of Aug 30, 2026. Both vendor perimeters are built and proven against the real
thing rather than against a design: Parallel search has made a live call, Gemini classifies a real
claim through `agent/classify.py`, and the wiki adapters read and write a real MediaWiki that is
up and seeded. The deterministic core, the seed corpus, the frontend, the service shell and a
persisting ledger are real, and the baseline pass fills that ledger with no key and no model call.
**What remains is the graph that joins them** — eight stages, two backward edges and a human
gate — plus claim proposal, now the only stage that still needs a model, and the Verify gate
with the publish route behind it, which need none. Then the video, then the deploy.

That is a narrower risk than it was a week ago, and a different kind. Nothing left depends on
an unknown API or an unproven vendor; every external surface has been called and measured, and
each one has a deterministic replay behind it, so the graph can be built and tested with no key,
no network and no container. The risk is now assembly, which is the kind you can work through in
a straight line.

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

**Retrieval shape measured live Aug 23, 2026 — and it settles the "split the search" question.**
Two calls on demo claim #1 (Gambit in *Avengers: Doomsday*), three queries, the MCU profile's
13-domain allowlist:

| | Results | Distinct domains | Tier histogram | Latency |
|---|---|---|---|---|
| Default `max_results` | 10 | **6** | `{1:2, 2:6, 3:2}` | 5.65s (cold) |
| `max_results=20` | 20 | **6** | `{1:3, 2:15, 3:2}` | 1.32s (warm, same queries) |

**Doubling the results found no new publishers** — variety went 3->9 and deadline 2->4, the
same six domains throughout. Six distinct publishers spanning three tiers is already double
what §6's confidence model can use, since corroboration saturates at three domains when the
best is tier 1. So partitioning retrieval into several smaller calls would multiply
`sku_search` by the number of partitions to buy nothing measurable, and raising `max_results`
buys depth rather than breadth while scaling the second meter. One call, default settings, is
the answer. The two latencies are not comparable: the second ran the same queries against a
warm cache.

Three things the run exposed that the spec did not have. **Billing is two meters** — a
20-result call billed `sku_search: 1` *and* `sku_extract_excerpts: 10`, so cost scales with
results and not only with calls. **`max_results` above 20 is silently reduced**, returning a
200 with a warning rather than an error. And **the top tier was the least complete source**:
`marvel.com` and `disney.com` list Channing Tatum in the cast without naming Gambit, so the
claim is only supported by tier-2 trade prose and a tier-3 table. Tier orders authority, not
completeness — which is a Draft-stage rule, now in `AGENTS.md` §7, and a nuance §6's tier
design had not stated.

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
propagate silently; Draft output is human-gated at Verify, so a weaker draft costs a reviewer
edit rather than a wrong page — literally so since Aug 30, 2026, when editing the draft in place
became the gate's purpose. Revisit if Draft quality disappoints — the model is named in one
place. Raw script: `bench_classify.py` (scratchpad, not committed).

**ADK 2.0 = Workflow Runtime.** Graph execution engine; agents, tools and functions are
*nodes* (`BaseAgent` now subclasses `BaseNode`). `NodeInterruptedError` exists to pause a
workflow for human-in-the-loop input.

This is what makes §6 buildable as designed rather than a diagram: the 8-stage flow with two
backward edges maps onto a workflow graph, and the Verify approval gate onto HITL — twice per
run, since fan-out follows it. Nothing
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
