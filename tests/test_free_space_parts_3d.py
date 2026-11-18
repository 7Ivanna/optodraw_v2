"""The 3D shape of free-space parts: each one reads as the real part on a bench.

The local origin of a free-space part is the beam axis; x runs along the beam, y up, z across it.
"""

from __future__ import annotations

import math

import pytest

import optodraw


def _solids(node):
    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _solids(child)
    else:
        yield node


def _ring(solid):
    """(inner radius, outer radius, width along the beam) of a ring made by ``_ring_along_x``."""

    radii = [p[0] for p in solid["points"]]
    widths = [p[1] for p in solid["points"]]
    return min(radii), max(radii), max(widths) - min(widths)


def _role(part, role):
    return [s for s in _solids(part.geometry_3d()) if s.get("role") == role]


@pytest.mark.parametrize("part, thickest", [(optodraw.ApertureStop(), 0.05), (optodraw.Pinhole(), 0.02)])
def test_an_aperture_is_a_thin_plate_with_an_open_hole_in_a_ring_holder(part, thickest):
    """The stop was a thick black torus: it read as a ring, not as a plate with a hole."""

    od = part.outer_diameter
    plates = [_ring(s) for s in _role(part, "plate")]
    assert plates and all(width <= thickest * od for _, _, width in plates)
    hole = min(inner for inner, _, _ in plates)
    assert hole == pytest.approx(max(part.aperture_diameter / 2.0, od * 0.0125))
    holder = [_ring(s) for s in _role(part, "holder")]
    assert holder and holder[0][1] == pytest.approx(od / 2.0) and holder[0][0] > hole
    assert not [s for s in _solids(part.geometry_3d()) if s.get("shape") == "torus" and s["tube"] > 0.02 * od]


def _x_extent(solid):
    if solid["shape"] == "box":
        return solid["width"]
    if solid["shape"] == "cylinder":
        along_x = solid.get("rotation", [0, 0, 0])[2]
        return solid["height"] if math.isclose(abs(along_x), math.pi / 2.0) else 2.0 * solid["radius"]
    raise AssertionError(solid["shape"])


def test_a_slit_is_a_plate_across_the_beam_with_a_vertical_opening_and_a_micrometer():
    """The slit was a box ten units long along the beam, with a horizontal gap."""

    slit = optodraw.SpectrometerSlit()
    bw = slit.body_width
    body = _role(slit, "body") + _role(slit, "jaw")
    assert body and all(_x_extent(s) <= 0.2 * bw for s in body)
    jaws = _role(slit, "jaw")
    assert len(jaws) == 2
    left, right = sorted(jaws, key=lambda s: s["position"][2])
    gap = (right["position"][2] - right["depth"] / 2.0) - (left["position"][2] + left["depth"] / 2.0)
    assert gap > 0 and left["position"][1] == right["position"][1] == 0.0       # side by side: a vertical slit
    assert left["height"] >= 0.6 * slit.slit_height
    screw = _role(slit, "micrometer")
    assert screw and all(math.isclose(s["rotation"][0], math.pi / 2.0) for s in screw)   # along z, to a jaw
    assert min(abs(s["position"][2]) for s in screw) > bw / 2.0                         # outside the plate


@pytest.mark.parametrize("part", [optodraw.Prism(), optodraw.RightAnglePrism(), optodraw.Pentaprism()])
def test_the_beam_runs_through_the_middle_of_a_prism_on_its_prism_table(part):
    """The glass stood on the beam axis, all above it: the beam grazed its bottom face."""

    glass = _role(part, "glass")
    assert len(glass) == 1 and glass[0]["shape"] == "extruded_polygon" and glass[0].get("edges")
    bottom = glass[0]["position"][1]
    top = bottom + glass[0]["height"]
    assert bottom == pytest.approx(-top)
    table = _role(part, "table")
    assert table and table[0]["position"][1] + table[0]["height"] / 2.0 == pytest.approx(bottom)


