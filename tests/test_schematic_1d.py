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


def test_an_instrument_that_drives_two_parts_sits_above_them():
    schematic = build_schematic(_bench())
    parts = _by_label(schematic)
    awg, m1, m2 = parts["AWG"], parts["MZM 1"], parts["MZM 2"]
    assert awg.y + awg.symbol.height <= min(m1.y, m2.y)
    assert m1.port("sig")[0] <= awg.port("out1")[0] < awg.port("out2")[0] <= m2.port("sig")[0]
    assert awg.x > parts["Laser"].x + parts["Laser"].symbol.width      # not in the column of the source
    assert _crossings(schematic) == 0 and _overlaps(schematic) == []
    assert min(item.y - (LABEL_HEIGHT if item.label_above else 0.0) for item in schematic.items) >= 4.99


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


def test_an_empty_scene_says_so():
    svg = render_notebook_1d(optodraw.Scene())
    ET.fromstring(svg)
    assert "No components" in svg


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


def test_a_chip_whose_automatic_1d_crosses_keeps_its_plan_arrangement():
    """The scope reads the receiver: drawn where the plan puts it, its cable crosses no optical path."""

    from optodraw.symbols.schematic import link_crossings

    scene = _bench(scope_first=True)
    assert link_crossings(build_schematic(scene, arrangement="auto")) > 0
    chosen = build_schematic(scene)
    assert link_crossings(chosen) == 0
    parts = _by_label(chosen)
    assert parts["Scope"].x > parts["ICR"].x


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


def test_a_row_of_pads_routes_quickly():
    import time

    started = time.perf_counter()
    schematic = build_schematic(_bank_with_pads(), arrangement="auto")
    assert time.perf_counter() - started < 1.0
    assert len(schematic.routes) == 8


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


