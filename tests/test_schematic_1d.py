"""The 1D schematic: every part as its symbol, compact, with links that end on named ports."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

import optodraw
from optodraw.notebook_1d import render_notebook_1d
from optodraw.symbols.schematic import LABEL_HEIGHT, Link, build_schematic, link_curve

SVG = "{http://www.w3.org/2000/svg}"


def _chain() -> optodraw.Scene:
    """Laser -> MZM -> ring -> 1x4 demux -> four detectors, and a DAC that drives the MZM."""

    scene = optodraw.Scene(width=400, height=200, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0), label="Laser"))
    mzm = scene.add(optodraw.MZM(center=(-60, 0), label="MZM"))
    ring = scene.add(optodraw.MicroringResonator(center=(40, 0), label="ring"))
    demux = scene.add(optodraw.AWG(center=(120, 0), channel_count=4, label="demux"))
    detectors = [scene.add(optodraw.OnChipPhotodetector(center=(260, 30 - 20 * k), label=f"PD{k + 1}")) for k in range(4)]
    dac = scene.add(optodraw.DAC(center=(-60, 60), label="DAC"))
    scene.route((laser, "o1"), (mzm, "o1"), kind="waveguide")
    scene.route((mzm, "o3"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (demux, "i1"), kind="waveguide")
    for k, detector in enumerate(detectors):
        scene.route((demux, f"o{k + 1}"), (detector, "o1"), kind="waveguide")
    scene.route((dac, "out"), (mzm, "sig"), kind="electrical")
    return scene


def _transmitter() -> optodraw.Scene:
    """Four lasers -> a demux used as a mux -> MZM -> ring modulator -> balanced detector."""

    scene = optodraw.Scene(width=400, height=200, platform="on_chip")
    lasers = [scene.add(optodraw.OnChipLaser(center=(-200, 30 - 20 * k), label=f"L{k + 1}")) for k in range(4)]
    mux = scene.add(optodraw.AWG(center=(-100, 0), channel_count=4, angle=180, label="mux"))
    mzm = scene.add(optodraw.MZM(center=(0, 0), drive_style="gsg", label="MZM"))
    ring = scene.add(optodraw.PNMicroringModulator(center=(80, 0), label="MRM"))
    detector = scene.add(optodraw.OnChipBalancedPhotodetector(center=(160, 0), label="BPD"))
    dac_1 = scene.add(optodraw.DAC(center=(0, 60), label="DAC 1"))
    dac_2 = scene.add(optodraw.DAC(center=(80, 60), label="DAC 2"))
    for k, laser in enumerate(lasers):
        scene.route((laser, "o1"), (mux, f"o{k + 1}"), kind="waveguide")
    scene.route((mux, "i1"), (mzm, "o1"), kind="waveguide")
    scene.route((mzm, "o3"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (detector, "o1"), kind="waveguide")
    scene.route((dac_1, "out"), (mzm, "gnd1"), kind="electrical")
    scene.route((dac_2, "out"), (ring, "e2"), kind="electrical")
    return scene


def _by_label(schematic):
    return {item.label: item for item in schematic.items}


def _crossings(schematic) -> int:
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    chords = [(curve[0], curve[3]) for curve in (link_curve(schematic, link) for link in schematic.links)]
    return sum(
        side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0
        for index, (a, b) in enumerate(chords) for c, d in chords[index + 1:]
    )


def _overlaps(schematic) -> list[tuple[str, str]]:
    boxes = [(item.x, item.y - (LABEL_HEIGHT if item.label_above else 0.0), item.x + item.symbol.width,
              item.y + item.symbol.height + (0.0 if item.label_above else LABEL_HEIGHT), item.label)
             for item in schematic.items]
    return [(p[4], q[4]) for index, p in enumerate(boxes) for q in boxes[index + 1:]
            if p[0] < q[2] and q[0] < p[2] and p[1] < q[3] and q[1] < p[3]]


def _bench(*, scope_first: bool = False) -> optodraw.Scene:
    """A laser, a splitter, two modulators and a coherent receiver. An AWG drives both modulators, a scope reads the receiver."""

    scene = optodraw.Scene(width=500, height=260, platform="on_chip")
    laser = scene.add(optodraw.Laser(center=(-220, 0), label="Laser"))
    split = scene.add(optodraw.YBranch(center=(-170, 0), label="split"))
    m1 = scene.add(optodraw.MZM(center=(-80, 20), drive_style="gsg", label="MZM 1"))
    m2 = scene.add(optodraw.MZM(center=(40, 20), drive_style="gsg", label="MZM 2"))
    receiver = scene.add(optodraw.CoherentReceiver(center=(170, 0), label="ICR"))
    awg = scene.add(optodraw.WaveformGenerator(center=(-20, 110), label="AWG"))
    scope = scene.add(optodraw.Oscilloscope(center=(260, 60), label="Scope"))
    scene.add(optodraw.Beam((laser, "out"), (split, "o1")))
    scene.route((split, "o2"), (m1, "o1"), kind="waveguide")
    scene.route((m1, "o3"), (m2, "o1"), kind="waveguide")
    scene.route((m2, "o3"), (receiver, "signal"), kind="waveguide")
    scene.route((split, "o3"), (receiver, "lo"), kind="waveguide")
    scene.route((awg, "out1"), (m1, "sig"), kind="electrical")
    scene.route((awg, "out2"), (m2, "sig"), kind="electrical")
    if scope_first:                                  # a trigger: the scope is a source, in the laser's column
        scene.route((scope, "ch1"), (receiver, "i_p"), kind="electrical")
    else:
        scene.route((receiver, "i_p"), (scope, "ch1"), kind="electrical")
        scene.route((receiver, "q_p"), (scope, "ch2"), kind="electrical")
    return scene


def test_every_part_is_its_symbol_and_every_link_is_kept():
    scene = _chain()
    schematic = build_schematic(scene)
    assert len(schematic.items) == 9 and len(schematic.links) == 8 and schematic.unresolved == 0
    for item in schematic.items:
        assert set(item.symbol.ports) == set(item.component.ports())
    assert sum(link.electrical for link in schematic.links) == 1
    assert [item.key for item in schematic.items] == [f"node-{n}" for n in range(9)]


@pytest.mark.parametrize("make", [_chain, _transmitter])
def test_the_automatic_layout_is_compact_and_clean(make):
    schematic = build_schematic(make())
    assert _crossings(schematic) == 0
    assert _overlaps(schematic) == []
    for item in schematic.items:                              # everything is on the page
        assert item.x >= 0 and item.y >= 0
        assert item.x + item.symbol.width <= schematic.width
        assert item.y + item.symbol.height + LABEL_HEIGHT <= schematic.height + 0.01
    widths = sum(item.symbol.width for item in schematic.items)
    assert schematic.width <= 1.35 * widths                    # the page is symbols, not white space


def test_the_optical_path_runs_on_one_line():
    parts = _by_label(build_schematic(_chain()))
    path = ["Laser", "MZM", "ring", "demux"]
    for left, right in zip(path, path[1:]):
        assert parts[left].x + parts[left].symbol.width <= parts[right].x
    schematic = build_schematic(_chain())
    level = [link for link in schematic.links[:3]]             # laser-MZM, MZM-ring, ring-demux
    for link in level:
        start, _, _, end = link_curve(schematic, link)
        assert start[1] == pytest.approx(end[1], abs=0.5)      # a straight link


def test_a_fan_out_keeps_the_order_of_its_ports():
    parts = _by_label(build_schematic(_chain()))
    demux = parts["demux"]
    by_port = sorted(range(1, 5), key=lambda k: demux.port(f"o{k}")[1])
    by_detector = sorted(range(1, 5), key=lambda k: parts[f"PD{k}"].y)
    assert by_port == by_detector


def test_a_driver_sits_above_the_part_it_drives():
    parts = _by_label(build_schematic(_chain()))
    dac, mzm = parts["DAC"], parts["MZM"]
    assert dac.y + dac.symbol.height <= mzm.y                  # above, not in a column of its own
    assert dac.x < mzm.x + mzm.symbol.width and mzm.x < dac.x + dac.symbol.width + 20


def test_a_label_goes_above_a_part_with_its_connectors_on_the_bottom():
    scene = _bench()
    parts = _by_label(build_schematic(scene))
    assert parts["AWG"].label_above and parts["Scope"].label_above
    assert not parts["Laser"].label_above and not parts["MZM 1"].label_above
    texts = {text.text: float(text.get("y")) for text in ET.fromstring(render_notebook_1d(scene)).iter(f"{SVG}text")}
    assert texts["AWG"] < parts["AWG"].y                       # the text is over the body, clear of the cables
    assert texts["Laser"] > parts["Laser"].y + parts["Laser"].symbol.height


def test_an_instrument_that_drives_two_parts_sits_above_them():
    schematic = build_schematic(_bench())
    parts = _by_label(schematic)
    awg, m1, m2 = parts["AWG"], parts["MZM 1"], parts["MZM 2"]
    assert awg.y + awg.symbol.height <= min(m1.y, m2.y)
    assert m1.port("sig")[0] <= awg.port("out1")[0] < awg.port("out2")[0] <= m2.port("sig")[0]
    assert awg.x > parts["Laser"].x + parts["Laser"].symbol.width      # not in the column of the source
    assert _crossings(schematic) == 0 and _overlaps(schematic) == []
    assert min(item.y - (LABEL_HEIGHT if item.label_above else 0.0) for item in schematic.items) >= 4.99


def test_an_instrument_in_the_column_of_the_source_does_not_bend_the_optical_path():
    parts = _by_label(build_schematic(_bench(scope_first=True), arrangement="auto"))
    assert parts["Scope"].x < parts["split"].x                 # the scope is a source here
    assert parts["Laser"].port("out")[1] == pytest.approx(parts["split"].port("o1")[1], abs=0.01)
    assert parts["split"].port("o2")[1] == pytest.approx(parts["MZM 1"].port("o1")[1], abs=0.01)


def test_a_cable_reaches_a_contact_inside_a_part_from_the_side_of_its_driver():
    schematic = build_schematic(_bench())
    link = next(link for link in schematic.links if link.end_port == "sig" and schematic.items[link.end].label == "MZM 1")
    start, _, control, end = link_curve(schematic, link)
    assert start[1] < end[1]                                   # the AWG is above
    assert control[0] == pytest.approx(end[0]) and control[1] < end[1] - 5.0     # so the cable comes down onto the contact


def test_a_cable_rises_into_a_connector_on_the_bottom_of_an_instrument():
    parts = _by_label(build_schematic(_bench()))
    scope, receiver = parts["Scope"], parts["ICR"]
    outputs = (receiver.port("i_p")[1] + receiver.port("q_p")[1]) / 2.0
    assert scope.port("ch1")[1] <= outputs - 6.0               # the connectors are above the outputs they read
    assert scope.port("ch1")[1] <= receiver.port("i_p")[1]     # no cable dips under its connector
    assert scope.x > receiver.x + receiver.symbol.width


def test_a_part_at_the_end_of_a_side_port_sits_beside_that_port():
    """A Michelson arm: the mirror on the bottom port of the beamsplitter goes below it, not in a far column."""

    scene = optodraw.Scene(width=300, height=200)
    laser = scene.add(optodraw.Laser(center=(-100, 0), label="Laser"))
    splitter = scene.add(optodraw.BeamSplitter(center=(0, 0), label="BS"))
    moving = scene.add(optodraw.Mirror(center=(80, 0), label="moving"))
    fixed = scene.add(optodraw.Mirror(center=(0, -80), label="fixed"))
    scene.add(optodraw.Beam((laser, "out"), (splitter, "in")))
    scene.add(optodraw.Beam((splitter, "trans"), (moving, "io")))
    scene.add(optodraw.Beam((splitter, "refl"), (fixed, "io")))
    schematic = build_schematic(scene)
    parts = _by_label(schematic)
    bs = parts["BS"]
    assert parts["fixed"].y >= bs.y + bs.symbol.height                       # below the beamsplitter
    assert abs(parts["fixed"].x - bs.port("refl")[0]) < bs.symbol.width      # and under its port
    assert parts["moving"].x > bs.x + bs.symbol.width                        # the straight arm goes on to the right
    assert parts["moving"].port("io")[1] == pytest.approx(bs.port("trans")[1], abs=0.01)
    assert _crossings(schematic) == 0 and _overlaps(schematic) == []


def test_a_port_near_the_edge_of_a_small_symbol_is_not_an_electrode():
    """A wave plate draws a short beam with a turn arrow; its ``out`` is at the end of that beam, a little inside the art."""

    from bench_scenes import free_space_breadboard

    schematic = build_schematic(free_space_breadboard())
    parts = _by_label(schematic)
    assert parts["Ref PD"].port("in")[1] == pytest.approx(parts["λ/4"].port("out")[1], abs=0.01)
    assert parts["Signal PD"].port("in")[1] == pytest.approx(parts["f=75"].port("out")[1], abs=0.01)
    _bench_is_clean(schematic)


def test_a_free_space_beam_is_a_straight_line():
    """Light in free space does not bend: a beam between two parts is drawn straight, even when they are not level."""

    from bench_scenes import free_space_breadboard

    schematic = build_schematic(free_space_breadboard())
    beams = [link for link in schematic.links if link.kind == "free_space"]
    assert beams
    for link in beams:
        a, c1, c2, b = link_curve(schematic, link)
        for c in (c1, c2):                                     # both control points on the segment
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            assert abs(cross) < 1e-6


def test_a_cable_is_a_solid_line():
    """A cable is a thin solid grey line, not a dashed one. Dashes read as a broken link."""

    import re

    svg = render_notebook_1d(_bench())
    assert not re.search(r"stroke-dasharray=[\"'](?!none)", svg)   # the symbols reset dashes to none; nothing is dashed
    assert 'stroke="#595959"' in svg


def _through_a_part(schematic) -> list[tuple[str, str]]:
    """Free-space beams that pass through the box of a part they do not end on."""

    def hits(a, b, box) -> bool:                               # sample the segment; the boxes are small
        return any(box[0] < a[0] + (b[0] - a[0]) * t < box[2] and box[1] < a[1] + (b[1] - a[1]) * t < box[3]
                   for t in (k / 50.0 for k in range(1, 50)))

    found = []
    for link in schematic.links:
        if link.kind != "free_space":
            continue
        a, _, _, b = link_curve(schematic, link)
        for index, item in enumerate(schematic.items):
            box = (item.x + 1.0, item.y + 1.0, item.x + item.symbol.width - 1.0, item.y + item.symbol.height - 1.0)
            if index not in (link.start, link.end) and hits(a, b, box):
                found.append((schematic.items[link.start].label, item.label))
    return found


def test_a_beam_that_a_mirror_sends_back_is_drawn_once():
    """A Michelson interferometer: the beam to each mirror and back is one line, and no beam crosses a part."""

    from bench_scenes import ftir_setup

    schematic = build_schematic(ftir_setup())
    pairs = [frozenset({(link.start, link.start_port), (link.end, link.end_port)}) for link in schematic.links]
    assert len(pairs) == len(set(pairs))
    assert _through_a_part(schematic) == []


def test_the_straight_through_beam_keeps_its_line():
    """A part fed through a left or right port stays level with it. A part on a top or bottom port gives way."""

    from bench_scenes import ftir_setup

    parts = _by_label(build_schematic(ftir_setup()))
    assert parts["Moving Mirror"].port("io")[1] == pytest.approx(parts["Interferometer BS"].port("trans")[1], abs=0.01)
    assert parts["Interferometer BS"].port("in")[1] == pytest.approx(parts["IR Source"].port("out")[1], abs=0.01)


def _label_box(item):
    from optodraw.symbols.schematic import LABEL_SIZE

    x, baseline, anchor = item.label_at
    width = 0.5 * LABEL_SIZE * len(item.label)
    left = {"middle": x - width / 2.0, "start": x, "end": x - width}[anchor]
    return (left, baseline - 0.8 * LABEL_SIZE, left + width, baseline + 0.2 * LABEL_SIZE)


def _cubic_points(curve, steps=24):
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = curve
    return [((1 - t) ** 3 * ax + 3 * (1 - t) ** 2 * t * bx + 3 * (1 - t) * t * t * cx + t ** 3 * dx,
             (1 - t) ** 3 * ay + 3 * (1 - t) ** 2 * t * by + 3 * (1 - t) * t * t * cy + t ** 3 * dy)
            for t in (k / steps for k in range(steps + 1))]


@pytest.mark.parametrize("make", ["ftir_setup", "confocal_pl_setup", "free_space_breadboard", "raman_setup",
                                  "qwp_circular_lab", "bench"])
def test_a_label_never_sits_on_a_link_or_a_part(make):
    from optodraw import presets

    schematic = build_schematic(_bench() if make == "bench" else getattr(presets, make)())
    labelled = [item for item in schematic.items if item.label]
    boxes = [_label_box(item) for item in labelled]

    def inside(point, box):
        return box[0] < point[0] < box[2] and box[1] < point[1] < box[3]

    for item, box in zip(labelled, boxes):
        for link in schematic.links:
            assert not any(inside(point, box) for point in _cubic_points(link_curve(schematic, link))), item.label
        own = (item.x, item.y, item.x + item.symbol.width, item.y + item.symbol.height)
        for other in schematic.items:
            art = (other.x, other.y, other.x + other.symbol.width, other.y + other.symbol.height)
            holds = art[0] <= own[0] and art[1] <= own[1] and own[2] <= art[2] and own[3] <= art[3]
            if other is not item and not holds:              # a part inside another (a cryostat) is named on it
                assert not (box[0] < art[2] and art[0] < box[2] and box[1] < art[3] and art[1] < box[3]), (item.label, other.label)
    for index, box in enumerate(boxes):
        for other in boxes[index + 1:]:
            assert not (box[0] < other[2] and other[0] < box[2] and box[1] < other[3] and other[1] < box[3])
    assert all(box[0] >= 0 and box[1] >= 0 and box[2] <= schematic.width and box[3] <= schematic.height for box in boxes)


def _bench_is_clean(schematic) -> None:
    """Every beam runs straight across or straight up and down; no part sits on another; no beam crosses a part."""

    for link in schematic.links:
        a, _, _, b = link_curve(schematic, link)
        assert abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01, (schematic.items[link.start].label, link.start_port)
    boxes = [(item.x, item.y, item.x + item.symbol.width, item.y + item.symbol.height, item.label) for item in schematic.items]
    for index, p in enumerate(boxes):
        for q in boxes[index + 1:]:
            assert not (p[0] < q[2] and q[0] < p[2] and p[1] < q[3] and q[1] < p[3]), (p[4], q[4])
    assert _through_a_part(schematic) == []


def _level(parts, a, a_port, b, b_port) -> bool:
    return abs(parts[a].port(a_port)[1] - parts[b].port(b_port)[1]) < 0.01


def _plumb(parts, a, a_port, b, b_port) -> bool:
    return abs(parts[a].port(a_port)[0] - parts[b].port(b_port)[0]) < 0.01


def test_a_bench_folds_the_reflected_arm_with_a_turned_mirror():
    """M1 goes above the PBS, turned 45 degrees with its face to the PBS; after the PBS every beam runs straight."""

    from bench_scenes import free_space_breadboard

    schematic = build_schematic(free_space_breadboard())
    parts = _by_label(schematic)
    assert _plumb(parts, "PBS", "refl", "M1", "io") and parts["M1"].y + parts["M1"].symbol.height < parts["PBS"].y
    assert parts["M1"].symbol.rotation == 135                # its face looks down to the PBS and right along the arm
    assert _level(parts, "M1", "io", "λ/4", "in") and _level(parts, "λ/4", "out", "Ref PD", "in")
    assert parts["Ref PD"].x < parts["Signal PD"].x + parts["Signal PD"].symbol.width    # the arm is not stretched
    assert _level(parts, "PBS", "trans", "Iris", "in") and _level(parts, "Iris", "out", "f=75", "in")
    assert _level(parts, "f=75", "out", "Signal PD", "in") and _level(parts, "633 nm", "out", "PBS", "in")
    _bench_is_clean(schematic)


def test_an_ftir_bench_is_drawn_as_it_is_built():
    """Each mirror faces the beam with its reflecting side; the sample sits between the beamsplitter and the detector."""

    from bench_scenes import ftir_setup

    schematic = build_schematic(ftir_setup())
    parts = _by_label(schematic)
    bs, fixed, moving = parts["Interferometer BS"], parts["Fixed Mirror"], parts["Moving Mirror"]
    assert _plumb(parts, "Interferometer BS", "refl", "Fixed Mirror", "io") and fixed.y > bs.y + bs.symbol.height
    assert fixed.symbol.rotation == 270                      # its face looks up, to the beamsplitter
    assert moving.symbol.rotation == 0 and moving.x > bs.x + bs.symbol.width
    assert _level(parts, "Interferometer BS", "trans", "Moving Mirror", "io")
    sample, detector = parts["Sample"], parts["Detector"]
    assert _plumb(parts, "Interferometer BS", "tap", "Sample", "in") and _plumb(parts, "Sample", "out", "Detector", "in")
    assert detector.y + detector.symbol.height < sample.y and sample.y + sample.symbol.height < bs.y
    assert sample.symbol.rotation == 90 and detector.symbol.rotation == 90   # both face the light from below
    _bench_is_clean(schematic)


def test_a_confocal_bench_is_drawn_as_it_is_built():
    from bench_scenes import confocal_pl_setup

    schematic = build_schematic(confocal_pl_setup())
    parts = _by_label(schematic)
    assert _plumb(parts, "Dichroic", "refl", "100x LWD Obj", "in") and parts["100x LWD Obj"].y > parts["Dichroic"].y
    assert _plumb(parts, "100x LWD Obj", "out", "Sample", "in") and parts["Sample"].y > parts["100x LWD Obj"].y
    assert _plumb(parts, "Dichroic", "tap", "LP Filter", "in") and parts["LP Filter"].y < parts["Dichroic"].y
    assert _plumb(parts, "Detect BS", "trans", "Spectrometer", "in") and parts["Spectrometer"].y < parts["Detect BS"].y
    assert _level(parts, "Detect BS", "refl", "CCD", "in") and parts["CCD"].x > parts["Detect BS"].x
    _bench_is_clean(schematic)


def test_a_splitter_shows_only_the_paths_that_light_takes():
    """The confocal dichroic: the pump comes in and goes down, the emission comes up and goes on up; nothing goes right."""

    from bench_scenes import confocal_pl_setup

    tikz_export = pytest.importorskip("optodraw.symbols.tikz_export")      # task 6 brings the 1D TikZ export
    _cm, render_tikz_1d = tikz_export._cm, tikz_export.render_tikz_1d

    from optodraw.symbols.schematic import hub_paths

    scene = confocal_pl_setup()
    schematic = build_schematic(scene)
    dichroic = _by_label(schematic)["Dichroic"]
    hub = (dichroic.x + dichroic.symbol.hub[0], dichroic.y + dichroic.symbol.hub[1])
    used = {name for link in schematic.links for index, name in ((link.start, link.start_port), (link.end, link.end_port))
            if schematic.items[index] is dichroic}
    assert used == {"in", "refl", "tap"}                                   # nothing goes right
    for port in used:                                                      # every beam meets the plate at its centre
        x, y, _ = dichroic.port(port)
        assert (round(x, 6), round(y, 6)) == (round(hub[0], 6), round(hub[1], 6)), port
    assert not any(a == b for a, b in hub_paths(schematic))
    render_notebook_1d(scene), render_tikz_1d(scene, include_library=False)  # both views still draw
    assert _cm is not None


def test_a_part_that_light_enters_from_the_right_is_mirrored():
    parts = _by_label(build_schematic(_transmitter()))
    assert parts["mux"].symbol.flipped
    assert not parts["MZM"].symbol.flipped
    assert parts["mux"].port("i1")[2] == "right" and parts["mux"].port("o1")[2] == "left"
    assert parts["L1"].x < parts["mux"].x < parts["MZM"].x


def test_a_saved_position_moves_only_that_part():
    scene = _chain()
    free = _by_label(build_schematic(scene))
    saved = {"node-1": [300, 5], "node-2": "x", "nowhere": [1, 2], "node-3": [float("nan"), 1], "node-4": [1, 2, 3]}
    placed = _by_label(build_schematic(scene, saved))
    assert (placed["MZM"].x, placed["MZM"].y) == (300.0, 5.0)
    for label in ("ring", "demux", "PD1", "Laser"):            # bad entries are ignored
        assert (placed[label].x, placed[label].y) == (free[label].x, free[label].y)
    scene.metadata["one_d_layout"] = {"node-2": [10, 200]}
    assert (_by_label(build_schematic(scene))["ring"].x, _by_label(build_schematic(scene))["ring"].y) == (10.0, 200.0)


def test_a_loop_and_a_missing_port_do_not_break_the_layout():
    scene = optodraw.Scene(platform="on_chip")
    a = scene.add(optodraw.MZM(center=(0, 0), label="A"))
    b = scene.add(optodraw.MicroringResonator(center=(120, 0), label="B"))
    scene.route((a, "o3"), (b, "o1"), kind="waveguide")
    scene.route((b, "o2"), (a, "o1"), kind="waveguide")
    schematic = build_schematic(scene)
    assert all(math.isfinite(value) for item in schematic.items for value in (item.x, item.y))
    assert _overlaps(schematic) == []
    curve = link_curve(schematic, Link(0, "o9", 1, "nope", "waveguide"))    # a route to a port the symbol lacks
    assert all(math.isfinite(value) for point in curve for value in point)


def test_the_svg_is_well_formed_and_leaves_the_2d_layout_alone():
    scene = _chain()
    mzm = next(node for node in scene.walk() if getattr(node, "label", "") == "MZM")
    mzm.label = "A<B & C"
    before = [(node.world_position.x, node.world_position.y) for node in scene.walk()]
    svg = render_notebook_1d(scene)
    root = ET.fromstring(svg)
    assert root.get("aria-label") == "1D schematic"
    assert svg.count('<g transform="translate(') >= 9          # one group per part
    assert "A&lt;B &amp; C" in svg
    assert before == [(node.world_position.x, node.world_position.y) for node in scene.walk()]
    schematic = build_schematic(scene)
    start = link_curve(schematic, schematic.links[0])[0]
    assert f'<path d="M{start[0]:.2f} {start[1]:.2f}' in svg      # the link starts on the port


def test_an_empty_scene_says_so():
    svg = render_notebook_1d(optodraw.Scene())
    ET.fromstring(svg)
    assert "No components" in svg


def test_the_notebook_viewer_has_the_1d_tab():
    document = _chain().preview(show_3d=False).document()
    assert 'id="b1"' in document and 'aria-label="1D schematic"' in document


def test_a_beam_that_names_parts_without_ports_draws_in_1d():
    """Beam(laser, lens, pd) gave each stop an empty port name; a one-port symbol then raised KeyError: ''."""

    import optodraw
    from optodraw.notebook_1d import render_notebook_1d
    from optodraw.symbols.schematic import build_schematic

    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    lens = scene.add(optodraw.Lens(center=(0, 0)))
    pd = scene.add(optodraw.Photodiode(center=(60, 0)))
    scene.add(optodraw.Beam(laser, lens, pd))
    assert "<svg" in render_notebook_1d(scene)
    links = build_schematic(scene).links
    assert len(links) == 2


def test_a_beam_through_a_four_port_splitter_without_port_names_draws_in_1d():
    """A splitter has no out port; a beam that names it bare picks the port that faces the next part."""

    from optodraw.symbols.schematic import build_schematic

    scene = optodraw.Scene(width=200, height=120, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    bs = scene.add(optodraw.BeamSplitter(center=(0, 0), angle=-45))
    up = scene.add(optodraw.Mirror(center=(0, 40), angle=90))
    right = scene.add(optodraw.Mirror(center=(40, 0)))
    scene.add(optodraw.Beam(laser, bs, right))
    scene.add(optodraw.Beam(bs, up))
    assert "<svg" in render_notebook_1d(scene)
    names = {(link.start_port, link.end_port) for link in build_schematic(scene).links}
    assert all(a and b for a, b in names), names


def test_an_annotation_arrow_with_no_link_stays_out_of_the_schematic():
    """A 2D arrow beside a waveguide marks the light; the 1D view places parts by their links, so a free arrow has no place."""

    scene = optodraw.Scene(platform="on_chip")
    a = scene.add(optodraw.MMI2x2(center=(0, 0)))
    b = scene.add(optodraw.MMI2x2(center=(60, 0)))
    scene.route((a, "o3"), (b, "o1"), kind="waveguide")
    scene.add(optodraw.SignalArrow((-12, 0), (12, 0), center=(-40, 10), label="Pump"))
    kinds = [item.component.component_type for item in build_schematic(scene).items]
    assert kinds == ["MMI2x2", "MMI2x2"]


def test_an_annotation_arrow_on_a_link_stays_in_the_schematic():
    scene = optodraw.Scene(platform="on_chip")
    arrow = scene.add(optodraw.SignalArrow((-12, 0), (12, 0), center=(-40, 0), label="RF in"))
    pad = scene.add(optodraw.ElectricalPad(center=(0, 0)))
    scene.route((arrow, "out"), (pad, "e1"), kind="electrical")
    kinds = sorted(item.component.component_type for item in build_schematic(scene).items)
    assert kinds == ["ElectricalPad", "SignalArrow"]


def test_a_traced_bundle_links_the_parts_it_passes_in_order():
    """Traced rays carry plain points, not parts: the 1D view links the parts whose drawing each ray crosses."""

    from optodraw.core.raytrace import trace_bundle

    scene = optodraw.Scene(platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-78, 0), label="laser"))
    scene.add(optodraw.Lens(center=(-58, 0), focal_length=45 / 4, aperture=6, label="short"))
    scene.add(optodraw.Lens(center=(53, 0), focal_length=100, aperture=24, label="long"))
    for ray in trace_bundle(scene, (laser, "out"), rays=5, width=2.0, exit_length=16):
        scene.add(ray.as_beam(wavelength=488))
    schematic = build_schematic(scene)
    labels = [item.label for item in schematic.items]
    pairs = sorted((labels[link.start], labels[link.end]) for link in schematic.links)
    assert pairs == [("laser", "short"), ("short", "long")]


def test_a_label_on_a_tight_vertical_run_goes_beside_its_part_not_across_the_beam():
    """Parts stacked close on a vertical beam leave no room under or over each one: the name goes beside it."""

    from optodraw.symbols.schematic import _cubic_points, _label_box

    scene = optodraw.Scene(platform="free_space")
    laser = scene.add(optodraw.Laser(center=(0, -60), angle=90, label="Laser"))
    lens = scene.add(optodraw.Lens(center=(0, -28), angle=90, focal_length=2, label="Lenslet array 1"))
    pinhole = scene.add(optodraw.Pinhole(center=(0, -34), angle=90, label="Pinhole array"))
    plate = scene.add(optodraw.WedgePlate(center=(0, -40), angle=90, label="Compensator plate"))
    detector = scene.add(optodraw.Photodiode(center=(0, 0), angle=-90, label="Detector"))
    scene.add(optodraw.Beam.through(laser, plate, pinhole, lens, detector))
    scene.set_view_layout({"1d": {"spacing": 1.0}})             # the 1D view then keeps the scene's tight spacing
    schematic = build_schematic(scene)
    points = [point for link in schematic.links for point in _cubic_points(link_curve(schematic, link))]
    for item in schematic.items:
        x0, y0, x1, y1 = _label_box(*item.label_at, item.label)
        crossed = [p for p in points if x0 < p[0] < x1 and y0 < p[1] < y1]
        assert not crossed, item.label


def test_an_interferometer_closes_its_loop_with_straight_beams_in_1d():
    """Both arms of a Mach-Zehnder meet at the second splitter. The 1D bench walk placed each part one gap
    along its beam and never closed the loop, so the beam from the second mirror ran diagonally."""

    import math

    from optodraw import Beam, BeamSplitter, Laser, Mirror, Photodiode, Sample, Scene
    from optodraw.layout import aim, face
    from optodraw.symbols.schematic import build_schematic

    s = Scene(title="MZI", width=89, height=70, platform="free_space")
    laser = s.add(Laser(center=(-36, -14), wavelength=633, label="633 nm"))
    bs1 = s.add(BeamSplitter(center=(-14, -14), label="BS1"))
    m1 = s.add(Mirror(center=(-14, 14), label="M1"))
    m2 = s.add(Mirror(center=(18, -14), label="M2"))
    sample = s.add(Sample(center=(2, -14), label="Sample"))
    bs2 = s.add(BeamSplitter(center=(18, 14), label="BS2"))
    pd1 = s.add(Photodiode(center=(38, 14), label="PD1"))
    pd2 = s.add(Photodiode(center=(18, 32), label="PD2"))
    aim(bs1, laser, m1)
    aim(m1, bs1, bs2)
    aim(m2, bs1, bs2)
    aim(bs2, m2, pd1)
    face(pd1, bs2)
    face(pd2, bs2)
    s.add(Beam.through(laser, bs1, sample, m2, bs2, pd1))
    s.add(Beam.through((bs1, "refl"), m1, bs2, pd2))
    schematic = build_schematic(s)
    bent = []
    for link in schematic.links:
        a = schematic.items[link.start].port(link.start_port)
        b = schematic.items[link.end].port(link.end_port)
        if min(abs(a[0] - b[0]), abs(a[1] - b[1])) > 0.5:
            angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            bent.append(f"{schematic.items[link.start].label}->{schematic.items[link.end].label} at {angle:.0f} deg")
    assert not bent, bent


def _mzi_bench():
    from optodraw import Beam, BeamSplitter, Laser, Mirror, Photodiode, Sample, Scene
    from optodraw.layout import aim, face

    s = Scene(title="MZI", width=89, height=70, platform="free_space")
    laser = s.add(Laser(center=(-35, -22), wavelength=633, label="HeNe laser"))
    bs1 = s.add(BeamSplitter(center=(-14, -22), label="BS1", label_side="bottom"))
    sample = s.add(Sample(center=(2, -22), label="Sample"))
    m2 = s.add(Mirror(center=(18, -22), label="M2", label_side="bottom"))
    m1 = s.add(Mirror(center=(-14, 6), label="M1"))
    bs2 = s.add(BeamSplitter(center=(18, 6), label="BS2", label_side="top-left"))
    pd1 = s.add(Photodiode(center=(38, 6), label="PD1"))
    pd2 = s.add(Photodiode(center=(18, 24), label="PD2", label_side="right"))
    aim(bs1, laser, m1)
    aim(m1, bs1, bs2)
    aim(m2, bs1, bs2)
    aim(bs2, m2, pd1)
    face(pd1, bs2)
    face(pd2, bs2)
    s.add(Beam.through(laser, bs1, sample, m2, bs2, pd1))
    s.add(Beam.through((bs1, "refl"), m1, bs2, pd2))
    return s


def test_no_1d_label_sits_on_a_beam():
    """The BS2 label touched the beam below it: spots were tested against sampled points with a 0.5 margin."""

    from optodraw import check_figure

    assert check_figure(_mzi_bench(), view="1d") == []


def test_the_bell_bench_of_the_docs_draws_clean_in_1d():
    """Two mirrors fold the pump back under itself; the crystal sends two arms out 13 degrees either side of the
    pump's dump; fibres take the four outputs to a detector above the bench. Rounded to the axes, the fold ran back
    over the pump and both arms ran on one line through each other's parts (35 findings). Once apart, the detector
    hung between the arms, and a fibre whose lead ended in a corner of its own label ran straight over the bench."""

    import runpy
    from pathlib import Path

    from optodraw import check_figure

    bell = Path(__file__).resolve().parents[1] / "docs" / "examples" / "examples" / "02-bell.py"
    assert check_figure(runpy.run_path(str(bell))["scene"], view="1d") == []


def test_a_plate_splitter_meets_its_beams_at_its_centre_in_1d():
    """The reflected beam left BS1 from the end of the plate, so the light seemed to split before it."""

    from optodraw.symbols.schematic import build_schematic

    schematic = build_schematic(_mzi_bench())
    for item in schematic.items:
        if item.label in ("BS1", "BS2"):
            hub = (item.x + item.symbol.hub[0], item.y + item.symbol.hub[1])
            used = {name for link in schematic.links for index, name in ((link.start, link.start_port),
                                                                            (link.end, link.end_port))
                    if schematic.items[index] is item}
            for name in used:
                x, y, _ = item.port(name)
                assert (round(x, 6), round(y, 6)) == (round(hub[0], 6), round(hub[1], 6)), (item.label, name)


def test_no_1d_label_sits_on_a_wire_of_a_chip():
    """The MZI switch's pad labels sat on their wires in 1D: spots were tested against sampled points."""

    from optodraw import ElectricalPad, MMI1x2, MMI2x2, PhaseShifter, Scene, VerticalGratingCoupler, check_figure

    chip = Scene(title="switch", width=400, height=200, platform="on_chip")
    split = chip.add(MMI1x2(center=(-70, 0), label="1x2 MMI"))
    join = chip.add(MMI2x2(center=(70, 0), label="2x2 MMI"))
    top = chip.add(PhaseShifter(center=(0, 25), label="PS top"))
    bottom = chip.add(PhaseShifter(center=(0, -25), angle=180, label="PS bottom"))
    gc_in = chip.add(VerticalGratingCoupler(center=(-140, 0), angle=180, label="In"))
    gc_1 = chip.add(VerticalGratingCoupler(center=(140, 20), label="Out 1"))
    gc_2 = chip.add(VerticalGratingCoupler(center=(140, -20), label="Out 2"))
    pads = {name: chip.add(ElectricalPad(center=(x, y), angle=90 if y > 0 else -90, label=name))
            for name, (x, y) in {"T1": (-22, 70), "T2": (22, 70), "B1": (-22, -70), "B2": (22, -70)}.items()}
    for a, b in [((gc_in, "o1"), (split, "o1")), ((split, "o3"), (top, "o1")), ((split, "o2"), (bottom, "o2")),
                 ((top, "o2"), (join, "o2")), ((bottom, "o1"), (join, "o1")),
                 ((join, "o4"), (gc_1, "o1")), ((join, "o3"), (gc_2, "o1"))]:
        chip.route(a, b, kind="waveguide", path_type="smooth")
    for a, b in [((top, "h1"), (pads["T1"], "e1")), ((top, "h2"), (pads["T2"], "e1")),
                 ((bottom, "h2"), (pads["B1"], "e1")), ((bottom, "h1"), (pads["B2"], "e1"))]:
        chip.route(a, b, kind="electrical", path_type="L", width=1.4)
    assert check_figure(chip, view="1d") == []


