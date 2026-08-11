# Seed plan — Deadpool & Wolverine

Demo subject for the wiki maintainer agent. Defines what goes into the seeded MediaWiki
instance and what the claim ledger tracks.

**Settled:** MCU Wiki as the single source · 8 pages · 50 claims · freeze at 2024-08-09.

---

## 1. The demo model

Two states of the same wiki, and the agent produces the second from the first.

```
MCU Wiki revision              your seeded              agent runs             diff view
as of 2024-08-09       ──→     MediaWiki        ──→     live, today    ──→     (the demo)
(real historical text)         (Cloud Run)              (Parallel + Gemini)
```

**Seed frozen, run live.** The base is the page as it actually stood two weeks after
release; the agent searches the current web. Every fix is genuine, every citation is real,
and the audit step has an honest reason to flag things. A seed containing today's correct
values would give the agent nothing to do.

Because the seed is frozen and the run is live, the agent needs no date-bounded searches —
it just needs current truth. Source *recency* still matters in adjudication (a 2026 source
outranks a 2024 one on a moving claim), but that's a source-tier rule, not a query constraint.

**Pull the seed from real revision history, don't hand-author it.** Fandom is MediaWiki, so
the August 2024 wikitext still exists:

```
action=query&prop=revisions&titles=Deadpool_%26_Wolverine
  &rvstart=2024-08-09T00:00:00Z&rvdir=older&rvlimit=1&rvprop=content|timestamp
```

`Special:Export` works too. This gives you authentic period text — including whatever was
provisional or wrong at the time — for free, and the drift becomes real drift. Much better
answer when a judge asks how the demo was built.

**Why 2024-08-09 and not 3 months.** D&W's theatrical run was essentially over by late
October 2024. Freeze at 3 months and box office has already settled, killing the most
legible claim in the set. At two weeks the gross is still mid-flight (~$824M → ~$1.34B),
and you keep the entire awards and retcon wave on top of it.

---

## 2. Page list (8 pages, 50 claims)

All from **Marvel Cinematic Universe Wiki** — deepest page structure, cleanest ripple.

| # | Page | Claims | Why it's here |
|---|---|---|---|
| 1 | Deadpool & Wolverine (film) | 15 | The trunk. Carries the volatile claims |
| 2 | Wade Wilson / Deadpool | 7 | Character ripple |
| 3 | Logan / Wolverine (variant) | 7 | Character ripple + continuity contest |
| 4 | Cassandra Nova | 4 | Antagonist, canon relationships |
| 5 | The Void | 4 | Location — ripples to *Loki* |
| 6 | Time Variance Authority | 4 | Organization — cross-property continuity |
| 7 | MCU Phase Five | 3 | Timeline / list page |
| 8 | Cameo character pages (6) | 6 | One claim each — the rumor→confirmed arc |

Page 8 is six thin pages (Elektra, Blade, X-23, Gambit, Human Torch, Pyro), one claim
apiece. They exist to make the ripple visible: a single confirmed cameo touches six pages,
plus the film's cast section, plus the "appearances" list on each.

---

## 3. Claims by volatility wave

Mapped to summary.md §7. The wave sets the initial `next_check_at`; the agent's decay logic
takes over from there.

**Day 0 — stable, should decay to ~6 months within two runs (13)**
Release date · runtime · director · rating · principal cast and portrayers · variant
designations · first-appearance facts · strike delay

These prove the decay ladder works. If every claim in the ledger is volatile, the
self-decaying interval never demonstrates anything.

**Week 1 — plot and reception (11)**
Character fates · relationship status · costume details · ending · RT and Metacritic ·
TVA continuity with *Loki* S2 · Cassandra–Xavier relationship

**Month 1–3 — the visible movers (14)**
Worldwide / domestic / international gross · opening weekend · budget · R-rated ranking ·
home media date · Disney+ date

**Month 6+ — still live today (12)**
Awards and nominations · retcons from subsequent MCU installments · future appearances ·
Phase Five composition

---

## 4. The six claims that carry the demo

Everything else is texture. These map onto the §9 video beats.

| Claim | Seeded as | Demonstrates |
|---|---|---|
| **Worldwide gross** | ~$824M (week-2 figure) | The headline fix. One number, huge delta, legible in a second of video |
| **Budget** | $200M | Sources genuinely disagree ($200M vs $250M+) with no authoritative resolution → `status: unresolved`, revisit queue. **The strongest behaviour in the design** (§7) |
| **"Highest-grossing R-rated film"** | Asserted flatly | A superlative that was true, then contested. Forces source-tier reasoning rather than value-copying |
| **Gambit cameo** | "Rumored" | Rumor → confirmed arc. Fan site vs. trade press vs. official credits — authority tiers made visible |
| **Awards** | Blank / "TBD" | Clean resolution with citations. The satisfying one |
| **Home media date** | "TBD" | Trivially verifiable. One easy claim so the diff queue isn't all hard cases |

Lead the video with **budget**. An agent that says *"two credible sources disagree and I am
not resolving this"* reads as more trustworthy than one that always produces an answer —
and §7 already identifies that as the design's best behaviour.

---

## 5. Deliberate omissions

- **No claims sourced only to social media.** Consistent with the Twitter cut in §8.
- **No fan-theory or speculation claims.** Not verifiable, not wiki-appropriate, and they'd
  teach the agent bad adjudication habits.
- **No pre-release rumor claims except the cameo six.** Enough to prove the arc; more is
  repetition.
- **Cast list capped at principals + the six cameos.** The full credited cast is ~40 people
  and adds no new agent behaviour.
- **Cut in the 57→50 trim:** distributor, filming locations, photography dates, CinemaScore,
  deleted-scenes reporting, and two powers/abilities claims. All low-movement, all
  demonstrating nothing the remaining claims don't.

---

## 6. What this unblocks

The ledger schema. Per summary.md §10, every other interface falls out of it — and the
fields are now derivable from the claim set above rather than guessed:

- `as_of` / source publication date, for recency-based adjudication (§1)
- `ripple_targets[]`, for the cameo→six-pages cascade (§2, page 8)
- `contradicts[]` and `status: unresolved`, for the budget claim (§4)
- `wave`, seeding the initial `next_check_at` (§3)
