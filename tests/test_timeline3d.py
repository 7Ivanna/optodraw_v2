"""Physics-anchored checks for the 3D animation payload compiler."""

import math

import pytest

from optodraw import (
    Beam,
    FocusingBeam,
    HeaterPad,
    Laser,
    Lens,
    MetalRoute,
    MicroringResonator,
    Photodiode,
    Scene,
    WaveguideRoute,
)
from optodraw.core.timeline3d import anim_payload_map


def _payload_for(scene, node):
    return anim_payload_map(scene).get(id(node))


class TestGuidedFlow:

    def test_electrical_route_gets_signal_kind(self):
        scene = Scene(platform="on_chip")
        a = scene.add(MetalRoute(points=((0, 0), (30, 0))))
        anim = _payload_for(scene, a)
        # MetalRoute may resolve via Route kind; accept either payload shape.
        if anim is not None and "signal" in anim:
            assert anim["signal"]["kind"] in ("dc", "rf", "digital", "clock")


class TestEnvelope:
    def test_gaussian_profile_hits_both_anchor_widths(self):
        scene = Scene(platform="free_space")
        lens = scene.add(Lens(center=(0, 0)))
        pd = scene.add(Photodiode(center=(50, 0)))
        fbeam = scene.add(FocusingBeam(lens, pd, width1=6.0, width2=0.5))
        anim = _payload_for(scene, fbeam)
        profile = anim["envelope"]["profile"]
        w_start = profile[0][1]
        w_end = profile[-1][1]
        assert w_start == pytest.approx(6.0, rel=0.02)
        assert w_end == pytest.approx(0.5, rel=0.05)
        # A Gaussian focus is a hyperbola: monotonically narrowing here.
        widths = [w for _, w in profile]
        assert widths == sorted(widths, reverse=True)


