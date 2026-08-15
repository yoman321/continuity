# Seed plan — Deadpool & Wolverine

Demo subject for the wiki maintainer agent. Defines what goes into the seeded MediaWiki
instance and what the claim ledger tracks.

**Settled:** MCU Wiki as the single source · 8 pages · 50 claims · freeze at 2024-08-09.

**Verified against the live wiki, Aug 15, 2026.** Seed revision `2019481`
(2024-08-08T23:57:40Z, 50,454 bytes) exists and pulls cleanly; templating is light enough
for section-level edits (§7). The claim set in §3–§4 was rebuilt on that evidence — the
original set assumed box-office and awards data this wiki does not carry (§8).

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

**Why 2024-08-09 still, on new reasoning.** The original justification was box office being
mid-flight at two weeks — dead, since this wiki never records it (§8). The date survives for
a better reason: it sits *before every later MCU release that touches these characters*.
*Thunderbolts* (which takes the `Void` name, §4.2) and *The Fantastic Four: First Steps*
(which introduces the prime Johnny Storm, §4.3) both ship after it, as do the *Avengers:
Doomsday* casting announcements. Freeze later and the agent has progressively less to find.
Two weeks post-release also means the page is complete rather than a stub, so what the agent
changes is a real correction rather than filling in a blank.

**The direction of work.** The agent does not diff page revisions — it re-checks a claim
against the world and edits the page to match. The current live page is therefore *not* the
target; it is one possible outcome, produced by human editors with different priorities. In
several cases (§4.2, §4.3) the agent should reach a correct edit that the humans have not
made. That is the product working, not a mismatch.

---

## 2. Page list (8 pages, 50 claims)

All from **Marvel Cinematic Universe Wiki** — deepest page structure, cleanest ripple.
Titles below are the resolved ones; drift is measured seed → live, both pulled Aug 15, 2026.

| # | Page | Claims | Seed → now | Why it's here |
|---|---|---|---|---|
| 1 | `Deadpool & Wolverine` | 14 | 50,454 → 60,864 (+21%) | The trunk |
| 2 | `Gambit` | 6 | 8,179 → 15,473 (**+89%**) | Cast in *Avengers: Doomsday* — the lead beat (§4) |
| 3 | `Void (End of Time)` | 6 | 15,102 → 20,768 (+38%) | The disambiguation cascade (§4) |
| 4 | `Human Torch` | 5 | 2,990 → 18,028 (**+503%**) | *First Steps* released; variant-vs-prime precision test |
| 5 | `Phase Six` | 5 | 1,580 → 7,309 (**+363%**) | Slate composition — the fastest-moving list page |
| 6 | `Deadpool` | 5 | 67,530 → 80,534 (+19%) | Character ripple from the trunk |
| 7 | `Blade/Universe Defender Blade` | 5 | 9,379 → 16,221 (+73%) | Variant subpage — proves the agent tracks subpages |
| 8 | Low-drift control set | 4 | +2% to +3% | `Wolverine`, `Cassandra Nova`, `Time Variance Authority`, `Phase Five` |

**Page 8 is not filler.** Those four moved 2–3% in two years. They are what proves the
decay ladder: claims that should double their interval every run and settle at the 6-month
ceiling. A ledger where everything is volatile demonstrates nothing (§3).

**Two title traps, both verified.** `Void` now redirects to `Sentry`, not the D&W location —
the seed's `[[Void]]` links are live-wrong today, which is claim §4.2. And D&W's cameo
characters live on **variant subpages** (`Human Torch/Void-Analyzing Fantastic Four`,
`Elektra/Forgotten Elektra`, `Blade/Universe Defender Blade`), not on the main character
pages. `Elektra` is the 136KB Daredevil-series page and is *not* a D&W ripple target.
Resolve redirects before seeding or the ledger will point at the wrong pages.

**8 rows, 12 files.** Row 8 is four pages, and the pull adds
`Human Torch/Void-Analyzing Fantastic Four` — §4.3 is a test of telling the variant from the
prime, which needs both sides present. It carries no claims of its own; the count stays 50.
Every byte figure in the table above was reproduced by the pull, so the drift numbers are
measured, not estimated (`snapshots/manifest.json`).

---

## 3. Claims by volatility wave

Mapped to summary.md §7. The wave sets the initial `next_check_at`; the agent's decay logic
takes over from there.

The waves are **not** the film's commercial lifecycle. This is a post-release, in-universe
wiki: nothing here moves because box office settled, it moves because *another film shipped
or another cast announcement landed*. What drives change is external events in the
franchise, which is exactly what Parallel is good at finding.

