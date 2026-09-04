"""The Parallel search tool — the agent's only route to the outside world.

Retrieval is where this system spends money and where it is most easily fooled, so three
decisions are baked into the signature rather than left to the caller:

* **One call carries every query for a claim.** Parallel bills one `sku_search` per *call*,
  not per query (`summary.md` §12), so `search_queries` is a list and always was — batching a
  claim's angles into one call costs exactly what asking one question costs. A tool taking a
  single query would have cost four times as much for no extra evidence.
* **The tier table is the retrieval policy, not a scoring function.** `include_domains` comes
  from the profile on every call and is never a parameter. Measured Aug 22, 2026 on the Human
  Torch precision case: unfiltered returned two Tumblr posts and a scraped cast table whose
  actor names had slipped a row against their roles; allowlisted returned Disney and Marvel
  stating the fact, in a third of the time (`AGENTS.md` §7).
* **Tier is assigned here, by lookup, and never by the model.** Parallel returns no authority,
  relevance or confidence field, which is what makes this safe: there is no vendor number for
  a model to anchor on, and ours is a table lookup on the registrable domain.

The excerpts come back as a list per URL and stay a list. Joining them into one blob would put
two unrelated passages next to each other and invite exactly the false-adjacency reading that
`AGENTS.md` §7 warns about with scraped tables.

Imports no ADK, and imports `parallel` only inside the call that needs it.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ...core.ledger import tiers
from ...core.ledger.schema import Source
from ...core.profile import WikiProfile

#: Deadline for **one attempt**, not for the call. Measured search latency is 1.4-5.8s
#: (`summary.md` §12), so 15s is ~2.6x the slowest observed — loose enough to survive a bad
#: day, tight enough that a wedged search is not mistaken for a slow one. The SDK's own default
#: is **600 seconds**: ten minutes, inside a tick with a 900s Cloud Run budget.
TIMEOUT_SECONDS = 15.0

#: Attempts are `MAX_RETRIES + 1`, and the retry is the SDK's, not ours — it retries timeouts,
#: 429s and 5xx alike. One rather than the SDK's two for two reasons. It halves the worst case
#: below; and a search that timed out may still have been served, so every retry risks a second
#: `sku_search` for one claim's evidence. Past this, ADK re-running the node is the right
#: escalation: a fresh search 30s later is what you wanted anyway.
MAX_RETRIES = 1

#: Backoff the SDK sleeps between attempts: `0.5 * 2**k`, capped at 8s, times 0.75-1.0 jitter.
#: Upper bound taken, because a bound that assumes lucky jitter is not a bound.
_INITIAL_RETRY_DELAY = 0.5
_MAX_RETRY_DELAY = 8.0


def worst_case_seconds(
    timeout: float = TIMEOUT_SECONDS, max_retries: int = MAX_RETRIES
) -> float:
    """The longest one `search()` can take before it raises, in wall clock.

    Computed rather than asserted in a comment, because the number that matters is not the
    per-attempt timeout — it is that timeout multiplied by the attempts the SDK makes on its
    own. At the defaults this is 30.5s; at the SDK's own (600s, 2 retries) it is 1801.5s, which
    is longer than the Cloud Run request budget it would be running inside.
    """
    backoff = sum(min(_INITIAL_RETRY_DELAY * 2.0**k, _MAX_RETRY_DELAY) for k in range(max_retries))
    return (max_retries + 1) * timeout + backoff


class SearchError(RuntimeError):
    """Retrieval failed in a way that retrying cannot fix: a rejected request, a bad key, a
    revoked permission. Transport failures are *not* this — they propagate (`AGENTS.md` §7)."""


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """One billable call, in the form both the live source and the cassette understand."""

    queries: tuple[str, ...]
    objective: str
    include_domains: tuple[str, ...]
    after_date: str | None = None
    session_id: str | None = None

    @property
    def key(self) -> str:
        """Stable identity of this request, for recording and replay.

        `session_id` is excluded: it threads calls within one run for result quality, so
        including it would make every recording a miss on the next run.
        """
        canonical = json.dumps(
            {
                "queries": list(self.queries),
                "objective": self.objective,
                "include_domains": sorted(self.include_domains),
                "after_date": self.after_date,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class RawResult:
    """One result, exactly as retrieved — before any tier is attached.

    Ours rather than the SDK's `WebSearchResult` so the cassette, the tests and the ledger
    conversion all work with `parallel` uninstalled.
    """

    url: str
    excerpts: tuple[str, ...]
    title: str | None = None
    publish_date: str | None = None  # YYYY-MM-DD, when the publisher declares one


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Results plus what the call cost. Usage is part of the return, not a side channel.

    Parallel meters more than one SKU — a call that returned 20 results billed
    `sku_search: 1` *and* `sku_extract_excerpts: 10` (measured Aug 23, 2026) — so a perimeter
    that hands back only results makes its own bill unobservable to the thing paying it.
    """

    results: tuple[RawResult, ...]
    usage: tuple[tuple[str, int], ...] = ()
    search_id: str | None = None
    session_id: str | None = None


