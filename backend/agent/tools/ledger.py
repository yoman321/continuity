"""The ledger tool — how a graph node reads and writes the agent's own memory.

The other three tools are how the agent sees the world. This one is how it sees *itself*
across runs: what it already claims to know, what is due for a re-check, and what a previous
run concluded. Without it the graph is a prompt chain that re-reads a page it has never heard
of; with it, the same page comes back with a history attached.

**The model reports findings; the core decides what they mean.** That split is the whole
design here, and it is why this is not a passthrough over `ClaimStore`. A store `put` takes a
whole claim, so a model-facing `put` would let the model write `next_check_at`,
`check_interval` and `confidence` directly — the three fields the deterministic core exists to
compute. A model could then schedule a claim for never, or assert 0.95 behind one blog post,
and every number the demo rests on would be model output wearing the ladder's clothes. So the
write side takes an *outcome* — `unchanged`, `changed`, `unresolved` — and calls the matching
transition on the stored record. The interval doubles or halves because `decay.py` says so
(`AGENTS.md` §2), never because a node asked for it.

Three outcomes, not four, because the record only distinguishes what a reviewer must act on.
"Budget spent and nothing found" is `unchanged`: no new data is no change, and the absence is
already legible — that round added no sources. A rejected draft is `unchanged` too, for the
same reason. The claim's own `status` answers one question and only one: does a human need to
look at this.

Three things follow from the same rule:

* **Source tiers are looked up here, never accepted.** `record_research` takes urls and
  excerpts and resolves the tier against the profile's table, so a model cannot promote its
  own citation. This is the second reason the tool binds a profile.
* **A claim id is allocated, not derived and not invented.** The audit stage re-reads the same
  eight pages every cycle, so re-proposing a tracked claim has to be a no-op — but a model-chosen
  id is phrased differently each time, and an id *derived* from the claim's content changes when
  the content does, which applying an edit guarantees. Both duplicate the record. So the store
  hands out a counter (`next_claim_id`), identity never moves once assigned, and recognising an
  existing claim is a lookup: `for_page` plus an exact anchor match.
* **Scheduling happens on the way in.** `track_claim` calls `Claim.seeded` before storing,
  which is what satisfies the store's "a persisted claim always has a wake time" contract
  (`core/ledger/store.py`) rather than making every caller remember it.

Reads are compact on purpose: `_view` omits source excerpts, which are the largest thing in a
claim and are already in the model's context from the search that produced them.

Every call returns the claim's own view, so a write reports what the record now *is* rather
than only that it succeeded. What the call did is under `result`, not `status`: `status` is the
claim's, it means `verified` or `unresolved`, and it is the name the ledger view and the
stored document already use. Two meanings of one key is how a node ends up branching on the
wrong one.

Imports no ADK: the graph wraps these methods in `FunctionTool` where it is constructed
(`AGENTS.md` §7), so this stays testable with nothing installed. Which store is behind it is
the deployment's choice — `in_memory` makes the whole graph runnable with no database, and the
Firestore adapter lands behind the same protocol without a node noticing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...core.ledger import (
    DEFAULT_LEDGER_PATH,
    MAX_RESEARCH_ROUNDS,
    Claim,
    ClaimKind,
    ClaimStore,
    Contradiction,
    InMemoryClaimStore,
    JsonFileClaimStore,
    Source,
    Wave,
)
from ...core.profile import WikiProfile

#: How many due claims one call returns. A cycle processes what it can; the rest stay due and
#: come back next tick, which is what makes an interrupted run harmless.
DEFAULT_DUE_LIMIT = 25

#: The transitions a node may ask for, by the name it uses. Every one of them reschedules the
#: claim through `decay.py`; none of them lets the caller say by how much. A rejected draft and
#: an exhausted research budget are both `unchanged` — see the module docstring.
OUTCOMES = ("unchanged", "changed", "unresolved")


def utcnow() -> datetime:
    """The clock, in one place so tests can replace it. Every instant the ledger stores is
    UTC and aware — `next_check_at` raises on a naive one."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Ledger:
    """Claim state for one wiki, under one profile's rules.

    The profile is bound here for the same reason it is in the other three tools — the model
    picks which claim, the deployment picks which wiki and whose source table scores it. The
    store is bound for the reason that makes the local-first split pay off: swapping
    `JsonFileClaimStore` for the Firestore adapter changes nothing above this line.
    """

    profile: WikiProfile
    store: ClaimStore
    clock: Callable[[], datetime] = field(default=utcnow)

    @classmethod
    def local(
        cls,
        profile: WikiProfile,
        path: Path | str = DEFAULT_LEDGER_PATH,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> Ledger:
        """The local database: one JSON file holding the documents Firestore will hold."""
        return cls(profile, JsonFileClaimStore(path), clock)

    @classmethod
    def in_memory(
        cls,
        profile: WikiProfile,
        claims: Iterable[Claim] = (),
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> Ledger:
        """The deterministic path: no file, no database, no cloud project. What the graph is
        tested against, the way `SnapshotPageSource` is for reads."""
        return cls(profile, InMemoryClaimStore(claims), clock)

    # -- the tools ----------------------------------------------------------------------

    def due_claims(self, limit: int = DEFAULT_DUE_LIMIT) -> dict[str, Any]:
        """Claims whose scheduled re-check has come due, soonest first.

        This is where a run starts. Each entry carries what the claim asserts, where on the
        page it lives, and what the last round concluded — enough to decide what to research
        without reading anything else first.

        Args:
          limit: how many to return. The rest stay due and come back on the next tick.
        """
        now = self.clock()
        due = self.store.due(now, limit=max(1, limit))
        return {
            "wiki": self.profile.name,
            "now": now.isoformat(),
            "count": len(due),
            "claims": [self._view(claim) for claim in due],
        }

    def read_claim(self, claim_id: str) -> dict[str, Any]:
        """One claim by id, including what it implicates elsewhere.

        Use it to follow `ripple_targets` — a claim that changed on one page names the claims
        on other pages that a previous run found to depend on it.

        Args:
          claim_id: the id as returned by `due_claims` or `track_claim`.
        """
        claim = self.store.get(claim_id)
        if claim is None:
            return {"error": f"no claim {claim_id!r} in the ledger", "claim_id": claim_id}
        return self._view(claim)

    def track_claim(
        self,
        page: str,
        text: str,
        wikitext_anchor: str,
        section_heading: str,
        section_index: int,
        kind: str,
        wave: str,
    ) -> dict[str, Any]:
        """Start tracking one atomic claim found on a page. This is the audit stage's output.

        Phrase `text` as a positive assertion about what the page says — "Gambit appears in
        Deadpool & Wolverine", never "Gambit appears *only* in Deadpool & Wolverine". A
        closed-world claim is contradicted by every new fact and generates false alarms
        forever (`AGENTS.md` §7).

        Proposing a claim that is already tracked is safe and changes nothing: a claim is
        recognised by its page and anchor, so the existing record comes back instead.

        Args:
          page: resolved page title, as `read_page_outline` returned it.
          text: the assertion, in one sentence, phrased positively.
          wikitext_anchor: the exact substring of the section's wikitext this claim rests on,
            copied verbatim — it is what a later edit patches.
          section_heading: heading the anchor sits under, without the `==` markers.
          section_index: that section's index, from the same read.
          kind: one of `prose`, `link`, `list_member`.
          wave: how fast this kind of fact moves — one of `settled`, `in_universe_slow`,
            `release_driven`, `announcement_driven`. It seeds the first recheck interval only;
            after one run the ledger's own history drives the schedule.
        """
        try:
            claim_kind = ClaimKind(kind)
        except ValueError:
            return _invalid("kind", kind, [k.value for k in ClaimKind])
        try:
            claim_wave = Wave(wave)
        except ValueError:
            return _invalid("wave", wave, [w.value for w in Wave])

        existing = self._at_anchor(page, wikitext_anchor)
        if existing is not None:
            return {**self._view(existing), "result": "already_tracked"}

        claim = Claim(
            claim_id=self.store.next_claim_id(),
            page=page,
            entity_ref=self.profile.entity_ref(page),
            kind=claim_kind,
            wave=claim_wave,
            text=text,
            wikitext_anchor=wikitext_anchor,
            section_index=section_index,
            section_heading=section_heading,
        ).seeded(self.clock())
        self.store.put(claim)
        return {**self._view(claim), "result": "tracked"}

    def record_research(
        self, claim_id: str, objective: str, sources: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Attach one round of evidence to a claim, and spend one round of its budget.

        Call this with what a search returned, whether or not it settled anything — a round
        that found nothing still counts, which is what stops the agent searching forever.

        **Do not call it for a search that failed.** A search that errored — no key, a quota,
        a timeout that exhausted its retries — established nothing about the world, so it is
        discarded rather than recorded: the claim keeps its schedule and its budget and comes
        due again. `sources_in` raises on an errored payload so this cannot be reached by
        accident. A search that *ran* and found nothing is the opposite case and belongs here.
        Confidence is recomputed from the tiers of the distinct publishers behind the claim;
        it is not something to pass in, and a second article from a domain already cited does
        not raise it.

        Args:
          claim_id: the claim the evidence is about.
          objective: the question this round was pursuing, self-contained enough to read alone.
            Stored, because a later run needs to know what was being asked, not just that it
            failed.
          sources: one entry per source worth keeping, each `{"url": ..., "excerpt": ...}`
            with an optional `"published": "YYYY-MM-DD"`. Tier and publisher are resolved
            here from the wiki's own source table, so they are not yours to send.
        """
        claim = self.store.get(claim_id)
        if claim is None:
            return {"error": f"no claim {claim_id!r} in the ledger", "claim_id": claim_id}

        retrieved_at = self.clock()
        try:
            records = tuple(
                Source.create(
                    url=str(entry["url"]),
                    excerpt=str(entry.get("excerpt", "")),
                    retrieved_at=retrieved_at,
                    as_of=_as_of(entry.get("published")),
                    domain_tiers=self.profile.domain_tiers,
                )
                for entry in sources
            )
        except (KeyError, TypeError):
            return {
                "error": "each source needs a 'url'; 'excerpt' and 'published' are optional",
                "claim_id": claim_id,
            }

        researched = claim.researched(objective, records)
        self.store.put(researched)
        return {**self._view(researched), "result": "recorded"}

    def record_outcome(
        self,
        claim_id: str,
        outcome: str,
        note: str = "",
        source_a: str = "",
        source_b: str = "",
    ) -> dict[str, Any]:
        """Record what the evidence said about a claim, and let it reschedule itself.

        The recheck interval is computed from this, so the outcome is the whole decision:
        `unchanged` doubles the interval, `changed` halves it and hands the claim to the draft
        stage, and both are clamped to [6h, 6mo]. Choose `unresolved` over guessing when
        sources genuinely disagree — declining to pick is the intended behaviour, not a
        failure, and the disagreement is kept for the reviewer to see. If three rounds of
        research turned up nothing either way, that is `unchanged`: no new data is no change.

        Args:
          claim_id: the claim being resolved.
          outcome: one of `unchanged` (the page stands — retrieval confirmed it, or found
            nothing new, or a reviewer rejected the drafted edit), `changed` (no longer correct,
            so an edit goes to the reviewer), `unresolved` (sources conflict and you are not
            picking).
          note: for `unresolved` only — what the disagreement is, in one sentence.
          source_a: for `unresolved` only — url of one side.
          source_b: for `unresolved` only — url of the other.
        """
        claim = self.store.get(claim_id)
        if claim is None:
            return {"error": f"no claim {claim_id!r} in the ledger", "claim_id": claim_id}
        if outcome not in OUTCOMES:
            return _invalid("outcome", outcome, list(OUTCOMES))

        now = self.clock()
        if outcome == "unresolved":
            if not (note and source_a and source_b):
                return {
                    "error": (
                        "unresolved needs note, source_a and source_b: a conflict recorded "
                        "without both sides is not reviewable"
                    ),
                    "claim_id": claim_id,
                }
            resolved = claim.unresolved(
                now, Contradiction(note=note, source_a=source_a, source_b=source_b)
            )
        elif outcome == "unchanged":
            resolved = claim.unchanged(now)
        else:
            resolved = claim.changed(now)

        self.store.put(resolved)
        return {**self._view(resolved), "result": "recorded"}

    def link_ripple_targets(
        self, claim_id: str, target_claim_ids: list[str]
    ) -> dict[str, Any]:
        """Record that this claim implicates claims on other pages — the fan-out stage's memo.

        Stored so the next run starts already knowing where a change spreads, instead of
        rediscovering it. Targets that are not tracked yet are kept and reported: the page
        holding them may simply not have been audited.

        Fan-out runs after the publish gate (`AGENTS.md` §7), so the edge recorded here is one
        the *applied* revision implies — not one a draft proposed and a reviewer then rejected
        or softened.

        Args:
          claim_id: the claim whose edit was published.
          target_claim_ids: ids of claims this one implicates. The claim's own id is ignored,
            and repeats collapse.
        """
        claim = self.store.get(claim_id)
        if claim is None:
            return {"error": f"no claim {claim_id!r} in the ledger", "claim_id": claim_id}

        merged = dict.fromkeys((*claim.ripple_targets, *target_claim_ids))
        merged.pop(claim_id, None)
        linked = replace(claim, ripple_targets=tuple(merged))
        self.store.put(linked)
        return {
            **self._view(linked),
            "result": "linked",
            "untracked": [t for t in linked.ripple_targets if self.store.get(t) is None],
        }

    # -- shared -------------------------------------------------------------------------

    def _at_anchor(self, page: str, wikitext_anchor: str) -> Claim | None:
        """The claim already tracked at this spot on this page, if there is one.

        Exact string match, not a similarity test. Matching loosely is how two genuinely
        different claims about one sentence get collapsed into one record, and deciding that two
        wordings mean the same thing is a judgement — it belongs to the audit stage's model, not
        to a lookup.
        """
        for claim in self.store.for_page(page):
            if claim.wikitext_anchor == wikitext_anchor:
                return claim
        return None

    def _view(self, claim: Claim) -> dict[str, Any]:
        """One claim as a node sees it: everything a decision needs, and no excerpts.

        The derived flags are recomputed from the record rather than read out of it — a stored
        derivation is how a ledger comes back disagreeing with itself — and they are here
        because they are what the graph's edges branch on: `budget_spent` gates the retry, and
        `auto_appliable` gates whether an edit may even be proposed without review.
        """
        return {
            "claim_id": claim.claim_id,
            "page": claim.page,
            "entity": {
                "title": claim.entity_ref.title,
                "base": claim.entity_ref.base,
                "variant": claim.entity_ref.variant,
                "is_variant": claim.entity_ref.is_variant,
            },
            "kind": claim.kind.value,
            "wave": claim.wave.value,
            "status": claim.status.value,
            "text": claim.text,
            "wikitext_anchor": claim.wikitext_anchor,
            "section_index": claim.section_index,
            "section_heading": claim.section_heading,
            "confidence": claim.confidence,
            "objective": claim.objective,
            "research_rounds": claim.research_rounds,
            "rounds_remaining": max(0, MAX_RESEARCH_ROUNDS - claim.research_rounds),
            "budget_spent": claim.budget_spent,
            "auto_appliable": claim.auto_appliable,
            "is_contradicted": claim.is_contradicted,
            # Publisher and tier, no excerpt: the text is already in context from the search
            # that produced it, and a due-claims call that carried it would be the largest
            # payload in the run.
            "sources": [
                {
                    "url": source.url,
                    "domain": source.domain,
                    "tier": source.tier,
                    "as_of": _iso(source.as_of),
                }
                for source in claim.sources
            ],
            "contradicts": [
                {"note": c.note, "source_a": c.source_a, "source_b": c.source_b}
                for c in claim.contradicts
            ],
            "ripple_targets": list(claim.ripple_targets),
            "last_verified": _iso(claim.last_verified),
            "next_check_at": _iso(claim.next_check_at),
            # Hours rather than seconds because the ladder is stated in hours and days
            # (`AGENTS.md` §2), and this number is read on camera.
            "check_interval_hours": claim.check_interval.total_seconds() / 3600,
        }


# -- helpers ----------------------------------------------------------------------------


def _invalid(name: str, given: str, allowed: list[str]) -> dict[str, Any]:
    """A rejected enum, as a value. Listing what is accepted lets the caller correct itself in
    one turn, the same way a missing section returns the headings that do exist."""
    return {"error": f"unknown {name} {given!r}", "allowed": allowed}


def _as_of(published: Any) -> datetime | None:
    """`YYYY-MM-DD` -> UTC midnight. An absent or malformed date is unknown, not an error: the
    publisher's own date is optional and the search's `after_date` is the reliable filter."""
    if not published:
        return None
    try:
        return datetime.strptime(str(published), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
