"""Real-simulator loading. There is deliberately no fixture fallback in this service."""

from __future__ import annotations

from typing import Any


class SimulatorUnavailable(RuntimeError):
    pass


def check() -> tuple[bool, str]:
    """(available, detail): can the real Sim2DAdapter be imported?"""
    try:
        import archipelago_sim2d.adapter  # noqa: F401
    except Exception as e:  # ImportError or a broken dependency: both mean "not available"
        return False, f"{type(e).__name__}: {e}"
    return True, "archipelago_sim2d"


def adapter_factory(world_kwargs: dict[str, Any]) -> Any:
    from archipelago_sim2d.adapter import Sim2DAdapter

    return Sim2DAdapter(**world_kwargs)


def reward_ids() -> set[str]:
    from archipelago_sim.env import REWARD_SPECS

    return set(REWARD_SPECS)


def min_survival_ticks(battery_scale: float) -> int:
    """Ticks a drone that moves every tick survives (the shortest battery life), computed with the
    world's own arithmetic. Faults scheduled beyond it can never be reached by a moving fleet."""
    from archipelago_sim.env import MOVE_COST

    battery, ticks = battery_scale, 0
    while battery > 1e-9:
        battery -= MOVE_COST
        ticks += 1
    return ticks
