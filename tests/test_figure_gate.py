"""check_figure finds what makes a figure wrong or unreadable and that no part check sees: labels."""

from __future__ import annotations

from optodraw import Beam, BeamSplitter, ElectricalPad, FocusingBeam, Laser, Lens, Mirror, OnChipPhotodetector, Photodiode, Scene
from optodraw import check_figure
from optodraw.layout import aim, face


def _bench():
    scene = Scene(title="bench", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    pd = scene.add(Photodiode(center=(30, 0), label="PD"))
    scene.add(Beam.through(laser, pd))
    return scene


def test_a_clean_bench_passes():
    assert check_figure(_bench(), view="2d") == []


def test_two_labels_that_overlap_are_found():
    scene = Scene(title="tight", width=100, height=40, platform="free_space")
    scene.add(Photodiode(center=(0, 0), label="Detector one"))
    scene.add(Photodiode(center=(4, 0), label="Detector two"))
    assert any("overlap" in f for f in check_figure(scene, view="2d"))


def test_a_label_on_a_beam_is_found():
    scene = Scene(title="fold", width=100, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    mirror = scene.add(Mirror(center=(0, 0), label="M", label_side="top"))
    pd = scene.add(Photodiode(center=(0, 30), label="PD"))
    aim(mirror, laser, pd)
    face(pd, mirror)
    scene.add(Beam.through(laser, mirror, pd))                  # the beam leaves the mirror upward, through "M"
    assert any("M" in f and "beam" in f for f in check_figure(scene, view="2d"))


def _cone(label_at=None):
    scene = Scene(title="cone", width=120, height=60, platform="free_space")
    lens = scene.add(Lens(center=(-20, 0), focal_length=40, label="Lens"))
    pd = scene.add(Photodiode(center=(20, 0), label="PD"))
    scene.add(FocusingBeam((lens, "out"), (pd, "in"), width1=4.0, width2=0.0))
    if label_at is not None:
        scene.add(Photodiode(center=label_at, label="Other"))
    return scene


def test_a_focusing_beam_is_light_not_a_part():
    assert not any("sits on" in f and "FocusingBeam" in f for f in check_figure(_cone(), view="2d"))


def test_a_label_on_a_focusing_beam_is_found():
    scene = _cone()
    scene.add(Photodiode(center=(0, -8), label="Below"))        # its label sits above it, across the cone
    assert any("Below" in f and "beam" in f for f in check_figure(scene, view="2d"))


def test_a_label_near_a_focusing_beam_does_not_stop_the_check():
    scene = _cone((0, 12))
    assert isinstance(check_figure(scene, view="2d"), list)


def test_a_beam_that_goes_on_as_a_focusing_beam_is_not_a_dead_end():
    scene = Scene(title="on", width=120, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser"))
    lens = scene.add(Lens(center=(-10, 0), focal_length=30, label="Lens"))
    pd = scene.add(Photodiode(center=(20, 0), label="PD"))
    scene.add(Beam((laser, "out"), (lens, "in")))
    scene.add(FocusingBeam((lens, "out"), (pd, "in"), width1=4.0, width2=0.0))
    assert not any("stops at" in f for f in check_figure(scene, view="2d"))


def test_a_label_far_from_its_part_is_found():
    scene = Scene(title="far", width=100, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    bs = scene.add(BeamSplitter(center=(0, 0), label="BS", label_side="top-right"))   # the empty corner of a "\\" plate
    pd = scene.add(Photodiode(center=(0, -30), label="PD"))
    aim(bs, laser, pd)
    assert any("BS" in f and "far from" in f for f in check_figure(scene, view="2d"))


def test_a_label_cut_off_by_the_frame_is_found():
    scene = Scene(title="edge", width=60, height=30, platform="free_space")
    scene.add(Laser(center=(-26, 0), label="Helium-neon laser"))
    assert any("cut off" in f for f in check_figure(scene, view="2d"))


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


def test_a_label_that_reads_like_a_sentence_is_found():
    scene = _bench()
    scene.add(Photodiode(center=(0, -15), label="the detector that reads the beam"))
    assert any("words" in f for f in check_figure(scene, view="2d"))


def test_unwired_chip_ports_and_crossing_routes_are_found():
    chip = Scene(title="chip", width=300, height=200, platform="on_chip")
    pd = chip.add(OnChipPhotodetector(center=(0, 0), label="PD"))
    pad_a = chip.add(ElectricalPad(center=(-40, -40), label="A"))
    pad_b = chip.add(ElectricalPad(center=(40, 40), label="B"))
    chip.route((pd, "e1"), (pad_a, "e1"), kind="electrical", path_type="L")
    chip.route((pd, "e2"), (pad_b, "e1"), kind="electrical", path_type="L")
    findings = check_figure(chip, view="2d")
    assert any("PD:o1" in f and "not connected" in f for f in findings)


def test_a_label_beside_a_tilted_plate_sits_next_to_the_plate():
    """A 45 degree plate's art frame is a square; its turned box put every corner label 8 units away."""

    scene = Scene(title="far", width=100, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    bs = scene.add(BeamSplitter(center=(0, 0), label="BS", label_side="top-right"))
    pd = scene.add(Photodiode(center=(0, 30), label="PD"))
    aim(bs, laser, pd)
    assert not any("BS" in f and "far from" in f for f in check_figure(scene, view="2d"))


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


def test_a_beam_that_ends_on_a_detector_or_returns_from_a_sample_is_finished():
    from optodraw import Objective, Sample

    assert not [f for f in check_figure(_bench(), view="2d") if "stops at" in f]
    scene = Scene(title="epi", width=120, height=80, platform="free_space")
    objective = scene.add(Objective(center=(0, 0), angle=-90, label="Obj", label_side="right"))
    sample = scene.add(Sample(center=(0, -30), angle=-90, label="Sample", label_side="right"))
    pd = scene.add(Photodiode(center=(0, 30), angle=-90, label="PD", label_side="right"))
    scene.add(Beam((objective, "out"), (sample, "in")))
    scene.add(Beam((sample, "in"), (objective, "out"), (objective, "in"), (pd, "in")))
    assert not [f for f in check_figure(scene, view="2d") if "stops at" in f]


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


def test_a_power_meter_or_a_sample_ends_a_beam_by_nature():
    from optodraw import PowerMeter, Sample

    for end in (PowerMeter(center=(30, 0), label="Meter"), Sample(center=(30, 0), angle=180, label="Sample")):
        scene = Scene(title="end", width=100, height=40, platform="free_space")
        laser = scene.add(Laser(center=(-30, 0), label="Laser"))
        scene.add(end)
        scene.add(Beam((laser, "out"), (end, "in")))
        assert not [f for f in check_figure(scene, view="2d") if "stops at" in f], type(end).__name__


def test_a_label_may_sit_on_the_part_that_holds_its_part():
    """An objective inside a cryostat: its label lies on the cryostat, as in the figure."""

    from optodraw import Cryostat, Objective

    scene = Scene(title="nest", width=120, height=120, platform="free_space")
    scene.add(Cryostat(center=(0, 0), radius=40, with_sample=False, label="Cryostat", label_side="right"))
    scene.add(Objective(center=(0, 10), angle=-90, label="Obj", label_side="right"))
    assert not [f for f in check_figure(scene, view="2d") if '"Obj" sits on Cryostat' in f]


def test_a_spread_out_chip_figure_is_found():
    """A figure is compact: parts that fill little of the box, and a wire that crosses it, are findings."""

    from optodraw import ElectricalPad, PhaseShifter

    chip = Scene(title="spread", width=1200, height=800, platform="on_chip")
    ps = chip.add(PhaseShifter(center=(-400, 0), label="PS"))
    pad = chip.add(ElectricalPad(center=(400, 300), label="pad"))
    chip.route((ps, "h2"), (pad, "e1"), kind="electrical", path_type="L")
    findings = check_figure(chip, view="2d")
    assert any("fill" in f for f in findings)
    assert any("runs" in f and "PS" in f for f in findings)


def test_a_long_loop_round_the_outside_is_not_a_finding():
    """A feedback bus that runs round the parts in one outside lane, as the skill asks, is not "across"."""

    from optodraw import MZM, OnChipLaser

    chip = Scene(title="loop", width=600, height=300, platform="on_chip")
    first = chip.add(MZM(center=(0, 40), label="M1"))
    chip.add(MZM(center=(0, -40), label="M2"))
    last = chip.add(OnChipLaser(center=(200, 0), label="out"))
    chip.route((first, "o3"), (last, "o1"), kind="waveguide", path_type="smooth")
    chip.route((last, "o1"), (first, "o1"), kind="waveguide", path_type="manhattan",
               steps=[{"x": 260.0}, {"y": -90.0}, {"x": -90.0}, {"y": 40.0}])
    assert not [f for f in check_figure(chip, view="2d") if "runs" in f]


def test_a_compact_chip_figure_passes_the_spread_checks():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    import tutorial_scenes

    findings = check_figure(tutorial_scenes.bogaerts_add_drop(), view="2d")
    assert not [f for f in findings if "fill" in f or "runs" in f]


def test_ports_a_part_declares_open_may_stay_unwired():
    """A weight bank's drop-bus taps and an MZM's spare ports are not loose ends; its bus ports still are."""

    from optodraw import MZM, MicroringWeightBank

    chip = Scene(title="open", width=400, height=200, platform="on_chip")
    chip.add(MicroringWeightBank(center=(0, 40), ring_count=4, label="Bank"))
    chip.add(MZM(center=(0, -40), label="MZM"))
    findings = " ".join(check_figure(chip, view="2d"))
    assert "Bank:d1" not in findings and "MZM:o2" not in findings and "MZM:o4" not in findings
    assert "Bank:o1" in findings and "MZM:o1" in findings


def test_a_wire_between_neighbours_is_not_long_whatever_the_small_pads():
    from optodraw import ElectricalPad, PhaseShifter

    chip = Scene(title="pads", width=300, height=200, platform="on_chip")
    ps = chip.add(PhaseShifter(center=(0, 0), label="PS"))
    for k in range(12):                                          # many small pads pull the median part size down
        chip.add(ElectricalPad(center=(-100 + 18 * k, -60), width=8, height=8, label=""))
    pad = chip.add(ElectricalPad(center=(60, 30), width=10, height=10, angle=90, label=""))
    chip.route((ps, "h2"), (pad, "e1"), kind="electrical", path_type="L")
    assert not [f for f in check_figure(chip, view="2d") if "runs" in f]


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
