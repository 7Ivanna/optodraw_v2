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
    def test_missing_layers_gives_empty_hints(self):
        assert layer_stack_hints(SimpleNamespace()) == {}
        assert layer_stack_hints(SimpleNamespace(layers=None)) == {}

    def test_level_without_layer_spec_is_skipped(self):
        stack = _stack(odd=SimpleNamespace(zmin=1.0))
        assert layer_stack_hints(stack) == {}

    def test_extracts_gds_z_and_material(self):
        stack = _stack(wg=_level((1, 0), zmin=2.0, thickness=0.22, material="si"))
        assert layer_stack_hints(stack) == {
            "wg": {"gds": (1, 0), "zmin": 2.0, "thickness": 0.22, "material": "si"}
        }

    def test_missing_numbers_default_to_zero(self):
        stack = _stack(slab=_level((2, 0)))
        hint = layer_stack_hints(stack)["slab"]
        assert (hint["zmin"], hint["thickness"], hint["material"]) == (0.0, 0.0, "")


class TestBootstrapSkeleton:
    def test_defaults_with_no_inputs(self):
        skeleton = bootstrap_process_skeleton()
        assert skeleton["name"] == "bootstrap_process"
        assert skeleton["units"] == "um"
        assert skeleton["layout_layers"] == {}
        assert skeleton["process"] == []
        assert skeleton["device"]["thickness"] == 0.22

    def test_layout_layer_map_wins_over_stack(self):
        stack = _stack(wg=_level((1, 0)))
        skeleton = bootstrap_process_skeleton(
            layer_stack=stack, layout_layer_map={"core": (10, 0)}
        )
        assert skeleton["layout_layers"] == {"core": {"gds": [10, 0]}}

    def test_stack_layers_become_layout_layers(self):
        stack = _stack(wg=_level((1, 0)), slab=_level((2, 0)))
        skeleton = bootstrap_process_skeleton(layer_stack=stack)
        assert skeleton["layout_layers"] == {
            "wg": {"gds": [1, 0]},
            "slab": {"gds": [2, 0]},
        }

    def test_silicon_layer_sets_device_thickness(self):
        stack = _stack(
            wg=_level((1, 0), zmin=2.0, thickness=0.22, material="si"),
            clad=_level((0, 0), zmin=0.0, thickness=2.0, material="sio2"),
        )
        device = bootstrap_process_skeleton(layer_stack=stack)["device"]
        assert device["thickness"] == 0.22
        assert device["z_on_box"] == 2.0

    def test_oxide_and_empty_layers_ignored_for_device(self):
        stack = _stack(
            clad=_level((0, 0), thickness=2.0, material="SiO2"),
            flat=_level((3, 0), thickness=0.0, material="si"),
        )
        device = bootstrap_process_skeleton(layer_stack=stack)["device"]
        assert device["thickness"] == 0.22  # silicon default kept

    def test_skeleton_loads_as_process_definition(self):
        from optodraw.gds.xsection.schema import ProcessDefinition

        stack = _stack(wg=_level((1, 0), zmin=2.0, thickness=0.22, material="si"))
        skeleton = bootstrap_process_skeleton(name="demo", layer_stack=stack)
        definition = ProcessDefinition.from_mapping(skeleton)
        assert definition.name == "demo"
        assert definition.units == "um"
        assert abs(definition.device.thickness - 0.22) < 1e-12      # the device band 2.0 .. 2.22
        assert set(definition.layout_layers) == {"wg"}
