"""Unified component registry for discovery and instantiation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_REGISTRY: dict[str, ComponentSpec] = {}


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    cls: type
    category: str
    platform: str
    description: str
    parameters: tuple[str, ...]
    creatable: bool = True
    physics_modes: tuple[str, ...] = ("diagram",)
    visual_only: bool = False
    schematic_default: bool = False
    supports_render_physical: bool = False
    supports_physical_spec: bool = False


_CATEGORY_PHYSICS_DEFAULTS: dict[str, dict[str, Any]] = {
    "optics": {"physics_modes": ("diagram", "ray", "paraxial"), "visual_only": False},
    "devices": {"physics_modes": ("diagram", "ray"), "visual_only": False},
    "on_chip": {
        "physics_modes": ("diagram",),
        "visual_only": False,
        "schematic_default": True,
        "supports_render_physical": True,
        "supports_physical_spec": True,
    },
    "electronics": {"physics_modes": ("diagram",), "visual_only": True},
    "misc": {"physics_modes": ("diagram",), "visual_only": True},
    "samples": {"physics_modes": ("diagram",), "visual_only": True},
    "models": {"physics_modes": ("diagram",), "visual_only": True},
    "instruments": {"physics_modes": ("diagram",), "visual_only": True},
    "light_paths": {"physics_modes": ("diagram",), "visual_only": False},
    "routing": {"physics_modes": ("diagram",), "visual_only": False},
}


#: component types that EMIT light (drive Trace mode, auto-join lit scenes)
SOURCE_COMPONENT_TYPES = frozenset({"Laser", "FiberLaser", "Lamp"})

_BUILTIN_METADATA: dict[str, dict[str, Any]] = {
    "Lens": {"category": "optics", "platform": "free_space", "description": "Thin lens", "parameters": ["center", "angle", "radius", "aperture", "focal_length", "label"]},
    "AsphericLens": {"category": "optics", "platform": "free_space", "description": "Aspheric singlet lens with conic/asphere metadata", "parameters": ["center", "angle", "aperture", "focal_length", "radius", "conic_constant", "asphere_coefficients", "numerical_aperture", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "CylindricalLens": {"category": "optics", "platform": "free_space", "description": "Cylindrical lens with single-axis focusing metadata", "parameters": ["center", "angle", "aperture", "length", "focal_length", "cylinder_axis", "thickness", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "Telescope": {"category": "optics", "platform": "free_space", "description": "Two-lens telescope or beam relay with magnification metadata", "parameters": ["center", "angle", "focal_length_1", "focal_length_2", "input_aperture", "output_aperture", "spacing", "telescope_type", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "FourFSystem": {"category": "optics", "platform": "free_space", "description": "Two-lens 4f relay with object, Fourier, and image plane metadata", "parameters": ["center", "angle", "focal_length_1", "focal_length_2", "aperture", "lens_spacing", "include_planes", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "Mirror": {"category": "optics", "platform": "free_space", "description": "Reflective mirror with flat, concave, convex, biconcave, or biconvex surface profiles; piezo='stack' or '3axis' mounts it on piezo actuators with a pzt drive port", "parameters": ["center", "angle", "aperture", "thickness", "surface_type", "curvature_depth", "focal_length", "piezo", "label"]},
    "FlipMirror": {"category": "optics", "platform": "free_space", "description": "Mirror on a flip mount: up in the beam, down out of it", "parameters": ["center", "angle", "aperture", "thickness", "state", "out_offset"]},
    "ConcaveMirror": {"category": "optics", "platform": "free_space", "description": "Concave reflective mirror convenience component", "parameters": ["center", "angle", "aperture", "thickness", "curvature_depth", "focal_length", "piezo", "label"]},
    "ConvexMirror": {"category": "optics", "platform": "free_space", "description": "Convex reflective mirror convenience component", "parameters": ["center", "angle", "aperture", "thickness", "curvature_depth", "focal_length", "piezo", "label"]},
    "BiconcaveMirror": {"category": "optics", "platform": "free_space", "description": "Double-sided concave mirror visual", "parameters": ["center", "angle", "aperture", "thickness", "curvature_depth", "focal_length", "piezo", "label"]},
    "BiconvexMirror": {"category": "optics", "platform": "free_space", "description": "Double-sided convex mirror visual", "parameters": ["center", "angle", "aperture", "thickness", "curvature_depth", "focal_length", "piezo", "label"]},
    "BeamSplitter": {"category": "optics", "platform": "free_space", "description": "Plate beam splitter or dichroic: a coated glass plate; transmission is the percent that passes", "parameters": ["center", "angle", "aperture", "dichroic", "transmission", "cutoff_wavelength", "label"]},
    "PartialMirror": {"category": "optics", "platform": "free_space", "description": "Partial mirror (partially reflecting): an output coupler or a cavity input or recycling mirror; transmission is the percent that passes", "parameters": ["center", "angle", "aperture", "thickness", "transmission", "label"]},
    "NDFilter": {"category": "optics", "platform": "free_space", "description": "Neutral density filter or ND wheel", "parameters": ["center", "angle", "aperture", "optical_density", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "Filter": {"category": "optics", "platform": "free_space", "description": "Optical filter", "parameters": ["center", "angle", "aperture", "cutoff_wavelength", "pass_band", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "Grating": {"category": "optics", "platform": "free_space", "description": "Diffraction grating", "parameters": ["center", "angle", "aperture", "pitch", "label"], "physics_modes": ("diagram", "ray")},
    "Objective": {"category": "optics", "platform": "free_space", "description": "Microscope objective", "parameters": ["center", "angle", "aperture", "length", "magnification", "mag", "working_distance", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "Prism": {"category": "optics", "platform": "free_space", "description": "Dispersive prism with apex-angle and material metadata (ray refraction stub)", "parameters": ["center", "angle", "size", "apex_angle", "refractive_index", "label"], "physics_modes": ("diagram", "ray")},
    "GlanLaserPolarizer": {"category": "optics", "platform": "free_space", "description": "Glan-Laser prism polarizer: p passes straight, s leaves through the side window", "parameters": ["center", "angle", "length", "aperture", "reject_angle_deg", "extinction_ratio", "label"], "physics_modes": ("diagram", "ray", "polarization")},
    "Polarizer": {"category": "optics", "platform": "free_space", "description": "Linear polarizer with transmission-axis metadata", "parameters": ["center", "angle", "aperture", "axis_angle", "extinction_ratio", "label"], "physics_modes": ("diagram", "ray", "paraxial", "polarization")},
    "Analyzer": {"category": "optics", "platform": "free_space", "description": "Analyzer polarizer for measurement arms", "parameters": ["center", "angle", "aperture", "axis_angle", "extinction_ratio", "label"], "physics_modes": ("diagram", "ray", "paraxial", "polarization")},
    "WavePlate": {"category": "optics", "platform": "free_space", "description": "Retarder plate with retardance and fast-axis metadata", "parameters": ["center", "angle", "aperture", "retardance", "fast_axis_angle", "label"], "physics_modes": ("diagram", "ray", "paraxial", "polarization")},
    "HalfWavePlate": {"category": "optics", "platform": "free_space", "description": "Half-wave plate convenience component", "parameters": ["center", "angle", "aperture", "fast_axis_angle", "label"], "physics_modes": ("diagram", "ray", "paraxial", "polarization")},
    "QuarterWavePlate": {"category": "optics", "platform": "free_space", "description": "Quarter-wave plate convenience component", "parameters": ["center", "angle", "aperture", "fast_axis_angle", "label"], "physics_modes": ("diagram", "ray", "paraxial", "polarization")},
    "PBS": {"category": "optics", "platform": "free_space", "description": "Polarizing beam splitter cube", "parameters": ["center", "angle", "aperture", "split_ratio", "label"], "physics_modes": ("diagram", "ray", "paraxial", "polarization")},
    "NonPolarizingBeamSplitter": {"category": "optics", "platform": "free_space", "description": "Non-polarizing beam splitter cube with split-ratio metadata", "parameters": ["center", "angle", "aperture", "split_ratio", "label"]},
    "DichroicMirror": {"category": "optics", "platform": "free_space", "description": "Wavelength-selective mirror with reflection/transmission metadata", "parameters": ["center", "angle", "aperture", "cutoff_wavelength", "pass_band", "reflects", "transmits", "label"]},
    "FiberPort": {"category": "optics", "platform": "free_space", "description": "Bare fiber endpoint or ferrule visual", "parameters": ["center", "angle", "core_diameter", "cladding_diameter", "length", "label"]},
    "FiberCollimator": {"category": "optics", "platform": "free_space", "description": "Fiber collimator with ferrule, barrel, lens, and focal metadata", "parameters": ["center", "angle", "aperture", "length", "focal_length", "label"]},
    "PolarizationController": {"category": "optics", "platform": "free_space", "description": "Fibre polarization controller: a fibre wound on paddles, fibre in and fibre out", "parameters": ["center", "angle", "length", "paddle_diameter", "paddles", "label"]},
    "FiberAmplifier": {"category": "optics", "platform": "free_space", "description": "Doped-fibre amplifier (EDFA): fibre in, amplified fibre out, with gain metadata", "parameters": ["center", "angle", "length", "gain_db", "doping", "label"]},
    "FiberCirculator": {"category": "optics", "platform": "free_space", "description": "Three-port fibre circulator: p1 to p2, p2 to p3", "parameters": ["center", "angle", "size", "label"]},
    "FiberCoupler": {"category": "optics", "platform": "free_space", "description": "Fused 2x2 fibre coupler with a split ratio", "parameters": ["center", "angle", "length", "port_gap", "ratio", "label"]},
    "FiberSpool": {"category": "optics", "platform": "free_space", "description": "Spool of fibre for a delay line or a fibre link, with its length in km", "parameters": ["center", "angle", "diameter", "fiber_length_km", "label"]},
    "VariableAttenuator": {"category": "optics", "platform": "free_space", "description": "Variable optical attenuator (VOA) in a fibre line", "parameters": ["center", "angle", "length", "attenuation_db", "label"]},
    "Iris": {"category": "optics", "platform": "free_space", "description": "Adjustable iris aperture with blade metadata", "parameters": ["center", "angle", "outer_diameter", "aperture_diameter", "blade_count", "label"]},
    "Pinhole": {"category": "optics", "platform": "free_space", "description": "Fixed pinhole aperture", "parameters": ["center", "angle", "outer_diameter", "aperture_diameter", "label"]},
    "ApertureStop": {"category": "optics", "platform": "free_space", "description": "Fixed aperture stop for paraxial and publication diagrams", "parameters": ["center", "angle", "outer_diameter", "aperture_diameter", "label"]},
    "SLM": {"category": "optics", "platform": "free_space", "description": "Spatial light modulator with active-area, pixel, fill-factor, and mode metadata", "parameters": ["center", "angle", "active_width", "active_height", "pixel_pitch", "resolution", "fill_factor", "mode", "label"]},
    "GalvoMirror": {"category": "optics", "platform": "free_space", "description": "Scanning galvo mirror with scan-range and drive-frequency metadata", "parameters": ["center", "angle", "aperture", "mirror_width", "scan_range_deg", "drive_frequency_khz", "label"], "physics_modes": ("diagram", "ray")},
    "AOM": {"category": "optics", "platform": "free_space", "description": "Acousto-optic modulator with center frequency and diffraction-efficiency metadata", "parameters": ["center", "angle", "aperture", "interaction_length", "center_frequency_mhz", "diffraction_efficiency", "label"], "physics_modes": ("diagram", "ray")},
    "EOM": {"category": "optics", "platform": "free_space", "description": "Electro-optic modulator crystal with half-wave voltage and bandwidth metadata", "parameters": ["center", "angle", "aperture", "crystal_length", "half_wave_voltage_v", "bandwidth_ghz", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "DMD": {"category": "optics", "platform": "free_space", "description": "Digital micromirror device with active-area and tilt metadata", "parameters": ["center", "angle", "active_width", "active_height", "resolution", "tilt_angle_deg", "fill_factor", "label"], "physics_modes": ("diagram", "ray")},
    "CameraSensor": {"category": "optics", "platform": "free_space", "description": "Generic camera sensor face with pixel, QE, and read-noise metadata", "parameters": ["center", "angle", "sensor_width", "sensor_height", "pixel_pitch_um", "resolution", "sensor_kind", "label"], "physics_modes": ("diagram", "ray")},
    "CMOSCamera": {"category": "optics", "platform": "free_space", "description": "CMOS camera specialization with low read-noise defaults", "parameters": ["center", "angle", "sensor_width", "sensor_height", "pixel_pitch_um", "resolution", "label"], "physics_modes": ("diagram", "ray")},
    "EMCCD": {"category": "optics", "platform": "free_space", "description": "EMCCD camera specialization with electron-multiplication gain metadata", "parameters": ["center", "angle", "sensor_width", "sensor_height", "pixel_pitch_um", "resolution", "em_gain", "label"], "physics_modes": ("diagram", "ray")},
    "SPADArray": {"category": "optics", "platform": "free_space", "description": "Single-photon avalanche diode array specialization with dead-time metadata", "parameters": ["center", "angle", "sensor_width", "sensor_height", "pixel_pitch_um", "resolution", "dead_time_ns", "max_count_rate_mhz", "label"], "physics_modes": ("diagram", "ray")},
    "PowerMeter": {"category": "optics", "platform": "free_space", "description": "Inline power meter stub with spectral and responsivity metadata", "parameters": ["center", "angle", "aperture", "length", "spectral_min_nm", "spectral_max_nm", "responsivity_a_per_w", "label"]},
    "OpticalTable": {"category": "optics", "platform": "free_space", "description": "Optical table or breadboard base with hole-grid metadata", "parameters": ["center", "angle", "length", "width", "thickness", "hole_pitch", "include_holes", "label"]},
    "Breadboard": {"category": "optics", "platform": "free_space", "description": "Compact optical breadboard: a small black table with a hole grid", "parameters": ["center", "angle", "length", "width", "thickness", "hole_pitch", "include_holes", "label"]},
    "Baseplate": {"category": "optics", "platform": "free_space", "description": "Modular optical baseplate: a machined sub-plate with a mount-hole grid that anchors a free-space subsystem at a fixed beam (optical) height (visualization only, no machining geometry)", "parameters": ["center", "angle", "length", "width", "thickness", "hole_pitch", "optical_height", "include_holes", "label"]},
    "Retroreflector": {"category": "optics", "platform": "free_space", "description": "Corner-cube retroreflector: returns any incoming beam back parallel to itself", "parameters": ["center", "angle", "aperture", "label"]},
    "BeamDump": {"category": "optics", "platform": "free_space", "description": "Beam dump / block: a horned cavity absorber that safely terminates a laser beam", "parameters": ["center", "angle", "aperture", "label"]},
    "OpticalChopper": {"category": "optics", "platform": "free_space", "description": "Rotating slotted-wheel optical chopper for lock-in detection", "parameters": ["center", "angle", "wheel_diameter", "blades", "label"]},
    "Pentaprism": {"category": "optics", "platform": "free_space", "description": "Pentaprism: deviates a beam by a constant 90\u00b0 regardless of tilt", "parameters": ["center", "angle", "size", "refractive_index", "label"], "physics_modes": ("diagram", "ray")},
    "NonlinearCrystal": {"category": "optics", "platform": "free_space", "description": "Nonlinear crystal (BBO, LBO, PPKTP, PPLN) for harmonics, photon pairs or white light; poled draws its domains in an oven", "parameters": ["center", "angle", "length", "aperture", "material", "process", "poled", "label"]},
    "WollastonPrism": {"category": "optics", "platform": "free_space", "description": "Wollaston prism: two crossed birefringent wedges send the two polarizations apart by separation_deg", "parameters": ["center", "angle", "length", "aperture", "separation_deg", "extinction_ratio", "label"]},
    "OpticalIsolator": {"category": "optics", "platform": "free_space", "description": "Free-space Faraday optical isolator (one-way light valve) with magnet barrel and polarizer caps", "parameters": ["center", "angle", "aperture", "length", "isolation_db", "label"]},
    "LensTube": {"category": "optics", "platform": "free_space", "description": "Threaded SM-style lens tube for stacking optics into an assembly", "parameters": ["center", "angle", "diameter", "length", "label"]},
    "BrewsterWindow": {"category": "optics", "platform": "free_space", "description": "Brewster-angle window in a slotted mount: passes p-polarised light without reflection loss", "parameters": ["center", "angle", "aperture", "thickness", "window_angle_deg", "label"], "physics_modes": ("diagram", "ray", "paraxial", "polarization")},
    "PlatformMount": {"category": "optics", "platform": "free_space", "description": "Kinematic platform / prism mount (L-bracket) that carries an AOM, prism, or grating; sits flat on the table", "parameters": ["center", "angle", "platform", "height", "label"]},
    "Periscope": {"category": "optics", "platform": "free_space", "description": "Periscope: two 45 deg mirrors on a vertical rail that move the beam between heights, with a top plate for an objective", "parameters": ["center", "angle", "rise", "output_angle_deg", "aperture", "post_diameter", "label"]},
    "OpticalPost": {"category": "optics", "platform": "free_space", "description": "Optical post / pedestal (base clamp + post-holder + post) that raises an optic to the beam height above the table: the standing breadboard hardware (visualization only)", "parameters": ["center", "angle", "height", "post_diameter", "base_size", "label"]},
    "TranslationStage": {"category": "optics", "platform": "free_space", "description": "Linear translation stage with travel-range metadata", "parameters": ["center", "angle", "length", "width", "travel_range_mm", "axis", "label"]},
    "RotationStage": {"category": "optics", "platform": "free_space", "description": "Rotary stage with angular-range metadata", "parameters": ["center", "angle", "diameter", "thickness", "rotation_range_deg", "angular_resolution_deg", "label"]},
    "KinematicMount": {"category": "optics", "platform": "free_space", "description": "Adjustable kinematic optic mount", "parameters": ["center", "angle", "optic_diameter", "base_width", "adjustment_range_deg", "label"]},
    "CryostatWindow": {"category": "optics", "platform": "free_space", "description": "Cryostat optical window with coating and thermal metadata", "parameters": ["center", "angle", "aperture", "thickness", "material", "temperature_k", "coating", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "VacuumChamber": {"category": "optics", "platform": "free_space", "description": "Vacuum chamber body with viewport and pressure metadata", "parameters": ["center", "angle", "diameter", "length", "viewport_diameter", "pressure_mbar", "window_count", "label"]},
    "SpectrometerSlit": {"category": "optics", "platform": "free_space", "description": "Entrance slit block with slit-width metadata", "parameters": ["center", "angle", "slit_width_um", "slit_height", "body_width", "label"]},
    "Monochromator": {"category": "optics", "platform": "free_space", "description": "Monochromator block with grating density and focal metadata", "parameters": ["center", "angle", "length", "width", "groove_density_l_mm", "focal_length_mm", "center_wavelength_nm", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "RightAnglePrism": {"category": "optics", "platform": "free_space", "description": "90-degree folding prism with in/out ports for beam steering diagrams", "parameters": ["center", "angle", "leg", "thickness", "refractive_index", "label"], "physics_modes": ("diagram", "ray")},
    "WedgePlate": {"category": "optics", "platform": "free_space", "description": "Wedged window with deviation-angle metadata for interferometer teaching sketches", "parameters": ["center", "angle", "aperture", "wedge_angle_deg", "thickness", "refractive_index", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "BeamExpanderTelescope": {"category": "optics", "platform": "free_space", "description": "Keplerian beam-expander telescope stub with magnification metadata", "parameters": ["center", "angle", "input_aperture", "output_aperture", "length", "magnification", "telescope_type", "label"], "physics_modes": ("diagram", "ray", "paraxial")},
    "Laser": {"category": "devices", "platform": "free_space", "description": "Laser source", "parameters": ["center", "angle", "wavelength", "beam_width", "rays", "ray_width", "beam_color", "divergence_deg", "show_envelope", "sync", "power_mw", "threshold_a", "slope_w_per_a", "label"]},
    "AmplifiedPhotodetector": {"category": "devices", "platform": "free_space", "description": "Amplified photodetector box with threaded input snout and BNC output", "parameters": ["center", "angle", "box_size", "gain_db", "responsivity_a_per_w", "dark_current_a", "bandwidth_hz", "gain_ohm", "label"]},
    "PMT": {"category": "devices", "platform": "free_space", "description": "Photomultiplier tube: high-gain single-photon detector (photocathode + dynode chain + HV base)", "parameters": ["center", "angle", "tube_diameter", "length", "gain", "label"]},
    "Lamp": {"category": "devices", "platform": "free_space", "description": "Broadband source", "parameters": ["center", "angle", "label"]},
    "Camera": {"category": "devices", "platform": "free_space", "description": "Camera detector", "parameters": ["center", "angle", "label"]},
    "Computer": {"category": "instruments", "platform": "free_space", "description": "Workstation: monitor, keyboard, and an electrical I/O port", "parameters": ["center", "angle", "label"]},
    "Oscilloscope": {"category": "instruments", "platform": "free_space", "description": "Bench oscilloscope with two BNC channel inputs", "parameters": ["center", "angle", "traces", "label"]},
    "SMU": {"category": "instruments", "platform": "free_space", "description": "Source-measure unit with HI/LO output jacks", "parameters": ["center", "angle", "label"]},
    "CoincidenceCounter": {"category": "instruments", "platform": "free_space", "description": "Coincidence counter: a pulse input per channel, a timing window, counts out to a computer", "parameters": ["center", "angle", "channels", "window_ns", "label"]},
    "FPGABoard": {"category": "instruments", "platform": "free_space", "description": "FPGA development board with GPIO ports", "parameters": ["center", "angle", "label"]},
    "OSA": {"category": "instruments", "platform": "free_space", "description": "Optical spectrum analyzer with a fiber input", "parameters": ["center", "angle", "trace", "label"]},
    "OpticalPowerMeter": {"category": "instruments", "platform": "free_space", "description": "Optical power meter with a fiber input", "parameters": ["center", "angle", "reading", "label"]},
    "WaveformGenerator": {"category": "instruments", "platform": "free_space", "description": "Arbitrary waveform generator with two outputs", "parameters": ["center", "angle", "label"]},
    "LaserDriver": {"category": "instruments", "platform": "free_space", "description": "Laser diode / TEC controller with a drive output", "parameters": ["center", "angle", "bias_a", "gain_a_per_v", "label"]},
    "DAQ": {"category": "instruments", "platform": "free_space", "description": "Data-acquisition module with screw-terminal channels", "parameters": ["center", "angle", "label"]},
    "VNA": {"category": "instruments", "platform": "free_space", "description": "Vector network analyzer with two RF ports", "parameters": ["center", "angle", "label"]},
    "LockInAmplifier": {"category": "instruments", "platform": "free_space", "description": "Lock-in amplifier: signal in, reference in, demodulated output X; a front panel with the phase knob", "parameters": ["center", "angle", "reading", "label"]},
    "VacuumPump": {"category": "instruments", "platform": "free_space", "description": "Vacuum pump (hook it to a cryostat with a free route)", "parameters": ["center", "angle", "label"]},
    "Cryostat": {"category": "samples", "platform": "free_space", "description": "Cryostat chamber with optical windows: the sample sits inside on a cold finger", "parameters": ["center", "angle", "radius", "label"]},
    "Photodiode": {"category": "devices", "platform": "free_space", "description": "Single-pixel detector", "parameters": ["center", "angle", "responsivity_a_per_w", "dark_current_a", "bandwidth_hz", "label"]},
    "QuadrantPhotodiode": {"category": "devices", "platform": "free_space", "description": "Quadrant photodiode for beam position: x, y and sum outputs, as in optical-trap detection", "parameters": ["center", "angle", "box_size", "active_diameter_mm", "label"]},
    "PhotonCounter": {"category": "devices", "platform": "free_space", "description": "Fibre-coupled single-photon counting module: a fibre in and a pulse out per channel", "parameters": ["center", "angle", "channels", "label"]},
    "SNSPD": {"category": "devices", "platform": "free_space", "description": "Superconducting nanowire single-photon detector: fibre in, electrical pulse out", "parameters": ["center", "angle", "length", "efficiency", "dark_count_hz", "temperature_k", "label"]},
    "Spectrometer": {"category": "devices", "platform": "free_space", "description": "Spectrometer", "parameters": ["center", "angle", "label"]},
    "Sample": {"category": "samples", "platform": "free_space", "description": "Sample mount", "parameters": ["center", "angle", "aperture", "in_cryostat", "label"]},
    "Note": {"category": "annotation", "platform": "mixed", "description": "Free text on a figure", "parameters": ["text", "center", "angle", "color", "anchor", "bold"]},
    "Callout": {"category": "annotation", "platform": "mixed", "description": "Text with a line to what it names", "parameters": ["text", "center", "angle", "target", "color", "anchor", "bold"]},
    "Bracket": {"category": "annotation", "platform": "mixed", "description": "A square bracket beside a span", "parameters": ["text", "center", "ends", "side", "clear", "depth", "color", "anchor", "bold", "reach"]},
    "Glyph": {"category": "annotation", "platform": "mixed", "description": "The state of the signal beside a beam", "parameters": ["kind", "center", "angle", "size", "color"]},
    "DashedLink": {"category": "annotation", "platform": "mixed", "description": "A thin line that ties two places", "parameters": ["text", "center", "ends", "side", "dashed", "arrow", "color", "anchor", "bold"]},
    "SectionMark": {"category": "annotation", "platform": "mixed", "description": "A cut line A to A′ on a 2D scene: where a cross-section is taken", "parameters": ["name", "center", "ends", "color"]},
    "Region": {"category": "annotation", "platform": "mixed", "description": "A dashed rounded box round a group of parts, with its name", "parameters": ["label", "center", "corners", "pad", "color", "bold"]},
    "Inset": {"category": "annotation", "platform": "mixed", "description": "A drawing set into a figure: a file, a plot or a section; with no source, an empty dashed box", "parameters": ["center", "angle", "width", "height", "frame", "letter"]},
    "ZoomLink": {"category": "annotation", "platform": "mixed", "description": "A box on one inset and two lines to a second inset that shows it closer", "parameters": ["small", "region", "big"]},
    "CutLink": {"category": "annotation", "platform": "mixed", "description": "A cut line A to A′ on a GDS inset and the same letters over the section it makes", "parameters": ["source", "a", "b", "section", "name"]},
    "Grid": {"category": "misc", "platform": "free_space", "description": "Reference grid", "parameters": ["pitch", "width", "height"]},
    "Block": {"category": "misc", "platform": "free_space", "description": "Beam block", "parameters": ["center", "angle", "size", "label"]},
    "Razor": {"category": "misc", "platform": "free_space", "description": "Knife-edge", "parameters": ["center", "angle", "blade_pos", "label"]},
    "Waveguide": {"category": "on_chip", "platform": "on_chip", "description": "Strip waveguide (schematic draw by default; ports stay physical µm)", "parameters": ["center", "angle", "length", "width", "effective_index", "pdk", "cross_section", "visual_style", "visual_scale", "render_physical", "label"]},
    "Spiral": {"category": "on_chip", "platform": "on_chip", "description": "Archimedean spiral waveguide delay line: both optical ports exit at the outer edge; length grows with turns/spacing", "parameters": ["center", "angle", "turns", "spacing", "inner_radius", "width", "label"]},
    "PhaseShifter": {"category": "on_chip", "platform": "on_chip", "description": "Straight waveguide with a thermo-optic (heater, h1/h2) or electro-optic (PN junction, e1/e2) phase shifter", "parameters": ["center", "angle", "length", "width", "mechanism", "shifter_length", "label"]},
    "GratingCouplerArray": {"category": "on_chip", "platform": "on_chip", "description": "Reusable array of upward-facing grating couplers with straight stubs and optional end alignment loop", "parameters": ["center", "angle", "count", "pitch", "coupler_kind", "align_ends", "stub_length", "alignment_drop", "with_fiber", "label"]},
    "VerticalGratingCoupler": {"category": "on_chip", "platform": "on_chip", "description": "Generic-PDK elliptical grating coupler with optional vertical fiber visual", "parameters": ["center", "angle", "length", "width", "taper_length", "tooth_count", "coupling_angle_deg", "with_fiber", "fiber_length", "pdk", "label"]},
    "FocusedApodizedGratingCoupler": {"category": "on_chip", "platform": "on_chip", "description": "Focused apodized grating coupler with curved teeth, tapered fan-out, and optional fiber visual", "parameters": ["center", "angle", "taper_length", "taper_angle", "tooth_count", "with_fiber", "fiber_length", "label"]},
    "EdgeCoupler": {"category": "on_chip", "platform": "on_chip", "description": "Inverse-taper edge coupler with oxide mode expander and optional edge fiber", "parameters": ["center", "angle", "taper_length", "cladding_length", "tip_width", "waveguide_width", "with_fiber", "fiber_length", "label"]},
    "MMI1x2": {"category": "on_chip", "platform": "on_chip", "description": "1x2 MMI splitter from generic-PDK dimensions", "parameters": ["center", "angle", "body_length", "body_width", "taper_length", "label"]},
    "MMI1x3": {"category": "on_chip", "platform": "on_chip", "description": "1x3 MMI splitter", "parameters": ["center", "angle", "body_length", "body_width", "taper_length", "label"]},
    "MMI1x4": {"category": "on_chip", "platform": "on_chip", "description": "1x4 MMI splitter", "parameters": ["center", "angle", "body_length", "body_width", "taper_length", "label"]},
    "MMI2x2": {"category": "on_chip", "platform": "on_chip", "description": "2x2 MMI coupler from generic-PDK dimensions", "parameters": ["center", "angle", "body_length", "body_width", "taper_length", "label"]},
    "MMI2x2PowerSplitter": {"category": "on_chip", "platform": "on_chip", "description": "2x2 balanced MMI power splitter", "parameters": ["center", "angle", "body_length", "body_width", "taper_length", "label"]},
    "YBranch": {"category": "on_chip", "platform": "on_chip", "description": "Adiabatic Y-branch splitter", "parameters": ["center", "angle", "branch_length", "stem_length", "branch_gap", "label"]},
    "DirectionalCoupler": {"category": "on_chip", "platform": "on_chip", "description": "Directional coupler with cosine-eased S-bends into a parallel coupling section", "parameters": ["center", "angle", "coupling_length", "transition_length", "port_spacing", "label"]},
    "MicroringResonator": {"category": "on_chip", "platform": "on_chip", "description": "True circular microring resonator with optional add-drop and heater metal", "parameters": ["center", "angle", "ring_radius", "gap", "add_drop", "with_heater", "heater_resistance_ohm", "label"], "physics_modes": ("diagram", "modulation")},
    "PNMicroringModulator": {"category": "on_chip", "platform": "on_chip", "description": "PN-junction microring modulator with top contact pads", "parameters": ["center", "angle", "ring_radius", "gap", "add_drop", "label"], "physics_modes": ("diagram", "modulation")},
    "CoupledRingFilter": {"category": "on_chip", "platform": "on_chip", "description": "Series-coupled microring filter of order 1 to 8: rings in a column between two buses, optional heater per ring", "parameters": ["center", "angle", "order", "ring_shape", "radius", "coupling_length", "gaps", "waveguide_width", "with_heaters", "power_couplings", "round_trip_amplitude", "label"]},
    "MicroringWeightBank": {"category": "on_chip", "platform": "on_chip", "description": "Multi-ring weight bank with 180-degree bent drop outputs and optional heater pads", "parameters": ["center", "angle", "ring_count", "ring_pitch", "ring_radius", "with_heaters", "label"]},
    # Compact blocks the preset chips are laid out around. Registered because a
    # component that only exists inside presets.py cannot be rebuilt from a
    # saved scene: the editor answered 500 when a preset used one.
    "PresetWDMInput": {"category": "on_chip", "platform": "on_chip", "description": "Compact wavelength-division input block", "parameters": ["center", "angle", "width", "body_length", "taper_length", "waveguide_width", "wavelengths_nm", "channel_powers", "label"]},
    "RacetrackResonator": {"category": "on_chip", "platform": "on_chip", "description": "Racetrack resonator with optional add-drop bus and thermal heater", "parameters": ["center", "angle", "bend_radius", "coupling_length", "add_drop", "with_heater", "label"], "physics_modes": ("diagram", "modulation")},
    "GratingAntennaArray": {"category": "on_chip", "platform": "on_chip", "description": "Optical phased array emitters: parallel waveguides on a pitch, each with a shallow-etched grating that sends the light up out of the chip", "parameters": ["center", "angle", "count", "pitch", "length", "period", "etch_depth", "waveguide_width", "label"]},
    "PCMCell": {"category": "on_chip", "platform": "on_chip", "description": "Phase-change (GST) cell on a waveguide: a non-volatile absorber whose state, crystalline or amorphous, sets how much light passes", "parameters": ["center", "angle", "length", "cell_length", "waveguide_width", "state", "label"]},
    "EORacetrackModulator": {"category": "on_chip", "platform": "on_chip", "description": "Electro-optic (Pockels) racetrack with gold G-S-G electrodes on both straights and a bus at one bend: a thin-film lithium niobate comb generator or ring modulator", "parameters": ["center", "angle", "straight_length", "bend_radius", "waveguide_width", "gap", "electrode_gap", "electrode_width", "label"]},
    "RacetrackModulator": {"category": "on_chip", "platform": "on_chip", "description": "Add-drop racetrack modulator with active straight, electrical pads, and optional thermal-bias heater", "parameters": ["center", "angle", "bend_radius", "coupling_length", "electrode_length", "with_heater", "label"]},
    "MZI": {"category": "on_chip", "platform": "on_chip", "description": "Mach-Zehnder interferometer built from directional couplers and balanced arms", "parameters": ["center", "angle", "arm_length", "arm_gap", "label"], "physics_modes": ("diagram", "guided")},
    "RingAssistedMZI": {"category": "on_chip", "platform": "on_chip", "description": "Ring-assisted Mach-Zehnder interferometer: microrings side-coupled to the arms make a sharp, flat-top filter", "parameters": ["center", "angle", "rings_per_arm", "ring_radius", "ring_gap", "arm_length", "arm_gap", "coupler", "with_heaters", "label"], "physics_modes": ("diagram",)},
    "MZM": {"category": "on_chip", "platform": "on_chip", "description": "Mach-Zehnder modulator: electro-optic (GS/GSG PN electrodes) or thermo-optic (heater); 1-input Y-branch or 2-input directional-coupler I/O", "parameters": ["center", "angle", "arm_length", "arm_gap", "mechanism", "drive_style", "splitter", "label"], "physics_modes": ("diagram", "guided", "modulation")},
    "IQModulator": {"category": "on_chip", "platform": "on_chip", "description": "Nested Mach-Zehnder IQ modulator: I and Q MZMs in an outer interferometer with a 90 degree bias heater", "parameters": ["center", "angle", "arm_gap", "bend_length", "label"]},
    "OnChipPhotodetector": {"category": "on_chip", "platform": "on_chip", "description": "Ge-on-Si style photodetector with electrical contact pads", "parameters": ["center", "angle", "length", "taper_length", "pad_width", "responsivity_a_per_w", "dark_current_a", "bandwidth_hz", "label"]},
    "OnChipBalancedPhotodetector": {"category": "on_chip", "platform": "on_chip", "description": "Two waveguide-fed photodetectors in series at a balanced node (two optical inputs, one difference output)", "parameters": ["center", "angle", "detector_gap", "label"]},
    "OnChipLaser": {"category": "on_chip", "platform": "on_chip", "description": "Hybrid DFB-style on-chip laser with segmented cavity, gratings, taper, and top metal pads", "parameters": ["center", "angle", "cavity_length", "ridge_width", "output_taper_length", "wavelength_nm", "power_mw", "threshold_a", "slope_w_per_a", "label"]},
    "FrequencyComb": {"category": "on_chip", "platform": "on_chip", "description": "On-chip frequency comb source: the on-chip laser with equally spaced output lines", "parameters": ["center", "angle", "line_spacing_ghz", "line_count", "label"]},
    "SOA": {"category": "on_chip", "platform": "on_chip", "description": "Semiconductor optical amplifier with tapered I/O, gain stripe, and bond pads", "parameters": ["center", "angle", "amplifier_length", "taper_length", "ridge_width", "label"]},
    "TIA": {"category": "on_chip", "platform": "on_chip", "description": "Transimpedance amplifier block for photodetector readout", "parameters": ["center", "angle", "length", "width", "label"]},
    "DACDriver": {"category": "on_chip", "platform": "on_chip", "description": "Differential DAC driver block for modulators", "parameters": ["center", "angle", "length", "width", "output_gap", "label"]},
    "ADC": {"category": "on_chip", "platform": "on_chip", "description": "Analog-to-digital converter block for electrical readout chains", "parameters": ["center", "angle", "length", "width", "label"]},
    "OpticalIOBank": {"category": "on_chip", "platform": "on_chip", "description": "Repeated optical I/O bank with routeable optical and optional fiber ports", "parameters": ["center", "angle", "count", "pitch", "coupler_kind", "side", "stub_length", "port_width", "fiber_port_width", "with_fibers", "visual_style", "visual_scale", "render_physical", "label"]},
    "StarCoupler": {"category": "on_chip", "platform": "on_chip", "description": "Free-propagation star coupler slab with multiple optical inputs and outputs", "parameters": ["center", "angle", "input_count", "output_count", "slab_length", "slab_width", "port_spacing", "waveguide_width", "visual_style", "visual_scale", "render_physical", "label"]},
    "AWG": {"category": "on_chip", "platform": "on_chip", "description": "Arrayed waveguide grating demultiplexer with channel and FSR metadata", "parameters": ["center", "angle", "channel_count", "array_count", "channel_spacing", "slab_length", "slab_width", "array_length", "free_spectral_range_nm", "channel_spacing_nm", "center_wavelength_nm", "waveguide_width", "visual_style", "visual_scale", "render_physical", "label"], "physics_modes": ("diagram", "wavelength")},
    "AWGR": {"category": "on_chip", "platform": "on_chip", "description": "Cyclic arrayed-waveguide grating router with multiple input and output channels", "parameters": ["center", "angle", "channel_count", "array_count", "dummy_count", "channel_spacing", "fpr_length", "fpr_width", "fpr_separation", "array_height", "tilt_deg", "free_spectral_range_nm", "channel_spacing_nm", "center_wavelength_nm", "waveguide_width", "aperture_width", "visual_style", "visual_scale", "render_physical", "label"]},
    "BraggGrating": {"category": "on_chip", "platform": "on_chip", "description": "Straight Bragg grating with period, center wavelength, and reflectivity metadata", "parameters": ["center", "angle", "length", "period", "corrugation_width", "waveguide_width", "center_wavelength_nm", "reflectivity", "visual_style", "visual_scale", "render_physical", "label"], "physics_modes": ("diagram", "wavelength")},
    "SagnacLoop": {"category": "on_chip", "platform": "on_chip", "description": "Sagnac loop mirror schematic with coupler and loop geometry", "parameters": ["center", "angle", "loop_radius", "coupler_length", "port_spacing", "waveguide_width", "visual_style", "visual_scale", "render_physical", "label"]},
    "Taper": {"category": "on_chip", "platform": "on_chip", "description": "Linear width taper / spot-size converter between two waveguide widths", "parameters": ["center", "angle", "length", "width1", "width2", "label"]},
    "WaveguideBend": {"category": "on_chip", "platform": "on_chip", "description": "Circular 90° waveguide bend (rotate to reorient); connects a west port to a north port", "parameters": ["center", "angle", "radius", "width", "angle_deg", "label"]},
    "WaveguideCrossing": {"category": "on_chip", "platform": "on_chip", "description": "Symmetric + waveguide crossing with tapered arms and a central expansion for low crosstalk", "parameters": ["center", "angle", "arm_length", "waveguide_width", "taper_width", "center_size", "label"]},
    "Terminator": {"category": "on_chip", "platform": "on_chip", "description": "Inverse-taper waveguide terminator that radiates unused light into the cladding (low back-reflection)", "parameters": ["center", "angle", "length", "width", "tip_width", "label"]},
    "TapCoupler": {"category": "on_chip", "platform": "on_chip", "description": "Asymmetric directional-coupler power tap (e.g. 1%/99%) for monitoring a bus", "parameters": ["center", "angle", "coupling_length", "transition_length", "port_spacing", "waveguide_gap", "tap_ratio", "label"]},
    "AdiabaticCoupler": {"category": "on_chip", "platform": "on_chip", "description": "Broadband adiabatic 3 dB coupler: wavelength-insensitive 50:50 splitting from two mismatched guides", "parameters": ["center", "angle", "coupling_length", "transition_length", "port_spacing", "waveguide_gap", "width_mismatch", "label"]},
    "PolarizationRotator": {"category": "on_chip", "platform": "on_chip", "description": "Mode-evolution polarization rotator (asymmetric bi-level waveguide, TE↔TM)", "parameters": ["center", "angle", "length", "width", "rib_width", "label"], "physics_modes": ("diagram", "polarization")},
    "PolarizationSplitterRotator": {"category": "on_chip", "platform": "on_chip", "description": "Polarization splitter-rotator (PSR): one input → TE output + rotated TM output", "parameters": ["center", "angle", "length", "port_spacing", "rotator_length", "waveguide_width", "label"], "physics_modes": ("diagram", "polarization")},
    "TwoDGratingCoupler": {"category": "on_chip", "platform": "on_chip", "description": "Polarization-splitting 2D grating coupler: fiber couples into two perpendicular waveguides", "parameters": ["center", "angle", "body_size", "taper_length", "waveguide_width", "hole_rows", "with_fiber", "fiber_length", "label"], "physics_modes": ("diagram", "polarization")},
    "ElectroAbsorptionModulator": {"category": "on_chip", "platform": "on_chip", "description": "Electro-absorption modulator (EAM): compact reverse-biased active waveguide with two contacts", "parameters": ["center", "angle", "length", "active_length", "waveguide_width", "pad_size", "label"], "physics_modes": ("diagram", "modulation")},
    "DBRLaser": {"category": "on_chip", "platform": "on_chip", "description": "Distributed-Bragg-reflector laser: gain ridge bounded by two grating mirrors, output taper, top contacts", "parameters": ["center", "angle", "gain_length", "dbr_length", "ridge_width", "output_taper_length", "waveguide_width", "pad_size", "tooth_count", "label"]},
    "AvalanchePhotodetector": {"category": "on_chip", "platform": "on_chip", "description": "Waveguide avalanche photodiode (APD) with a separate multiplication region for internal gain", "parameters": ["center", "angle", "length", "width", "multiplication_length", "taper_length", "pad_width", "pad_length", "gain", "label"]},
    "EchelleGrating": {"category": "on_chip", "platform": "on_chip", "description": "Planar concave (echelle / Rowland) grating demultiplexer: a compact AWG alternative", "parameters": ["center", "angle", "channel_count", "slab_length", "slab_width", "grating_radius", "facet_count", "center_wavelength_nm", "channel_spacing_nm", "label"], "physics_modes": ("diagram", "wavelength")},
    "ChipSubstrate": {"category": "on_chip", "platform": "on_chip", "description": "Die / substrate base rectangle defining the chip extent (SOI by default); translucent, sits behind devices: the on-chip analogue of an optical table", "parameters": ["center", "angle", "length", "width", "kind", "chamfer", "label"]},
    "ElectricalPad": {"category": "electronics", "platform": "on_chip", "description": "Reusable bond or probe pad with an electrical routing port (schematic draw by default; ports stay physical µm)", "parameters": ["center", "angle", "width", "height", "port_side", "layer", "visual_scale", "render_physical", "label"], "schematic_default": True, "supports_render_physical": True, "supports_physical_spec": True},
    "GSGProbePad": {"category": "electronics", "platform": "on_chip", "description": "Ground-signal-ground RF probe pad group (schematic draw by default; ports stay physical µm)", "parameters": ["center", "angle", "pad_width", "pad_height", "gap", "port_side", "layer", "visual_scale", "render_physical", "label"], "schematic_default": True, "supports_render_physical": True, "supports_physical_spec": True},
    "MetalRoute": {"category": "electronics", "platform": "mixed", "description": "Explicit electrical metal route with layer, width, and resistance metadata (schematic draw by default; ports stay physical µm)", "parameters": ["points", "center", "angle", "width", "thickness", "layer", "sheet_resistance_ohm_per_sq", "visual_scale", "render_physical", "label"], "schematic_default": True, "supports_render_physical": True, "supports_physical_spec": True},
    "HeaterPad": {"category": "electronics", "platform": "on_chip", "description": "Thermo-optic heater stripe with contact pads, electrical ports, and tuning metadata", "parameters": ["center", "angle", "heater_length", "heater_width", "contact_width", "contact_height", "layer", "sheet_resistance_ohm_per_sq", "resistance_ohms", "tuning_efficiency_pm_per_mw", "max_power_mw", "visual_scale", "render_physical", "label"], "schematic_default": True, "supports_render_physical": True, "supports_physical_spec": True},
    "SignalArrow": {"category": "electronics", "platform": "mixed", "description": "Directional annotation for voltage, current, RF, clock, or digital signals", "parameters": ["start", "end", "center", "angle", "signal", "label"]},
    "RFDriver": {"category": "electronics", "platform": "mixed", "description": "Publication-style RF amplifier or driver block with differential outputs", "parameters": ["center", "angle", "length", "width", "output_gap", "visual_style", "visual_scale", "label"]},
    "Microcontroller": {"category": "electronics", "platform": "mixed", "description": "Digital microcontroller block for clock, GPIO, and control diagrams", "parameters": ["center", "angle", "length", "width", "pin_count", "visual_style", "visual_scale", "label"]},
    "ElectricalIOBank": {"category": "electronics", "platform": "mixed", "description": "Repeated DC/RF/clock/digital electrical I/O pad bank with routeable ports", "parameters": ["center", "angle", "count", "pitch", "pad_width", "pad_height", "side", "bank_kind", "signal_kinds", "layer", "visual_style", "visual_scale", "label"]},
    "BalancedPhotodetector": {"category": "electronics", "platform": "on_chip", "description": "Balanced photodetector block with optical inputs, differential electrical outputs, and detector metadata", "parameters": ["center", "angle", "length", "width", "optical_gap", "output_gap", "pad_size", "responsivity_a_per_w", "bandwidth_ghz", "dark_current_na", "cmrr_db", "visual_style", "visual_scale", "label"], "physics_modes": ("diagram", "readout")},
    "CoherentReceiver": {"category": "electronics", "platform": "mixed", "description": "Coherent receiver macro with optical signal/LO inputs, hybrid, balanced detector lanes, and I/Q outputs", "parameters": ["center", "angle", "length", "width", "pad_size", "optical_gap", "output_gap", "responsivity_a_per_w", "bandwidth_ghz", "polarization_diverse", "visual_style", "visual_scale", "label"], "physics_modes": ("diagram", "readout")},
    "TransmitterMacro": {"category": "electronics", "platform": "mixed", "description": "PIC transmitter macro from digital drive to modulated optical output", "parameters": ["center", "angle", "length", "width", "pad_size", "data_rate_gbps", "wavelength_nm", "extinction_ratio_db", "visual_style", "visual_scale", "label"], "physics_modes": ("diagram", "modulation")},
    "ReceiverMacro": {"category": "electronics", "platform": "mixed", "description": "Single-ended detector-to-digital receiver macro with photodetector, TIA, and ADC stages", "parameters": ["center", "angle", "length", "width", "pad_size", "responsivity_a_per_w", "bandwidth_ghz", "adc_bits", "visual_style", "visual_scale", "label"], "physics_modes": ("diagram", "readout")},
    "MEMSActuator": {"category": "electronics", "platform": "on_chip", "description": "Comb-drive MEMS actuator visual for tunable photonic devices", "parameters": ["center", "angle", "length", "width", "finger_count", "visual_style", "visual_scale", "label"]},
    "PCB": {"category": "electronics", "platform": "mixed", "description": "Printed circuit board context with edge pads, vias, and copper traces; style plain draws the outline in its color and the edge pads only", "parameters": ["center", "angle", "length", "width", "pad_count", "visual_style", "visual_scale", "style", "color", "label"]},
    "TIABlock": {"category": "electronics", "platform": "mixed", "description": "Transimpedance amplifier / integrator drawn as an op-amp block", "parameters": ["center", "angle", "length", "width", "pad_size", "mode", "visual_style", "visual_scale", "gain_ohm", "bandwidth_hz", "label"]},
    "DAC": {"category": "electronics", "platform": "mixed", "description": "Digital-to-analog converter block with bit count and package style", "parameters": ["center", "angle", "length", "width", "pad_size", "bit_count", "differential", "package_style", "visual_style", "visual_scale", "sample_rate_hz", "full_scale_v", "label"]},
    "ADCBlock": {"category": "electronics", "platform": "mixed", "description": "Analog-to-digital converter block with bit count and package style", "parameters": ["center", "angle", "length", "width", "pad_size", "bit_count", "package_style", "visual_style", "visual_scale", "sample_rate_hz", "full_scale_v", "label"]},
    "EIC": {"category": "electronics", "platform": "mixed", "description": "Electronic IC / driver chip package (QFP/QFN/BGA/die) for EPIC diagrams", "parameters": ["center", "angle", "length", "width", "pad_size", "pin_count", "package_style", "role", "visual_style", "visual_scale", "label"]},
    "Resistor": {"category": "electronics", "platform": "mixed", "description": "Resistor: the IEC rectangle in 1D and 2D, a chip resistor in 3D; its value prints after the label", "parameters": ["center", "angle", "length", "value", "label"]},
    "Capacitor": {"category": "electronics", "platform": "mixed", "description": "Capacitor: two plates in 1D and 2D, a ceramic chip capacitor in 3D; its value prints after the label", "parameters": ["center", "angle", "length", "value", "label"]},
    "Inductor": {"category": "electronics", "platform": "mixed", "description": "Inductor: four half turns in 1D and 2D, a ferrite chip inductor in 3D; its value prints after the label", "parameters": ["center", "angle", "length", "value", "label"]},
    "OpAmp": {"category": "electronics", "platform": "mixed", "description": "Operational amplifier with inverting and non-inverting inputs and V+ and V- supply pins: a triangle in 1D and 2D, an SOIC-8 in 3D", "parameters": ["center", "angle", "length", "value", "label"]},
    "Ground": {"category": "electronics", "platform": "mixed", "description": "Ground (earth) symbol: a lead to three bars; a symbol only, with no 3D solid", "parameters": ["center", "angle", "length", "value", "label"]},
    "BiasTee": {"category": "electronics", "platform": "mixed", "description": "Bias tee: RF through a series capacitor, DC in through an inductor; a module with SMA jacks in 3D", "parameters": ["center", "angle", "length", "value", "label"]},
    "RFMixer": {"category": "electronics", "platform": "mixed", "description": "RF mixer: RF and LO in, IF out; a crossed circle in 1D and 2D, a module with SMA jacks in 3D", "parameters": ["center", "angle", "length", "value", "label"]},
    "Amplifier": {"category": "electronics", "platform": "mixed", "description": "Amplifier (RF, servo, preamplifier): the IEC triangle in 1D and 2D, a module with SMA jacks in 3D", "parameters": ["center", "angle", "length", "value", "gain", "bandwidth_hz", "label"]},
    "RFFilter": {"category": "electronics", "platform": "mixed", "description": "Electrical filter, low-pass, high-pass, band-pass or band-stop: the IEC box with three waves, a coaxial filter in 3D", "parameters": ["center", "angle", "length", "value", "response", "label"]},
    "FiberArray": {"category": "electronics", "platform": "mixed", "description": "Fibre array at a chip edge: a V-groove block (glass lid on a silicon base) with count fibres at a pitch, ports o1..oN on its front face", "parameters": ["center", "angle", "count", "pitch", "label"]},
    "SMAConnector": {"category": "electronics", "platform": "mixed", "description": "Edge-launch SMA jack at a board edge: the IEC coaxial connector in 1D, the jack from above in 2D, pin, flange, hex and barrel in 3D", "parameters": ["center", "angle", "label"]},
    "PIDController": {"category": "electronics", "platform": "mixed", "description": "PID controller (servo, loop filter) of a laser lock or a phase-locked loop: an amplifier with RC feedback in 1D and 2D, a servo module in 3D", "parameters": ["center", "angle", "length", "value", "label"]},
    "SignalSource": {"category": "electronics", "platform": "mixed", "description": "Signal source (local oscillator, RF source, synthesizer): the IEC circle with a sine in 1D and 2D, an oscillator module in 3D; value prints the frequency", "parameters": ["center", "angle", "length", "value", "label"]},
    "SummingJunction": {"category": "electronics", "platform": "mixed", "description": "Summing junction (adder or subtractor, signs ++ or +-): a circle with a plus and the sign of each input; a summing module in 3D", "parameters": ["center", "angle", "length", "value", "signs", "label"]},
    "RFSplitter": {"category": "electronics", "platform": "mixed", "description": "RF power splitter (Wilkinson divider) or combiner: one input, two equal outputs; a module with SMA jacks in 3D", "parameters": ["center", "angle", "length", "value", "label"]},
    "RFCoupler": {"category": "electronics", "platform": "mixed", "description": "RF directional coupler: a main line through and a coupled port for a sample (a monitor tap); value prints the coupling", "parameters": ["center", "angle", "length", "value", "label"]},
    "RFPhaseShifter": {"category": "electronics", "platform": "mixed", "description": "RF (electrical) phase shifter, as on a local oscillator before a mixer: a box with phi; a module with SMA jacks in 3D", "parameters": ["center", "angle", "length", "value", "label"]},
    "RFSpectrumAnalyzer": {"category": "instruments", "platform": "free_space", "description": "RF (electrical) spectrum analyser, the ESA: a beat note on its screen and an RF input; the optical one is OSA", "parameters": ["center", "angle", "label"]},
    "CustomModel": {"category": "models", "platform": "mixed", "description": "Imported GLTF/GLB/OBJ model", "parameters": ["source", "center", "angle", "scale", "label"]},
    "GDSModel": {"category": "models", "platform": "on_chip", "description": "Imported GDS footprint or gdsfactory component", "parameters": ["source", "cell_name", "center", "angle", "scale", "z_exaggeration", "process_context", "oxide_opacity", "handle_opacity", "context_edge_opacity", "box_depth", "cladding_top", "handle_thickness", "label"]},    "Beam": {"category": "light_paths", "platform": "free_space", "description": "Free-space beam path", "parameters": ["anchors", "wavelength", "width", "opacity", "offset", "label"]},
    "Route": {"category": "routing", "platform": "mixed", "description": "Port-based routed interconnect", "parameters": ["points", "width", "kind", "path_type", "label"]},
    "FaradayRotator": {"category": "optics", "platform": "free_space", "description": "Faraday rotator: a TGG rod in a ring magnet turns the polarization by rotation_deg, the same sense both ways (two passes add)", "parameters": ["center", "angle", "length", "aperture", "rotation_deg", "label"]},
    "ModeCleaner": {"category": "optics", "platform": "free_space", "description": "Triangular ring mode cleaner (mode-cleaning cavity): two flat couplers and a curved mirror; passes the TEM00 mode on the input line, refl carries the lock error signal; piezo on the curved mirror", "parameters": ["center", "angle", "size", "transmission", "piezo", "label"]},
    "RoofMirror": {"category": "optics", "platform": "free_space", "description": "Hollow roof mirror: two mirrors at 90 degrees send the beam back parallel and beside itself (separate in and out); on its stage, the default mount, it is an optical delay line", "parameters": ["center", "angle", "aperture", "label"]},
    "BalancedDetector": {"category": "devices", "platform": "free_space", "description": "Free-space balanced detector: two matched photodiodes in one housing (inputs in1 and in2 on the front face), out carries the difference; for balanced homodyne detection", "parameters": ["center", "angle", "box_size", "label"]},
}


def _build_class_map() -> dict[str, type]:
    from optodraw.components.devices import (SNSPD, AmplifiedPhotodetector, Camera, Lamp, Laser, PMT, Photodiode,
                                             PhotonCounter, QuadrantPhotodiode, Spectrometer)
    from optodraw.components.preset_chip import (
        WDMInput,
    )
    from optodraw.components.instruments import (
        DAQ,
        OSA,
        SMU,
        VNA,
        CoincidenceCounter,
        Computer,
        FPGABoard,
        LaserDriver,
        OpticalPowerMeter,
        Oscilloscope,
        LockInAmplifier,
        VacuumPump,
        WaveformGenerator,
    )
    from optodraw.components.electronics import (
        ADCBlock,
        BalancedPhotodetector,
        CoherentReceiver,
        DAC,
        EIC,
        ElectricalPad,
        ElectricalIOBank,
        GSGProbePad,
        HeaterPad,
        FiberArray,
        SMAConnector,
        MEMSActuator,
        MetalRoute,
        Microcontroller,
        PCB,
        ReceiverMacro,
        RFDriver,
        SignalArrow,
        TIABlock,
        TransmitterMacro,
    )
    from optodraw.components.electronics.circuit import (Amplifier, BiasTee, Capacitor, Ground, Inductor, OpAmp,
                                                         Resistor, RFFilter, RFMixer)
    from optodraw.components.misc import Block, Bracket, Callout, DashedLink, Glyph, Grid, Note, Razor, Region, SectionMark
    from optodraw.figure.inset import CutLink, Inset, ZoomLink
    from optodraw.components.models import CustomModel, GDSModel
    from optodraw.components.electronics.circuit import (PIDController, RFCoupler, RFPhaseShifter, RFSplitter,
                                                         SignalSource, SummingJunction)
    from optodraw.components.instruments import RFSpectrumAnalyzer
    from optodraw.components.onchip import (
        ADC,
        AdiabaticCoupler,
        AvalanchePhotodetector,
        DACDriver,
        DBRLaser,
        DirectionalCoupler,
        EdgeCoupler,
        ElectroAbsorptionModulator,
        FocusedApodizedGratingCoupler,
        GratingAntennaArray,
        GratingCouplerArray,
        MMI1x2,
        MMI1x3,
        MMI1x4,
        MMI2x2,
        MMI2x2PowerSplitter,
        MZI,
        MZM,
        RingAssistedMZI,
        IQModulator,
        MicroringResonator,
        CoupledRingFilter,
        MicroringWeightBank,
        OnChipLaser,
        FrequencyComb,
        OnChipBalancedPhotodetector,
        OnChipPhotodetector,
        PNMicroringModulator,
        PolarizationRotator,
        PolarizationSplitterRotator,
        RacetrackModulator,
        RacetrackResonator,
        EORacetrackModulator,
        PCMCell,
        SOA,
        TIA,
        TapCoupler,
        Taper,
        Terminator,
        TwoDGratingCoupler,
        VerticalGratingCoupler,
        Waveguide,
        WaveguideBend,
        WaveguideCrossing,
        Spiral,
        PhaseShifter,
        YBranch,
    )
    from optodraw.components.onchip.system import AWG, AWGR, BraggGrating, ChipSubstrate, EchelleGrating, OpticalIOBank, SagnacLoop, StarCoupler
    from optodraw.components.optics import (
        Analyzer,
        ApertureStop,
        AsphericLens,
        BeamExpanderTelescope,
        BeamSplitter,
        PartialMirror,
        BiconcaveMirror,
        BiconvexMirror,
        ConcaveMirror,
        ConvexMirror,
        CylindricalLens,
        DichroicMirror,
        FiberCollimator,
        FiberPort,
        PolarizationController,
        FiberAmplifier,
        FiberCirculator,
        FiberCoupler,
        FiberSpool,
        VariableAttenuator,
        Filter,
        NDFilter,
        FourFSystem,
        FlipMirror,
        Grating,
        HalfWavePlate,
        Iris,
        Lens,
        Mirror,
        NonPolarizingBeamSplitter,
        OpticalTable,
        Objective,
        PBS,
        PowerMeter,
        Pinhole,
        GlanLaserPolarizer,
        Polarizer,
        Prism,
        QuarterWavePlate,
        RightAnglePrism,
        SPADArray,
        SLM,
        AOM,
        Baseplate,
        Breadboard,
        BrewsterWindow,
        LensTube,
        OpticalIsolator,
        NonlinearCrystal,
        WollastonPrism,
        Retroreflector,
        BeamDump,
        OpticalChopper,
        Pentaprism,
        OpticalPost,
        Periscope,
        PlatformMount,
        CMOSCamera,
        CameraSensor,
        CryostatWindow,
        DMD,
        EOM,
        EMCCD,
        GalvoMirror,
        KinematicMount,
        Monochromator,
        Telescope,
        RotationStage,
        SpectrometerSlit,
        TranslationStage,
        VacuumChamber,
        WavePlate,
        WedgePlate,
    )
    from optodraw.components.samples import Cryostat, Sample
    from optodraw.core.beam import Beam
    from optodraw.core.routing import Route
    from optodraw.components.optics import FaradayRotator, ModeCleaner, RoofMirror
    from optodraw.components.devices import BalancedDetector

    return {
        "Lens": Lens,
        "AsphericLens": AsphericLens,
        "CylindricalLens": CylindricalLens,
        "Telescope": Telescope,
        "FourFSystem": FourFSystem,
        "Mirror": Mirror,
        "FlipMirror": FlipMirror,
        "ConcaveMirror": ConcaveMirror,
        "ConvexMirror": ConvexMirror,
        "BiconcaveMirror": BiconcaveMirror,
        "BiconvexMirror": BiconvexMirror,
        "BeamSplitter": BeamSplitter,
        "PartialMirror": PartialMirror,
        "Filter": Filter,
        "NDFilter": NDFilter,
        "Grating": Grating,
        "Objective": Objective,
        "Prism": Prism,
        "GlanLaserPolarizer": GlanLaserPolarizer,
        "Polarizer": Polarizer,
        "Analyzer": Analyzer,
        "WavePlate": WavePlate,
        "HalfWavePlate": HalfWavePlate,
        "QuarterWavePlate": QuarterWavePlate,
        "PBS": PBS,
        "NonPolarizingBeamSplitter": NonPolarizingBeamSplitter,
        "DichroicMirror": DichroicMirror,
        "FiberPort": FiberPort,
        "FiberCollimator": FiberCollimator,
        "PolarizationController": PolarizationController,
        "FiberAmplifier": FiberAmplifier,
        "FiberCirculator": FiberCirculator,
        "FiberCoupler": FiberCoupler,
        "FiberSpool": FiberSpool,
        "VariableAttenuator": VariableAttenuator,
        "Iris": Iris,
        "Pinhole": Pinhole,
        "ApertureStop": ApertureStop,
        "SLM": SLM,
        "GalvoMirror": GalvoMirror,
        "AOM": AOM,
        "EOM": EOM,
        "DMD": DMD,
        "CameraSensor": CameraSensor,
        "CMOSCamera": CMOSCamera,
        "EMCCD": EMCCD,
        "SPADArray": SPADArray,
        "PowerMeter": PowerMeter,
        "OpticalTable": OpticalTable,
        "Breadboard": Breadboard,
        "Baseplate": Baseplate,
        "Periscope": Periscope,
        "OpticalPost": OpticalPost,
        "OpticalIsolator": OpticalIsolator,
        "NonlinearCrystal": NonlinearCrystal,
        "WollastonPrism": WollastonPrism,
        "Retroreflector": Retroreflector,
        "BeamDump": BeamDump,
        "OpticalChopper": OpticalChopper,
        "Pentaprism": Pentaprism,
        "LensTube": LensTube,
        "BrewsterWindow": BrewsterWindow,
        "PlatformMount": PlatformMount,
        "AmplifiedPhotodetector": AmplifiedPhotodetector,
        "PMT": PMT,
        "TranslationStage": TranslationStage,
        "RotationStage": RotationStage,
        "KinematicMount": KinematicMount,
        "CryostatWindow": CryostatWindow,
        "VacuumChamber": VacuumChamber,
        "SpectrometerSlit": SpectrometerSlit,
        "Monochromator": Monochromator,
        "RightAnglePrism": RightAnglePrism,
        "WedgePlate": WedgePlate,
        "BeamExpanderTelescope": BeamExpanderTelescope,
        "Laser": Laser,
        "Lamp": Lamp,
        "Camera": Camera,
        "Computer": Computer,
        "Oscilloscope": Oscilloscope,
        "SMU": SMU,
        "CoincidenceCounter": CoincidenceCounter,
        "FPGABoard": FPGABoard,
        "OSA": OSA,
        "OpticalPowerMeter": OpticalPowerMeter,
        "WaveformGenerator": WaveformGenerator,
        "LaserDriver": LaserDriver,
        "DAQ": DAQ,
        "VNA": VNA,
        "LockInAmplifier": LockInAmplifier,
        "VacuumPump": VacuumPump,
        "Photodiode": Photodiode,
        "PhotonCounter": PhotonCounter,
        "QuadrantPhotodiode": QuadrantPhotodiode,
        "SNSPD": SNSPD,
        "Spectrometer": Spectrometer,
        "Sample": Sample,
        "Cryostat": Cryostat,
        "Grid": Grid,
        "Note": Note,
        "Callout": Callout,
        "Bracket": Bracket,
        "DashedLink": DashedLink,
        "SectionMark": SectionMark,
        "Region": Region,
        "Glyph": Glyph,
        "Inset": Inset,
        "ZoomLink": ZoomLink,
        "CutLink": CutLink,
        "Block": Block,
        "Razor": Razor,
        "Waveguide": Waveguide,
        "Spiral": Spiral,
        "PhaseShifter": PhaseShifter,
        "GratingCouplerArray": GratingCouplerArray,
        "GratingAntennaArray": GratingAntennaArray,
        "VerticalGratingCoupler": VerticalGratingCoupler,
        "FocusedApodizedGratingCoupler": FocusedApodizedGratingCoupler,
        "EdgeCoupler": EdgeCoupler,
        "MMI1x2": MMI1x2,
        "MMI1x3": MMI1x3,
        "MMI1x4": MMI1x4,
        "MMI2x2": MMI2x2,
        "MMI2x2PowerSplitter": MMI2x2PowerSplitter,
        "YBranch": YBranch,
        "DirectionalCoupler": DirectionalCoupler,
        "TapCoupler": TapCoupler,
        "AdiabaticCoupler": AdiabaticCoupler,
        "PolarizationRotator": PolarizationRotator,
        "PolarizationSplitterRotator": PolarizationSplitterRotator,
        "TwoDGratingCoupler": TwoDGratingCoupler,
        "Taper": Taper,
        "WaveguideBend": WaveguideBend,
        "WaveguideCrossing": WaveguideCrossing,
        "Terminator": Terminator,
        "ElectroAbsorptionModulator": ElectroAbsorptionModulator,
        "DBRLaser": DBRLaser,
        "AvalanchePhotodetector": AvalanchePhotodetector,
        "EchelleGrating": EchelleGrating,
        "ChipSubstrate": ChipSubstrate,
        "MicroringResonator": MicroringResonator,
        "PNMicroringModulator": PNMicroringModulator,
        "MicroringWeightBank": MicroringWeightBank,
        "CoupledRingFilter": CoupledRingFilter,
        "PresetWDMInput": WDMInput,
        "RacetrackResonator": RacetrackResonator,
        "RacetrackModulator": RacetrackModulator,
        "EORacetrackModulator": EORacetrackModulator,
        "PCMCell": PCMCell,
        "MZI": MZI,
        "RingAssistedMZI": RingAssistedMZI,
        "MZM": MZM,
        "IQModulator": IQModulator,
        "OnChipBalancedPhotodetector": OnChipBalancedPhotodetector,
        "OnChipPhotodetector": OnChipPhotodetector,
        "OnChipLaser": OnChipLaser,
        "FrequencyComb": FrequencyComb,
        "SOA": SOA,
        "TIA": TIA,
        "DACDriver": DACDriver,
        "ADC": ADC,
        "OpticalIOBank": OpticalIOBank,
        "StarCoupler": StarCoupler,
        "AWG": AWG,
        "AWGR": AWGR,
        "BraggGrating": BraggGrating,
        "SagnacLoop": SagnacLoop,
        "ElectricalPad": ElectricalPad,
        "GSGProbePad": GSGProbePad,
        "MetalRoute": MetalRoute,
        "HeaterPad": HeaterPad,
        "SignalArrow": SignalArrow,
        "RFDriver": RFDriver,
        "Microcontroller": Microcontroller,
        "ElectricalIOBank": ElectricalIOBank,
        "BalancedPhotodetector": BalancedPhotodetector,
        "CoherentReceiver": CoherentReceiver,
        "TransmitterMacro": TransmitterMacro,
        "ReceiverMacro": ReceiverMacro,
        "MEMSActuator": MEMSActuator,
        "PCB": PCB,
        "TIABlock": TIABlock,
        "DAC": DAC,
        "ADCBlock": ADCBlock,
        "EIC": EIC,
        "Resistor": Resistor,
        "Capacitor": Capacitor,
        "Inductor": Inductor,
        "OpAmp": OpAmp,
        "Ground": Ground,
        "BiasTee": BiasTee,
        "RFMixer": RFMixer,
        "Amplifier": Amplifier,
        "RFFilter": RFFilter,
        "FiberArray": FiberArray,
        "SMAConnector": SMAConnector,
        "PIDController": PIDController,
        "SignalSource": SignalSource,
        "SummingJunction": SummingJunction,
        "RFSpectrumAnalyzer": RFSpectrumAnalyzer,
        "RFSplitter": RFSplitter,
        "RFCoupler": RFCoupler,
        "RFPhaseShifter": RFPhaseShifter,
        "CustomModel": CustomModel,
        "GDSModel": GDSModel,
        "Beam": Beam,
        "Route": Route,
        "FaradayRotator": FaradayRotator,
        "ModeCleaner": ModeCleaner,
        "RoofMirror": RoofMirror,
        "BalancedDetector": BalancedDetector,
    }


_CLASS_MAP: dict[str, type] = _build_class_map()


def register(
    name: str,
    cls: type,
    *,
    category: str,
    platform: str,
    description: str,
    parameters: list[str] | tuple[str, ...],
    creatable: bool = True,
    physics_modes: tuple[str, ...] | list[str] = ("diagram",),
    visual_only: bool = False,
    schematic_default: bool = False,
    supports_render_physical: bool = False,
    supports_physical_spec: bool = False,
    replace: bool = False,
) -> None:
    existing = _REGISTRY.get(name)
    if existing is not None and existing.cls is not cls and not replace:
        raise ValueError(f"{name} is already a catalog part ({existing.cls.__module__}.{existing.cls.__name__}); "
                         "give your part a new name, or pass replace=True to replace it")
    _REGISTRY[name] = ComponentSpec(
        name=name,
        cls=cls,
        category=category,
        platform=platform,
        description=description,
        parameters=tuple(parameters),
        creatable=creatable,
        physics_modes=tuple(physics_modes),
        visual_only=visual_only,
        schematic_default=schematic_default,
        supports_render_physical=supports_render_physical,
        supports_physical_spec=supports_physical_spec,
    )


def get_component_class(name: str, *, part_library=None) -> type | None:
    if name.startswith("user:"):
        from optodraw.parts import default_library

        library = default_library() if part_library is None else part_library
        try:
            return library.get(name).component_class
        except KeyError:
            return None
    spec = _REGISTRY.get(name)
    return None if spec is None else spec.cls


def component_registry() -> dict[str, ComponentSpec]:
    return dict(_REGISTRY)


def creatable_component_names() -> list[str]:
    return sorted(name for name, spec in _REGISTRY.items() if spec.creatable)


def describe_physics_support(name: str) -> dict[str, Any]:
    """Return physics contract metadata for a registered component."""

    spec = _REGISTRY.get(name)
    if spec is None:
        raise KeyError(f"Unknown component '{name}'")
    return {
        "name": spec.name,
        "physics_modes": list(spec.physics_modes),
        "visual_only": spec.visual_only,
        "schematic_default": spec.schematic_default,
        "supports_render_physical": spec.supports_render_physical,
        "supports_physical_spec": spec.supports_physical_spec,
        "supports_diagram": "diagram" in spec.physics_modes,
        "supports_ray": "ray" in spec.physics_modes,
        "supports_paraxial": "paraxial" in spec.physics_modes,
    }


def _normalize_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(kwargs)
    for key in ("center", "start", "end"):
        value = normalized.get(key)
        if isinstance(value, list):
            normalized[key] = tuple(value)
    if "resolution" in normalized and isinstance(normalized["resolution"], list):
        normalized["resolution"] = tuple(normalized["resolution"])
    if "points" in normalized:
        points = normalized["points"]
        if isinstance(points, list):
            normalized["points"] = [
                tuple(point) if isinstance(point, list) else point
                for point in points
            ]
    return normalized


def build_component(type_name: str, *, part_library=None, **kwargs: Any) -> Any:
    # ``type_name`` is the registry key; a component param literally called ``name``
    # (e.g. SectionMark) is passed via kwargs without colliding with it.
    if type_name.startswith("user:"):
        from optodraw.parts import default_library

        library = default_library() if part_library is None else part_library
        return library.get(type_name)(**_normalize_kwargs(kwargs))
    spec = _REGISTRY.get(type_name)
    if spec is None:
        raise KeyError(f"Unknown component '{type_name}'")
    if not spec.creatable:
        raise KeyError(f"Component '{type_name}' is not creatable via the registry")

    normalized = _normalize_kwargs(kwargs)
    if type_name == "Beam":
        anchors = normalized.pop("anchors", ())
        return spec.cls(*anchors, **normalized)
    if type_name == "Route":
        points = normalized.pop("points", ())
        return spec.cls(points, **normalized)
    return spec.cls(**normalized)


def _bootstrap_registry() -> None:
    missing = sorted(set(_BUILTIN_METADATA) - set(_CLASS_MAP))
    if missing:
        raise RuntimeError(f"Registry class map is missing entries: {', '.join(missing)}")

    for name, meta in _BUILTIN_METADATA.items():
        category = meta["category"]
        category_defaults = _CATEGORY_PHYSICS_DEFAULTS.get(category, {})
        physics_modes = tuple(meta.get("physics_modes", category_defaults.get("physics_modes", ("diagram",))))
        visual_only = bool(meta.get("visual_only", category_defaults.get("visual_only", False)))
        schematic_default = bool(
            meta.get("schematic_default", category_defaults.get("schematic_default", False))
        )
        supports_render_physical = bool(
            meta.get("supports_render_physical", category_defaults.get("supports_render_physical", False))
        )
        supports_physical_spec = bool(
            meta.get("supports_physical_spec", category_defaults.get("supports_physical_spec", False))
        )
        register(
            name,
            _CLASS_MAP[name],
            category=category,
            platform=meta["platform"],
            description=meta["description"],
            parameters=meta["parameters"],
            physics_modes=physics_modes,
            visual_only=visual_only,
            schematic_default=schematic_default,
            supports_render_physical=supports_render_physical,
            supports_physical_spec=supports_physical_spec,
        )


_bootstrap_registry()
