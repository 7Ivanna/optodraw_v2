"""On a foundry stack, every on-chip part draws its core where the stack puts it, in the stack's material.

The coordinator measured it on lnoi400: the draw stack had core_z 0.5, and the Waveguide's core still ran from 0 to
0.5 in the 2D silicon blue, under the stack's lithium niobate ridge and on no slab. A part drew its core with its own
colour on the buried oxide; ``component_heights`` gave no core material; and a part that draws through a drawing
copy lost the scene's stack, so its metal stood at the schematic heights. Now a part draws each core solid with
``**self._core()``, and ``_on_the_stack`` adds the slab under a ridge (lnoi400) and the films over a core film (InP).

The stacks: lnoi400 (a ridge on a slab), cornerstone_si500 (SOI), cornerstone_sin300 (SiN), inp_generic (a film
stack). The checks hold for every on-chip part the stack tests check on the default stack.
"""

from __future__ import annotations

import pytest

pytest.importorskip("yaml")
pytest.importorskip("shapely")

from optodraw import Scene  # noqa: E402
from optodraw.gds.palette import material_fill  # noqa: E402
from optodraw.gds.parsers import load_layer_stack  # noqa: E402
from optodraw.registry import build_component, component_registry  # noqa: E402

STACKS = ("lnoi400", "cornerstone_si500", "cornerstone_sin300", "inp_generic")
# Not process layers on the die (as in test_onchip_stack.py): flip-chip dies, the die, and a preset group.
_NOT_ON_THE_STACK = {"TIA", "ADC", "DACDriver", "ChipSubstrate", "GDSModel", "CustomModel", "Route", "PresetWDMInput"}
_BONDED = {"indium_phosphide", "gallium_arsenide"}     # a laser's III-V mesa, bonded over the process
_ON_THE_CORE = {"germanium", "sio2", "gst"}             # Ge, the oxide and a GST film over a core start on its top
_VARIANTS = {"MZM": [{"drive_style": "gsg"}], "PhaseShifter": [{"mechanism": "pn"}],
             "MicroringResonator": [{"with_heater": True}]}
PARTS = [(name, kwargs) for name, spec in sorted(component_registry().items())
         if spec.category == "on_chip" and name not in _NOT_ON_THE_STACK
         for kwargs in [{}, *_VARIANTS.get(name, [])]]


def _on(stack: str, name: str, **kwargs):
    scene = Scene(platform="on_chip")
    part = scene.add(build_component(name, **kwargs))
    scene.set_foundry_stack(stack)
    return scene, part


def _solids(node):
    """(bottom, top, preset, colour) of every box and extruded polygon of a part's tree."""

    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _solids(child)
        return
    if node.get("shape") not in ("box", "extruded_polygon"):
        return
    height = float(node["height"])
    y = float((node.get("position") or [0.0, 0.0, 0.0])[1])
    bottom = y if node["shape"] == "extruded_polygon" else y - height / 2.0
    material = node.get("material") or {}
    yield bottom, bottom + height, material.get("preset", ""), str(material.get("color", "")).lower()


def _levels(part, core) -> set[float]:
    stack = part._draw_layer_stack()
    scale = part._draw_thickness() / part._foundry_heights()["chip_thickness"]
    return {0.0, stack["core_z"], stack["rib_z"], stack["implant_z"], stack["contact_z"],
            stack["contact_z"] + stack["contact_height"], stack["via_z"], stack["metal_z"],
            stack["metal_z"] + stack["metal_height"], stack["heater_z"], stack["heater_z"] + stack["heater_height"],
            stack["pad_z"], stack["pad_z"] + stack["pad_height"], *(z * scale for z, _, _ in core.over)}


