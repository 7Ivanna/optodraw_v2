"""Scene-independent animation actions and composition."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .styles import resolve_style

EASINGS = ("smooth", "linear", "there_and_back", "ease_in", "ease_out")
PRIMITIVES = (
    "Create", "FadeIn", "FadeOut", "Indicate", "Dim", "Label", "Arrow", "Write",
    "Transform", "MoveAlong", "Flow", "Zoom", "Pan", "Fit", "Morph", "Set", "Sweep",
    "Plot", "Wait", "Click",
)


def number(value, name, *, minimum=0.0, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < minimum or (positive and value == minimum)):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return float(value)


def parameter(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("parameter must be a nonempty string")
    return name


@dataclass(frozen=True)
class Action:
    type: str
    target: object
    seconds: float | None
    easing: str
    args: dict

    def __post_init__(self):
        if self.type not in PRIMITIVES:
            raise ValueError(f"unknown primitive: {self.type}")
        if self.easing not in EASINGS:
            raise ValueError(f"unknown easing: {self.easing}")
        if self.seconds is None:
            if self.type not in ("Flow", "Plot"):
                raise ValueError("seconds must be resolved")
        else:
            number(self.seconds, "seconds")


@dataclass(frozen=True)
class Quantity:
    target: object
    name: str = "power"
    port: str | None = None

    def __post_init__(self):
        if self.name != "power":
            raise ValueError(f"unsupported quantity: {self.name}")


@dataclass(frozen=True, init=False)
class Sequence:
    children: tuple

    def __init__(self, *children):
        if not all(isinstance(child, (Action, Sequence, Lagged)) for child in children):
            raise ValueError("composition requires action descriptors")
        object.__setattr__(self, "children", tuple(children))


@dataclass(frozen=True, init=False)
class Lagged(Sequence):
    lag: float

    def __init__(self, *children, lag=0.1):
        super().__init__(*children)
        object.__setattr__(self, "lag", number(lag, "lag"))


def ease(name: str, u: float) -> float:
    if name not in EASINGS or not math.isfinite(u) or not 0 <= u <= 1:
        raise ValueError("invalid easing or fraction")
    if name == "linear":
        return u
    if name == "smooth":
        return u * u * (3 - 2 * u)
    if name == "ease_in":
        return u * u
    if name == "ease_out":
        return 1 - (1 - u) ** 2
    v = 2 * u if u <= 0.5 else 2 * (1 - u)
    return v * v * (3 - 2 * v)


def Create(target, *, seconds=0.6, easing="smooth"):
    return Action("Create", target, seconds, easing, {})


def FadeIn(target, *, seconds=0.6, easing="smooth"):
    return Action("FadeIn", target, seconds, easing, {})


def FadeOut(target, *, seconds=0.6, easing="smooth"):
    return Action("FadeOut", target, seconds, easing, {})


def Indicate(target, *, seconds=0.6, easing="smooth"):
    return Action("Indicate", target, seconds, easing, {})


def Dim(target, *, opacity=0.25, seconds=0.6, easing="smooth"):
    number(opacity, "opacity")
    if opacity > 1:
        raise ValueError("opacity must be between zero and one")
    return Action("Dim", target, seconds, easing, {"opacity": float(opacity)})


def Label(target, text, *, seconds=0.6, easing="smooth"):
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return Action("Label", target, seconds, easing, {"text": text})


def Arrow(start, end, *, seconds=0.6, easing="smooth"):
    return Action("Arrow", None, seconds, easing, {"start": start, "end": end})


def Write(text, *, near=None, seconds=0.6, easing="smooth"):
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return Action("Write", None, seconds, easing, {"text": text, "near": near})


def Transform(target, to, *, seconds=0.6, easing="smooth"):
    return Action("Transform", target, seconds, easing, {"to": to})


def MoveAlong(target, path, *, seconds=0.6, easing="linear"):
    return Action("MoveAlong", target, seconds, easing, {"path": path})


def Flow(*, paths=None, style=None, mode=None, seconds=None, easing="linear"):
    if mode not in (None, "pulse", "cw"):
        raise ValueError("mode must be pulse or cw")
    if paths is not None and isinstance(paths, str):
        paths = [paths]
    return Action("Flow", None, seconds, easing, {
        "paths": None if paths is None else list(paths),
        "style": None if style is None else resolve_style(style).to_json(), "mode": mode,
    })


def Zoom(target, *, factor=2.0, seconds=0.6, easing="smooth"):
    return Action("Zoom", target, seconds, easing, {"factor": number(factor, "factor", positive=True)})


def Pan(offset, *, seconds=0.6, easing="smooth"):
    if len(offset) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in offset):
        raise ValueError("offset must contain two finite numbers")
    return Action("Pan", None, seconds, easing, {"offset": list(offset)})


def Fit(*, margin=0.05, seconds=0.6, easing="smooth"):
    return Action("Fit", None, seconds, easing, {"margin": number(margin, "margin")})


def Morph(*, to, seconds=0.6, easing="smooth"):
    if to not in ("1d", "2d"):
        raise ValueError("view must be 1d or 2d")
    return Action("Morph", None, seconds, easing, {"to": to})


def Set(param, value):
    return Action("Set", parameter(param), 0.0, "linear", {"value": value})


def Sweep(param, start, stop, seconds, *, samples=120, easing="linear"):
    number(seconds, "seconds", positive=True)
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 2:
        raise ValueError("samples must be an integer of at least two")
    for value in (start, stop):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("sweep endpoints must be finite")
    return Action("Sweep", parameter(param), seconds, easing, {
        "start": float(start), "stop": float(stop), "samples": samples,
    })


def Plot(quantity, *, against, seconds=None, easing="linear"):
    if not isinstance(quantity, Quantity):
        raise ValueError("Plot requires a Quantity")
    return Action("Plot", None, seconds, easing, {"quantity": quantity, "against": parameter(against)})


def Wait(seconds):
    return Action("Wait", None, seconds, "linear", {})


def Click():
    return Action("Click", None, 0.0, "linear", {})
