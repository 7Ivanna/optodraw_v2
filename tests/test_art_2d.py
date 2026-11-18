"""2D art: a part is painted with its symbol, fitted to its physical ports."""

from __future__ import annotations

import pytest

import optodraw
from optodraw.registry import build_component
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d, fit_art

STAGE_0 = ["Lens", "Mirror", "PBS"]


def _svg_point(matrix, x, y):
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


@pytest.mark.parametrize("name", STAGE_0)
def test_a_part_is_painted_with_its_symbol(name):
    art = art_2d(build_component(name))
    assert art is not None and art["type"] == "art" and art["residual"] < 0.15
    assert art["svg"] and len(art["matrix"]) == 6


@pytest.mark.parametrize("name", STAGE_0)
def test_the_art_ports_land_on_the_physical_ports(name):
    part = build_component(name)
    art, symbol = art_2d(part), lookup(part)
    ports = part.ports()
    span = max(max(abs(p.center.x), abs(p.center.y)) for p in ports.values()) * 2 or 10.0
    for port_name, port in ports.items():
        x, y = _svg_point(art["matrix"], symbol.ports[port_name].x, symbol.ports[port_name].y)
        assert abs(x - port.center.x) <= 0.15 * span and abs(-y - port.center.y) <= 0.15 * span, port_name


def test_the_fit_finds_a_symbol_drawn_at_another_angle():
    """The 1D plate beamsplitter is drawn as the 2D part at 45 degrees."""

    splitter = optodraw.BeamSplitter()
    fit = fit_art(splitter, lookup(splitter))
    assert fit is not None and fit.residual < 0.15 and fit.turn % 90 == 45


@pytest.mark.parametrize("interaction_length", [7.0, 11.0, 20.0])
def test_modulator_art_keeps_both_body_ports_aligned(interaction_length):
    part = optodraw.AOM(interaction_length=interaction_length)
    art, symbol = art_2d(part), lookup(part)
    for name, port in part.ports().items():
        mark = symbol.ports[name]
        x, y = _svg_point(art["matrix"], mark.x, mark.y)
        assert (x, -y) == pytest.approx((port.center.x, port.center.y))


def test_the_2d_svg_paints_the_art_instead_of_the_geometry():
    scene = optodraw.Scene(width=60, height=40, platform="free_space")
    scene.add(optodraw.Lens(label=""))
    svg = scene.render_svg().as_svg()
    assert 'data-art="lens"' in svg


def test_an_on_chip_part_keeps_its_physical_geometry():
    """On-chip parts are drawn from their real layout (spec: they take the 1D colors, not the 1D art)."""

    assert art_2d(optodraw.MZM()) is None
    scene = optodraw.Scene(width=200, height=80, platform="on_chip")
    scene.add(optodraw.MZM(label=""))
    assert "data-art" not in scene.render_svg().as_svg()


def test_a_line_shrinks_with_a_small_part_and_is_capped_in_a_large_one():
    """Line weight in scene units: the native weight times the part's scale, at most times LINE_SCALE.

    A small part keeps the proportions of its drawing (a thin plate stays glass,
    not a black bar); a large part does not get heavy lines.
    """

    import re

    from optodraw.symbols.art import LINE_SCALE

    for name in ["Lens", "Mirror", "PBS", "BeamSplitter", "Objective", "Polarizer"]:
        part = build_component(name)
        art = art_2d(part)
        scale = (art["matrix"][0] ** 2 + art["matrix"][1] ** 2) ** 0.5
        native = sorted({round(float(v), 3) for v in re.findall(r"stroke-width='([\d.]+)'", lookup(part).svg2d)})
        drawn = sorted({round(float(v) * scale, 3) for v in re.findall(r"stroke-width='([\d.]+)'", art["svg"])})
        expected = sorted({round(w * min(scale, LINE_SCALE), 3) for w in native})
        assert [round(d, 2) for d in drawn] == [round(e, 2) for e in expected], name


