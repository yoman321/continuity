#!/usr/bin/env python3
"""Build `FE/data/demo-state.json` — everything the review-queue page renders.

The frontend has no backend yet, so this is its deterministic fallback (`CLAUDE.md` §3): the
page fetches `/api/state` and falls back to this file, and the two must be the same shape.
When the ADK graph lands it serves that shape from Firestore and nothing in the FE changes.

Two properties make the fixture honest rather than decorative, and both are enforced here
rather than promised:

* **Page text is verbatim from `snapshots/`.** Nothing is retyped, so the CC BY-SA attribution
  in `snapshots/ATTRIBUTION.md` covers what the page displays. Every `wikitext_anchor` below
  is checked against the seed file and the build fails if one is missing — an anchor that
  doesn't exist is an edit that could never apply.
* **Status, confidence and scheduling come from the real ledger core.** This script builds
  actual `Claim` objects and drives them through the real transitions; it never types a
  number. Change `tiers.py` and these numbers change.

What is *not* real: the claims and their citations are a hand-built fixture standing in for an
agent run that has not happened yet. Marked `"stub": true` in the output and surfaced in the
UI, per `CLAUDE.md` §3.

    python3 scripts/build_demo_state.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.ledger.decay import Wave
from backend.core.ledger.schema import Claim, ClaimKind, ClaimStatus, Contradiction, Source
from backend.core.profile import MCU_FANDOM
from backend.core.wiki import find_section, slug_for, split_sections, subtree

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = REPO_ROOT / "snapshots"
OUT = REPO_ROOT / "FE" / "data" / "demo-state.json"

# Fixed so the fixture is reproducible: rebuilding must not churn every timestamp.
NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

STUB_NOTE = (
    "Claims and citations are a hand-built fixture, not the output of an agent run. "
    "Page text is verbatim from snapshots/ and the ledger numbers are computed by "
    "backend/core/ledger/, but no research has been performed. Replaced by live "
    "Firestore state once the ADK graph runs."
)

# Which pages the FE can display, and which sections of each it carries. Whole pages would be
# 50KB of wikitext for a view that shows three of nine sections; the lead is always included
# because that is where the infobox lives.
PAGE_VIEWS: dict[str, tuple[str, ...]] = {
    "Deadpool & Wolverine": ("Plot", "Cast"),
    "Gambit": ("Trivia", "Behind the Scenes"),
    "Phase Six": ("Overview", "Films"),
    "Human Torch": (),
}

# Plug-and-play made visible (`summary.md` §5). Only the first is seeded today; the others are
# listed so the picker shows the agent is pointed at a wiki rather than wired to one. Read
# support for all three is already real — `MediaWikiReader` took a different `api_url` and
# pulled live revisions from each on Aug 15, 2026.
PROFILES: list[dict[str, Any]] = [
    {
        "id": "mcu-fandom",
        "label": "MCU Wiki (Fandom)",
        "api": "https://marvelcinematicuniverse.fandom.com/api.php",
        "article_base": "https://marvelcinematicuniverse.fandom.com/wiki/",
        "licence": "CC BY-SA 3.0 Unported",
        "subpages": True,
        "seeded": True,
    },
    {
        "id": "wikipedia-en",
        "label": "Wikipedia (English)",
        "api": "https://en.wikipedia.org/w/api.php",
        "article_base": "https://en.wikipedia.org/wiki/",
        "licence": "CC BY-SA 4.0",
        "subpages": False,
        "seeded": False,
    },
    {
        "id": "memory-alpha",
        "label": "Memory Alpha (Star Trek)",
        "api": "https://memory-alpha.fandom.com/api.php",
        "article_base": "https://memory-alpha.fandom.com/wiki/",
        "licence": "CC BY-NC 4.0",
        "subpages": True,
        "seeded": False,
    },
]


@dataclass(frozen=True, slots=True)
class DemoSource:
    url: str
    excerpt: str
    as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class DemoClaim:
    """One fixture claim, plus how it should be driven through the ledger's state machine."""

    claim_id: str
    page: str
    kind: ClaimKind
    wave: Wave
    text: str
    anchor: str  # must appear verbatim in the seed snapshot
    section_heading: str  # "" for the lead
    objective: str
    sources: tuple[DemoSource, ...]
    outcome: str  # "changed" | "unchanged" | "unresolved"
    replacement: str | None = None  # what the anchor becomes; None when no edit is drafted
    rationale: str = ""
    ripple_targets: tuple[str, ...] = ()
    runs: int = 1  # how many clean rechecks to simulate; >1 shows the interval ladder
    contradiction: Contradiction | None = None
    conflict_note: str = ""
    pending_selection: bool = field(default=False)


