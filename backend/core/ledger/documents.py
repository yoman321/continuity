"""The stored shape of a claim — one document, and the same one in every store.

The ledger runs against a local file now and Firestore after the deploy weekend
(`summary.md` §10). What keeps that port cheap is that neither store owns the shape: this
module does, and both read it from here.

`to_document` emits only the value types Firestore's document model accepts — `str`, `int`,
`float`, `bool`, `None`, `datetime`, `list`, `dict` — so the adapter hands the result straight
to `.set()` with nothing in between. The local store is the one that pays for the difference,
because JSON has no timestamp type: it encodes datetimes on the way out and `from_document`
coerces them back. Firestore returns `DatetimeWithNanoseconds`, a `datetime` subclass, so the
same reader covers both.

Derived values are never stored. `auto_appliable`, `is_contradicted` and `budget_spent` are
properties on `Claim`, recomputed on load — a stored derivation is how a ledger comes back
disagreeing with itself.

Pure: no vendor SDK, no I/O (`CLAUDE.md` §3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from .decay import Wave
from .schema import Claim, ClaimKind, ClaimStatus, Contradiction, EntityRef, Source

#: Bumped when a stored field changes meaning. `from_document` refuses anything else rather
#: than guessing, because a ledger read wrong is worse than a ledger not read at all.
#:
#: v2 (Aug 29, 2026) collapsed `status` to `verified` / `unresolved`. A v1 document can hold
#: `stale`, `drafted`, `applied` or `exhausted`, and there is no honest mapping for the middle
#: two — where an edit sat in the pipeline is not something the claim ever recorded. So a v1
#: ledger is refused rather than migrated; the local file is gitignored run state and nothing
#: is deployed, so there is no v1 data anywhere that matters.
DOCUMENT_VERSION = 2


def to_document(claim: Claim) -> dict[str, Any]:
    """The claim as one Firestore document. `claim_id` is in the body as well as being the
    document id — a few bytes to make an exported document self-describing."""
    return {
        "v": DOCUMENT_VERSION,
        "claim_id": claim.claim_id,
        "page": claim.page,
        "entity_ref": {
            "title": claim.entity_ref.title,
            "base": claim.entity_ref.base,
            "variant": claim.entity_ref.variant,
        },
        "kind": claim.kind.value,
        "wave": claim.wave.value,
        "status": claim.status.value,
        "text": claim.text,
        "wikitext_anchor": claim.wikitext_anchor,
        "section_index": claim.section_index,
        "section_heading": claim.section_heading,
        "confidence": claim.confidence,
        "sources": [_source_document(s) for s in claim.sources],
        "contradicts": [_contradiction_document(c) for c in claim.contradicts],
        "objective": claim.objective,
        "research_rounds": claim.research_rounds,
        "ripple_targets": list(claim.ripple_targets),
        "last_verified": _utc(claim.last_verified),
        "next_check_at": _utc(claim.next_check_at),
        # Firestore has no duration type. Seconds as an integer, because every interval on the
        # ladder is a whole number of hours (`decay.py`) and a float would round-trip noise.
        "check_interval_seconds": int(claim.check_interval.total_seconds()),
    }


def from_document(doc: Mapping[str, Any]) -> Claim:
    """Rebuild a claim from its stored document. Raises `ValueError` on an unknown version."""
    version = doc.get("v")
    if version != DOCUMENT_VERSION:
        raise ValueError(
            f"claim document version {version!r}; this build reads {DOCUMENT_VERSION}"
        )

    ref = doc["entity_ref"]
    return Claim(
        claim_id=doc["claim_id"],
        page=doc["page"],
        entity_ref=EntityRef(
            title=ref["title"], base=ref["base"], variant=ref.get("variant")
        ),
        kind=ClaimKind(doc["kind"]),
        wave=Wave(doc["wave"]),
        status=ClaimStatus(doc["status"]),
        text=doc["text"],
        wikitext_anchor=doc["wikitext_anchor"],
        section_index=doc["section_index"],
        section_heading=doc["section_heading"],
        confidence=doc["confidence"],
        sources=tuple(_source(s) for s in doc.get("sources", ())),
        contradicts=tuple(_contradiction(c) for c in doc.get("contradicts", ())),
        objective=doc.get("objective", ""),
        research_rounds=doc.get("research_rounds", 0),
        ripple_targets=tuple(doc.get("ripple_targets", ())),
        last_verified=as_datetime(doc.get("last_verified")),
        next_check_at=as_datetime(doc.get("next_check_at")),
        check_interval=timedelta(seconds=doc.get("check_interval_seconds", 0)),
    )


def as_datetime(value: Any) -> datetime | None:
    """Coerce a stored instant to an aware UTC datetime.

    Accepts what either store hands back: `None`, a `datetime` (Firestore), or an ISO-8601
    string (the JSON file). A naive value is read as UTC — the ledger stores UTC instants and
    nothing else ever writes here. Normalising on read is what makes a file round trip and a
    Firestore round trip produce the same value, which is the whole portability claim.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc(value)
    text = str(value)
    # `datetime.fromisoformat` only learned `Z` in 3.11, and the project floor is 3.10.
    parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    return _utc(parsed)


def is_firestore_safe(value: Any) -> bool:
    """Whether `value` is a type Firestore stores without translation.

    The portability check, pinned in the suite: if a document ever holds something else, the
    adapter would need a converter and the two stores would stop agreeing.
    """
    if value is None or isinstance(value, (bool, int, float, str, datetime)):
        return True
    if isinstance(value, Mapping):
        return all(
            isinstance(k, str) and is_firestore_safe(v) for k, v in value.items()
        )
    if isinstance(value, Sequence):
        return all(is_firestore_safe(v) for v in value)
    return False


# -- pieces ---------------------------------------------------------------------------


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _source_document(source: Source) -> dict[str, Any]:
    return {
        "url": source.url,
        "excerpt": source.excerpt,
        "retrieved_at": _utc(source.retrieved_at),
        "as_of": _utc(source.as_of),
        # Looked up at creation against the profile's table, never model-assigned, so it is
        # stored rather than re-derived — `recompute_confidence` must not need a profile.
        "tier": source.tier,
        "domain": source.domain,
    }


def _source(doc: Mapping[str, Any]) -> Source:
    retrieved_at = as_datetime(doc["retrieved_at"])
    if retrieved_at is None:
        raise ValueError(f"source {doc.get('url')!r} has no retrieved_at")
    return Source(
        url=doc["url"],
        excerpt=doc["excerpt"],
        retrieved_at=retrieved_at,
        as_of=as_datetime(doc.get("as_of")),
        tier=doc["tier"],
        domain=doc.get("domain", ""),
    )


def _contradiction_document(contradiction: Contradiction) -> dict[str, Any]:
    return {
        "note": contradiction.note,
        "source_a": contradiction.source_a,
        "source_b": contradiction.source_b,
    }


def _contradiction(doc: Mapping[str, Any]) -> Contradiction:
    return Contradiction(
        note=doc["note"], source_a=doc["source_a"], source_b=doc["source_b"]
    )
