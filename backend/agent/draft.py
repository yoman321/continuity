"""The draft stage — writing the edit, and the arithmetic that checks it.

Classify decided *what* is true of a claim; this is the node that decides what the page should
say instead. It rewrites one anchor — the exact substring the ledger holds — and hands back
the replacement, a sentence for the reviewer, and the one source that becomes the `<ref>`.

**It edits the anchor, not the section.** `Claim.wikitext_anchor` is defined as an exact
substring of the page precisely so an edit can be surgical, and every downstream consumer is
built for that size: `diff.py` elides no context because its inputs are one infobox line or one
sentence, and the queue renders the whole diff without scrolling. The section is in the prompt
as *context* — what the page already says, so the model does not restate it — and never as the
thing to return.

**The bucket is an input, not a question.** Classify already tested the excerpts against the
page and ordered the three buckets to make that judgement reproducible. Asking a second model
whether the fact conflicts would buy a second opinion nothing can adjudicate, and the decay
ladder has already been driven off the first one. So this stage is *told* `new` or
`conflicting` and writes accordingly; it is never asked to reconsider which one it is.

**A conflict is drafted, not withheld.** Anything retrieval carried that the page does not say
reaches the reviewer as a card — a `new` claim as an addition, a `conflicting` one as an edit
that makes the disagreement visible without settling it. The card carries the note and both
urls, and the reviewer's two buttons mean what they always mean: take it, or discard it. What
this stage must never do is pick a side, which is why the prompt is told to show a disagreement
rather than resolve one.

**It carries a cheap check on its own output, and it is only the floor.** A model told to
insert a fact can quietly restructure the sentence it was inserting into, so the stage computes
`diff.shape(before, after)` and holds it against the bucket: a `new` claim whose draft displaced
existing *text* is `overreached`, and the queue says so. That is arithmetic — free, keyless, and
never wrong about text. It is also blind to the case that matters most, an edit that adds a
clause and reverses what the passage asserted, because nothing was removed for it to see. That
reading belongs to the Diff stage (`semantic_diff.py`), which runs next and is a separate node
for a reason: a stage that writes an edit and then rules on whether the edit was conservative is
reporting on itself, and that report is the one thing it cannot be used to check.

**Confidence is not asked for and never accepted.** It is computed by the core from the tiers
of the distinct domains backing the claim (`tiers.confidence_from`), the same as everywhere
else. A model-assigned score would be a number with no measurement behind it sitting in the
same field as one that has.

The stage writes nothing. It returns a `Draft`; publishing it is the gate's job, and the gate
is a human (`summary.md` §6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..core.ledger.citations import best_citation
from ..core.ledger.drafts import Change
from ..core.ledger.schema import Claim, Source
from ..core.profile import WikiProfile

# `shape` is aliased because `Draft` exposes a property of the same name; the plain name
# would read inside that property as a recursive call, which it is not.
from ..core.wiki.diff import MODIFY, Row, diff, to_payload
from ..core.wiki.diff import shape as edit_shape
from .model import ModelError, ModelRequest, ModelSource

#: Buckets this stage will draft for. `still_true` produces no edit at all — the claim's
#: citation is refreshed and its interval doubles, and there is nothing to show as a diff.
#: Both of the others do: **if retrieval carried something the page does not say, it goes to
#: the reviewer** (decided Aug 30, 2026). A `conflicting` claim is drafted as an edit that shows
#: the disagreement rather than settles it, and the reviewer discards it or takes it — the same
#: two buttons every other card has, so nothing about a conflict needs its own verdict.
DRAFTABLE = ("new", "conflicting")

SYSTEM = """\
You edit one passage of a wiki page to record something retrieval found that the page does not
say — a fact it is missing, or a fact that contradicts what it currently claims.

You are given: the SUBJECT, the CLAIM as the page currently states it, the ANCHOR (the exact
passage to rewrite), the SECTION it sits in for context, the FINDING that classification
reached, and the one SOURCE that will be cited.

Return the ANCHOR rewritten. Not the section, not the page — the anchor and nothing else.

Rules, and none of them is optional:

1. ADD, DO NOT REWRITE — WHEN THE FINDING IS `new`. The page is incomplete, not wrong. Every
   character of the ANCHOR that is still correct must appear in your answer unchanged and
   unbroken. If you find yourself rephrasing a clause that was already right, stop and add
   beside it instead.

   WHEN THE FINDING IS `conflicting`, the page may be wrong rather than incomplete: sources
   contradict what it says, or they contradict each other. Change only the part the
   disagreement is about and leave every other character of the ANCHOR alone. Where the
   sources disagree with EACH OTHER, do not choose between them — write the passage so both
   readings are visible, and let the reviewer settle it. You are never resolving a
   disagreement; you are showing one.

2. KEEP THE WIKI'S OWN CONVENTION. Look at how the ANCHOR already lists things and extend it
   the same way: a `<br>`-separated infobox value gains another `<br>` entry, a bulleted list
   gains a bullet, a sentence gains a clause. Do not introduce a new infobox field, a new
   section, or a new formatting style. This wiki's headings are fixed and you may not invent
   one.

