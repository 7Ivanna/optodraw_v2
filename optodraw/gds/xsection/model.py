"""A cross-section of a layout: the regions a process makes along one cut, ready to draw."""

from __future__ import annotations

import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import MultiPolygon, box

from optodraw.gds.layout import GDSLayout, load_gds_layout
from optodraw.gds.xsection.cut import cut_layout, layer_key
from optodraw.gds.xsection.engine import XSectionEngine
from optodraw.gds.xsection.masks import IntervalSet, LayoutCut
from optodraw.gds.xsection.regions import repair
from optodraw.gds.palette import is_known, material_fill, material_label

MAX_WINDOW = 40.0                              # um: wider than this, a figure of a cut stops being readable
_FIXED = {"passivation": "Passivation"}


@dataclass(frozen=True)
class SectionBeam:
    """A beam that comes in from above the chip and ends at ``s``, ``z`` (um): see :meth:`CrossSection.beam`."""

    s: float
    z: float
    wavelength: float = 633.0
    label: str = ""


@dataclass
class CrossSection:
    regions: dict[str, MultiPolygon]
    materials: dict[str, str]
    labels: dict[str, str]
    doping: dict[str, MultiPolygon]
    steps: list[tuple[str, str, dict[str, MultiPolygon]]]
    window: tuple[float, float]
    findings: list[str] = field(default_factory=list)
    expected: set[str] = field(default_factory=set)      # regions the cut should make
    roles: dict[str, str] = field(default_factory=dict)  # region -> stack role
    source: dict[str, Any] = field(default_factory=dict)  # layout, cut ends, stack or process: for parallel cuts
    beams: list[SectionBeam] = field(default_factory=list)
    fills: dict[str, str] = field(default_factory=dict)  # region -> fill colour, from the table and the stack
    z_window: tuple[float, float] | None = None          # um: the band of z the figure shows; None: all of it

    def beam(self, s: float | None = None, z: float | None = None, *, wavelength: float = 633.0,
             label: str = "") -> SectionBeam:
        """Draw a beam into :meth:`svg`: it comes in from above the chip and ends at ``s``, ``z`` (um). By default
        it ends at the middle of the window, halfway up the device layer there, or on the top of the stack."""

        if s is None:
            s = sum(self.window) / 2.0
        if z is None:
            device = self.regions.get("device")
            if device is not None and not device.is_empty and device.bounds[0] <= s <= device.bounds[2]:
                z = (device.bounds[1] + device.bounds[3]) / 2.0
            else:
                z = max(g.bounds[3] for g in self.regions.values() if not g.is_empty)
        beam = SectionBeam(float(s), float(z), float(wavelength), label)
        self.beams.append(beam)
        return beam

    def check(self) -> list[str]:
        """One sentence per fault of this cross-section; empty when it is clean. Look at the figure too."""

        out = list(self.findings)
        for species, region in self.doping.items():
            if region.is_empty:
                out.append(f"implant {species} falls where the device layer is etched away")
        for name in sorted(self.expected):
            if self.regions.get(name, MultiPolygon([])).is_empty:
                out.append(f"{name} is drawn on the cut but came out empty")
        for name, region in self.regions.items():
            if self.roles.get(name) not in ("contact", "via") or region.is_empty:
                continue
            others = [g for n, g in self.regions.items() if n not in (name, "oxide", "box", "passivation")]
            for piece in region.geoms:
                x0, z0, x1, _ = piece.bounds
                below = box(x0, z0 - 1e-3, x1, z0)
                if not any(g.intersects(below) for g in others):
                    out.append(f"{name} at s = {(x0 + x1) / 2:.2f} um lands on nothing")
        return out

    def svg(self, path: str | Path | None = None, **options: Any) -> str:
        from optodraw.gds.xsection.schematic import render_schematic

        text = render_schematic(self, **options)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def png(self, path: str | Path | None = None, *, look: str = "sem", seed: int = 0, mark: bool = True,
            width_px: int = 2000) -> bytes:
        """Look B: an SEM-like image as PNG bytes, written to ``path`` when given. It is marked as a render;
        ``mark=False`` removes the visible marks, the PNG metadata stays."""

        if look != "sem":
            raise ValueError(f"png() draws the SEM-like look (look='sem'), not {look!r}; the schematic is svg()")
        if self.z_window is not None:
            raise ValueError("png() draws the whole section, and this one has a z window: make it with z=None")
        from optodraw.gds.xsection.sem import render_sem

        data = render_sem(self, seed=seed, mark=mark, width_px=width_px)
        if path is not None:
            Path(path).write_bytes(data)
        return data

    def steps_svg(self, path: str | Path | None = None, **options: Any) -> str:
        from optodraw.gds.xsection.schematic import render_steps

        text = render_steps(self, **options)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def slab(self, path: str | Path | None = None, *, depth: float | None = None, cutaway: bool = True,
             z_scale: float = 1.0, **image: Any) -> Any:
        """Look C: the cut 3D slab, ``depth`` um deep behind the face (default: as deep as the window is wide),
        the cladding cut away in steps when ``cutaway``. ``path`` ends in .glb, .png (the viewer, headless;
        ``image`` takes the options of the 3D image) or .html (the interactive view); with no path, the
        scene that holds the slab."""

        from optodraw.gds.xsection.slab import render_slab, slab_glb, slab_model, slab_scene

        suffix = Path(path).suffix.lower() if path is not None else None
        if suffix not in (None, ".glb", ".png", ".html"):
            raise ValueError(f"a slab is written as .glb, .png or .html, not {suffix!r}")
        model = slab_model(self, depth=depth, cutaway=cutaway, z_scale=z_scale)
        if path is None:
            return slab_scene(model)
        out = Path(path)
        if suffix == ".glb":
            out.write_bytes(slab_glb(model))
        elif suffix == ".png":
            render_slab(model, out, **image)
        else:
            slab_scene(model).render_threejs(str(out), show_labels=False)
        return out


