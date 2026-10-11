"""Skills: named, versioned, measurable capabilities a node has learned.

Proficiency (0..1) is measured by greedy evaluation episodes on fixed seeds, from the world's own
counters, so it is a property of the policy params and nothing else. ``learner.skills`` holds
``{name: {"proficiency", "version", "source"}}``: ``version`` counts measured changes, ``source`` is
the node the current proficiency came from (itself after local training, the peer after adoption).
"""

from __future__ import annotations

SKILL_SPEC = 1  # bump when a metric below changes meaning
SKILLS = {
    "explore": "fraction of free cells visited (search coverage)",
    "avoid": "1 - collisions per drone-tick (obstacle and drone avoidance)",
    "acquire": "fraction of targets found (target acquisition)",
    "energy": "mean battery left at episode end (return-to-base / energy economy)",
}


def world_skills(world) -> dict[str, float]:
    """Skill proficiencies of one finished episode of a GridWorld."""
    c = world.counters
    free = world.size * world.height - len(world.obstacles)
    hits = c["wall_collisions"] + c["agent_collisions"]
    return {
        "explore": min(1.0, len(world.visited - world.obstacles) / max(1, free)),
        "avoid": max(0.0, 1.0 - hits / max(1, c["agent_ticks"])),
        "acquire": len(world.found_targets) / max(1, len(world.targets)),
        "energy": sum(max(0.0, d.battery) for d in world.drones.values())
        / max(1, len(world.drones)),
    }


def mean_skills(per_episode: list[dict[str, float]]) -> dict[str, float]:
    return {k: sum(e[k] for e in per_episode) / len(per_episode) for k in SKILLS}


def record(learner, measured: dict[str, float], source: str) -> dict:
    """Store a measurement on the learner. A skill whose proficiency moved gets version+1 and
    ``source``; an unchanged one keeps both. Returns the learner's skills."""
    old = getattr(learner, "skills", None) or {}
    new = {}
    for name, p in measured.items():
        o = old.get(name)
        moved = o is None or abs(o["proficiency"] - p) > 1e-9
        new[name] = {
            "proficiency": float(p),
            "version": (o["version"] + 1 if o else 1) if moved else o["version"],
            "source": source if moved else o["source"],
        }
    learner.skills = new
    return new


def best_gain(before: dict[str, float], after: dict[str, float]) -> tuple[str, float]:
    """The skill a candidate improved most (ties: first in SKILLS order) and the gain."""
    gains = {k: after[k] - before[k] for k in SKILLS}
    k = max(gains, key=gains.get)
    return k, gains[k]
