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
import http.cookiejar
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


def format_timestamp(when: datetime) -> str:
    """The inverse. MediaWiki wants `Z`, and `isoformat()` writes `+00:00` — which `rvstart`
    tolerates and `basetimestamp` on an edit does not, so the two are not interchangeable."""
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    """A page was missing, or the API answered in a shape we refuse to guess about.

    `code` carries MediaWiki's own machine-readable error code when there was one. Callers need
    it because the API reports outcomes that are not all the same kind of thing: `editconflict`
    means re-read and re-draft, `protectedpage` means give up, `badtoken` means the session is
    wrong. Matching on the human-readable message instead is how those get conflated.
    """

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


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
        params["rvstart"] = format_timestamp(before)
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


#: Where the wiki credential travels. A header rather than a query parameter because a URL is
#: logged by every proxy it passes and shows up in error messages; a header is not. MediaWiki
#: itself ignores this today (see `AGENTS.md` §2) — the gate is ours, and it is what makes the
#: agent reach its own wiki the way it reaches anything external.
API_KEY_HEADER = "X-API-Key"


class MediaWikiReader:
    """Thin read client. One method that touches the network, so it is the only thing to
    stub when the pipeline is tested offline."""

    def __init__(self, api_url: str, *, user_agent: str, timeout: float = 30.0,
                 api_key: str | None = None) -> None:
        self.api_url = api_url
        self.user_agent = user_agent
        self.timeout = timeout
        self.api_key = api_key

    @classmethod
    def for_profile(cls, profile: WikiProfile, *, timeout: float = 30.0,
                    api_key: str | None = None) -> MediaWikiReader:
        """The normal way to build one — endpoint and User-Agent both come from the wiki.

        Refuses to build against a gated endpoint with no key, the same way the writer refuses
        a profile that is not writable: a misconfiguration should be an exception at
        construction, not an unauthorised request at the first read.
        """
        if profile.requires_key and not api_key:
            raise WikiError(
                f"{profile.name} requires an API key and none was supplied. Read it from "
                f"MEDIAWIKI_API_KEY and pass it in; it is never stored on a profile."
            )
        return cls(profile.api_url, user_agent=profile.user_agent, timeout=timeout,
                   api_key=api_key)

    def headers(self) -> dict[str, str]:
        """What goes on the wire. The key is a header, never a query parameter — a URL ends up
        in access logs, browser history and error messages, and this one is a credential."""
        sent = {"User-Agent": self.user_agent}
        if self.api_key:
            sent[API_KEY_HEADER] = self.api_key
        return sent

    def fetch(self, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers=self.headers())
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        parsed: dict[str, Any] = json.loads(body)
        if "error" in parsed:
            error = parsed["error"]
            raise WikiError(f"API error: {error}", code=str(error.get("code", "")))
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