3. CITE THE SOURCE YOU WERE GIVEN, AND ONLY IT. Attach `<ref>` carrying that exact url. Never
   write a url that was not handed to you, and never cite a second source you were not given.

4. SAY WHAT YOU DID IN ONE SENTENCE. `summary` is what a reviewer reads before looking at the
   diff: name the fact added and where it went. Do not argue for it — the sources are on
   screen beside your edit.

Do not report your own confidence, and do not judge whether the fact conflicts with the page.
Both were decided before you were called.
"""

#: The shape the answer must satisfy. Two fields: what the anchor becomes, and the sentence a
#: reviewer reads. No confidence field — see the module docstring.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "after": {
            "type": "string",
            "description": "the ANCHOR rewritten, with the new fact and its <ref>",
        },
        "summary": {
            "type": "string",
            "description": "one sentence naming the fact added and where it went",
        },
    },
    "required": ["after", "summary"],
}


@dataclass(frozen=True, slots=True)
class Draft:
    """One proposed edit, waiting at the publish gate.

    `before` and `after` are the content; the diff is a view of them and is computed on demand,
    never stored, because the gate's whole purpose is to let hours pass before someone clicks
    (`diff.py`).
    """

    claim_id: str
    page: str
    section_index: int
    section_heading: str
    before: str
    after: str
    summary: str
    citation: str  # the url that becomes the <ref>; "" when nothing citable survived filtering
    bucket: str  # the Classify verdict this was drafted from
    confidence: float  # from the core's tier table, never from the model
    conflict: str = ""  # what the sources fell out over; empty unless the bucket is conflicting
    conflict_sources: tuple[str, ...] = ()  # the two urls that disagree

    # -- derived -----------------------------------------------------------------

    @property
    def shape(self) -> str:
        """`append` or `modify` — what this edit did to the text already on the page."""
        return edit_shape(self.before, self.after)

    @property
    def is_empty(self) -> bool:
        """Nothing changed. A well-formed answer that did no work: the claim was `new`, so
        there was a fact to add, and the anchor came back as it went in."""
        return self.before == self.after

    @property
    def overreached(self) -> bool:
        """A `new` claim whose draft displaced existing wording.

        The bucket said the page was incomplete rather than wrong, so the edit had nothing to
        take away. That it did means either the classification or the draft is wrong, and
        which one it is takes a human — so this does not raise, it flags.
        """
        return self.bucket == "new" and self.shape == MODIFY

    @property
    def uncited(self) -> bool:
        """No source survived the citability filter, so the edit has no footnote. Worse than a
        weak citation on a real wiki — it is what gets a bot reverted (`citations.py`)."""
        return not self.citation

    @property
    def flags(self) -> tuple[str, ...]:
        """What the reviewer is warned about, in the order it matters. Empty is the good case
        and is what most drafts should carry."""
        return tuple(
            name
            for name, raised in (
                ("empty", self.is_empty),
                ("overreached", self.overreached),
                ("uncited", self.uncited),
            )
            if raised
        )

    @property
    def rows(self) -> tuple[Row, ...]:
        return diff(self.before, self.after)

    def as_change(
        self, *, edit_id: str, page_slug: str, flags: tuple[str, ...] | None = None
    ) -> Change:
        """This proposal as the record the review draft stores.

        Same fields as `payload()` below and for the same reason — the card a reviewer reads and
        the row a store holds must not be two shapes that can disagree. What the store adds is
        the lifecycle: the change arrives `undecided` and unwritten, and the gate moves it.

        `flags` overrides this draft's own, and the Diff stage is why: it reads the same edit
        for what it did to the *ideas* and raises flags this stage cannot see, so the card
        carries both readings or it misrepresents one of them (`agent/graph.py`).
        """
        return Change(
            edit_id=edit_id,
            claim_id=self.claim_id,
            page=self.page,
            page_slug=page_slug,
            section_index=self.section_index,
            section_heading=self.section_heading,
            before=self.before,
            after=self.after,
            summary=self.summary,
            rationale=self.summary,
            confidence=self.confidence,
            citation=self.citation,
            bucket=self.bucket,
            conflict=self.conflict,
            conflict_sources=self.conflict_sources,
            flags=self.flags if flags is None else flags,
        )

    def payload(self, *, edit_id: str, page_slug: str) -> dict[str, Any]:
        """The queue card, in the shape `FE/app.js` already renders.

        The diff rows are computed here rather than in the browser for the reason every other
        number is: the core owns it, so what a reviewer sees and what a test asserts cannot
        disagree (`AGENTS.md` §4).
        """
        return {
            "edit_id": edit_id,
            "claim_id": self.claim_id,
            "page": self.page,
            "page_slug": page_slug,
            "section_index": self.section_index,
            "section_heading": self.section_heading or "(lead)",
            "before": self.before,
            "after": self.after,
            "diff": to_payload(self.rows),
            "summary": self.summary,
            "rationale": self.summary,
            "confidence": self.confidence,
            "citation": self.citation,
            "bucket": self.bucket,
            "conflict": self.conflict,
            "conflict_sources": list(self.conflict_sources),
            "shape": self.shape,
            "flags": list(self.flags),
        }


@dataclass(frozen=True, slots=True)
class Drafter:
    """One wiki's draft stage. The profile is bound for the same reason it is on every stage:
    the model writes, the deployment decides whose conventions it writes under."""

    profile: WikiProfile
    source: ModelSource

    def draft(self, claim: Claim, section_text: str, verdict: Any) -> Draft:
        """Write the edit one classified claim implies.

        Args:
          claim: the ledger record, for its anchor, its section and its sources.
          section_text: the section's current wikitext, from the baseline or a fresh read.
            Context for the prompt — never the thing rewritten.
          verdict: the `classify.Verdict` this claim was sorted into.

        Raises:
          ModelError: if the bucket is not one this stage drafts for, or the answer does not
            satisfy the schema. A guessed edit would reach the gate looking exactly like a
            real one.
        """
        if verdict.bucket not in DRAFTABLE:
            raise ModelError(
                f"nothing to draft for bucket {verdict.bucket!r}; "
                f"expected one of {list(DRAFTABLE)}"
            )
        citation = best_citation(claim)
        request = ModelRequest(
            system=SYSTEM,
            prompt=self.prompt(claim, section_text, verdict, citation),
            schema=RESPONSE_SCHEMA,
        )
        after, summary = parse(self.source.run(request))
        return Draft(
            claim_id=claim.claim_id,
            page=claim.page,
            section_index=claim.section_index,
            section_heading=claim.section_heading,
            before=claim.wikitext_anchor,
            after=after,
            summary=summary,
            citation=citation.url if citation else "",
            bucket=verdict.bucket,
            confidence=claim.recompute_confidence(),
            # Carried onto the card so the reviewer sees what the disagreement was without
            # opening the ledger behind it. Empty for every bucket but `conflicting`.
            conflict=getattr(verdict, "note", ""),
            # Deduped: the classify schema requires both sides by url and a model that found
            # only one sometimes fills the field twice. Showing it twice would imply two
            # sources agreed to disagree; the note still says what the disagreement is.
            conflict_sources=tuple(
                dict.fromkeys(
                    url for url in (
                        getattr(verdict, "source_a", ""), getattr(verdict, "source_b", "")
                    ) if url
                )
            ),
        )

    def prompt(
        self, claim: Claim, section_text: str, verdict: Any, citation: Source | None
    ) -> str:
        """The filled prompt. Public so a test can assert on it and a run can record it.

        The source arrives with its excerpt attached, not just its url: the model has to write
        a sentence that the footnote actually supports, and it cannot do that from a link.
        """
        entity = claim.entity_ref
        source = (
            f"url: {citation.url}\n"
            f"publisher: {citation.domain} (tier {citation.tier})\n"
            f"excerpt: {citation.excerpt}"
            if citation
            else "(none citable — write the edit without a <ref>)"
        )
        return (
            f"SUBJECT: {entity.title}\n\n"
            f"CLAIM (as the page states it): {claim.text}\n\n"
            f"FINDING ({verdict.bucket}): {verdict.reason}\n\n"
            f"ANCHOR (rewrite exactly this):\n{claim.wikitext_anchor}\n\n"
            f"SECTION ({claim.section_heading or '(lead)'}) of {claim.page}, for context:\n"
            f"{section_text}\n\n"
            f"{_disagreement(verdict)}"
            f"SOURCE to cite:\n{source}\n"
        )


def _disagreement(verdict: Any) -> str:
    """The two sides, when there are two. Empty for every bucket but `conflicting`.

    Stated explicitly rather than left inside `reason`, because "show the disagreement" is not
    an instruction a model can follow from a sentence that summarises it.
    """
    note = getattr(verdict, "note", "")
    a, b = getattr(verdict, "source_a", ""), getattr(verdict, "source_b", "")
    if not (note or a or b):
        return ""
    sides = "\n".join(f"  - {url}" for url in (a, b) if url)
    return f"DISAGREEMENT: {note}\nThe sources that disagree:\n{sides}\n\n"


def parse(answer: str) -> tuple[str, str]:
    """Read the shape we declared, refusing anything else.

    An empty `after` is refused here rather than flagged: `Draft.is_empty` means the model
    returned the anchor unchanged, which is a weak edit a reviewer can still read, while a
    blank answer would delete the passage outright if anyone approved it.
    """
    try:
        payload = json.loads(answer)
    except json.JSONDecodeError as exc:
        raise ModelError(f"model answer was not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelError(f"model answer was {type(payload).__name__}, expected an object")

    after = payload.get("after")
    if not isinstance(after, str) or not after.strip():
        raise ModelError("model returned no replacement text; the anchor would be deleted")

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ModelError("model returned no summary; the reviewer has nothing to read")

    return after, summary
