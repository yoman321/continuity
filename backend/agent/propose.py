"""The propose stage — reading a page and deciding what it asserts.

This is what fills the ledger Audit reads. Everything downstream is about a claim: Research
builds its query from one, Classify judges one against the world, Draft patches the anchor one
holds. Nothing created them until now — six were hand-written into a fixture and seeded, so the
agent re-checked a set somebody chose rather than one it found. This is the stage that finds
them.

**Its input is the page, not the web.** A claim is *what the page asserts*, so it is proposed
from the page's own bytes — which is also the only place a `wikitext_anchor` can come from.
Retrieval knows nothing about this wiki's wikitext, and a claim proposed from a web excerpt
would carry no anchor, so its edit could never be applied. The web's turn comes next, in
Research, once there is a claim to ask a question about.

**The anchor is the hard part, and it is checked rather than trusted.** The model is asked to
copy a span verbatim; models paraphrase. So every proposal is verified against the section text
before anything is stored — present, and present exactly once — and one that fails is dropped
with a reason rather than repaired. A claim whose anchor is not in the page is an edit that can
never apply, and it would sit in the ledger looking exactly like a good one.

**Three rules in the prompt come from measurements made elsewhere** (`AGENTS.md` §7), and they
are the reason this stage is not just "list some facts":

1. **Positive assertions, never closed-world.** "Gambit appears in *Deadpool & Wolverine*",
   never "Gambit appears *only* in…". A claim asserting an absence is contradicted by every new
   fact, so a correctly-working agent routes it to `conflicting` forever. Rephrasing two
   benchmark claims from closed- to open-world moved every model from 50% to >=88%.
2. **`kind` is load-bearing, not decoration.** A `link` claim is verified by resolving a
   redirect, a `prose` claim by comparing text, a `list_member` claim by checking a list.
   Modelling all three as prose is what makes the `[[Void]]` case unimplementable
   (`seed-plan.md` §6).
3. **Only claims the outside world could settle.** The wave vocabulary is about *external*
   events — another film ships, a casting lands — so a claim about the page's own prose style,
   or about in-universe trivia no source reports, is one Research can never resolve and that
   will decay to the ceiling unanswered.

The stage writes nothing itself. It returns proposals; `store_proposals` is what turns the ones
that survive verification into `Claim` records, and it is deliberately the only place a claim
is created — schedules come from `Claim.seeded`, never from the model (`AGENTS.md` §2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from ..core.ledger import Claim, ClaimKind, Wave
from ..core.ledger.baseline import SectionBaseline
from ..core.ledger.store import ClaimStore
from ..core.profile import WikiProfile
from .model import ModelError, ModelRequest, ModelSource

__all__ = [
    "MAX_PER_PAGE", "MAX_PER_SECTION", "RESPONSE_SCHEMA", "SYSTEM", "ModelRequest", "Proposal",
    "Proposer", "Rejected", "room_left", "store_proposals", "verify", "worth_reading",
]

#: What one *section* may contribute. Named honestly after a live run made the distinction
#: expensive: this was called `MAX_PER_PAGE` and enforced here, inside a per-section call, so
#: Gambit's 19 readable sections produced **50 claims** rather than 6 (measured Sept 1, 2026).
MAX_PER_SECTION = 4

#: What a whole page may contribute, enforced across its sections in `store_proposals`. This is
#: the number that matters: every claim costs one Parallel search on every tick, forever, so a
#: page that proposes 50 claims makes a single tick cost 50 searches by itself. Bounded autonomy
#: is the rule the whole design rests on (`summary.md` §6), and the per-section cap alone does
#: not bound anything — a long page just has more sections.
MAX_PER_PAGE = 12

#: Sections whose content is never a claim about the world. Matched case-insensitively against
#: the heading. These hold citations, galleries and navigation — a "claim" drawn from them is
#: about the page's own machinery, and Research has nothing to ask about it.
SKIP_HEADINGS = frozenset({
    "references", "external links", "gallery", "navigation", "see also", "notes",
})

SYSTEM = """\
You read one section of a wiki page and list the factual claims it asserts, so that an agent can
re-check each one against the world later.

A CLAIM is one atomic statement of fact that the section makes, which a source outside the wiki
could confirm or contradict.