def test_a_part_on_a_ring_s_west_port_sits_west_of_the_ring():
    """The drop leaves at o3, which faces west: its detector goes left of the ring, so the wire does not loop
    across it (and the add terminator on o4 goes right)."""

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    import tutorial_scenes

    schematic = build_schematic(tutorial_scenes.bogaerts_add_drop())
    by_label = {item.label: item for item in schematic.items}
    ring, drop, add = by_label["ring"], by_label["drop PD"], by_label["add"]
    west = ring.symbol.ports["o3"]
    assert west.side == "left"
    assert drop.x + drop.symbol.width <= ring.x + west.x
    assert add.x >= ring.x + ring.symbol.ports["o4"].x


def _loop_back_receiver():
    """A coherent-receiver core: the signal enters from the right and turns back to couplers on the left."""

    from optodraw import DirectionalCoupler, MMI1x2, OnChipBalancedPhotodetector, PhaseShifter, Scene, VerticalGratingCoupler

    chip = Scene(title="loop", width=700, height=360, platform="on_chip")
    lo = chip.add(VerticalGratingCoupler(center=(-300, 0), angle=180, label="LO"))
    split = chip.add(DirectionalCoupler(center=(-200, 0), label="LO split"))
    top = chip.add(DirectionalCoupler(center=(-60, 110), label="DC I"))
    bottom = chip.add(DirectionalCoupler(center=(-60, -110), label="DC Q"))
    pd_top = chip.add(OnChipBalancedPhotodetector(center=(60, 110), label="BPD I"))
    pd_bottom = chip.add(OnChipBalancedPhotodetector(center=(60, -110), label="BPD Q"))
    ps_top = chip.add(PhaseShifter(center=(120, 40), angle=180, label="PS I"))
    ps_bottom = chip.add(PhaseShifter(center=(120, -40), angle=180, label="PS Q"))
    mmi = chip.add(MMI1x2(center=(240, 0), angle=180, label="MMI"))
    sig = chip.add(VerticalGratingCoupler(center=(320, 0), angle=0, label="Signal"))
    for a, b in [((lo, "o1"), (split, "o1")), ((split, "o3"), (top, "o1")), ((split, "o4"), (bottom, "o1")),
                 ((sig, "o1"), (mmi, "o1")), ((mmi, "o2"), (ps_top, "o1")), ((mmi, "o3"), (ps_bottom, "o1")),
                 ((ps_top, "o2"), (top, "o2")), ((ps_bottom, "o2"), (bottom, "o2")), ((top, "o3"), (pd_top, "o1")),
                 ((top, "o4"), (pd_top, "o2")), ((bottom, "o3"), (pd_bottom, "o1")), ((bottom, "o4"), (pd_bottom, "o2"))]:
        chip.route(a, b, kind="waveguide", path_type="smooth")
    return chip