class MediaWikiWriter:
    """Write-side adapter: log in, hold the session, and edit.

    Separate from `MediaWikiReader` because writing needs three things reading does not — a
    logged-in session, a CSRF token, and a cookie jar to carry both. Reads stay anonymous and
    stateless, which is why the reader can be pointed at Fandom and this cannot.

    **Only ever constructed against our own instance.** `for_profile` refuses a profile whose
    `writable` is false, which is every profile we ship except `local_wiki()`. `AGENTS.md` §2
    forbids writing to a real wiki, and an unsanctioned bot edit gets the account banned — so
    that rule is a raised exception here, not a line in a document.

    Network is confined to `post`, mirroring the reader's `fetch`, so everything above it is
    testable without a socket.
    """

    def __init__(self, api_url: str, *, user_agent: str, timeout: float = 30.0,
                 api_key: str | None = None) -> None:
        self.api_url = api_url
        self.user_agent = user_agent
        self.timeout = timeout
        self.api_key = api_key
        self._csrf: str | None = None
        # MediaWiki carries the login session in cookies; urlopen alone drops them.
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    @classmethod
    def for_profile(cls, profile: WikiProfile, *, timeout: float = 30.0,
                    api_key: str | None = None) -> MediaWikiWriter:
        if not profile.writable:
            raise WikiError(
                f"{profile.name} is not writable. Writes go only to our own seeded instance "
                f"(`AGENTS.md` §2); build the profile with `local_wiki()`."
            )
        if profile.requires_key and not api_key:
            raise WikiError(
                f"{profile.name} requires an API key and none was supplied. Read it from "
                f"MEDIAWIKI_API_KEY and pass it in; it is never stored on a profile."
            )
        return cls(profile.api_url, user_agent=profile.user_agent, timeout=timeout,
                   api_key=api_key)

    def headers(self) -> dict[str, str]:
        """Same contract as the reader's: the key rides a header, never the URL."""
        sent = {"User-Agent": self.user_agent}
        if self.api_key:
            sent[API_KEY_HEADER] = self.api_key
        return sent

    def post(self, params: dict[str, str]) -> dict[str, Any]:
        """The only method that opens a socket."""
        body = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
        request = urllib.request.Request(
            self.api_url, data=body.encode("utf-8"), headers=self.headers()
        )
        with self._opener.open(request, timeout=self.timeout) as response:
            parsed: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        if "error" in parsed:
            error = parsed["error"]
            raise WikiError(f"API error: {error}", code=str(error.get("code", "")))
        return parsed

    def token(self, kind: str) -> str:
        """Fetch a token. `login` before logging in, `csrf` after — they are not the same and
        a csrf token issued to an anonymous session is silently useless."""
        payload = self.post({"action": "query", "meta": "tokens", "type": kind})
        token: str = payload["query"]["tokens"][f"{kind}token"]
        return token

    def login(self, username: str, password: str) -> str:
        """Log in with a BotPassword — `User@appid` plus its generated secret.

        Main-account API login is deprecated and refused on current MediaWiki; a BotPassword is
        the supported path and is separately revocable, which is why the seeder gets one rather
        than the admin's own credentials.
        """
        payload = self.post({
            "action": "login",
            "lgname": username,
            "lgpassword": password,
            "lgtoken": self.token("login"),
        })
        result = payload.get("login", {})
        if result.get("result") != "Success":
            # Never interpolate the password, and MediaWiki does not echo it either.
            raise WikiError(f"login failed for {username}: {result.get('reason', result)}")
        self._csrf = None  # tokens are session-scoped; the old one belongs to the anon session
        return str(result.get("lgusername", username))

    @property
    def csrf(self) -> str:
        """Cached edit token. One per session, reused across edits."""
        if self._csrf is None:
            self._csrf = self.token("csrf")
        return self._csrf

    def edit(
        self,
        title: str,
        text: str,
        *,
        summary: str,
        section: int | None = None,
        basetimestamp: datetime | None = None,
        bot: bool = True,
    ) -> dict[str, Any]:
        """Write `text`, to a whole page or to one section of it.

        `basetimestamp` is the edit-conflict guard: it is the timestamp of the revision the
        text was derived from, and MediaWiki refuses the edit if anything landed since. Passing
        it is the difference between failing loudly and silently overwriting someone
        (`AGENTS.md` §2), which is why both read calls return the revision they came from.

        `section` addresses the heading's own index, never the subtree — re-resolve it from
        the stored heading first, because indices shift when anything is inserted above.
        """
        params = {
            "action": "edit",
            "title": title,
            "text": text,
            "summary": summary,
            "token": self.csrf,
        }
        if section is not None:
            params["section"] = str(section)
        if basetimestamp is not None:
            params["basetimestamp"] = format_timestamp(basetimestamp)
        if bot:
            params["bot"] = "1"
        result: dict[str, Any] = self.post(params).get("edit", {})
        if result.get("result") != "Success":
            raise WikiError(
                f"edit of {title!r} failed: {result}", code=str(result.get("code", ""))
            )
        return result
