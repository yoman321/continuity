"""The whole Python application: the deterministic core, and the perimeter around it.

The pure/perimeter split that `CLAUDE.md` §3 requires did not go away when this became one
package — it moved into the import path, where it is harder to miss. `backend.core.*` is the
deterministic half: pure, dependency-free, importable with nothing installed and no network.
Everything else under `backend/` is the perimeter — `app.py` imports FastAPI today, and the
ADK graph, the Parallel tool and the Firestore adapter will import their SDKs here.

Two rules, and the second one is new and load-bearing:

1. `backend.core` never imports from the perimeter. One direction, always.
2. **This file stays import-free.** Importing `backend.core.ledger` now executes this module
   first, so a single vendor import here would silently make the core un-importable without
   the SDKs installed — and would break the cold-start deferral in `app.py`. Docstring only.
"""