def test_the_tikz_pic_scales_its_lines_the_same_way():
    from optodraw.symbols.art import LINE_SCALE, tikz_pic

    art = art_2d(optodraw.Objective())
    line = tikz_pic(art)
    assert f"\\def\\odls{{{min(art['pic']['scale'], LINE_SCALE):.4g}}}" in line


def test_the_tikz_export_draws_the_art_as_a_pic_of_the_library():
    scene = optodraw.Scene(width=60, height=40, platform="free_space")
    scene.add(optodraw.Lens(label=""))
    tikz = scene.render_tikz()
    assert "pics/od lens/.style" in tikz and "{od lens=" in tikz and "x=1cm" in tikz


def test_the_tikz_art_lands_where_the_part_is(tmp_path):
    """Compiled, a lens at (48, -20) in a 60 unit scene stays inside a page of about that size."""

    import re
    import subprocess

    from optodraw.symbols import build

    if not build.latex_available():
        pytest.skip("needs latex and dvisvgm")
    scene = optodraw.Scene(width=120, height=60, platform="free_space")
    scene.add(optodraw.Lens(center=(48, -20), label=""))
    figure = scene.render_tikz().replace("\\end{tikzpicture}", "\\path (-60,-30) (60,30);\\end{tikzpicture}")  # the scene frame
    (tmp_path / "f.tex").write_text("\\documentclass[dvisvgm]{standalone}\n\\usepackage{tikz}\n\\begin{document}\n"
                                    + figure + "\n\\end{document}\n", encoding="utf-8")
    subprocess.run(["latex", "-interaction=nonstopmode", "-halt-on-error", "f.tex"], cwd=tmp_path,
                   capture_output=True, timeout=120, check=True)
    subprocess.run(["dvisvgm", "--no-fonts", "--bbox=papersize", "f.dvi", "-o", "f.svg"], cwd=tmp_path,
                   capture_output=True, timeout=120, check=True)
    width, height = map(float, re.search(r"viewBox=.-?[\d.]+ -?[\d.]+ ([\d.]+) ([\d.]+)", (tmp_path / "f.svg").read_text()).groups())
    assert width < 125 and height < 65                        # the lens is inside the 120 x 60 frame


# ---------------------------------------------------------------- stage 1: free-space optics
CARRIERS = {"OpticalTable", "Breadboard", "Baseplate"}    # the plates a bench stands on keep their own drawing
TWO_MOUNTS = {"Periscope", "Telescope", "FourFSystem"}   # drawn as their two parts from above, at their true spacing


def _optics():
    from optodraw.registry import component_registry

    return sorted(name for name, spec in component_registry().items() if spec.category == "optics")


@pytest.mark.parametrize("name", [name for name in _optics() if name not in CARRIERS | TWO_MOUNTS])
def test_every_free_space_part_is_painted_with_its_symbol(name):
    art = art_2d(build_component(name))
    assert art is not None and art["residual"] < 0.15, name


@pytest.mark.parametrize("name", sorted(CARRIERS | TWO_MOUNTS))
def test_a_carrier_keeps_its_plate(name):
    assert art_2d(build_component(name)) is None


@pytest.mark.parametrize("name", ["Polarizer", "HalfWavePlate", "QuarterWavePlate", "Grating", "OpticalChopper", "Pinhole"])
def test_a_thin_part_is_as_tall_as_its_aperture(name):
    """A thin plate's 1D symbol carries its output at the end of a short beam; the 2D art still fills the aperture."""

    from optodraw.layout import estimate_component_bounds

    part = build_component(name)
    art, symbol = art_2d(part), lookup(part)
    x0, y0, x1, y1 = estimate_component_bounds(part)
    corners = [_svg_point(art["matrix"], x, y) for x, y in ((0, 0), (symbol.width, 0), (0, symbol.height), (symbol.width, symbol.height))]
    tall = max(y for _, y in corners) - min(y for _, y in corners)
    assert 0.6 * (y1 - y0) <= tall <= 1.4 * (y1 - y0), (name, tall, y1 - y0)


