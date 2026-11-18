"""Each drawn family: every part gets its own symbol, not the labeled block."""

from __future__ import annotations

import pytest

import optodraw  # noqa: F401  (fills the registry)
from optodraw.core.component import ANNOTATION_TYPES
from optodraw.registry import build_component
from optodraw.symbols import lookup

FAMILY_A = [  # on-chip
    "BalancedPhotodetector", "EchelleGrating", "ElectricalPad",
    "GSGProbePad", "GratingCouplerArray", "HeaterPad", "MEMSActuator",
    "MicroringWeightBank", "OpticalIOBank", "PolarizationRotator",
    "PolarizationSplitterRotator", "PresetWDMInput", "RacetrackModulator", "Spiral",
    "IQModulator", "FrequencyComb",
]

FAMILY_C = [  # instruments and electronics
    "Computer", "DAQ", "FPGABoard", "LaserDriver", "OSA", "OpticalPowerMeter", "Oscilloscope", "SMU", "VNA",
    "VacuumPump", "WaveformGenerator",
    "CoherentReceiver", "EIC", "ElectricalIOBank", "MetalRoute", "Microcontroller", "PCB",
    "ReceiverMacro", "SignalArrow", "TransmitterMacro",
]


FAMILY_D = [  # sources, detectors, samples
    "Laser", "Lamp", "Photodiode", "SNSPD", "AmplifiedPhotodetector", "PMT", "Camera", "Spectrometer",
    "Cryostat", "Sample", "Block", "Razor",
]

FAMILY_B = [  # free-space and fibre optics
    "Lens", "AsphericLens", "CylindricalLens", "Objective", "LensTube", "Telescope", "BeamExpanderTelescope",
    "FourFSystem", "FiberCollimator", "FiberPort",
    "FiberAmplifier", "FiberCirculator", "FiberCoupler", "FiberSpool", "VariableAttenuator",
    "Mirror", "ConcaveMirror", "ConvexMirror", "BiconcaveMirror", "BiconvexMirror",
    "DichroicMirror", "GalvoMirror", "Retroreflector", "Periscope",
    "BeamSplitter", "PBS", "NonPolarizingBeamSplitter",
    "Polarizer", "Analyzer", "WavePlate", "HalfWavePlate", "QuarterWavePlate", "OpticalIsolator", "BrewsterWindow",
    "WedgePlate", "CryostatWindow", "Filter",
    "AOM", "EOM", "SLM", "DMD", "OpticalChopper",
    "Iris", "ApertureStop", "Pinhole", "SpectrometerSlit",
    "Prism", "RightAnglePrism", "Pentaprism", "Grating", "Monochromator",
    "CameraSensor", "CMOSCamera", "EMCCD", "SPADArray", "PowerMeter",
    "OpticalTable", "Breadboard", "Baseplate", "KinematicMount", "OpticalPost", "PlatformMount", "RotationStage",
    "TranslationStage", "VacuumChamber", "BeamDump",
]


@pytest.mark.parametrize("name", FAMILY_A + FAMILY_B + FAMILY_C + FAMILY_D)
def test_a_drawn_part_has_its_own_symbol(name):
    part = build_component(name)
    symbol = lookup(part)
    assert symbol.source == "prebuilt" and symbol.exact, f"{name} is drawn as {symbol.source}"
    assert {key: port.kind for key, port in symbol.ports.items()} == {
        key: port.kind for key, port in part.ports().items()}


@pytest.mark.parametrize(
    "name, arguments, ports",
    [
        ("EchelleGrating", {"channel_count": 4}, 5),
        ("ElectricalIOBank", {"count": 4}, 4),
        ("GratingCouplerArray", {"count": 4}, 8),
        ("OpticalIOBank", {"count": 4}, 4),
        ("MicroringWeightBank", {"ring_count": 2}, 9),
        ("StarCoupler", {"input_count": 4, "output_count": 4}, 8),
    ],
)
def test_an_array_part_follows_its_count(name, arguments, ports):
    part = build_component(name, **arguments)
    assert len(part.ports()) == ports
    symbol = lookup(part)
    assert symbol.source == "prebuilt" and set(symbol.ports) == set(part.ports())


def test_the_weight_bank_drop_bus_turns_round():
    """Light that a ring drops travels back toward the input.

    So the drop bus passes the rings, turns round at the input end, and leaves
    at the far end, on a line beyond the one that passes the rings.
    """

    ports = lookup(build_component("MicroringWeightBank")).ports
    assert ports["o1"].side == "left" and ports["o2"].side == "right"
    assert ports["o1"].y == ports["o2"].y                               # input and through: one straight bus
    assert ports["drop"].x == pytest.approx(ports["o2"].x)              # the drop leaves at the far end
    assert ports["drop"].y < ports["d1"].y < ports["o1"].y              # on the return line (y grows downward)


def test_a_weight_bank_meets_its_balanced_detector_with_straight_links():
    """The two outputs of a bank are as far apart as the two inputs of a balanced detector."""

    outputs = lookup(build_component("MicroringWeightBank")).ports
    inputs = lookup(build_component("OnChipBalancedPhotodetector")).ports
    assert abs(outputs["o2"].y - outputs["drop"].y) == pytest.approx(abs(inputs["o1"].y - inputs["o2"].y), abs=0.01)


