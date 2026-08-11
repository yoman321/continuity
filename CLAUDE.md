# CLAUDE.md — universal working rules

<!--
PROJECT-AGNOSTIC. Copy to any project root unchanged; nothing here names a product,
package, version or path.

If you catch yourself writing a project name, a version number, a file path or a command
into this file — it belongs in AGENTS.md instead. That test is the whole boundary. See §0.
-->

## 0. The document set — and which file to write to

`AGENTS.md` in this repo root holds the project-specific half of these rules: what the
product is, the stack, the file map, the real commands, and the gotchas actually hit on
this codebase. **Read it before writing any code.** This file only carries what is true
of every project.

| File | Holds | Read it for | Scope |
|---|---|---|---|
| `CLAUDE.md` (this) | universal working rules | the **how**, always | agnostic |
| `AGENTS.md` | how this project gets built — stack, file map, commands, invariants, gotchas | the **how, here** | project |
| `summary.md` | the idea — product brief, decision log, status, roadmap | the **why**, and what's next | project |
| `README.md` | setup, commands, routes, env vars | onboarding a human | project |

In one line: **`summary.md` is the idea, `AGENTS.md` is how it gets built, `CLAUDE.md` is how
I work on anything.**

`summary.md` is the only source of product truth. Implement the behavior it describes; do
not introduce, infer, or enforce behavior it does not state.

### Never edit this file for a project

This file is copied between repos unchanged. A project-specific line added here is a line
that will be wrong in the next repo and followed anyway, silently. So no project fact, however
durable it feels, is a reason to touch it — that includes stack decisions, verified vendor
behaviour, and rules imposed from outside the codebase. All of it goes to `AGENTS.md`.

The only justification for editing this file is a change to how I work *in general*, and that
comes from an explicit instruction — never from me generalizing a lesson learned on one
project.

### Bootstrapping: splitting a `summary.md`

A project usually starts as a single document holding the idea and the implementation thinking
tangled together. That's the normal starting state, not a defect, and untangling it doesn't
need permission. Split as soon as implementation detail exists — stack and version choices,
commands, file layout, invariants, "never do X because Y forbids it":

- The **rule** moves to `AGENTS.md`, stated imperatively and standing alone.
- The **reasoning** stays in `summary.md`, with a pointer to where the rule now lives.
- Nothing is stated in both. A rule duplicated in two files is a rule that will disagree
  with itself later.

After the split `summary.md` must still read as the product idea — a coherent brief, not a
shell of pointers. If a section is left saying only "see `AGENTS.md`", the reasoning behind
that decision was never written down; write it.

## 1. Trust the installed version, not your memory

The dependencies in this repo may differ from your training data — APIs, conventions and
file layout all move, and major versions break. Before writing code against any library,
check the version in the lockfile and read the local source of truth: `node_modules/<pkg>/`,
the vendored docs, `--help`, or the package source itself. Heed deprecation notices. Never
write an API call from recall when the installed copy is one command away.

## 2. Working agreement

- **No product-direction change without an explicit user decision.** If you need an
  assumption to proceed, state it plainly and keep going — don't stall, don't silently pick.
- **Same-task doc updates.** Never defer these to a follow-up:
  - direction, scope, architecture or rules changed → update `summary.md`
  - stack, file layout or a project invariant changed → update `AGENTS.md`
  - setup, commands, public routes or env vars changed → update `README.md`
  - a rule that is true of *every* project changed → update this file, and only then (§0)
- Durable rules live in `CLAUDE.md` / `AGENTS.md`; rationale and history live in
  `summary.md`. Don't mix them.
- Preserve user changes. No unrelated refactors, no drive-by renames, no reformatting files
  you didn't otherwise need to touch.

## 3. Universal architecture invariants

- **Deterministic core, I/O at the perimeter.** The logic you're judged on is pure and never
  fetches. Network calls, model calls and third-party data enter only through thin adapters
  at the edge, and **every external source has a deterministic fallback** — a demo must never
  break because a key expired, a quota ran out, or a network blipped.
- **Secrets are server-side only.** Never referenced in client code, never in a bundle, never
  logged. Where they live for this project: `AGENTS.md`.
- **One shared model per concept.** A parameter is modelled in the core *before* any UI
  exposes it. A control that changes no number is the anti-pattern to avoid.
- **Stubs are labelled.** Any POC path — in-memory store, mocked route, hardcoded fixture —
  says so in the code and in the handoff note.

Project-specific invariants — the ones that mean a rewrite rather than a patch — are in
`AGENTS.md`.

## 4. The verification gate

**Never claim done until the project's test, typecheck, lint and build commands pass.** The
actual commands are in `AGENTS.md`. If one fails and you're handing off regardless, say
which, and paste the actual output.

**Standing permission — do these without asking:** start or gracefully restart the dev
server, run any command listed in `AGENTS.md`, read files, run read-only diagnostics.

**Ask first:** anything that writes outside the repo, spends money, publishes, deploys, or
touches production data.

## 5. Gotchas

Project gotchas go in `AGENTS.md`, one line each: symptom → fix. Append there whenever
something costs more than ten minutes and the cause was non-obvious. It is a scar log, not
a list of things that might go wrong — anticipated vendor constraints belong in `summary.md`.

One universal entry:

- **Measure, don't eyeball.** Screenshots and visual similarity lie. Assert on numbers —
  scroll widths, counts, timings, real output — never on whether it "looks right" or matches
  an expected shape. Score factual results, not resemblance.

## 6. Universal code conventions

- Keep motion meaningful — it should reflect real state, not decorate.
- Match the surrounding code's idiom, naming and comment density rather than importing your
  own. Prefer the smallest change that fully satisfies the task.
- Don't add a dependency where ~20 lines of local code would do.
- Attribute derived content per its license; never copy copyrighted material into the app.

Design system, typing strictness and state rules are per-project — see `AGENTS.md`.

## 7. How to write to me

Default to the shortest reply that fully answers. Length is a cost I pay, not effort you show.

- **Lead with the answer.** No preamble, no restating my question back to me.
- **Match length to the question.** A yes/no question gets a yes/no, then the one caveat that
  actually matters — not a survey.
- **Prose for connected reasoning; bullets only for genuinely parallel items.** A bulleted
  list of full sentences is usually a paragraph in costume.
- **Tables for comparing 3+ things.** Not for two.
- **Cut:** filler openers, throat-clearing, hedges, and any closing paragraph that
  re-summarizes what you just said.
- **Say the hard thing plainly.** "This won't work, because X" beats three softening clauses.
- Write like a senior colleague answering in Slack: direct, specific, done.

### Handoff report

When you finish a task, report:

1. **What changed** — files and behavior, not a narration of the diff.
2. **What was verified** — the commands you actually ran, and their result.
3. **What's still open** — intentional limitations, stubs, skipped scope, and why.

Report outcomes faithfully. If tests fail, say so with the output. If you skipped a step, say
that. When something is done and verified, state it plainly without hedging.