def test_a_chopper_wheel_puts_its_slots_on_the_beam_and_its_hub_below_it():
    """The hub sat on the beam axis, so the beam ran into the motor, and the blades were loose boxes."""

    chopper = optodraw.OpticalChopper()
    r = chopper.wheel_diameter / 2.0
    hub = _role(chopper, "hub")
    assert hub and hub[0]["position"][1] < -0.5 * r
    beam_radius = -hub[0]["position"][1]
    teeth = _role(chopper, "tooth")
    assert len(teeth) == chopper.blades and all(t["shape"] == "extruded_polygon" for t in teeth)
    radii = [math.hypot(u, v) for t in teeth for u, v in t["points"]]
    assert min(radii) < beam_radius < max(radii) <= r + 1e-9               # the beam crosses the slotted ring


def _profile_to_x(solid):
    """(radius, world x) of each point of a lathe ring along x (``_ring_along_x`` turns profile y to -x)."""

    return [(p[0], solid["position"][0] - p[1]) for p in solid["points"]]


def test_a_beam_dump_opens_its_cone_toward_the_beam_and_has_round_fins():
    """The cone opened to the back, inside the body, and the fins were boxes on top."""

    dump = optodraw.BeamDump()
    a = dump.aperture
    body = _role(dump, "body")
    assert len(body) == 1
    points = _profile_to_x(body[0])
    apex = min(points, key=lambda p: p[0])
    front = min(x for _, x in points)
    mouth = min(r for r, x in points if math.isclose(x, front))
    assert apex[1] > 0 > front and mouth >= 0.3 * a                         # wide at the front, apex at the back
    assert len(_role(dump, "fin")) >= 3
    assert not [s for s in _solids(dump.geometry_3d()) if s["shape"] == "box" and s["position"][1] > 0]


def _normal(rotation):
    """The axis (local y) of a cylinder after its Euler rotation (three.js XYZ order)."""

    rx, ry, rz = rotation
    x, y, z = -math.sin(rz), math.cos(rz), 0.0                                  # about z
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)   # about y
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)    # about x
    return x, y, z


def test_a_brewster_window_sits_whole_in_its_tilted_holder_at_the_brewster_angle():
    """The plate was larger than the bore and stuck out of a fat ring, like a blade through a tyre."""

    window = optodraw.BrewsterWindow()
    glass = _role(window, "glass")[0]
    holder = _role(window, "holder")[0]
    nx, ny, nz = _normal(glass["rotation"])
    assert math.degrees(math.acos(abs(nx))) == pytest.approx(window.window_angle_deg)
    assert abs(ny) < 1e-9                                                     # tilted in the table plane, as in 2D
    assert glass["radius"] <= _ring(holder)[0] and holder["rotation"] == glass["rotation"]


@pytest.mark.parametrize("part", [optodraw.AsphericLens(), optodraw.CylindricalLens(), optodraw.WedgePlate()])
def test_a_lens_or_plate_on_a_post_sits_in_a_holder(part):
    """The glass stood bare on the post."""

    assert _role(part, "holder")


def test_a_4f_relay_is_a_cage_with_its_fourier_mask_one_focal_length_behind_the_first_lens():
    """The relay was a rail on one post with loose lenses and floating planes, its mask at the midpoint."""

    relay = optodraw.FourFSystem(focal_length_1=20, focal_length_2=30)
    lenses = sorted(s["position"][0] for s in _role(relay, "lens"))
    mask = _role(relay, "mask")
    assert len(lenses) == 2 and len(mask) == 1 and len(_role(relay, "rod")) == 4
    x = mask[0]["position"][0]
    assert lenses[0] + relay.system_length / 2.0 == pytest.approx(20)          # object plane to lens 1: f1
    assert x - lenses[0] == pytest.approx(20) and lenses[1] - x == pytest.approx(30)
    assert not [s for s in _solids(relay.geometry_3d()) if s["shape"] == "box" and s["material"].get("opacity", 1) < 0.5]
    art = {round(c["pic"]["origin"][0], 6) for c in relay.geometry_2d()["children"] if c["type"] == "art"}
    assert art == {round(v, 6) for v in lenses}                                  # 2D lenses where the 3D ones are