@pytest.mark.parametrize("name", ["OpticalPost", "PlatformMount"])
def test_a_mount_is_seen_from_above_in_2d(name):
    """The 1D symbol of a post or a platform is a side view; the 2D art is the top view of the same pic."""

    art = art_2d(build_component(name))
    assert art is not None and art["params"].get("view") == "top", name


@pytest.mark.parametrize("preset", ["free_space_breadboard", "ftir_setup", "confocal_pl_setup", "raman_setup", "qwp_circular_lab"])
def test_a_free_space_preset_paints_every_optic(preset):
    from optodraw import presets

    scene = getattr(presets, preset)()
    optics = [node for node in scene.walk() if getattr(node, "component_type", "") in set(_optics()) - CARRIERS]
    assert scene.render_svg().as_svg().count("data-art=") >= len(optics) > 0


@pytest.mark.parametrize("name", ["RotationStage", "SMU", "Lens"])
def test_the_bounds_of_a_painted_part_hold_its_drawing(name):
    """Previews, frames and labels use the bounds: a drawing larger than the old geometry must not be cut off."""

    from optodraw.layout import estimate_component_bounds

    part = build_component(name)
    art, symbol = art_2d(part), lookup(part)
    x0, y0, x1, y1 = estimate_component_bounds(part)
    for x, y in ((0, 0), (symbol.width, 0), (0, symbol.height), (symbol.width, symbol.height)):
        sx, sy = _svg_point(art["matrix"], x, y)
        assert x0 - 1e-6 <= sx <= x1 + 1e-6 and y0 - 1e-6 <= -sy <= y1 + 1e-6, name


