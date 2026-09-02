"""The graph — the stages as ADK nodes, joined, with the one backward edge that matters here.

Six of the eight stages run inside one ADK `Workflow`: Audit hands over what is due, Research
buys evidence, Classify sorts it, Draft writes the edit, Diff reads what the edit did to the
ideas, and Verify puts the result where a person can decide. The seventh and eighth — Publish
and Fan-out — are not nodes in this graph and must not become them: Publish is a button on a
route (`backend/app.py`), and Fan-out only has an *applied* edit to expand once that button has
been pressed (`summary.md` §6).

**The run ends at Verify rather than pausing inside it.** ADK can hold a node open for a human
through `request_input`, and an earlier plan said Verify would. The draft store made that the
wrong shape: Cloud Run scales to zero and the tick is hourly, so a coroutine waiting on a
reviewer is a coroutine that dies at the first idle timeout — while a stored `ReviewDraft`
survives the container, the reload, and the week. So Verify's node writes the draft and the
invocation finishes. The pause is the store, and resuming is `POST /api/drafts/{id}/publish`.

**One backward edge: `Classify → Research`.** It fires on the one signal the classify stage
already produces — a `conflicting` verdict where filtering dropped *every* excerpt, which is
retrieval having gone off-subject rather than the world disagreeing with itself (`classify.py`,
rule 4). A real conflict never routes here; it routes to a person, which is the whole point of
the bucket. The edge is bounded twice over: `Claim.budget_spent` after `MAX_RESEARCH_ROUNDS`,
checked in the Research node because that is where a round is spent, and a retry set that can
only shrink. A claim that exhausts its budget with nothing to judge settles as `unchanged` —
"no new data is no change" (`AGENTS.md` §7) — which also resets its rounds, so the next tick
can research it again rather than finding it permanently out of budget.

**What the nodes are, and what they are not.** Each stage is an ordinary method returning a
plain dict, so the whole pipeline is runnable and testable with no ADK installed; `build()`
wraps those methods as nodes and is the only thing here that imports the SDK. Same rule as the
tools (`agent/__init__.py`): the logic does not know it is in a graph. The run's typed
intermediates — verdicts, drafts, reviews — live on the `Run` object rather than in
`ctx.state`, because `Draft` is not JSON and a lossy codec between two halves of one run is a
place for them to disagree; what goes into state is each stage's summary, which is what the
event stream is for. The durable artifact is the stored `ReviewDraft`, not the ADK session.

Nothing here writes to the wiki. The only thing this graph produces is a draft waiting at the
gate, which is the invariant the whole publish path rests on (`AGENTS.md` §2).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from ..core.ledger.baseline import BaselineStore
from ..core.ledger.documents import task_id_for
from ..core.ledger.drafts import DraftStore, ReviewDraft
from ..core.ledger.judgements import Judgement, JudgementStore
from ..core.profile import WikiProfile
from ..core.wiki import slug_for
from .classify import Classifier, Verdict
from .draft import DRAFTABLE, Draft, Drafter
from .model import ModelError
from .semantic_diff import Review, Reviewer
from .tools import DEFAULT_DUE_LIMIT, Ledger, WebSearch, utcnow

#: The stages a run visits, in order. Seven and eight are deliberately absent: Publish is a
#: button on a route and Fan-out has nothing to expand until an edit has been applied.
STAGES = ("audit", "research", "classify", "draft", "diff", "verify")

#: Every bucket that carried something the page does not say. `still_true` is the only one that
#: produces no card, because there is nothing to show — the claim's citation is refreshed and
#: its interval doubles. A `conflicting` claim is drafted as an edit that makes the
#: disagreement visible, and the reviewer takes it or discards it (`AGENTS.md` §7).

#: How many results retrieved elsewhere in a run may be offered to one claim on the second
#: classification sweep. A ceiling rather than a judgement: the stage filters off-subject
#: evidence itself, but a prompt is not a corpus.
EVIDENCE_CAP = 10

#: Dropped from a claim's text when building queries: they carry no retrieval signal and eat
#: into the 3-6 words a query should be.
#: Written as prose and split once: one word per line would be forty lines of no information.
_STOPWORD_TEXT = (
    "a an and any are as at be been by does do for from had has have he her his in is it its "
    "no not of on only or she that the their they this to was were which who with"
)
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


@dataclass(frozen=True, slots=True)
class Stages:
    """Everything one run is made of, bound once.

    Every field is a seam with a deterministic implementation behind it — the in-memory ledger,
    the snapshot baseline, the recorded search, the model cassette, the JSON draft store — so
    the whole graph runs with no key, no network and no database (`CLAUDE.md` §3). Swapping any
    one of them for its live counterpart changes nothing above this line.
    """

    profile: WikiProfile
    ledger: Ledger
    baseline: BaselineStore
    search: WebSearch
    classifier: Classifier
    drafter: Drafter
    reviewer: Reviewer
    drafts: DraftStore
    judgements: JudgementStore
    clock: Callable[[], datetime] = utcnow
    limit: int = DEFAULT_DUE_LIMIT


@dataclass(frozen=True, slots=True)
class RunReport:
    """What one run did, in counts rather than prose (`CLAUDE.md` §5).

    `unresolved` and `failed` are the two that need reading: a conflict has no card at the gate
    yet, and a draft the model could not produce is a claim the reviewer will never be shown.
    """

    wiki: str
    task_id: str  # every document this run wrote names it
    started_at: datetime
    due: int
    researched: int
    discarded: int  # searches that errored: the round is discarded, the claim keeps its schedule
    out_of_budget: int  # claims Research refused a further round for
    rounds: int  # Research passes, so >1 means the backward edge fired
    stages: tuple[str, ...]  # the stages this run completed, in order
    buckets: Mapping[str, int]
    #: Claims the second classification sweep moved to a different bucket, on evidence another
    #: claim's search returned. A run that changed its mind and did not say so is unauditable.
    reclassified: tuple[str, ...]
    drafted: int
    failed: tuple[str, ...]  # claim ids the draft stage could not write an edit for
    unresolved: tuple[str, ...]  # claim ids a person must settle; no card carries them yet
    skipped: tuple[str, ...]  # claim ids with no baseline section to read against
    unjudged: tuple[str, ...]  # claims whose classification could not be read back
    draft_id: str  # "" when the run proposed nothing, and then nothing is stored
    changes: int

    @property
    def stored(self) -> bool:
        """Whether a reviewable draft came out of this run."""
        return bool(self.draft_id)


# -- the pure half: what a run asks, and what it calls things ----------------------------


def keywords(text: str, limit: int = 6) -> list[str]:
    """The content words of a claim, in order, deduped. Deterministic so a replay hits."""
    seen: dict[str, None] = {}
    for raw in text.replace("'", " ").replace('"', " ").split():
        word = "".join(c for c in raw if c.isalnum() or c in "-&:").strip("-:&")
        if any(c.isalnum() for c in word) and word.lower() not in STOPWORDS:
            seen.setdefault(word, None)
    return list(seen)[:limit]


def queries_for(claim: Mapping[str, Any], round_: int = 1) -> list[str]:
    """The angles on one claim, all riding a single billable call (`AGENTS.md` §7).

    The subject leads every query because retrieval cannot tell a variant from its prime on
    its own — the same missing information rule 3 of the classify prompt exists to supply. The
    second angle is whatever the claim actually offers: its section, its page when that is a
    different subject, or the rest of its own wording. There is no third for a prime subject
    and that is deliberate — padding a query with words the claim does not contain invents
    retrieval signal, and one call is billed the same for one query as for four. What the retry
    changes for a prime subject is the objective and the date filter, not the keywords.
    """
    entity = claim.get("entity", {})
    subject = str(entity.get("title") or claim.get("page", ""))
    page = str(claim.get("page", ""))
    base = str(entity.get("base") or subject)
    words = [w for w in keywords(str(claim.get("text", ""))) if w.lower() not in subject.lower()]
    heading = str(claim.get("section_heading") or "")

    queries = [f"{subject} {' '.join(words[:3])}"]
    if heading:
        queries.append(f"{subject} {heading}")
    elif page and page != subject:
        queries.append(f"{page} {' '.join(words[:2])}")
    else:
        queries.append(f"{subject} {' '.join(words[3:6])}")
    if round_ > 1 and base != subject:
        queries.append(f"{base} {' '.join(words[:2])}")
    picked: list[str] = []
    for query in dict.fromkeys(" ".join(q.split()) for q in queries):
        # A query that is a prefix of one already picked is the same search, shorter.
        if query and query != subject and not any(q.startswith(query) for q in picked):
            picked.append(query)
    return picked


def objective_for(claim: Mapping[str, Any], round_: int = 1) -> str:
    """The question this round pursues, self-contained enough to read alone.

    Round one uses the objective the ledger holds when there is one — that is what a previous
    round, or the stage that proposed the claim, decided this claim is about. A retry never
    does: re-asking the question that came back empty is the one thing the backward edge exists
    to avoid, so it broadens from the claim instead. `record_research` stores whichever was
    used, so the ledger keeps the history either way.
    """
    entity = claim.get("entity", {})
    subject = str(entity.get("title") or claim.get("page", ""))
    stored = str(claim.get("objective") or "")
    if round_ <= 1 and stored:
        return stored
    ask = f"Is it still true that {str(claim.get('text', '')).rstrip('.')}?"
    if round_ <= 1:
        return f"{ask} The subject is {subject} specifically."
    return (
        f"{ask} Earlier retrieval returned nothing about {subject} itself. Broaden to any "
        f"announcement, casting or later work naming {subject}, under any wording."
    )


def after_date_for(claim: Mapping[str, Any], round_: int = 1) -> str:
    """`YYYY-MM-DD` to filter on, or `""` for no filter.

    The newest date already backing the claim, so a check asks what has happened *since* what
    we hold. Absent on a claim nobody has researched yet, and dropped on a retry — a date
    filter is applied before ranking, so it is the first thing to relax when a batch came back
    empty (`AGENTS.md` §6).
    """
    if round_ > 1:
        return ""
    dates = [str(s.get("as_of") or "")[:10] for s in claim.get("sources", ())]
    return max((d for d in dates if d), default="")


def sources_for(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A search payload as `Ledger.record_research` takes it. Tier and publisher are resolved
    there from the wiki's own table, so they are deliberately not sent."""
    return [
        {
            "url": result["url"],
            "excerpt": " ".join(result.get("excerpts", ())),
            "published": result.get("publish_date"),
        }
        for result in payload.get("results", ())
    ]


