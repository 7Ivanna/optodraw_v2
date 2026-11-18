"""Tests for schematic-first on-chip component rendering."""

from __future__ import annotations

import pytest

from optodraw import AWG, BraggGrating, OpticalIOBank, StarCoupler, Waveguide, MMI1x2
from optodraw.components.onchip import couplers, io, mmi, modulators, rings, splitters, system, waveguides
from optodraw.components.onchip.base import ChipComponent
from optodraw.components.onchip.couplers import EdgeCoupler, GratingCouplerArray
from optodraw.components.onchip.io import OnChipLaser, SOA
from optodraw.components.onchip.modulators import MZI, MZM
from optodraw.components.onchip.rings import MicroringWeightBank, RacetrackModulator, RacetrackResonator
from optodraw.components.onchip.schematic_tables import SCHEMATIC_TABLES
from optodraw.components.onchip.splitters import DirectionalCoupler, YBranch
from optodraw.components.onchip.system import SagnacLoop


class TestSchematicOnChipDefaults:
    def test_public_onchip_classes_have_schematic_metadata(self):
        modules = [couplers, io, mmi, modulators, rings, splitters, system, waveguides]
        failures: list[str] = []
        for module in modules:
            for value in vars(module).values():
                if (
                    isinstance(value, type)
                    and issubclass(value, ChipComponent)
                    and value is not ChipComponent
                    and value.__module__ == module.__name__
                    and not value.__name__.startswith("_")
                ):
                    family = getattr(value, "schematic_family", None)
                    has_spec = value.physical_spec is not ChipComponent.physical_spec
                    if family not in SCHEMATIC_TABLES or not has_spec or (family == "waveguide" and value is not Waveguide):
                        failures.append(f"{module.__name__}.{value.__name__}: family={family!r}, has_spec={has_spec}")

        assert failures == []

    @pytest.mark.parametrize(
        ("component", "family", "key", "expected"),
        [
            (EdgeCoupler(taper_length=72.0), "edge_coupler", "taper_length", 72.0),
            (GratingCouplerArray(count=4, pitch=125.0), "grating_coupler_array", "array_width", 375.0),
            (YBranch(branch_length=36.0), "y_branch", "branch_length", 36.0),
            (DirectionalCoupler(coupling_length=18.0), "directional_coupler", "coupling_length", 18.0),
            (MZI(arm_length=180.0), "mzi", "arm_length", 180.0),
            (MZM(electrode_width=8.0, drive_style="gsg"), "mzm", "electrode_width", 8.0),
            (RacetrackResonator(bend_radius=12.0), "racetrack", "bend_radius", 12.0),
            (RacetrackModulator(coupling_length=60.0, electrode_length=44.0, add_drop=False), "racetrack_modulator", "active_length", 44.0),
            (MicroringWeightBank(ring_count=3), "microring_weight_bank", "ring_count", 3),
            (OpticalIOBank(count=4, pitch=127.0), "optical_io_bank", "count", 4),
            (StarCoupler(input_count=2, output_count=6), "star_coupler", "output_count", 6),
            (AWG(channel_count=8, array_count=24), "awg", "array_count", 24),
            (BraggGrating(length=320.0, period=0.32), "bragg_grating", "length", 320.0),
            (SagnacLoop(loop_radius=40.0), "sagnac_loop", "loop_radius", 40.0),
        ],
    )
    def test_expanded_onchip_components_record_physical_specs(self, component, family, key, expected):
        spec = component.physical_spec()
        assert component.schematic_family == family
        assert spec.device_family == family
        assert spec[key] == pytest.approx(expected)


    def test_mmi_body_draw_dims_from_table(self):
        mmi = MMI1x2(body_length=5.5, body_width=2.5, taper_length=10.0)
        assert mmi.body_length == pytest.approx(5.5)
        assert mmi.total_length == pytest.approx(25.5)
        dims = mmi.schematic_dims()
        assert dims["body_length"] == pytest.approx(12.0)


    def test_laser_and_soa_draw_from_schematic_tables(self):
        laser = OnChipLaser(cavity_length=180.0, ridge_width=2.5, output_taper_length=22.0)
        # Port sits on the drawn (compacted) output; render_physical restores physical µm.
        assert laser.ports()["o1"].center.x == pytest.approx(40.0)      # a compact figure: shorter than an MZM
        laser_phys = OnChipLaser(cavity_length=180.0, ridge_width=2.5, output_taper_length=22.0, render_physical=True)
        assert laser_phys.ports()["o1"].center.x == pytest.approx(laser.total_length / 2.0)
        assert laser.geometry_2d()["children"][0]["w"] == pytest.approx(64.0)
        assert OnChipLaser(cavity_length=180.0, render_physical=True).geometry_2d()["children"][0]["w"] == pytest.approx(180.0)

        soa = SOA(amplifier_length=70.0, taper_length=10.0, ridge_width=1.8)
        assert soa.ports()["o1"].center.x == pytest.approx(-45.0)
        assert soa.geometry_2d()["children"][1]["w"] == pytest.approx(180.0)
        assert SOA(amplifier_length=70.0, render_physical=True).geometry_2d()["children"][1]["w"] == pytest.approx(70.0)


    def test_onchip_system_primitives_have_ports_and_metadata(self):
        bank = OpticalIOBank(count=4, pitch=127.0, with_fibers=True, side="left")
        # Ports track the drawn (schematic-pitch) bank; render_physical restores the 127µm pitch.
        assert bank.ports()["o4"].center.y == pytest.approx(45.0)
        assert OpticalIOBank(count=4, pitch=127.0, side="left", render_physical=True).ports()["o4"].center.y == pytest.approx(190.5)
        assert bank.ports()["f1"].kind == "fiber"
        assert bank.geometry_2d()["children"]

        awg = AWG(channel_count=5, array_count=12, center_wavelength_nm=1310.0)
        ports = awg.ports()
        assert ports["i1"].orientation_deg == pytest.approx(180.0)
        # o5 topmost, o1 bottom, o3 on the optical axis with the input. The fan
        # is NOT mirror symmetric about that axis and cannot be: the AWG is
        # built from the router's tilted star couplers now, so the channels are
        # evenly spaced along a tilted arc and their projection onto y is not.
        channel_y = [ports[f"o{i}"].center.y for i in range(1, 6)]
        assert channel_y == sorted(channel_y), "o1 at the bottom through o5 at the top"
        # o3 on the optical axis of the input aperture; the input guide then bends into i1 (one 10 um bend), so i1
        # sits less than a bend radius below that axis
        assert 0.0 <= ports["o3"].center.y - ports["i1"].center.y < 10.0
        assert channel_y[0] < 0.0 < channel_y[-1]
        # y=0 is the input aperture, not the middle of the part: the arm bundle
        # climbs above both horns, so the drawn box is not centred on the
        # placement point. Scene.content_bounds reads that box rather than
        # assuming a centred one, which is what keeps the part in frame.
        from optodraw.layout import _bounds_from_geometry
        box = _bounds_from_geometry(awg.geometry_2d())
        assert box[1] < channel_y[0] and channel_y[-1] < box[3]
        assert box[3] > -box[1], "the arms sit above the couplers"
        # Each channel launches along its own arc normal, never a flat 0.
        assert len({round(ports[f"o{i}"].orientation_deg, 3) for i in range(1, 6)}) == 5
        assert awg.physics_metadata()["center_wavelength_nm"] == pytest.approx(1310.0)

        grating = BraggGrating(length=240.0, period=0.3, reflectivity=0.72)
        assert grating.grating_count == 800
        assert grating.physics_metadata()["reflectivity"] == pytest.approx(0.72)

