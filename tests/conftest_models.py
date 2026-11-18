"""Scenes the compact-model tests share. A module, not a conftest: the tests import it by name."""

import optodraw


def _ring_scene():
    """A chip laser, an all-pass ring labelled "ring" and a chip detector, joined by two waveguide routes."""

    scene = optodraw.Scene(width=300, height=120, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    ring = scene.add(optodraw.MicroringResonator(center=(0, 0), label="ring"))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (detector, "o1"), kind="waveguide")
    return scene, ring, detector
