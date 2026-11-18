"""Each drawn family: every part gets its own symbol, not the labeled block."""

from __future__ import annotations

import pytest

import optodraw  # noqa: F401  (fills the registry)
from optodraw.core.component import ANNOTATION_TYPES
from optodraw.registry import build_component
from optodraw.symbols import lookup

from sweep import sweep

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


def _check_a_drawn_part_has_its_own_symbol(name):
    part = build_component(name)
    symbol = lookup(part)
    assert symbol.source == "prebuilt" and symbol.exact, f"{name} is drawn as {symbol.source}"
    assert {key: port.kind for key, port in symbol.ports.items()} == {
        key: port.kind for key, port in part.ports().items()}


def test_a_drawn_part_has_its_own_symbol():
    sweep(_check_a_drawn_part_has_its_own_symbol, FAMILY_A + FAMILY_B + FAMILY_C + FAMILY_D)


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


def test_a_wave_plate_shows_its_retardance():
    import math

    assert _art("WavePlate", retardance=math.pi / 2) == _art("QuarterWavePlate")
    assert _art("WavePlate", retardance=math.pi) == _art("HalfWavePlate")
    assert _art("QuarterWavePlate") != _art("HalfWavePlate")
    assert _art("WavePlate", retardance=1.0) not in (_art("QuarterWavePlate"), _art("HalfWavePlate"))


TURNED = {"RightAnglePrism", "Pentaprism"}          # these send the beam out through another face


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