def test_each_stack_names_its_core_material_and_level():
    lnoi, sin, inp = (load_layer_stack(name) for name in ("lnoi400", "cornerstone_sin300", "inp_generic"))
    assert (lnoi.component_core().core, lnoi.component_core().slab) == ("lithium_niobate", "lithium_niobate")
    assert lnoi.component_heights()["core_z"] == pytest.approx(0.2)                     # the ridge on its slab
    assert sin.component_core().core == "silicon_nitride"
    heights, core = inp.component_heights(), inp.component_core()
    assert (core.core, heights["core_z"], heights["core_height"]) == ("ingaasp", 0.0, 0.5)   # the Q(1.25) film
    assert [m for _, _, m in core.over] == ["indium_phosphide", "ingaasp", "indium_phosphide", "ingaas"]
    assert sum(h for _, h, _ in core.over) == pytest.approx(2.12 - 0.5)                   # up to the wafer top
    assert core.fills["ingaasp"] == material_fill("ingaasp")


def test_a_waveguide_on_lnoi400_is_a_lithium_niobate_ridge_on_its_slab():
    _, guide = _on("lnoi400", "Waveguide")
    stack = guide._draw_layer_stack()
    fill = material_fill("lithium_niobate")
    rows = sorted(set(_solids(guide.geometry_3d())))
    assert rows == [(pytest.approx(0.0), pytest.approx(stack["core_z"]), "lithium_niobate", fill),
                    (pytest.approx(stack["core_z"]), pytest.approx(stack["core_z"] + stack["core_height"]),
                     "lithium_niobate", fill)], rows                   # mutant: z_offset 0 in _core(): fails


@pytest.mark.parametrize("stack", STACKS)
@pytest.mark.parametrize("name, kwargs", PARTS, ids=[f"{n}-{'-'.join(k) or 'default'}" for n, k in PARTS])
def test_every_core_solid_starts_on_the_stack_core_in_its_material(stack, name, kwargs):
    _, part = _on(stack, name, **kwargs)
    core, levels = part._foundry_core(), _levels(part, part._foundry_core())
    draw = part._draw_layer_stack()
    tolerance = 1e-6 + 1e-3 * max(levels)
    slab = (draw["rib_z"], draw["rib_z"] + draw["rib_height"])
    wrong = []
    rows = list(_solids(part.geometry_3d()))
    cores = [bottom for bottom, _, preset, _ in rows if preset == core.core]
    if cores and not any(abs(bottom - draw["core_z"]) <= tolerance for bottom in cores):
        wrong.append(f"no {core.core} solid starts on the core level {draw['core_z']:.3f}")     # mutant: z_offset 0
    for bottom, end, preset, colour in rows:
        if end - bottom <= tolerance or (preset in _BONDED and colour not in core.fills.values()):
            continue
        if colour == part.color.lower():
            wrong.append(f"a solid in the part's 2D colour at {bottom:.3f}")      # mutant: self.color in _core()
        if preset == core.core and bottom < draw["core_z"] - tolerance \
                and (abs(bottom - slab[0]) > tolerance or abs(end - slab[1]) > tolerance):
            wrong.append(f"{preset} from {bottom:.3f} to {end:.3f}: under the core level and not the slab")
        allowed = levels | {draw["core_z"] + part._draw_thickness()} if preset in _ON_THE_CORE else levels
        if not any(abs(bottom - level) <= tolerance for level in allowed):
            wrong.append(f"{preset or colour} starts at {bottom:.3f}, on no level of {stack}")
    assert not wrong, f"{name} {kwargs} on {stack}: " + "; ".join(sorted(set(wrong))[:6])


@pytest.mark.parametrize("stack", STACKS)
@pytest.mark.parametrize("name, kwargs", PARTS, ids=[f"{n}-{'-'.join(k) or 'default'}" for n, k in PARTS])
def test_a_part_on_a_foundry_stack_puts_no_two_looks_on_one_plane(stack, name, kwargs):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    import viewer_flat

    from optodraw.renderers.vector3d_scene import scene_solids

    scene, _ = _on(stack, name, **kwargs)
    built = scene_solids(scene)
    solids = built.solids

    def look(solid):
        return f"{solid.look.preset or '?'} {solid.look.color} {solid.look.opacity:.2f}"

    pairs = sorted({f"{look(solids[a])} / {look(solids[b])}" for a, b in viewer_flat.coplanar(built, range(len(solids)))
                    if solids[a].look.color.lower() != solids[b].look.color.lower()
                    or abs(solids[a].look.opacity - solids[b].look.opacity) > 1e-6})
    assert not pairs, f"{name} {kwargs} on {stack}: two looks on one plane: {pairs}"


