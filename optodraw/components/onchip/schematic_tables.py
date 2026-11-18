"""Per-device-family schematic dimension tables for on-chip rendering.

Values are legible diagram defaults (µm).  They intentionally differ from PDK
footprints so MZM arms, ring gaps, slab thickness, and coupling regions read
clearly in 2D/3D.  Physical truth lives in ``PhysicalSpec`` / ports / routing.
"""

from __future__ import annotations

from typing import Any

# Shared keys merged into every resolved ``SchematicDims``.
_SHARED: dict[str, float] = {
    "waveguide_width": 1.2,
    "thickness": 0.55,
    "metal_height": 0.28,
    "via_height": 0.42,
    "oxide_clad_height": 0.35,
}

SCHEMATIC_TABLES: dict[str, dict[str, Any]] = {
    "_shared": _SHARED,
    "waveguide": {
        "length": 24.0,
        "width": 1.2,
        "thickness": 0.55,
    },
    "spiral": {
        "width": 1.2,
        "thickness": 0.55,
    },
    "phase_shifter": {
        "width": 1.2,
        "thickness": 0.55,
    },
    "mmi": {
        "body_length": 12.0,
        "body_width": 6.0,
        "taper_length": 9.0,
        "waveguide_width": 1.7,
        "width_taper": 2.6,
        "thickness": 0.55,
    },
    "grating_coupler": {
        "length": 42.0,
        "width": 28.0,
        "taper_length": 18.0,
        "waveguide_width": 1.2,
        "fiber_port_width": 12.0,
        "thickness": 0.55,
    },
    "focused_grating_coupler": {
        "length": 38.0,
        "width": 24.0,
        "taper_length": 14.0,
        "waveguide_width": 1.2,
        "fiber_port_width": 11.0,
        "thickness": 0.55,
    },
    "edge_coupler": {
        "taper_length": 30.0,
        "cladding_length": 18.0,
        "cladding_width": 5.0,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "grating_coupler_array": {
        # Drawn pitch is compacted so the array reads as one tight unit (esp. in 3D);
        # physical 127µm fiber pitch is preserved for ports/GDS via render_physical.
        "pitch": 45.0,
        "stub_length": 14.0,
        "thickness": 0.55,
    },
    "y_branch": {
        "branch_length": 11.0,
        "stem_length": 1.4,
        "waveguide_width": 1.2,
        "branch_width": 1.4,
        "thickness": 0.55,
    },
    "directional_coupler": {
        "coupling_length": 20.0,
        "transition_length": 8.0,
        "straight_length": 4.0,
        "port_spacing": 14.0,
        "waveguide_gap": 0.8,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "microring": {
        "ring_radius": 14.0,
        "gap": 1.0,
        "waveguide_width": 1.2,       # one waveguide width for every part and route
        "length_x": 5.0,
        "length_y": 0.8,
        "heater_width": 1.6,
        "heater_gap": 2.4,
        "thickness": 0.55,
    },
    "pn_microring": {
        "ring_radius": 14.0,
        "gap": 1.0,
        "waveguide_width": 1.2,       # one waveguide width for every part and route
        "slab_ring_width": 4.2,
        "thickness": 0.55,
    },
    "racetrack": {
        "bend_radius": 14.0,
        "gap": 1.0,
        "coupling_length": 28.0,
        "length_y": 8.0,
        "waveguide_width": 1.2,       # one waveguide width for every part and route
        "thickness": 0.55,
    },
    "racetrack_modulator": {
        "bend_radius": 14.0,
        "gap": 1.0,
        "coupling_length": 28.0,
        "waveguide_width": 1.2,       # one waveguide width for every part and route
        "active_length": 24.0,
        "thickness": 0.55,
    },
    "coupled_ring_filter": {
        "radius": 14.0,
        "gap": 1.0,
        "coupling_length": 20.0,
        "waveguide_width": 1.2,       # one waveguide width for every part and route
        "heater_width": 1.6,
        "heater_gap": 2.4,
        "heater_pad_size": 3.6,
        "thickness": 0.55,
    },
    "microring_weight_bank": {
        "ring_radius": 12.0,
        "gap": 1.0,
        "ring_pitch": 36.0,
        "waveguide_width": 1.2,       # one waveguide width for every part and route
        "thickness": 0.55,
    },
    "mzi": {
        "coupler_length": 28.0,
        "coupler_width": 3.6,
        "arm_length": 48.0,
        "arm_gap": 14.0,
        "waveguide_width": 1.2,
        "taper_length": 12.0,
        "thickness": 0.55,
    },
    "ramzi": {
        "coupler_length": 28.0,
        "coupler_width": 3.6,
        "arm_length": 48.0,
        "arm_gap": 14.0,
        "waveguide_width": 1.2,
        "taper_length": 12.0,
        "ring_radius": 12.0,
        "ring_gap": 0.8,
        "thickness": 0.55,
    },
    "mzm": {
        "coupler_length": 28.0,
        "coupler_width": 3.6,
        "arm_length": 52.0,
        "arm_gap": 16.0,
        "waveguide_width": 1.2,
        "taper_length": 12.0,
        "waveguide_gap": 0.8,
        "slab_width": 3.2,
        "metal_width": 2.4,
        "thickness": 0.55,
    },
    "photodetector": {
        "length": 44.0,
        "width": 5.0,
        "taper_length": 22.0,
        "pad_width": 12.0,
        "pad_length": 22.0,
        "contact_finger_width": 0.6,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "laser": {
        "cavity_length": 64.0,
        "ridge_width": 3.6,
        "output_taper_length": 16.0,
        "pad_length": 28.0,
        "pad_width": 14.0,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "soa": {
        "amplifier_length": 180.0,
        "taper_length": 18.0,
        "ridge_width": 4.0,
        "pad_length": 22.0,
        "pad_width": 10.0,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "tia": {
        "length": 36.0,
        "width": 28.0,
        "pad_size": 3.2,
        "thickness": 0.55,
    },
    "dac_driver": {
        "length": 42.0,
        "width": 32.0,
        "pad_size": 3.0,
        "output_gap": 9.0,
        "thickness": 0.55,
    },
    "adc": {
        "length": 42.0,
        "width": 32.0,
        "pad_size": 3.0,
        "thickness": 0.55,
    },
    "optical_io_bank": {
        "pitch": 30.0,
        "stub_length": 18.0,
        "port_width": 1.2,
        "coupler_length": 20.0,
        "coupler_width": 12.0,
        "thickness": 0.55,
    },
    "star_coupler": {
        "slab_length": 48.0,
        "slab_width": 56.0,
        "port_spacing": 7.0,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "awg": {
        "slab_length": 42.0,
        "slab_width": 54.0,
        "array_length": 76.0,
        "channel_spacing": 6.5,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    # The router. Only the legibility constants live here. fpr_length,
    # fpr_separation and array_height are deliberately ABSENT: those three carry
    # a geometric consistency rule (fpr_separation must clear
    # AWGR.min_fpr_separation(fpr_length) or the two free-propagation regions
    # interpenetrate), and _draw reads the table in preference to the
    # constructor, so pinning them here would silently override the clamp that
    # enforces the rule and freeze the requested arch height.
    "awgr": {
        "aperture_width": 1.8,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "bragg_grating": {
        "length": 72.0,
        "period": 2.0,
        "corrugation_width": 0.6,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "sagnac_loop": {
        "loop_radius": 22.0,
        "coupler_length": 26.0,
        "port_spacing": 9.0,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    # Passive routing + polarization + extra active families draw at physical scale
    # (geometry uses the component's own attributes), so only the core thickness is
    # needed here — mirrors the spiral / phase_shifter approach.
    "taper": {"width1": 1.2, "thickness": 0.55},
    "bend": {"width": 1.2, "thickness": 0.55},
    "crossing": {"thickness": 0.55},
    "terminator": {"width": 1.2, "thickness": 0.55},
    "tap_coupler": {"thickness": 0.55},
    "adiabatic_coupler": {"thickness": 0.55},
    "polarization_rotator": {"width": 1.2, "thickness": 0.55},
    "polarization_splitter_rotator": {"thickness": 0.55},
    "grating_coupler_2d": {"thickness": 0.55},
    "eam": {"thickness": 0.55},
    "dbr_laser": {"thickness": 0.55},
    "avalanche_photodetector": {"thickness": 0.55},
    "echelle_grating": {"thickness": 0.55},
    "substrate": {"thickness": 0.55},
    # An optical phased array's emitters: guides on a pitch that reads (2 um is a hairline), teeth drawn to scale
    # of the drawn length, not of the 630 nm period.
    "grating_antenna_array": {
        "pitch": 6.0,
        "length": 40.0,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "pcm_cell": {
        "length": 24.0,
        "cell_length": 8.0,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
    "eo_racetrack": {
        "straight_length": 90.0,
        "bend_radius": 12.0,
        "gap": 0.8,
        "electrode_gap": 1.6,
        "electrode_width": 3.0,
        "waveguide_width": 1.2,
        "thickness": 0.55,
    },
}