def test_a_chip_whose_automatic_1d_crosses_keeps_its_plan_arrangement():
    """The scope reads the receiver: drawn where the plan puts it, its cable crosses no optical path."""

    from optodraw.symbols.schematic import link_crossings

    scene = _bench(scope_first=True)
    assert link_crossings(build_schematic(scene, arrangement="auto")) > 0
    chosen = build_schematic(scene)
    assert link_crossings(chosen) == 0
    parts = _by_label(chosen)
    assert parts["Scope"].x > parts["ICR"].x


def test_the_plan_arrangement_keeps_the_2d_order_and_turns():
    scene = _loop_back_receiver()
    parts = _by_label(build_schematic(scene, arrangement="plan"))
    assert parts["LO"].x < parts["DC I"].x < parts["PS I"].x < parts["MMI"].x < parts["Signal"].x
    assert parts["DC I"].y < parts["PS I"].y < parts["PS Q"].y < parts["DC Q"].y
    assert parts["MMI"].port("o1")[0] > parts["MMI"].port("o2")[0]       # turned as in 2D: its input faces the signal


def test_a_simple_ring_chip_follows_its_2d_with_every_route_straight():
    """The add-drop ring as in 2D: the bus in, ring and through on one line, the drop detector and the add
    terminator on the drop bus. Each part lines up with the port that feeds it, so every route is straight."""

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    import tutorial_scenes

    schematic = build_schematic(tutorial_scenes.bogaerts_add_drop())
    plan = build_schematic(tutorial_scenes.bogaerts_add_drop(), arrangement="plan")
    assert [(i.x, i.y) for i in schematic.items] == [(i.x, i.y) for i in plan.items]
    assert all(len(route) == 2 for route in schematic.routes.values())