def _auto_window(cut: LayoutCut) -> tuple[tuple[float, float], str | None]:
    hits = [item for intervals in cut.layer_intervals.values() for item in intervals.intervals]
    if not hits:
        return (cut.y_min, cut.y_max), None
    lo, hi = min(item.y0 for item in hits), max(item.y1 for item in hits)
    margin = max(1.0, 0.25 * (hi - lo))
    s0, s1 = max(cut.y_min, lo - margin), min(cut.y_max, hi + margin)
    if s1 - s0 <= MAX_WINDOW:
        return (s0, s1), None
    middle = (lo + hi) / 2.0
    nearest = min(hits, key=lambda item: abs((item.y0 + item.y1) / 2.0 - middle))
    centre = (nearest.y0 + nearest.y1) / 2.0
    s0 = max(cut.y_min, centre - MAX_WINDOW / 2.0)
    return (s0, s0 + MAX_WINDOW), (f"the cut crosses {hi - lo:.0f} um of layout; the window shows {MAX_WINDOW:g} um "
                                   f"around s = {centre:.1f} um: pass window=(s0, s1) for another part")


def _clip(cut: LayoutCut, s0: float, s1: float, names: dict[str, str] | None = None) -> LayoutCut:
    """The cut inside ``s0..s1``; ``names`` renames its layer keys (a process file names its own layers)."""

    band = IntervalSet.from_intervals([(s0, s1)])
    names = names or {}
    return LayoutCut(y_min=s0, y_max=s1, x=cut.x, window=cut.window, label=cut.label,
                     layer_intervals={names.get(key, key): value.intersection(band)
                                      for key, value in cut.layer_intervals.items()
                                      if not value.intersection(band).is_empty()})


def _process_file(stack: Any):
    """The process definition when ``stack`` is a process file (it has steps of its own), else None."""

    from optodraw.gds.xsection.schema import _load_mapping, load_process_definition

    path = Path(str(stack))
    if not (path.is_file() and path.suffix.lower() in (".yaml", ".yml", ".json")):
        return None
    if "process" not in _load_mapping(path):
        return None
    return load_process_definition(path)


def stack_section(stack: Any, layer: tuple[int, int], *, width: float = 0.5,
                  window: tuple[float, float] | None = None) -> CrossSection:
    """The cross-section of one waveguide ``width`` um wide on ``layer`` of ``stack``, for a chip figure with no GDS.
    Every film comes from the stack; the waveguide's width is the only value that does not."""

    import gdstk

    reach, half = max(10.0 * float(width), 6.0), max(6.0 * float(width), 3.0)
    library = gdstk.Library()
    library.new_cell("section").add(gdstk.rectangle((-reach, -width / 2.0), (reach, width / 2.0),
                                                    layer=int(layer[0]), datatype=int(layer[1])))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "section.gds"
        library.write_gds(path)
        return cross_section(path, stack, ((0.0, -reach), (0.0, reach)), window=window or (reach - half, reach + half))


