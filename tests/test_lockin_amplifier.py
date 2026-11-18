"""The lock-in amplifier: signal in, output X and reference in on the front panel, one plan for the ports, the 2D,
the TikZ pic and the 3D case (an SR830-kind dual-phase lock-in)."""

from __future__ import annotations


from optodraw import (LockInAmplifier, Photodiode, Scene, WaveformGenerator, check_figure)


def test_a_detector_and_a_reference_wire_to_it_clean_in_2d_and_1d():
    # mutant: JACKS "ref": 0.95 in LockInAmplifier: the reference jack sits on the corner of the case
    scene = Scene(width=120, height=60, platform="free_space")
    lockin = scene.add(LockInAmplifier(center=(20, 0), label="Lock-in"))
    pd = scene.add(Photodiode(center=(-30, -20), label="PD"))
    source = scene.add(WaveformGenerator(center=(40, 30), label="Reference"))
    scene.route((pd, "e2"), (lockin, "in"), kind="electrical", width=0.3)
    scene.route((source, "out2"), (lockin, "ref"), kind="electrical", width=0.3)
    scene.fit_frame(margin=6)
    assert check_figure(scene, preset="single_column") == []


