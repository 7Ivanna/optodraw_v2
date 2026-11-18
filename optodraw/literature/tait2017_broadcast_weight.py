"""Broadcast-and-weight network after Tait et al., Sci. Rep. 7, 7430 (2017), Fig. 1a: four nodes, each a laser and
an MZM (the neuron) whose wavelength joins a WDM multiplexer; one bus loops back and a 1:4 splitter broadcasts the
four wavelengths to four microring weight banks; each bank's balanced detector drives its own node's MZM.

A compact schematic, not to scale. Each node is one row: weight bank, balanced detector, laser and MZM on one line.
The multiplexer is an AWG. The only long route is the broadcast bus, round the outside, as in the figure.
"""

from __future__ import annotations

import math

from optodraw import (AWG, ElectricalPad, MicroringWeightBank, MMI1x4, MZM, OnChipBalancedPhotodetector, OnChipLaser,
                      Scene)
from optodraw.layout import Vec3

NODES = 4
PITCH = 80.0         # one node per row: a bank and its label
PAD = 10.0           # ground pads
WG = 1.2             # every waveguide one width, so no route tapers between its ports


def _place(part, port: str, x: float, y: float) -> None:
    """Move ``part`` so its ``port`` lands on (x, y)."""

    at = part.world_ports()[port].center
    p = part.transform.position
    part.transform.position = Vec3(round(float(p.x + x - at.x), 2), round(float(p.y + y - at.y), 2), 0.0)   # readable


PAPER = {
    "citation": "A. N. Tait, T. Ferreira de Lima, E. Zhou, A. X. Wu, M. A. Nahmias, B. J. Shastri, P. R. Prucnal, "
                "Neuromorphic photonic networks using silicon photonic weight banks, Sci. Rep. 7, 7430 (2017)",
    "doi": "10.1038/s41598-017-07754-z",
    "figure": "Fig. 1a",
}


