"""Stable ids: the same part has the same id in every view and in every run of a script."""

from __future__ import annotations

from typing import Any

from optodraw.core.component import Group
from optodraw.core.routing import Route


def scene_ids(scene: Any) -> dict[int, str]:
    """``id(node) -> '<type in lower case><n>'``, numbered per type in walk order from 1.

    Every kind of route (waveguide, fibre, electrical) counts as ``route``: route1, route2, ...
    """

    counts: dict[str, int] = {}
    ids: dict[int, str] = {}
    for node in scene.walk():
        if isinstance(node, Group):
            continue
        ctype = "route" if isinstance(node, Route) else (getattr(node, "component_type", "") or type(node).__name__).lower()
        counts[ctype] = counts.get(ctype, 0) + 1
        ids[id(node)] = f"{ctype}{counts[ctype]}"
    return ids


def part_id(sid: str) -> str:
    return f"part:{sid}"


def port_id(sid: str, port: str) -> str:
    return f"port:{sid}:{port}"


def route_id(sid: str) -> str:
    return f"route:{sid}"


def path_id(sid: str, in_port: str, out_port: str, name: str = "") -> str:
    return f"path:{sid}:{in_port}->{out_port}" + (f"#{name}" if name else "")
