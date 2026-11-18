"""PDK bootstrap adapters — pure helpers, no gdsfactory install needed.

``layer_stack_hints`` and ``bootstrap_process_skeleton`` duck-type the
gdsfactory ``LayerStack`` object, so fakes cover every branch. The skeleton
round-trips through ``ProcessDefinition.from_mapping`` to prove it is a
loadable process definition, not just a dict shape.
"""

from __future__ import annotations

from types import SimpleNamespace

from optodraw.gds.xsection.pdk_adapters import (
    bootstrap_process_skeleton,
    layer_stack_hints,
)


def _level(gds, *, zmin=0.0, thickness=0.0, material=""):
    return SimpleNamespace(
        layer=SimpleNamespace(layer=tuple(gds)),
        zmin=zmin,
        thickness=thickness,
        material=material,
    )


def _stack(**layers):
    return SimpleNamespace(layers=dict(layers))


class TestLayerStackHints:

    def test_level_without_layer_spec_is_skipped(self):
        stack = _stack(odd=SimpleNamespace(zmin=1.0))
        assert layer_stack_hints(stack) == {}


class TestBootstrapSkeleton:

    def test_layout_layer_map_wins_over_stack(self):
        stack = _stack(wg=_level((1, 0)))
        skeleton = bootstrap_process_skeleton(
            layer_stack=stack, layout_layer_map={"core": (10, 0)}
        )
        assert skeleton["layout_layers"] == {"core": {"gds": [10, 0]}}


    def test_skeleton_loads_as_process_definition(self):
        from optodraw.gds.xsection.schema import ProcessDefinition

        stack = _stack(wg=_level((1, 0), zmin=2.0, thickness=0.22, material="si"))
        skeleton = bootstrap_process_skeleton(name="demo", layer_stack=stack)
        definition = ProcessDefinition.from_mapping(skeleton)
        assert definition.name == "demo"
        assert definition.units == "um"
        assert abs(definition.device.thickness - 0.22) < 1e-12      # the device band 2.0 .. 2.22
        assert set(definition.layout_layers) == {"wg"}