def test_the_plan_arrangement_keeps_a_part_s_pads_beside_it():
    """Pads that serve one part stay with it in 1D, as in its 2D plan, instead of taking columns of their own."""

    from optodraw import ElectricalPad, MicroringWeightBank, Scene

    chip = Scene(title="pads", width=500, height=200, platform="on_chip")
    bank = chip.add(MicroringWeightBank(center=(0, 0), ring_count=4, with_heaters=True, label="Bank"))
    for j in range(1, 9):
        contact = bank.world_ports()[f"e{j}"].center
        pad = chip.add(ElectricalPad(center=(contact.x, contact.y - 11.0), width=10, height=10, angle=-90, label=""))
        chip.route((bank, f"e{j}"), (pad, "e1"), kind="electrical", path_type="L")
    schematic = build_schematic(chip, arrangement="plan")
    items = {item.label or f"pad{k}": item for k, item in enumerate(schematic.items)}
    bank_item = items["Bank"]
    pads = [item for item in schematic.items if item.label == ""]
    assert len(pads) == 8
    pad_width = 2.0 * pads[0].symbol.width          # eight pads overhang a 4-ring bank a little
    assert all(bank_item.x - pad_width <= p.x and p.x + p.symbol.width <= bank_item.x + bank_item.symbol.width + pad_width
               for p in pads)