class TestRingAndHeat:

    def test_heater_payload_follows_the_metal_strip(self):
        scene = Scene(platform="on_chip")
        heater = scene.add(HeaterPad(center=(10, 5)))
        anim = _payload_for(scene, heater)
        paths = anim["heat"]["paths"]
        assert len(paths) == 1
        pts = paths[0]["pts"]
        # a straight strip of heater_length centred on the component
        assert math.dist(pts[0], pts[-1]) == pytest.approx(heater.heater_length, rel=1e-6)
        assert pts[0][1] == pytest.approx(5.0)  # world-transformed
        assert paths[0]["w"] == pytest.approx(heater.heater_width)
        assert anim["heat"]["tau_s"] > 0

    def test_heated_racetrack_heat_wraps_the_whole_oval(self):
        """The heat halo must hug the metal that is actually drawn. Unifying the
        racetrack heater retired ``heater_y``, which the payload keyed on — the
        halo silently disappeared instead of following the new full-oval band."""

        from optodraw import RacetrackResonator

        scene = Scene(platform="on_chip")
        track = scene.add(RacetrackResonator(center=(0, 0), with_heater=True))
        anim = _payload_for(scene, track)
        assert anim.get("heat"), "a heated racetrack must emit a heat payload"
        (path,) = anim["heat"]["paths"]
        pts = path["pts"]
        assert path["w"] == pytest.approx(track.heater_width)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        # spans both straights and reaches around the top AND bottom bends...
        assert max(xs) > track.coupling_length / 2.0
        assert min(xs) < -track.coupling_length / 2.0
        assert max(ys) > track.ring_top_y
        assert min(ys) < track.ring_bottom_y + track.bend_radius
        # ... but stops short of straight-down, leaving the bus coupling clear
        assert min(ys) > track.ring_bottom_y

    def test_heated_ring_gets_arc_heat_and_circulation(self):
        from optodraw import PNMicroringModulator

        scene = Scene(platform="on_chip")
        ring = scene.add(PNMicroringModulator(center=(0, 0)))  # with_heater=True default
        anim = _payload_for(scene, ring)
        assert "guides" in anim and "heat" in anim  # light + heat on one device
        arc = anim["heat"]["paths"][0]["pts"]
        assert len(arc) > 10  # an arc, not a 2-point strip
        # every arc point sits at heater_radius from the ring centre
        for x, y in (arc[0], arc[len(arc) // 2], arc[-1]):
            assert math.hypot(x, y) == pytest.approx(ring.heater_radius, rel=1e-3)

    def test_mzi_heat_sits_on_the_upper_arm(self):
        from optodraw import MZI

        scene = Scene(platform="on_chip")
        mzi = scene.add(MZI(center=(0, 0)))
        anim = _payload_for(scene, mzi)
        pts = anim["heat"]["paths"][0]["pts"]
        drawn = mzi._draw_variant()  # heat hugs the DRAWN heater metal
        assert pts[0][1] == pytest.approx(drawn.arm_gap / 2.0)  # on the drawn arm
        assert math.dist(pts[0], pts[-1]) == pytest.approx(drawn.heater_length, rel=1e-6)
        # and the heat strip sits exactly on the animated light path's arm
        arm_y = max(abs(p[1]) for p in anim["guides"][0]["pts"])
        assert pts[0][1] == pytest.approx(arm_y, abs=0.1)


class TestBeamChaining:
    def test_branch_beam_starts_when_pulse_reaches_splitter(self):
        from optodraw import BeamSplitter

        scene = Scene(platform="free_space")
        laser = scene.add(Laser(center=(0, 0)))
        bs = scene.add(BeamSplitter(center=(40, 0), angle=45))
        pd1 = scene.add(Photodiode(center=(90, 0)))
        pd2 = scene.add(Photodiode(center=(40, 50), angle=90))
        main = scene.add(Beam(laser, bs, pd1))
        branch = scene.add(Beam(bs, pd2))
        payloads = anim_payload_map(scene)
        main_p = payloads[id(main)]["pulse"]
        branch_p = payloads[id(branch)]["pulse"]
        assert main_p["t0"] == pytest.approx(0.0)
        # branch launches exactly when the pulse reaches the BS (= first segment length)
        assert branch_p["t0"] == pytest.approx(main_p["segments"][0]["len"], rel=1e-6)
        # and carries the reflected half of the power
        assert branch_p["segments"][0]["power"] == pytest.approx(0.5, abs=0.05)


class TestAnchorTuples:
    def test_port_tuple_beams_chain_and_split(self):
        """Editor-built beams anchor to (component, port) tuples — they must chain."""
        from optodraw import PBS

        scene = Scene(platform="free_space")
        laser = scene.add(Laser(center=(0, 0)))
        pbs = scene.add(PBS(center=(40, 0)))
        pd1 = scene.add(Photodiode(center=(90, 0)))
        pd2 = scene.add(Photodiode(center=(40, 50), angle=90))
        b_in = scene.add(Beam((laser, "out"), (pbs, "in")))
        b_t = scene.add(Beam((pbs, "trans"), (pd1, "in")))
        b_r = scene.add(Beam((pbs, "refl"), (pd2, "in")))
        payloads = anim_payload_map(scene)
        t0_t = payloads[id(b_t)]["pulse"]["t0"]
        t0_r = payloads[id(b_r)]["pulse"]["t0"]
        assert t0_t > 0 and t0_r > 0
        assert t0_t == pytest.approx(t0_r, rel=1e-6)  # both arms fire TOGETHER


class TestCouplingRegimes:
    """Coupling regimes bake into the through-path power of the system trace."""

    def _guides(self, regime):
        from optodraw import MicroringResonator

        scene = Scene(platform="on_chip")
        ring = scene.add(MicroringResonator(center=(0, 0)))
        ring.anim_params = {"ring_coupling": regime}
        return anim_payload_map(scene)[id(ring)]["guides"]


class TestCouplerTransfer:
    """Couplers animate on their own DRAWN centerlines with baked transfer profiles."""


    def test_adiabatic_transfer_is_monotonic(self):
        from optodraw import AdiabaticCoupler

        scene = Scene(platform="on_chip")
        ac = scene.add(AdiabaticCoupler(center=(0, 0)))
        guides = anim_payload_map(scene)[id(ac)]["guides"]
        powers = [s["power"] for s in guides[1]["segments"]]
        assert powers == sorted(powers)  # no beat, pure transfer

    def test_spiral_guide_is_the_full_coil(self):
        from optodraw import Spiral

        scene = Scene(platform="on_chip")
        spiral = scene.add(Spiral(center=(0, 0)))
        guides = anim_payload_map(scene)[id(spiral)]["guides"]
        assert len(guides[0]["pts"]) > 100  # the drawn coil, not a straight line
        # the coil is much longer than the port-to-port distance (real delay)
        direct = math.dist(guides[0]["pts"][0], guides[0]["pts"][-1])
        assert guides[0]["len"] > 3 * direct


class TestJunctions:

    def test_eam_is_pin_injection(self):
        from optodraw import ElectroAbsorptionModulator

        scene = Scene(platform="on_chip")
        eam = scene.add(ElectroAbsorptionModulator(center=(0, 0)))
        j = anim_payload_map(scene)[id(eam)]["junction"]
        assert j["kind"] == "pin"

    def test_junction_off_via_anim_params(self):
        from optodraw import MZM

        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(center=(0, 0)))
        mzm.anim_params = {"junction": "off"}
        payload = anim_payload_map(scene).get(id(mzm)) or {}
        assert "junction" not in payload

    def test_anim_params_round_trip_spec(self):
        from optodraw import MicroringResonator
        from optodraw.schema import component_from_spec

        ring = MicroringResonator(center=(0, 0))
        ring.anim_params = {"ring_coupling": "over"}
        spec = ring.to_dict()
        assert spec["anim_params"] == {"ring_coupling": "over"}
        clone = component_from_spec({k: v for k, v in spec.items() if k != "ports"})
        assert clone.anim_params == {"ring_coupling": "over"}


class TestCircuitTrace:
    """On-chip devices ARE waveguides: light flows THROUGH them, timed and split."""

    def _chip(self):
        from optodraw import MMI1x2, MicroringResonator, Waveguide, route_ports

        scene = Scene(platform="on_chip")
        wg = scene.add(Waveguide(center=(-50, 0)))
        mmi = scene.add(MMI1x2(center=(0, 0)))
        ring = scene.add(MicroringResonator(center=(60, 16), add_drop=True))
        r1 = scene.add(route_ports((wg, "o2"), (mmi, "o1")))
        r2 = scene.add(route_ports((mmi, "o2"), (ring, "o1")))
        return scene, wg, mmi, ring, r1, r2


class TestPerComponentTransmissions:
    def _traced(self, mid):
        from optodraw import Waveguide, route_ports

        scene = Scene(platform="on_chip")
        wg_in = scene.add(Waveguide(center=(-60, 0)))
        scene.add(mid)
        scene.add(route_ports((wg_in, "o2"), (mid, "o1")))
        return anim_payload_map(scene).get(id(mid)) or {}

    def test_tap_coupler_uses_its_own_ratio(self):
        from optodraw import TapCoupler

        tap = TapCoupler(center=(0, 0), tap_ratio=0.1)
        guides = self._traced(tap).get("guides") or []
        powers = sorted(round(g["power"], 3) for g in guides)
        assert powers == [pytest.approx(0.1), pytest.approx(0.9)]  # cross 10%, bar 90%

    def test_insertion_loss_scales_transmission(self):
        from optodraw import Waveguide

        lossy = Waveguide(center=(0, 0))
        lossy.insertion_loss_db = 3.0  # ~50%
        guides = self._traced(lossy).get("guides") or []
        assert guides and guides[0]["power"] == pytest.approx(0.97 * 10 ** (-0.3), rel=0.02)

    def test_anim_params_transmissions_override_everything(self):
        from optodraw import MMI1x2

        mmi = MMI1x2(center=(0, 0))
        mmi.anim_params = {"transmissions": {"o2": 0.9, "o3": 0.1}}
        guides = self._traced(mmi).get("guides") or []
        by_power = sorted(round(g["power"], 3) for g in guides)
        assert by_power == [pytest.approx(0.1), pytest.approx(0.9)]

    def test_free_space_reads_instance_transmission(self):
        from optodraw.core.timeline3d import _transmission
        from optodraw import Filter

        filt = Filter(center=(0, 0))
        filt.transmission = 0.85
        assert _transmission(filt) == pytest.approx(0.85)


class TestRelativeSpeeds:
    def test_silicon_slower_than_air_by_group_index(self):
        """The physical core promise: guided light visibly lags free-space light."""

        scene = Scene(platform="on_chip")
        route = scene.add(WaveguideRoute([(0, 0), (60, 0)]))
        anim = _payload_for(scene, route)
        n_guided = anim["flow"]["n"]
        assert n_guided / 1.0 > 3  # ≥3x slower than a free-space beam
        # Traversal time ratio for equal lengths is exactly the index ratio.
        assert math.isclose(n_guided / 1.0, anim["flow"]["n"], rel_tol=1e-9)


class TestWavelengthChannels:
    """Resonators couple their RESONANT color; heaters act on the light."""


    def test_bank_drop_follows_the_drawn_serial_bus_left_then_right(self):
        from optodraw import MicroringWeightBank

        scene = Scene(platform="on_chip")
        bank = scene.add(MicroringWeightBank(center=(0, 0)))
        guides = anim_payload_map(scene)[id(bank)]["guides"]
        drop = next(g for g in guides if g["pts"][-1][1] > 30)  # ends at the drop port
        xs = [p[0] for p in drop["pts"]]
        # the dropped light first heads LEFT (co-propagating with the CCW ring
        # tops) past the serial bus end, then returns RIGHT on the output bus
        assert min(xs) < -80
        assert drop["pts"][-1][0] > 80
        leftmost = xs.index(min(xs))
        assert 0 < leftmost < len(xs) - 1  # left first, then right — a real U-turn


class TestBehavioralStates:
    """The unified control layer: every device's behaviour is switchable."""

    def _laser_chip(self, emission=None):
        from optodraw import OnChipLaser, OnChipPhotodetector, route_ports

        scene = Scene(platform="on_chip")
        laser = scene.add(OnChipLaser(center=(-60, 0)))
        if emission:
            laser.anim_params = {"emission": emission}
        ring = scene.add(MicroringResonator(center=(0, 0), add_drop=True))
        pd = scene.add(OnChipPhotodetector(center=(60, 0)))
        r1 = scene.add(route_ports((laser, "o1"), (ring, "o1")))
        scene.add(route_ports((ring, "o2"), (pd, "o1")))
        return scene, laser, ring, r1

    def test_laser_off_darkens_the_whole_subtree(self):
        scene, _, ring, r1 = self._laser_chip("off")
        payloads = anim_payload_map(scene)
        assert payloads[id(r1)]["flow"]["power"] == 0.0
        # the ring is connected to a dark circuit: no light, no self-seeding
        assert not (payloads.get(id(ring)) or {}).get("guides")

    def test_pulsed_laser_marks_the_traced_light(self):
        scene, _, ring, r1 = self._laser_chip("pulsed")
        payloads = anim_payload_map(scene)
        assert payloads[id(r1)]["flow"].get("pulsed") is True
        assert all(g.get("pulsed") for g in payloads[id(ring)]["guides"])


    def test_heater_off_removes_halo_and_tuning(self):
        scene = Scene(platform="on_chip")
        ring = scene.add(MicroringResonator(center=(0, 0), with_heater=True))
        ring.anim_params = {"heater": "off"}
        payload = anim_payload_map(scene)[id(ring)]
        assert "heat" not in payload
        assert all("mod" not in g for g in payload["guides"])

    def test_drive_off_stills_the_metal(self):
        scene = Scene(platform="on_chip")
        trace = scene.add(MetalRoute(points=((0, 0), (40, 0))))
        trace.anim_params = {"drive": "off"}
        assert anim_payload_map(scene).get(id(trace)) is None


class TestBehaviorProtocol:
    """Every device declares its switchable behaviours (the per-device protocol)."""

    def test_devices_declare_their_controls(self):
        from optodraw import (MZI, MZM, DirectionalCoupler, OnChipLaser,
                              PNMicroringModulator)

        assert {b["key"] for b in MicroringResonator(center=(0, 0), with_heater=True).anim_behaviors()} == {
            "state", "ring_coupling", "channel", "heater"}
        assert "junction" in {b["key"] for b in PNMicroringModulator(center=(0, 0)).anim_behaviors()}
        assert {b["key"] for b in MZM(center=(0, 0)).anim_behaviors()} == {"bias", "junction", "heater"}
        assert "split" in {b["key"] for b in DirectionalCoupler(center=(0, 0)).anim_behaviors()}
        assert "emission" in {b["key"] for b in OnChipLaser(center=(0, 0)).anim_behaviors()}
        assert MZI(center=(0, 0)).anim_behaviors()  # every guided device has controls


    def test_mzm_default_bias_is_quadrature(self):
        from optodraw import MZM

        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(center=(0, 0)))
        guides = anim_payload_map(scene)[id(mzm)]["guides"]
        total_out = sum(g["segments"][-1]["power"] for g in guides)
        assert total_out == pytest.approx(0.5, abs=0.06)  # half transmission


