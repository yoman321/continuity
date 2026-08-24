"""The agent itself: the ADK graph and the tools its nodes call.

Perimeter, by `AGENTS.md` §4 — everything here may import vendor SDKs, and `backend.core` may
not import any of it. Two rules keep that from costing anything at runtime:

* **Vendor imports go inside the function that needs them, never at module top**
  (`AGENTS.md` §7). Cloud Run scales to zero and ADK costs 5-15s to import, which a cold
  container would otherwise pay before it could serve `index.html`.
* **A tool's logic does not import ADK at all.** `FunctionTool` wrapping happens where the
  graph is built; the tool bodies are plain typed callables, so they are testable — and the
  demo's fallback path is runnable — on an interpreter with nothing installed.
"""
