"""The Parallel search tool: what it costs, what it is allowed to read, and who scores it.

Three properties here are the reason retrieval is a tool and not a function call:

* **One call per claim, however many queries it carries.** Parallel bills per call, so a tool
  that took a single query would quietly quadruple the cost of a fan-out.
* **The allowlist is not a parameter.** It comes off the profile every time, because the tier
  table is the retrieval policy and not just a scoring function (`AGENTS.md` §7).
* **Tier is a property of the wiki's policy, not of the URL.** `marvel.com` is tier 1 to the
  MCU wiki and tier 4 to Wikipedia — same bytes, different authority, no model involved.

Everything runs offline against a fake source; nothing here spends a `sku_search`.
"""

from __future__ import annotations

import inspect
import json
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, get_type_hints

from backend.agent.tools import (
    MAX_RETRIES,
    TIMEOUT_SECONDS,
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
from backend.core.profile import MCU_FANDOM, WIKIPEDIA_EN

RESULTS = (
    RawResult(
        url="https://www.marvel.com/movies/deadpool-and-wolverine",
        excerpts=("Gambit appears in the film.", "Channing Tatum plays Gambit."),
        title="Deadpool & Wolverine",
        publish_date="2024-07-26",
    ),
    RawResult(
        url="https://someone.tumblr.com/post/12345",
        excerpts=("i heard gambit is in doomsday",),
        title=None,
        publish_date=None,
    ),
)


class Fake:
    """Records what it was asked and answers with fixed results. Counts calls, because the
    call count *is* the bill."""

    def __init__(self, results: tuple[RawResult, ...] = RESULTS) -> None:
        self.results = results
        self.requests: list[SearchRequest] = []

    def run(self, request: SearchRequest) -> SearchOutcome:
        self.requests.append(request)
        return SearchOutcome(
            results=self.results,
            usage=(("sku_search", 1), ("sku_extract_excerpts", len(self.results))),
            search_id="search_fake",
        )


class Terminal:
    """A dead key or a malformed request: no amount of retrying helps."""

    def run(self, request: SearchRequest) -> SearchOutcome:
        raise SearchError("AuthenticationError: invalid x-api-key")


class Unreachable:
    """The network is down. Deliberately not a `SearchError`."""

    def run(self, request: SearchRequest) -> SearchOutcome:
        raise urllib.error.URLError("connection refused")


class TestBilling(unittest.TestCase):
    def test_every_query_for_a_claim_rides_one_call(self) -> None:
        fake = Fake()
        WebSearch(MCU_FANDOM, fake).search(
            search_queries=["gambit doomsday casting", "channing tatum avengers", "gambit mcu"],
            objective="Has Gambit been cast in anything since Deadpool & Wolverine?",
        )
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(len(fake.requests[0].queries), 3)


class TestSourcePolicy(unittest.TestCase):
    def test_the_allowlist_comes_from_the_profile_not_the_caller(self) -> None:
        fake = Fake()
        WebSearch(MCU_FANDOM, fake).search(search_queries=["q"], objective="o")
        self.assertEqual(fake.requests[0].include_domains, MCU_FANDOM.include_domains)
        self.assertNotIn("include_domains", inspect.signature(WebSearch.search).parameters)

    def test_swapping_the_wiki_swaps_what_the_agent_may_read(self) -> None:
        fandom, wikipedia = Fake(), Fake()
        WebSearch(MCU_FANDOM, fandom).search(search_queries=["q"], objective="o")
        WebSearch(WIKIPEDIA_EN, wikipedia).search(search_queries=["q"], objective="o")
        self.assertNotEqual(
            fandom.requests[0].include_domains, wikipedia.requests[0].include_domains
        )
        self.assertIn("marvel.com", fandom.requests[0].include_domains)
        self.assertNotIn("marvel.com", wikipedia.requests[0].include_domains)

    def test_after_date_is_sent_only_when_given(self) -> None:
        fake = Fake()
        tool = WebSearch(MCU_FANDOM, fake)
        tool.search(search_queries=["q"], objective="o")
        tool.search(search_queries=["q"], objective="o", after_date="2024-08-09")
        self.assertIsNone(fake.requests[0].after_date)
        self.assertEqual(fake.requests[1].after_date, "2024-08-09")


class TestScoring(unittest.TestCase):
    def test_the_same_url_scores_differently_per_wiki(self) -> None:
        """Tier is the wiki's policy, not a property of the publisher."""
        fandom = WebSearch(MCU_FANDOM, Fake()).search(search_queries=["q"], objective="o")
        wikipedia = WebSearch(WIKIPEDIA_EN, Fake()).search(search_queries=["q"], objective="o")
        self.assertEqual(fandom["results"][0]["tier"], 1)
        self.assertEqual(wikipedia["results"][0]["tier"], 4)
        self.assertEqual(fandom["results"][0]["domain"], "marvel.com")

    def test_a_social_host_absent_from_the_table_falls_to_general_press(self) -> None:
        """`AGENTS.md` §7, stated as a rule and asserted here: unknown is tier 4, which skips
        the social cap. Add hosts to the table as they appear."""
        fandom = WebSearch(MCU_FANDOM, Fake()).search(search_queries=["q"], objective="o")
        wikipedia = WebSearch(WIKIPEDIA_EN, Fake()).search(search_queries=["q"], objective="o")
        self.assertEqual(fandom["results"][1]["tier"], 5)  # tumblr.com is in the MCU table
        self.assertEqual(wikipedia["results"][1]["tier"], 4)  # and absent from Wikipedia's

    def test_tier_counts_summarise_the_batch_with_json_safe_keys(self) -> None:
        """String keys, because JSON object keys are strings: int keys would come back from
        ADK's serialisation as something the node did not send."""
        payload = WebSearch(MCU_FANDOM, Fake()).search(search_queries=["q"], objective="o")
        self.assertEqual(payload["tier_counts"], {"1": 1, "5": 1})

    def test_excerpts_stay_separate(self) -> None:
        """Merging them would place two unrelated passages adjacent, which is the same
        false-adjacency failure `AGENTS.md` §7 records for scraped tables."""
        payload = WebSearch(MCU_FANDOM, Fake()).search(search_queries=["q"], objective="o")
        self.assertEqual(len(payload["results"][0]["excerpts"]), 2)

    def test_the_payload_reports_what_the_call_metered(self) -> None:
        """Parallel bills more than one SKU and the second scales with results (measured
        Aug 23, 2026: 20 results billed `sku_search: 1` and `sku_extract_excerpts: 10`), so a
        payload that reported only results would make its own cost unobservable."""
        payload = WebSearch(MCU_FANDOM, Fake()).search(search_queries=["q"], objective="o")
        self.assertEqual(payload["usage"], {"sku_search": 1, "sku_extract_excerpts": 2})
        self.assertEqual(payload["search_id"], "search_fake")

    def test_a_replayed_search_reports_the_original_cost_and_bills_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "searches.json"
            request = SearchRequest(
                queries=("q",), objective="o", include_domains=MCU_FANDOM.include_domains
            )
            RecordedSearch.record(
                path, request, SearchOutcome(RESULTS, usage=(("sku_search", 1),))
            )
            payload = WebSearch(MCU_FANDOM, RecordedSearch(path)).search(
                search_queries=["q"], objective="o"
            )
            self.assertEqual(payload["usage"], {"sku_search": 1})

    def test_the_payload_survives_json_round_trip(self) -> None:
        payload = WebSearch(MCU_FANDOM, Fake()).search(search_queries=["q"], objective="o")
        self.assertEqual(json.loads(json.dumps(payload)), payload)


class TestFailureModes(unittest.TestCase):
    def test_a_dead_key_is_an_answer_not_an_exception(self) -> None:
        payload = WebSearch(MCU_FANDOM, Terminal()).search(search_queries=["q"], objective="o")
        self.assertIn("AuthenticationError", payload["error"])
        self.assertNotIn("results", payload)

    def test_a_network_failure_propagates_so_adk_can_retry(self) -> None:
        with self.assertRaises(urllib.error.URLError):
            WebSearch(MCU_FANDOM, Unreachable()).search(search_queries=["q"], objective="o")


class TestLedgerConversion(unittest.TestCase):
    def payload(self) -> dict[str, Any]:
        return WebSearch(MCU_FANDOM, Fake()).search(search_queries=["q"], objective="o")

    def test_sources_carry_the_tier_the_model_was_shown(self) -> None:
        payload = self.payload()
        sources = sources_in(payload)
        self.assertEqual([s.tier for s in sources], [r["tier"] for r in payload["results"]])
        self.assertEqual([s.domain for s in sources], ["marvel.com", "tumblr.com"])

    def test_publish_date_becomes_as_of_and_absence_stays_unknown(self) -> None:
        first, second = sources_in(self.payload())
        self.assertEqual(first.as_of, datetime(2024, 7, 26, tzinfo=timezone.utc))
        self.assertIsNone(second.as_of)

    def test_conversion_is_pure_and_bills_nothing(self) -> None:
        fake = Fake()
        payload = WebSearch(MCU_FANDOM, fake).search(search_queries=["q"], objective="o")
        sources_in(payload)
        sources_in(payload)
        self.assertEqual(len(fake.requests), 1)

    def test_an_errored_payload_yields_no_sources_rather_than_raising(self) -> None:
        payload = WebSearch(MCU_FANDOM, Terminal()).search(search_queries=["q"], objective="o")
        self.assertEqual(sources_in(payload), ())

    def test_the_excerpts_are_joined_only_at_the_ledger_boundary(self) -> None:
        first = sources_in(self.payload())[0]
        self.assertIn("Gambit appears in the film.", first.excerpt)
        self.assertIn("Channing Tatum plays Gambit.", first.excerpt)


class TestCassette(unittest.TestCase):
    def request(self, **over: Any) -> SearchRequest:
        base: dict[str, Any] = {
            "queries": ("gambit doomsday",),
            "objective": "is gambit cast",
            "include_domains": MCU_FANDOM.include_domains,
        }
        return SearchRequest(**{**base, **over})

    def test_a_recording_replays_byte_for_byte(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "searches.json"
            request = self.request()
            outcome = SearchOutcome(results=RESULTS, usage=(("sku_search", 1),))
            RecordedSearch.record(path, request, outcome)
            replayed = RecordedSearch(path).run(request)
            self.assertEqual(replayed.results, RESULTS)
            self.assertEqual(replayed.usage, (("sku_search", 1),))

    def test_the_key_ignores_session_but_not_the_question(self) -> None:
        """A session id threads one run's calls for result quality. Keying on it would make
        every recording a miss on the next run."""
        base = self.request()
        self.assertEqual(base.key, self.request(session_id="run-2").key)
        self.assertNotEqual(base.key, self.request(objective="something else").key)
        self.assertNotEqual(base.key, self.request(queries=("other query",)).key)
        self.assertNotEqual(base.key, self.request(after_date="2024-08-09").key)
        self.assertNotEqual(base.key, self.request(include_domains=("marvel.com",)).key)

    def test_a_miss_surfaces_as_an_error_value_naming_the_cassette(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "searches.json"
            RecordedSearch.record(path, self.request(), SearchOutcome(RESULTS))
            payload = WebSearch(MCU_FANDOM, RecordedSearch(path)).search(
                search_queries=["never recorded"], objective="o"
            )
            self.assertIn("no recording", payload["error"])
            self.assertIn(str(path), payload["error"])

    def test_recording_twice_accumulates_rather_than_overwrites(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "searches.json"
            RecordedSearch.record(path, self.request(), SearchOutcome(RESULTS))
            RecordedSearch.record(path, self.request(objective="second"), SearchOutcome(RESULTS))
            self.assertEqual(len(RecordedSearch(path).keys), 2)

    def test_both_sources_satisfy_the_protocol(self) -> None:
        from backend.agent.tools import ParallelSearch

        self.assertIsInstance(ParallelSearch(api_key="x"), SearchSource)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "searches.json"
            RecordedSearch.record(path, self.request(), SearchOutcome(()))
            self.assertIsInstance(RecordedSearch(path), SearchSource)


class TestDeadline(unittest.TestCase):
    """How long a search can take, measured rather than asserted in a comment.

    The per-attempt timeout bounds nothing on its own: the SDK retries timeouts as well as
    429s and 5xx, so the number that matters is the timeout multiplied by the attempts it
    makes without being asked. At the SDK's own defaults that product is 1801.5s — inside a
    Cloud Run request budget of 900.
    """

    def test_the_worst_case_is_thirty_seconds_not_the_per_attempt_timeout(self) -> None:
        self.assertEqual(worst_case_seconds(), 30.5)
        self.assertEqual(worst_case_seconds(TIMEOUT_SECONDS, 0), TIMEOUT_SECONDS)
        # What we would have shipped by setting `timeout` alone and leaving retries at 2.
        self.assertEqual(worst_case_seconds(30.0, 2), 91.5)
        # And what the SDK does untouched: longer than the request it runs inside.
        self.assertGreater(worst_case_seconds(600.0, 2), 900)

    def test_a_hanging_search_is_attempted_exactly_max_retries_plus_one_times(self) -> None:
        """Counted against a transport that never answers — the SDK's retry, observed."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - only on a bare interpreter
            raise unittest.SkipTest(f"needs the venv: {exc}") from exc
        from parallel import APITimeoutError

        from backend.agent.tools import ParallelSearch

        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ReadTimeout("timed out", request=request)

        source = ParallelSearch(
            api_key="test-key",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        request = SearchRequest(
            queries=("q",), objective="o", include_domains=MCU_FANDOM.include_domains
        )
        # Propagates rather than becoming a `SearchError`: a timeout is worth ADK retrying.
        with self.assertRaises(APITimeoutError):
            source.run(request)
        self.assertEqual(attempts, MAX_RETRIES + 1)

    def test_a_timeout_reaches_the_caller_of_the_tool_too(self) -> None:
        """`search()` must not swallow it into an error payload — that would look to the graph
        like a search that found nothing, and retry would never fire."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - only on a bare interpreter
            raise unittest.SkipTest(f"needs the venv: {exc}") from exc
        from parallel import APITimeoutError

        from backend.agent.tools import ParallelSearch

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        tool = WebSearch(
            MCU_FANDOM,
            ParallelSearch(
                api_key="test-key",
                max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            ),
        )
        with self.assertRaises(APITimeoutError):
            tool.search(search_queries=["q"], objective="o")


class TestToolSurface(unittest.TestCase):
    def test_every_model_facing_argument_is_json_expressible(self) -> None:
        hints = get_type_hints(WebSearch.search)
        names = [p for p in inspect.signature(WebSearch.search).parameters if p != "self"]
        self.assertEqual(names, ["search_queries", "objective", "after_date"])
        self.assertEqual(hints["search_queries"], list[str])
        self.assertIs(hints["objective"], str)
        self.assertIs(hints["after_date"], str)

    def test_the_declared_schema_hides_self_and_the_profile(self) -> None:
        try:
            from google.adk.tools.function_tool import FunctionTool
        except ImportError as exc:  # pragma: no cover - only on a bare interpreter
            raise unittest.SkipTest(f"needs the venv: {exc}") from exc

        tool = FunctionTool(WebSearch(MCU_FANDOM, Fake()).search)
        self.assertEqual(tool.name, "search")
        declaration = tool._get_declaration()
        assert declaration is not None
        schema = declaration.parameters_json_schema or {}
        self.assertEqual(
            set(schema.get("properties", {})), {"search_queries", "objective", "after_date"}
        )
        self.assertEqual(schema["properties"]["search_queries"]["type"], "array")


class TestWireShape(unittest.TestCase):
    """What actually goes out on the wire, asserted without spending a `sku_search`.

    The SDK call is built from reading `parallel-web` 1.3.0's source, not from running it, so
    the parts that matter are checked against a mock transport: `include_domains` has to land
    inside `advanced_settings.source_policy` or the source policy silently does nothing, and
    that filter is the difference §12 measured between Disney stating the fact and two Tumblr
    posts. Needs the venv for `httpx`.
    """

    def call(self, **over: Any) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - only on a bare interpreter
            raise unittest.SkipTest(f"needs the venv: {exc}") from exc
        from backend.agent.tools import ParallelSearch

        sent: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            sent["url"] = str(request.url)
            sent["headers"] = dict(request.headers)
            sent["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": "https://www.marvel.com/x", "excerpts": ["e"],
                         "title": "T", "publish_date": "2024-07-26"}
                    ],
                    "search_id": "search_abc",
                    "session_id": "session_xyz",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        source = ParallelSearch(api_key="test-key", http_client=client)
        base: dict[str, Any] = {
            "queries": ("gambit doomsday casting",),
            "objective": "has gambit been cast since",
            "include_domains": MCU_FANDOM.include_domains,
        }
        outcome = source.run(SearchRequest(**{**base, **over}))
        sent["outcome"] = outcome
        sent["source"] = source
        return sent

    def test_the_allowlist_reaches_the_source_policy(self) -> None:
        sent = self.call()
        policy = sent["body"]["advanced_settings"]["source_policy"]
        self.assertEqual(policy["include_domains"], list(MCU_FANDOM.include_domains))
        self.assertIn("marvel.com", policy["include_domains"])

    def test_after_date_is_absent_unless_asked_for(self) -> None:
        self.assertNotIn(
            "after_date", self.call()["body"]["advanced_settings"]["source_policy"]
        )
        self.assertEqual(
            self.call(after_date="2024-08-09")["body"]["advanced_settings"]["source_policy"][
                "after_date"
            ],
            "2024-08-09",
        )

    def test_an_omitted_session_id_is_not_sent_as_null(self) -> None:
        """`omit` and `None` are different to this SDK: null would override the server's own
        session generation with nothing."""
        self.assertNotIn("session_id", self.call()["body"])
        self.assertEqual(self.call(session_id="run-1")["body"]["session_id"], "run-1")

    def test_the_key_travels_in_the_header_and_never_in_the_url(self) -> None:
        sent = self.call()
        self.assertEqual(sent["headers"]["x-api-key"], "test-key")
        self.assertNotIn("test-key", sent["url"])

    def test_the_response_maps_onto_our_own_result_type(self) -> None:
        sent = self.call()
        self.assertEqual(sent["outcome"].results, (
            RawResult(
                url="https://www.marvel.com/x",
                excerpts=("e",),
                title="T",
                publish_date="2024-07-26",
            ),
        ))
        self.assertEqual(sent["source"].last_search_id, "search_abc")
        self.assertEqual(sent["source"].last_session_id, "session_xyz")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
