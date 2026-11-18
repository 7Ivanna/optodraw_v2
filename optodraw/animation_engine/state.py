"""The signal state: everything the light does in a scene, as plain JSON for the timeline and the player."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any

from .graph import build_graph
from .errors import AnimationError
from .ids import port_id
from .signals import to_json
from .solver import Propagation, check_passivity, propagate_pulses, steady_state


@dataclass
class SignalState:
    mode: str
    propagation: Propagation
    warnings: list[dict] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        prop = self.propagation
        edges = {eid: {"points": [[float(x), float(y)] for x, y in data["points"]], "length_um": data["length_um"],
                       "group_index": data["group_index"], "packets": [], "cw": []}
                 for eid, data in prop.edges.items()}
        for index, p in enumerate(prop.packets):
            record = {"from": port_id(*p.start), "to": port_id(*p.end), "t0": float(p.t0_ps), "t1": float(p.t1_ps),
                      "jones": to_json(p.jones), "wavelength_nm": float(p.wavelength_nm), "width": float(p.width_ps),
                      "source": p.source}
            if index in prop.bucket_of:                    # the light the engine added with it as it left its end port
                record["bucket"] = prop.bucket_of[index]
            edges[p.edge]["packets"].append(record)
        for s in prop.steady:
            edges[s.edge]["cw"].append({"from": port_id(*s.start), "to": port_id(*s.end),
                                        "wavelength_nm": float(s.wavelength_nm), "jones": to_json(s.jones)})
        return {"version": 1, "mode": self.mode,
                "duration_ps": max((float(p.t1_ps) for p in prop.packets), default=0.0),
                "edges": edges, "exits": [_plain(e) for e in prop.exits], "absorbed": [_plain(a) for a in prop.absorbed],
                "warnings": self.warnings}


def _plain(record: dict) -> dict:
    return {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in record.items()}


def compile_signal_state(scene: Any, *, mode: str = "pulse", params: dict[str, Any] | None = None,
                         floor: float | None = None, inputs=(), strict: bool = False,
                         heater_delay_scale: float = 1.0) -> SignalState:
    """``heater_delay_scale`` multiplies the heaters' delays of a pulse (a labelled display exaggeration; the phases
    do not change); continuous light has no delay."""

    if mode not in ("pulse", "cw"):
        raise ValueError("mode must be 'pulse' or 'cw'")
    graph = build_graph(scene)
    if mode == "pulse":
        prop = propagate_pulses(graph, params, floor=1e-3 if floor is None else floor, inputs=inputs,
                                heater_delay_scale=heater_delay_scale)
    else:
        prop = steady_state(graph, params, floor=1e-9 if floor is None else floor, inputs=inputs)
    check_passivity(graph, prop, params)
    notices = []
    seen = set()
    for record in prop.exits:
        sid, port = record["part"], record["port"]
        message = f"{sid}: light leaves unconnected port {port}"
        if strict:
            raise AnimationError(message)
        world = graph.parts[sid].world_port(port)
        angle = math.radians(world.orientation_deg)
        origin = [float(world.center.x), float(world.center.y)]
        direction = [math.cos(angle), math.sin(angle)]
        record.update({"id": f"exit:{port_id(sid, port)}", "from": port_id(sid, port),
                       "points": [origin, [origin[k] + 32.0 * direction[k] for k in (0, 1)]],
                       "direction": direction, "visual_only": True, "display_duration_s": 0.25})
        if (sid, port) not in seen:
            notices.append({"part": sid, "port": port, "message": message})
            warnings.warn(message, RuntimeWarning, stacklevel=2)
            seen.add((sid, port))
    return SignalState(mode, prop, notices)


def sweep_steady_state(scene: Any, param: str, values, params: dict[str, Any] | None = None, *, inputs=(), strict=False) -> list[SignalState]:
    return [compile_signal_state(scene, mode="cw", params={**(params or {}), param: value}, inputs=inputs, strict=strict) for value in values]
