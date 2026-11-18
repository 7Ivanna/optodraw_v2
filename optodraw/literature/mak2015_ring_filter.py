"""Fifth-order microring filter after Mak et al., IEEE J. Quantum Electron. 51(11), 2015, Fig. 1a and Fig. 7.

Five racetrack rings stand in a column between two buses. Light enters the bottom bus from the right and the
through port is its left end; the drop port is the top bus on the right, through a 25 % tap to a germanium
detector; the add port (top left) is ended. The through port has a 25 % tap too, unused. Each ring has its own
heater with two small pads beside it. The input and the through port end at grating couplers on the right edge.

A compact schematic, not to scale: the paper's gaps (230, 380, 430, 430, 380, 230 nm) set the filter's
coupling; the rings, taps and pads are drawn at optodraw's schematic sizes.
"""

from __future__ import annotations

from optodraw import (CoupledRingFilter, ElectricalPad, OnChipPhotodetector, Scene, TapCoupler, Terminator,
                      VerticalGratingCoupler)
from optodraw.layout import Vec3

PAPER = {
    "citation": "J. C. C. Mak, W. D. Sacher, T. Xue, J. C. Mikkelsen, Z. Yong, J. K. S. Poon, Automatic resonance "
                "alignment of high-order microring filters, IEEE J. Quantum Electron. 51(11), 1-11 (2015)",
    "doi": "10.1109/JQE.2015.2479939",
    "figure": "Fig. 1a (filter), Fig. 7 (chip)",
}

GAPS = [0.230, 0.380, 0.430, 0.430, 0.380, 0.230]    # bus to ring 1, ring to ring, ring 5 to bus (um)
PAD = 10.0                                         # heater pads
TAP = 0.25
WG = 1.2                                           # every waveguide one width: no route tapers


def _place(part, port: str, x: float, y: float):
    """Move ``part`` so its ``port`` lands on (x, y)."""

    at = part.world_ports()[port].center
    p = part.transform.position
    part.transform.position = Vec3(round(float(p.x + x - at.x), 2), round(float(p.y + y - at.y), 2), 0.0)   # readable
    return part


def build(title: str = "Fifth-order microring filter (after Mak 2015)") -> Scene:
    chip = Scene(title=title, width=400, height=300, platform="on_chip")
    wg = dict(kind="waveguide", path_type="smooth", width=WG)
    wire = dict(kind="electrical", path_type="L", width=1.0)
    rings = chip.add(CoupledRingFilter(center=(0, 0), order=5, ring_shape="racetrack", gaps=GAPS, with_heaters=True,
                                       label="5th-order filter", label_side="top"))
    ports = rings.world_ports()
    # light from the right: input at o2, through at o1; an odd order drops at the top on the same side, o4
    o1, o2, o3, o4 = (ports[name].center for name in ("o1", "o2", "o3", "o4"))

    gc_in = _place(chip.add(VerticalGratingCoupler(angle=0, label="In", label_side="right")), "o1", o2.x + 30.0, o2.y)
    chip.route((gc_in, "o1"), (rings, "o2"), **wg)

    # the through port: a 25 % tap (unused), then under the filter to the second coupler, below the input one
    tap_t = _place(chip.add(TapCoupler(angle=180, tap_ratio=TAP, waveguide_width=WG, label="25% tap", label_side="bottom")), "o1",
                   o1.x - 46.0, o1.y)                     # its spare port's terminator ends west of the pads
    chip.route((rings, "o1"), (tap_t, "o1"), **wg)
    for name, step in (("o3", -8.0), ("o4", 8.0)):
        at = tap_t.world_ports()[name].center
        stop = _place(chip.add(Terminator(angle=180 if step < 0 else 0, width=WG, label="")), "o1", at.x + step, at.y)
        chip.route((tap_t, name), (stop, "o1"), **wg)
    gc_thru = _place(chip.add(VerticalGratingCoupler(angle=0, label="Thru", label_side="right")), "o1",
                     o2.x + 30.0, o2.y - 30.0)
    out = tap_t.world_ports()["o2"].center
    chip.route((tap_t, "o2"), (gc_thru, "o1"), kind="waveguide", path_type="manhattan", width=WG, smooth=True,
               bend_radius=4.0,
               steps=[{"x": out.x - 8.0}, {"y": o2.y - 30.0}])

    # the drop port: a 25 % tap to the germanium detector; the 75 % arm and the spare port are ended
    tap_d = _place(chip.add(TapCoupler(angle=0, tap_ratio=TAP, waveguide_width=WG, label="Drop tap", label_side="top")), "o1",
                   o4.x + 40.0, o4.y)                     # its spare port's terminator ends east of the pads
    chip.route((rings, "o4"), (tap_d, "o1"), **wg)
    at = tap_d.world_ports()["o3"].center
    pd = _place(chip.add(OnChipPhotodetector(label="Ge PD", label_side="bottom")), "o1", at.x + 26.0, at.y)
    chip.route((tap_d, "o3"), (pd, "o1"), **wg)
    for name, step in (("o2", 8.0), ("o4", -8.0)):
        at = tap_d.world_ports()[name].center
        stop = _place(chip.add(Terminator(angle=0 if step > 0 else 180, width=WG, label="")), "o1", at.x + step, at.y)
        chip.route((tap_d, name), (stop, "o1"), **wg)
    add = _place(chip.add(Terminator(angle=180, width=WG, label="Add", label_side="top")), "o1", o3.x - 10.0, o3.y)
    chip.route((rings, "o3"), (add, "o1"), **wg)

    # two pads per heater, side by side in one row beside it: the row sits level with the heater contact nearer
    # the middle of the column (a straight wire), the other contact runs out under the row and turns up (or
    # down) into the outer pad. Few rows keep the 1D view as compact as the 2D.
    for k in range(1, 6):
        contacts = {end: ports[f"h{k}{end}"].center for end in ("a", "b")}
        near, far = sorted(contacts, key=lambda end: abs(float(contacts[end].y)))
        west = contacts["a"].x < 0
        out = -1.0 if west else 1.0
        level = round(float(contacts[near].y), 2)
        inner_x = round(float(contacts[near].x) + out * (4.0 + PAD / 2.0), 2)
        inner = chip.add(ElectricalPad(center=(inner_x, level), width=PAD, height=PAD, angle=180 if west else 0,
                                       label=""))                                  # port faces the heater
        outer = chip.add(ElectricalPad(center=(inner_x + out * (PAD + 4.0), level), width=PAD, height=PAD,
                                       angle=90 if contacts[far].y < level else -90, label=""))   # port faces the wire
        chip.route((rings, f"h{k}{near}"), (inner, "e1"), kind="electrical", path_type="straight", width=1.0)
        chip.route((rings, f"h{k}{far}"), (outer, "e1"), **wire)

    chip.fit_frame(margin=10)
    chip.metadata["paper"] = dict(PAPER)
    return chip
