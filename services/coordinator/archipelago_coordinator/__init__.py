"""Simulation coordinator: owns the 2D world and tick loop; never owns models."""

from .service import Coordinator
from .settings import Settings

__all__ = ["Coordinator", "Settings"]