def _two_rows():
    """A weight bank and its detector on one row; a laser and its modulator on the row below, further right."""

    from optodraw import MZM, ElectricalPad, MicroringWeightBank, OnChipBalancedPhotodetector, OnChipLaser, Scene

    chip = Scene(title="rows", width=600, height=300, platform="on_chip")
    bank = chip.add(MicroringWeightBank(center=(0, 60), ring_count=4, label="Bank"))
    bpd = chip.add(OnChipBalancedPhotodetector(center=(180, 60), label="BPD"))
    laser = chip.add(OnChipLaser(center=(90, 0), label="LD"))
    mzm = chip.add(MZM(center=(300, 0), label="MZM"))
    gnd = mzm.world_ports()["gnd"].center
    pad = chip.add(ElectricalPad(center=(gnd.x, gnd.y + 12), width=10, height=10, angle=90, label=""))
    chip.route((bank, "o2"), (bpd, "o1"), kind="waveguide")
    chip.route((bank, "drop"), (bpd, "o2"), kind="waveguide")
    chip.route((laser, "o1"), (mzm, "o1"), kind="waveguide")
    chip.route((bpd, "out"), (mzm, "sig"), kind="electrical")
    chip.route((mzm, "gnd"), (pad, "e1"), kind="electrical")
    return chip


