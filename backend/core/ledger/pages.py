"""One document per page the agent has ever run on, and the counter that names its runs.

A run used to carry two ids and neither said what it was about: a random uuid held by the
process that started it (`backend/runs.py`), and a clock-derived `task_id` stamped on every
document it wrote (`documents.task_id_for`). This is the third thing a run needs and the only
one that outlives the process — a record of the *page*, created the first time anybody runs on
it, holding the count that gives each run on that page its number.

That collapses the two ids into one that reads as what it is. `run-Gambit-0003` is the third
run on Gambit, and the same string is the claim's `task_id`, the draft's name and the path the
popup polls, so tracing a stored claim back to the run that proposed it is reading it rather
than joining on it.

**The counter is per page and it counts attempts, not successes.** A run that died in Research
still spent its number, because the number is how you say *which* run, and two runs both
calling themselves #3 is the provenance bug the id exists to prevent. It is never reset and
never reused — a page whose claims were all deleted still numbers its next run from where it
left off, the same rule `next_claim_id` follows (`AGENTS.md` §7).

**The record is not a cache of the page.** It holds no wikitext, no section count and no
revision: what the page *says* is the baseline's job (`baseline.py`), and a second copy of it
here would be a second copy able to disagree. This holds only what is true of the agent's
relationship to the page — when it first ran on it, and how often since.

**Two fields are stored and the interesting two are not.** The slug and the last run's id are
both functions of the title and the counter, so they are properties recomputed on load, the
same rule `documents.py` follows. That is also what makes the store's write one operation: a
single atomic increment settles the ordinal, and there is no derived field left to write back
in a second round trip that could fail on its own.

Pure: no vendor SDK, no I/O (`CLAUDE.md` §3).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..wiki.client import slug_for
from .documents import as_datetime

#: Bumped when a stored field changes meaning, like `documents.DOCUMENT_VERSION`.
PAGE_VERSION = 1


def run_id_for(page: str, ordinal: int) -> str:
    """The id of run number `ordinal` on `page`.

    Takes the title rather than the slug so there is one slug rule and no call site can pass an
    unslugged one. Zero-padded because these sort as strings in every store and in every
    listing, and `run-Gambit-10` before `run-Gambit-2` is a listing nobody trusts twice.
    """
    if ordinal < 1:
        raise ValueError(f"run ordinal must be 1 or more, not {ordinal}")
    return f"run-{slug_for(page)}-{ordinal:04d}"


@dataclass(frozen=True, slots=True)
class PageRecord:
    """The agent's relationship with one page: since when, and how many runs deep."""

    page: str  # resolved title; redirects are followed before storing (`AGENTS.md` §6)
    created_at: datetime  # the first run on this page — the moment the record was created
    runs: int = 0  # runs started against this page, ever; also the last run's ordinal
    last_run_at: datetime | None = None

    @property
    def slug(self) -> str:
        """Document id. Derived rather than stored, so the title is the only thing a caller
        can get wrong."""
        return slug_for(self.page)

    @property
    def last_run_id(self) -> str:
        """The id of the most recent run on this page, or `""` before there has been one."""
        return run_id_for(self.page, self.runs) if self.runs else ""

    def opening(self, now: datetime) -> PageRecord:
        """This record with one more run on it.

        The pure half of what a store does atomically: a store that can increment server-side
        should, and this is what its answer has to equal.
        """
        return replace(self, runs=self.runs + 1, last_run_at=now)


def to_document(record: PageRecord) -> dict[str, Any]:
    """Firestore-native types only, same contract as `documents.to_document`."""
    return {
        "v": PAGE_VERSION,
        "slug": record.slug,
        "page": record.page,
        "created_at": record.created_at,
        "runs": record.runs,
        "last_run_at": record.last_run_at,
    }


def from_document(doc: Mapping[str, Any]) -> PageRecord:
    version = doc.get("v")
    if version != PAGE_VERSION:
        raise ValueError(f"page document version {version!r}; this build reads {PAGE_VERSION}")
    created_at = as_datetime(doc["created_at"])
    if created_at is None:
        raise ValueError(f"{doc.get('slug')!r} has no created_at")
    return PageRecord(
        page=doc["page"],
        created_at=created_at,
        runs=doc.get("runs", 0),
        last_run_at=as_datetime(doc.get("last_run_at")),
    )


@runtime_checkable
class PageStore(Protocol):
    """Three operations, and the middle one is the only writer.

    There is no `put`: a page record is never assembled by a caller and handed over, because
    the one field that matters is a counter and a caller that sets it has already raced with
    whoever else was setting it. `open_run` is the write, it is one operation, and it returns
    the record as it now stands — `runs` is this run's ordinal and `last_run_id` is its id.
    """

    def get(self, page: str) -> PageRecord | None: ...

    def open_run(self, page: str, *, now: datetime) -> PageRecord: ...

    def all(self) -> tuple[PageRecord, ...]: ...


class InMemoryPageStore:
    """The deterministic store: runs can be numbered with no database, which is what lets the
    graph tests and a bare interpreter exercise the same code the demo runs."""

    def __init__(self, records: Iterable[PageRecord] = ()) -> None:
        self._records: dict[str, PageRecord] = {r.slug: r for r in records}

    def __len__(self) -> int:
        return len(self._records)

    def get(self, page: str) -> PageRecord | None:
        return self._records.get(slug_for(page))

    def open_run(self, page: str, *, now: datetime) -> PageRecord:
        existing = self._records.get(slug_for(page))
        record = (existing or PageRecord(page=page, created_at=now)).opening(now)
        self._records[record.slug] = record
        return record

    def all(self) -> tuple[PageRecord, ...]:
        return tuple(sorted(self._records.values(), key=lambda r: r.slug))
