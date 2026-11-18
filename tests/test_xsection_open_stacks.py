"""Open stacks: a section for any core material and any stack, while the old stacks keep their sections."""

from __future__ import annotations

import functools
import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

gdstk = pytest.importorskip("gdstk")

from optodraw.core.markup import plain  # noqa: E402
from optodraw.gds import check_stack  # noqa: E402
from optodraw.gds.parsers import BUNDLED_STACKS, Fill, Film, Wafer, load_layer_stack, stack_wafer  # noqa: E402
from optodraw.gds.xsection import cross_section  # noqa: E402
from optodraw.gds.xsection.schematic import section_frame, section_place  # noqa: E402

RECORDER = Path(__file__).parent / "fixtures" / "xsection" / "record_old_sections.py"
GOLDEN = RECORDER.with_name("old_sections.json")


def _recorder():
    spec = importlib.util.spec_from_file_location("record_old_sections", RECORDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECORD = _recorder()


@functools.cache
def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _gds(path: Path, *layers: tuple[int, int]) -> Path:
    library = gdstk.Library()
    cell = library.new_cell("DEVICE")
    for index, (layer, datatype) in enumerate(layers):
        cell.add(gdstk.rectangle((-5.0, -0.5 - index), (5.0, 0.5 + index), layer=layer, datatype=datatype))
    library.write_gds(str(path))
    return path


def _strips(path: Path, strips: dict[tuple[int, int], list[tuple[float, float]]]) -> Path:
    """A GDS of strips along x, each from y0 to y1 (um), so a cut along y crosses each one."""

    library = gdstk.Library()
    cell = library.new_cell("DEVICE")
    for (layer, datatype), spans in strips.items():
        for y0, y1 in spans:
            cell.add(gdstk.rectangle((-10.0, y0), (10.0, y1), layer=layer, datatype=datatype))
    library.write_gds(str(path))
    return path


# The numbers of the open lnoi400 PDK stack, written here as a test stack.
_LNOI = ("name: lnoi test\nsubstrate: {material: silicon, thickness: 10.0}\n"
         "films:\n  - {name: BOX, material: sio2, thickness: 4.7}\n"
         "fill: {material: sio2, top: 2.0, planarized: true}\nlayers:\n"
         '  "2/0": {name: LN_RIDGE, role: core, zmin: 0.2, thickness: 0.2, material: lithium_niobate, sidewall_deg: 77}\n'
         '  "3/0": {name: LN_SLAB, role: slab, zmin: 0.0, thickness: 0.2, material: lithium_niobate, sidewall_deg: 77}\n')


def _lnoi_ridge(tmp_path: Path):
    """The lnoi400 rib xs_rwg1000 cut across: a ridge 1.0 um wide on a slab 10 um wide, centred at s = 8."""

    stack = tmp_path / "lnoi.yaml"
    stack.write_text(_LNOI)
    gds = _strips(tmp_path / "rib.gds", {(2, 0): [(-0.5, 0.5)], (3, 0): [(-5.0, 5.0)]})
    return cross_section(gds, stack, ((0.0, -8.0), (0.0, 8.0)), window=(0.0, 16.0))


@pytest.mark.parametrize("cut", RECORD.CUTS)
@pytest.mark.parametrize("stack", list(RECORD.STACKS))
def test_old_sections_are_unchanged(stack, cut):
    """The stacks bundled before the open stacks make the same sections: the same regions byte for byte, the same
    figure with its texts taken out, and the same texts at the same anchor points. Only the inside of a text
    element may change, where markup sets a script."""

    # Mutants that must fail it: the box top at zb + 1e-3; handle and box swapped in the wafer; the silicon fill
    # changed in the material table; text_box measuring text_width instead of the plain length.
    old = _golden()[f"{stack}/{cut}"]
    new = RECORD.fingerprint(RECORD.section(stack, cut, old["layers"]), [label[1] for label in old["labels"]])
    assert new["regions"] == old["regions"]
    assert new["art"] == old["art"]
    assert [label[:2] for label in new["labels"]] == [label[:2] for label in old["labels"]]
    for (text, _, x, y), (_, _, x0, y0) in zip(new["labels"], old["labels"]):
        assert (x, y) == pytest.approx((x0, y0), abs=0.01), text


def test_old_oxide_block_maps_onto_the_wafer(tmp_path):
    # Mutants that must fail it: the BOX zmin at 0; the check for both forms in one file removed.
    assert stack_wafer(load_layer_stack("gdsfactory_generic")) == Wafer(
        Film("substrate", "silicon", -5.0, 2.0), (Film("BOX", "sio2", -3.0, 3.0),), Fill("sio2", 3.0, False))
    both = tmp_path / "both.yaml"
    both.write_text('oxide:\n  box: {thickness: 2.0}\nfilms:\n  - {name: BOX, material: sio2, thickness: 2.0}\n'
                    'layers:\n  "1/0": {name: WG, zmin: 0, thickness: 0.22, material: silicon}\n')
    with pytest.raises(ValueError, match=r"oxide:.*films:"):
        load_layer_stack(both)


def test_films_lie_under_and_over_the_core(tmp_path):
    """The core film lies at z = 0, the films before it under it and the films after it over it. With no core film
    the last film ends at z = 0. ``top: flush`` is the top of the wafer: the highest film, or the core layers."""

    # Mutants that must fail it: the films stacked up from z = 0 whatever the core; flush taken as the top of the
    # highest film when no film is the core.
    stack = tmp_path / "inp.yaml"
    stack.write_text("name: t\nsubstrate: {material: indium_phosphide}\nfilms:\n"
                     "  - {name: Buffer, material: indium_phosphide, thickness: 0.5}\n"
                     "  - {name: Q, role: core, material: ingaasp, thickness: 0.5}\n"
                     "  - {name: Top, material: indium_phosphide, thickness: 1.5}\n"
                     "fill: {material: bcb, top: flush}\n"
                     'layers:\n  "1/0": {name: Deep etch, zmin: -0.2, thickness: 2.2, material: air}\n')
    spec = load_layer_stack(stack)
    wafer = stack_wafer(spec)
    assert [film.name for film in wafer.films] == ["Buffer", "Q", "Top"]
    assert [film.zmin for film in wafer.films] == pytest.approx([-0.5, 0.0, 0.5])
    assert (wafer.substrate.material, wafer.substrate.zmin) == ("indium_phosphide", pytest.approx(-2.5))
    assert (wafer.fill.material, wafer.fill.top) == ("bcb", pytest.approx(2.0))
    assert spec.oxide == pytest.approx({"box_depth": 0.5, "cladding_top": 2.0, "handle_thickness": 2.0})
    assert spec.oxide_source == "explicit"

    stack.write_text("name: t\nfilms:\n  - {name: BOX, material: sio2, thickness: 4.7}\nfill: {material: sio2, top: flush}\n"
                     'layers:\n  "2/0": {name: Ridge, role: core, zmin: 0.2, thickness: 0.2, material: lithium_niobate}\n'
                     '  "3/0": {name: Slab, zmin: 0.0, thickness: 0.2, material: lithium_niobate}\n')
    wafer = stack_wafer(load_layer_stack(stack))
    assert (wafer.films[0].zmin, wafer.fill.top) == pytest.approx((-4.7, 0.4))


_OXIDE = "oxide:\n  box: {thickness: 2.0}\n  tox: {thickness: 1.0}\n  handle: {thickness: 1.0}\n"
_LAYERS = ('layers:\n  "1/0": {name: WG, role: core, zmin: 0, thickness: 0.22, material: silicon}\n'
           '  "7/0": {name: Foo, zmin: 0.22, thickness: 0.1, material: unobtanium}\n')


def test_an_unknown_material_is_a_finding(tmp_path):
    """A material the table does not know draws grey. It is a finding until the stack names it under materials:,
    in the stack check and in the section. A section made from the files names it once, not twice."""

    # Mutants that must fail it: the unknown-material loop in check_stack removed; is_known ignoring the stack's
    # materials; the unknown-material loop in cross_section removed; material_fill ignoring the stack's materials.
    gds = _gds(tmp_path / "foo.gds", (1, 0), (7, 0))
    stack = tmp_path / "foo.yaml"
    stack.write_text(_OXIDE + _LAYERS)
    found = [finding for finding in check_stack(gds, stack) if "unobtanium" in finding]
    assert len(found) == 1 and "layer 7/0" in found[0] and "Foo" in found[0]
    cut = ((0.0, -4.0), (0.0, 4.0))
    for given in (stack, load_layer_stack(stack)):        # the files run check_stack too; a loaded stack does not
        xs = cross_section(gds, given, cut)
        found = [finding for finding in xs.check() if "unobtanium" in finding]
        assert len(found) == 1 and "layer 7/0" in found[0] and "Foo" in found[0], found
        assert 'data-region="Foo"' in xs.svg()
    stack.write_text(_OXIDE + 'materials:\n  unobtanium: {fill: "#123456"}\n' + _LAYERS)
    assert not [finding for finding in check_stack(gds, stack) if "unobtanium" in finding]
    xs = cross_section(gds, load_layer_stack(stack), cut)
    assert not [finding for finding in xs.check() if "unobtanium" in finding]
    assert re.search(r'data-region="Foo"[^>]*fill="#123456"', xs.svg())


_WAFER = "substrate: {material: silicon}\nfilms:\n  - {name: BOX, material: sio2, thickness: 2.0}\nfill: {top: 1.0}\n"


@pytest.mark.parametrize("text, finding", [
    ("substrate: {material: indium_phosphide}\nfilms:\n  - {name: Q, role: core, material: ingaasp, thickness: 0.5}\n"
     "  - {name: Q2, role: core, material: ingaasp, thickness: 0.5}\nfill: {material: bcb, top: flush}\n"
     'layers:\n  "1/0": {name: Etch, zmin: 0, thickness: 1.0, material: air}\n', "2 films have role: core (Q, Q2)"),
    (_WAFER + 'layers:\n  "1/0": {name: WG, role: core, zmin: 0, thickness: 0.22, material: silicon}\n'
     '  "2/0": {name: SiN, role: core, zmin: 0, thickness: 0.3, material: silicon_nitride}\n',
     "2 materials (silicon, silicon_nitride)"),
    (_WAFER + 'layers:\n  "1/0": {name: Ridge, role: core, zmin: 0.2, thickness: 0.2, material: lithium_niobate}\n',
     "the core starts at z = 0.2 um"),
], ids=["two core films", "core of two materials", "core over a gap"])
def test_check_stack_names_a_core_it_cannot_build(tmp_path, text, finding):
    # Mutants that must fail it: each of the three core checks in check_stack removed in turn.
    stack = tmp_path / "core.yaml"
    stack.write_text("name: t\n" + text)
    assert any(finding in found for found in check_stack(_gds(tmp_path / "core.gds", (1, 0)), stack))


def _modulator_gds(path: Path) -> Path:
    """The modulator cut of test_xsection_stack_process as a GDS: a rib on its 90 nm slab, N and P, a contact and
    M1. The cut from (0, -4) to (0, 4) puts the rib at s = 4."""

    return _strips(path, {(1, 0): [(-0.25, 0.25)], (3, 0): [(-3.0, 3.0)], (20, 0): [(-3.0, 0.0)],
                          (21, 0): [(0.0, 3.0)], (40, 0): [(-2.8, -2.2)], (41, 0): [(-3.2, -1.8)]})


def test_a_z_window_clips_with_no_voids(tmp_path):
    """A z window draws one band of the section: the frame is that band, with no BOX break and no cut-out of the
    top oxide, and the section has no gap inside the band. place() reads the same frame."""

    # Mutants that must fail it: the break or the cut-out left on under a z window; the window applied to z1 only.
    gds = _modulator_gds(tmp_path / "modulator.gds")
    cut = ((0.0, -4.0), (0.0, 4.0))
    with pytest.raises(ValueError, match="z0 < z1"):
        cross_section(gds, "gdsfactory_generic", cut, z=(1.5, -0.5))
    xs = cross_section(gds, "gdsfactory_generic", cut, z=(-0.5, 1.5))
    frame, room = section_frame(xs, width_mm=89, font_pt=7)
    assert (frame.z0, frame.z1, frame.keep) == (-0.5, 1.5, None)
    assert 'class="break"' not in xs.svg(width_mm=89, font_pt=7)
    s0, s1 = xs.window
    solid = unary_union([region for region in xs.regions.values() if not region.is_empty])
    lowest = min(solid.intersection(LineString([(s0 + (k + 0.5) * (s1 - s0) / 200, -50.0),
                                                (s0 + (k + 0.5) * (s1 - s0) / 200, 50.0)])).bounds[3]
                 for k in range(200))
    band = box(s0, -0.5, s1, min(1.5, lowest))
    assert band.difference(solid).area < 1e-6 * band.area
    pieces = list(getattr(solid, "geoms", [solid]))
    assert all(Polygon(ring).intersection(band).area <= 1e-6 for piece in pieces for ring in piece.interiors)
    place = section_place(xs, width_mm=89, font_pt=7)
    assert place(4.0, 1.5)[1] == pytest.approx(frame.top + room)
    assert place(4.0, -0.5)[1] == pytest.approx(frame.top + room + 2.0 * frame.zscale)
    with pytest.raises(ValueError, match="z window"):
        xs.png()


def _texts(svg: str) -> list[tuple[str, str]]:
    """The head and the inside of each text element."""

    return re.findall(r"<text\b([^>]*)>(.*?)</text>", svg, re.S)


def test_section_labels_set_scripts(tmp_path):
    """The material labels set their scripts as the table writes them: LiNbO3 and SiO2 with a subscript run. A
    label with no script keeps its anchor, and no markup is left in the printed text."""

    # Mutant that must fail it: the old raw label element (no tspan, and a literal SiO_2).
    texts = _texts(_lnoi_ridge(tmp_path).svg(width_mm=89, font_pt=7))
    printed = {plain(re.sub(r"<[^>]+>", "", inner)): (head, inner) for head, inner in texts}
    assert re.fullmatch(r'LiNbO<tspan dy="[^"]+" font-size="[^"]+">3</tspan>', printed["LiNbO3"][1])
    assert re.fullmatch(r'SiO<tspan dy="[^"]+" font-size="[^"]+">2</tspan>', printed["SiO2"][1])
    words = [(head, inner) for head, inner in texts if 'class="label"' in head and "<" not in inner]
    assert {inner for _, inner in words} >= {"BOX", "Si substrate"}         # BOX sits in the label column here
    assert all("text-anchor=" in head for head, _ in words)
    assert not [inner for _, inner in texts if "_" in re.sub(r"<[^>]+>", "", inner)]


# The stacks shipped with the open sections, and the layers that draw each one's core: the ridge and its slab, the
# deep etch that cuts the InP guide, the Si strip on the BaTiO3.
_NEW_STACKS = {"lnoi400": [(2, 0), (3, 0)], "ltoi300": [(2, 10), (3, 10)], "inp_generic": [(1, 0)],
               "bto_generic": [(1, 0)]}


@pytest.mark.parametrize("name", list(_NEW_STACKS))
def test_shipped_stacks_cite_every_number(name):
    """Every visible layer, film, substrate and fill names its source and whether it is the PDK's, the literature's
    or a model. A literature stack says so in its header; a PDK stack keeps the PDK's MIT notice."""

    # Mutants that must fail it: one source: deleted; the MIT notice stripped.
    text = (BUNDLED_STACKS / f"{name}.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    entries = [data["substrate"], data["fill"], *data["films"],
               *(entry for entry in data["layers"].values() if entry.get("visible") is not False)]
    for entry in entries:
        assert entry.get("source"), entry
        assert entry.get("provenance") in ("pdk", "literature", "model"), entry
    if name in ("inp_generic", "bto_generic"):
        assert any(line.startswith("# literature stack") for line in text.splitlines())
    else:
        assert "Copyright (c) 2023-2026 Luxtelligence" in text
        assert "Permission is hereby granted" in text


