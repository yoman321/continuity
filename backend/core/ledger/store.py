"""Where claims live between runs — the protocol, and the two stores that satisfy it locally.

The ledger is the agent's whole memory, so it has to outlive a run: `check_interval` doubles
from *last* run's value, `next_check_at` is an absolute wake time Cloud Scheduler polls weeks
later, and a claim left `UNRESOLVED` is the resume point for a reviewer who clicks hours after
the container scaled to zero. A store that emptied itself between runs would leave every claim
restarting at its wave seed, and the decay ladder — the headline behaviour — would never
climb.

**Local first, Firestore after** (`summary.md` §10). `JsonFileClaimStore` is the local
database: one file holding the exact documents Firestore will hold, written through
`documents.py` so the port swaps the transport and nothing else. Two things make the local
store behave like the remote one rather than merely stand in for it:

* **`due()` orders by `(next_check_at, claim_id)`** — the same order Firestore returns for
  `order_by("next_check_at")`, whose implicit tiebreak is the document id.
* **`put()` refuses a claim whose `next_check_at` is `None`.** Firestore inequality filters do
  not match null-valued fields, so an unscheduled claim would be due in memory and *invisible*
  in production — the one failure that would pass every local test. Asserting it on write makes
  the two stores agree, and pushes the fix to where it belongs: call `Claim.seeded` first.

Storage and nothing else. The deciding stays in `schema.py` — `Claim.is_due` and the
transitions that return new records — and no logic may migrate in here.

Pure: filesystem only, like `core/wiki/snapshots.py`. No network, no vendor SDK.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .documents import from_document, to_document
from .schema import Claim

#: Local ledger file, relative to the repo root. Gitignored: it is run state, not source.
DEFAULT_LEDGER_PATH = Path("data") / "ledger.json"

#: Claim ids are `claim-0001`, `claim-0002`, … — a counter, not a hash of anything. Zero-padded
#: so lexical order matches numeric order, which is what `all()` and `due()`'s tiebreak sort on;
#: that holds below 10000 claims, which is far more than one wiki will ever hold.
CLAIM_ID_PREFIX = "claim-"


class LedgerError(Exception):
    """A write the store refuses. Raised, not returned — unlike the wiki tools, there is no
    model on the other side of this call to re-plan from a value."""


@runtime_checkable
class ClaimStore(Protocol):
    """Six operations, and deliberately no more.

    `due` is the audit stage's input, `put`/`put_all` are how a run writes its conclusions
    back, `get` resolves `ripple_targets`, and `all` serves `/api/state`. `for_page` is how the
    audit stage sees what it already tracks, and `next_claim_id` allocates a name for a new
    claim — both belong here because only the store knows what exists. Every store that
    satisfies this — in-memory, file, Firestore — is interchangeable in the graph.
    """

    def get(self, claim_id: str) -> Claim | None: ...

    def put(self, claim: Claim) -> None: ...

    def put_all(self, claims: Iterable[Claim]) -> None: ...

    def due(self, now: datetime, *, limit: int | None = None) -> tuple[Claim, ...]: ...

    def all(self) -> tuple[Claim, ...]: ...

    def for_page(self, page: str) -> tuple[Claim, ...]: ...

    def next_claim_id(self) -> str: ...


def require_scheduled(claim: Claim) -> Claim:
    """The store contract: a persisted claim always has a wake time.

    See the module docstring — this is the guard against a claim that is due locally and
    unreachable on Firestore. `Claim.seeded(now)` is what supplies it.
    """
    if claim.next_check_at is None:
        raise LedgerError(
            f"{claim.claim_id}: next_check_at is None; call Claim.seeded(now) before storing. "
            "A null wake time is invisible to a Firestore inequality filter."
        )
    return claim


class InMemoryClaimStore:
    """The deterministic store. Makes the whole graph runnable with no database at all —
    every stage that touches state can be tested offline, the way `SnapshotPageSource` does
    for reads."""

    def __init__(self, claims: Iterable[Claim] = ()) -> None:
        self._claims: dict[str, Claim] = {}
        for claim in claims:
            self._claims[claim.claim_id] = require_scheduled(claim)

    def __len__(self) -> int:
        return len(self._claims)

    def get(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def put(self, claim: Claim) -> None:
        self._claims[claim.claim_id] = require_scheduled(claim)

    def put_all(self, claims: Iterable[Claim]) -> None:
        """Write a batch. Every claim is validated before any is stored, so a rejected one
        leaves the ledger untouched — the same all-or-nothing a Firestore batch gives."""
        staged = [require_scheduled(claim) for claim in claims]
        for claim in staged:
            self._claims[claim.claim_id] = claim

    def due(self, now: datetime, *, limit: int | None = None) -> tuple[Claim, ...]:
        """Claims whose wake time has passed, soonest first.

        No status filter on purpose: a second predicate would need a Firestore composite
        index, and the emulator does not enforce those — so the query would pass locally and
        fail deployed. Callers filter status in Python; the collection is one wiki.
        """
        ready = [claim for claim in self._claims.values() if claim.is_due(now)]
        ready.sort(key=_due_order)
        return tuple(ready if limit is None else ready[:limit])

    def all(self) -> tuple[Claim, ...]:
        return tuple(sorted(self._claims.values(), key=lambda c: c.claim_id))

    def for_page(self, page: str) -> tuple[Claim, ...]:
        """Every claim tracked on one page, so the audit stage can recognise what it already
        has instead of proposing it again.

        One equality filter, which Firestore serves from the automatic single-field index —
        no composite index, and therefore nothing the emulator would fail to catch (§6). The
        caller matches anchors in Python: a page holds a handful of claims, and an anchor is
        long enough that indexing it would be the expensive way to compare strings.
        """
        return tuple(c for c in self.all() if c.page == page)

    def next_claim_id(self) -> str:
        """Allocate the next claim name.

        Deliberately a meaningless counter. An id derived from the claim's content — a hash of
        page and anchor was the first attempt — changes when the content does, and applying an
        edit changes the anchor by definition: the record would be re-keyed on every successful
        edit, dangling every `ripple_targets` entry pointing at it. So identity is assigned once
        and never recomputed, and *finding* a claim is `for_page` plus an anchor match.

        Single writer assumed: one hourly tick, one run. Two concurrent runs could allocate the
        same number, which on Firestore is closed by allocating inside a transaction — the
        adapter's problem, not the protocol's.
        """
        used = [_claim_number(c.claim_id) for c in self._claims.values()]
        return f"{CLAIM_ID_PREFIX}{max(used, default=0) + 1:04d}"


class JsonFileClaimStore(InMemoryClaimStore):
    """The local database: an in-memory store that survives the process.

    It *inherits* rather than reimplements, so `due` and `all` cannot drift from the
    in-memory semantics the graph is tested against — the whole point of running local first
    is that the behaviour ports, not just the data.

    The file holds `{"claims": {claim_id: document}}`, sorted and indented, so a run's effect
    on the ledger is legible in a diff. Every write rewrites the file: O(n) per put, which at
    one wiki and eight pages is nothing, and which Firestore removes rather than optimises.
    Writes go through a temp file and `Path.replace`, so an interrupted run leaves the previous
    ledger intact instead of a truncated one.
    """

    def __init__(self, path: Path | str = DEFAULT_LEDGER_PATH) -> None:
        self.path = Path(path)
        super().__init__(_read_claims(self.path))

    def put(self, claim: Claim) -> None:
        super().put(claim)
        self._flush()

    def put_all(self, claims: Iterable[Claim]) -> None:
        super().put_all(claims)
        self._flush()

    def _flush(self) -> None:
        write_json(
            self.path,
            {
                "claims": {
                    claim_id: to_document(claim)
                    for claim_id, claim in sorted(self._claims.items())
                }
            },
        )


# -- file plumbing --------------------------------------------------------------------


def _read_claims(path: Path) -> tuple[Claim, ...]:
    if not path.exists():
        return ()
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return tuple(from_document(doc) for doc in payload.get("claims", {}).values())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write one collection to disk, atomically.

    Sorted and indented so a run's effect is legible in a diff, and written through a temp file
    plus `Path.replace` so an interrupted run leaves the previous file intact rather than a
    truncated one. Shared with `baseline.py`: both collections are files on the way to being
    Firestore collections, and they must not disagree about durability.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_encode),
        encoding="utf-8",
    )
    temp.replace(path)


def _encode(value: Any) -> str:
    """JSON has no timestamp type; Firestore does. This is the only place the two differ."""
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot store {type(value).__name__} in the ledger file")


def _claim_number(claim_id: str) -> int:
    """The counter inside an allocated id, or 0 for an id this store did not allocate.

    Hand-written ids are legal — `build_demo_state.py` uses mnemonics like `GAM-APP-01` — and
    they simply do not participate in the sequence.
    """
    if not claim_id.startswith(CLAIM_ID_PREFIX):
        return 0
    suffix = claim_id[len(CLAIM_ID_PREFIX):]
    return int(suffix) if suffix.isdigit() else 0


def _due_order(claim: Claim) -> tuple[datetime, str]:
    # `require_scheduled` guarantees the wake time, so the assertion here is documentation.
    assert claim.next_check_at is not None
    return claim.next_check_at, claim.claim_id