def test_the_symbol_of_a_default_part_stays_small():
    """A figure has a fixed width. No default part may take more than 3.9 cm (110 points) of it."""

    import json

    from optodraw.symbols import build

    library = json.loads((build.HERE / "symbols.json").read_text(encoding="utf-8"))["symbols"]
    too_big = {
        entry["component"]: (round(entry["width"]), round(entry["height"]))
        for entry in library.values()
        if entry.get("component") and not entry.get("args") and max(entry["width"], entry["height"]) > 110.0
    }
    assert too_big == {}


def _art(name: str, **arguments) -> str:
    return lookup(build_component(name, **arguments)).svg


def test_no_part_of_the_catalog_is_a_labeled_block():
    from optodraw.registry import component_registry

    not_parts = {"Beam", "Route", "Grid", "ChipSubstrate", "CustomModel", "GDSModel"} | ANNOTATION_TYPES
    blocks = [name for name in sorted(component_registry())
              if name not in not_parts and lookup(build_component(name)).source == "block"]
    assert blocks == []


def test_a_lens_with_a_negative_focal_length_is_drawn_concave():
    assert lookup(build_component("Lens", focal_length=-30.0)).source == "prebuilt"
    assert _art("Lens", focal_length=-30.0) != _art("Lens")


def test_a_wave_plate_shows_its_retardance():
    import math

    assert _art("WavePlate", retardance=math.pi / 2) == _art("QuarterWavePlate")
    assert _art("WavePlate", retardance=math.pi) == _art("HalfWavePlate")
    assert _art("QuarterWavePlate") != _art("HalfWavePlate")
    assert _art("WavePlate", retardance=1.0) not in (_art("QuarterWavePlate"), _art("HalfWavePlate"))


def test_a_mirror_shows_its_surface():
    assert _art("Mirror", surface_type="concave") == _art("ConcaveMirror")
    assert _art("Mirror", surface_type="convex") == _art("ConvexMirror")
    assert len({_art(name) for name in ("Mirror", "ConcaveMirror", "ConvexMirror", "BiconcaveMirror", "BiconvexMirror")}) == 5


def test_a_galilean_telescope_has_a_concave_lens():
    assert lookup(build_component("Telescope", telescope_type="galilean")).source == "prebuilt"
    assert _art("Telescope", telescope_type="galilean") != _art("Telescope")


def test_the_two_outputs_of_a_cube_beamsplitter_leave_at_a_right_angle():
    ports = lookup(build_component("PBS")).ports
    assert ports["in"].side == "left" and ports["trans"].side == "right" and ports["refl"].side == "top"
    assert ports["in"].y == pytest.approx(ports["trans"].y)


TURNED = {"RightAnglePrism", "Pentaprism"}          # these send the beam out through another face


@pytest.mark.parametrize("name", [name for name in FAMILY_B if name not in TURNED])
def test_the_beam_goes_through_a_free_space_part_from_left_to_right(name):
    """A link leaves a port square to its edge, so ``in`` must face left and ``out`` must face right."""

    ports = lookup(build_component(name)).ports
    for port, side in (("in", "left"), ("out", "right"), ("object", "left"), ("image", "right"), ("trans", "right")):
        if port in ports:
            assert ports[port].side == side, f"{name}.{port} faces {ports[port].side}"


def test_a_beam_inside_a_part_is_never_broken():
    """A beam drawn inside a part is a solid line, so it joins the links without a break.

    Only the Fourier plane of a 4f system, the post hidden under a platform
    (seen from above) and the place a flip mirror flips to are dashed: a plane,
    a hidden edge and a position, not beams.
    """

    import json
    import re

    from optodraw.symbols import build

    library = json.loads((build.HERE / "symbols.json").read_text(encoding="utf-8"))["symbols"]
    dashed = sorted({entry["symbol"] for entry in library.values()
                     if re.search(r"stroke-dasharray=.(?!none)", (build.HERE / "svg" / entry["svg"]).read_text())})
    assert dashed == ["flipmirror", "fourf", "platform"]


def test_a_splitter_knows_where_its_beams_meet():
    """A view draws the beam from each port that a scene uses to this point, so a splitter shows only real paths."""

    for name in ("BeamSplitter", "PBS", "NonPolarizingBeamSplitter"):
        symbol = lookup(build_component(name))
        assert symbol.hub is not None and "hub" not in symbol.ports, name
        assert 0 < symbol.hub[0] < symbol.width and 0 < symbol.hub[1] < symbol.height, name
    plate = lookup(build_component("BeamSplitter"))
    turned, flipped = plate.rotated(90), plate.mirrored()
    assert abs(turned.hub[0] - plate.hub[1]) < 0.01 and abs(flipped.hub[0] - (plate.width - plate.hub[0])) < 0.01
    assert "hub" in plate.to_dict()


def test_a_dichroic_plate_shows_its_coating():
    plain, dichroic = lookup(build_component("BeamSplitter")), lookup(build_component("BeamSplitter", dichroic=True))
    assert dichroic.source == "prebuilt" and dichroic.params == {"kind": "dichroic"} and dichroic.svg != plain.svg