def test_a_drawing_copy_keeps_the_scene_stack():
    """The MZI draws through a copy in draw units, which has no parent: its heater stood at the schematic M1."""

    _, mzi = _on("lnoi400", "MZI")
    stack = mzi._draw_layer_stack()
    gold = [bottom for bottom, _, preset, _ in _solids(mzi.geometry_3d()) if preset == "gold"]
    assert gold and all(abs(bottom - stack["heater_z"]) < 1e-9 for bottom in gold), (gold, stack["heater_z"])


def test_a_waveguide_route_runs_on_the_core_level_with_its_slab():
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = Scene(platform="on_chip")
    a = scene.add(build_component("Waveguide", center=(0, 0)))
    b = scene.add(build_component("Waveguide", center=(40, 0)))
    scene.route((a, "o2"), (b, "o1"))
    scene.set_foundry_stack("lnoi400")
    strips = [item for item in ThreeJsRenderer(scene)._collect_scene_data() if item.get("type") == "route"]
    stack = a._draw_layer_stack()
    levels = sorted((item["stripZ"], item["stripThick"], item["stripMaterial"]["preset"]) for item in strips)
    assert levels == [(pytest.approx(0.0), pytest.approx(stack["rib_height"]), "lithium_niobate"),
                      (pytest.approx(stack["core_z"]), pytest.approx(stack["core_height"]), "lithium_niobate")]


def test_the_default_stack_keeps_the_part_colour_and_the_buried_oxide():
    part = build_component("MicroringResonator")
    rows = set(_solids(part.geometry_3d()))
    assert {(bottom, colour) for bottom, _, _, colour in rows} == {(0.0, part.color.lower())}


def _cladding(scene) -> list:
    """(plan in layout x and y, bottom, top) of each band of the scene's cladding entry, in draw units."""

    import shapely

    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    items = ThreeJsRenderer(scene)._collect_scene_data()
    entries = [item for item in items if item["type"] == "mesh" and item.get("sid") is None]
    assert len(entries) == 1, entries
    px, _, pz = entries[0]["position"]
    bands = []
    for solid in entries[0]["geometry"]["children"]:
        def layout(ring):
            return [(x + px, y - pz) for x, y, _ in ring]   # the shape's x, y to layout x, y
        plan = shapely.Polygon(layout(solid["points"]), [layout(hole) for hole in solid.get("holes", [])])
        bottom = solid["position"][1]
        bands.append((plan, bottom, bottom + solid["height"]))
    return bands