def test_the_plan_view_packs_a_part_under_another_row_when_nothing_links_them():
    parts = _by_label(build_schematic(_two_rows(), arrangement="plan"))
    bank, bpd, laser, mzm = parts["Bank"], parts["BPD"], parts["LD"], parts["MZM"]
    assert bank.x + bank.symbol.width <= bpd.x and laser.x + laser.symbol.width <= mzm.x
    assert laser.x < bank.x + bank.symbol.width                  # under the bank, not in a column of its own
    assert mzm.x >= bpd.x + bpd.symbol.width                     # a linked pair keeps its order


def test_a_pad_in_the_plan_view_faces_the_part_it_serves():
    schematic = build_schematic(_two_rows(), arrangement="plan")
    mzm = next(item for item in schematic.items if item.label == "MZM")
    pad = next(item for item in schematic.items if item.component.component_type == "ElectricalPad")
    side = pad.port("e1")[2]
    assert side == ("top" if pad.y > mzm.y else "bottom")


def _bank_with_pads(angle: float = 0.0):
    from optodraw import ElectricalPad, MicroringWeightBank, Scene

    chip = Scene(title="pads", width=500, height=200, platform="on_chip")
    bank = chip.add(MicroringWeightBank(center=(0, 0), ring_count=4, with_heaters=True, label="Bank"))
    for j in range(1, 9):
        contact = bank.world_ports()[f"e{j}"].center
        pad = chip.add(ElectricalPad(center=(contact.x, contact.y - 11.0), width=10, height=10, angle=angle, label=""))
        chip.route((bank, f"e{j}"), (pad, "e1"), kind="electrical", path_type="L")
    return chip


