"""The 3D crop of an InP chip fills its etched trenches with the stack's fill, as the section does.

inp_generic fills the etched space with polyimide flush with the top of the wafer. The section through a deep and a
shallow guide draws that polyimide in each trench, and 100 nm of it over the whole crop, where the contact layer comes
off. View3D.chip must hold polyimide there too, in the section's colour: opaque from each trench floor up to the top of
the wafer the etches leave, and clear from there up to the section's fill top, so the guide tops show from above."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
shapely = pytest.importorskip("shapely")
gdstk = pytest.importorskip("gdstk")

from shapely.geometry import Point, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from optodraw import View3D  # noqa: E402
from optodraw.figure.sources import cut_section  # noqa: E402
from optodraw.renderers.vector3d_scene import scene_solids  # noqa: E402
from optodraw.renderers.vector3d_solids import figure_color  # noqa: E402

STACK = "inp_generic"
LENGTH, TRENCH = 30.0, 3.0                       # um: the crop length and each trench width
REGION = (0.0, -18.0, LENGTH, 16.0)
GUIDES = ((8.0, 1.5, 1), (-8.0, 2.0, 2))         # (centre y, width, etch layer): a deep and a shallow guide
CUT = ((26.0, -13.5), (26.0, 13.0))              # A to A' across both guides
X = 15.0                                         # where the 3D view is probed along the guides


def _gds(tmp_path):
    library = gdstk.Library()
    cell = library.new_cell("INP_GUIDES")
    for y, width, layer in GUIDES:
        for side in (-1, 1):
            edge = y + side * width / 2
            cell.add(gdstk.rectangle((0, edge), (LENGTH, edge + side * TRENCH), layer=layer))
    cell.add(gdstk.rectangle(REGION[:2], REGION[2:], layer=3))     # the contact layer comes off the whole crop
    path = tmp_path / "inp.gds"
    library.write_gds(str(path))
    return path


def _probes():
    """(label, file y): the middle of each trench, and the middle of each guide."""

    out = []
    for y, width, layer in GUIDES:
        out.append((f"guide {layer}/0", y))
        for side in (-1, 1):
            out.append((f"trench {layer}/0 {'+' if side > 0 else '-'}", y + side * (width + TRENCH) / 2))
    return out


def _merge(spans):
    out = []
    for z0, z1 in sorted(spans):
        if out and z0 <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], z1))
        else:
            out.append((z0, z1))
    return [(round(z0, 4), round(z1, 4)) for z0, z1 in out]


def test_the_3d_crop_fills_each_trench_as_the_section_does(tmp_path):
    # mutant (the fault): _WaferChip leaves an etch that ends inside the wafer open; no polyimide stands in a trench
    # mutant: draw the fill all opaque (or all clear); the clear cap (or the opaque trench fill) is missing
    gds = _gds(tmp_path)
    xs = cut_section(gds, STACK, CUT).xs
    fill = [name for name, material in xs.materials.items() if material == "polyimide"]
    assert fill, "the section fills the etched space with the stack's polyimide"
    section_fill = unary_union([xs.regions[name] for name in fill])
    colour = {xs.fills[name] for name in fill}
    top = max(g.bounds[3] for name, g in xs.regions.items() if name not in fill and not g.is_empty)

    view = View3D.chip(gds, STACK, region=REGION, z_scale=3)
    world = np.array(view.fragment(60.0, font_pt=7).map["world"]).reshape(3, 4)
    z_scale = world[1, 2]                                            # world up is the true z times the height scale
    built = scene_solids(view.scene, renderer_options={"show_chip_base": False})
    polyimide = [s for s in built.solids if s.chip and s.look.preset == "polyimide"]

    wrong = []
    for label, y in _probes():
        s = y - CUT[0][1]
        cut = section_fill.intersection(box(s - 0.01, -10.0, s + 0.01, 10.0))
        want = _merge([(g.bounds[1], g.bounds[3]) for g in getattr(cut, "geoms", [cut]) if not g.is_empty])
        under = _merge([(z0, min(z1, top)) for z0, z1 in want if z0 < top - 1e-6])     # opaque, in the wafer
        over = _merge([(max(z0, top), z1) for z0, z1 in want if z1 > top + 1e-6])      # clear, over it
        at = world @ np.array([X, y, 0.0, 1.0])
        spans = {False: [], True: []}
        colours = set()
        for solid in polyimide:
            faces = [f for f in built.faces if f.solid == solid.id]
            tops = [f for f in faces if f.normal[1] > 0.99]
            if any(Polygon(f.ring[:, [0, 2]], [h[:, [0, 2]] for h in f.holes]).contains(Point(at[0], at[2]))
                   for f in tops):
                heights = np.concatenate([f.ring[:, 1] for f in faces]) / z_scale
                spans[solid.look.clear].append((float(heights.min()), float(heights.max())))
                colours.add(figure_color(solid))
        got_under, got_over = _merge(spans[False]), _merge(spans[True])
        if got_under != under or got_over != over or not colours <= colour:
            wrong.append(f"{label} (y = {y}): the 3D crop holds polyimide {sorted(colours)}, opaque over z "
                         f"{got_under} and clear over z {got_over}; the section {sorted(colour)} over z {want}, "
                         f"so opaque over {under} under the wafer top {top} and clear over {over}")
    assert not wrong, "\n".join(wrong)