def cross_section(gds: Any, stack: Any, cut: tuple[tuple[float, float], tuple[float, float]], *,
                  window: tuple[float, float] | None = None, z: tuple[float, float] | None = None,
                  cell_name: str | None = None, label: str = "cut") -> CrossSection:
    """The cross-section of ``gds`` (a path or a loaded ``GDSLayout``) along ``cut`` (two points), made by the
    process ``stack`` implies (a bundled stack name, a stack YAML, a loaded ``LayerStackSpec``, or a process
    YAML). ``z=(z0, z1)`` (um) draws only that band of the section; the regions stay whole."""

    from optodraw.gds.check import unknown_material
    from optodraw.gds.parsers import LayerStackSpec, load_layer_stack, stack_wafer
    from optodraw.gds.xsection.stack_process import _is_via, process_from_stack

    if z is not None:
        z = (float(z[0]), float(z[1]))
        if not z[0] < z[1]:
            raise ValueError(f"z=(z0, z1) needs z0 < z1, not {z}")
    if isinstance(gds, GDSLayout):
        layout = gds
    else:
        with warnings.catch_warnings():          # undeclared layers are findings here, not warnings
            warnings.simplefilter("ignore", UserWarning)
            layout = load_gds_layout(gds, cell_name=cell_name)
    full = cut_layout(layout, cut[0], cut[1], label=label)
    findings: list[str] = []
    if window is None:
        window, note = _auto_window(full)
        if note:
            findings.append(note)
    s0, s1 = float(window[0]), float(window[1])
    roles: dict[str, str] = {}
    names: dict[str, str] = {}
    numbers: dict[str, str] = {}                 # a layer's region -> its "layer/datatype"
    process = None if isinstance(stack, LayerStackSpec) else _process_file(stack)
    spec = None
    if process is not None:                      # expert mode: the file's steps read its own layer names
        windowed = _clip(full, s0, s1, {layer_key(item.gds): name for name, item in process.layout_layers.items()})
    else:
        windowed = _clip(full, s0, s1)
        spec = stack if isinstance(stack, LayerStackSpec) else load_layer_stack(stack)
        process = process_from_stack(spec, drawn=set(windowed.layer_intervals))
        known = {layer_key(s): s for s in spec.styles}
        for key in sorted(windowed.layer_intervals):
            if key not in known:
                findings.append(f"layer {key[1:].replace('_', '/')} is drawn on the cut but the stack has no entry")
        for key, s in known.items():
            style = spec.styles[s]
            names[key] = str(style.get("name") or key)
            numbers[names[key]] = f"{s[0]}/{s[1]}"
            if style.get("role"):
                roles[names[key]] = str(style["role"]).lower()
            if _is_via(style):
                roles.setdefault(names[key], "via")
        if isinstance(gds, GDSLayout) or isinstance(stack, LayerStackSpec):
            findings += list(spec.warnings)
        else:                                    # the whole-file checks; they name the stack warnings too
            from optodraw.gds.check import check_stack

            findings += check_stack(gds, stack, cell_name=cell_name)
    if not windowed.layer_intervals:
        findings.append("the cut crosses no drawn layer: only the substrate and the cladding show")
    result = XSectionEngine(process).run(windowed)
    # GEOS gives the last bits and the vertex order differently on x86 and ARM: snap and normalize, so a section
    # is the same SVG on every machine
    regions = {name: shapely.normalize(repair(shapely.set_precision(geometry, 1e-9)))
               for name, geometry in result.internal_regions.items()}
    own = spec.materials if spec is not None else {}
    films = stack_wafer(spec).films if spec is not None else ()
    box_name = films[0].name if films and films[0].role != "core" else "BOX"     # the film on the substrate
    labels, fills = {}, {}
    for name, material in result.materials.items():
        word = material_label(material, own) or material
        bands = {"handle": f"{word} substrate", "device": word, "oxide": word, "box": box_name}
        labels[name] = bands.get(name) or _FIXED.get(name) or name
        fills[name] = material_fill(material, own)
        named = any(found.startswith(f"material {material!r} ") for found in findings)    # by check_stack
        if spec is not None and not is_known(material, own) and not named:
            where = f"layer {numbers[name]}, region {name}" if name in numbers else f"region {name}"
            findings.append(unknown_material(material, where))
    expected = {names[key] for key in windowed.layer_intervals if key in names and names[key] in regions}
    species = [step.implant["species"] for step in process.process
               if step.implant is not None and step.mask in windowed.layer_intervals]
    doping = {name: MultiPolygon([]) for name in species} | dict(result.doping)
    source = {"layout": layout, "cut": ((float(cut[0][0]), float(cut[0][1])), (float(cut[1][0]), float(cut[1][1]))),
              "stack": spec, "process": process, "label": label}
    return CrossSection(regions=regions, materials=dict(result.materials), labels=labels, doping=doping,
                        steps=list(result.steps), window=(s0, s1), findings=findings, expected=expected, roles=roles,
                        source=source, fills=fills, z_window=z)