@runtime_checkable
class SearchSource(Protocol):
    """Where results come from. Live or recorded — no stage can tell which."""

    def run(self, request: SearchRequest) -> SearchOutcome: ...


class ParallelSearch:
    """Live retrieval over `parallel-web`. The only outbound call in the system."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
        http_client: Any | None = None,
    ) -> None:
        self.api_key = api_key  # None => the SDK reads PARALLEL_API_KEY itself
        self.timeout = timeout
        self.max_retries = max_retries
        # Only for tests: an `httpx.Client` on a mock transport asserts the request body
        # without a network call or a billed `sku_search`. Typed loosely so this module still
        # imports with `httpx` absent.
        self.http_client = http_client
        self.last_search_id: str | None = None
        self.last_session_id: str | None = None

    def run(self, request: SearchRequest) -> SearchOutcome:
        # Deferred: importing the SDK at module top would drag it into every cold start and
        # into the dependency-free test path (`AGENTS.md` §7).
        # Exceptions from the package root, not `parallel._exceptions`: the root lists them in
        # an explicit `__all__`, so this is a public re-export mypy strict accepts — unlike
        # ADK's lazy mapping, which is not (`AGENTS.md` §6). And `SourcePolicy` from
        # `shared_params`, because `parallel.types.SourcePolicy` is the response model of the
        # same name and is not accepted here.
        from parallel import (
            AuthenticationError,
            BadRequestError,
            NotFoundError,
            Parallel,
            PermissionDeniedError,
            UnprocessableEntityError,
            omit,
        )
        from parallel.types import AdvancedSearchSettingsParam
        from parallel.types.shared_params import SourcePolicy

        # `api_key=None` is the SDK's own "read PARALLEL_API_KEY from the environment".
        # `max_retries` is set here rather than left at the SDK's 2: it is half of what bounds
        # how long a search can run, and the per-call `timeout` alone does not bound anything.
        client = Parallel(
            api_key=self.api_key,
            max_retries=self.max_retries,
            http_client=self.http_client,
        )
        policy: SourcePolicy = {"include_domains": list(request.include_domains)}
        if request.after_date:
            policy["after_date"] = request.after_date
        settings: AdvancedSearchSettingsParam = {"source_policy": policy}

        try:
            result = client.search(
                search_queries=list(request.queries),
                objective=request.objective,
                advanced_settings=settings,
                # Threads a run's calls together; the server generates one if we omit it —
                # and `omit` is not `None`, which would send an explicit null instead.
                session_id=request.session_id if request.session_id else omit,
                timeout=self.timeout,
            )
        except (
            BadRequestError,
            AuthenticationError,
            NotFoundError,
            PermissionDeniedError,
            UnprocessableEntityError,
        ) as exc:
            # A malformed request or a dead key does not get better on the third attempt.
            # 429 and 5xx and connection errors are deliberately absent: the SDK already
            # retries those twice itself, and past that ADK should see the exception.
            raise SearchError(f"{type(exc).__name__}: {exc}") from exc

        self.last_search_id = result.search_id
        self.last_session_id = result.session_id
        return SearchOutcome(
            results=tuple(
                RawResult(
                    url=item.url,
                    excerpts=tuple(item.excerpts),
                    title=item.title,
                    publish_date=item.publish_date,
                )
                for item in result.results
            ),
            usage=tuple((item.name, item.count) for item in (result.usage or [])),
            search_id=result.search_id,
            session_id=result.session_id,
        )


class RecordedSearch:
    """Replays a cassette of past searches — the deterministic fallback (`CLAUDE.md` §3).

    A demo must not break because a key expired or a quota ran out, and retrieval is the one
    perimeter with no local equivalent: there is no offline web. So a live run can be recorded
    and replayed byte-for-byte, which also makes every stage downstream of Research testable
    without spending a `sku_search` per assertion.

    The cassette holds third-party web excerpts, so it is **not committed** — see `.gitignore`.
    A fresh clone has no recording and must run live or supply its own.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        self._entries: dict[str, Any] = raw.get("searches", {})

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def run(self, request: SearchRequest) -> SearchOutcome:
        entry = self._entries.get(request.key)
        if entry is None:
            raise SearchError(
                f"no recording for this search ({request.key}); "
                f"the cassette at {self.path} holds {len(self._entries)}"
            )
        return SearchOutcome(
            results=tuple(
                RawResult(
                    url=item["url"],
                    excerpts=tuple(item["excerpts"]),
                    title=item.get("title"),
                    publish_date=item.get("publish_date"),
                )
                for item in entry["results"]
            ),
            # Replayed as recorded, and never re-billed: a cassette hit costs nothing, and
            # reporting the original usage is what keeps a replayed run's cost legible.
            usage=tuple((name, count) for name, count in entry.get("usage", [])),
            search_id=entry.get("search_id"),
            session_id=entry.get("session_id"),
        )

    @staticmethod
    def record(path: Path, request: SearchRequest, outcome: SearchOutcome) -> None:
        """Append one live outcome to a cassette, creating it if absent."""
        store: dict[str, Any] = {"searches": {}}
        if path.exists():
            store = json.loads(path.read_text(encoding="utf-8"))
            store.setdefault("searches", {})
        store["searches"][request.key] = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "request": {
                "queries": list(request.queries),
                "objective": request.objective,
                "include_domains": sorted(request.include_domains),
                "after_date": request.after_date,
            },
            "usage": [list(item) for item in outcome.usage],
            "search_id": outcome.search_id,
            "session_id": outcome.session_id,
            "results": [
                {
                    "url": r.url,
                    "excerpts": list(r.excerpts),
                    "title": r.title,
                    "publish_date": r.publish_date,
                }
                for r in outcome.results
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True, slots=True)
class WebSearch:
    """Retrieval under one wiki's source policy.

    The profile is bound and the tier table travels with it, so swapping wikis swaps what the
    agent is allowed to read as well as how it scores what comes back (`summary.md` §6).
    """

    profile: WikiProfile
    source: SearchSource
    session_id: str | None = None

    @classmethod
    def live(cls, profile: WikiProfile, *, session_id: str | None = None) -> WebSearch:
        return cls(profile, ParallelSearch(), session_id=session_id)

    @classmethod
    def recorded(cls, profile: WikiProfile, cassette: Path) -> WebSearch:
        return cls(profile, RecordedSearch(cassette))

    # -- the tool -------------------------------------------------------------------

    def search(
        self, search_queries: list[str], objective: str, after_date: str = ""
    ) -> dict[str, Any]:
        """Search the web for evidence about one claim, restricted to sources this wiki trusts.

        Pass every angle on the claim in a single call: one call is billed the same whether it
        carries one query or four, and the results come back merged and ranked together.

        Args:
          search_queries: 2-3 concise keyword queries, 3-6 words each.
          objective: the question behind the search, self-contained enough to read alone.
          after_date: optional `YYYY-MM-DD`; only sources published on or after it. Use the
            claim's `as_of` when checking whether something has changed since it was recorded.
        """
        request = SearchRequest(
            queries=tuple(search_queries),
            objective=objective,
            include_domains=self.profile.include_domains,
            after_date=after_date or None,
            session_id=self.session_id,
        )
        retrieved_at = datetime.now(timezone.utc)
        try:
            outcome = self.source.run(request)
        except SearchError as exc:
            # Terminal by construction (`ParallelSearch.run`): transport failures never
            # become `SearchError`, so they are still propagating past this line.
            return {"error": str(exc), "objective": objective, "queries": search_queries}

        scored = [
            {
                "url": result.url,
                "title": result.title,
                "domain": tiers.registrable_domain(result.url, self.profile.domain_tiers),
                "tier": tiers.tier_for(result.url, self.profile.domain_tiers),
                "publish_date": result.publish_date,
                "excerpts": list(result.excerpts),
            }
            for result in outcome.results
        ]
        return {
            "wiki": self.profile.name,
            "objective": objective,
            "queries": search_queries,
            "after_date": after_date or None,
            "retrieved_at": retrieved_at.isoformat(),
            "include_domains": list(request.include_domains),
            "search_id": outcome.search_id,
            # What this call actually metered. Parallel bills more than one SKU and the second
            # one scales with results, so a caller reasoning about cost needs the real numbers
            # rather than the "one sku_search per call" half of the story.
            "usage": {name: count for name, count in outcome.usage},
            "results": scored,
            # The shape §12 measures retrieval quality by; cheap to carry and the one number
            # that says at a glance whether the source policy did its job. Keys are strings
            # because JSON object keys are: left as ints, this dict comes back from ADK's
            # serialisation different from how the node built it.
            "tier_counts": {
                str(tier): count
                for tier, count in sorted(Counter(r["tier"] for r in scored).items())
            },
        }


