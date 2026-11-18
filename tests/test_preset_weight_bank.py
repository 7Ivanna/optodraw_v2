"""The weight bank preset is the broadcast-and-weight network of Tait et al. 2017, Fig. 1a.

Four nodes, each a laser and an MZM, join a WDM multiplexer (an AWG). One bus loops back to a 1:4 splitter that
broadcasts to four microring weight banks. Each bank has its own balanced detector, and each detector drives its
own node's MZM.
"""

from __future__ import annotations

import optodraw  # noqa: F401  (fills the registry)
from optodraw.presets import build_preset


def _routes(scene):
    return [node for node in scene.walk() if getattr(node, "start_component", None) is not None
            and getattr(node, "end_component", None) is not None]


def test_each_weight_bank_has_its_own_balanced_detector():
    scene = build_preset("wdm_delay_weight_bank_chip")
    nodes = list(scene.walk())
    banks = [node for node in nodes if node.component_type == "MicroringWeightBank"]
    detectors = [node for node in nodes if node.component_type == "OnChipBalancedPhotodetector"]
    assert len(banks) == 4 and len(detectors) == 4
    used = set()
    for bank in banks:
        ends = {route.start_port: (route.end_component, route.end_port)
                for route in _routes(scene) if route.start_component is bank and route.kind == "waveguide"}
        assert set(ends) == {"o2", "drop"}, f"{bank.label}: both outputs go to a detector"
        (through_detector, through_port), (drop_detector, drop_port) = ends["o2"], ends["drop"]
        assert through_detector is drop_detector and through_detector in detectors
        detector = through_detector
        used.add(id(detector))
        upper = max(("o1", "o2"), key=lambda name: detector.world_port(name).center.y)
        assert drop_port == upper and through_port != upper                # the drop bus over, the through under
        assert abs(bank.world_port("o2").center.y - detector.world_port(through_port).center.y) < 0.5   # straight in
    assert len(used) == 4                                                # no detector is shared


