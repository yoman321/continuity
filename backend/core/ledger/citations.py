"""Which source goes in the footnote.

Every source a search returns is evidence: it corroborates, it counts toward confidence, and
it is what the reviewer reads. Exactly one of them becomes the `<ref>` on a drafted edit, and
picking that one is *not* the same question as ranking authority.

Measured Aug 23, 2026 on the demo's opening claim. Retrieval returned six publishers for
"Gambit appears in *Avengers: Doomsday*". The two tier-1 sources — `marvel.com` and
`disney.com`, the studio's own pages, the most authoritative in the table — list the cast as
actor names and **never write the word Gambit**. They establish that Channing Tatum is in the
film; they do not establish the claim, which is about the character. The four tier-2 and
tier-3 sources name both.

So "cite your best source" produces a sentence footnoted to a page that does not contain it.
Nothing catches that: the claim is true, six publishers agree, confidence scores 1.0, and the
reviewer sees a green edit from `marvel.com`. On a real wiki an unsupportive citation is worse
than none — it is what gets a bot reverted.

The fix is two steps, and this module is the first one:

1. **Keep only sources whose excerpt actually contains the claim's terms.**
2. Rank what survives by tier, as before.

Tier keeps both of its other jobs — deciding what retrieval may fetch, and computing
confidence from every source regardless of whether it can be cited. `marvel.com` still counts
toward the score here; it just is not the footnote.

Pure, and deliberately not a model call: a citation that cannot be checked by string
comparison cannot be checked by a reviewer either.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .schema import Claim, Source


def _normalise(text: str) -> str:
    """Collapse whitespace and fold case. Excerpts are markdown scraped from a page, so a term
    can arrive split across a line break that the publisher never wrote."""
    return re.sub(r"\s+", " ", text).casefold()


def mentions(text: str, term: str) -> bool:
    """Whether `text` contains `term` as a whole word (or whole phrase).

    Word-bounded so `Gambit` does not match inside a longer word, but tolerant at the edges
    because press copy wraps terms in quotation marks and dashes — straight or curly, the
    boundary is the same and both have to count.
    """
    if not term.strip():
        return False
    pattern = r"(?<!\w)" + r"\s*".join(re.escape(c) for c in _normalise(term)) + r"(?!\w)"
    return re.search(pattern, _normalise(text)) is not None


def citation_terms(claim: Claim) -> tuple[str, ...]:
    """The terms a source must contain to be citable for `claim`, when none are given.

    The subject, and only the subject. It is the one term a supporting source cannot omit —
    `marvel.com` fails on exactly this — and it is already on the record, so no claim needs a
    new field to get the default right. `base` rather than `title`: a variant subpage's suffix
    (`Human Torch/Void-Analyzing Fantastic Four`) is a wiki naming convention that no publisher
    writes, so requiring it would reject every source in existence. Distinguishing a variant
    from its prime is the classify stage's job (`AGENTS.md` §7), not the footnote's.

    Callers with a more specific sentence in hand should pass their own terms — the drafted
    wording is what the footnote has to support, and only the Draft stage knows it.
    """
    return (claim.entity_ref.base,)


def supports(source: Source, terms: Sequence[str]) -> bool:
    """Whether `source` can be cited for a claim needing every term in `terms`.

    Every term, not any: a footnote has to support the whole sentence. A source carrying half
    of it is corroboration, which is a different and lesser thing.
    """
    return all(mentions(source.excerpt, term) for term in terms)


def supporting(claim: Claim, terms: Sequence[str] | None = None) -> tuple[Source, ...]:
    """Every source that can be cited for `claim`, best tier first.

    Ties keep retrieval order, which is Parallel's own relevance ranking — the best available
    signal once tier has been spent, and stable, so a rebuild does not reshuffle footnotes.
    """
    required = tuple(terms) if terms is not None else citation_terms(claim)
    citable = [source for source in claim.sources if supports(source, required)]
    return tuple(sorted(citable, key=lambda source: source.tier))


def best_citation(claim: Claim, terms: Sequence[str] | None = None) -> Source | None:
    """The one source that belongs in the `<ref>`, or `None` when nothing supports the claim.

    `None` is a real answer and must not be rounded up to "cite the best source anyway". A
    claim whose evidence never states it is one the reviewer should see as unsupported — that
    is the same instinct as declining to resolve a conflict (`summary.md` §6), applied to
    citation rather than to adjudication.
    """
    citable = supporting(claim, terms)
    return citable[0] if citable else None


def uncited(claim: Claim, terms: Sequence[str] | None = None) -> bool:
    """True when the claim has sources but none of them state it. Distinct from having no
    sources at all: this is retrieval that landed near the claim without landing on it."""
    return bool(claim.sources) and not supporting(claim, terms)