def sources_in(payload: dict[str, Any]) -> tuple[Source, ...]:
    """Ledger records from a `WebSearch.search` payload. Pure — no second call, no re-billing.

    Tier and domain are already resolved in the payload, so this needs no profile and cannot
    disagree with what the model was shown.

    **An errored payload raises, and that is a reversal.** This used to return `()` on the
    reasoning that a failed search is a claim with no new evidence rather than a crash. That
    was true until `ClaimStatus` collapsed to two values: "no new evidence" now routes to
    `unchanged`, which *doubles* the recheck interval — so an expired key or a cassette miss
    would quietly make the agent look at that claim less often, and nothing would report it.
    An infrastructure failure must not be recorded as a finding about the world. A search that
    genuinely returned nothing still yields `()`, because that is a real answer; the two are
    distinguishable in the payload and must stay distinguishable here.

    Discard the round instead: write nothing to the ledger, leave the claim's schedule and its
    research budget untouched, and let it come due again (`AGENTS.md` §7).
    """
    if "error" in payload:
        raise SearchError(
            f"search failed, so there is nothing to record: {payload['error']}. "
            "Discard the round — do not write it to the ledger as a finding."
        )
    if "results" not in payload:
        return ()
    retrieved_at = datetime.fromisoformat(payload["retrieved_at"])
    return tuple(
        Source(
            url=result["url"],
            excerpt="\n\n".join(result["excerpts"]),
            retrieved_at=retrieved_at,
            as_of=_as_of(result.get("publish_date")),
            tier=result["tier"],
            domain=result["domain"],
        )
        for result in payload["results"]
    )


def _as_of(publish_date: str | None) -> datetime | None:
    """`YYYY-MM-DD` -> UTC midnight. Absent or malformed dates are simply unknown: the
    publisher's own date is optional and `source_policy.after_date` is the reliable filter."""
    if not publish_date:
        return None
    try:
        return datetime.strptime(publish_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
