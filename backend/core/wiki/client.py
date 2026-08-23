"""Read-side MediaWiki adapter.

The only route to page text: `Special:Export` sits behind Cloudflare on Fandom and returns a
challenge page instead of XML (`AGENTS.md` §6), so `api.php` is it.

Network lives in `fetch`; everything else here is pure and tested without a socket
(`CLAUDE.md` §3). Two behaviours are load-bearing rather than incidental, and both are
enforced here so no caller can forget them:

* `redirects=1` on every title lookup, with the redirect recorded — two of the seed pages
  resolve somewhere else, and silently seeding the wrong page is the failure mode
  (`AGENTS.md` §6).
* a real `User-Agent`, because Fandom throttles anonymous defaults.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..profile import WikiProfile

# The User-Agent and the endpoint both moved onto the profile (`backend.core.profile`): which
# wiki we read and how we identify ourselves to it are per-wiki facts, and a default here is
# how the MCU endpoint would end up being used against another wiki without anyone noticing.

# Anything outside this becomes "_". Titles carry "&", "/", spaces and parentheses; the
# manifest keeps the true title, so the filename only has to be stable and shell-safe.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slug_for(title: str) -> str:
    """Filesystem-safe stem for a page title. Not reversible — the manifest is."""
    return _UNSAFE.sub("_", title).strip("_")


def parse_timestamp(raw: str) -> datetime:
    """MediaWiki ISO-8601. `datetime.fromisoformat` only accepts the `Z` suffix on 3.11+."""
    return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class PageRevision:
    """One revision's wikitext, plus everything needed to prove where it came from."""

    requested_title: str
    resolved_title: str
    redirected_from: str | None
    pageid: int
    revid: int
    timestamp: datetime
    user: str
    comment: str
    content: str

    @property
    def size(self) -> int:
        """Bytes as MediaWiki counts them — UTF-8, not characters."""
        return len(self.content.encode("utf-8"))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def slug(self) -> str:
        return slug_for(self.resolved_title)


class WikiError(RuntimeError):
    """A page was missing, or the API answered in a shape we refuse to guess about."""


def build_query(
    title: str,
    *,
    before: datetime | None = None,
) -> dict[str, str]:
    """Query for one revision's content: the latest, or the last one at/before `before`.

    `rvslots=main` is required from MediaWiki 1.32 on — content lives in slots now, and
    omitting it earns a deprecation warning and no text.
    """
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "redirects": "1",
        "rvlimit": "1",
        "rvprop": "ids|timestamp|user|comment|content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
    }
    if before is not None:
        params["rvstart"] = before.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params["rvdir"] = "older"
    return params


def parse_revision(payload: dict[str, Any], requested_title: str) -> PageRevision:
    """Pull one `PageRevision` out of an action-API response.

    Raises rather than returning a partial record: a snapshot missing its text is worse than
    no snapshot, because it looks like a successful pull.
    """
    query = payload.get("query")
    if not query:
        raise WikiError(f"{requested_title}: no query block in response")

    # formatversion=2 gives a list, and reports misses with an explicit flag.
    pages = query.get("pages") or []
    if not pages:
        raise WikiError(f"{requested_title}: no pages in response")
    page = pages[0]
    if page.get("missing"):
        raise WikiError(f"{requested_title}: page does not exist")

    resolved = page["title"]
    redirected_from = next(
        (r["from"] for r in query.get("redirects", []) if r["to"] == resolved), None
    )

    revisions = page.get("revisions") or []
    if not revisions:
        raise WikiError(f"{requested_title}: no revision at the requested point in history")
    rev = revisions[0]

    content = rev.get("slots", {}).get("main", {}).get("content")
    if content is None:
        raise WikiError(f"{requested_title}: revision {rev.get('revid')} returned no content")

    return PageRevision(
        requested_title=requested_title,
        resolved_title=resolved,
        redirected_from=redirected_from,
        pageid=page["pageid"],
        revid=rev["revid"],
        timestamp=parse_timestamp(rev["timestamp"]),
        user=rev.get("user", ""),
        comment=rev.get("comment", ""),
        content=content,
    )


class MediaWikiReader:
    """Thin read client. One method that touches the network, so it is the only thing to
    stub when the pipeline is tested offline."""

    def __init__(self, api_url: str, *, user_agent: str, timeout: float = 30.0) -> None:
        self.api_url = api_url
        self.user_agent = user_agent
        self.timeout = timeout

    @classmethod
    def for_profile(cls, profile: WikiProfile, *, timeout: float = 30.0) -> MediaWikiReader:
        """The normal way to build one — endpoint and User-Agent both come from the wiki."""
        return cls(profile.api_url, user_agent=profile.user_agent, timeout=timeout)

    def fetch(self, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        parsed: dict[str, Any] = json.loads(body)
        if "error" in parsed:
            raise WikiError(f"API error: {parsed['error']}")
        return parsed

    def revision(self, title: str, *, before: datetime | None = None) -> PageRevision:
        return parse_revision(self.fetch(build_query(title, before=before)), title)

    def rights_info(self) -> dict[str, Any]:
        """Licence as the wiki self-declares it. Returned unversioned by this wiki, which is
        exactly why the answer gets recorded rather than assumed (`seed-plan.md` §7)."""
        payload = self.fetch({
            "action": "query",
            "meta": "siteinfo",
            "siprop": "rightsinfo|general",
            "format": "json",
            "formatversion": "2",
        })
        query: dict[str, Any] = payload.get("query", {})
        return query