def _boxes(node):
    """(x0, x1, y0, y1, z0, z1) of every box and upright cylinder that is not turned."""

    for s in _solids(node):
        if s["shape"] not in ("box", "cylinder") or any(s.get("rotation") or []):
            continue
        x, y, z = s.get("position") or [0.0, 0.0, 0.0]
        hx, hz = (s["width"] / 2, s["depth"] / 2) if s["shape"] == "box" else (s["radius"], s["radius"])
        yield (x - hx, x + hx, y - s["height"] / 2, y + s["height"] / 2, z - hz, z + hz)


@pytest.mark.parametrize("name", ["Oscilloscope", "OSA", "PlatformMount"])
def test_nothing_on_a_part_hangs_in_the_air(name):
    """An instrument handle hung half a unit above its case; the platform mount's adjusters ended in the air."""

    from optodraw.registry import build_component

    boxes = list(_boxes(build_component(name).geometry_3d()))
    floor = min(b[2] for b in boxes)
    for b in boxes:
        held = b[2] == pytest.approx(floor) or any(
            o is not b and o[2] - 1e-6 <= b[2] <= o[3] + 1e-6 and o[0] <= b[1] + 1e-6 and b[0] <= o[1] + 1e-6
            and o[4] <= b[5] + 1e-6 and b[4] <= o[5] + 1e-6
            for o in boxes)
        assert held, f"a solid from y = {b[2]:.2f} to {b[3]:.2f} floats"


def test_a_fibre_port_holds_its_connector_in_a_ring_holder_between_the_ferrule_and_the_nut():
    """The port was a connector on a big loose silver disc behind it."""

    port = optodraw.FiberPort()
    cd = port.cladding_diameter
    holder = _role(port, "holder")
    ferrule = _role(port, "ferrule")[0]
    nut = _role(port, "nut")[0]
    assert holder and ferrule["position"][0] < holder[0]["position"][0] < nut["position"][0]
    assert _ring(holder[0])[1] <= cd
    silver = [s for s in _solids(port.geometry_3d()) if s["shape"] == "cylinder" and s["material"].get("color") == "#c6cbd1"]
    assert all(s["radius"] <= 0.6 * cd for s in silver)


def test_a_kinematic_mount_has_thin_plates_and_two_adjusters_in_an_l_with_the_pivot():
    """The plates were bricks and three big knobs stood in a triangle."""

    mount = optodraw.KinematicMount()
    w = mount.base_width
    plates = _role(mount, "plate")
    assert len(plates) == 2 and all(p["height"] <= 0.22 * w for p in plates)      # an extruded plate: its height is its thickness
    knobs = _role(mount, "knob")
    pivot = _role(mount, "pivot")
    assert len(knobs) == 2 and len(pivot) == 1 and all(k["radius"] <= 0.08 * w for k in knobs)
    (_, py, pz), corners = pivot[0]["position"], [k["position"][1:] for k in knobs]
    assert sorted([abs(y - py) < 1e-9 for y, _ in corners]) == [False, True]       # one knob beside the pivot,
    assert sorted([abs(z - pz) < 1e-9 for _, z in corners]) == [False, True]       # one knob below it: an L


def test_an_upright_sample_is_a_chip_on_a_thin_holder_plate():
    """A long copper block stuck out behind the chip and a slab sat under it."""

    sample = optodraw.Sample()
    a = sample.aperture
    boxes = list(_boxes(sample.geometry_3d()))
    assert max(b[1] for b in boxes) <= 0.1 * a and min(b[0] for b in boxes) >= -0.1 * a


