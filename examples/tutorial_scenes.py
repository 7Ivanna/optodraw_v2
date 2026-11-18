"""Scene builders for the public tutorial notebooks.

Every on-chip builder measures drawn extent before it places parts, routes with
``path_type="smooth"``, and can list optical ports that nobody connected.
These are schematic reconstructions for teaching. They are not copies of a
paper's artwork and they are not fabrication GDS.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from optodraw import (
    AWG,
    MZM,
    Beam,
    BeamSplitter,
    Camera,
    ElectricalPad,
    Filter,
    FourFSystem,
    Grid,
    HalfWavePlate,
    Laser,
    Lens,
    MicroringResonator,
    MicroringWeightBank,
    Mirror,
    Objective,
    OnChipPhotodetector,
    PBS,
    Polarizer,
    Sample,
    Scene,
    Spectrometer,
    Terminator,
    VerticalGratingCoupler,
)
from optodraw.layout import aim, chain_ports
from optodraw.presets import _objective_focus

PAPERS: dict[str, dict[str, str]] = {
    "bogaerts2012": {
        "citation": (
            "Bogaerts, W. et al. Silicon microring resonators. "
            "Laser Photonics Rev. 6, 47-73 (2012)."
        ),
        "doi": "10.1002/lpor.201100017",
        "note": "Add-drop ring schematic after the review's device diagrams, not a copy of a figure.",
    },
    "reed2010": {
        "citation": (
            "Reed, G. T., Mashanovich, G., Gardes, F. Y. and Thomson, D. J. "
            "Silicon optical modulators. Nat. Photonics 4, 518-526 (2010)."
        ),
        "doi": "10.1038/nphoton.2010.179",
        "note": "Mach-Zehnder modulator with a GSG probe, after the review's MZI diagrams.",
    },
    "smit1996": {
        "citation": (
            "Smit, M. K. and van Dam, C. PHASAR-based WDM-devices: Principles, "
            "design and applications. IEEE J. Sel. Top. Quantum Electron. 2, 236-250 (1996)."
        ),
        "doi": "10.1109/2944.577370",
        "note": "1x4 arrayed-waveguide grating demux after the PHASAR geometry, not a copy of Fig. 1.",
    },
    "tait2017": {
        "citation": (
            "Tait, A. N. et al. Neuromorphic photonic networks using silicon photonic "
            "weight banks. Sci. Rep. 7, 7430 (2017)."
        ),
        "doi": "10.1038/s41598-017-07754-z",
        "note": "Broadcast-and-weight bank on a bus, after the architecture in that paper.",
    },
    "conchello2005": {
        "citation": (
            "Conchello, J.-A. and Lichtman, J. W. Optical sectioning microscopy. "
            "Nat. Methods 2, 920-931 (2005)."
        ),
        "doi": "10.1038/nmeth815",
        "note": "Confocal photoluminescence path that follows the confocal idea in that review.",
    },
}


def measure_extent(component) -> tuple[float, float, float, float]:
    """Return the drawn box ``(x0, y0, x1, y1)`` of one component at the origin."""

    probe = Scene(title="", width=2000, height=2000, platform="on_chip")
    probe.add(component)
    return probe.content_bounds()


def half_size(component) -> tuple[float, float]:
    x0, y0, x1, y1 = measure_extent(component)
    return 0.5 * (x1 - x0), 0.5 * (y1 - y0)


def dangling_optical_ports(scene: Scene, connected: Iterable[tuple[object, str]]) -> list[str]:
    """Return ``component_label:port`` for optical ports that were never routed."""

    used = {(id(comp), name) for comp, name in connected}
    dangling: list[str] = []
    for component in scene.walk():
        ports = getattr(component, "ports", None)
        if not callable(ports):
            continue
        for name, port in ports().items():
            kind = getattr(port, "kind", "optical")
            if kind not in {"optical", "free_space"} and not name.startswith(("o", "i", "d")):
                continue
            if kind == "electrical":
                continue
            if (id(component), name) in used:
                continue
            if name.startswith(("e", "h", "gnd", "sig")):
                continue
            label = getattr(component, "label", None) or component.__class__.__name__
            dangling.append(f"{label}:{name}")
    return dangling


HOP = 20.0


def _chain(links):
    return chain_ports(links, gap=HOP, grid=0.0)


def _wg(scene: Scene, a, ap: str, b, bp: str):
    return scene.route((a, ap), (b, bp), kind="waveguide", path_type="smooth")


def _rf(scene: Scene, a, ap: str, b, bp: str, *, width: float, west: float, rail_y: float):
    """Leave the MZM as an L of a given west length, then jog on a rail to the pad."""

    return scene.route(
        (a, ap),
        (b, bp),
        kind="electrical",
        path_type="L",
        start_straight_length=west,
        end_straight_length=3.0,
        width=width,
        steps=[{"y": rail_y}],
    )


def _finish(scene: Scene, connected: list[tuple[object, str]], paper: str | None = None) -> Scene:
    scene.metadata["dangling"] = dangling_optical_ports(scene, connected)
    if paper is not None:
        scene.metadata["paper"] = PAPERS[paper]
    scene.fit_frame(margin=16.0)
    return scene


def _gsg_square_pads(scene: Scene, mzm, mzm_hh: float):
    """Three square pads above the MZM. Each net is its own pad."""

    pad_hw, pad_hh = half_size(ElectricalPad(width=16.0, height=16.0, port_side="bottom", label="S"))
    pitch = 2.0 * pad_hw + 6.0
    y = float(mzm.transform.position.y) + mzm_hh + 20.0 + pad_hh
    x_g2 = float(mzm.world_ports()["gnd2"].center.x) - 24.0     # west of the three cable lanes: no crossing
    pads = {}
    for i, label in enumerate(("G2", "S", "G1")):
        pads[label] = scene.add(
            ElectricalPad(
                center=(x_g2 + i * pitch, y),
                width=16.0,
                height=16.0,
                port_side="bottom",
                label=label,
            )
        )
    return pads


def fold_and_focus() -> Scene:
    """Laser, fold mirror, lens. The first demo."""

    scene = Scene(title="Fold and focus", width=220, height=120, platform="free_space")
    scene.add(Grid(width=220, height=120, pitch=20))
    laser = scene.add(Laser(center=(-75, 0), wavelength=532, label="Pump"))
    mirror = scene.add(Mirror(center=(20, 0), angle=45, label="M1", label_side="right"))
    lens = scene.add(Lens(center=(20, 42), angle=90, focal_length=30, label="L1"))
    aim(mirror, laser, lens)
    scene.add(Beam.through(laser, mirror, lens, wavelength=532, label="Excitation"))
    return scene


def polarization_bench() -> Scene:
    """HeNe, half-wave plate, polarizer, PBS."""

    scene = Scene(title="Polarization bench", width=260, height=100, platform="free_space")
    scene.add(Grid(width=260, height=100, pitch=20))
    laser = scene.add(Laser(center=(-100, 0), wavelength=633, label="HeNe"))
    hwp = scene.add(HalfWavePlate(center=(-40, 0), fast_axis_angle=22.5, label="HWP"))
    pol = scene.add(Polarizer(center=(10, 0), axis_angle=0, label="Pol"))
    pbs = scene.add(PBS(center=(60, 0), label="PBS"))
    scene.add(Beam(laser, hwp, pol, pbs, wavelength=633))
    return scene


def gc_ring_photodetector() -> Scene:
    """Drop receiver: GC in, ring, PD on drop, terminator on through."""

    scene = Scene(title="GC, ring, photodetector", width=320, height=140, platform="on_chip")
    gc = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="GC"))
    ring = scene.add(MicroringResonator(add_drop=True, label="Ring"))
    pd = scene.add(OnChipPhotodetector(angle=180, label="PD"))        # on the drop, west: faces the ring
    term = scene.add(Terminator(label="term"))
    add = scene.add(Terminator(label="add"))
    _chain(
        [
            (gc, "o1", ring, "o1"),
            (ring, "o3", pd, "o1"),
            (ring, "o2", term, "o1"),
            (ring, "o4", add, "o1"),
        ],
    )
    _wg(scene, gc, "o1", ring, "o1")
    _wg(scene, ring, "o3", pd, "o1")
    _wg(scene, ring, "o2", term, "o1")
    _wg(scene, ring, "o4", add, "o1")
    return _finish(
        scene,
        [(gc, "o1"), (ring, "o1"), (ring, "o2"), (ring, "o3"), (ring, "o4"), (pd, "o1"), (term, "o1"), (add, "o1")],
    )


def bogaerts_add_drop() -> Scene:
    """Add-drop microring with through grating coupler and drop photodetector.

    Schematic reconstruction after Bogaerts et al., Laser Photonics Rev. 2012.
    """

    scene = Scene(title="Add-drop ring (after Bogaerts 2012)", width=360, height=160, platform="on_chip")
    gc_in = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="in"))
    ring = scene.add(MicroringResonator(add_drop=True, label="ring"))
    gc_th = scene.add(VerticalGratingCoupler(angle=0, label="through"))
    pd = scene.add(OnChipPhotodetector(angle=180, label="drop PD"))   # the drop leaves west (Bogaerts Fig. 1)
    add = scene.add(Terminator(label="add"))
    _chain(
        [
            (gc_in, "o1", ring, "o1"),
            (ring, "o2", gc_th, "o1"),
            (ring, "o3", pd, "o1"),
            (ring, "o4", add, "o1"),
        ],
    )
    _wg(scene, gc_in, "o1", ring, "o1")
    _wg(scene, ring, "o2", gc_th, "o1")
    _wg(scene, ring, "o3", pd, "o1")
    _wg(scene, ring, "o4", add, "o1")
    return _finish(
        scene,
        [
            (gc_in, "o1"),
            (ring, "o1"),
            (ring, "o2"),
            (ring, "o3"),
            (ring, "o4"),
            (gc_th, "o1"),
            (pd, "o1"),
            (add, "o1"),
        ],
        paper="bogaerts2012",
    )


def reed_mzm_probe() -> Scene:
    """MZM with a GSG probe, after Reed et al., Nat. Photonics 2010."""

    mzm_hh = half_size(MZM(drive_style="gsg", label="MZM"))[1]

    scene = Scene(title="MZM with GSG probe (after Reed 2010)", width=400, height=200, platform="on_chip")
    gc = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="in"))
    mzm = scene.add(MZM(drive_style="gsg", label="MZM"))
    pd = scene.add(OnChipPhotodetector(label="PD"))
    _chain([(gc, "o1", mzm, "o1"), (mzm, "o3", pd, "o1")])
    pads = _gsg_square_pads(scene, mzm, mzm_hh)
    mzm_top = float(mzm.transform.position.y) + mzm_hh
    _wg(scene, gc, "o1", mzm, "o1")
    _wg(scene, mzm, "o3", pd, "o1")
    _rf(scene, mzm, "gnd1", pads["G1"], "e1", width=2.4, west=6.0, rail_y=mzm_top + 9.0)
    _rf(scene, mzm, "sig", pads["S"], "e1", width=1.4, west=12.0, rail_y=mzm_top + 15.0)
    _rf(scene, mzm, "gnd2", pads["G2"], "e1", width=2.4, west=18.0, rail_y=mzm_top + 3.0)
    return _finish(
        scene,
        [(gc, "o1"), (mzm, "o1"), (mzm, "o3"), (pd, "o1")],
        paper="reed2010",
    )


def smit_awg_demux() -> Scene:
    """1x4 AWG demultiplexer after Smit and van Dam, IEEE JSTQE 1996."""

    pd_hh = half_size(OnChipPhotodetector(label="PD"))[1]
    pitch = max(2.2 * pd_hh, 32.0)
    n = 4

    scene = Scene(title="1x4 AWG demux (after Smit 1996)", width=520, height=240, platform="on_chip")
    gc = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="in"))
    awg = scene.add(AWG(channel_count=4, array_count=8, label="AWG"))
    _chain([(gc, "o1", awg, "i1")])
    outs = [awg.world_ports()[f"o{i}"] for i in range(1, n + 1)]
    pd_ys = [(i - 1.5) * pitch for i in range(n)]
    rise = max(abs(pd_ys[i] - float(outs[i].center.y)) for i in range(n))
    gap_out = max(1.5 * rise, 48.0)
    x_port = max(float(port.center.x) for port in outs) + gap_out
    local_x = float(OnChipPhotodetector(label="PD").ports()["o1"].center.x)
    pds = [
        scene.add(OnChipPhotodetector(center=(x_port - local_x, pd_ys[i]), label=f"PD{i + 1}",
                                       label_side="right"))
        for i in range(n)
    ]
    _wg(scene, gc, "o1", awg, "i1")
    connected: list[tuple[object, str]] = [(gc, "o1"), (awg, "i1")]
    for i, pd in enumerate(pds, start=1):
        _wg(scene, awg, f"o{i}", pd, "o1")
        connected.extend([(awg, f"o{i}"), (pd, "o1")])
    return _finish(scene, connected, paper="smit1996")


def tait_weight_bank() -> Scene:
    """Microring weight bank on a bus, after Tait et al., Sci. Rep. 2017."""

    scene = Scene(title="Microring weight bank (after Tait 2017)", width=420, height=180, platform="on_chip")
    gc = scene.add(VerticalGratingCoupler(center=(0, 0), angle=180, label="WDM in"))
    bank = scene.add(MicroringWeightBank(ring_count=4, with_heaters=True, label="weight bank"))
    pd = scene.add(OnChipPhotodetector(label="sum PD"))
    term = scene.add(Terminator(label="through"))
    _chain(
        [
            (gc, "o1", bank, "o1"),
            (bank, "drop", pd, "o1"),
            (bank, "o2", term, "o1"),
        ],
    )
    _wg(scene, gc, "o1", bank, "o1")
    _wg(scene, bank, "drop", pd, "o1")
    _wg(scene, bank, "o2", term, "o1")
    return _finish(
        scene,
        [(gc, "o1"), (bank, "o1"), (bank, "drop"), (bank, "o2"), (pd, "o1"), (term, "o1")],
        paper="tait2017",
    )


def conchello_confocal() -> Scene:
    """Confocal PL path after Conchello and Lichtman, Nat. Methods 2005."""

    # Epi-illumination on one vertical axis: the pump reflects down off the dichroic into the objective, the
    # PL returns up and transmits through the dichroic and a longpass filter to the detection splitter.
    scene = Scene(title="Confocal PL (after Conchello 2005)", width=240, height=240, platform="free_space")
    scene.add(Grid(width=240, height=240, pitch=20))
    laser = scene.add(Laser(center=(-70, 0), wavelength=532, label="532 nm Pump"))
    # the edge sits between the 532 nm pump and the 650 nm emission
    dichroic = scene.add(BeamSplitter(center=(0, 0), angle=45, dichroic=True, cutoff_wavelength=550,
                                      label="Dichroic", label_side="right"))
    # a long-working-distance objective focuses through the cryostat window; the sample sits at its focus
    objective = scene.add(Objective(center=(0, -45), angle=-90, working_distance=29.5, label="100x LWD Obj",
                                    label_side="right"))
    sample = scene.add(Sample(center=_objective_focus(objective), angle=-90, in_cryostat=True, label="Sample",
                              label_side="right"))
    emission_filter = scene.add(Filter(center=(0, 38), angle=90, cutoff_wavelength=550, pass_band="longpass",
                                       label="LP Filter", label_side="right"))
    detect_bs = scene.add(BeamSplitter(center=(0, 64), angle=135, label="Detect BS", label_side="left"))
    spectrometer = scene.add(Spectrometer(center=(0, 96), angle=90, label="Spectrometer"))
    camera = scene.add(Camera(center=(36, 64), angle=0, label="CCD"))
    scene.add(Beam((laser, "out"), (dichroic, "in"), (dichroic, "refl"), (objective, "in"), (objective, "out"),
                   (sample, "in"), wavelength=532, label="Pump"))
    scene.add(Beam((sample, "in"), (objective, "out"), (objective, "in"), (dichroic, "refl"), (dichroic, "tap"),
                   (emission_filter, "in"), (emission_filter, "out"), (detect_bs, "in"), (detect_bs, "trans"),
                   (spectrometer, "in"), wavelength=650, width=1.0, label="PL"))
    scene.add(Beam((detect_bs, "in"), (detect_bs, "refl"), (camera, "in"), wavelength=650, width=1.0, label="Image"))
    scene.metadata["paper"] = PAPERS["conchello2005"]
    return scene


def four_f_relay() -> Scene:
    """4f relay as a single component plus a source."""

    scene = Scene(title="4f relay", width=260, height=100, platform="free_space")
    scene.add(Grid(width=260, height=100, pitch=20))
    laser = scene.add(Laser(center=(-110, 0), wavelength=532, label="object"))
    relay = scene.add(FourFSystem(center=(0, 0), focal_length_1=25, focal_length_2=25, label="4f"))
    scene.add(Beam(laser, relay, wavelength=532))
    return scene


TUTORIALS: Sequence[tuple[str, str, Callable[[], Scene]]] = (
    ("fold_and_focus", "simple", fold_and_focus),
    ("polarization_bench", "simple", polarization_bench),
    ("gc_ring_photodetector", "simple", gc_ring_photodetector),
    ("bogaerts_add_drop", "paper", bogaerts_add_drop),
    ("reed_mzm_probe", "paper", reed_mzm_probe),
    ("smit_awg_demux", "paper", smit_awg_demux),
    ("tait_weight_bank", "paper", tait_weight_bank),
    ("conchello_confocal", "paper", conchello_confocal),
    ("four_f_relay", "simple", four_f_relay),
)