For each claim, return:
  text     — the assertion in one sentence, in your own words, self-contained.
  anchor   — the EXACT substring of the SECTION this claim rests on, copied character for
             character from the text you were given. It must appear in the section verbatim and
             exactly once. Copy the shortest span that carries the claim: one infobox line, one
             sentence, one list entry. DO NOT paraphrase, normalise whitespace, fix typos, or
             expand templates. If you cannot copy a span exactly, omit the claim.
  kind     — `link` if the claim is about what a [[wikilink]] points at; `list_member` if it is
             about something being an entry in a list; otherwise `prose`.
  wave     — how fast this kind of fact moves: `settled` (release dates, directors, credits —
             fixed once shipped), `in_universe_slow` (character fates, relationships — moves
             only when a later installment retcons it), `release_driven` (cross-references and
             variant identities — re-tested when a new film ships), `announcement_driven`
             (casting and future appearances — trade press, moves constantly).
  objective — the question a researcher should ask to re-check this claim, self-contained
             enough to read alone.

RULES:

1. PHRASE EVERY CLAIM AS A POSITIVE ASSERTION. Write "Gambit appears in Deadpool & Wolverine",
   never "Gambit appears only in Deadpool & Wolverine" and never "Gambit does not appear in X".
   A claim that asserts an absence or an exclusivity is contradicted by every new fact that
   turns up, which makes it useless to re-check.

2. ONLY CLAIMS THE OUTSIDE WORLD COULD SETTLE. A trade publication, a studio announcement or a
   credits list must be able to bear on it. Skip anything that is purely about how the page is
   written, purely in-universe narrative summary no source reports on, or a matter of opinion.

3. ATOMIC. One assertion per claim. A sentence naming three cast members is three claims, each
   with its own anchor, unless one span genuinely carries all three.

4. FEWER AND CERTAIN beats more and approximate. Returning two solid claims is better than six
   where four have anchors you had to guess at. Return an empty list if the section asserts
   nothing checkable.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "anchor": {"type": "string"},
                    "kind": {"type": "string", "enum": [k.value for k in ClaimKind]},
                    "wave": {"type": "string", "enum": [w.value for w in Wave]},
                    "objective": {"type": "string"},
                },
                "required": ["text", "anchor", "kind", "wave", "objective"],
            },
        },
    },
    "required": ["claims"],
}


@dataclass(frozen=True, slots=True)
class Proposal:
    """One claim a page might support, before anything has checked its anchor."""

    text: str
    anchor: str
    kind: str
    wave: str
    objective: str
    section_index: int
    section_heading: str


@dataclass(frozen=True, slots=True)
class Rejected:
    """A proposal that did not survive verification, and why.

    Kept rather than discarded silently: a stage that quietly drops half its output looks
    identical to a page that had nothing to say, and the difference matters when tuning the
    prompt.
    """

    text: str
    anchor: str
    reason: str


def verify(proposal: Proposal, section_text: str) -> str:
    """Why this proposal cannot be stored, or `""` if it can.

    The anchor is the whole check. It has to be present — a paraphrase is an edit that can
    never apply — and unique, because `write_anchor` refuses an ambiguous substitution rather
    than guessing which occurrence was meant, so a claim anchored on a repeated string is one
    whose edit is refused at publish time, hours after anyone could act on it.
    """
    if not proposal.anchor.strip():
        return "empty anchor"
    if not proposal.text.strip():
        return "empty claim text"
    occurrences = section_text.count(proposal.anchor)
    if occurrences == 0:
        return "anchor is not in the section verbatim"
    if occurrences > 1:
        return f"anchor appears {occurrences} times; an edit could not tell them apart"
    return ""


