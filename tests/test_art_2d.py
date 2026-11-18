"""2D art: a part is painted with its symbol, fitted to its physical ports."""

from __future__ import annotations

import pytest

from optodraw.registry import build_component

STAGE_0 = ["Lens", "Mirror", "PBS"]


# ---------------------------------------------------------------- stage 1: free-space optics
CARRIERS = {"OpticalTable", "Breadboard", "Baseplate"}    # the plates a bench stands on keep their own drawing
TWO_MOUNTS = {"Periscope", "Telescope", "FourFSystem"}   # drawn as their two parts from above, at their true spacing


def _optics():
    from optodraw.registry import component_registry

    return sorted(name for name, spec in component_registry().items() if spec.category == "optics")


@pytest.mark.parametrize("preset", ["free_space_breadboard", "ftir_setup", "confocal_pl_setup", "raman_setup", "qwp_circular_lab"])
def test_a_free_space_preset_paints_every_optic(preset):
    from optodraw import presets

    scene = getattr(presets, preset)()
    optics = [node for node in scene.walk() if getattr(node, "component_type", "") in set(_optics()) - CARRIERS]
    assert scene.render_svg().as_svg().count("data-art=") >= len(optics) > 0


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


# ---------------------------------------------------------------- stage 3: electronics and packaging