@pytest.mark.parametrize("arrangement", ["auto", "plan"])
def test_a_pad_turns_to_face_the_contact_it_serves(arrangement):
    schematic = build_schematic(_bank_with_pads(), arrangement=arrangement)
    bank = next(item for item in schematic.items if item.label == "Bank")
    for pad in (item for item in schematic.items if item.component.component_type == "ElectricalPad"):
        assert pad.port("e1")[2] == ("top" if pad.y > bank.y else "bottom")


def test_a_pad_beside_its_part_keeps_the_side_its_2d_port_faces():
    """A pad whose 2D port already looks at its contact keeps that side in the plan view: here the pads beside
    a filter face the heater (east) or the wire under them (down), so no wire loops round a pad."""

    from optodraw.literature import mak2015_ring_filter

    scene = mak2015_ring_filter.build()
    schematic = build_schematic(scene, arrangement="plan")
    sides = {0: "right", 90: "top", 180: "left", 270: "bottom"}
    for item in schematic.items:
        if item.component.component_type == "ElectricalPad":
            facing = round(item.component.world_ports()["e1"].orientation_deg) % 360
            assert item.port("e1")[2] == sides[facing]


def test_a_pad_wired_straight_to_a_contact_inside_its_part_lines_up_with_it():
    """The heater contacts sit inside the filter's symbol. A pad wired straight to one in 2D is level with it in
    1D, and the pad beside it in the same 2D row stays in that row."""

    from optodraw.literature import mak2015_ring_filter

    schematic = build_schematic(mak2015_ring_filter.build(), arrangement="plan")
    rings = next(item for item in schematic.items if item.component.component_type == "CoupledRingFilter")
    pads = {id(item.component): item for item in schematic.items if item.component.component_type == "ElectricalPad"}
    centre = {key: item.y + item.symbol.height / 2.0 for key, item in pads.items()}
    straight = 0
    for link in schematic.links:
        ends = [(schematic.items[link.start], link.start_port), (schematic.items[link.end], link.end_port)]
        if ends[1][0] is rings:
            ends.reverse()
        (a, a_port), (b, b_port) = ends
        if a is not rings or id(b.component) not in pads:
            continue
        contact = a.component.world_ports()[a_port].center
        pad_port = b.component.world_ports()[b_port].center
        if abs(float(contact.y) - float(pad_port.y)) < 0.5:                  # wired straight in 2D
            straight += 1
            assert abs(a.port(a_port)[1] - b.port(b_port)[1]) < 0.5
            twin = next(key for key, item in pads.items() if item is not b
                        and abs(float(item.component.world_position.y) - float(b.component.world_position.y)) < 0.5
                        and (item.component.world_position.x < 0) == (b.component.world_position.x < 0))
            assert abs(centre[twin] - centre[id(b.component)]) < 0.5
    assert straight == 5


def test_a_row_of_pads_routes_quickly():
    import time

    started = time.perf_counter()
    schematic = build_schematic(_bank_with_pads(), arrangement="auto")
    assert time.perf_counter() - started < 1.0
    assert len(schematic.routes) == 8


