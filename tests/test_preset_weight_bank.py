"""The weight bank preset is the broadcast-and-weight network of Tait et al. 2017, Fig. 1a.

Four nodes, each a laser and an MZM, join a WDM multiplexer (an AWG). One bus loops back to a 1:4 splitter that
broadcasts to four microring weight banks. Each bank has its own balanced detector, and each detector drives its
own node's MZM.
"""

from __future__ import annotations

import optodraw  # noqa: F401  (fills the registry)
from optodraw.presets import build_preset
from optodraw.registry import build_component


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


def test_the_multiplexer_is_an_awg_and_each_mzm_takes_its_own_channel_in_row_order():
    scene = build_preset("wdm_delay_weight_bank_chip")
    awgs = [node for node in scene.walk() if node.component_type == "AWG"]
    assert len(awgs) == 1
    mux = awgs[0]
    feeds = sorted(((route.start_component, route.end_port) for route in _routes(scene)
                    if route.end_component is mux and route.start_component.component_type == "MZM"),
                   key=lambda feed: -feed[0].world_position.y)
    assert len(feeds) == 4 and len({port for _, port in feeds}) == 4
    levels = [mux.world_port(port).center.y for _, port in feeds]
    assert levels == sorted(levels, reverse=True)                         # top row, top channel: no crossing


def test_each_detector_drives_its_own_node():
    scene = build_preset("wdm_delay_weight_bank_chip")
    drives = [(route.start_component, route.end_component) for route in _routes(scene)
              if route.kind == "electrical" and route.start_component.component_type == "OnChipBalancedPhotodetector"]
    assert len(drives) == 4 and all(mzm.component_type == "MZM" for _, mzm in drives)
    assert len({id(mzm) for _, mzm in drives}) == 4


def test_the_old_stand_in_parts_are_gone():
    """A user must not pick an old design by mistake: the catalog offers the full parts only."""

    from optodraw.registry import component_registry

    catalog = component_registry()
    for old, full in (("PresetDelaySpiral", "Spiral"), ("PresetMRRWeightBank", "MicroringWeightBank"),
                      ("PresetStarCoupler", "StarCoupler"), ("PresetBalancedPhotodetector", "OnChipBalancedPhotodetector")):
        assert old not in catalog and full in catalog


def test_a_label_clears_art_that_is_not_centred_on_the_part():
    """The name used to sit half the art's height above the centre. A weight bank
    is drawn almost wholly above its bus, so its name landed on the drop bus."""

    import re

    from optodraw import Scene
    from optodraw.layout import estimate_component_bounds

    for name in ("MicroringWeightBank", "PolarizationController"):
        part = build_component(name, label="NAME")
        scene = Scene(width=200, height=120)
        scene.add(part)
        svg = scene.render_svg().as_svg()
        text_y = float(re.search(r'<text[^>]*\by="(-?[\d.]+)"[^>]*>\s*NAME', svg).group(1))
        top = estimate_component_bounds(part)[3]                 # the highest point of the art, y up
        assert -text_y >= top + 2.0, f"{name}: the label at {-text_y} is inside art that reaches {top}"