def build(title: str = "Broadcast-and-weight network (after Tait 2017)") -> Scene:
    chip = Scene(title=title, width=900, height=520, platform="on_chip")
    wg = dict(kind="waveguide", path_type="smooth", width=WG)
    wire = dict(kind="electrical", path_type="L", width=1.0)
    mzms, banks, lasers = [], [], []
    for k in range(NODES):
        y = ((NODES - 1) / 2.0 - k) * PITCH                  # the bank's through bus in row k (top row first)
        # the weight bank, its balanced detector, the laser and the MZM on one line, so the rows stack as close
        # as a bank allows
        bank = chip.add(MicroringWeightBank(ring_count=4, with_heaters=True, label=f"Weight bank {k + 1}",
                                            label_side="top"))
        _place(bank, "o2", 0.0, y)
        bpd = chip.add(OnChipBalancedPhotodetector(label="BPD", label_side="left"))
        _place(bpd, "o2", 40.0, y)                           # the through port runs straight into the lower diode
        chip.route((bank, "o2"), (bpd, "o2"), **wg)
        chip.route((bank, "drop"), (bpd, "o1"), **wg)
        # each ring's heater ends on the bank's own pads, between the rings: a wire out would cross a bus
        # the laser and the MZM east of the detector, their axis 4 um over the bank's bus
        out = bpd.world_ports()["out"].center
        laser = chip.add(OnChipLaser(label=f"LD λ{k + 1}", label_side="bottom"))
        _place(laser, "o1", out.x + 100.0, y + 4.0)
        mzm = chip.add(MZM(drive_style="gs", label=f"MZM {k + 1}", label_side="bottom"))
        _place(mzm, "o1", out.x + 112.0, y + 4.0)
        chip.route((laser, "o1"), (mzm, "o1"), **wg)
        # the ground contact is the centre electrode, between the arms: its pad hangs under the MZM
        gnd = mzm.world_ports()["gnd"].center
        pad = chip.add(ElectricalPad(width=PAD, height=PAD, angle=-90, label=""))       # the port faces up
        _place(pad, "e1", gnd.x, y - 12.0)
        chip.route((mzm, "gnd"), (pad, "e1"), **wire)
        # the detector's output runs over the laser and drops onto the MZM's signal contact
        sig = mzm.world_ports()["sig"].center
        chip.route((bpd, "out"), (mzm, "sig"), kind="electrical", path_type="manhattan", width=1.0,
                   steps=[{"x": out.x + 6.0}, {"y": y + 34.0}, {"x": sig.x}, {"y": sig.y}])
        mzms.append(mzm)
        banks.append(bank)
        lasers.append(laser)

    # the WDM multiplexer: an AWG east of the MZMs, turned so its channel ports face them; the 1:4 splitter west
    mux = chip.add(AWG(channel_count=NODES, array_count=8, angle=180, label="WDM mux (AWG)", label_side="bottom"))
    rows_mid = (mzms[0].world_ports()["o3"].center.y + mzms[-1].world_ports()["o3"].center.y) / 2.0
    east = mzms[0].world_ports()["o3"].center.x
    ports = mux.world_ports()
    channels = sorted((name for name in ports if name != "i1"), key=lambda name: -ports[name].center.y)
    near = max(ports[name].center.x for name in channels)
    _place(mux, channels[0], east + 60.0 + (ports[channels[0]].center.x - near), rows_mid + (ports[channels[0]].center.y - (sum(ports[n].center.y for n in channels) / NODES)))
    ports = mux.world_ports()
    # the channel ports face up and to the west: each waveguide runs along its lane to the level of its port's
    # lead, across, and the last um along the port's own direction. Every lead ends at one x, so the leads are a
    # parallel fan into the tilted face and the 1D, which stacks the ports in a column, needs no jog. The leads
    # fall from the top channel to the bottom one, so no two cross. Bends of 6 um radius: smaller ones read as
    # square corners at this size
    fan = min(float(ports[name].center.x) for name in channels) - 4.0         # the x every lead ends at
    for k, (mzm, name) in enumerate(zip(mzms, channels)):              # the top row takes the top channel
        # each laser emits the colour of the channel it feeds, so the multiplexer passes all four
        lasers[k].wavelength_nm = mux.center_wavelength_nm + (int(name[1:]) - (NODES + 1) / 2.0) * mux.channel_spacing_nm
        lane = east + 12.0 + 12.0 * (k in (0, NODES - 1))            # the outer rows on the outer lane
        port = ports[name]
        turn = math.radians(float(port.orientation_deg))
        lead = (fan - float(port.center.x)) / math.cos(turn)
        lead_y = float(port.center.y) + lead * math.sin(turn)
        chip.route((mzm, "o3"), (mux, name), kind="waveguide", path_type="manual", width=WG, smooth=True,
                   bend_radius=6.0, steps=[{"x": lane}, {"y": lead_y}], end_straight_length=lead)   # as given
    split = chip.add(MMI1x4(label="1:4 splitter", label_side="bottom"))
    west = min(b.world_ports()["o1"].center.x for b in banks)
    # level with the second row's bank: in 1D the splitter is far taller than in 2D, and a row's band has the room
    # (19.5 um over its bus keeps the 1D rows within 2.5 of each other; 18 or 21 does not)
    _place(split, "o1", west - 70.0, rows_mid + PITCH / 2.0 + 19.5)
    outs = sorted((name for name in split.world_ports() if name != "o1"), key=lambda n: -split.world_ports()[n].center.y)
    for k, (name, bank) in enumerate(zip(outs, banks)):
        # the outputs sit at west - 40: a route down turns before the ones over it (the lowest output first), a
        # route up after them; none cross
        down = bank.world_ports()["o1"].center.y < split.world_ports()[name].center.y
        lane = west - 34.0 + 6.0 * (NODES - 1 - k) if down else west - 22.0
        chip.route((split, name), (bank, "o1"), kind="waveguide", path_type="manhattan", width=WG, smooth=True, bend_radius=8.0,
                   steps=[{"x": lane}, {"y": bank.world_ports()["o1"].center.y}])
    # the broadcast bus: from the mux round the bottom to the splitter, as the loop of the figure
    x0, y0, x1, y1 = chip.content_bounds()
    out = mux.world_ports()["i1"].center
    into = split.world_ports()["o1"].center
    chip.route((mux, "i1"), (split, "o1"), kind="waveguide", path_type="manhattan", width=WG, smooth=True, bend_radius=8.0,
               steps=[{"x": out.x + 10.0}, {"y": y0 - 10.0}, {"x": into.x - 12.0}, {"y": into.y}])
    chip.fit_frame(margin=12)
    chip.metadata["paper"] = dict(PAPER)
    return chip
