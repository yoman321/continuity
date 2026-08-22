"""The service layer: FastAPI routes, and the vendor adapters that will hang off them.

Kept out of `src/continuity/` deliberately. That package is the deterministic core — pure,
dependency-free, importable without a network or a key (`CLAUDE.md` §3). Everything in here
is the perimeter: it imports FastAPI, and it will import ADK, `google-genai` and
`parallel-web`. One directory boundary, one rule — the core never imports from here.
"""
