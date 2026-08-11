# AGENTS.md — fandom wiki maintainer agent

Project-specific half of the working rules. Universal rules are in `CLAUDE.md`; product
truth and rationale are in `summary.md`. Nothing here restates either.

## 1. What this is

An agent that keeps a fandom wiki current. It decomposes wiki pages into atomic claims,
re-verifies them against the live web, adjudicates contradictory sources, and drafts
section-level edits with citations and a confidence level — flagging honestly when sources
disagree rather than always producing an answer. Audience: wiki maintainers.

Built for **Agentic Cinema: The Blockbuster Hackathon** (Google Cloud x Devpost).
Deadline **Sept 7, 2026, 2:00 PM PT**. Parallel track. Demo subject: *Deadpool & Wolverine*,
seeded from real MCU Wiki revision history frozen at 2024-08-09 (`seed-plan.md`).

## 2. Project invariants

Violating one of these means a rewrite, a ban, or a disqualification — not a patch.

- **Every `model=` string is `gemini-*`.** ADK ships adapters for the platform's non-Google
  catalog; the rules ban them outright. Never pin `gemini-2.5-flash` (shutdown 2026-10-16,
  judging ends Oct 07) — use `gemini-3.1-pro` for adjudication, `gemini-3.6-flash` for
  throughput.
- **Parallel is the only path to the outside world.** All retrieval — discovery *and*
  re-verification — goes through the `parallel-web` SDK directly. Not LangChain's
  `ParallelWebSearchTool`, not the Vercel AI SDK tools: the Parallel page lists both as
  satisfying the track, but the AI-usage clause bans third-party agent frameworks and the
  plain SDK already satisfies it. Gemini never fetches. Exactly one partner track is
  permitted, so no second partner may be used for its AI features.
- **Never write to the real Fandom wiki.** Unsanctioned bot edits get banned. All writes go
  to our own seeded MediaWiki instance.
- **Section-level edits only, never full-page rewrites.** Full rewrites get reverted by wiki
  communities and are illegible in a 3-minute video.
- **Source tiers and decay intervals are deterministic code, not model output.** Tiers are a
  domain → tier lookup table; the poll interval is `double on no-change, halve on change,
  clamp [6h, 6mo]`. Gemini reasons *over* the tiers; it never invents them per call. Handing
  either to the model makes the headline behaviour unreproducible on camera.
- **The ledger store stays schema-flexible.** ADK 2.0 added `node_info` and `output` to the
  Event schema; rigid SQL columns fail on insert or ORM deserialize. Prefer Firestore, or
  migrate columns before first run.
- **Secrets:** `.env` locally (gitignored), Secret Manager when deployed. Gemini uses ADC —
  no API key exists on either side. Parallel and MediaWiki credentials are real secrets.

## 3. Stack

| Layer | Choice |
|---|---|
| Orchestration | ADK 2.x Workflow Runtime (`google-adk` ≥2.6.3) — stages as graph nodes |
| Model | `gemini-3.1-pro` (adjudication), `gemini-3.6-flash` (throughput), via `google-genai` |
| Auth | Enterprise/ADC — no API key. `GOOGLE_GENAI_USE_ENTERPRISE=true` (§5) |
| Retrieval | Parallel Search via `parallel-web`, wrapped as an ADK tool |
| Wiki I/O | MediaWiki API — `action=parse` to read, `action=edit` with section param to write |
| Ledger | Firestore (or Cloud SQL if ripple queries need joins) |
| Scheduling | Cloud Scheduler → Cloud Run endpoint, hourly; interval logic lives in the ledger |
| Secrets | Secret Manager — Parallel key, wiki bot credentials |
| Frontend | Diff review queue: change + sources + confidence badge + approve/reject |

Why each was chosen, and what was rejected: `summary.md` §6 and §12.

## 4. File map

<!-- One line per file: path # what it owns. Mark entry points "<-- read first".
     Update in the same task that moves a file. A stale map is worse than no map. -->

```text
docs only — no source yet.
  summary.md        # product truth, decision log, verified vendor facts (§12)
  seed-plan.md      # demo subject, page list, the 6 claims that carry the video
  .env.example      # required env vars, no values
```

Fill this in with the first commit of source.

## 5. Commands and the verification gate

```bash
pip install google-adk google-genai parallel-web    # install
# dev / test / typecheck / lint / build — not yet established
```

Gate commands are undefined until source exists. Establish them with the first module and
update this section in the same task.

Python ≥3.10 (required by `google-adk` 2.6.3).

**Auth.** One-time locally: `gcloud auth application-default login`. Deployed, the Cloud Run
service account supplies credentials via the metadata server — same client line either way:

```python
from google import genai
client = genai.Client(enterprise=True, project="…", location="global")
# or set GOOGLE_GENAI_USE_ENTERPRISE / GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION
# in .env, then call genai.Client() bare
```

`location` is `"global"` for model calls. The pick-one-region rule applies to Firestore and
Cloud Run, not to Gemini.

## 6. Gotchas — don't repeat these

Symptom → fix. Append when something costs more than ten minutes and the cause was
non-obvious. Scar log only; anticipated vendor constraints go in `summary.md` §12.

- **Vertex SDK names are one generation stale.** `vertexai=True` /
  `GOOGLE_GENAI_USE_VERTEXAI` are pre-rebrand and every pre-June-2026 tutorial uses them →
  `enterprise=True` / `GOOGLE_GENAI_USE_ENTERPRISE`, and `location="global"`, not a region.
- **`grep -r` from `.` silently skips dotfiles on this machine.** A clean recursive sweep is
  not proof a secret is absent → enumerate files explicitly, or `grep` the dotfile by name.

## 7. Code conventions

- **Catch narrowly inside ADK tools.** ADK 2.0 catches exceptions to drive automatic retry;
  a broad `except Exception:` masks the failure and permanently disables retry for that step.
  `except BaseException:` also traps `NodeInterruptedError` and breaks the HITL approval gate.
- **Never append to `context.session.events`.** It circumvents the 2.0 graph engine and
  breaks determinism. Return values; let the runner emit.
- **Stages are graph nodes, not hand-rolled sub-agent calls.** The 6-stage flow with two
  backward edges is an ADK 2.0 Workflow Runtime graph; the publish gate is its HITL pause.
- Typing strictness, design system and state rules: TBD with the first module.
