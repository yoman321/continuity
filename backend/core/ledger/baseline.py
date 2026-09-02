"""What the page says now — the ledger's other half.

A run compares the world against something, and this is the something. Before any research
happens, an ingest pass reads each monitored page and records its sections verbatim: the
*previous* data, in the sense that everything retrieval later finds is measured against it.

**Sections, not claims, and that is the point of the split.** A claim is an assertion the agent
decided to track, and deciding what a page asserts is a judgement — it needs the model. A
section is what MediaWiki hands back, addressable by the same index `action=edit&section=N`
writes to. So the baseline is deterministic: read the page, split it, store it, with no key, no
model call and no judgement anywhere in the path. Claims are then proposed *against* a baseline
that already exists, rather than being the only thing the ledger holds.

Four collections, one ledger. `claims` is what the agent tracks and reschedules, `judgements`
is why each claim was routed that way (`judgements.py`), `drafts` is what a run proposed and a
reviewer decided (`drafts.py`), and `sections` is what the wiki currently says.
They are keyed differently and written at different times, which
is exactly why they are not one table: a re-ingest replaces a page's sections wholesale, while
a claim outlives every edit made to the section it sits in.

`content_hash` is what makes a re-ingest cheap to reason about: two ingests of an unchanged page
produce identical hashes, so "has this section moved since we last looked" is an equality rather
than a diff. It is stored rather than recomputed because Firestore can filter on it and cannot
filter on a value it would have to hash first.

Pure: filesystem only, no vendor SDK, no network (`CLAUDE.md` §3).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .documents import as_datetime
from .store import LedgerError

#: Bumped when a stored field changes meaning, like `documents.DOCUMENT_VERSION`.
BASELINE_VERSION = 1


@dataclass(frozen=True, slots=True)
class SectionBaseline:
    """One section of one page, as it read at `fetched_at`.

    `text` is the section verbatim, heading line included — the same bytes
    `action=edit&section=N` round-trips, so a diff against a later read is a diff of the real
    thing rather than of a normalised copy of it.
    """

    page: str  # resolved title; redirects are followed before storing (`AGENTS.md` §6)
    section_index: int
    section_heading: str  # "" for the lead
    text: str
    revid: int  # the revision this came from — a later write's `basetimestamp` partner
    fetched_at: datetime
    task_id: str = ""  # the ingest pass that read it (`documents.task_id_for`)

    @property
    def key(self) -> str:
        """Document id. Keyed by position because a page's sections are replaced together —
        inserting a heading renumbers the rest, and re-ingesting rewrites all of them at once."""
        return f"{self.page}#{self.section_index}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def chars(self) -> int:
        return len(self.text)


def to_document(baseline: SectionBaseline) -> dict[str, Any]:
    """Firestore-native types only, same contract as `documents.to_document`."""
    return {
        "v": BASELINE_VERSION,
        "key": baseline.key,
        "page": baseline.page,
        "section_index": baseline.section_index,
        "section_heading": baseline.section_heading,
        "text": baseline.text,
        # Derived, and stored anyway: Firestore filters on a field it holds, never on one it
        # would have to compute. The single exception to "derived values are never stored",
        # and it cannot drift because it is recomputed on every write.
        "content_hash": baseline.content_hash,
        "revid": baseline.revid,
        "fetched_at": baseline.fetched_at,
        "task_id": baseline.task_id,
    }


def from_document(doc: Mapping[str, Any]) -> SectionBaseline:
    version = doc.get("v")
    if version != BASELINE_VERSION:
        raise ValueError(
            f"baseline document version {version!r}; this build reads {BASELINE_VERSION}"
        )
    fetched_at = as_datetime(doc["fetched_at"])
    if fetched_at is None:
        raise ValueError(f"{doc.get('key')!r} has no fetched_at")
    return SectionBaseline(
        page=doc["page"],
        section_index=doc["section_index"],
        section_heading=doc["section_heading"],
        text=doc["text"],
        revid=doc["revid"],
        fetched_at=fetched_at,
        task_id=doc.get("task_id", ""),
    )


@runtime_checkable
class BaselineStore(Protocol):
    """Three operations. A page's sections are written and read as a set, never one at a time,
    because their indices are only meaningful relative to each other."""

    def for_page(self, page: str) -> tuple[SectionBaseline, ...]: ...

    def replace_page(self, page: str, sections: Iterable[SectionBaseline]) -> None: ...

    def pages(self) -> tuple[str, ...]: ...


class InMemoryBaselineStore:
    """The deterministic store: ingest runs, and the graph reads a baseline, with no database."""

    def __init__(self, sections: Iterable[SectionBaseline] = ()) -> None:
        self._sections: dict[str, SectionBaseline] = {s.key: s for s in sections}

    def __len__(self) -> int:
        return len(self._sections)

    def for_page(self, page: str) -> tuple[SectionBaseline, ...]:
        return tuple(
            sorted(
                (s for s in self._sections.values() if s.page == page),
                key=lambda s: s.section_index,
            )
        )

    def replace_page(self, page: str, sections: Iterable[SectionBaseline]) -> None:
        """Swap a page's whole baseline atomically.

        Wholesale rather than per-section because section indices shift: a heading inserted at
        the top renumbers everything under it, so merging a new read into old rows would leave
        one section's text filed under another's index — wrong, and silently so.
        """
        staged = list(sections)
        for section in staged:
            if section.page != page:
                raise LedgerError(
                    f"{section.key}: belongs to {section.page!r}, not {page!r}; a page's "
                    "baseline is replaced as one set"
                )
        self._sections = {k: v for k, v in self._sections.items() if v.page != page}
        for section in staged:
            self._sections[section.key] = section

    def pages(self) -> tuple[str, ...]:
        return tuple(sorted({s.page for s in self._sections.values()}))


def _read_sections(path: Path) -> tuple[SectionBaseline, ...]:
    if not path.exists():
        return ()
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return tuple(from_document(doc) for doc in payload.get("sections", {}).values())
