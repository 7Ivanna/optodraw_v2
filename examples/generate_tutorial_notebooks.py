"""Write tutorial notebooks with the layout skill in the cells, not behind an import."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

EXAMPLES = Path(__file__).resolve().parent

HALF_SIZE = """
from optodraw import Scene

def half_size(component):
    probe = Scene(title="", width=2000, height=2000, platform="on_chip")
    probe.add(component)
    x0, y0, x1, y1 = probe.content_bounds()
    return 0.5 * (x1 - x0), 0.5 * (y1 - y0)
"""

DANGLING = """
def dangling_optical(scene, connected):
    used = {(id(comp), name) for comp, name in connected}
    leftover = []
    for component in scene.walk():
        ports = getattr(component, "ports", None)
        if not callable(ports):
            continue
        for name, port in ports().items():
            if getattr(port, "kind", "optical") in ("electrical", "fiber"):   # a fibre port is the off-chip side
                continue
            if name.startswith(("e", "h", "gnd", "sig")):
                continue
            if (id(component), name) in used:
                continue
            label = getattr(component, "label", None) or component.__class__.__name__
            leftover.append(f"{label}:{name}")
    return leftover
"""

PREVIEW = """
print("bounds", scene.content_bounds())
scene.preview(show_3d=False)
"""


def _source(text: str) -> list[str]:
    body = dedent(text).strip("\n")
    return [f"{line}\n" for line in body.splitlines()]


def _markdown(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _source(text)}


def _code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": _source(text),
    }


def _notebook(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


NOTEBOOKS: list[tuple[str, list[dict]]] = [
    (
        "fold_and_focus",
        [
            _markdown(
                """
                # Fold and focus

                Place a laser, a fold mirror, and a lens. Look at the scene with
                `preview()`, not `render_svg()`. A raw SVG grows with the layout
                and scrolls the notebook page.
                """
            ),
            _code(
                """
                from optodraw import Scene, Grid, Laser, Mirror, Lens, Beam

                scene = Scene(title="Fold and focus", width=220, height=120, platform="free_space")
                scene.add(Grid(width=220, height=120, pitch=20))
                laser = scene.add(Laser(center=(-75, 0), wavelength=532, label="Pump"))
                mirror = scene.add(Mirror(center=(20, 0), angle=45, label="M1", label_side="right"))
                lens = scene.add(Lens(center=(20, 42), angle=90, focal_length=30, label="L1"))
                _ = scene.add(Beam(laser, mirror, lens, wavelength=532, label="Excitation"))
                """
            ),
            _code(PREVIEW),
        ],
    ),
    (
        "polarization_bench",
        [
            _markdown(
                """
                # Polarization bench

                A 633 nm source, a half-wave plate, a polarizer, and a PBS.
                """
            ),
            _code(
                """
                from optodraw import Scene, Grid, Laser, HalfWavePlate, Polarizer, PBS, Beam

                scene = Scene(title="Polarization bench", width=260, height=100, platform="free_space")
                scene.add(Grid(width=260, height=100, pitch=20))
                laser = scene.add(Laser(center=(-100, 0), wavelength=633, label="HeNe"))
                hwp = scene.add(HalfWavePlate(center=(-40, 0), fast_axis_angle=22.5, label="HWP"))
                pol = scene.add(Polarizer(center=(10, 0), axis_angle=0, label="Pol"))
                pbs = scene.add(PBS(center=(60, 0), label="PBS"))
                scene.add(Beam(laser, hwp, pol, pbs, wavelength=633))
                print(pol.physics_metadata())
                """
            ),
            _code(PREVIEW),
        ],
    ),
    (
        "four_f_relay",
        [
            _markdown(
                """
                # 4f relay

                A 4f system as one component: object plane, Fourier plane, image plane.
                """
            ),
            _code(
                """
                from optodraw import Scene, Grid, Laser, FourFSystem, Beam

                scene = Scene(title="4f relay", width=260, height=100, platform="free_space")
                scene.add(Grid(width=260, height=100, pitch=20))
                laser = scene.add(Laser(center=(-110, 0), wavelength=532, label="object"))
                relay = scene.add(FourFSystem(center=(0, 0), focal_length_1=25, focal_length_2=25, label="4f"))
                scene.add(Beam(laser, relay, wavelength=532))
                print(relay.physics_metadata())
                """
            ),
            _code(PREVIEW),
        ],
    ),
    (
        "gc_ring_photodetector",
        [
            _markdown(
                """
                # Grating coupler, ring, photodetector

                Place each part in front of the port that feeds it
                (`chain_ports`). That keeps the figure compact and the
                waveguide a short hop. Route with `path_type="smooth"`.
                List optical ports that nobody connected.
                """
            ),
            _code(HALF_SIZE),
            _code(DANGLING),
            _code(
                """
                from optodraw import Scene, VerticalGratingCoupler, MicroringResonator, OnChipPhotodetector, Terminator
                from optodraw.layout import chain_ports

                print("PD half size", half_size(OnChipPhotodetector(label="PD")))
                HOP = 20.0
                """
            ),
            _code(
                """
                scene = Scene(title="GC, ring, photodetector", width=320, height=140, platform="on_chip")
                gc = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="GC"))
                ring = scene.add(MicroringResonator(add_drop=True, label="Ring"))
                pd = scene.add(OnChipPhotodetector(angle=180, label="PD"))        # on the drop, west: faces the ring
                term = scene.add(Terminator(label="term"))
                add = scene.add(Terminator(label="add"))
                chain_ports(
                    [(gc, "o1", ring, "o1"), (ring, "o3", pd, "o1"), (ring, "o2", term, "o1"), (ring, "o4", add, "o1")],
                    gap=HOP, grid=0,
                )
                scene.route((gc, "o1"), (ring, "o1"), kind="waveguide", path_type="smooth")
                scene.route((ring, "o3"), (pd, "o1"), kind="waveguide", path_type="smooth")
                scene.route((ring, "o2"), (term, "o1"), kind="waveguide", path_type="smooth")
                scene.route((ring, "o4"), (add, "o1"), kind="waveguide", path_type="smooth")
                leftover = dangling_optical(
                    scene,
                    [(gc, "o1"), (ring, "o1"), (ring, "o2"), (ring, "o3"), (ring, "o4"), (pd, "o1"), (term, "o1"), (add, "o1")],
                )
                print("unconnected", leftover)
                scene.fit_frame(margin=16)
                """
            ),
            _code(PREVIEW),
        ],
    ),
    (
        "bogaerts_add_drop",
        [
            _markdown(
                """
                # Add-drop microring

                Schematic reconstruction after Bogaerts et al., Laser Photonics Rev.
                2012 ([doi:10.1002/lpor.201100017](https://doi.org/10.1002/lpor.201100017)).

                Cite that paper for the device. Cite optodraw for the drawing.
                This is not a copy of a figure from that review.
                """
            ),
            _code(HALF_SIZE),
            _code(DANGLING),
            _code(
                """
                from optodraw import Scene, VerticalGratingCoupler, MicroringResonator, OnChipPhotodetector, Terminator
                from optodraw.layout import chain_ports

                print("ring half size", half_size(MicroringResonator(add_drop=True, label="ring")))
                HOP = 20.0
                """
            ),
            _code(
                """
                scene = Scene(title="Add-drop ring (after Bogaerts 2012)", width=360, height=160, platform="on_chip")
                gc_in = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="in"))
                ring = scene.add(MicroringResonator(add_drop=True, label="ring"))
                gc_th = scene.add(VerticalGratingCoupler(angle=0, label="through"))
                pd = scene.add(OnChipPhotodetector(angle=180, label="drop PD"))   # the drop leaves west (Bogaerts Fig. 1)
                add = scene.add(Terminator(label="add"))
                chain_ports(
                    [(gc_in, "o1", ring, "o1"), (ring, "o2", gc_th, "o1"), (ring, "o3", pd, "o1"), (ring, "o4", add, "o1")],
                    gap=HOP, grid=0,
                )
                scene.route((gc_in, "o1"), (ring, "o1"), kind="waveguide", path_type="smooth")
                scene.route((ring, "o2"), (gc_th, "o1"), kind="waveguide", path_type="smooth")
                scene.route((ring, "o3"), (pd, "o1"), kind="waveguide", path_type="smooth")
                scene.route((ring, "o4"), (add, "o1"), kind="waveguide", path_type="smooth")
                leftover = dangling_optical(
                    scene,
                    [(gc_in, "o1"), (ring, "o1"), (ring, "o2"), (ring, "o3"), (ring, "o4"), (gc_th, "o1"), (pd, "o1"), (add, "o1")],
                )
                print("unconnected", leftover)
                scene.fit_frame(margin=16)
                """
            ),
            _code(PREVIEW),
        ],
    ),
    (
        "reed_mzm_probe",
        [
            _markdown(
                """
                # Silicon MZM with a GSG probe

                Schematic reconstruction after Reed et al., Nat. Photonics 2010
                ([doi:10.1038/nphoton.2010.179](https://doi.org/10.1038/nphoton.2010.179)).

                Each GSG landing is its own square `ElectricalPad`. The MZM
                electrical ports leave as `path_type="L"` traces at different
                widths and west lengths, then jog on stacked rails to the pads
                above so the nets do not cross the optical input.
                """
            ),
            _code(HALF_SIZE),
            _code(DANGLING),
            _code(
                """
                from optodraw import Scene, VerticalGratingCoupler, MZM, OnChipPhotodetector, ElectricalPad
                from optodraw.layout import chain_ports

                mzm_hh = half_size(MZM(drive_style="gsg", label="MZM"))[1]
                pad_hw, pad_hh = half_size(ElectricalPad(width=16, height=16, port_side="bottom", label="S"))
                PITCH = 2.0 * pad_hw + 6.0
                HOP = 20.0
                print("MZM half height", mzm_hh, "pad pitch", PITCH)
                """
            ),
            _code(
                """
                scene = Scene(title="MZM with GSG probe (after Reed 2010)", width=400, height=200, platform="on_chip")
                gc = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="in"))
                mzm = scene.add(MZM(drive_style="gsg", label="MZM"))
                pd = scene.add(OnChipPhotodetector(label="PD"))
                chain_ports([(gc, "o1", mzm, "o1"), (mzm, "o3", pd, "o1")], gap=HOP, grid=0)
                mzm_top = float(mzm.transform.position.y) + mzm_hh
                y_pad = mzm_top + 20.0 + pad_hh
                x_mid = float(mzm.transform.position.x)
                pads = {
                    name: scene.add(ElectricalPad(center=(x_mid + (i - 1) * PITCH, y_pad), width=16, height=16, port_side="bottom", label=name))
                    for i, name in enumerate(("G2", "S", "G1"))
                }
                scene.route((gc, "o1"), (mzm, "o1"), kind="waveguide", path_type="smooth")
                scene.route((mzm, "o3"), (pd, "o1"), kind="waveguide", path_type="smooth")
                for port, name, width, west, rail in (
                    ("gnd1", "G1", 2.4, 6.0, mzm_top + 9.0),
                    ("sig", "S", 1.4, 12.0, mzm_top + 15.0),
                    ("gnd2", "G2", 2.4, 18.0, mzm_top + 3.0),
                ):
                    scene.route(
                        (mzm, port),
                        (pads[name], "e1"),
                        kind="electrical",
                        path_type="L",
                        start_straight_length=west,
                        end_straight_length=3,
                        width=width,
                        steps=[{"y": rail}],
                    )
                leftover = dangling_optical(scene, [(gc, "o1"), (mzm, "o1"), (mzm, "o3"), (pd, "o1")])
                print("unconnected", leftover)
                scene.fit_frame(margin=16)
                """
            ),
            _code(PREVIEW),
        ],
    ),
    (
        "smit_awg_demux",
        [
            _markdown(
                """
                # 1x4 AWG demultiplexer

                Schematic reconstruction after Smit and van Dam, IEEE J. Sel. Top.
                Quantum Electron. 1996
                ([doi:10.1109/2944.577370](https://doi.org/10.1109/2944.577370)).

                Chain the input coupler onto `i1`. Fan the four detectors out
                at 1.5 times the rise, with pitch from the detector height.
                `o1` is the lowest output.
                """
            ),
            _code(HALF_SIZE),
            _code(DANGLING),
            _code(
                """
                from optodraw import Scene, AWG, VerticalGratingCoupler, OnChipPhotodetector
                from optodraw.layout import chain_ports

                pd_hh = half_size(OnChipPhotodetector(label="PD"))[1]
                PITCH = max(2.2 * pd_hh, 32.0)
                HOP = 20.0
                print("PD half height", pd_hh, "pitch", PITCH)
                """
            ),
            _code(
                """
                scene = Scene(title="1x4 AWG demux (after Smit 1996)", width=520, height=240, platform="on_chip")
                gc = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="in"))
                awg = scene.add(AWG(channel_count=4, array_count=8, label="AWG"))
                chain_ports([(gc, "o1", awg, "i1")], gap=HOP, grid=0)
                n = 4
                outs = [awg.world_ports()[f"o{i}"] for i in range(1, n + 1)]
                pd_ys = [(i - 1.5) * PITCH for i in range(n)]
                rise = max(abs(pd_ys[i] - float(outs[i].center.y)) for i in range(n))
                gap_out = max(1.5 * rise, 48.0)
                x_port = max(float(port.center.x) for port in outs) + gap_out
                local_x = float(OnChipPhotodetector(label="PD").ports()["o1"].center.x)
                pds = [
                    scene.add(OnChipPhotodetector(center=(x_port - local_x, pd_ys[i]), label=f"PD{i + 1}",
                                                   label_side="right"))
                    for i in range(n)
                ]
                scene.route((gc, "o1"), (awg, "i1"), kind="waveguide", path_type="smooth")
                connected = [(gc, "o1"), (awg, "i1")]
                for i, pd in enumerate(pds, start=1):
                    scene.route((awg, f"o{i}"), (pd, "o1"), kind="waveguide", path_type="smooth")
                    connected.extend([(awg, f"o{i}"), (pd, "o1")])
                print("unconnected", dangling_optical(scene, connected))
                scene.fit_frame(margin=16)
                """
            ),
            _code(PREVIEW),
        ],
    ),
    (
        "tait_weight_bank",
        [
            _markdown(
                """
                # Microring weight bank

                Schematic reconstruction after Tait et al., Sci. Rep. 2017
                ([doi:10.1038/s41598-017-07754-z](https://doi.org/10.1038/s41598-017-07754-z)).

                A WDM bus feeds a four-ring bank. The summed drop port goes to a
                photodetector. Through is terminated. Per-ring taps `d1`..`d4`
                stay unwired on purpose.
                """
            ),
            _code(HALF_SIZE),
            _code(DANGLING),
            _code(
                """
                from optodraw import Scene, VerticalGratingCoupler, MicroringWeightBank, OnChipPhotodetector, Terminator
                from optodraw.layout import chain_ports

                print("bank half size", half_size(MicroringWeightBank(ring_count=4, with_heaters=True, label="weight bank")))
                HOP = 20.0
                """
            ),
            _code(
                """
                scene = Scene(title="Microring weight bank (after Tait 2017)", width=420, height=180, platform="on_chip")
                gc = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="WDM in"))
                bank = scene.add(MicroringWeightBank(ring_count=4, with_heaters=True, label="weight bank"))
                pd = scene.add(OnChipPhotodetector(label="sum PD"))
                term = scene.add(Terminator(label="through"))
                chain_ports(
                    [(gc, "o1", bank, "o1"), (bank, "drop", pd, "o1"), (bank, "o2", term, "o1")],
                    gap=HOP, grid=0,
                )
                scene.route((gc, "o1"), (bank, "o1"), kind="waveguide", path_type="smooth")
                scene.route((bank, "drop"), (pd, "o1"), kind="waveguide", path_type="smooth")
                scene.route((bank, "o2"), (term, "o1"), kind="waveguide", path_type="smooth")
                leftover = dangling_optical(
                    scene,
                    [(gc, "o1"), (bank, "o1"), (bank, "drop"), (bank, "o2"), (pd, "o1"), (term, "o1")],
                )
                print("unconnected", leftover)
                scene.fit_frame(margin=16)
                """
            ),
            _code(PREVIEW),
        ],
    ),
    (
        "conchello_confocal",
        [
            _markdown(
                """
                # Confocal photoluminescence

                Schematic reconstruction of a confocal PL path after Conchello and
                Lichtman, Nat. Methods 2005
                ([doi:10.1038/nmeth815](https://doi.org/10.1038/nmeth815)).

                Pump reflects at the dichroic into a long-working-distance
                objective. Emission transmits to a spectrometer. The sample sits
                at the objective focus so the drawing and the trace agree.
                """
            ),
            _code(
                """
                from optodraw import (Scene, Grid, Laser, BeamSplitter, Objective, Sample, Filter, Spectrometer,
                                      Camera, Beam)
                from optodraw.presets import _objective_focus

                scene = Scene(title="Confocal PL (after Conchello 2005)", width=240, height=240, platform="free_space")
                scene.add(Grid(width=240, height=240, pitch=20))
                laser = scene.add(Laser(center=(-70, 0), wavelength=532, label="532 nm Pump"))
                # the edge sits between the 532 nm pump and the 650 nm emission
                dichroic = scene.add(BeamSplitter(center=(0, 0), angle=45, dichroic=True, cutoff_wavelength=550,
                                                  label="Dichroic", label_side="right"))
                # a long-working-distance objective; the sample sits at its focus
                objective = scene.add(Objective(center=(0, -45), angle=-90, working_distance=29.5,
                                                label="100x LWD Obj", label_side="right"))
                sample = scene.add(Sample(center=_objective_focus(objective), angle=-90, in_cryostat=True,
                                          label="Sample", label_side="right"))
                emission_filter = scene.add(Filter(center=(0, 38), angle=90, cutoff_wavelength=550,
                                                   pass_band="longpass", label="LP Filter", label_side="right"))
                detect_bs = scene.add(BeamSplitter(center=(0, 64), angle=135, label="Detect BS", label_side="left"))
                spectrometer = scene.add(Spectrometer(center=(0, 96), angle=90, label="Spectrometer"))
                camera = scene.add(Camera(center=(36, 64), angle=0, label="CCD"))
                scene.add(Beam((laser, "out"), (dichroic, "in"), (dichroic, "refl"), (objective, "in"),
                               (objective, "out"), (sample, "in"), wavelength=532, label="Pump"))
                scene.add(Beam((sample, "in"), (objective, "out"), (objective, "in"), (dichroic, "refl"),
                               (dichroic, "tap"), (emission_filter, "in"), (emission_filter, "out"),
                               (detect_bs, "in"), (detect_bs, "trans"), (spectrometer, "in"),
                               wavelength=650, width=1.0, label="PL"))
                scene.add(Beam((detect_bs, "in"), (detect_bs, "refl"), (camera, "in"), wavelength=650, width=1.0,
                               label="Image"))
                """
            ),
            _code(PREVIEW),
        ],
    ),
]


def write_notebooks() -> list[Path]:
    written: list[Path] = []
    for name, cells in NOTEBOOKS:
        path = EXAMPLES / f"{name}.ipynb"
        path.write_text(json.dumps(_notebook(cells), indent=1) + "\n")
        written.append(path)
    return written


def _output_text(text: str) -> list[str]:
    if not text:
        return []
    if text.endswith("\n"):
        lines = text.splitlines(keepends=True)
    else:
        lines = [f"{line}\n" for line in text.splitlines()]
        if lines:
            lines[-1] = lines[-1].rstrip("\n")
    return lines


def _mimebundle(data: dict) -> dict:
    bundle: dict = {}
    for key, value in data.items():
        if isinstance(value, str):
            bundle[key] = [value] if value.endswith("\n") or "\n" in value else [value]
        else:
            bundle[key] = value
    return bundle


def execute_notebook(path: Path) -> None:
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output

    nb = json.loads(path.read_text())
    shell = InteractiveShell.instance()
    shell.reset(new_session=True)
    count = 1
    for cell in nb["cells"]:
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        with capture_output() as cap:
            result = shell.run_cell(src)
        outputs: list[dict] = []
        if cap.stdout:
            stdout = "".join(
                line
                for line in cap.stdout.splitlines(keepends=True)
                if not line.startswith("Out[")
            )
            if stdout:
                outputs.append(
                    {"output_type": "stream", "name": "stdout", "text": _output_text(stdout)}
                )
        if cap.stderr:
            outputs.append(
                {"output_type": "stream", "name": "stderr", "text": _output_text(cap.stderr)}
            )
        for rich in cap.outputs:
            data = _mimebundle(dict(rich.data))
            if "text/html" not in data and "image/png" not in data:
                continue
            outputs.append(
                {
                    "output_type": "display_data",
                    "data": data,
                    "metadata": dict(getattr(rich, "metadata", None) or {}),
                }
            )
        if result.result is not None:
            html_repr = getattr(result.result, "_repr_html_", None)
            already = any("text/html" in (o.get("data") or {}) for o in outputs)
            if callable(html_repr) and not already:
                outputs.append(
                    {
                        "output_type": "execute_result",
                        "execution_count": count,
                        "data": {
                            "text/html": [html_repr()],
                            "text/plain": [repr(result.result)],
                        },
                        "metadata": {},
                    }
                )
        if result.error_before_exec is not None or result.error_in_exec is not None:
            err = result.error_in_exec or result.error_before_exec
            outputs.append(
                {
                    "output_type": "error",
                    "ename": type(err).__name__,
                    "evalue": str(err),
                    "traceback": [str(err)],
                }
            )
        cell["outputs"] = outputs
        cell["execution_count"] = count
        count += 1
    path.write_text(json.dumps(nb, indent=1) + "\n")


if __name__ == "__main__":
    import sys

    written = write_notebooks()
    execute = "--execute" in sys.argv or "-e" in sys.argv
    for path in written:
        if execute:
            execute_notebook(path)
            print(f"executed {path}")
        else:
            print(path)
