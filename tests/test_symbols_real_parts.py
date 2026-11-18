"""A bench symbol shows its object: the art agrees with the part's own 3D model, and no two parts share one bar."""

import io
import itertools
import math
import re

import pytest

from optodraw import ApertureStop, Beam, BeamDump, Block, Filter, Laser, Mirror, Periscope, Photodiode, Razor, Sample, Scene
from optodraw.animation_engine import Animation
from optodraw.app.validation import run_checks
from optodraw.symbols import lookup
from optodraw.symbols.art import art_bounds, fit_art, symbol_for_2d
from optodraw.symbols.build import library_files


def art(part, look="2d"):
    """The drawing of a part as red, green, blue, alpha, at ten pixels to the point."""

    numpy = pytest.importorskip("numpy")
    cairosvg = pytest.importorskip("cairosvg")
    image = pytest.importorskip("PIL.Image")
    symbol = lookup(part)
    drawn = cairosvg.svg2png(bytestring=(symbol.svg2d if look == "2d" else symbol.svg).encode(), scale=10)
    return numpy.asarray(image.open(io.BytesIO(drawn)).convert("RGBA")).astype(float), symbol


def pixel(rgba, symbol, x, y):
    """The row and the column of a point of the symbol, in SVG points."""

    scale = rgba.shape[1] / symbol.width
    return int(y * scale), int(x * scale)


def luma(rgba):
    return 0.2126 * rgba[..., 0] + 0.7152 * rgba[..., 1] + 0.0722 * rgba[..., 2]


def runs(row):
    return sum(1 for a, b in itertools.pairwise([False, *row]) if b and not a)


def silhouette(part, size=64):
    numpy = pytest.importorskip("numpy")
    image = pytest.importorskip("PIL.Image")
    rgba, _ = art(part)
    ink = rgba[..., 3] > 128
    rows, columns = numpy.where(ink.any(axis=1))[0], numpy.where(ink.any(axis=0))[0]
    crop = ink[rows.min():rows.max() + 1, columns.min():columns.max() + 1]
    return numpy.asarray(image.fromarray(crop).resize((size, size))) > 0


def solids(part):
    return part.geometry_3d()["children"]


def top_of(solid):
    return solid["position"][1] + solid["height"] / 2.0


def test_the_fins_of_a_dump_stand_round_its_body_as_in_3d():
    rgba, _ = art(BeamDump())
    ink = rgba[..., 3] > 128
    top = int(ink.any(axis=1).argmax())
    assert runs(ink[top + 4]) == sum(solid.get("role") == "fin" for solid in solids(BeamDump()))


def test_the_flat_geometry_of_a_dump_is_as_tall_as_its_fins():
    from optodraw.layout import _bounds_from_geometry

    dump = BeamDump(aperture=10.0)
    _, y0, _, y1 = _bounds_from_geometry(dump.geometry_2d())
    assert y1 - y0 == pytest.approx(2 * 0.58 * 10.0)


@pytest.mark.parametrize("look, dark", [("2d", True), ("1d", False)])
def test_the_cone_of_a_dump_is_dark_in_2d_and_open_in_1d(look, dark):
    rgba, symbol = art(BeamDump(), look)
    row, column = pixel(rgba, symbol, symbol.ports["in"].x + 3.0, symbol.ports["in"].y + 0.6)   # the rays run off the axis
    brightness = luma(rgba)[row, column]
    assert rgba[row, column, 3] > 200 and brightness < 70 if dark else rgba[row, column, 3] < 60 or brightness > 200


def ray_of_the_dump():
    """The legs of the ray in the picture of the dump, as they are drawn: (x0, y0, x1, y1), in units of the aperture."""

    tex = "\n".join(path.read_text(encoding="utf-8") for path in library_files())
    picture = tex[tex.index("pics/od beamdump/.style"):]
    legs = re.search(r"\\odo in\s*\{([^}]*)\}", picture).group(1)
    return [tuple(float(v) for v in leg.strip().split("/")[:4]) for leg in legs.split(",")]