**Settled — should decay to the 6-month ceiling within two runs (13)**
Release date · runtime · director · writers · composer · principal cast and portrayers ·
production-history dates · plot beats · the strike delay

The control group. If every claim is volatile the decay ladder proves nothing.

**In-universe, slow (11)**
Character fates · relationship status · variant designations · TVA continuity with *Loki*
S2 · Cassandra–Xavier relationship · costume and artefact details

Moves only when a later installment retcons it. Low yield, and that is the point: most
research rounds should end in "no change," which is what makes the ones that don't legible.

**Release-driven (14)**
Cross-reference targets · variant-vs-prime disambiguation · "appearances in" lists · Phase
membership · link targets that a newer page has since claimed

Re-tested every time an MCU film or series ships. `Void (End of Time)` and `Human Torch`
both sit here, and both are wrong in the seed today.

**Announcement-driven (12)**
Future appearances · casting for unreleased films · slate dates and delays · retcons
trailed in interviews

Fastest-moving, trade-press sourced, and the wave where `status: unresolved` occurs
naturally — outlets routinely disagree on whether a casting is confirmed or in talks.

---

## 4. The six claims that carry the demo

Everything else is texture. These map onto the summary.md §9 video beats. All six were
confirmed against the live wiki on Aug 15, 2026 — each is genuinely stale in the seed today.

| # | Claim | Seeded as | Demonstrates |
|---|---|---|---|
| 1 | **Gambit's future appearances** | Cast credit only, no future work | Cast in *Avengers: Doomsday*. One search, one confirmed fact, and it lands on `Gambit` **and** `Phase Six` **and** the film's appearances context. The cascade, legible in seconds |
| 2 | **`[[Void]]` link target** | `[[Void]]`, plain | *Thunderbolts* gave `Void` to Sentry; the seed's link now sends readers to the wrong character. **Nobody edited the page — the world moved underneath it.** Forces the agent to pick between two live targets on evidence |
| 3 | **Human Torch identity** | Flat reference to Johnny Storm | *First Steps* introduced the prime MCU Johnny Storm (that page grew **+503%**). The D&W character is a Void variant. The correct edit distinguishes them; the tempting edit conflates them. **This is the precision test — the one where a wrong answer is worse than no answer** |
| 4 | **Phase Six composition** | 1,580-byte stub | +363% and still moving. One research round yields several claims at once — shows batching and the ripple into `Phase Five` boundaries |
| 5 | **A contested cameo return** | Not present | Trade outlets routinely split on confirmed-vs-in-talks for unreleased films → `status: unresolved` + revisit queue. **The strongest behaviour in the design** (summary.md §7). Pick the specific cameo at ledger-seed time — whichever of the six is genuinely contested that week |
| 6 | **A shipped film's release date** | Absent or "TBD" | Trivially verifiable, single authoritative source. One easy claim so the diff queue isn't all hard cases |

**Ordering for the video.** Open with **#1** — the cascade is the design's distinctive
feature and reads instantly on screen. Close with **#5**: an agent that says *"two credible
sources disagree and I am not resolving this"* reads as more trustworthy than one that
always produces an answer, and summary.md §7 already identifies that as the best behaviour
in the design. Put **#2** in the middle; it is the subtlest and the most convincing to
anyone who has maintained a wiki, because no diff would ever have surfaced it.

**What #2 and #3 have in common** is worth stating in the writeup: both are claims that
became wrong without the page changing. A human maintainer finds those only by chance. That
is the case for the product, and neither is discoverable by diffing page revisions — only by
re-checking the claim against the world.

---

## 5. Deliberate omissions

- **No box office, budget, reception or awards claims.** Not an oversight and not a gap in
  the seed — this wiki has no section for any of them on *any* film page (§8). An agent that
  researched its way to a gross would have nowhere conventional to write it, and inventing a
  section is the kind of edit wiki communities revert. Those claims are Wikipedia's job.
- **No restructuring or reformatting claims.** The largest real diff on the trunk page is the
  Appearances list being reorganised into a location hierarchy (+6,444 bytes). No search
  result implies that edit; it is an editorial convention decision. Out of scope by design,
  and saying so is the difference between scoping and missing it.
- **No fan-theory or speculation claims.** Not verifiable, not wiki-appropriate, and they'd
  teach the agent bad adjudication habits.
- **Cast list capped at principals + the six cameos.** The full credited cast is ~87 bullet
  entries on the live page and adds no new agent behaviour.