def test_a_grating_has_fine_rulings_in_a_holder():
    """Ten bright bars with gaps read as a barcode, on a bare post."""

    grating = optodraw.Grating()
    grooves = _role(grating, "groove")
    assert len(grooves) >= 30 and all(g["height"] <= grating.aperture / 40.0 for g in grooves)
    assert _role(grating, "holder")


def _inside(point, polygon):
    """Whether a point lies inside a polygon (even-odd rule)."""

    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


KINEMATIC = [optodraw.Mirror(), optodraw.ConcaveMirror(), optodraw.BiconvexMirror(), optodraw.BeamSplitter(),
             optodraw.PartialMirror(), optodraw.DichroicMirror(), optodraw.KinematicMount()]


@pytest.mark.parametrize("part", KINEMATIC, ids=lambda p: p.component_type)
def test_a_kinematic_mount_carries_its_knobs_through_an_l_back_plate(part):
    """The knobs hung in space behind a ring, inside its bore. On a real mount (KM100, KM200) a square
    front plate holds the optic and an L-shaped back plate runs along one side and the bottom; the two knobs
    thread through the free ends of the L and the pivot sits at its corner."""

    front, back = sorted(_role(part, "plate"), key=lambda p: p["position"][0])
    assert front.get("holes") and not back.get("holes") and len(back["points"]) == 6
    l_back_face = back["position"][0]                          # a plate extrudes toward -x from its position
    knobs, pivot = _role(part, "knob"), _role(part, "pivot")
    assert len(knobs) == 2 and len(pivot) == 1
    # world (y, z) of each knob and the pivot is the plate's (u, v) = (y, -z)
    assert all(_inside((k["position"][1], -k["position"][2]), back["points"]) for k in knobs + pivot)
    assert all(k["position"][0] - k["height"] / 2.0 > l_back_face for k in knobs)
    screws = _role(part, "screw")
    assert len(screws) == 2 and all(s["position"][0] - s["height"] / 2.0 == pytest.approx(l_back_face) for s in screws)
    assert front["position"][0] < pivot[0]["position"][0] < back["position"][0] - back["height"]


from optodraw.check import solid_boxes as _world_boxes  # noqa: E402


def _free_space_parts():
    from optodraw.registry import component_registry

    return sorted(name for name, spec in component_registry().items()
                  if spec.category in ("optics", "devices", "instruments", "samples"))


def test_the_slit_post_stands_under_its_stem_not_under_the_middle_of_its_bounds():
    """The micrometer on one side moved the middle of the slit's bounds, and the post with it."""

    from test_free_space_3d import _probe_viewer

    slit = optodraw.SpectrometerSlit()
    stem = slit.geometry_3d()["post_at"]
    scene = optodraw.Scene(width=60, height=40, platform="free_space")
    scene.add(slit)
    posts = _probe_viewer(scene, """
      const out = [];
      V.scene.traverse(o => {
        const p = o.isMesh && o.geometry && o.geometry.type === 'CylinderGeometry' ? o.geometry.parameters : null;
        if (p && o.material && o.material.color && o.material.color.getHex() === 0xc4c9cf && Math.abs(p.radiusTop - 2.5) < 1e-6) {
          const w = new V.THREE.Vector3(); o.getWorldPosition(w); out.push([w.x, w.z]);
        }
      });
      return out;
    """)
    assert len(posts) == 1 and posts[0] == pytest.approx([stem[0], stem[2]], abs=1e-6)


def test_a_vacuum_chamber_stands_on_its_feet_on_the_table():
    """Its post stopped in the air between its two feet."""

    from optodraw.components.optics.optomech import BEAM_HEIGHT

    chamber = optodraw.VacuumChamber()
    assert chamber.base_mount == "none"
    lowest = min(b[1][0] for _, b in _world_boxes(chamber.geometry_3d()))
    assert lowest == pytest.approx(-BEAM_HEIGHT)