def survivors(payload: Mapping[str, Any], verdict: Verdict) -> tuple[str, ...]:
    """Urls the classify stage did *not* drop as off-subject. Empty is the signal the backward
    edge fires on: nothing was left to judge, so the verdict is about retrieval, not the world."""
    dropped = set(verdict.off_entity)
    return tuple(r["url"] for r in payload.get("results", ()) if r["url"] not in dropped)


def edit_id_for(claim_id: str) -> str:
    """One card per claim per run. Stable, so re-running a claim addresses the same card."""
    return f"edit-{claim_id.lower()}"


def draft_id_for(task_id: str) -> str:
    """One draft per run, named for the task that produced it.

    Derived from the task id rather than from the clock a second time: the two would be the
    same string built twice, and a draft whose id disagreed with its own `task_id` is exactly
    the provenance bug the field exists to prevent.
    """
    return f"draft-{task_id.removeprefix('task-')}"


def flags_for(draft: Draft, review: Review | None) -> tuple[str, ...]:
    """What the card warns about: the draft's own arithmetic, then the Diff stage's reading.

    Deduped in that order because `overreached` is raised by both and means the same thing —
    the text one is free, the idea one is the reason the stage exists (`AGENTS.md` §7).
    """
    return tuple(dict.fromkeys(draft.flags + (review.flags if review else ())))