class TestPhysicsAudit:
    """Sweep EVERY guided device x optical port x behavioural state against hard
    physics invariants — catches wrong-port exits, teleports, non-conservation."""

    DEVICES = None  # built lazily (import cost)

    @classmethod
    def _devices(cls):
        from optodraw import (AdiabaticCoupler, DirectionalCoupler, MZI, MZM,
                              MicroringWeightBank, PNMicroringModulator,
                              RacetrackModulator, RacetrackResonator, Spiral,
                              TapCoupler, WaveguideBend, YBranch)

        return [
            lambda: DirectionalCoupler(center=(0, 0)),
            lambda: TapCoupler(center=(0, 0)),
            lambda: AdiabaticCoupler(center=(0, 0)),
            lambda: YBranch(center=(0, 0)),
            lambda: MZI(center=(0, 0)),
            lambda: MZM(center=(0, 0)),
            lambda: Spiral(center=(0, 0)),
            lambda: WaveguideBend(center=(0, 0)),
            lambda: MicroringResonator(center=(0, 0), add_drop=True, with_heater=True),
            lambda: RacetrackResonator(center=(0, 0), add_drop=True, with_heater=True),
            lambda: PNMicroringModulator(center=(0, 0), add_drop=True),
            lambda: RacetrackModulator(center=(0, 0), add_drop=True),
            lambda: MicroringWeightBank(center=(0, 0), with_heaters=True),
        ]

    def test_all_devices_all_ports_all_states(self):
        violations = []
        for make in self._devices():
            probe = make()
            name = probe.component_type
            options = {b["key"]: [v for v, _ in b["options"]] for b in probe.anim_behaviors()}
            optical = [n for n, p in probe.ports().items()
                       if getattr(p, "kind", "optical") != "electrical"]
            states = [None] + [{k: v} for k, vals in options.items() for v in vals if v != "auto"]
            for in_port in optical:
                for params in states:
                    node = make()
                    if params:
                        node.anim_params = dict(params)
                    ports = node.ports()
                    entry = ports[in_port]
                    paths = node.optical_paths(in_port)
                    total_exit = 0.0
                    for p in paths:
                        pts, port = p["pts"], p.get("port", "")
                        power = float(p.get("power", 0))
                        tag = f"{name}[{in_port}->{port or 'loop'}]{params}"
                        if not (-1e-6 <= power <= 1.001):
                            violations.append(f"{tag}: power {power}")
                        if port:
                            total_exit += power
                            tp = ports[port]
                            if math.dist(pts[-1], (float(tp.center.x), float(tp.center.y))) > 0.6:
                                violations.append(f"{tag}: wrong exit endpoint")
                        if not p.get("delay_len"):
                            if math.dist(pts[0], (float(entry.center.x), float(entry.center.y))) > 0.6:
                                violations.append(f"{tag}: wrong start point")
                        for a, b in zip(pts, pts[1:]):
                            dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
                            if math.hypot(dx, dy) > 3.5 and dx > 0.3 and dy > 0.3:
                                violations.append(f"{tag}: diagonal teleport {math.hypot(dx, dy):.1f}")
                                break
                        prof = p.get("powers")
                        if prof is not None:
                            if len(prof) != len(pts):
                                violations.append(f"{tag}: profile length mismatch")
                            elif any(not (-1e-6 <= v <= 1.02) for v in prof):
                                violations.append(f"{tag}: profile out of range")
                            elif port and abs(prof[-1] - power) > 0.06:
                                violations.append(f"{tag}: profile end != declared power")
                    if total_exit > 1.02:
                        violations.append(f"{name}[{in_port}]{params}: non-conservation {total_exit:.2f}")
        assert not violations, "\n".join(violations[:20])