def test_a_ray_shows_in_the_2d_dump():
    rgba, _ = art(BeamDump())
    assert (rgba[..., 0] - rgba[..., 2] > 80).any()


def test_a_ray_in_the_dump_keeps_to_the_law_of_reflection():
    legs = ray_of_the_dump()
    slope = 0.34 / 0.68                                                 # the cone of the part: mouth 0.34, length 0.68
    for first, second in zip(legs, legs[1:]):
        assert first[2:] == second[:2]
        x, y = first[2:]
        assert abs(y) == pytest.approx(slope * (0.33 - x), abs=0.003)   # the leg ends on a wall
        side = math.copysign(1.0, y)
        normal = (math.sin(math.atan(slope)), side * math.cos(math.atan(slope)))
        come = (x - first[0], y - first[1])
        length = math.hypot(*come)
        come = (come[0] / length, come[1] / length)
        dot = come[0] * normal[0] + come[1] * normal[1]
        turned = (come[0] - 2.0 * dot * normal[0], come[1] - 2.0 * dot * normal[1])
        away = math.atan2(second[3] - y, second[2] - x)
        assert math.degrees(abs(away - math.atan2(turned[1], turned[0]))) == pytest.approx(0.0, abs=1.0)


def test_the_third_bounce_turns_the_ray_back_toward_the_mouth():
    last = ray_of_the_dump()[-1]
    assert last[2] < last[0]


@pytest.mark.parametrize("part", [BeamDump(), Block(), ApertureStop()], ids=["dump", "block", "stop"])
def test_what_stops_light_is_dark_in_2d(part):
    rgba, _ = art(part)
    ink = rgba[..., 3] > 200
    assert (luma(rgba)[ink] < 90).mean() > 0.35


def test_no_two_kinds_of_part_on_a_beam_share_one_bar():
    parts = {name: silhouette(cls()) for name, cls in
             {"Block": Block, "Mirror": Mirror, "Filter": Filter, "Sample": Sample, "Razor": Razor}.items()}
    for (a, first), (b, second) in itertools.combinations(parts.items(), 2):
        overlap = (first & second).sum() / (first | second).sum()
        assert overlap < 0.85, f"{a} and {b} draw the same outline"


def test_a_block_stands_on_a_post_and_a_base_as_in_3d():
    rgba, _ = art(Block())
    ink = rgba[..., 3] > 128
    rows = ink.any(axis=1).nonzero()[0]
    widths = [ink[row].sum() for row in rows]
    assert max(widths[-40:]) > 2.5 * max(widths[: len(widths) // 3])        # a base wider than the flag


def test_a_block_meets_the_beam_on_its_flag():
    rgba, symbol = art(Block())
    row, column = pixel(rgba, symbol, symbol.ports["in"].x + 0.5, symbol.ports["in"].y)
    assert rgba[row, column, 3] > 200 and luma(rgba)[row, column] < 90


def test_a_beam_runs_past_a_knife_edge():
    scene = Scene(title="Knife edge", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-35, 0), wavelength=633, label="Laser"))
    razor = scene.add(Razor(center=(0, 0), label="Knife edge"))
    pd = scene.add(Photodiode(center=(35, 0), label="PD"))
    scene.add(Beam.through(laser, razor, pd, wavelength=633))
    assert sorted(razor.ports()) == ["in", "out"]
    assert not [issue for issue in run_checks(scene) if issue["level"] == "error"]


def test_the_tip_of_a_knife_edge_sits_on_the_beam_axis():
    rgba, symbol = art(Razor())
    ink = rgba[..., 3] > 128
    assert int(ink.any(axis=1).argmax()) == pytest.approx(pixel(rgba, symbol, 0.0, symbol.ports["in"].y)[0], abs=6)


@pytest.mark.parametrize("edge", [0.0, 1.5, -1.0])
def test_nothing_of_a_knife_edge_stands_above_its_edge_in_3d(edge):
    razor = Razor(blade_pos=edge)
    assert max(top_of(solid) for solid in solids(razor)) == pytest.approx(edge)