# -- the run ------------------------------------------------------------------------------


@dataclass
class Run:
    """One pass through the graph, and the only mutable thing in this module.

    Held for the length of one invocation. Every method is an ordinary call — no ADK, no
    async — so the pipeline can be driven straight through in a test and the graph is only
    ever the scheduling on top.
    """

    stages: Stages
    started_at: datetime = field(default_factory=utcnow)
    #: Minted at Audit and stamped on every document this run writes — claims, judgements and
    #: the draft alike. Held here rather than on `Stages` because the task *is* the run.
    task_id: str = ""
    rounds: int = 0
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending: tuple[str, ...] = ()
    #: Claims a malformed model answer cost their judgement, with the reason.
    unjudged: list[str] = field(default_factory=list)
    #: Stage names in completion order. The run's own account of where it went,
    #: which is what a graph object used to be inspected for.
    visited: list[str] = field(default_factory=list)
    refused: tuple[str, ...] = ()  # out of budget on *this* pass; settled by the next Classify
    searches: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The latest verdict per claim — including one being held for a retry, which is what the
    #: next round is handed so it can revise rather than start cold.
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    #: Claims whose ledger transition has been written. Settling ends a claim's classification
    #: phase and happens once: a second one would apply the decay ladder twice.
    settled: list[str] = field(default_factory=list)
    #: Of those, the ones settled *on their own verdict* — so they are what Draft works from.
    #: A claim the run overruled (out of budget, nothing to judge) settles without appearing
    #: here, because the bucket it carries is not what the ledger acted on.
    decided: list[str] = field(default_factory=list)
    #: How many times each claim has been classified in this run. The judgement store keys on
    #: it, so a revision and what it revised are two rows rather than one overwriting the other.
    attempts: dict[str, int] = field(default_factory=dict)
    #: Claims the second sweep moved to a different bucket. Reported, because a run that
    #: changed its mind and did not say so is a run nobody can check.
    reclassified: list[str] = field(default_factory=list)
    drafts: dict[str, Draft] = field(default_factory=dict)
    reviews: dict[str, Review] = field(default_factory=dict)
    discarded: list[str] = field(default_factory=list)
    out_of_budget: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    draft_id: str = ""
    #: The task-bound ledger. Replaced in `audit()` once the task id exists; until then it is
    #: the unbound one from `Stages`, so a stage called out of order still has a ledger rather
    #: than an `AttributeError`.
    ledger: Ledger = field(init=False)

    def __post_init__(self) -> None:
        self.ledger = self.stages.ledger

    # -- stage 1 ---------------------------------------------------------------------

    def audit(self) -> dict[str, Any]:
        """What the schedule says is due, and nothing else.

        One clock for the whole run, taken here, so every timestamp the run writes agrees —
        the same rule `ingest_all` follows for a baseline pass.
        """
        self.started_at = self.stages.clock()
        # Minted here unless the caller already has one. A run started from the button proposes
        # its claims *before* Audit and seals the store to that id, so both halves have to agree
        # — a second id here would have Audit reading a scope nothing was written under.
        self.task_id = self.task_id or task_id_for(self.started_at)
        # Bound rather than passed: the ledger stamps what it writes, and a task is no more a
        # model-facing parameter than a profile is (`AGENTS.md` §7).
        self.ledger = replace(self.stages.ledger, task_id=self.task_id)
        due = self.ledger.due_claims(self.stages.limit)
        self.claims = {claim["claim_id"]: claim for claim in due["claims"]}
        self.pending = tuple(self.claims)
        return {"stage": "audit", "wiki": due["wiki"], "task_id": self.task_id,
                "due": len(self.claims), "claims": list(self.pending)}

    # -- stage 2 ---------------------------------------------------------------------

    def research(self) -> dict[str, Any]:
        """One Parallel call per pending claim, and the budget check that bounds the retry.

        Three outcomes per claim, and the difference between the last two is load-bearing
        (`AGENTS.md` §7): a search that ran is recorded even if it found nothing, because a
        round that established nothing still counts; a search that *errored* establishes
        nothing about the world, so the round is discarded whole — no sources, no budget spent,
        no schedule change — and the claim simply comes due again.
        """
        self.rounds += 1
        searched: list[str] = []
        refused: list[str] = []
        for claim_id in self.pending:
            claim = self.claims[claim_id]
            if claim["budget_spent"]:
                # Nothing refuses a fourth round anywhere else: `record_research` spends one
                # without consulting the budget, so this is the check (`summary.md` §6).
                refused.append(claim_id)
                continue
            objective = objective_for(claim, self.rounds)
            payload = self.stages.search.search(
                search_queries=queries_for(claim, self.rounds),
                objective=objective,
                after_date=after_date_for(claim, self.rounds),
            )
            if "error" in payload:
                self.discarded.append(claim_id)
                continue
            self.searches[claim_id] = payload
            self.ledger.record_research(claim_id, objective, sources_for(payload))
            self.claims[claim_id] = self.ledger.read_claim(claim_id)
            searched.append(claim_id)
        self.pending = tuple(searched)
        self.refused = tuple(refused)
        self.out_of_budget.extend(refused)
        return {"stage": "research", "round": self.rounds, "searched": len(searched),
                "discarded": len(self.discarded), "out_of_budget": len(refused)}

    # -- stage 3 ---------------------------------------------------------------------

    def classify(self) -> dict[str, Any]:
        """Sort each researched claim, write the ledger outcome, and decide who retries.

        **Two sweeps, because a run learns things out of order.** The first classifies every
        claim against the evidence its own search returned. The second offers each claim what
        the *rest of the run* turned up about its subject and lets the stage revise itself:
        six claims are six searches, and the excerpt that contradicts one claim is very often
        the one another claim's search went and fetched. Classifying each claim in isolation
        threw that away — the run would hold the contradiction and reach the opposite verdict
        with it sitting in memory. The second sweep costs one model call per claim that
        actually gained evidence, and none for the rest.

        Reclassification is free for as long as a claim is in this phase, and every
        classification is recorded — superseded ones included, because a record of the
        conclusion with no trace of the revision is the half that explains it. What happens
        once is *settling*: the ledger transition reschedules the claim, and that is what ends
        the phase for it.

        The claims that reach the backward edge are the ones where filtering emptied the batch
        and the budget still allows another round. They get no ledger write at all: the round
        is not concluded, so recording an outcome would reschedule a claim mid-decision.
        """
        retry: list[str] = []
        buckets: dict[str, int] = {}
        judged: list[str] = []

        # -- sweep one: each claim against what its own search returned -------------------
        for claim_id in self.pending:
            claim = self.claims[claim_id]
            section = self.section_text(claim["page"], claim["section_index"])
            if section is None:
                # No baseline to read the claim against. Judging it would be judging a claim
                # nobody re-read the page for; run `scripts/ingest_baseline.py` first.
                self.skipped.append(claim_id)
                continue
            try:
                self.judge(claim, section, self.verdicts.get(claim_id))
            except ModelError as exc:
                # One unreadable answer must not cost the other claims their review. The
                # searches behind them are already billed, and a run that aborts here throws
                # away every judgement it had made. Measured Sept 1, 2026: a live run returned
                # `conflicting` with no sides on one claim of twelve and took the whole tick
                # down with it. The claim keeps its schedule and comes due again.
                self.unjudged.append(f"{claim_id}: {exc}")
                continue
            judged.append(claim_id)

        # -- sweep two: and against everything else this run found about its subject -------
        for claim_id in judged:
            claim = self.claims[claim_id]
            elsewhere = self.corroborating(claim_id)
            if not elsewhere:
                continue
            self.searches[claim_id] = {
                **self.searches[claim_id],
                "results": [*self.searches[claim_id].get("results", ()), *elsewhere],
            }
            section = self.section_text(claim["page"], claim["section_index"]) or ""
            before = self.verdicts[claim_id]
            try:
                after = self.judge(claim, section, before)
            except ModelError as exc:
                # Same rule as the first sweep: a bad second answer must not cost the claim the
                # verdict it already has. It keeps `before` and settles on that.
                self.unjudged.append(f"{claim_id}: {exc}")
                continue
            if after.bucket != before.bucket:
                self.reclassified.append(claim_id)

        # -- and only now, what the ledger is told -----------------------------------------
        for claim_id in judged:
            verdict = self.verdicts[claim_id]
            if verdict.is_conflict and not survivors(self.searches[claim_id], verdict):
                if not self.claims[claim_id]["budget_spent"]:
                    # Held, not settled — and kept, so the next round is handed what this one
                    # concluded and can revise it rather than starting cold.
                    retry.append(claim_id)
                    continue
                # Out of rounds with nothing to judge: no new data is no change, which also
                # clears the spent rounds so the next tick may research it again. Recorded,
                # because this is the one case where what the model said and what the ledger
                # did diverge — and a judgement that hid the override would be a record of the
                # decision nobody actually made.
                self.settle(claim_id, "unchanged")
                self.record(self.claims[claim_id], self.verdicts[claim_id], outcome="unchanged")
                continue
            self.settle(claim_id, verdict.outcome, verdict)
            self.decided.append(claim_id)
            buckets[verdict.bucket] = buckets.get(verdict.bucket, 0) + 1

        for claim_id in self.refused:
            # Refused a further round this pass, so nothing new was learned about it: the page
            # stands, and `unchanged` clears the spent rounds for the next tick.
            self.settle(claim_id, "unchanged")
        self.pending = tuple(retry)
        return {"stage": "classify", "classified": len(self.decided), "retry": len(retry),
                "buckets": buckets, "skipped": len(self.skipped),
                "reclassified": len(self.reclassified),
                "judgements": len(self.stages.judgements.for_task(self.task_id))}

    def judge(
        self, claim: dict[str, Any], section: str, previous: Verdict | None
    ) -> Verdict:
        """One classification, kept and recorded. Never settles anything.

        Split out because it happens more than once per claim now, and every occurrence has to
        reach the judgement store — the revision and what it revised are both the record.
        """
        claim_id = str(claim["claim_id"])
        verdict = self.stages.classifier.classify(
            claim, section, self.searches[claim_id], previous
        )
        self.verdicts[claim_id] = verdict
        self.attempts[claim_id] = self.attempts.get(claim_id, 0) + 1
        self.record(claim, verdict)
        return verdict

    def corroborating(self, claim_id: str) -> list[dict[str, Any]]:
        """Results this run retrieved *for other claims* that name this claim's subject.

        The match is a case-insensitive mention of the subject title in a result's title or
        excerpts — deterministic, free, and no second search. It is deliberately generous:
        offering the stage an excerpt that turns out to be irrelevant costs one line of prompt,
        and the stage already has a filtering step whose whole job is dropping off-subject
        evidence (`classify.py`, rule 4). Capped, because a prompt is not a corpus.
        """
        subject = str(self.claims[claim_id].get("entity", {}).get("title") or "").lower()
        base = str(self.claims[claim_id].get("entity", {}).get("base") or "").lower()
        if not subject:
            return []
        seen = {r["url"] for r in self.searches[claim_id].get("results", ())}
        found: list[dict[str, Any]] = []
        for other, payload in self.searches.items():
            if other == claim_id:
                continue
            for result in payload.get("results", ()):
                if result["url"] in seen or len(found) >= EVIDENCE_CAP:
                    continue
                haystack = " ".join(
                    [str(result.get("title") or ""), *result.get("excerpts", ())]
                ).lower()
                if subject in haystack or (base and base in haystack):
                    seen.add(result["url"])
                    found.append(result)
        return found

    def record(
        self, claim: Mapping[str, Any], verdict: Verdict, outcome: str | None = None
    ) -> None:
        """Store why this claim was routed as it was — one document per claim per task.

        Written *after* the ledger transition, so a judgement never claims an outcome the
        ledger refused. It is a record and nothing reads it back: the run's decisions come from
        `Claim`, and a stage that branched on this would be branching on a copy (`judgements.py`).

        `outcome` overrides the one the bucket implies, for the single case where the run
        overrules the model: a budget exhausted with nothing left to judge settles `unchanged`
        whatever the bucket said. Both are stored, because they are two different statements.
        """
        claim_id = str(claim["claim_id"])
        self.stages.judgements.put(
            Judgement(
                task_id=self.task_id,
                claim_id=claim_id,
                page=str(claim.get("page", "")),
                attempt=self.attempts.get(str(claim["claim_id"]), 1),
                bucket=verdict.bucket,
                outcome=verdict.outcome if outcome is None else outcome,
                reason=verdict.reason,
                decided_at=self.started_at,
                objective=str(self.searches[claim_id].get("objective", "")),
                considered=tuple(
                    str(r["url"]) for r in self.searches[claim_id].get("results", ())
                ),
                off_entity=verdict.off_entity,
                note=verdict.note,
                source_a=verdict.source_a,
                source_b=verdict.source_b,
            )
        )

    def settle(self, claim_id: str, outcome: str, verdict: Verdict | None = None) -> None:
        """The ledger write one verdict implies, and the end of that claim's classification.

        The stage decides the bucket; `decay.py` decides what it costs, and nothing here may
        touch an interval. It happens **once per claim per run**: the transition reschedules
        the claim, so settling a second time would halve or double the interval twice over a
        single run's worth of evidence. Reclassification is free right up until this call,
        which is what makes the guard the boundary of the phase rather than a nuisance.
        """
        if claim_id in self.settled:
            return
        self.settled.append(claim_id)
        if verdict is not None and verdict.is_conflict:
            self.unresolved.append(claim_id)
        self.ledger.record_outcome(
            claim_id, outcome,
            note=verdict.note if verdict else "",
            source_a=verdict.source_a if verdict else "",
            source_b=verdict.source_b if verdict else "",
        )

    # -- stage 4 ---------------------------------------------------------------------

    def draft(self) -> dict[str, Any]:
        """One edit per claim retrieval turned out to have something to say about.

        Both draftable buckets land here: `new` because the page is incomplete, `conflicting`
        because it may be wrong. The reviewer gets the same two buttons for either — take the
        edit, or discard it — so a conflict needs no verdict of its own (`AGENTS.md` §7).

        A `ModelError` is caught per claim and never for the run: it is a domain failure — a
        refusal, an answer that does not satisfy the schema — so retrying it burns a round trip
        on something that cannot succeed, and one claim's bad answer must not cost the others
        their review. Transport failures are not caught and still reach ADK's retry
        (`AGENTS.md` §7).
        """
        for claim_id in self.decided:
            verdict = self.verdicts[claim_id]
            if verdict.bucket not in DRAFTABLE:
                continue
            claim = self.ledger.store.get(claim_id)
            if claim is None:  # pragma: no cover - the ledger just wrote it
                continue
            section = self.section_text(claim.page, claim.section_index)
            if section is None:  # pragma: no cover - classify skipped these already
                continue
            try:
                self.drafts[claim_id] = self.stages.drafter.draft(claim, section, verdict)
            except ModelError:
                self.failed.append(claim_id)
        return {"stage": "draft", "drafted": len(self.drafts), "failed": len(self.failed)}

    # -- stage 5 ---------------------------------------------------------------------

    def diff(self) -> dict[str, Any]:
        """What each edit did to the ideas already on the page. Degrades rather than fails —
        an unavailable model leaves the textual shape and a `text_only` flag."""
        for claim_id, draft in self.drafts.items():
            self.reviews[claim_id] = self.stages.reviewer.review(draft)
        destructive = sum(1 for review in self.reviews.values() if review.flags)
        return {"stage": "diff", "reviewed": len(self.reviews), "flagged": destructive}

    # -- stage 6 ---------------------------------------------------------------------

    def verify(self) -> dict[str, Any]:
        """Hand the run to the reviewer: one draft, holding every change it proposes.

        Nothing is stored for a run that proposed nothing — an empty draft is a card set with
        no cards, and it would sit at the head of the gate's unpublished list saying so.
        """
        changes = tuple(
            draft.as_change(
                edit_id=edit_id_for(claim_id),
                page_slug=slug_for(draft.page),
                flags=flags_for(draft, self.reviews.get(claim_id)),
            )
            for claim_id, draft in self.drafts.items()
        )
        if not changes:
            return {"stage": "verify", "draft_id": "", "changes": 0}
        self.draft_id = draft_id_for(self.task_id)
        self.stages.drafts.put(
            ReviewDraft(
                draft_id=self.draft_id,
                wiki=self.stages.profile.name,
                task_id=self.task_id,
                created_at=self.started_at,
                changes=changes,
            )
        )
        return {"stage": "verify", "draft_id": self.draft_id, "task_id": self.task_id,
                "changes": len(changes)}

    # -- shared ----------------------------------------------------------------------

    def section_text(self, page: str, section_index: int) -> str | None:
        """The section's wikitext from the baseline, or `None` when the page was never read.

        Context for a prompt, never the thing rewritten (`AGENTS.md` §7) — both stages that
        take it are editing an anchor inside it.
        """
        for section in self.stages.baseline.for_page(page):
            if section.section_index == section_index:
                return section.text
        return None

    @property
    def report(self) -> RunReport:
        buckets: dict[str, int] = {}
        for claim_id in self.decided:
            bucket = self.verdicts[claim_id].bucket
            buckets[bucket] = buckets.get(bucket, 0) + 1
        return RunReport(
            wiki=self.stages.profile.name,
            task_id=self.task_id,
            started_at=self.started_at,
            due=len(self.claims),
            researched=len(self.searches),
            discarded=len(self.discarded),
            out_of_budget=len(self.out_of_budget),
            rounds=self.rounds,
            stages=tuple(self.visited),
            buckets=buckets,
            reclassified=tuple(self.reclassified),
            drafted=len(self.drafts),
            failed=tuple(self.failed),
            unresolved=tuple(self.unresolved),
            skipped=tuple(self.skipped),
            unjudged=tuple(self.unjudged),
            draft_id=self.draft_id,
            changes=len(self.drafts) if self.draft_id else 0,
        )

    # -- the run -----------------------------------------------------------------------

    def execute(self) -> RunReport:
        """The six stages, in order, with the one backward edge as a loop.

        This used to be an ADK `Workflow` with six nodes and a routing map. It is a plain
        method now, because the routing was never a judgement: nothing here asks a model which
        stage runs next. Audit, Research, Classify, Draft, Diff and Verify run in a fixed
        order, and the single non-linear edge — a claim that needs another research round —
        is a `while`. A graph engine bought scheduling this does not need and cost an SDK in
        the import path.

        **What terminates it is unchanged**, and it is not the cap below: `research()` refuses
        a claim whose budget is spent, so `pending` shrinks to empty within
        `MAX_RESEARCH_ROUNDS` rounds on its own. The cap is a backstop against a future edit
        that breaks that, not the mechanism — a loop whose only bound is a constant is one
        nobody has to keep honest.
        """
        for stage in (self.audit, self.research, self.classify):
            stage()
            self.visited.append(stage.__name__)

        rounds = 0
        while self.pending:
            rounds += 1
            if rounds > MAX_ROUNDS:  # pragma: no cover - the budget check gets there first
                raise RuntimeError(
                    f"classify kept asking for another round after {rounds} of them; "
                    "the research budget check is what is supposed to stop this."
                )
            self.research()
            self.classify()

        for stage in (self.draft, self.diff, self.verify):
            stage()
            self.visited.append(stage.__name__)
        return self.report


#: A backstop on the Research <- Classify loop. The real bound is the per-claim research
#: budget; this only fires if that stops working.
MAX_ROUNDS = 10


def run(stages: Stages) -> RunReport:
    """One tick: build the run and execute it."""
    return Run(stages).execute()


__all__ = [
    "Run",
    "RunReport",
    "Stages",
    "after_date_for",
    "draft_id_for",
    "edit_id_for",
    "flags_for",
    "keywords",
    "objective_for",
    "queries_for",
    "run",
    "sources_for",
    "survivors",
]
