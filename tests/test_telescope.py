"""A telescope is two lenses at their true spacing, in every view, with the light open between them."""


from optodraw import Beam, Laser, Photodiode, Scene, Telescope


def with_role(part, role):
    return [solid for solid in part.geometry_3d()["children"] if solid.get("role") == role]


def along_x(solid):
    """The start and the end of a solid along the beam."""

    x = solid["position"][0]
    if solid["shape"] == "lathe_profile":
        heights = [point[1] for point in solid["points"]]
        return x + min(heights), x + max(heights)
    half = solid.get("height", solid.get("width", 0.0)) / 2.0 if solid.get("rotation") else solid.get("width", 0.0) / 2.0
    return x - half, x + half


def lens_places(part):
    return sorted(child["pic"]["origin"][0] for child in part.geometry_2d()["children"] if child["type"] == "art")


def rays(part):
    return [child for child in part.geometry_2d()["children"] if child["type"] == "line" and child.get("role") == "ray"]


def test_a_bench_draws_it_in_2d_and_in_tikz():
    scene = Scene(title="Telescope", width=170, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-62, 0), wavelength=633, label="Laser"))
    part = scene.add(Telescope(center=(0, 0), label="Telescope"))
    detector = scene.add(Photodiode(center=(62, 0), label="Detector"))
    scene.add(Beam.through(laser, part, detector, wavelength=633))
    assert scene.render_svg().as_svg().count('data-art="lens"') == 2
    assert scene.render_tikz().count("{od lens=") == 2


