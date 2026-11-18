"""The default light input of a scene that has no source of its own."""

from __future__ import annotations

from typing import Any

from optodraw.animation_engine.behaviours import find_behaviour
from optodraw.animation_engine.errors import AnimationError
from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.inputs import InputSignal
from optodraw.core.beam import Beam, FocusingBeam

_NOT_OPTICAL = ("electrical", "thermal")


def emitter_ids(scene: Any, graph: Any = None) -> list[str]:
    """The ids of the parts that emit light on their own, in walk order (``graph``: the scene's signal graph, built
    when not given)."""

    found = []
    for sid, part in (graph if graph is not None else build_graph(scene)).parts.items():
        behaviour = find_behaviour(part)
        if behaviour is not None and behaviour.emissions(part, sid, {}):
            found.append(sid)
    return found


def has_emitter(scene: Any, graph: Any = None) -> bool:
    """True when a part of the scene emits light on its own."""

    return bool(emitter_ids(scene, graph))


def beam_wavelength(scene: Any, part: Any, port: str) -> float | None:
    """The wavelength (nm) of the drawn beam that meets ``part`` at ``port``: a beam anchored there by name, else a
    beam anchored on the part itself, the first in walk order. None when no beam meets the part."""

    loose = None
    for node in scene.walk():
        if not isinstance(node, (Beam, FocusingBeam)):
            continue
        for anchor in node.anchors if isinstance(node, Beam) else (node.anchor1, node.anchor2):
            if isinstance(anchor, (tuple, list)) and len(anchor) == 2 and anchor[0] is part and str(anchor[1]) == port:
                return float(node.wavelength)
            if anchor is part and loose is None:
                loose = float(node.wavelength)
    return loose


def default_inputs(scene: Any, graph: Any = None) -> tuple[list[InputSignal], list[str]]:
    """``(inputs, notices)``: no input when the scene has a source, else the first free optical port. The input takes
    the wavelength of the drawn beam that meets that port (``beam_wavelength``), else the engine's default. ``graph``
    is the scene's signal graph, built when not given."""

    graph = graph if graph is not None else build_graph(scene)
    if has_emitter(scene, graph):
        return [], []
    for sid, part in graph.parts.items():
        for port, spec in part.ports().items():
            if spec.kind in _NOT_OPTICAL or graph.links_at(sid, port):
                continue
            nm = beam_wavelength(scene, part, port)
            try:
                found = InputSignal(f"port:{sid}:{port}", **({} if nm is None else {"wavelength_nm": nm}))
                found.validate(graph)
            except AnimationError:
                continue
            return [found], [f"no light source: light enters at {sid}.{port}"]
    return [], ["no light source and no free optical input"]


def input_wavelength(graph: Any, inputs: list, params: dict) -> float | None:
    """The input wavelength (nm): the first input's, else the first emitter's; None without light. Only an
    ``InputSignal`` has a wavelength: other inputs go to the engine as they are and are passed over here."""

    for found in inputs:
        if isinstance(found, InputSignal):
            return float(found.wavelength_nm)
    for sid, part in graph.parts.items():
        behaviour = find_behaviour(part)
        found = behaviour.emissions(part, sid, params) if behaviour is not None else []
        if found:
            return float(found[0].wavelength_nm)
    return None
