"""Per-container node runtime: act/feedback/control HTTP, in-process training, peer exchange."""

from .config import Config, ConfigError
from .encoder import encode_observation, for_world

__all__ = ["Config", "ConfigError", "encode_observation", "for_world"]
