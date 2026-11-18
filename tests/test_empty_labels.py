"""A part asked for no label has none: no default text comes back, in the scene or after a save and reload."""

from __future__ import annotations

import inspect
import warnings

import optodraw
from optodraw.core.component import Component
from optodraw.schema import scene_from_spec, scene_to_spec


def _parts():
    for name in sorted(dir(optodraw)):
        cls = getattr(optodraw, name)
        if inspect.isclass(cls) and issubclass(cls, Component) and cls is not Component:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    yield cls(label="")
            except Exception:
                continue                                  # a part that needs arguments of its own


def test_no_part_puts_a_default_text_in_place_of_an_empty_label():
    named = [(type(part).__name__, part.label) for part in _parts() if getattr(part, "label", "")]
    assert named == []


def test_an_empty_label_stays_empty_after_a_save_and_reload():
    scene = optodraw.Scene(title="labels", width=100, height=100, platform="free_space")
    for part in (optodraw.TranslationStage(label=""), optodraw.Lens(label=""), optodraw.ElectricalPad(label="")):
        scene.add(part)
    reloaded = scene_from_spec(scene_to_spec(scene))
    assert [node.label for node in reloaded.walk() if node is not reloaded and hasattr(node, "label")] == ["", "", ""]


def test_a_part_with_no_label_keeps_no_room_for_one_in_1d():
    from optodraw import ElectricalPad, Scene
    from optodraw.symbols.schematic import MARGIN, build_schematic

    scene = Scene(title="", width=60, height=60, platform="on_chip")
    scene.add(ElectricalPad(center=(0, 0), width=10, height=10, label=""))
    schematic = build_schematic(scene)
    pad = schematic.items[0]
    assert schematic.height == pad.y + pad.symbol.height + MARGIN