# `seed-plan.md` §4. Six claims, each verified stale (or verified *correct*, which is the
# point of DW-HT-01) against the live wiki on Aug 15, 2026.
DEMO_CLAIMS: tuple[DemoClaim, ...] = (
    DemoClaim(
        claim_id="GAM-APP-01",
        page="Gambit",
        kind=ClaimKind.PROSE,
        wave=Wave.ANNOUNCEMENT_DRIVEN,
        text="Gambit's only film appearance is Deadpool & Wolverine.",
        anchor="|movie = ''[[Deadpool & Wolverine]]''",
        section_heading="",
        objective="Which announced films does Channing Tatum's Gambit appear in?",
        sources=(
            DemoSource(
                "https://thewaltdisneycompany.com/marvel-studios-announces-robert-downey-jr-"
                "and-the-russo-brothers-to-return-for-avengers-doomsday/",
                "Studio announcement of Avengers: Doomsday.",
                datetime(2024, 7, 27, tzinfo=timezone.utc),
            ),
            DemoSource(
                "https://deadline.com/2024/07/robert-downey-jr-victor-von-doom-avengers-"
                "doomsday-1236024873/",
                "Trade reporting on the Doomsday cast announcement.",
                datetime(2024, 7, 27, tzinfo=timezone.utc),
            ),
        ),
        outcome="changed",
        replacement=(
            "|movie = ''[[Deadpool & Wolverine]]''<br>''[[Avengers: Doomsday]]'' "
            "<small>(unreleased)</small>"
        ),
        rationale=(
            "The infobox lists one film. A second is announced, so the field is incomplete "
            "rather than wrong — appended in the wiki's existing <br> convention, no new "
            "field and no new section."
        ),
        ripple_targets=("PS6-FILMS-01",),
    ),
    DemoClaim(
        claim_id="DW-VOID-01",
        page="Deadpool & Wolverine",
        kind=ClaimKind.LINK,
        wave=Wave.RELEASE_DRIVEN,
        text="The Plot section's [[Void]] link points at the D&W location.",
        anchor="sent to the [[Void]], where Wolverine",
        section_heading="Plot",
        objective="What does the title 'Void' resolve to on this wiki today?",
        sources=(
            DemoSource(
                "https://deadline.com/2022/06/marvels-thunderbolts-jake-schreier-1235041619/",
                "Trade coverage establishing the competing Void subject.",
                datetime(2022, 6, 8, tzinfo=timezone.utc),
            ),
        ),
        outcome="changed",
        replacement="sent to the [[Void (End of Time)|Void]], where Wolverine",
        rationale=(
            "Nobody edited this page — the target moved underneath it. 'Void' now resolves "
            "to Sentry's Void, so the link sends readers to the wrong character. Piped to "
            "the explicit title so the displayed text is unchanged."
        ),
    ),
    DemoClaim(
        claim_id="DW-HT-01",
        page="Deadpool & Wolverine",
        kind=ClaimKind.LINK,
        wave=Wave.IN_UNIVERSE_SLOW,
        text=(
            "The Cast entry for Chris Evans points at the Void variant, not the prime "
            "Johnny Storm."
        ),
        anchor=(
            "*[[Chris Evans]] as [[Human Torch/Void Analyzing Fantastic Four|"
            "Johnny Storm/Human Torch]]"
        ),
        section_heading="Cast",
        objective=(
            "Is the Human Torch in Deadpool & Wolverine the prime MCU Johnny Storm or a "
            "Void variant?"
        ),
        sources=(
            DemoSource(
                "https://www.marvel.com/articles/movies/fantastic-four-cast",
                "Studio cast announcement for the prime MCU Fantastic Four.",
                datetime(2024, 2, 14, tzinfo=timezone.utc),
            ),
        ),
        outcome="unchanged",
        replacement=None,
        rationale=(
            "The precision test, and the correct answer is no edit. The Human Torch page "
            "grew 503% because First Steps introduced the prime Johnny Storm — which makes "
            "repointing this link the tempting, well-cited, wrong edit. Different subject, "
            "different claims; the variant subpage is right and stays."
        ),
    ),
    DemoClaim(
        claim_id="PS6-FILMS-01",
        page="Phase Six",
        kind=ClaimKind.LIST_MEMBER,
        wave=Wave.ANNOUNCEMENT_DRIVEN,
        text="Phase Six comprises First Steps, Doomsday and Secret Wars.",
        anchor=(
            "|films = ''[[The Fantastic Four: First Steps]]''<br>''[[Avengers: Doomsday]]''"
            "<br>''[[Avengers: Secret Wars]]''"
        ),
        section_heading="",
        objective="Which films are currently slated in Phase Six?",
        sources=(
            DemoSource(
                "https://thewaltdisneycompany.com/news/cinemacon-2026-recap/",
                "Studio slate presentation.",
                datetime(2026, 4, 2, tzinfo=timezone.utc),
            ),
        ),
        outcome="changed",
        replacement=(
            "|films = ''[[The Fantastic Four: First Steps]]''<br>''[[Spider-Man: Brand New "
            "Day]]''<br>''[[Avengers: Doomsday]]''<br>''[[Avengers: Secret Wars]]''"
        ),
        rationale=(
            "One research round yields the whole slate at once. Note what is *not* proposed: "
            "the live wiki renamed this section Films -> Projects, and renaming a section is "
            "an editorial convention decision no source implies (AGENTS.md §2)."
        ),
    ),
    DemoClaim(
        claim_id="DW-CAMEO-01",
        page="Deadpool & Wolverine",
        kind=ClaimKind.LIST_MEMBER,
        wave=Wave.ANNOUNCEMENT_DRIVEN,
        text="Channing Tatum's Gambit returns in Avengers: Secret Wars.",
        anchor="*[[Channing Tatum]] as [[Gambit|Remy LeBeau/Gambit]]",
        section_heading="Cast",
        objective="Is Gambit confirmed for Avengers: Secret Wars, or only in talks?",
        sources=(
            DemoSource(
                "https://variety.com/2022/film/news/hugh-jackman-wolverine-deadpool-3-logan-"
                "timeline-1235466229/",
                "Trade outlet reporting the return as confirmed.",
                datetime(2026, 6, 11, tzinfo=timezone.utc),
            ),
            DemoSource(
                "https://collider.com/deadpool-3-mcu-confirmed-r-rating-filming-details-"
                "kevin-feige-interview/",
                "Second outlet reporting the same return as unconfirmed.",
                datetime(2026, 6, 18, tzinfo=timezone.utc),
            ),
        ),
        outcome="unresolved",
        replacement=None,
        rationale=(
            "Two credible outlets disagree on confirmed vs in-talks. The agent declines "
            "rather than picking, keeps both citations, and re-queues the claim for when "
            "new sources appear."
        ),
        conflict_note="Confirmed vs. in talks — the outlets do not agree and neither retracted.",
        contradiction=Contradiction(
            note="One outlet reports the casting as confirmed; the other reports it as in talks.",
            source_a="variety.com",
            source_b="collider.com",
        ),
        pending_selection=True,
    ),
    DemoClaim(
        claim_id="DW-REL-01",
        page="Deadpool & Wolverine",
        kind=ClaimKind.PROSE,
        wave=Wave.SETTLED,
        text="Deadpool & Wolverine released July 26, 2024.",
        anchor="'''''Deadpool & Wolverine'''''",
        section_heading="",
        objective="Confirm the theatrical release date of a film already in release.",
        sources=(
            DemoSource(
                "https://www.marvel.com/movies/deadpool-and-wolverine",
                "Studio page for a released film.",
                datetime(2024, 7, 26, tzinfo=timezone.utc),
            ),
        ),
        outcome="unchanged",
        replacement=None,
        rationale=(
            "A shipped film's release date does not move. Two clean rechecks take the "
            "interval 45d -> 90d -> 180d, the ceiling: the agent stops asking a settled "
            "question without ever dropping it from the schedule."
        ),
        runs=2,
    ),
)