def test_the_flat_blade_of_a_knife_edge_is_under_its_edge():
    from optodraw.layout import _bounds_from_geometry

    razor = Razor(blade_pos=0.0)
    assert _bounds_from_geometry(razor.geometry_2d())[3] == pytest.approx(0.0)


def test_a_sample_shows_its_chip_on_a_copper_plate_as_in_3d():
    rgba, symbol = art(Sample())
    above = symbol.ports["in"].y - 4.0                                      # above the spot the beam lands on
    chip = rgba[pixel(rgba, symbol, symbol.ports["in"].x + 0.5, above)]
    plate = rgba[pixel(rgba, symbol, symbol.ports["out"].x - 0.5, above)]
    assert chip[3] > 200 and chip[:3].sum() < 3 * 100
    assert plate[3] > 200 and plate[0] - plate[2] > 60


def test_a_vertical_sample_is_held_by_clips_at_both_ends_as_in_3d():
    sample = Sample()
    clips = [solid for solid in solids(sample) if solid.get("role") == "clip"]
    assert sorted(math.copysign(1.0, solid["position"][1]) for solid in clips) == [-1.0, -1.0, 1.0, 1.0]
    rgba, _ = art(sample)
    ink = rgba[..., 3] > 128
    rows = ink.any(axis=1).nonzero()[0]
    widest, middle = ink[rows.min() + 6].sum(), ink[(rows.min() + rows.max()) // 2].sum()
    assert widest > 1.2 * middle                                            # the clips reach past the chip's face


def test_a_vertical_sample_draws_no_stem_foot_or_spot():
    tex = "\n".join(path.read_text(encoding="utf-8") for path in library_files())
    picture = tex[tex.index("pics/od sample/.style"):]
    upright = picture[picture.index("% In units of the aperture"):picture.index("}}}")]
    assert "circle" not in upright and "od wg" not in upright


@pytest.mark.parametrize("part", [Razor(), Sample(), Block()], ids=["razor", "sample", "block"])
def test_the_ports_of_a_part_on_a_beam_face_along_it(part):
    ports = lookup(part).ports
    assert (ports["in"].side, ports["out"].side) == ("left", "right")


def absorbed(*parts):
    scene = Scene(title="Light", width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), wavelength=633))
    placed = [scene.add(part) for part in parts]
    scene.add(Beam.through(laser, *placed, wavelength=633))
    light = Animation(scene, mode="cw", strict=True).auto().click()
    return {record["part"]: round(record["power"], 3) for record in light.to_json()["signal_state"]["absorbed"]}


def test_a_block_ends_the_light():
    assert list(absorbed(Block(center=(0, 0))).values()) == [1.0]


def test_a_knife_edge_on_the_axis_passes_half_of_the_power():
    assert list(absorbed(Razor(center=(0, 0)), Photodiode(center=(30, 0), angle=180)).values()) == [0.5]


def top_art(part):
    """The drawing a part shows in 2D, which may be another view than its 1D symbol."""

    numpy = pytest.importorskip("numpy")
    cairosvg = pytest.importorskip("cairosvg")
    image = pytest.importorskip("PIL.Image")
    symbol = symbol_for_2d(part)
    drawn = cairosvg.svg2png(bytestring=symbol.svg2d.encode(), scale=10)
    return numpy.asarray(image.open(io.BytesIO(drawn)).convert("RGBA")).astype(float), symbol


def test_a_laser_head_is_dark_as_in_3d():
    rgba, symbol = top_art(Laser())
    ink = rgba[..., 3] > 200
    assert (luma(rgba)[ink] < 90).mean() > 0.6