- **Social media is a tier, not a ban.** summary.md §8 cuts Twitter as a *monitoring target*
  and that stands. But the seed page itself cites Reynolds' Twitter and Instagram for the
  Jackman casting and the production wrap, so the agent must be able to *read and rank* a
  social citation it encounters — lowest tier, never sufficient alone, acceptable as
  corroboration when the primary is a studio principal announcing their own project.

---

## 6. What this unblocks

The ledger schema. Per summary.md §10, every other interface falls out of it — and the
fields are now derivable from the claim set above rather than guessed:

- `as_of` / source publication date, for recency-based adjudication (§1)
- `ripple_targets[]`, for the Gambit → `Phase Six` cascade (§4.1)
- `contradicts[]` and `status: unresolved`, for the contested cameo (§4.5)
- `wave`, seeding the initial `next_check_at` (§3)

Two fields the *revised* claim set forces that the old one did not:

- **`claim_kind`** — a claim's subject can be a prose value (*"grossed X"*), a **link target**
  (§4.2), or a **list membership** (§4.4). These verify and patch differently: a link claim is
  checked by resolving redirects, not by comparing text. Modelling all three as free text
  makes §4.2 unimplementable.
- **`entity_ref`** — which *variant* a claim is about (§4.3). `Human Torch` and
  `Human Torch/Void-Analyzing Fantastic Four` are different subjects, and research about one
  is evidence about the other only sometimes. Without this the agent's most likely failure is
  a confident, well-cited, wrong edit.

---

## 7. Pulling the seed — verified mechanics

MCU Wiki runs MediaWiki 1.43.9 with the action API open and unauthenticated. Two calls:
find the revision at the freeze date, then fetch its content by id.

```bash
BASE='https://marvelcinematicuniverse.fandom.com/api.php'
curl -s "$BASE?action=query&prop=revisions&titles=Deadpool%20%26%20Wolverine\
&rvstart=2024-08-09T00:00:00Z&rvdir=older&rvlimit=1&rvprop=ids|timestamp&format=json"
curl -s "$BASE?action=query&prop=revisions&revids=2019481\
&rvprop=content&rvslots=main&format=json"
```

Send a real `User-Agent`; Fandom throttles anonymous defaults. Pass `redirects=1` on title
lookups — two of the eight pages resolve elsewhere (§2).

**Templating is not a problem.** 134 template calls but only 15 distinct, and 110 of those
are `{{WPS}}` inline Wikipedia links. The only structural one is `{{Movie}}` in the lead.
Nine clean `==` sections, so `action=edit&section=N` works as designed and the summary.md §10
worry about heavy templating is closed.

**Licensing — settled: CC BY-SA 3.0 Unported.** `siprop=rightsinfo` self-declares only a bare
**CC-BY-SA** and points at the JS-rendered `fandom.com/licensing`, so it cannot separate 3.0
from 4.0. The wiki's own `Project:Copyrights` (revision 3728) states 3.0 Unported outright,
and the puller re-reads that page every run rather than hardcoding the answer. Share-alike
with attribution, so seeding our own instance is fine provided the MCU Wiki is attributed and
the licence carries forward — including onto the agent's own edits, which are derivative
works. The notice is `snapshots/ATTRIBUTION.md`.

**The snapshots are pulled.** `snapshots/` holds both states of all 12 pages with a manifest
carrying `revid`, `sha256`, byte size and drift per page. The seed side reproduces
byte-for-byte on re-run, and the test suite re-hashes it against the manifest, so a corrupted
fixture fails the gate instead of quietly becoming the seed.

---

## 8. Why this wiki carries no commercial data

Recorded so it is not rediscovered as a bug. Verified Aug 15, 2026.

MCU Wiki film pages have exactly these sections: Synopsis, Plot, Cast, Appearances,
Production, Videos, Music, References, External Links. *Avengers: Endgame* and *The Marvels*
have the identical nine. Grepping the trunk seed: **zero** hits for gross, box office,
budget, Rotten Tomatoes, Metacritic, awards, Blu-ray or Disney+. The two `$` matches are the
Disney–Fox acquisition price inside Production. The infobox drifted by **zero fields** in two
years.

It is an in-universe wiki. It documents what happens inside the story plus the real-world
*production* history — announcements, casting, interviews, trade reporting — and nothing
about the film's commercial life. Production is 12.5KB of dated, `Deadline`/`Variety`/`THR`-
cited reporting, and editors added **no post-release items to it in two years**: the +11/−11
line diff is 2020–2023 entries being reworded.

Two consequences, both already applied above: the box-office claim family is out (§5), and
the Production section is a genuine, visible staleness the agent can fill in a format that
already matches its output — a dated sentence with a trade citation.