def load_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(
        (SNAPSHOTS / "manifest.json").read_text(encoding="utf-8")
    )
    return manifest


def build_claim(demo: DemoClaim, section_index: int) -> Claim:
    """Drive one fixture claim through the real ledger transitions.

    Nothing below is typed by hand — confidence comes from the tier table, status from the
    state machine, and the schedule from the decay logic.
    """
    claim = Claim(
        claim_id=demo.claim_id,
        page=demo.page,
        entity_ref=MCU_FANDOM.entity_ref(demo.page),
        kind=demo.kind,
        wave=demo.wave,
        text=demo.text,
        wikitext_anchor=demo.anchor,
        section_index=section_index,
        section_heading=demo.section_heading,
        ripple_targets=demo.ripple_targets,
    ).seeded(NOW)

    sources = tuple(
        Source.create(s.url, s.excerpt, retrieved_at=NOW, as_of=s.as_of,
                      domain_tiers=MCU_FANDOM.domain_tiers) for s in demo.sources
    )
    claim = claim.researched(demo.objective, sources)

    for run in range(demo.runs):
        at = NOW + timedelta(days=run)
        if demo.outcome == "unchanged":
            claim = claim.unchanged(at)
        elif demo.outcome == "changed":
            claim = claim.changed(at)
        elif demo.outcome == "unresolved":
            assert demo.contradiction is not None
            claim = claim.unresolved(at, demo.contradiction)
        else:  # pragma: no cover - guarded by the fixture, not by input
            raise ValueError(f"{demo.claim_id}: unknown outcome {demo.outcome!r}")

    # A drafted replacement means an edit is waiting on the human gate, which is a distinct
    # status from "we know this is stale".
    if demo.replacement is not None:
        claim = replace(claim, status=ClaimStatus.DRAFTED)
    return claim