@pytest.mark.parametrize("hole", [1.0, 4.0, 8.0, 9.5, 14.0])
def test_a_stop_keeps_a_plate_round_any_hole(hole):
    """The hole follows ``aperture_diameter``; with a large hole the machined rim grew past the plate and
    turned the plate ring inside out."""

    stop = optodraw.ApertureStop(aperture_diameter=hole, outer_diameter=12.0)
    rings = [_ring(s) for s in _solids(stop.geometry_3d()) if s["shape"] == "lathe_profile"]
    assert all(inner < outer for inner, outer, _ in rings)
    plate = [_ring(s) for s in _role(stop, "plate")]
    assert min(i for i, _, _ in plate) == pytest.approx(min(hole / 2.0, 12.0 * 0.4 * 0.9))


@pytest.mark.parametrize("kwargs", [{"rise": 20.0}, {"rise": -20.0}, {"rise": 20.0, "output_angle_deg": 90.0}])
def test_a_periscope_mirror_sits_on_a_kinematic_plate_tilted_by_two_knobs_in_an_l(kwargs):
    """The two knobs stood side by side on the cut back face, in a line: with the pivot they cannot give two
    independent tilts, and they pushed on the solid block."""

    scope = optodraw.Periscope(**kwargs)
    children = scope.geometry_3d()["children"]
    for which in ("entry", "exit"):
        assert [c for c in children if c.get("role") == "plate" and c.get("mirror") == which]
        knobs = [c for c in children if c.get("role") == "knob" and c.get("mirror") == which]
        assert len(knobs) == 2 and all(k["radius"] <= 0.1 * scope.aperture for k in knobs)
        point, a, b = scope._fold(which)
        along = [(a[i] - b[i]) / math.sqrt(2.0) for i in range(3)]               # across the cut face
        w = scope._cross(a, b)                                                   # along the block's length
        (e1, w1), (e2, w2) = [(sum((k["position"][i] - point[i]) * along[i] for i in range(3)),
                               sum((k["position"][i] - point[i]) * w[i] for i in range(3))) for k in knobs]
        assert abs(e1 - e2) > 0.1 * scope.aperture and abs(w1 - w2) > 0.3 * scope.aperture   # an L, not a line


def _extent(part, axis):
    boxes = [b for _, b in _world_boxes(part.geometry_3d())]
    return min(b[axis][0] for b in boxes), max(b[axis][1] for b in boxes)


def test_a_power_meter_is_a_slim_round_head_with_a_viewing_target():
    """It was a black box. A photodiode power head (Thorlabs S120C) is a puck 30.5 mm across and 12.7 mm
    thick, with a salmon annular viewing target round a 9.5 mm aperture and an outer SM1 thread."""

    head = optodraw.PowerMeter()
    body = _role(head, "head")
    assert len(body) == 1 and body[0]["shape"] == "cylinder"
    assert body[0]["height"] / (2.0 * body[0]["radius"]) == pytest.approx(12.7 / 30.5, rel=0.02)
    target = [_ring(s) for s in _role(head, "target")]
    aperture = [s for s in _role(head, "aperture")]
    assert target and aperture and aperture[0]["radius"] / body[0]["radius"] == pytest.approx(9.5 / 30.5, rel=0.05)
    assert _role(head, "thread")


def test_a_camera_is_a_grooved_body_with_end_caps_a_c_mount_and_its_front_at_the_input():
    """It was a black cube with fins. A Thorlabs compact scientific camera is 70.4 x 60.3 x 47.6 mm: a grooved
    body between two end caps, a knurled C-mount on the front, cage-rod holes, USB and I/O on the back."""

    camera = optodraw.CMOSCamera()
    x0, _ = _extent(camera, 0)
    caps = sorted(_role(camera, "cap"), key=lambda c: c["position"][0])
    assert len(caps) == 2 and len(_role(camera, "body")) == 1 and len(_role(camera, "groove")) >= 6
    u, v = [q[0] for q in caps[0]["points"]], [q[1] for q in caps[0]["points"]]
    height, width = max(u) - min(u), max(v) - min(v)                          # an end cap's outline: (u, v) = (y, -z)
    length = caps[1]["position"][0] - (caps[0]["position"][0] - caps[0]["height"])   # it extrudes toward -x
    assert (width / height, length / height) == pytest.approx((60.3 / 47.6, 70.4 / 47.6), rel=0.02)
    mount = _role(camera, "c_mount")
    assert mount and min(_ring(s)[0] for s in mount) > 0                      # a ring: the light goes through
    assert x0 == pytest.approx(camera.ports()["in"].center.x, abs=1e-6)      # the C-mount front meets the beam
    assert len(_role(camera, "rear")) >= 2


