"""The claim ledger — one record per atomic claim, and the agent's whole memory.

Field set derived in `seed-plan.md` §6; the ledger's role in the 6-stage flow is
`summary.md` §6. This is what makes the system stateful rather than a prompt chain, and what
lets it answer "have I already checked this?"

Pure data and pure transitions. No Firestore, no network, no model calls — persistence is an
adapter at the perimeter (`CLAUDE.md` §3). Records are frozen; every transition returns a new
one, so a run's history is a list of values rather than a mutated object.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum

from . import tiers
from .decay import Wave, next_check_at, next_interval, seed_interval

# `summary.md` §6 guardrail. A claim the agent cannot settle in three rounds is not one more
# search away from settling; it is unresolved, and saying so is the desired behaviour.
MAX_RESEARCH_ROUNDS = 3


class ClaimKind(str, Enum):
    """What kind of thing the claim asserts.

    Forced by the revised claim set (`seed-plan.md` §6). These verify and patch differently,
    and modelling all three as free text makes the link claim unimplementable.
    """

    PROSE = "prose"  # a value asserted in a sentence; verify by comparing normalised values
    LINK = "link"  # a wikilink target; verify by resolving redirects, not by string compare
    LIST_MEMBER = "list_member"  # membership in a list; verify by presence/absence


class ClaimStatus(str, Enum):
    """Whether a human has to look at this claim. Two answers, and deliberately no more.

    Six values were tried first — `stale`, `drafted`, `applied` and `exhausted` alongside
    these two — and they conflated three different questions: what the agent concluded, where
    an edit is in the publish pipeline, and whether the data is old. Only the first belongs on
    the record. Where an edit sits is the *queue's* state, not the claim's, and age is not a
    state at all: it is `next_check_at` compared to the clock (`is_due`).
    """

    VERIFIED = "verified"  # checked; the page stands, nothing for a reviewer to do
    UNRESOLVED = "unresolved"  # a human decides: an edit at the gate, or sources that conflict


@dataclass(frozen=True, slots=True)
class EntityRef:
    """Which subject a claim is about.

    MCU Wiki puts film-specific character variants on subpages, so `Human Torch` and
    `Human Torch/Void-Analyzing Fantastic Four` are different subjects with different claims.
    Research about one is evidence about the other only sometimes. Without this distinction
    the agent's likeliest failure is a confident, well-cited, wrong edit (`seed-plan.md` §4.3).
    """

    title: str
    base: str
    variant: str | None = None

    @property
    def is_variant(self) -> bool:
        return self.variant is not None

    @classmethod
    def from_title(cls, title: str, *, subpages: bool) -> EntityRef:
        """Parse `title` under a wiki's subpage grammar.

        `subpages` is required and has no default on purpose. It is a real MediaWiki setting
        (`$wgNamespacesWithSubpages`, reported by `siprop=namespaces`), and it differs: Fandom
        enables mainspace subpages, Wikipedia disables them. Guess wrong with a default and
        `AC/DC` — one 202KB article — becomes a variant named `DC` of a subject named `AC`,
        silently, with no error anywhere downstream. Prefer `WikiProfile.entity_ref`.
        """
        if not subpages:
            return cls(title=title, base=title, variant=None)
        base, sep, variant = title.partition("/")
        return cls(title=title, base=base, variant=variant if sep else None)


@dataclass(frozen=True, slots=True)
class Source:
    """One retrieved citation. `tier` is assigned by lookup, never by the model."""

    url: str
    excerpt: str
    retrieved_at: datetime
    as_of: datetime | None = None  # publication date, for recency-based adjudication
    tier: int = field(default=tiers.UNKNOWN_TIER)

    # Resolved once at creation, against the profile's table, and stored. Deriving it later
    # would need the table again, and `Claim.recompute_confidence` must not have to carry a
    # profile to count publishers.
    domain: str = ""

    @classmethod
    def create(cls, url: str, excerpt: str, retrieved_at: datetime,
               as_of: datetime | None = None, *,
               domain_tiers: Mapping[str, int]) -> Source:
        """Build a source with its tier looked up, never passed in and never model-assigned."""
        return cls(url=url, excerpt=excerpt, retrieved_at=retrieved_at, as_of=as_of,
                   tier=tiers.tier_for(url, domain_tiers),
                   domain=tiers.registrable_domain(url, domain_tiers))


@dataclass(frozen=True, slots=True)
class Contradiction:
    """Two sources the agent could not reconcile. Kept rather than collapsed — the honest
    flag is the deliverable (`summary.md` §5)."""

    note: str
    source_a: str
    source_b: str


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str
    page: str  # resolved title; pass redirects=1 before storing (`AGENTS.md` §6)
    entity_ref: EntityRef
    kind: ClaimKind
    wave: Wave

    text: str  # the assertion, phrased positively — never closed-world (AGENTS.md §7)
    wikitext_anchor: str  # exact substring to patch, so edits stay surgical

    # MediaWiki addresses sections by index, but indices shift when a section is added above.
    # Store the heading too and re-resolve the index before every write.
    section_index: int
    section_heading: str

    status: ClaimStatus = ClaimStatus.VERIFIED
    confidence: float = 0.0
    sources: tuple[Source, ...] = ()
    contradicts: tuple[Contradiction, ...] = ()

    # The semantic objective last sent to Parallel. Persisted because the revisit queue needs
    # to know what was being pursued, not just that it failed (`summary.md` §7).
    objective: str = ""
    research_rounds: int = 0

    ripple_targets: tuple[str, ...] = ()  # claim_ids on other pages this one implicates

    last_verified: datetime | None = None
    next_check_at: datetime | None = None
    check_interval: timedelta = timedelta(0)

    # The task that last wrote this claim (`documents.task_id_for`). Provenance and nothing
    # else: no transition reads it, and it is empty on a claim no task has touched. Carried
    # through every transition by `replace`, so the last writer is what it names.
    task_id: str = ""

    # -- derived -----------------------------------------------------------------

    @property
    def is_contradicted(self) -> bool:
        return bool(self.contradicts)

    @property
    def auto_appliable(self) -> bool:
        """Whether this may be applied without a human decision.

        Dry-run is the default and the publish gate is a judging criterion, so this only ever
        gates the *proposal*; it never bypasses the gate itself (`summary.md` §6). Every
        candidate is `UNRESOLVED` by definition — a verified claim has no edit to apply — and
        the contradicted ones are exactly the ones a reviewer must see.
        """
        return (
            self.confidence >= tiers.AUTO_APPLY_THRESHOLD
            and not self.is_contradicted
            and self.status is ClaimStatus.UNRESOLVED
        )

    @property
    def budget_spent(self) -> bool:
        return self.research_rounds >= MAX_RESEARCH_ROUNDS

    def is_due(self, now: datetime) -> bool:
        """Whether the schedule says to check this again — and therefore whether the record is
        stale. Staleness is time against `next_check_at`, never a stored status: a claim goes
        stale because nothing has re-checked it for as long as its own interval allows, and
        one run turns it back into `VERIFIED` or `UNRESOLVED`."""
        return self.next_check_at is None or now >= self.next_check_at

    def recompute_confidence(self) -> float:
        """Confidence from the tiers of distinct source domains. One vote per publisher."""
        by_domain = {s.domain: s.tier for s in self.sources}
        return tiers.confidence_from(list(by_domain.values()), contradicted=self.is_contradicted)

    # -- transitions ---------------------------------------------------------------

    def seeded(self, now: datetime) -> Claim:
        """First scheduling, from the claim's wave. After this the ledger drives itself."""
        interval = seed_interval(self.wave)
        return replace(self, check_interval=interval, next_check_at=next_check_at(now, interval))

    def _rescheduled(self, now: datetime, *, changed: bool) -> Claim:
        interval = next_interval(self.check_interval or seed_interval(self.wave), changed=changed)
        return replace(self, check_interval=interval,
                       next_check_at=next_check_at(now, interval), last_verified=now)

    def researched(self, objective: str, sources: tuple[Source, ...]) -> Claim:
        """Record one research round. Counts against the budget whether or not it helped."""
        merged = self.sources + sources
        candidate = replace(self, objective=objective, sources=merged,
                            research_rounds=self.research_rounds + 1)
        return replace(candidate, confidence=candidate.recompute_confidence())

    def unchanged(self, now: datetime) -> Claim:
        """Still correct. Interval doubles — most claims live here and drift to the ceiling.

        Three outcomes land here, because the record cannot tell them apart and should not
        pretend to: retrieval confirmed the claim, retrieval found nothing new, or a reviewer
        rejected a drafted edit and kept the existing text. All three mean the page stands. The
        difference between "confirmed" and "nothing found" is visible in `sources` — the
        confirmed one gained some — and the cost of treating them alike is in `summary.md` §10.
        """
        return replace(self._rescheduled(now, changed=False),
                       status=ClaimStatus.VERIFIED, research_rounds=0)

    def changed(self, now: datetime) -> Claim:
        """No longer correct. Interval halves, and a human now has to approve the fix, which is
        what `UNRESOLVED` means — the draft stage picks the claim up from here. A conflict and
        a pending edit are the same status on purpose; `is_contradicted` is what tells them
        apart, and it is derived rather than stored."""
        return replace(self._rescheduled(now, changed=True), status=ClaimStatus.UNRESOLVED)

    def unresolved(self, now: datetime, contradiction: Contradiction) -> Claim:
        """Sources conflict and the agent declines to pick. Stays scheduled so it is
        re-attempted when new sources appear — the revisit queue (`summary.md` §7)."""
        candidate = replace(self._rescheduled(now, changed=True),
                            status=ClaimStatus.UNRESOLVED,
                            contradicts=(*self.contradicts, contradiction))
        return replace(candidate, confidence=candidate.recompute_confidence())