@dataclass(frozen=True, slots=True)
class Proposer:
    """One wiki's propose stage. The profile is bound, as on every stage: the model reads, the
    deployment decides whose page it is reading."""

    profile: WikiProfile
    source: ModelSource

    def prompt(self, page: str, section: SectionBaseline) -> str:
        """The filled prompt. Public so a test can assert on it and a run can record it."""
        entity = self.profile.entity_ref(page)
        subject = entity.title
        variant = (
            f"{subject} is a VARIANT of {entity.base}; they are different subjects."
            if entity.is_variant
            else f"{subject} is a prime subject, not a variant of anything."
        )
        heading = section.section_heading or "(lead section)"
        return (
            f"PAGE: {page}\n"
            f"SUBJECT: {subject}\n"
            f"{variant}\n\n"
            f"SECTION: {heading}\n"
            f"---\n{section.text}\n---\n"
        )

    def propose(self, page: str, section: SectionBaseline) -> tuple[Proposal, ...]:
        """What this section asserts, unverified.

        Raises `ModelError` on a malformed answer rather than returning nothing: an empty list
        is a real finding — the section asserts nothing checkable — and a parse failure must
        not be able to impersonate it.
        """
        request = ModelRequest(
            system=SYSTEM, prompt=self.prompt(page, section), schema=RESPONSE_SCHEMA
        )
        raw = self.source.run(request)
        try:
            answer = json.loads(raw)
            entries = answer["claims"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ModelError(f"propose: unreadable answer ({exc}): {raw[:200]}") from exc

        proposals = []
        for entry in entries[:MAX_PER_SECTION]:
            try:
                proposals.append(
                    Proposal(
                        text=str(entry["text"]),
                        anchor=str(entry["anchor"]),
                        kind=str(entry["kind"]),
                        wave=str(entry["wave"]),
                        objective=str(entry.get("objective", "")),
                        section_index=section.section_index,
                        section_heading=section.section_heading,
                    )
                )
            except (KeyError, TypeError) as exc:
                raise ModelError(f"propose: a claim is missing {exc}") from exc
        return tuple(proposals)


def store_proposals(
    proposals: tuple[Proposal, ...],
    *,
    page: str,
    section_text: str,
    profile: WikiProfile,
    store: ClaimStore,
    now: datetime,
    task_id: str = "",
) -> tuple[tuple[Claim, ...], tuple[Rejected, ...]]:
    """Turn verified proposals into tracked claims. The only place a claim is created.

    Three things happen here and nowhere else, and each is a rule rather than a convenience:

    * **The anchor is verified against the section** before anything is stored (`verify`).
    * **A claim already tracked at this anchor is left alone.** Recognising an existing claim is
      an exact `(page, anchor)` lookup, never a similarity test — deciding two wordings mean the
      same claim is a judgement, and a loose match would merge two real claims into one record.
      Re-proposing is therefore free and idempotent, which is what lets this run every tick.
    * **The schedule comes from `Claim.seeded`**, off the wave, never from the model. The model
      picks how fast a fact moves; `decay.py` decides what that costs (`AGENTS.md` §2). It is
      then pulled **due immediately**, and that is not a shortcut: `seeded` schedules a claim
      as though it had just been confirmed, which is true of one the ledger has re-checked and
      false of one just read off a page. A newly proposed claim has `research_rounds=0` and
      `last_verified=None` — nobody has ever asked the world about it, and the page asserting
      something is not evidence that it is still true. Waiting 45 days to find out would mean a
      cold start produces a ledger and then does nothing with it. The interval itself is
      untouched, so the ladder starts from the wave's own seed the moment the first round
      settles.
    """
    tracked = store.for_page(page)
    existing = {claim.wikitext_anchor for claim in tracked}
    budget = MAX_PER_PAGE - len(tracked)
    kept: list[Claim] = []
    rejected: list[Rejected] = []

    for proposal in proposals:
        if budget <= 0:
            rejected.append(
                Rejected(proposal.text, proposal.anchor,
                         f"page is at its cap of {MAX_PER_PAGE} claims")
            )
            continue
        problem = verify(proposal, section_text)
        if problem:
            rejected.append(Rejected(proposal.text, proposal.anchor, problem))
            continue
        if proposal.anchor in existing:
            rejected.append(Rejected(proposal.text, proposal.anchor, "already tracked"))
            continue
        try:
            kind, wave = ClaimKind(proposal.kind), Wave(proposal.wave)
        except ValueError as exc:
            rejected.append(Rejected(proposal.text, proposal.anchor, str(exc)))
            continue

        claim = Claim(
            claim_id=store.next_claim_id(),
            page=page,
            entity_ref=profile.entity_ref(page),
            kind=kind,
            wave=wave,
            text=proposal.text,
            wikitext_anchor=proposal.anchor,
            section_index=proposal.section_index,
            section_heading=proposal.section_heading,
            objective=proposal.objective,
            task_id=task_id,
        ).seeded(now)
        claim = replace(claim, next_check_at=now)
        store.put(claim)
        existing.add(claim.wikitext_anchor)
        budget -= 1
        kept.append(claim)

    return tuple(kept), tuple(rejected)


def room_left(store: ClaimStore, page: str) -> int:
    """How many more claims this page may contribute.

    Callers check this **before** asking the model, not after. `store_proposals` enforces the
    cap either way, but enforcing it only there means every section past the one that filled
    the page still costs a call whose every answer is thrown away — measured Sept 1, 2026 on
    Gambit: 17 sections, a cap of 12, and roughly 13 wasted calls per pass. Model calls arrive
    in a burst and a burst is what a rate limit punishes, so the cheapest call is the one not
    made.
    """
    return max(0, MAX_PER_PAGE - len(store.for_page(page)))


def worth_reading(section: SectionBaseline) -> bool:
    """Whether a section can carry a claim at all.

    References, galleries and navigation hold the page's own machinery rather than statements
    about the world, and an empty section holds nothing. Skipping them here is cheaper than
    asking a model to decide it, and it is deterministic — a section's heading is not a
    judgement call.
    """
    heading = (section.section_heading or "").strip().lower()
    return bool(section.text.strip()) and heading not in SKIP_HEADINGS
