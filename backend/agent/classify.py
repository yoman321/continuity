"""The classify stage — the judgement, and the prompt that shapes it.

Retrieval returns a batch of excerpts, not an answer. This is the node that reads them against
the page as it currently stands and puts the claim in exactly one of three buckets: it is still
true, the world has something the page lacks, or there is a disagreement a person should
settle. The bucket is the whole output. Every number that follows from it — the recheck
interval, the next wake time, the confidence — is computed by the deterministic core from that
one word, so a bad judgement produces a wrong bucket and never a corrupted schedule.

**The prompt is four rules, and each one was measured rather than reasoned** (`AGENTS.md` §7).
They are constants in this module so a change to any of them shows up in a diff:

1. **Precedence order, said out loud.** The three bucket definitions overlap — "page and
   sources disagree" swallows "retrieval carries something the page lacks", because an absence
   reads as a disagreement. Left unordered every model tested collapsed toward `conflicting`;
   stating the order took the precision case from 0/3 to 3/3 on every model.
2. **An absence on the page is not a contradiction.** The same failure from the other side.
   Its corollary lives in the ledger rather than here: claims are phrased as positive
   assertions, because a claim asserting an absence is contradicted by every new fact.
   Rephrasing two benchmark claims from closed- to open-world moved every model from 50% to
   ≥88%.
3. **The subject is in the prompt, variant included.** Retrieval cannot tell `Human Torch`
   from `Human Torch/Void-Analyzing Fantastic Four` — Parallel returns excerpts about "the
   Human Torch" with nothing marking which. Without the subject stated, the model is being
   asked for a judgement it has no input for, which is a missing-information bug and not a
   prompting one.
4. **Filter, then classify — two operations, in that order.** An off-entity excerpt is not weak
   evidence, it is not evidence; routing it to `conflicting` per-excerpt fills the review queue
   with noise. `conflicting` is reserved for a real disagreement, or for filtering emptying the
   batch — which is the honest signal that retrieval went off-target.

The stage is otherwise thin on purpose: build the prompt, call the perimeter, parse the shape
we declared, and hand back a value. It writes nothing — the caller maps the bucket onto
`Ledger.record_outcome`, which is where the ladder lives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..core.profile import WikiProfile
from .model import ModelError, ModelRequest, ModelSource

#: The three buckets, in the order they must be tested. Order is load-bearing (rule 1).
BUCKETS = ("conflicting", "new", "still_true")

#: What the outcome name is in ledger terms. The stage decides the bucket; `decay.py` decides
#: what the bucket costs. Nothing here may touch an interval.
OUTCOME_FOR = {
    "still_true": "unchanged",
    "new": "changed",
    "conflicting": "unresolved",
}

SYSTEM = """\
You classify one factual claim taken from a wiki page against evidence retrieved from the web.

You are given: the SUBJECT the claim is about, the CLAIM as the page currently states it, the
SECTION of the page it sits in, and EXCERPTS retrieved from sources.

Do two operations, in this order, never as one:

STEP 1 — FILTER. Drop every excerpt that is not about the SUBJECT. A wiki distinguishes a
character from a film-specific variant of that character, and they are DIFFERENT SUBJECTS: an
excerpt about the prime is not evidence for or against a claim about the variant, and the
reverse. An off-subject excerpt is not weak evidence and not a disagreement — it is not
evidence at all. List what you dropped in `off_entity`, by url.

STEP 2 — CLASSIFY what remains, testing the buckets in this order and stopping at the first
that fits:

1. `conflicting` — the surviving excerpts contradict the CLAIM, or they contradict each other,
   or STEP 1 dropped every excerpt so nothing is left to judge. Do not resolve a
   disagreement; state it and let a person decide.
2. `new` — the surviving excerpts carry a fact the SECTION does not contain. The page is not
   wrong, it is incomplete.
3. `still_true` — the SECTION already says this and the excerpts support it.

AN ABSENCE ON THE PAGE IS NOT A CONTRADICTION. If the excerpts say something the section
simply does not mention, that is `new`, never `conflicting`.

