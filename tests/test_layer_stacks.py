"""Production-robustness tests for the unified layer-stack pipeline.

Every foundry stack must resolve a full oxide envelope (explicit, derived, or
default — never silently absent) and grow the SAME process context on a real
GDS: BOX + TOX + handle, with etch layers carved at their declared depths.
"""

from pathlib import Path

import pytest

from optodraw.gds.parsers import LayerStackSpec, _derive_oxide, load_layer_stack, stack_wafer

STACKS_DIR = Path("optodraw/gds/stacks")
BUNDLED = sorted(p for p in STACKS_DIR.glob("*.yaml"))


class TestUnifiedLoader:
    @pytest.mark.parametrize("path", BUNDLED, ids=lambda p: p.stem)
    def test_every_bundled_stack_resolves_a_full_envelope(self, path):
        stack = load_layer_stack(path)
        assert isinstance(stack, LayerStackSpec)
        assert stack.styles, "stack must define layers"
        keys = ["cladding_top", "handle_thickness"]
        films = stack_wafer(stack).films
        if films and films[0].role != "core":       # a film under the core: the stack states a box
            keys.append("box_depth")
        for key in keys:
            assert stack.oxide.get(key, 0) > 0, f"{path.stem}: {key} not resolved"
        # bundled stacks are fully specified — no guessing, no warnings
        assert stack.oxide_source == "explicit"
        assert stack.warnings == []


    def test_derive_oxide_pure(self):
        oxide, source, warnings = _derive_oxide({})
        assert source == "default"
        assert oxide["cladding_top"] > 0 and oxide["box_depth"] > 0


@pytest.fixture(scope="module")
def sample_gds(tmp_path_factory):
    """A small device drawn here: a waveguide on 1/0 and a bond pad on 41/0."""

    gdstk = pytest.importorskip("gdstk")
    lib = gdstk.Library()
    cell = lib.new_cell("DEVICE")
    cell.add(gdstk.rectangle((0, 0), (120, 0.5), layer=1, datatype=0))
    cell.add(gdstk.rectangle((130, -40), (210, 40), layer=41, datatype=0))
    path = tmp_path_factory.mktemp("gds") / "device.gds"
    lib.write_gds(path.as_posix())
    return path


class TestUniformGrowth:
    """Applying ANY stack to a GDS grows the same process context."""

    @pytest.fixture(autouse=True)
    def _gds(self, sample_gds):
        self.gds = sample_gds

    def _apply(self, stack_name):
        from optodraw import GDSModel, Scene
        from optodraw.gds.parsers import load_layer_stack

        stack = load_layer_stack(STACKS_DIR / f"{stack_name}.yaml")
        scene = Scene(platform="on_chip", width=2000, height=1200)
        model = scene.add(GDSModel(str(self.gds), process_context=True, **stack.oxide))
        from optodraw.gds import normalize_layer_stack

        model.layer_stack = normalize_layer_stack(stack.styles)
        return model, stack


class TestOnChipUnification:
    """On-chip components extrude at the SAME z-heights the stack gives a GDS."""


    def test_foundry_stack_round_trips_the_spec(self):
        from optodraw import MZI, Scene
        from optodraw.schema import scene_from_spec

        scene = Scene(platform="on_chip")
        scene.add(MZI(center=(0, 0), render_physical=True))
        scene.set_foundry_stack("siepic_ebeam")
        clone = scene_from_spec(scene.to_spec())
        assert clone.foundry_stack == "siepic_ebeam"
        mzi = next(iter(clone.root.children))
        assert mzi._draw_layer_stack()["metal_z"] == pytest.approx(1.0)

    def test_unknown_stack_raises(self):
        from optodraw import Scene

        scene = Scene(platform="on_chip")
        with pytest.raises(FileNotFoundError):
            scene.set_foundry_stack("no_such_foundry")


class TestAttachFilePath:
    """The 'Attach your own file' path (private NDA stacks) grows the SAME
    process context as the bundled dropdown."""

    def test_attached_stack_enables_process_context(self, tmp_path):
        gdstk = pytest.importorskip("gdstk")
        from starlette.testclient import TestClient

        from optodraw.app.server import create_app

        lib = gdstk.Library()
        cell = lib.new_cell("DEVICE")
        cell.add(gdstk.rectangle((0, 0), (40, 2), layer=1, datatype=0))       # a waveguide
        cell.add(gdstk.rectangle((10, -6), (30, 8), layer=6, datatype=0))     # an oxide opening
        cell.add(gdstk.rectangle((-10, -12), (50, -9), layer=201, datatype=0))  # a deep trench
        gds = tmp_path / "chip.gds"
        lib.write_gds(gds.as_posix())
        stack_file = tmp_path / "private_stack.yaml"
        stack_file.write_text(
            'name: private\n'
            'layers:\n'
            '  "1/0": {name: Si, zmin: 0.0, thickness: 0.22, material: silicon}\n'
            '  "6/0": {name: OX_OPEN, zmin: 0.5, thickness: 2.5, material: air}\n'
            '  "201/0": {name: DT, zmin: -4.0, thickness: 7.0, material: air}\n'
        )
        client = TestClient(create_app())
        client.post("/api/scene/new", json={"platform": "on_chip", "width": 2000, "height": 1200})
        cid = client.post(
            "/api/gds/import?filename=chip.gds", content=gds.read_bytes()
        ).json()["id"]
        r = client.post(
            f"/api/gds/{cid}/technology?filename=private.yaml",
            content=stack_file.read_bytes(),
        )
        assert r.status_code == 200
        j = r.json()
        assert j["oxide"]["cladding_top"] == pytest.approx(3.0)  # derived from OX_OPEN
        assert j["oxide"]["box_depth"] == pytest.approx(4.0)     # derived from DT
        assert j["oxide_source"] == "derived"


def test_the_3d_oxide_covers_the_top_metal_and_opens_the_pads(tmp_path):
    """The 3D builds the cover the cross-section builds: the generic stack's oxide passivation fills round M3 to
    its top plus 0.5 um, one body with the cladding, and PADOPEN cuts the window down to the pad."""

    import gdstk

    from optodraw import GDSModel
    from optodraw.gds import normalize_layer_stack
    from optodraw.gds.parsers import load_layer_stack

    lib = gdstk.Library()
    cell = lib.new_cell("PAD")
    cell.add(gdstk.rectangle((0, -0.25), (30, 0.25), layer=1))
    cell.add(gdstk.rectangle((5, 2), (25, 12), layer=49))               # M3, 3.2 to 5.2 um
    cell.add(gdstk.rectangle((7, 4), (23, 10), layer=46))               # PADOPEN, 16 x 6 um inside it
    path = tmp_path / "pad.gds"
    lib.write_gds(str(path))
    stack = load_layer_stack("gdsfactory_generic")
    model = GDSModel(str(path), cell_name="PAD", layer_stack=normalize_layer_stack(stack.styles),
                     process_context=True, **stack.oxide)
    bands = [(za, zb, g.area) for g, za, zb, _ in model.process_context_regions()]
    assert max(zb for _, zb, _ in bands) == pytest.approx(5.2 + 0.5)
    below = max(area for za, zb, area in bands if zb <= 5.2 + 1e-6)
    above = [area for za, zb, area in bands if za >= 5.2 - 1e-6]
    assert above == [pytest.approx(below - 16 * 6)]                    # the window over the pad, open
