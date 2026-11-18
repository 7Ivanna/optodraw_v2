"""A 2D directional coupler in Meep, run on fieldrt, written as sampled S-parameters for optodraw.

Model (2D effective index, not a 3D device): 0.5 um strips of index 2.85 (the TE slab index of 220 nm silicon at
1550 nm) in oxide of index 1.444, a 0.2 um gap over a 10 um straight, cosine S-bends out to ports 2 um apart.
One eigenmode source at o1; mode monitors at all four ports; 1001 wavelengths from 1500 to 1600 nm. The other three
columns of S follow from the coupler's two mirror symmetries (top-bottom, left-right).

Ports as optodraw's DirectionalCoupler: o1 top left, o2 bottom left, o3 top right, o4 bottom right.
Run with a Python that has meep and fieldrt: python coupler_fieldrt.py [resolution]. The default, 45 px/um, writes
coupler_fieldrt.npz here (the docs table); another resolution writes coupler_res<resolution>.npz, for a convergence check.
"""
from __future__ import annotations

import datetime
import json
import math
import sys
from pathlib import Path

import meep as mp
import numpy as np

import fieldrt
import fieldrt.meep as frt

mp.verbosity(0)
HERE = Path(__file__).resolve().parent
W, GAP, LC, LS, LEAD, SEP = 0.5, 0.2, 10.0, 6.0, 3.0, 2.0      # um
N_CORE, N_CLAD = 2.85, 1.444
RES, PML = int(sys.argv[1]) if len(sys.argv) > 1 else 45, 1.0
WL = np.linspace(1.5, 1.6, 1001)                               # um
FREQS = 1.0 / WL

y_in, y_out = (GAP + W) / 2.0, SEP / 2.0                       # guide centres: coupling region, ports
x_end = LC / 2.0 + LS + LEAD
cell = mp.Vector3(2 * (x_end + PML), 2 * (y_out + 1.5 + PML))


def centre_y(x: float) -> float:
    """The upper guide's centre line: flat at y_in over the coupling length, cosine S-bends to y_out."""
    ax = abs(x)
    if ax <= LC / 2.0:
        return y_in
    if ax >= LC / 2.0 + LS:
        return y_out
    t = (ax - LC / 2.0) / LS
    return y_in + (y_out - y_in) * (1.0 - math.cos(math.pi * t)) / 2.0


def guide(sign: float) -> mp.Prism:
    xs = np.linspace(-x_end - PML - 1.0, x_end + PML + 1.0, 801)
    top = [mp.Vector3(x, sign * centre_y(x) + W / 2.0) for x in xs]
    bottom = [mp.Vector3(x, sign * centre_y(x) - W / 2.0) for x in xs[::-1]]
    return mp.Prism(top + bottom, height=mp.inf, material=mp.Medium(index=N_CORE))


fcen, df = 1.0 / 1.55, 0.08
x_src, x_mon = -(x_end - 0.5), x_end - 1.0
sim = mp.Simulation(cell_size=cell, resolution=RES, default_material=mp.Medium(index=N_CLAD),
                    geometry=[guide(+1.0), guide(-1.0)], boundary_layers=[mp.PML(PML)],
                    sources=[mp.EigenModeSource(mp.GaussianSource(fcen, fwidth=df), center=mp.Vector3(x_src, y_out),
                                                size=mp.Vector3(0, 1.8), eig_band=1, eig_parity=mp.EVEN_Z,
                                                eig_match_freq=True)])
ports = {"o1": (-x_mon, y_out), "o2": (-x_mon, -y_out), "o3": (x_mon, y_out), "o4": (x_mon, -y_out)}
monitors = {name: sim.add_mode_monitor(list(FREQS), mp.ModeRegion(center=mp.Vector3(x, y), size=mp.Vector3(0, 1.8)))
            for name, (x, y) in ports.items()}

result = frt.run(sim, until_after_sources=250, precision="float64")
alpha = {name: sim.get_eigenmode_coefficients(m, [1], eig_parity=mp.EVEN_Z).alpha[0] for name, m in monitors.items()}
incident = alpha["o1"][:, 0]                                    # forward (+x) at o1
column = {"o1": alpha["o1"][:, 1] / incident, "o2": alpha["o2"][:, 1] / incident,   # backward at the left ports
          "o3": alpha["o3"][:, 0] / incident, "o4": alpha["o4"][:, 0] / incident}    # forward at the right ports

# S[(out, in)] from the o1 column and the two mirrors: y swaps o1<->o2, o3<->o4; x swaps o1<->o3, o2<->o4
mirror_y, mirror_x = {"o1": "o2", "o2": "o1", "o3": "o4", "o4": "o3"}, {"o1": "o3", "o3": "o1", "o2": "o4", "o4": "o2"}
s = {(out, "o1"): column[out] for out in column}
for move in (mirror_y, mirror_x, lambda p: mirror_x[mirror_y[p]]):
    step = move.get if isinstance(move, dict) else move
    for out in column:
        s[(step(out), step("o1"))] = column[out]

meta = {"tool": "Meep on fieldrt (fieldrt.meep.run)", "fieldrt": getattr(fieldrt, "__version__", "?"),
        "meep": mp.__version__, "backend": result.meta.get("backend", {}).get("name"),
        "precision": result.meta.get("precision"), "resolution_px_per_um": RES,
        "model": "2D effective index: core 2.85, cladding 1.444, w 0.5 um, gap 0.2 um, L 10 um",
        "symmetry": "one run at o1; the other columns from the top-bottom and left-right mirrors",
        "date": datetime.date.today().isoformat(), "python": sys.version.split()[0]}
# optodraw's layout (SParameters.load): "<out>@0,<in>@0", as fieldrt.sax
np.savez(HERE / ("coupler_fieldrt.npz" if RES == 45 else f"coupler_res{RES}.npz"), wavelengths_um=WL,
         **{f"{out}@0,{inp}@0": value for (out, inp), value in s.items()}, meta=json.dumps(meta))
bar, cross = np.abs(s[("o3", "o1")]) ** 2, np.abs(s[("o4", "o1")]) ** 2
i = int(np.argmin(np.abs(WL - 1.55)))
print(json.dumps(meta, indent=1))
print(f"at 1550 nm: bar {bar[i]:.4f}, cross {cross[i]:.4f}, back {abs(s[('o2', 'o1')][i])**2:.2e}, "
      f"reflection {abs(s[('o1', 'o1')][i])**2:.2e}, total {bar[i] + cross[i]:.4f}")
print(f"cross over band: {cross.min():.4f} .. {cross.max():.4f}")