@pytest.mark.parametrize("name", sorted(CARRIERS))
def test_a_carrier_is_a_light_plate_in_2d_and_keeps_its_metal_in_3d(name):
    """Black line art needs a light ground; the 3D view keeps the real colour of the metal."""

    def light(value: str) -> float:
        r, g, b = (int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    part = build_component(name)
    plate = next(child for child in part.geometry_2d()["children"] if child.get("fill", "none") not in ("none", None))
    assert light(plate["fill"]) > 0.85 and light(part.color) < 0.85


# ---------------------------------------------------------------- stage 2: instruments, sources, detectors, samples
STAGE_2_CATEGORIES = {"instruments", "devices", "samples", "misc"}


def _stage_2():
    from optodraw.registry import component_registry

    return sorted(name for name, spec in component_registry().items()
                  if spec.category in STAGE_2_CATEGORIES and name != "Grid")


@pytest.mark.parametrize("name", _stage_2())
def test_every_instrument_source_detector_and_sample_is_painted(name):
    art = art_2d(build_component(name))
    assert art is not None and art["residual"] < 0.15, name


def test_a_cryostat_is_seen_from_above_in_2d():
    assert art_2d(optodraw.Cryostat())["params"].get("view") == "top"


def test_a_sample_in_a_cryostat_shows_the_cryostat():
    plain, cold = optodraw.Sample(), optodraw.Sample(in_cryostat=True)
    assert art_2d(cold)["params"].get("kind") == "cryostat" and art_2d(plain)["params"].get("kind") is None
    assert lookup(cold).source == "prebuilt" and lookup(cold).params == {"kind": "cryostat"}


@pytest.mark.parametrize("preset", ["free_space_breadboard", "ftir_setup", "confocal_pl_setup", "raman_setup", "qwp_circular_lab"])
def test_every_part_of_a_free_space_preset_is_painted(preset):
    from optodraw import presets

    scene = getattr(presets, preset)()
    painted = set(_optics()) - CARRIERS | set(_stage_2())
    parts = [node for node in scene.walk() if getattr(node, "component_type", "") in painted]
    assert scene.render_svg().as_svg().count("data-art=") == len(parts) > 0


def test_a_laser_head_is_as_long_as_the_laser():
    """A laser is a long box in 2D; its drawing from above must fill that length, not shrink to the height."""

    from optodraw.layout import estimate_component_bounds

    laser = optodraw.Laser()
    art, symbol = art_2d(laser), lookup(laser, ("lasersource", {"view": "top"}))
    assert art["params"].get("view") == "top"
    corners = [_svg_point(art["matrix"], x, y) for x, y in ((0, 0), (symbol.width, 0), (0, symbol.height), (symbol.width, symbol.height))]
    long = max(x for x, _ in corners) - min(x for x, _ in corners)
    x0, _, x1, _ = estimate_component_bounds(laser)
    assert long >= 0.8 * (x1 - x0)


def test_a_photodiode_on_a_bench_is_a_housing_seen_from_above():
    """The 1D photodiode is a circuit symbol; on a bench it is a housing with a window toward the beam."""

    from optodraw.layout import estimate_component_bounds

    diode = optodraw.Photodiode()
    art, symbol = art_2d(diode), lookup(diode, ("detector", {"view": "top"}))
    assert art["params"].get("view") == "top"
    corners = [_svg_point(art["matrix"], x, y) for x, y in ((0, 0), (symbol.width, 0), (0, symbol.height), (symbol.width, symbol.height))]
    x0, y0, x1, y1 = estimate_component_bounds(diode)
    assert max(y for _, y in corners) - min(y for _, y in corners) >= 0.7 * (y1 - y0)


# ---------------------------------------------------------------- the 2D look: color and depth
STAGE_3_BLOCKS = ["ADCBlock", "DAC", "TIABlock", "RFDriver", "EIC", "Microcontroller",
                  "CoherentReceiver", "ReceiverMacro", "TransmitterMacro",
                  "ElectricalIOBank", "BalancedPhotodetector", "MEMSActuator", "FiberArray", "SMAConnector"]
# The circuit set is IEC line art: a body (resistor, op amp, bias tee, mixer) is painted, plates, turns and ground
# bars stay lines, so the set is not in the depth test.
STAGE_3_CIRCUIT = ["Resistor", "Capacitor", "Inductor", "OpAmp", "Ground", "BiasTee", "RFMixer", "Amplifier",
                   "RFFilter", "PIDController", "SignalSource", "SummingJunction", "RFSplitter", "RFCoupler",
                   "RFPhaseShifter"]
# Physical layout keeps its true geometry (and takes the 1D colours with the on-chip parts, stage 4); an
# annotation arrow keeps its own ends and colour.
STAGE_3_PHYSICAL = ["ElectricalPad", "GSGProbePad", "HeaterPad", "MetalRoute", "SignalArrow", "PCB"]


def _painted_parts():
    return [name for name in _optics() if name not in CARRIERS | TWO_MOUNTS] + _stage_2() + STAGE_3_BLOCKS


def test_every_symbol_has_a_painted_2d_look_with_the_same_frame():
    """The build compiles each symbol twice: line art for 1D, paint for 2D, in one frame so the ports stay put."""

    import re

    symbol = lookup(optodraw.Oscilloscope())
    assert symbol.svg2d and symbol.svg2d != symbol.svg
    frame = [float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', symbol.svg2d).groups()]
    assert abs(frame[0] - symbol.width) < 1e-3 and abs(frame[1] - symbol.height) < 1e-3


@pytest.mark.parametrize("name", _painted_parts())
def test_a_part_in_2d_has_depth(name):
    """Gradients give each painted part its depth (glass, metal, cases, screens); the 1D symbol has none."""

    part = build_component(name)
    assert "Gradient" in art_2d(part)["svg"], name
    assert "Gradient" not in lookup(part).svg, name


def test_an_instrument_in_2d_has_a_slate_screen_hairline_edges_and_a_soft_shadow():
    """Modern product art: a slate screen, hairline edges in a tint of the fill (no black), a soft shadow."""

    import re

    part = optodraw.Oscilloscope()
    svg = lookup(part).svg2d.lower()
    assert "#334155" in svg and "#0f172a" in svg              # the screen gradient: slate 700 to 900
    assert "fill-opacity" in svg                              # the soft cast shadow
    assert max(float(v) for v in re.findall(r"stroke-width='([\d.]+)'", svg)) < 0.8      # no heavy line (the trace is 0.7)
    assert "stroke='#000'" not in svg                         # no black edge


def test_the_tikz_export_paints_the_2d_look():
    from optodraw.symbols.art import tikz_pic

    assert "\\odtwodlook" in tikz_pic(art_2d(optodraw.Oscilloscope()))


def test_a_turned_part_is_turned_in_the_tikz_export(tmp_path):
    """A pic ignores the rotation of its scope unless it transforms its shape: a mirror at 90 degrees lies flat."""

    import re
    import subprocess

    from optodraw.symbols import build

    if not build.latex_available():
        pytest.skip("needs latex and dvisvgm")
    scene = optodraw.Scene(width=60, height=60, platform="free_space")
    scene.add(optodraw.Mirror(center=(0, 0), angle=90, label=""))
    figure = scene.render_tikz().replace("\\begin{pgfinterruptboundingbox}", "").replace("\\end{pgfinterruptboundingbox}", "")
    figure = re.sub(r"\\path \([-\d.,]+\) rectangle \([-\d.,]+\);", "", figure)      # measure the drawing, not its box
    (tmp_path / "m.tex").write_text("\\documentclass[dvisvgm]{standalone}\n\\usepackage{tikz}\n\\begin{document}\n"
                                    + figure + "\n\\end{document}\n", encoding="utf-8")
    subprocess.run(["latex", "-interaction=nonstopmode", "-halt-on-error", "m.tex"], cwd=tmp_path,
                   capture_output=True, timeout=120, check=True)
    subprocess.run(["dvisvgm", "--no-fonts", "--bbox=papersize", "m.dvi", "-o", "m.svg"], cwd=tmp_path,
                   capture_output=True, timeout=120, check=True)
    width, height = map(float, re.search(r"viewBox=.-?[\d.]+ -?[\d.]+ ([\d.]+) ([\d.]+)", (tmp_path / "m.svg").read_text()).groups())
    assert width > height                                     # the mirror lies across the page


@pytest.mark.parametrize("name", ["BeamSplitter", "PBS", "NonPolarizingBeamSplitter"])
def test_a_splitter_is_drawn_on_the_point_where_its_beams_meet(name):
    """The confocal and FTIR beamsplitters sat away from their ports: the plate must sit where the beams cross."""

    part = build_component(name)
    art, symbol = art_2d(part), lookup(part)
    x, y = _svg_point(art["matrix"], *symbol.hub)
    assert abs(x) < 0.1 and abs(-y) < 0.1, name               # the beams cross at the part's own origin


# ---------------------------------------------------------------- stage 3: electronics and packaging
def test_stage_3_covers_the_whole_family():
    from optodraw.registry import component_registry

    family = {name for name, spec in component_registry().items() if spec.category == "electronics"}
    assert family == set(STAGE_3_BLOCKS) | set(STAGE_3_PHYSICAL) | set(STAGE_3_CIRCUIT)


@pytest.mark.parametrize("name", STAGE_3_BLOCKS + STAGE_3_CIRCUIT)
def test_every_electronic_block_is_painted(name):
    art = art_2d(build_component(name))
    assert art is not None and art["residual"] < 0.15, name


@pytest.mark.parametrize("name", STAGE_3_PHYSICAL)
def test_physical_layout_keeps_its_true_geometry(name):
    assert art_2d(build_component(name)) is None, name


def test_digital_and_analog_marks_have_their_own_colours_in_2d():
    svg = lookup(optodraw.DAC()).svg2d.lower()
    assert "#6366f1" in svg and "#14b8a6" in svg              # steps indigo (digital), wave teal (analog)


@pytest.mark.parametrize("name", ["TIA", "ADC", "DACDriver"])
def test_an_on_chip_circuit_block_is_painted_like_its_electronic_twin(name):
    """A TIA, ADC or DAC driver on a chip is a block, not layout: the recipes drew it as a flat grey box."""

    art = art_2d(build_component(name))
    assert art is not None and art["residual"] < 0.15, name
    assert "Gradient" in art["svg"], name


def test_the_balanced_detector_in_2d_has_its_ports_where_the_part_has_them():
    """The 1D symbol has long inputs and a short output; the part the reverse (residual 0.183 before)."""

    art = art_2d(optodraw.BalancedPhotodetector())
    assert art["params"].get("view") == "top" and art["residual"] < 0.02


def test_the_coherent_receiver_in_2d_is_as_wide_as_the_part():
    art = art_2d(optodraw.CoherentReceiver())
    assert art["params"].get("view") == "top" and art["residual"] < 0.02


def test_a_signal_arrow_keeps_its_own_colour_and_ends():
    """The fixed grey arrow art replaced the arrow: its colour, start and end were lost."""

    import optodraw
    from optodraw.symbols.art import art_2d

    arrow = optodraw.SignalArrow((-20, 0), (20, 0), color="#e0302a", label="pump")
    assert art_2d(arrow) is None
    scene = optodraw.Scene(width=80, height=40)
    scene.add(arrow)
    svg = scene.render_svg().as_svg()
    assert "#e0302a" in svg


def _drawing_order(monkeypatch, scene):
    from optodraw.renderers.svg_renderer import SvgRenderer

    order = []
    original = SvgRenderer._render_node

    def spy(self, parent, node):
        order.append(node)
        return original(self, parent, node)

    monkeypatch.setattr(SvgRenderer, "_render_node", spy)
    scene.render_svg(view="2d")
    return order


def test_the_light_runs_under_the_parts_it_meets(monkeypatch):
    """Ni's FTIR: the wide beam drawn over G1 and G2 hid the plates, and the figure no longer showed which
    part takes the light."""

    from optodraw import Beam
    from optodraw.literature import ni2020_ftir

    scene = ni2020_ftir.build()
    order = _drawing_order(monkeypatch, scene)
    beams = [k for k, node in enumerate(order) if isinstance(node, Beam)]
    parts = {getattr(node, "label", ""): k for k, node in enumerate(order) if not isinstance(node, Beam)}
    assert beams and max(beams) < min(parts["G1"], parts["G2"], parts["L"], parts["M1"])


def test_the_light_runs_over_a_cryostat_it_enters(monkeypatch):
    """A cryostat is drawn as a cutaway: the beam to the sample shows inside it, so it lies under the light."""

    from optodraw import Beam, Cryostat, Laser, Sample, Scene

    scene = Scene(width=120, height=80)
    laser = scene.add(Laser(center=(-40, 0)))
    cryostat = scene.add(Cryostat(center=(20, 0), angle=180))
    sample = scene.add(Sample(center=(20, 30), angle=180, in_cryostat=True))
    scene.add(Beam((laser, "out"), (cryostat, "sample")))
    order = _drawing_order(monkeypatch, scene)
    beam = next(k for k, node in enumerate(order) if isinstance(node, Beam))
    assert order.index(cryostat) < beam and order.index(sample) < beam and beam < order.index(laser)


def test_a_focusing_beam_runs_under_the_lens_too(monkeypatch):
    from optodraw import FocusingBeam, Lens, Scene

    scene = Scene(width=80, height=40)
    lens = scene.add(Lens(center=(10, 0)))
    cone = scene.add(FocusingBeam((-20, 0), (30, 0), width1=6.0, width2=0.0))       # added last, drawn first
    order = _drawing_order(monkeypatch, scene)
    assert order.index(cone) < order.index(lens)