def test_a_chip_1d_puts_each_mesh_coupler_between_the_rows_it_joins():
    """As in 2D: a coupler that mixes two rows sits midway between them, not on one row."""

    from optodraw import presets

    schematic = build_schematic(presets.mzm_mesh_chip())
    centre = {i: item.y + item.symbol.height / 2.0 for i, item in enumerate(schematic.items)}
    for index, item in enumerate(schematic.items):
        if item.component.component_type != "DirectionalCoupler":
            continue
        fed = [link.start for link in schematic.links if link.end == index]              # the two rows it mixes
        rows = sorted({round(centre[i], 3) for i in fed})
        assert len(rows) == 2
        assert abs(centre[index] - (rows[0] + rows[1]) / 2.0) < 0.15 * (rows[1] - rows[0])


def _loop_round_the_parts():
    """A ring of stages whose last output loops back over every part to the first input, as a bus does."""

    from optodraw import MMI1x2, MZM, OnChipPhotodetector, Scene, VerticalGratingCoupler

    chip = Scene(title="loop", width=600, height=300, platform="on_chip")
    split = chip.add(MMI1x2(center=(0, 0), label="split"))
    top = chip.add(MZM(center=(140, 30), label="top"))
    bottom = chip.add(MZM(center=(140, -30), label="bottom"))
    pd = chip.add(OnChipPhotodetector(center=(260, 30), label="PD"))
    gc = chip.add(VerticalGratingCoupler(center=(260, -30), angle=0, label="out"))
    chip.route((split, "o2"), (top, "o1"), kind="waveguide", path_type="smooth")
    chip.route((split, "o3"), (bottom, "o1"), kind="waveguide", path_type="smooth")
    chip.route((top, "o3"), (pd, "o1"), kind="waveguide", path_type="smooth")
    chip.route((bottom, "o3"), (gc, "o1"), kind="waveguide", path_type="smooth")
    # the feedback: from the bottom modulator's spare output, round over everything, into the splitter input
    chip.route((bottom, "o4"), (split, "o1"), kind="waveguide", path_type="manhattan",
               steps=[{"x": 220.0}, {"y": 80.0}, {"x": -60.0}, {"y": 0.0}])
    return chip


def test_a_chip_1d_route_runs_round_the_parts_where_its_2d_route_does():
    schematic = build_schematic(_loop_round_the_parts())
    loop = next(i for i, link in enumerate(schematic.links) if {link.start_port, link.end_port} == {"o4", "o1"})
    highest = min(item.y for item in schematic.items if item.label in ("top", "PD"))
    assert min(y for _, y in schematic.routes[loop]) < highest           # over the top row, as in 2D


def test_a_second_source_s_arm_is_placed_from_the_part_it_joins():
    """The Raman bench has two sources. The LED arm joins the laser line at DM1 through M1; the walk places it
    from DM1, as in 2D, not below the whole laser arm with a long empty drop."""

    from optodraw.literature import mcnairn2021_raman

    scene = mcnairn2021_raman.build()
    scene.metadata.get("view_layout", {}).pop("1d", None)           # the walk, not the source plan
    parts = _by_label(build_schematic(scene))
    dm1, m1, sample = parts["DM1"], parts["M1"], parts["RCF sample"]
    assert m1.y < sample.y + sample.symbol.height                     # the LED row is not below the sample column
    assert abs(m1.port("io")[0] - dm1.port("in")[0]) < 0.01           # straight down from DM1, as in 2D
    _bench_is_clean(build_schematic(scene))


def test_a_bench_label_keeps_its_2d_side_at_the_page_edge():
    """The FTIR source label was set to "top" but went below in 1D: a label over the left edge of the page
    was not free, so a spot below won. The 2D side comes first; the page grows for it."""

    from optodraw import Beam, Lamp, Mirror, Scene

    s = Scene(title="edge", width=60, height=30, platform="free_space")
    lamp = s.add(Lamp(center=(-20, 0), label="Light source", label_side="top"))
    mirror = s.add(Mirror(center=(10, 0), angle=180, label="M"))
    s.add(Beam.through(lamp, mirror))
    schematic = build_schematic(s)
    item = next(item for item in schematic.items if item.label == "Light source")
    assert item.label_at[1] < item.y, (item.label_at, item.y)


def test_a_1d_cable_follows_its_2d_path_left_of_every_part():
    """The Sahoo sync cable runs left of the laser in 2D. The 1D router grid began at page x = 0, so it could
    not follow and went right, across the excitation beam."""

    from bench_scenes import sync_bench

    schematic = build_schematic(sync_bench())
    laser = next(index for index, item in enumerate(schematic.items) if item.label == "Laser")
    index = next(index for index, link in enumerate(schematic.links) if link.kind != "free_space")
    route = schematic.routes[index]
    assert min(x for x, _ in route) < schematic.items[laser].x, route


def _banks_and_pads():
    from optodraw.literature import tait2017_broadcast_weight

    scene = tait2017_broadcast_weight.build()
    schematic = build_schematic(scene)
    banks = sorted((item for item in schematic.items if item.label.startswith("Weight bank")), key=lambda item: item.y)
    return scene, schematic, banks


def test_the_tait_1d_rows_sit_evenly_apart():
    """Review: the gaps between channels 1-2 and 2-3 were too wide, 3-4 fine. The 1D maps height by one map
    for the page, so the tall splitter and AWG symbols stretched the bands of rows 1-2 and 2-3 in every column."""

    _, _, banks = _banks_and_pads()
    pitches = [b.y - a.y for a, b in zip(banks, banks[1:])]
    assert max(pitches) - min(pitches) <= 4.0, pitches


def test_the_tait_1d_passes_the_figure_checks():
    from optodraw import check_figure

    scene, _, _ = _banks_and_pads()
    assert check_figure(scene, view="1d") == []


def _iris_bench():
    from optodraw import Beam, Iris, Laser, Photodiode, QuarterWavePlate, Scene

    s = Scene(title="iris", width=80, height=20, platform="free_space")
    laser = s.add(Laser(center=(-30, 0), wavelength=633, label="Laser"))
    iris = s.add(Iris(center=(-10, 0), outer_diameter=8, aperture_diameter=1, label="Iris"))
    qwp = s.add(QuarterWavePlate(center=(5, 0), aperture=8, label="QWP"))
    qwp.base_mount = "rotation_stage"
    pd = s.add(Photodiode(center=(20, 0), angle=180, label="PD"))
    s.add(Beam(laser, (iris, "in"), (iris, "out"), (qwp, "in"), (qwp, "out"), (pd, "in")))
    return s, iris


def test_a_beam_is_drawn_through_an_open_iris_in_2d():
    """Review: the Wirthl beam stopped on each side of every iris. The light passes through the aperture."""

    scene, iris = _iris_bench()
    beam = next(node for node in scene.walk() if type(node).__name__ == "Beam")
    x0, x1 = (float(iris.world_ports()[name].center.x) for name in ("in", "out"))
    assert any(min(p[0] for p in run) <= x0 and max(p[0] for p in run) >= x1 for run in beam.segments())


def test_a_beam_runs_through_a_straight_through_part_in_1d():
    """The 1D link ended at each side of an iris and of a QWP whose rotation mark widens its symbol: a gap."""

    from optodraw.symbols.schematic import hub_paths

    scene, _ = _iris_bench()
    schematic = build_schematic(scene)
    paths = hub_paths(schematic)
    for label in ("Iris", "QWP"):
        item = next(item for item in schematic.items if item.label == label)
        a, b = item.port("in")[:2], item.port("out")[:2]
        assert (a, b) in paths or (b, a) in paths, label


def test_the_default_label_size_prints_as_before():
    assert 'font-size="7.0"' in render_notebook_1d(_bench())
