"""Where each part sits in the editor's parts menu: a section (Free-space optics, On-chip photonics, Electronics,
Annotations, My parts) and a group inside it (Lenses, Cage system, Mounts...).

The free-space parts are listed by name. On-chip and electronic parts fall into groups by a word in their name, so
a new part lands somewhere sensible; anything else falls back on its catalogue category.
"""

from __future__ import annotations

SECTIONS = ("My parts", "Free-space optics", "On-chip photonics", "Electronics", "Annotations")

FREE_SPACE_GROUPS: dict[str, tuple[str, ...]] = {
    "Sources": ("Laser", "Lamp", "CatalogLED"),
    "Lenses & objectives": ("Lens", "AsphericLens", "CylindricalLens", "CatalogLens", "Objective", "Telescope",
                            "BeamExpanderTelescope", "FourFSystem"),
    "Mirrors": ("Mirror", "ConcaveMirror", "ConvexMirror", "BiconcaveMirror", "BiconvexMirror", "PartialMirror",
                "DichroicMirror", "FlipMirror", "GalvoMirror", "MotorizedMirror", "RoofMirror", "Retroreflector",
                "CatalogMirror", "CatalogDichroic"),
    "Beamsplitters": ("BeamSplitter", "NonPolarizingBeamSplitter", "PBS", "CatalogCubeSplitter", "CatalogPlateSplitter"),
    "Polarization": ("Polarizer", "Analyzer", "WavePlate", "HalfWavePlate", "QuarterWavePlate", "GlanLaserPolarizer",
                     "WollastonPrism", "FaradayRotator", "OpticalIsolator", "BrewsterWindow", "CatalogWavePlate",
                     "CatalogPolarizer", "CatalogGlanPolarizer"),
    "Filters & apertures": ("Filter", "NDFilter", "CatalogFilter", "CatalogNDFilter", "Iris", "Pinhole", "ApertureStop",
                            "SpectrometerSlit", "Block", "BeamDump", "Razor", "OpticalChopper"),
    "Prisms, gratings & modulators": ("Prism", "RightAnglePrism", "Pentaprism", "WedgePlate", "Grating", "NonlinearCrystal",
                                      "EOM", "AOM", "SLM", "DMD", "ModeCleaner"),
    "Fiber": ("FiberCollimator", "CatalogCollimator", "FiberPort", "FiberCoupler", "FiberCirculator", "FiberSpool",
              "FiberAmplifier", "PolarizationController", "VariableAttenuator", "CatalogSleeve"),
    "Detectors & cameras": ("Photodiode", "CatalogPhotodiode", "AmplifiedPhotodetector", "BalancedDetector",
                            "QuadrantPhotodiode", "PMT", "SNSPD", "PhotonCounter", "SPADArray", "Camera", "CMOSCamera",
                            "EMCCD", "CameraSensor", "CatalogCamera", "PowerMeter", "OpticalPowerMeter", "Spectrometer",
                            "Monochromator", "OSA"),
    "Cage system": ("CageCube", "CageRods", "CageRightAngleMirror", "CageWavePlate", "CageTower", "CatalogCageMount",
                    "CatalogCageCube", "CatalogRightAngleMount"),
    "Mounts & hardware": ("KinematicMount", "OpticalPost", "PlatformMount", "TranslationStage", "RotationStage",
                          "Periscope", "LensTube", "CatalogLensTube", "CatalogAdapter", "CatalogHardware",
                          "CatalogTableClamp"),
    "Tables & breadboards": ("OpticalTable", "Breadboard", "Baseplate"),
    "Samples & cryostats": ("Sample", "Cryostat", "CryostatWindow", "CryostatCabinet", "VacuumChamber", "VacuumPump"),
}

# On-chip groups, by a word in the part's name, any case (first match wins)
ON_CHIP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Couplers & I/O", ("GratingCoupler", "EdgeCoupler", "OpticalIOBank", "GratingAntenna", "PresetWDMInput")),
    ("Lasers, sources & amplifiers", ("Laser", "FrequencyComb", "SOA")),
    ("Detectors & receivers", ("Photodetector", "TIA")),
    ("Modulators & phase shifters", ("Modulator", "MZM", "IQ", "PhaseShifter", "PCMCell")),
    ("Resonators & interferometers", ("Ring", "Racetrack", "MZI", "Sagnac", "Bragg", "WeightBank")),
    ("Splitters & multiplexers", ("MMI", "YBranch", "DirectionalCoupler", "AdiabaticCoupler", "TapCoupler", "AWG",
                                  "StarCoupler", "Echelle", "Polarization")),
    ("Waveguides", ("Waveguide", "Taper", "Spiral", "Terminator")),
    ("Electronics on chip", ("ADC", "DAC")),
    ("Substrate", ("ChipSubstrate",)),
)

# Electronics groups, by a word in the part's name, any case (first match wins); instruments first, so a lock-in
# amplifier is an instrument, not an RF amplifier
ELECTRONICS_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Instruments", ("Oscilloscope", "VNA", "SMU", "LockIn", "WaveformGenerator", "RFSpectrumAnalyzer", "DAQ",
                     "Computer", "CoincidenceCounter", "LaserDriver")),
    ("Circuit parts", ("Resistor", "Capacitor", "Inductor", "OpAmp", "Ground", "SummingJunction", "SignalArrow")),
    ("RF parts", ("RF", "BiasTee", "SignalSource", "SMAConnector", "Amplifier")),
    ("Receivers & transmitters", ("Receiver", "Transmitter", "TIABlock", "BalancedPhotodetector")),
    ("Chips & boards", ("EIC", "PCB", "Microcontroller", "FPGA", "ADCBlock", "DAC", "MEMS")),
    ("Pads, probes & packaging", ("Pad", "IOBank", "FiberArray", "MetalRoute")),
    ("Control", ("PIDController",)),
)

_FREE_SPACE = {name: group for group, names in FREE_SPACE_GROUPS.items() for name in names}


def _by_rules(name: str, rules) -> str | None:
    lowered = name.lower()
    for group, words in rules:
        if any(word.lower() in lowered for word in words):
            return group
    return None


def palette_place(name: str, category: str) -> tuple[str, str]:
    """(section, group) of a part in the parts menu, from its name and catalogue category."""

    if category == "my_parts":
        return "My parts", "My parts"
    if category == "annotation":
        return "Annotations", "Marks & notes"
    if name in _FREE_SPACE:
        return "Free-space optics", _FREE_SPACE[name]
    if category == "on_chip":
        return "On-chip photonics", _by_rules(name, ON_CHIP_RULES) or "Other on-chip parts"
    if category in ("electronics", "instruments"):
        group = _by_rules(name, ELECTRONICS_RULES)
        if group:
            return "Electronics", group
        if category == "instruments":                  # an optical instrument (OSA, power meter) stays with the optics
            return "Free-space optics", "Detectors & cameras"
        return "Electronics", "Other electronics"
    if category in ("optics", "devices", "samples", "misc"):
        return "Free-space optics", "Other free-space parts"
    return "Free-space optics", "Other free-space parts"