For `conflicting`, `conflict` is required and must name both sides by url with a one-sentence
note. For every bucket, `reason` is one sentence a reviewer can read.
"""

#: The shape the answer must satisfy. Declared rather than parsed out of prose: a model that
#: cannot meet it fails loudly instead of producing something plausible and wrong.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "off_entity": {
            "type": "array",
            "items": {"type": "string"},
            "description": "urls dropped in STEP 1 as being about a different subject",
        },
        "bucket": {"type": "string", "enum": list(BUCKETS)},
        "reason": {"type": "string"},
        "conflict": {
            "type": "object",
            "properties": {
                "note": {"type": "string"},
                "source_a": {"type": "string"},
                "source_b": {"type": "string"},
            },
            "required": ["note", "source_a", "source_b"],
        },
    },
    "required": ["off_entity", "bucket", "reason"],
}


@dataclass(frozen=True, slots=True)
class Verdict:
    """One classification, in the terms the ledger takes."""

    bucket: str
    reason: str
    off_entity: tuple[str, ...] = ()
    note: str = ""
    source_a: str = ""
    source_b: str = ""

    @property
    def outcome(self) -> str:
        """The `Ledger.record_outcome` name for this bucket."""
        return OUTCOME_FOR[self.bucket]

    @property
    def is_conflict(self) -> bool:
        return self.bucket == "conflicting"


@dataclass(frozen=True, slots=True)
class Classifier:
    """One wiki's classify stage. The profile is bound for the same reason it is on every
    tool: the model judges, the deployment decides whose rules it judges under."""

    profile: WikiProfile
    source: ModelSource

    def classify(
        self, claim: dict[str, Any], section_text: str, search: dict[str, Any]
    ) -> Verdict:
        """Sort one claim into a bucket.

        Args:
          claim: a claim view as `Ledger.due_claims` returns it.
          section_text: the section's current wikitext, from the baseline or a fresh read.
          search: a `WebSearch.search` payload. Must have succeeded — a failed search is
            discarded, never classified (`AGENTS.md` §7).
        """
        if "error" in search:
            raise ModelError(
                f"nothing to classify: the search failed ({search['error']}). Discard the "
                "round rather than judging an empty batch."
            )
        request = ModelRequest(
            system=SYSTEM, prompt=self.prompt(claim, section_text, search),
            schema=RESPONSE_SCHEMA,
        )
        return parse(self.source.run(request))

    def prompt(
        self, claim: dict[str, Any], section_text: str, search: dict[str, Any]
    ) -> str:
        """The filled prompt. Public so a test can assert on it and a run can record it.

        `entity` is stated even when the claim is about a prime subject, because "this is not a
        variant" is itself the information rule 3 exists to supply.
        """
        entity = claim.get("entity", {})
        subject = entity.get("title", claim.get("page", ""))
        variant = entity.get("variant")
        kind = (
            f"{subject} is a VARIANT of {entity.get('base')}. They are different subjects."
            if variant
            else f"{subject} is a prime subject, not a variant of anything."
        )
        excerpts = "\n\n".join(
            f"[{i + 1}] url: {r['url']}\n"
            f"    publisher: {r.get('domain', '')} (tier {r.get('tier', '?')})\n"
            f"    published: {r.get('publish_date') or 'unknown'}\n"
            f"    excerpt: {' '.join(r.get('excerpts', []))}"
            for i, r in enumerate(search.get("results", ()))
        )
        return (
            f"SUBJECT: {subject}\n"
            f"{kind}\n\n"
            f"CLAIM (as the page states it): {claim.get('text', '')}\n\n"
            f"SECTION ({claim.get('section_heading') or '(lead)'}) of {claim.get('page', '')}:\n"
            f"{section_text}\n\n"
            f"RESEARCH OBJECTIVE: {search.get('objective', '')}\n\n"
            f"EXCERPTS:\n{excerpts or '(none returned)'}\n"
        )


def parse(answer: str) -> Verdict:
    """Read the shape we declared, refusing anything else.

    A malformed answer is a `ModelError` rather than a default bucket: guessing here would put
    a fabricated judgement into the ledger with the same authority as a real one.
    """
    try:
        payload = json.loads(answer)
    except json.JSONDecodeError as exc:
        raise ModelError(f"model answer was not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelError(f"model answer was {type(payload).__name__}, expected an object")

    bucket = payload.get("bucket")
    if bucket not in BUCKETS:
        raise ModelError(f"unknown bucket {bucket!r}; expected one of {list(BUCKETS)}")

    conflict = payload.get("conflict") or {}
    verdict = Verdict(
        bucket=bucket,
        reason=str(payload.get("reason", "")),
        off_entity=tuple(payload.get("off_entity", ())),
        note=str(conflict.get("note", "")),
        source_a=str(conflict.get("source_a", "")),
        source_b=str(conflict.get("source_b", "")),
    )
    if verdict.is_conflict and not (verdict.note and verdict.source_a and verdict.source_b):
        # `Ledger.record_outcome` refuses this too. Catching it here names the stage that
        # produced it, rather than surfacing as a storage complaint two calls later.
        raise ModelError(
            "conflicting verdict without both sides: a disagreement recorded without "
            "note, source_a and source_b is not reviewable"
        )
    return verdict
