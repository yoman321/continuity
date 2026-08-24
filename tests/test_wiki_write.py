"""The write adapter: who it refuses, and what it puts on the wire.

Two things here are invariants rather than behaviour:

* **`AGENTS.md` §2 — never write to a real wiki — is a raised exception, not a document.**
  `for_profile` refuses any profile whose `writable` is false, which is every profile we ship
  except `local_wiki()`. An unsanctioned bot edit gets the account banned, so the check belongs
  where a writer is built rather than in a reviewer's memory.
* **`basetimestamp` is the edit-conflict guard.** Omitting it turns a conflict into a silent
  overwrite of whoever edited in between, which is why both read calls return the revision
  they came from.

Network is confined to `post`, so everything above it is tested by replacing that one method.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from backend.core.profile import MCU_FANDOM, PROFILES, WIKIPEDIA_EN, local_wiki
from backend.core.wiki import MediaWikiWriter, WikiError

API = "http://wiki.invalid/api.php"
OURS = local_wiki(API)
SECRET = "0123456789abcdef0123456789abcdef"


class Recording(MediaWikiWriter):
    """A writer whose only socket is replaced by a script of canned answers."""

    def __init__(self, answers: list[dict[str, Any]] | None = None) -> None:
        super().__init__(API, user_agent="test-agent")
        self.posted: list[dict[str, str]] = []
        self.answers = answers or []

    def post(self, params: dict[str, str]) -> dict[str, Any]:
        self.posted.append(dict(params))
        if self.answers:
            return self.answers.pop(0)
        if params.get("action") == "query":
            kind = params.get("type", "csrf")
            return {"query": {"tokens": {f"{kind}token": f"{kind}-token+\\"}}}
        if params.get("action") == "login":
            return {"login": {"result": "Success", "lgusername": "TestBot"}}
        return {"edit": {"result": "Success", "newrevid": 42}}


def logged_in(answers: list[dict[str, Any]] | None = None) -> Recording:
    """A writer past the login dance. Scripted answers are installed *after* it, so they
    apply to the edit under test rather than being eaten by the token exchange."""
    writer = Recording()
    writer.login("TestBot@testapp", SECRET)
    _ = writer.csrf  # fetched lazily inside edit(), so prime it before scripting answers
    writer.posted.clear()
    writer.answers = answers or []
    return writer


class TestWriteGuard(unittest.TestCase):
    def test_no_shipped_profile_can_build_a_writer(self) -> None:
        for name, profile in PROFILES.items():
            with self.subTest(profile=name), self.assertRaises(WikiError):
                MediaWikiWriter.for_profile(profile)

    def test_the_refusal_names_the_wiki_and_the_way_out(self) -> None:
        with self.assertRaises(WikiError) as caught:
            MediaWikiWriter.for_profile(WIKIPEDIA_EN)
        self.assertIn("English Wikipedia", str(caught.exception))
        self.assertIn("local_wiki()", str(caught.exception))

    def test_our_own_instance_is_accepted(self) -> None:
        writer = MediaWikiWriter.for_profile(OURS)
        self.assertEqual(writer.api_url, API)
        self.assertEqual(writer.user_agent, OURS.user_agent)

    def test_reading_fandom_stays_allowed(self) -> None:
        """The guard is on writing only — the agent reads real wikis constantly."""
        from backend.core.wiki import MediaWikiReader

        self.assertEqual(MediaWikiReader.for_profile(MCU_FANDOM).api_url, MCU_FANDOM.api_url)


class TestLogin(unittest.TestCase):
    def test_a_login_token_is_fetched_before_the_login(self) -> None:
        writer = Recording()
        writer.login("TestBot@testapp", SECRET)
        self.assertEqual(
            [(p.get("action"), p.get("type", "")) for p in writer.posted],
            [("query", "login"), ("login", "")],
        )
        self.assertEqual(writer.posted[1]["lgtoken"], "login-token+\\")

    def test_a_failed_login_raises_without_echoing_the_password(self) -> None:
        writer = Recording([
            {"query": {"tokens": {"logintoken": "t"}}},
            {"login": {"result": "Failed", "reason": "Incorrect username or password"}},
        ])
        with self.assertRaises(WikiError) as caught:
            writer.login("TestBot@testapp", SECRET)
        self.assertIn("Incorrect username", str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))

    def test_the_anonymous_csrf_token_is_discarded_on_login(self) -> None:
        """A csrf token issued before login belongs to the anonymous session and is silently
        useless afterwards — the edit fails with `badtoken`, long after the cause."""
        writer = Recording()
        self.assertEqual(writer.csrf, "csrf-token+\\")
        writer.login("TestBot@testapp", SECRET)
        writer.posted.clear()
        _ = writer.csrf
        self.assertEqual([p["action"] for p in writer.posted], ["query"])


class TestEdit(unittest.TestCase):
    def test_a_whole_page_edit_carries_no_section(self) -> None:
        writer = logged_in()
        writer.edit("Gambit", "text", summary="seeded")
        sent = writer.posted[-1]
        self.assertEqual(sent["action"], "edit")
        self.assertEqual(sent["title"], "Gambit")
        self.assertNotIn("section", sent)
        self.assertEqual(sent["bot"], "1")

    def test_a_section_edit_addresses_one_index(self) -> None:
        writer = logged_in()
        writer.edit("Gambit", "text", summary="s", section=3)
        self.assertEqual(writer.posted[-1]["section"], "3")

    def test_section_zero_is_the_lead_and_not_omitted(self) -> None:
        """`if section:` would drop the lead — index 0 is a real section, and the infobox
        lives in it."""
        writer = logged_in()
        writer.edit("Gambit", "text", summary="s", section=0)
        self.assertEqual(writer.posted[-1]["section"], "0")

    def test_basetimestamp_goes_out_in_mediawikis_own_format(self) -> None:
        """`isoformat()` writes `+00:00`, which `basetimestamp` rejects."""
        writer = logged_in()
        writer.edit(
            "Gambit", "text", summary="s",
            basetimestamp=datetime(2024, 8, 8, 23, 57, 40, tzinfo=timezone.utc),
        )
        self.assertEqual(writer.posted[-1]["basetimestamp"], "2024-08-08T23:57:40Z")

    def test_no_basetimestamp_means_no_conflict_guard_is_claimed(self) -> None:
        writer = logged_in()
        writer.edit("Gambit", "text", summary="s")
        self.assertNotIn("basetimestamp", writer.posted[-1])

    def test_a_rejected_edit_raises_rather_than_returning_quietly(self) -> None:
        writer = logged_in([{"edit": {"result": "Failure", "code": "editconflict"}}])
        with self.assertRaises(WikiError) as caught:
            writer.edit("Gambit", "text", summary="s")
        self.assertIn("editconflict", str(caught.exception))

    def test_the_edit_token_is_fetched_once_and_reused(self) -> None:
        """Built without the helper so the whole sequence is visible: one csrf query, then
        every edit after it rides the same token."""
        writer = Recording()
        writer.login("TestBot@testapp", SECRET)
        writer.posted.clear()
        writer.edit("Gambit", "a", summary="s")
        writer.edit("Wolverine", "b", summary="s")
        writer.edit("Deadpool", "c", summary="s")
        self.assertEqual(
            [p["action"] for p in writer.posted], ["query", "edit", "edit", "edit"]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