def test_a_laser_head_shows_the_fins_of_its_3d_model():
    rgba, symbol = top_art(Laser())
    fins = sum(solid["shape"] == "box" and solid["height"] == pytest.approx(0.7) for solid in solids(Laser()))
    row = int(rgba.shape[0] / 2)
    column_stop = pixel(rgba, symbol, symbol.origin[0] - 0.47 * 28.35, 0.0)[1]    # the fins end before the screen
    start = pixel(rgba, symbol, symbol.origin[0] - 1.0 * 28.35, 0.0)[1]           # the rear face; the drive jack stands behind it
    lines = luma(rgba)[row, start + 8:column_stop] > 70
    assert runs(lines) == fins


def test_a_laser_head_is_as_wide_as_its_3d_model():
    """The head read as a flat bar: 3.3 times longer than wide, where the 3D head is about 2 to 1."""

    laser = Laser()
    rgba, symbol = top_art(laser)
    numpy = pytest.importorskip("numpy")
    ink = rgba[..., 3] > 128
    rows, columns = numpy.where(ink.any(axis=1))[0], numpy.where(ink.any(axis=0))[0]
    drawn = (columns.max() - columns.min()) / (rows.max() - rows.min())
    shapes = solids(laser)
    length = max(solid["position"][0] + solid.get("height", 0.0) / 2.0 for solid in shapes if solid["shape"] == "cylinder" and solid.get("rotation"))
    length -= min(solid["position"][0] - solid["width"] / 2.0 for solid in shapes if solid["shape"] == "box")
    depth = max(solid["depth"] for solid in shapes if solid["shape"] == "box")
    assert drawn == pytest.approx(length / depth, rel=0.1)


def test_a_laser_head_keeps_its_length_and_gains_its_width_on_a_bench():
    x0, y0, x1, y1 = art_bounds(Laser())
    assert x1 - x0 > 13.0 and y1 - y0 > 6.5


def test_a_laser_with_a_sync_output_is_drawn_at_the_size_of_any_other_laser():
    plain, synced = art_bounds(Laser()), art_bounds(Laser(sync=True))
    assert synced[2] - synced[0] == pytest.approx(plain[2] - plain[0], rel=0.05)
    assert fit_art(Laser(sync=True)).residual < 0.01                        # the jack sits on its port


def test_a_laser_keeps_its_spectrum_and_its_diode():
    tex = "\n".join(path.read_text(encoding="utf-8") for path in library_files())
    top = tex[tex.index("pics/od lasersource/.style"):tex.index("% ---------------------------------------------------------------- lamp")]
    assert top.count("od trace, draw=\\odtc") == 2 and top.count("od light") >= 2


