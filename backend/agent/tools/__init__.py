"""The four tools the graph's nodes call: wiki read, web search, wiki write, ledger.

Every one of them binds a `WikiProfile` at construction rather than taking it as an argument.
That is not a style choice. A profile is not JSON-serialisable, so a model could not pass one
anyway — and a tool that let the model choose the wiki would hand it the decision the profile
exists to take away (`AGENTS.md` §2). The model chooses *what to read* and *what to ask*; the
profile decides *where from*, *which sources are allowed*, and *under whose rules*.

Each tool also has two sources behind one protocol: live, and a deterministic replay
(`CLAUDE.md` §3). Nothing downstream can tell which it is holding, which is what lets the whole
graph be built and tested before any credential or container exists.
"""

from .web_search import (
    MAX_RETRIES,
    TIMEOUT_SECONDS,
    ParallelSearch,
    RawResult,
    RecordedSearch,
    SearchError,
    SearchOutcome,
    SearchRequest,
    SearchSource,
    WebSearch,
    sources_in,
    worst_case_seconds,
)
from .wiki_read import WikiRead
from .wiki_write import CONFLICT_CODE, WikiWrite

__all__ = [
    "CONFLICT_CODE",
    "MAX_RETRIES",
    "TIMEOUT_SECONDS",
    "ParallelSearch",
    "RawResult",
    "RecordedSearch",
    "SearchError",
    "SearchOutcome",
    "SearchRequest",
    "SearchSource",
    "WebSearch",
    "WikiRead",
    "WikiWrite",
    "sources_in",
    "worst_case_seconds",
]