def iso(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def serialise_claim(claim: Claim, demo: DemoClaim) -> dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "page": claim.page,
        "page_slug": slug_for(claim.page),
        "entity_ref": {
            "title": claim.entity_ref.title,
            "base": claim.entity_ref.base,
            "variant": claim.entity_ref.variant,
        },
        "kind": claim.kind.value,
        "wave": claim.wave.value,
        "text": claim.text,
        "wikitext_anchor": claim.wikitext_anchor,
        "section_index": claim.section_index,
        "section_heading": claim.section_heading or "(lead)",
        "status": claim.status.value,
        "confidence": claim.confidence,
        "auto_appliable": claim.auto_appliable,
        "objective": claim.objective,
        "research_rounds": claim.research_rounds,
        "ripple_targets": list(claim.ripple_targets),
        "last_verified": iso(claim.last_verified),
        "next_check_at": iso(claim.next_check_at),
        "check_interval_hours": round(claim.check_interval.total_seconds() / 3600),
        "sources": [
            {
                "url": s.url,
                "domain": s.domain,
                "tier": s.tier,
                "excerpt": s.excerpt,
                "as_of": iso(s.as_of),
                "placeholder": True,
            }
            for s in claim.sources
        ],
        "contradictions": [
            {"note": c.note, "source_a": c.source_a, "source_b": c.source_b}
            for c in claim.contradicts
        ],
        "conflict_note": demo.conflict_note,
        "rationale": demo.rationale,
        "pending_selection": demo.pending_selection,
    }