def test_an_amplified_detector_is_slim_along_the_beam_with_its_connectors_on_top():
    """It was a deep black cube. A PDA36A2 is 70.9 tall, 49.8 wide and 22.5 mm along the beam, with an SM1
    coupler round the photodiode, a label panel, the BNC and the power plug on top and the gain knob on a side."""

    pd = optodraw.AmplifiedPhotodetector()
    housing = _role(pd, "housing")[0]
    assert housing["width"] / housing["height"] == pytest.approx(22.5 / 70.9, rel=0.05)
    assert housing["depth"] / housing["height"] == pytest.approx(49.8 / 70.9, rel=0.05)
    top = housing["position"][1] + housing["height"] / 2.0
    on_top = _role(pd, "connector")
    assert len(on_top) == 2 and all(c["position"][1] - c["height"] / 2.0 == pytest.approx(top) for c in on_top)
    assert _role(pd, "coupler") and _role(pd, "gain") and _role(pd, "label")


def _luminance(hex_color):
    r, g, b = (int(hex_color.lstrip("#")[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_every_camera_class_uses_the_camera_housing():
    """The Camera device was a tiny black cube on a tall post, unlike the other cameras."""

    camera = optodraw.Camera()
    assert len(_role(camera, "cap")) == 2 and _role(camera, "c_mount") and _role(camera, "body")
    assert _extent(camera, 0)[0] == pytest.approx(camera.ports()["in"].center.x, abs=1e-6)


def test_an_emccd_is_a_larger_cooled_camera_with_a_fan():
    """The EMCCD was the CMOS camera: an EMCCD is a cooled camera, larger, with a fan on the back."""

    def cap_height(part):
        u = [q[0] for q in _role(part, "cap")[0]["points"]]
        return max(u) - min(u)

    assert cap_height(optodraw.EMCCD()) > 1.4 * cap_height(optodraw.CMOSCamera())
    assert _role(optodraw.EMCCD(), "fan") and not _role(optodraw.CMOSCamera(), "fan")


def test_a_lamp_is_a_lamp_housing_not_the_laser():
    """The lamp was the laser's black finned block with a yellow dot."""

    lamp = optodraw.Lamp()
    house = _role(lamp, "house")
    assert house and house[0]["shape"] == "cylinder" and not any(house[0].get("rotation") or [])   # upright
    assert _luminance(house[0]["material"]["color"]) > 0.4
    assert _role(lamp, "condenser")


def test_an_eom_is_a_housed_modulator_with_windows_and_an_rf_connector():
    """The EOM was a bare purple crystal between two electrode plates on a slab."""

    eom = optodraw.EOM()
    assert _role(eom, "housing") and len(_role(eom, "window")) == 2 and _role(eom, "sma")
    assert not [s for s in _solids(eom.geometry_3d()) if s["shape"] == "box" and s["material"].get("transparent")]


def test_a_post_is_stainless_steel_in_a_black_holder():
    post = optodraw.OpticalPost()
    steel = [s for s in _solids(post.geometry_3d()) if s.get("role") == "post"]
    assert steel and _luminance(steel[0]["material"]["color"]) > 0.6


@pytest.mark.parametrize("name", ["SMU", "VNA", "Oscilloscope", "OSA", "WaveformGenerator", "OpticalPowerMeter", "LaserDriver",
                                  "Computer", "CoincidenceCounter", "LockInAmplifier"])
def test_an_instrument_screen_is_lit(name):
    """The screens rendered nearly black, as if the instruments were off: clear glass (the preset) showed the
    dark panel behind a weak glow. A screen is an opaque lit panel."""

    from optodraw.registry import build_component

    screens = [s for s in _solids(build_component(name).geometry_3d()) if s["material"].get("preset") == "glass"
               and s["material"].get("emissive")]
    assert screens and all(s["material"].get("transmission") == 0.0 and s["material"].get("emissiveIntensity", 0) >= 0.2
                           for s in screens)


@pytest.mark.parametrize("name", ["SMU", "VNA", "DAQ"])
def test_bench_instruments_are_not_all_black(name):
    """Keithley source meters and Keysight analysers have grey cases; NI DAQ boxes are silver."""

    from optodraw.registry import build_component

    assert _luminance(build_component(name).color) > 0.45


_COILS = {"PolarizationController", "FiberAmplifier", "FiberSpool", "Cryostat", "Sample", "VacuumChamber"}


@pytest.mark.parametrize("name", [n for n in _free_space_parts() if n not in _COILS])
def test_rims_are_flat_rings_not_shiny_donuts(name):
    """Retaining rings, lips and bands were tori: on lenses, wave plates, mirrors, the isolator, the PMT and
    the collimator they read as shiny chrome donuts. Only fibre coils stay round."""

    from optodraw.registry import build_component

    solids = list(_solids(build_component(name).geometry_3d()))
    assert not [s for s in solids if s["shape"] == "torus"]
    shiny = [s for s in solids if s["shape"] == "lathe_profile" and s["material"].get("metalness", 0) > 0.6
             and s["material"].get("roughness", 1) < 0.3]
    assert not shiny, f"{name}: {len(shiny)} chrome rings"


def test_the_viewer_keeps_the_corners_of_a_ring_sharp():
    """A lathe ring's corners were smoothed, so a flat ring shaded like a rounded donut."""

    from test_free_space_3d import _probe_viewer

    scene = optodraw.Scene(width=60, height=40, platform="free_space")
    scene.add(optodraw.Lens())
    data = _probe_viewer(scene, """
      let lathes = 0;
      V.scene.traverse(o => { if (o.isMesh && o.geometry && o.geometry.type === 'LatheGeometry') lathes++; });
      return lathes;
    """)
    assert data == 0                                    # every lathe went through the creased-normals pass


def test_an_objective_shows_its_open_back_aperture_where_the_light_enters():
    """The back was a solid brass cylinder: the light had no entrance."""

    objective = optodraw.Objective()
    thread = _role(objective, "thread")
    assert thread and _ring(thread[0])[0] > 0                         # a ring: the back aperture is open
    assert _role(objective, "rear_lens")


def test_a_translation_stage_drives_its_carriage_with_a_micrometer_on_a_bracket():
    """The micrometer stuck out of the bottom of the base, below the carriage, like a loose knob."""

    stage = optodraw.TranslationStage()
    carriage = _role(stage, "carriage")[0]
    bracket = _role(stage, "bracket")[0]
    screw = _role(stage, "micrometer")
    c_bottom, c_top = carriage["position"][1] - carriage["height"] / 2.0, carriage["position"][1] + carriage["height"] / 2.0
    assert screw and all(c_bottom < s["position"][1] < c_top for s in screw)          # level with the carriage
    assert all(math.isclose(abs(s["rotation"][2]), math.pi / 2.0) for s in screw)        # along the travel axis
    assert bracket["position"][0] < carriage["position"][0] - carriage["width"] / 2.0     # the bracket past its end


def test_a_monochromator_sits_on_the_table_with_slits_at_the_beam():
    """It stood on a post as a small box with a drum on top."""

    from optodraw.components.optics.optomech import BEAM_HEIGHT

    mono = optodraw.Monochromator()
    assert mono.base_mount == "none"
    assert _extent(mono, 1)[0] == pytest.approx(-BEAM_HEIGHT)
    slits = _role(mono, "slit")
    assert len(slits) == 2 and all(abs(s["position"][1]) < 1e-6 for s in slits)


def test_a_lamp_house_carries_a_finned_heat_sink_on_top():
    """Its head was a stack of shrinking discs on a stem."""

    lamp = optodraw.Lamp()
    fins = _role(lamp, "fin")
    assert len(fins) >= 4 and all(f["shape"] == "box" for f in fins)


def test_an_optical_table_is_stainless_steel():
    assert _luminance(optodraw.OpticalTable().color) > 0.6


def test_a_laser_driver_has_the_front_panel_of_a_benchtop_controller():
    """Thorlabs LDC205C: a light grey case, a yellow-green LED display, keys in groups, a large current knob
    and a line switch. It was a black box with a dark screen and a round blank."""

    driver = optodraw.LaserDriver()
    assert _luminance(driver.color) > 0.6
    display = _role(driver, "display")
    assert display and display[0]["material"]["emissive"].lower() in ("#c8f03c",)
    assert len(_role(driver, "key")) >= 4 and _role(driver, "knob") and _role(driver, "switch")


def test_a_handheld_power_meter_is_the_console_in_its_rubber_boot():
    """Thorlabs PM100D: a landscape handheld (183 x 109 x 40 mm) in a red boot, a light LCD with the reading,
    a navigation cross with OK, and a kickstand. It was a tall black block."""

    console = optodraw.OpticalPowerMeter()
    boot = _role(console, "boot")[0]
    assert boot["width"] / boot["height"] == pytest.approx(183 / 109, rel=0.02)
    assert boot["depth"] / boot["height"] == pytest.approx(40 / 109, rel=0.05)
    assert _luminance(boot["material"]["color"]) < 0.5 and int(boot["material"]["color"][1:3], 16) > 0x99   # red
    assert len(_role(console, "key")) >= 5 and _role(console, "stand") and _role(console, "display")


def test_daq_connectors_stand_in_a_neat_grid_with_the_channel_ports_on_the_bottom_row():
    """Its knobs and BNCs were scattered over a dark strip."""

    daq = optodraw.DAQ()
    bncs = _role(daq, "bnc")
    rows = sorted({round(b["position"][1], 6) for b in bncs})
    cols = sorted({round(b["position"][0], 6) for b in bncs})
    assert len(bncs) == len(rows) * len(cols) >= 8                      # a full grid
    ports = sorted(p.center.x for p in daq.ports().values())
    assert all(round(x, 6) in cols for x in ports)



def test_a_4f_symbol_puts_its_fourier_plane_one_f1_behind_the_first_lens():
    """The symbol always drew the Fourier plane at the middle, for any f1 and f2."""

    from optodraw.symbols import lookup

    even = optodraw.FourFSystem(focal_length_1=20, focal_length_2=20)
    assert even.symbol_1d() is None or even.symbol_1d()[1] == {}               # the prebuilt even relay
    relay = optodraw.FourFSystem(focal_length_1=20, focal_length_2=40)
    name, params = relay.symbol_1d()
    assert name == "fourf" and params["split"] == pytest.approx(1 / 3, abs=0.01)
    symbol = lookup(relay)
    obj, image, fourier = (symbol.ports[k].x for k in ("object", "image", "fourier"))
    assert (fourier - obj) / (image - obj) == pytest.approx(params["split"], abs=0.02)   # object to plane: 2 f1


def test_the_power_meter_console_symbol_shows_a_digital_reading():
    """The PM100D shows its reading on an LCD; the symbol drew an analogue needle."""

    from importlib.resources import files

    source = (files("optodraw.symbols") / "tikz" / "od-instruments.tex").read_text()
    pic = source[source.index("pics/od powermeter/.style"):]
    pic = pic[:pic.index("}}}")]
    assert "arc" not in pic and "rectangle" in pic.split("od screen", 1)[1]
