"""Self-decaying recheck intervals.

`AGENTS.md` §2: `double on no-change, halve on change, clamp [6h, 6mo]`. Deterministic code,
not model output — an agent choosing its own cadence is the point (`summary.md` §7), but the
choice has to be reproducible on camera.

The wave a claim belongs to (`seed-plan.md` §3) only seeds the *first* interval. After one
run the ledger's own history drives it, which is what makes the ladder emerge rather than
being a cron table in disguise.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

FLOOR = timedelta(hours=6)
CEILING = timedelta(days=180)


class Wave(str, Enum):
    """Why a claim moves, and therefore how often it is worth asking (`seed-plan.md` §3)."""

    SETTLED = "settled"
    IN_UNIVERSE_SLOW = "in_universe_slow"
    RELEASE_DRIVEN = "release_driven"
    ANNOUNCEMENT_DRIVEN = "announcement_driven"


# Seeds only. Settled claims start high so they reach the ceiling in two runs, which is what
# demonstrates the ladder; announcement-driven claims start at the floor because trade
# reporting moves within a day.
WAVE_SEED: dict[Wave, timedelta] = {
    # 45d doubles to 90d then 180d — the ceiling in exactly two clean runs, which is the
    # claim `seed-plan.md` §3 makes. 30d would take three and blunt the demo.
    Wave.SETTLED: timedelta(days=45),
    Wave.IN_UNIVERSE_SLOW: timedelta(days=14),
    Wave.RELEASE_DRIVEN: timedelta(days=7),
    Wave.ANNOUNCEMENT_DRIVEN: timedelta(hours=24),
}


def clamp(interval: timedelta) -> timedelta:
    """Hold `interval` inside [6h, 6mo]. The ceiling stops a settled claim from silently
    falling out of the schedule; the floor stops a thrashing claim from burning quota."""
    return max(FLOOR, min(interval, CEILING))


def seed_interval(wave: Wave) -> timedelta:
    return clamp(WAVE_SEED[wave])


def next_interval(current: timedelta, *, changed: bool) -> timedelta:
    """Halve on change, double on no-change, clamped.

    `changed` means the research round found the claim no longer matches the world — not that
    an edit was published. A claim that keeps moving earns attention whether or not a human
    has approved the resulting edit yet.
    """
    return clamp(current / 2 if changed else current * 2)


def next_check_at(now: datetime, interval: timedelta) -> datetime:
    """Absolute wake time for the scheduler to poll against (`summary.md` §7).

    Cloud Scheduler is deliberately dumb: it asks the ledger what is due. All the intelligence
    is in what the agent wrote here last run.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware; the ledger stores UTC instants")
    return now.astimezone(timezone.utc) + clamp(interval)
