"""Explicit optical inputs on existing scene ports."""

from __future__ import annotations

from dataclasses import KW_ONLY, asdict, dataclass

from .behaviours import Emission, behaviour_for
from .errors import AnimationError
from .primitives import number
from .signals import from_json


@dataclass(frozen=True)
class InputSignal:
    target: str
    _: KW_ONLY
    jones: tuple = (1.0, 0.0, 0.0, 0.0)
    wavelength_nm: float = 1550.0
    width_ps: float = 0.2
    t0_ps: float = 0.0
    direction: str = "in"

    def __post_init__(self):
        if not isinstance(self.target, str) or not self.target.startswith("port:") or len(self.target.split(":")) != 3:
            raise ValueError("input target must be a port ID")
        if self.direction not in ("in", "out"):
            raise ValueError("input direction must be in or out")
        vector = tuple(self.jones)
        if len(vector) != 4:
            raise ValueError("Jones amplitude must contain four numbers")
        for value in vector:
            number(value, "Jones amplitude", minimum=-float("inf"))
        object.__setattr__(self, "jones", vector)
        number(self.wavelength_nm, "wavelength_nm", positive=True)
        number(self.width_ps, "width_ps", positive=True)
        number(self.t0_ps, "t0_ps")

    @property
    def endpoint(self):
        _, sid, port = self.target.split(":")
        return sid, port

    def validate(self, graph):
        sid, port = self.endpoint
        if sid not in graph.parts:
            raise AnimationError(f"{sid}: input part is missing")
        part = graph.parts[sid]
        if port not in part.ports():
            raise AnimationError(f"{sid}: input port {port} is missing")
        if part.ports()[port].kind in ("electrical", "thermal"):
            raise AnimationError(f"{sid}: input port {port} is not optical")
        behaviour_for(part, sid)

    def emission(self):
        return Emission(self.endpoint[1], from_json(list(self.jones)), self.wavelength_nm,
                        self.width_ps, self.t0_ps)

    def to_json(self):
        data = asdict(self)
        data["jones"] = list(self.jones)
        return data

    @classmethod
    def from_json(cls, data):
        return cls(**data)
