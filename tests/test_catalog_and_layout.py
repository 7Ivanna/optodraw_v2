"""Tests for discovery and layout convenience APIs."""

import pytest

from optodraw import (
    Lens,
    Laser,
    Mirror,
    MicroringResonator,
    component_catalog,
    describe_component,
    list_components,
    list_material_presets,
    get_material_preset,
)
from optodraw.core.scene import Scene
from optodraw.layout import arrange_line


class TestCatalogs:
    def test_builtin_component_catalog(self):
        catalog = component_catalog()
        assert "Lens" in catalog
        assert "GratingCouplerArray" in catalog
        assert catalog["MicroringResonator"]["platform"] == "on_chip"

    def test_describe_component(self):
        info = describe_component("GDSModel")
        assert info["category"] == "models"
        assert "gdsfactory" in info["description"].lower()

    def test_grating_coupler_array_is_discoverable(self):
        info = describe_component("GratingCouplerArray")
        assert info["category"] == "on_chip"
        assert "stub" in info["description"].lower()

    def test_electronics_primitives_are_discoverable(self):
        electronics = list_components(category="electronics")
        assert "ElectricalPad" in electronics
        assert "GSGProbePad" in electronics
        assert "RFDriver" in electronics
        assert "Microcontroller" in electronics
        assert "MEMSActuator" in electronics
        assert "PCB" in electronics
        assert "ElectricalIOBank" in electronics
        assert "BalancedPhotodetector" in electronics
        assert "CoherentReceiver" in electronics
        assert "TransmitterMacro" in electronics
        assert "ReceiverMacro" in electronics
        assert describe_component("HeaterPad")["platform"] == "on_chip"


# Parts that papers do not show as symbols. Duplicates (Transposer = Interposer,
# ElectricalPadArray = ElectricalIOBank, ThermalPhaseShifter = PhaseShifter, IntegratorTIA =
# TIABlock(mode="integrator")) and package parts seen only in cross-sections (bumps, vias, bonds).
REMOVED = ["Transposer", "ElectricalPadArray", "ThermalPhaseShifter", "IntegratorTIA", "Interposer",
           "SolderBumpGrid", "ViaGrid", "ViaStack", "PadOpening", "Wirebond", "RFLaunch"]


@pytest.mark.parametrize("name", REMOVED)
def test_a_part_that_papers_do_not_show_is_not_in_the_catalog(name):
    import optodraw
    import optodraw.components.electronics as electronics
    from optodraw.registry import component_registry

    assert name not in component_registry()
    assert not hasattr(optodraw, name) and not hasattr(electronics, name)


def test_an_integrating_tia_is_a_tia_block_mode():
    """IntegratorTIA was TIABlock(mode="integrator") under another name; the mode keeps its capacitor mark."""

    from optodraw import TIABlock
    from optodraw.symbols import lookup

    assert lookup(TIABlock(mode="integrator")).params == {"mark": "capacitor"}
    assert lookup(TIABlock()).params == {"mark": "resistor"}


class TestMaterials:
    def test_material_presets(self):
        presets = list_material_presets()
        assert "gold" in presets
        assert get_material_preset("silicon")["color"].startswith("#")


class TestLayoutHelpers:
    def test_arrange_line_respects_spacing(self):
        laser = Laser(center=(0, 0))
        mirror = Mirror(center=(0, 0))
        arrange_line([laser, mirror], origin=(-40, 0), spacing=20)
        assert laser.transform.position.x == -40
        assert mirror.transform.position.x > laser.transform.position.x

    def test_scene_optimize_layout(self):
        scene = Scene(platform="free_space")
        laser = scene.add(Laser(center=(0, 0), label="Laser"))
        mirror = scene.add(Mirror(center=(0, 0), angle=45, label="Mirror"))
        lens = scene.add(Lens(center=(0, 0), angle=90, label="Lens"))
        scene.optimize_layout([laser, mirror, lens], spacing=18, origin=(-60, 0))
        assert laser.transform.position.x == -60
        assert mirror.transform.position.x > laser.transform.position.x
        assert lens.transform.position.x > mirror.transform.position.x


class TestComponentPreview:
    def test_component_can_render_self_to_threejs(self):
        ring = MicroringResonator(label="Preview Ring", material_preset="silicon")
        html = ring.render_threejs(show_grid=False)
        assert "Preview Ring" in html
        assert "materialPresets" in html

def test_gds_loader_skips_gdsfactory_context_cell(tmp_path):
    """gdsfactory exports a "$$$CONTEXT_INFO$$$" top cell; the loader must resolve
    to the real device instead, or referenced geometry (e.g. an OX_OPEN window) is
    silently dropped. Regression for a real device import."""
    import gdstk

    from optodraw.gds.layout import _select_gds_cell, load_gds_geometry_from_path

    lib = gdstk.Library()
    win = lib.new_cell("oxwin")  # referenced sub-cell carrying layer 154/0
    win.add(gdstk.rectangle((0, 0), (5, 5), layer=154, datatype=0))
    dev = lib.new_cell("DEVICE")  # the real device: Si rib + a reference to the window
    dev.add(gdstk.rectangle((0, 0), (20, 1), layer=10, datatype=0))
    dev.add(gdstk.Reference(win, origin=(8, 3)))
    lib.new_cell("$$$CONTEXT_INFO$$$")  # gdsfactory metadata cell (no geometry)

    assert _select_gds_cell(lib, None).name == "DEVICE"  # not the $$$ cell

    path = tmp_path / "dev.gds"
    lib.write_gds(str(path))
    geo = load_gds_geometry_from_path(str(path), None, scale=1.0)
    assert geo is not None
    assert (154, 0) in geo.polygons_by_spec  # the referenced OX_OPEN window is read
    assert (10, 0) in geo.polygons_by_spec


def test_gds_process_context_wraps_oxide_and_carves_openings():
    """process_context=True auto-adds SiO2 (BOX + top cladding) on handle-Si and
    subtracts material-'air' layers (OX_OPEN / deep trench) as real holes."""
    from optodraw.components.models import GDSModel

    m = GDSModel(source="x.gds", process_context=True, z_exaggeration=1.0)
    m._polygons_by_spec = {
        (10, 0): [[(0, 0), (40, 0), (40, 20), (0, 20)]],     # Si
        (154, 0): [[(12, 6), (28, 6), (28, 14), (12, 14)]],  # OX_OPEN window (air)
    }
    m.layer_stack = {
        (10, 0): {"zmin": 0.0, "thickness": 0.22, "material_preset": "silicon"},
        (154, 0): {"zmin": 0.72, "thickness": 2.28, "material_preset": "air"},
    }
    children = m.geometry_3d()["children"]
    presets = [(c.get("material") or {}).get("preset") for c in children]
    # auto oxide cladding: a translucent depthWrite:false block (not heavy glass preset)
    oxide = [c for c in children if (c.get("material") or {}).get("depthWrite") is False]
    assert oxide and all((c.get("material") or {}).get("opacity", 1) < 1 for c in oxide)
    assert presets.count("air") == 0  # the air layer is carved, not drawn solid
    holed = [c for c in children if c.get("holes")]
    assert len(holed) == 1  # the OX_OPEN window is a hole in the oxide
    assert holed[0].get("edges")  # the opening is outlined so the cut is legible
    hole = holed[0]["holes"][0]
    xs = [p[0] for p in hole]
    assert min(xs) == 12 and max(xs) == 28  # hole matches the OX_OPEN extent


def test_gds_process_context_off_by_default():
    from optodraw.components.models import GDSModel

    m = GDSModel(source="x.gds")
    assert m.process_context is False