def test_a_mirror_shows_a_bright_face_on_a_dark_mount():
    rgba, symbol = art(Mirror())
    row = int(rgba.shape[0] / 2)
    ink = (rgba[row, :, 3] > 200).nonzero()[0]
    assert luma(rgba)[row, ink[len(ink) // 6]] > 170 and luma(rgba)[row, ink[-len(ink) // 3]] < 90


@pytest.mark.parametrize("kwargs", [{}, {"rise": -30.0}, {"output_angle_deg": 90.0}])
def test_the_periscope_keeps_to_the_light_look_of_the_bench(kwargs):
    fills = [child["fill"] for child in Periscope(**kwargs).geometry_2d()["children"] if child.get("fill", "none").startswith("#")
             and child["type"] == "rect"]
    assert fills and all(int(fill[1:3], 16) > 200 for fill in fills)


@pytest.mark.parametrize("angle", [0.0, 90.0, 270.0])
def test_the_upper_mirror_of_a_periscope_stands_across_the_beam_that_leaves(angle):
    band = [child for child in Periscope(output_angle_deg=angle).geometry_2d()["children"] if child["type"] == "polyline"][-1]
    (x0, y0), (x1, y1) = band["points"]
    leave = (math.cos(math.radians(angle)), math.sin(math.radians(angle)))
    assert (x1 - x0) * leave[0] + (y1 - y0) * leave[1] == pytest.approx(0.0, abs=1e-9)


def test_the_mark_of_a_periscope_is_not_under_its_upper_mount():
    children = Periscope().geometry_2d()["children"]
    upper = [child for child in children if child["type"] == "rect"][-1]
    mark = next(child for child in children if child["type"] == "circle")
    assert mark["cx"] + mark["r"] < upper["cx"] - upper["w"] / 2.0


def test_the_mark_of_a_periscope_says_which_way_the_light_runs():
    up = Periscope(rise=30.0).geometry_2d()["children"]
    down = Periscope(rise=-30.0).geometry_2d()["children"]
    assert sum(child["type"] == "circle" for child in up) == 2 and not [child for child in up if child["type"] == "line"]
    assert sum(child["type"] == "circle" for child in down) == 1 and sum(child["type"] == "line" for child in down) == 2


def test_no_drawing_in_the_library_is_cut_by_its_box():
    """A 2D drawing shares the box of its 1D symbol, so a 2D part that reaches past that box loses its edge."""

    numpy = pytest.importorskip("numpy")
    cairosvg = pytest.importorskip("cairosvg")
    image = pytest.importorskip("PIL.Image")
    from optodraw.symbols import _index, _symbol

    cut = []
    for name, (entry, folder) in _index()[0].items():
        symbol = _symbol(entry, folder, exact=True, source="library")
        for look, svg in (("1d", symbol.svg), ("2d", symbol.svg2d)):
            if not svg:
                continue
            rgba = numpy.asarray(image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(), scale=4))).convert("RGBA"))
            alpha = rgba[..., 3] > 200
            if alpha[:, :2].any() or alpha[:, -2:].any() or alpha[:2, :].any() or alpha[-2:, :].any():
                cut.append(f"{name} {look}")
    assert not cut, cut


@pytest.mark.parametrize("name", ["objective", "iris"])
def test_a_part_draws_no_light_in_the_air_beside_it(name):
    tex = "\n".join(path.read_text(encoding="utf-8") for path in library_files())
    picture = tex[tex.index(f"pics/od {name}/.style"):]
    picture = picture[:picture.index("}}}")]
    assert "od rayb" not in picture


def test_an_objective_ends_at_its_front_lens():
    from optodraw import Objective

    rgba, symbol = art(Objective())
    ink = rgba[..., 3] > 128
    last = int(ink.any(axis=0).nonzero()[0].max())
    assert last == pytest.approx(pixel(rgba, symbol, symbol.ports["out"].x, 0.0)[1], abs=6)
    red = (rgba[..., 0] > 200) & (rgba[..., 1] < 110) & (rgba[..., 2] < 110) & ink
    assert not red.any()


def test_a_block_stands_on_the_bench_post_alone():
    """The part draws its flag and a boss. The post and its base come from the bench, as for every part on a post."""

    block = Block()
    assert block.base_mount == "post"
    group = block.geometry_3d()
    assert len(group["children"]) == 2 and "post_at" in group
    boss = group["children"][1]
    assert group["post_at"][1] == pytest.approx(boss["position"][1] - boss["height"] / 2.0)


def test_a_block_has_no_loose_solid_in_3d():
    from optodraw import check_part_3d

    assert check_part_3d(Block()) == [] and check_part_3d(Razor()) == []


def test_a_knife_edge_shows_a_blade_in_a_clamp_in_3d():
    roles = [solid.get("role") for solid in solids(Razor())]
    assert roles.count("jaw") == 2 and roles.count("slot") == 1 and roles.count("hole") == 2


def test_the_jaws_of_a_knife_edge_hold_the_blade_from_both_sides():
    razor = Razor()
    blade = next(solid for solid in solids(razor) if solid.get("role") == "blade")
    jaws = [solid for solid in solids(razor) if solid.get("role") == "jaw"]
    assert sorted(math.copysign(1.0, jaw["position"][0]) for jaw in jaws) == [-1.0, 1.0]
    for jaw in jaws:
        assert abs(jaw["position"][0]) - jaw["width"] / 2.0 == pytest.approx(blade["width"] / 2.0)
