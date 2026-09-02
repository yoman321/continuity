"""Shared setup for the tests that exercise the real store.

The ledger's persistence is MongoDB as of Sept 1, 2026 (`AGENTS.md` §2) — there is no file
store any more, and no fallback. Which leaves the suite two kinds of test, and the split is
deliberate:

  * Most tests use `InMemory*`, which needs nothing installed. That is what keeps the core's
    tests runnable on a bare interpreter, and it is why the in-memory stores still exist.
  * The tests that were checking *persistence* — what survives a restart, what the codec
    round-trips through storage — now run against a real mongod, because that is the thing
    they are actually about. Against an in-memory dict they would assert nothing.

Those skip rather than fail when mongod is not running, so the suite still passes on a machine
without it. `--dbpath data/mongo`, or `./scripts/mongo.sh start`.

Each test gets its **own database**, dropped afterwards, so a run never sees another run's rows
and never touches the `continuity` database a demo is using.
"""

from __future__ import annotations

import os
import unittest
import uuid
from typing import Any

MONGO_URI = os.environ.get("MONGO_TEST_URI") or os.environ.get("MONGO_URI") \
    or "mongodb://127.0.0.1:27017"


def mongo_available() -> bool:
    """Whether a mongod is reachable. Cheap, and the answer is not cached: a developer who
    starts the server mid-session should not have to restart the suite."""
    try:
        import pymongo
    except ImportError:
        return False
    try:
        client: Any = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=400)
        client.admin.command("ping")
        client.close()
    except Exception:
        return False
    return True


requires_mongo = unittest.skipUnless(
    mongo_available(),
    f"no mongod at {MONGO_URI} — start it with ./scripts/mongo.sh start",
)


class MongoTestCase(unittest.TestCase):
    """A private, disposable database per test."""

    def setUp(self) -> None:
        import pymongo

        self._client: Any = pymongo.MongoClient(MONGO_URI, tz_aware=True)
        self._name = f"continuity_test_{uuid.uuid4().hex[:12]}"
        self.db = self._client[self._name]

    def tearDown(self) -> None:
        self._client.drop_database(self._name)
        self._client.close()
