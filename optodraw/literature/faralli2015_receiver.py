"""Single-polarisation silicon coherent receiver after Faralli et al., IEEE Photonics J. 7(4), 7802806 (2015),
Fig. 1: a 1x2 DC splits the local oscillator, a 1x2 MMI splits the signal, two heaters set the 90 degree
phase, two 2x2 DCs mix them, and two balanced germanium detectors read I and Q. No waveguide crossing.

A compact schematic, not to scale: the 500 um heaters are drawn as short phase shifters, and each detector's
own G-S-G probe pads stand for the paper's pad sets.
"""

from __future__ import annotations

from optodraw import (DirectionalCoupler, ElectricalPad, MMI1x2, OnChipBalancedPhotodetector, PhaseShifter, Scene,
                      Terminator, VerticalGratingCoupler)
from optodraw.layout import align_ports

ARM = 14.0          # the signal arms, above and below the axis
ROW = 40.0          # the coupler and detector rows
PAD = 12.0          # heater pad size
WG = 1.2            # every waveguide one width, so no route tapers between its ports


PAPER = {
    "citation": "S. Faralli, G. Meloni, F. Gambini, J. Klamkin, L. Poti, G. Contestabile, A compact silicon coherent "
                "receiver without waveguide crossing, IEEE Photonics J. 7(4), 7802806 (2015)",
    "doi": "10.1109/JPHOT.2015.2456632",
    "figure": "Fig. 1",
}


def build(title: str = "Coherent receiver (after Faralli 2015)") -> Scene:
    chip = Scene(title=title, width=520, height=200, platform="on_chip")
    gc_lo = chip.add(VerticalGratingCoupler(center=(-176, 0), angle=180, label="LO"))
    split = chip.add(DirectionalCoupler(center=(-120, 0), label="1x2 DC", label_side="bottom"))
    dump = chip.add(Terminator(angle=180, width=WG, label=""))
    align_ports(split, "o2", dump, "o1", gap=6)                 # the 1x2 DC's unused input
    chip.route((split, "o2"), (dump, "o1"), kind="waveguide", path_type="straight", width=WG)
    mmi = chip.add(MMI1x2(center=(118, 0), angle=180, label="1x2 MMI", label_side="bottom"))
    gc_sig = chip.add(VerticalGratingCoupler(center=(165, 0), angle=0, label="Signal"))

    rows = {}
    for name, y, ps_angle in (("I", ROW, 0), ("Q", -ROW, 180)):
        dc = chip.add(DirectionalCoupler(center=(-40, y), label=f"2x2 DC {name}",
                                         label_side="top" if y > 0 else "bottom"))
        pd = chip.add(OnChipBalancedPhotodetector(center=(25, y), label=f"BPD {name}",
                                                  label_side="top" if y > 0 else "bottom"))   # on the outer side
        # the heater runs on the arm right of the detector, so its pads fit between the arm and the row
        ps = chip.add(PhaseShifter(center=(76, y / abs(y) * ARM), angle=ps_angle, width=WG, label=f"PS {name}",
                                   label_side="bottom" if y > 0 else "top"))
        pads = []
        for contact in ("h1", "h2"):
            at = ps.world_ports()[contact].center
            side = 1.0 if y > 0 else -1.0
            pad = chip.add(ElectricalPad(center=(at.x, at.y + side * (PAD / 2 + 6)), width=PAD, height=PAD,
                                         angle=90 if y > 0 else -90, label=""))   # the port faces the heater
            chip.route((ps, contact), (pad, "e1"), kind="electrical", path_type="L", width=1.2)
            pads.append(pad)
        rows[name] = (dc, pd, ps)

    wg = dict(kind="waveguide", path_type="smooth", width=WG)
    bend = dict(kind="waveguide", path_type="manhattan", width=WG, smooth=True, bend_radius=4.0)
    chip.route((gc_lo, "o1"), (split, "o1"), **wg)
    chip.route((gc_sig, "o1"), (mmi, "o1"), **wg)
    dc_i, pd_i, ps_i = rows["I"]
    dc_q, pd_q, ps_q = rows["Q"]
    # the LO takes the outer lanes, the signal the inner lanes: the two U-turns never cross
    chip.route((split, "o3"), (dc_i, "o1"), **bend, steps=[{"x": -96.0}, {"y": ROW + 7.0}])
    chip.route((split, "o4"), (dc_q, "o2"), **bend, steps=[{"x": -96.0}, {"y": -ROW - 7.0}])
    chip.route((mmi, "o2"), (ps_i, "o2"), **wg)
    chip.route((mmi, "o3"), (ps_q, "o1"), **wg)
    chip.route((ps_i, "o1"), (dc_i, "o2"), **bend, steps=[{"x": -74.0}, {"y": ROW - 7.0}])
    chip.route((ps_q, "o2"), (dc_q, "o1"), **bend, steps=[{"x": -74.0}, {"y": -ROW + 7.0}])
    for dc, pd in ((dc_i, pd_i), (dc_q, pd_q)):
        chip.route((dc, "o3"), (pd, "o1"), **wg)
        chip.route((dc, "o4"), (pd, "o2"), **wg)
    chip.fit_frame(margin=10)
    chip.metadata["paper"] = dict(PAPER)
    return chip
