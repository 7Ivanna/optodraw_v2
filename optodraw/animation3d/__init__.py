"""The 3D light animation: one JSON payload per page, built from the physics engine."""

from .colours import CHANNEL_PALETTE, channel_colors
from .inputs import default_inputs
from .payload import build_light_payload

__all__ = ["CHANNEL_PALETTE", "build_light_payload", "channel_colors", "default_inputs"]
