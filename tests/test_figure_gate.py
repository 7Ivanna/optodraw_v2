"""check_figure finds what makes a figure wrong or unreadable and that no part check sees: labels."""

from __future__ import annotations

from optodraw import Beam, BeamSplitter, FocusingBeam, Laser, Lens, OnChipPhotodetector, Photodiode, Scene
from optodraw import check_figure
from optodraw.layout import aim


def _bench():
    scene = Scene(title="bench", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    pd = scene.add(Photodiode(center=(30, 0), label="PD"))
    scene.add(Beam.through(laser, pd))
    return scene


def test_two_labels_that_overlap_are_found():
    scene = Scene(title="tight", width=100, height=40, platform="free_space")
    scene.add(Photodiode(center=(0, 0), label="Detector one"))
    scene.add(Photodiode(center=(4, 0), label="Detector two"))
    assert any("overlap" in f for f in check_figure(scene, view="2d"))


def _cone(label_at=None):
    scene = Scene(title="cone", width=120, height=60, platform="free_space")
    lens = scene.add(Lens(center=(-20, 0), focal_length=40, label="Lens"))
    pd = scene.add(Photodiode(center=(20, 0), label="PD"))
    scene.add(FocusingBeam((lens, "out"), (pd, "in"), width1=4.0, width2=0.0))
    if label_at is not None:
        scene.add(Photodiode(center=label_at, label="Other"))
    return scene


def test_a_label_on_a_focusing_beam_is_found():
    scene = _cone()
    scene.add(Photodiode(center=(0, -8), label="Below"))        # its label sits above it, across the cone
    assert any("Below" in f and "beam" in f for f in check_figure(scene, view="2d"))


def test_a_label_far_from_its_part_is_found():
    scene = Scene(title="far", width=100, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    bs = scene.add(BeamSplitter(center=(0, 0), label="BS", label_side="top-right"))   # the empty corner of a "\\" plate
    pd = scene.add(Photodiode(center=(0, -30), label="PD"))
    aim(bs, laser, pd)
    assert any("BS" in f and "far from" in f for f in check_figure(scene, view="2d"))


def test_a_label_too_small_at_the_final_width_is_found():
    bench = Scene(title="bench", width=600, height=200, platform="free_space")      # 600 mm in an 89 mm column
    bench.add(Photodiode(center=(0, 0), label="PD"))
    assert any("pt" in f and "small" in f for f in check_figure(bench, preset="single_column", view="2d"))


def test_a_chip_label_is_checked_at_the_size_the_fitted_export_prints_it():
    """A chip goes to the page with fit="width": its labels print at the preset's point size, however wide."""

    from optodraw import VerticalGratingCoupler

    chip = Scene(title="chip", width=1200, height=200, platform="on_chip")
    gc = chip.add(VerticalGratingCoupler(center=(-500, 0), angle=180, label="In"))
    pd = chip.add(OnChipPhotodetector(center=(500, 0), label="PD"))
    chip.route((gc, "o1"), (pd, "o1"), kind="waveguide", path_type="smooth")
    assert not [f for f in check_figure(chip, preset="double_column", view="2d") if "too small" in f]


def test_a_detector_s_own_probe_pads_are_not_loose_ends():
    """A probe lands on the two pads a photodetector draws itself; its optical input still needs a route."""

    from optodraw import VerticalGratingCoupler

    chip = Scene(title="chip", width=300, height=120, platform="on_chip")
    gc = chip.add(VerticalGratingCoupler(center=(-80, 0), angle=180, label="GC"))
    pd = chip.add(OnChipPhotodetector(center=(60, 0), label="PD"))
    chip.route((gc, "o1"), (pd, "o1"), kind="waveguide", path_type="smooth")
    assert not [f for f in check_figure(chip, view="2d") if "not connected" in f]
    chip2 = Scene(title="chip", width=300, height=120, platform="on_chip")
    chip2.add(OnChipPhotodetector(center=(0, 0), label="PD"))
    assert any("PD:o1" in f and "PD:e1" not in f for f in check_figure(chip2, view="2d"))


def test_a_beam_that_stops_inside_a_splitter_is_found():
    """Light leaves a PBS by two faces: a beam that ends in it leaves the figure unfinished."""

    from optodraw import PBS

    scene = Scene(title="stop", width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser"))
    pbs = scene.add(PBS(center=(20, 0), label="PBS"))
    scene.add(Beam(laser, pbs))
    assert any("stops at PBS" in f for f in check_figure(scene, view="2d"))


def test_a_beam_that_leaves_its_last_part_into_nothing_is_found():
    from optodraw import Polarizer

    scene = Scene(title="air", width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser"))
    pol = scene.add(Polarizer(center=(20, 0), label="Analyzer"))
    scene.add(Beam((laser, "out"), (pol, "in"), (pol, "out")))
    assert any("Analyzer" in f and "ends in the air" in f for f in check_figure(scene, view="2d"))


def test_a_detector_off_the_focus_of_the_lens_before_it_is_found():
    from optodraw import Lens

    def bench(gap):
        scene = Scene(title="focus", width=200, height=40, platform="free_space")
        laser = scene.add(Laser(center=(-80, 0), label="Laser"))
        lens = scene.add(Lens(center=(-20, 0), focal_length=75, label="L"))
        pd = scene.add(Photodiode(center=(-20 + gap, 0), label="PD"))
        scene.add(Beam((laser, "out"), (lens, "in"), (lens, "out"), (pd, "in")))
        return scene

    assert any("PD" in f and "focus" in f for f in check_figure(bench(28), view="2d"))
    assert not [f for f in check_figure(bench(75), view="2d") if "focus" in f]


def test_ports_a_part_declares_open_may_stay_unwired():
    """A weight bank's drop-bus taps and an MZM's spare ports are not loose ends; its bus ports still are."""

    from optodraw import MZM, MicroringWeightBank

    chip = Scene(title="open", width=400, height=200, platform="on_chip")
    chip.add(MicroringWeightBank(center=(0, 40), ring_count=4, label="Bank"))
    chip.add(MZM(center=(0, -40), label="MZM"))
    findings = " ".join(check_figure(chip, view="2d"))
    assert "Bank:d1" not in findings and "MZM:o2" not in findings and "MZM:o4" not in findings
    assert "Bank:o1" in findings and "MZM:o1" in findings


def test_a_route_drawn_across_a_part_it_does_not_join_is_a_finding():
    """A waveguide that runs under a detector's pads looks clean in the picture's code and wrong on the chip."""

    from optodraw import OnChipBalancedPhotodetector, Scene, Waveguide

    chip = Scene(title="", width=200, height=100, platform="on_chip")
    a = chip.add(Waveguide(center=(-60, 0), length=14, label=""))
    b = chip.add(Waveguide(center=(60, 0), length=14, label=""))
    chip.add(OnChipBalancedPhotodetector(center=(0, 0), label="BPD"))
    # explicit steps: the router follows them and does not steer round the detector
    chip.route((a, "o2"), (b, "o1"), kind="waveguide", path_type="manhattan", steps=[{"x": -20.0}, {"y": 0.0}])
    findings = check_figure(chip, view="2d")
    assert any("runs over BPD" in finding for finding in findings), findings


def test_a_1d_route_that_crosses_more_than_its_2d_route_is_a_finding(monkeypatch):
    """The Sahoo sync cable runs round the outside in 2D and crossed the excitation beam in 1D; the gate did
    not see it. A 1D route that crosses more links than its 2D route does not follow the 2D."""

    import optodraw.symbols.router as router
    from bench_scenes import sync_bench

    real = router.route_links
    monkeypatch.setattr(router, "route_links", lambda schematic, guides=None: real(schematic, {}))  # no guides
    findings = check_figure(sync_bench(), view="1d")
    assert any("sync->in1" in finding and "cross" in finding for finding in findings), findings


def _coupler_alone():
    from optodraw import EdgeCoupler

    chip = Scene(title="chip", width=200, height=80, platform="on_chip")
    return chip, chip.add(EdgeCoupler(center=(0, 0), label="EC"))     # o1 at (24, 0), facing +x


def _loose(scene):
    return [f for f in check_figure(scene, view="2d") if "not connected" in f]


def test_an_arrow_at_a_port_shows_the_light_and_closes_it():
    from optodraw import SignalArrow

    chip, _ = _coupler_alone()
    assert _loose(chip)
    chip.add(SignalArrow((0, 0), (12, 0), center=(27, 1), label="Out"))   # its tail 3 past o1, pointing away
    assert _loose(chip) == []


def test_an_arrow_across_a_port_does_not():
    from optodraw import SignalArrow

    chip, _ = _coupler_alone()
    chip.add(SignalArrow((0, -10), (0, 0), center=(24, 2)))                # its head 2 from o1, but across the axis
    assert _loose(chip)


def test_a_port_the_figure_leaves_open_stays_open_after_a_save():
    import pytest

    from optodraw.schema import scene_from_spec

    chip, coupler = _coupler_alone()
    chip.leave_open(coupler, "o1")
    assert _loose(chip) == []
    assert _loose(scene_from_spec(chip.to_spec())) == []
    with pytest.raises(KeyError, match="no port o9"):
        chip.leave_open(coupler, "o9")