def build_pages(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Verbatim slices of the seed snapshots, keyed by slug."""
    by_title = {p["requested_title"]: p for p in manifest["pages"]}
    pages: dict[str, dict[str, Any]] = {}

    for title, wanted in PAGE_VIEWS.items():
        entry = by_title[title]
        raw = (REPO_ROOT / entry["seed"]["file"]).read_text(encoding="utf-8")
        sections = split_sections(raw)

        # Each entry carries its subsections' text but keeps its own index: the index is what
        # `action=edit&section=N` will target, the text is what a reviewer has to read.
        kept = [(sections[0], sections[0].text)]
        for heading in wanted:
            section = find_section(sections, heading)
            if section is None:
                raise SystemExit(f"{title}: no section {heading!r} in the seed snapshot")
            kept.append((section, "".join(s.text for s in subtree(sections, section.index))))

        pages[entry["slug"]] = {
            "title": entry["resolved_title"],
            "slug": entry["slug"],
            "pageid": entry["pageid"],
            "revid": entry["seed"]["revid"],
            "timestamp": entry["seed"]["timestamp"],
            "role": entry["role"],
            "seed_size": entry["seed"]["size"],
            "current_size": entry["current"]["size"],
            "drift_pct": entry.get("drift_pct"),
            "section_count": len(sections),
            "sections": [
                {"index": s.index, "level": s.level, "heading": s.heading, "text": text}
                for s, text in kept
            ],
        }
    return pages


def resolve_anchors(pages: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Check every anchor exists, and resolve each claim's section index from its heading.

    A fixture anchor that isn't in the seed is an edit that could never apply, so this fails
    the build rather than shipping a queue item that lies.
    """
    indices: dict[str, int] = {}
    missing: list[str] = []

    for demo in DEMO_CLAIMS:
        page = pages[slug_for(demo.page)]
        section = next(
            (s for s in page["sections"] if (s["heading"] or "") == demo.section_heading), None
        )
        if section is None:
            missing.append(f"{demo.claim_id}: section {demo.section_heading!r} not carried")
            continue
        if demo.anchor not in section["text"]:
            where = f"{demo.page}#{demo.section_heading or '(lead)'}"
            missing.append(f"{demo.claim_id}: anchor not found in {where}")
            continue
        indices[demo.claim_id] = section["index"]

    if missing:
        raise SystemExit("anchors do not match the snapshots:\n  " + "\n  ".join(missing))
    return indices


def build_queue(claims: dict[str, Claim]) -> list[dict[str, Any]]:
    """The drafted edits awaiting the publish gate — the §6 HITL pause made visible."""
    queue: list[dict[str, Any]] = []
    for demo in DEMO_CLAIMS:
        if demo.replacement is None:
            continue
        claim = claims[demo.claim_id]
        queue.append({
            "edit_id": f"edit-{demo.claim_id.lower()}",
            "claim_id": demo.claim_id,
            "page": demo.page,
            "page_slug": slug_for(demo.page),
            "section_index": claim.section_index,
            "section_heading": demo.section_heading or "(lead)",
            "before": demo.anchor,
            "after": demo.replacement,
            "rationale": demo.rationale,
            "confidence": claim.confidence,
            "auto_appliable": claim.auto_appliable,
            "drafted_at": iso(NOW),
            "summary": f"{demo.page} — {demo.text}",
        })
    return queue


def main() -> int:
    manifest = load_manifest()
    pages = build_pages(manifest)
    indices = resolve_anchors(pages)

    claims = {d.claim_id: build_claim(d, indices[d.claim_id]) for d in DEMO_CLAIMS}
    queue = build_queue(claims)

    state = {
        "generated_by": "scripts/build_demo_state.py",
        "generated_at": iso(NOW),
        "stub": True,
        "stub_note": STUB_NOTE,
        "source": manifest["source"],
        "freeze": manifest["freeze"],
        "profiles": PROFILES,
        "pages": pages,
        "claims": [serialise_claim(claims[d.claim_id], d) for d in DEMO_CLAIMS],
        "queue": queue,
        "counts": {
            "claims": len(claims),
            "queued": len(queue),
            "planned_claims": 50,  # `seed-plan.md` §2; these six are the ones that carry §4
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    print(f"{len(pages)} pages, {len(claims)} claims, {len(queue)} queued")
    for claim in claims.values():
        print(f"  {claim.claim_id:<14} {claim.status.value:<10} conf {claim.confidence:<6} "
              f"next {iso(claim.next_check_at)}")
    print(f"\nwrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