def test_the_cladding_carries_the_heater_and_opens_each_pad():
    """On cornerstone_si500 the MZI heater stood at the stack's 1.1 um with no cladding under it: it floated. Now
    the 3D draws the stack's cladding as one clear body over the parts, from the top of the buried oxide to the top
    of the fill, filled round the cores; the heater rests on it. On siepic_ebeam a pad lies under the 4.5 um
    cladding, and the cladding is etched open down to it."""

    import shapely

    from optodraw import ElectricalPad

    scene, mzi = _on("cornerstone_si500", "MZI")
    bands = _cladding(scene)                                      # mutant: no cladding entry: fails
    scale = mzi._draw_thickness() / mzi._foundry_heights()["chip_thickness"]
    assert min(b for _, b, _ in bands) == pytest.approx(0.0)
    assert max(t for _, _, t in bands) == pytest.approx(1.1 * scale)                 # the stack's tox
    gold = [bottom for bottom, _, preset, _ in _solids(mzi.geometry_3d()) if preset == "gold"]
    assert gold and all(bottom == pytest.approx(1.1 * scale) for bottom in gold)       # the heater on it
    core = mzi._draw_thickness()
    guide = shapely.Point(mzi.ports()["o1"].center.x + 0.5, mzi.ports()["o1"].center.y)
    assert not any(plan.contains(guide) for plan, b, t in bands if b < core / 2 < t)   # it fills round the core
    assert any(plan.contains(guide) for plan, b, t in bands if b < core * 1.01 < t)    # and covers it

    scene = Scene(platform="on_chip")
    scene.add(build_component("Waveguide", center=(0, 0)))
    scene.add(ElectricalPad(center=(0, 30)))
    scene.set_foundry_stack("siepic_ebeam")
    bands = _cladding(scene)
    stack = scene.root.children[0]._draw_layer_stack()
    top = max(t for _, _, t in bands)
    over = stack["pad_z"] + stack["pad_height"]
    assert over < top                                             # the pad lies under the cladding top
    centre = shapely.Point(0, 30)
    assert any(plan.contains(centre) for plan, b, t in bands if t <= stack["pad_z"] + 1e-9)  # oxide under the pad
    assert not any(plan.contains(centre) for plan, b, t in bands if t > over + 1e-9)       # mutant: no window: fails


@pytest.mark.parametrize("stack", [*STACKS, "gdsfactory_generic"])
def test_a_stack_waveguide_width_sets_the_draw_scale(stack):
    """inp_generic stood its 2.12 um ridge 5.3 units tall on the 1.2 unit guide every part draws: a fence. A stack
    that gives its waveguide width now draws that width as the parts' guide, and its heights at the same scale, so
    the guide has the stack's own height to width. A stack with no width keeps the default scale."""

    spec = load_layer_stack(stack)
    _, guide = _on(stack, "Waveguide")
    width = guide.ports()["o1"].width
    assert width == pytest.approx(1.2)                            # the guide every part and route draws
    core = guide._foundry_heights()["chip_thickness"]
    if spec.waveguide_width is None:
        assert guide._draw_thickness() == pytest.approx(0.55 * core / 0.22)
    else:                                                         # mutant: the default scale: fails
        assert guide._draw_thickness() / width == pytest.approx(core / spec.waveguide_width)


def test_the_vector_view_draws_the_cladding_as_one_body():
    """The cladding is built in bands, one per level of the parts in it. The vector view draws no seam where two
    bands touch: the face of the lower band that lies on the upper band is inside the body."""

    from optodraw.renderers.vector3d import _inside
    from optodraw.renderers.vector3d_hidden import camera_for
    from optodraw.renderers.vector3d_scene import scene_solids

    scene, _ = _on("cornerstone_si500", "MZI")
    built = scene_solids(scene)
    camera, _ = camera_for(built, "isometric", "perspective", 60.0)
    clear = [i for i, face in enumerate(built.faces) if built.solids[face.solid].look.clear
             and camera.facing(face) and face.normal[1] > 0.5]
    top = max(float(built.faces[i].ring[0][1]) for i in clear)
    inner = [i for i in clear if float(built.faces[i].ring[0][1]) < top - 1e-6]
    inside = _inside(built.faces, built.solids, camera)
    assert inner and all(i in inside for i in inner)              # mutant: _inside returns {}: fails


def test_a_heater_on_a_stack_with_no_metal_rests_on_the_cladding():
    """inp_generic names no metal or heater level, so the MZI heater kept the default height and floated 0.30 above
    the polyimide fill. With no level of its own, a heater is deposited on the top dielectric: it rests on it."""

    scene, mzi = _on("inp_generic", "MZI")
    top = max(t for _, _, t in _cladding(scene))
    gold = [bottom for bottom, _, preset, _ in _solids(mzi.geometry_3d()) if preset == "gold"]
    assert gold and all(bottom == pytest.approx(top) for bottom in gold)
