"""Parsers for GDS-related technology and layer config files."""

from __future__ import annotations

from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any
import xml.etree.ElementTree as ET

from optodraw.gds.palette import canonical, is_metal, material_fill
from optodraw.gds.styles import (
    GDS_LAYER_PALETTE,
    LayerSpec,
    _format_layer_description,
    _normalize_layer_key,
    _rgb_fraction_to_hex,
    coerce_scalar,
    material_preset_from_layer_name,
    material_preset_from_name,
)

if TYPE_CHECKING:
    from optodraw.components.onchip.layer_stack import StackCore


def _gds3d_style_from_block(
    block_name: str,
    block_values: dict[str, str],
    *,
    unit_scale: float,
    material_aliases: dict[str, str] | None,
) -> tuple[LayerSpec, dict[str, Any]] | None:
    datatype_value = block_values.get("Datatype")
    spec = _normalize_layer_key((
        block_values.get("Layer"),
        0 if datatype_value in (None, "") else datatype_value,
    ))
    if spec is None:
        return None

    height_value = coerce_scalar(block_values.get("Height"))
    thickness_value = coerce_scalar(block_values.get("Thickness"))
    red_value = coerce_scalar(block_values.get("Red"))
    green_value = coerce_scalar(block_values.get("Green"))
    if green_value is None:
        green_value = coerce_scalar(block_values.get("Greeen"))
    blue_value = coerce_scalar(block_values.get("Blue"))
    filter_value = coerce_scalar(block_values.get("Filter"))
    show_value = coerce_scalar(block_values.get("Show"))

    name = block_name or f"L{spec[0]}/{spec[1]}"
    material_name = block_values.get("Material") or None
    material_preset = material_preset_from_name(material_name, material_aliases)
    if material_preset is None:
        material_preset = material_preset_from_layer_name(name) or "silicon"

    if None not in (red_value, green_value, blue_value):
        assert red_value is not None and green_value is not None and blue_value is not None
        color = _rgb_fraction_to_hex(float(red_value), float(green_value), float(blue_value))
    else:
        color = GDS_LAYER_PALETTE[spec[0] % len(GDS_LAYER_PALETTE)]

    opacity = 0.78
    if filter_value is not None:
        opacity = max(0.0, min(1.0, 1.0 - float(filter_value)))

    zmin = float(height_value or 0.0) * unit_scale
    thickness = abs(float(thickness_value or 0.0)) * unit_scale
    visible = show_value is None or bool(int(show_value))

    style = {
        "name": name,
        "color": color,
        "opacity": opacity,
        "thickness": thickness,
        "zmin": zmin,
        "visible": visible,
        "style_source": "gds3d-techfile",
        "description": _format_layer_description(
            spec,
            name=name,
            material_name=material_name,
            material_preset=material_preset,
            thickness=thickness,
            zmin=zmin,
            source_label="GDS3D TECHFILE",
        ),
        "material_preset": material_preset,
    }
    if material_name is not None:
        style["material"] = material_name
    return spec, style


def parse_gds3d_techfile(
    techfile_path: str | PathLike[str],
    *,
    unit_scale: float = 1e-3,
    include_hidden: bool = False,
    material_aliases: dict[str, str] | None = None,
) -> dict[LayerSpec, dict[str, Any]]:
    path = Path(techfile_path)
    styles: dict[LayerSpec, dict[str, Any]] = {}
    current_name: str | None = None
    current_values: dict[str, str] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if line.startswith("LayerStart:"):
            current_name = line.split(":", 1)[1].strip()
            current_values = {}
            continue

        if line == "LayerEnd":
            if current_name is not None:
                parsed = _gds3d_style_from_block(
                    current_name,
                    current_values,
                    unit_scale=unit_scale,
                    material_aliases=material_aliases,
                )
                if parsed is not None:
                    spec, style = parsed
                    if include_hidden or style.get("visible", True):
                        styles[spec] = style
            current_name = None
            current_values = {}
            continue

        if current_name is None or ":" not in line:
            continue

        key, value = line.split(":", 1)
        current_values[key.strip()] = value.strip()

    return styles


def _xml_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _xml_child_text(element: ET.Element, name: str) -> str | None:
    for child in list(element):
        if _xml_tag(child) == name:
            text = child.text
            return text.strip() if isinstance(text, str) else None
    return None


def _iter_klayout_property_nodes(element: ET.Element):
    if _xml_tag(element) == "properties":
        yield element
    for child in list(element):
        yield from _iter_klayout_property_nodes(child)


def _parse_bool_text(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


def _normalize_hex_color(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text.lower() in {"none", "nil", "transparent"}:
        return None
    if not text.startswith("#"):
        text = f"#{text}"
    if len(text) == 4:
        return "#" + "".join(char * 2 for char in text[1:]).lower()
    if len(text) == 7:
        return text.lower()
    return None


def _parse_klayout_source(source: str | None) -> LayerSpec | None:
    if source is None:
        return None
    text = source.strip()
    if not text:
        return None
    text = text.split("@", 1)[0].split()[0]
    if "*" in text:
        return None
    return _normalize_layer_key(text)


def _layerstack_length_scale(data: dict[str, Any]) -> float:
    """Convert a layer-stack file's length unit to micrometres."""

    unit = str(data.get("units", "um")).strip().lower()
    scales = {
        "nm": 1e-3,
        "nanometer": 1e-3,
        "nanometers": 1e-3,
        "um": 1.0,
        "µm": 1.0,
        "micron": 1.0,
        "microns": 1.0,
        "micrometer": 1.0,
        "micrometers": 1.0,
        "mm": 1e3,
        "millimeter": 1e3,
        "millimeters": 1e3,
        "m": 1e6,
        "meter": 1e6,
        "meters": 1e6,
    }
    if unit not in scales:
        raise ValueError(f"Unsupported layer-stack length unit: {unit!r}")
    return scales[unit]


def parse_layerstack_yaml(
    path: str | PathLike[str],
) -> dict[LayerSpec, dict[str, Any]]:
    """Parse a simple layer-stack YAML/JSON into per-layer styles (z + thickness).

    This is the foundry-agnostic, human-fillable format: one entry per GDS layer,
    keyed by ``"layer/datatype"``. It carries everything the 3D view needs — z and
    thickness make the extrusion physical; color/material drive appearance::

        name: My SOI process
        units: um            # optional (default microns)
        layers:
          "1/0": {name: Si core, zmin: 0.0, thickness: 0.22, material: silicon, color: "#c0392b"}
          "41/0": {name: Metal 1, zmin: 1.5, thickness: 0.5, material: aluminum}

    Returns ``{LayerSpec: {name, color, thickness, zmin, material_preset, opacity}}``
    ready to merge into a GDSModel ``layer_stack``."""

    data = _load_yaml_file(Path(path))
    if not isinstance(data, dict):
        return {}
    length_scale = _layerstack_length_scale(data)
    layers = data.get("layers", data)
    if not isinstance(layers, dict):
        return {}
    out: dict[LayerSpec, dict[str, Any]] = {}
    for key, props in layers.items():
        spec = _parse_klayout_source(str(key))
        if spec is None or not isinstance(props, dict):
            continue
        style: dict[str, Any] = {}
        if props.get("name") is not None:
            style["name"] = str(props["name"])
        color = _normalize_hex_color(props.get("color") or props.get("fill"))
        if color:
            style["color"] = color
        thickness = coerce_scalar(props.get("thickness"))
        if thickness is not None:
            style["thickness"] = float(thickness) * length_scale
        z = props.get("zmin", props.get("z_offset", props.get("z")))
        z = coerce_scalar(z)
        if z is not None:
            style["zmin"] = float(z) * length_scale
        material = props.get("material", props.get("material_preset"))
        if material:
            style["material_preset"] = str(material)
        opacity = coerce_scalar(props.get("opacity"))
        if opacity is not None:
            style["opacity"] = opacity
        if props.get("visible") is False:
            style["visible"] = False
        for field_name in ("role", "from", "to", "provenance", "source"):
            if props.get(field_name) is not None:
                style[field_name] = str(props[field_name])
        sidewall = coerce_scalar(props.get("sidewall_deg"))
        if sidewall is not None:
            style["sidewall_deg"] = float(sidewall)
        if props.get("polarity") is not None:
            style["polarity"] = str(props["polarity"])
        out[spec] = style
    return out


def parse_layerstack_oxide(path: str | PathLike[str]) -> dict[str, float] | None:
    """Parse the optional top-level ``oxide`` block of a layer-stack YAML into the
    GDSModel process-context fields, so the device is embedded in full-height oxide and
    etch layers (deep trench / oxide-open / m_open) carve the real TOX + BOX depth rather
    than being estimated from the tallest drawn layer.

    Returns ``{box_depth, cladding_top, handle_thickness}`` (µm) or ``None``::

        oxide:
          box:    {thickness: 4.5}     # buried oxide depth below z=0
          tox:    {thickness: 4.5}     # top cladding; cladding_top = zmin + thickness
          handle: {thickness: 2.0}     # substrate slab below the BOX (cosmetic)
    """
    data = _load_yaml_file(Path(path))
    if not isinstance(data, dict):
        return None
    length_scale = _layerstack_length_scale(data)
    ox = data.get("oxide")
    if not isinstance(ox, dict):
        return None
    out: dict[str, float] = {}
    box = ox.get("box")
    if isinstance(box, dict):
        t = coerce_scalar(box.get("thickness"))
        if t is not None:
            out["box_depth"] = abs(float(t)) * length_scale
    tox = ox.get("tox")
    if isinstance(tox, dict):
        t = coerce_scalar(tox.get("thickness"))
        z = coerce_scalar(tox.get("zmin", tox.get("z_offset", tox.get("z")))) or 0.0
        if t is not None:
            out["cladding_top"] = (float(z) + abs(float(t))) * length_scale
    handle = ox.get("handle")
    if isinstance(handle, dict):
        t = coerce_scalar(handle.get("thickness"))
        if t is not None:
            out["handle_thickness"] = min(abs(float(t)) * length_scale, 6.0)  # cap: render slab, not a 525 µm wafer
    if isinstance(tox, dict) and tox.get("planarized") is True:
        out["tox_planarized"] = 1.0
    passivation = ox.get("passivation")
    if isinstance(passivation, dict):
        t = coerce_scalar(passivation.get("thickness"))
        if t is not None:
            out["passivation"] = abs(float(t)) * length_scale
    return out or None


_HANDLE_CAP = 6.0                 # um: the substrate is drawn as a slab, not a 525 um wafer
_WAFER_BLOCKS = ("substrate", "films", "fill")


@dataclass(frozen=True)
class Film:
    """A blanket film of the wafer, before any mask. ``zmin`` and ``thickness`` in um."""

    name: str              # the label in a section; the region key, except the substrate (handle) and the box
    material: str          # a key of the material table
    zmin: float
    thickness: float
    role: str = ""         # "core": the blanket core film the etches pattern
    source: str = ""


@dataclass(frozen=True)
class Fill:
    """What fills the etched space up to the cladding surface ``top`` (um)."""

    material: str = "sio2"
    top: float = 0.0
    planarized: bool = False
    source: str = ""


@dataclass(frozen=True)
class Wafer:
    """The substrate, the films bottom up (each on the one before), and the fill."""

    substrate: Film
    films: tuple[Film, ...]
    fill: Fill


@dataclass
class LayerStackSpec:
    """The SINGLE source of truth for a foundry z-stack.

    Every consumer (GDS 3D extrusion, cross-section, GLB export, on-chip
    component heights) reads this one object, so BOX/TOX growth and etch depths
    are uniform across foundries. ``oxide`` is ALWAYS resolved — explicitly from
    the YAML's ``oxide:`` block, else DERIVED from the stack's own layers (etch
    layers end at the oxide surface; trench bottoms mark the depth), else safe
    defaults — a stack can never silently produce "no growth".
    """

    name: str = ""
    styles: dict[LayerSpec, dict[str, Any]] = field(default_factory=dict)
    # box_depth, cladding_top, handle_thickness, passivation (um) and passivation_material: the process-context
    # keywords of a GDSModel, so GDSModel(**stack.oxide) draws the cover the cross-section draws
    oxide: dict[str, Any] = field(default_factory=dict)
    oxide_source: str = "default"  # "explicit" | "derived" | "default"
    passivation_material: str = ""  # the YAML's oxide.passivation.material; empty: the process default
    warnings: list[str] = field(default_factory=list)
    wafer: Wafer | None = None      # None: stack_wafer() maps the oxide envelope
    materials: dict[str, dict[str, str]] = field(default_factory=dict)   # table key -> its own fill and label
    waveguide_width: float | None = None   # um, the YAML's waveguide.width: sets the draw scale of on-chip parts

    def component_heights(self) -> dict[str, float]:
        """Map the stack's REAL layers onto the on-chip component z-keys, so
        schematic components (MZIs, rings, heaters) extrude at the same heights
        as an imported GDS under the same stack — one z-truth for the whole chip.

        Returns only the keys the stack can actually answer:
        chip_thickness (tallest guiding layer at z~0), via_z/via_height (lowest
        copper/tungsten), metal_z/metal_height (lowest routing/heater metal),
        pad_z/pad_height (topmost metal)."""

        vias = {"copper", "tungsten"}
        guiding = []
        silicon = []
        via_layers = []
        metal_layers = []
        for style in self.styles.values():
            if style.get("visible") is False:
                continue
            thickness = style.get("thickness")
            if thickness is None:
                continue
            z0 = float(style.get("zmin") or 0.0)
            material = str(style.get("material_preset", "")).lower()
            if material in ("silicon", "silicon_nitride") and abs(z0) < 0.05:
                guiding.append(float(thickness))
                if material == "silicon":
                    silicon.append((z0, float(thickness)))
            elif material in vias:
                via_layers.append((z0, float(thickness)))
            elif is_metal(material):
                metal_layers.append((z0, float(thickness)))
        out: dict[str, float] = {}
        if silicon:
            # A legacy mixed profile must not turn a silicon core into the thicker SiN film.
            out["chip_thickness"] = max(t for _, t in silicon)
            z, t = min(silicon, key=lambda layer: layer[1])
            if t < out["chip_thickness"]:
                out.update(rib_z=z, rib_height=t, implant_z=z, implant_height=t)
        elif guiding:
            out["chip_thickness"] = max(guiding)
        if via_layers:
            z, t = min(via_layers)
            out["via_z"], out["via_height"] = z, t
        if metal_layers:
            metal_layers.sort()
            z, t = metal_layers[0]
            out["metal_z"], out["metal_height"] = z, t
            z, t = metal_layers[-1]
            out["pad_z"], out["pad_height"] = z, t
        # Explicit roles override material-based inference in older stack files.
        named = {str(style.get("name")): style for style in self.styles.values() if style.get("name")}
        roles = {"core": "core", "slab": "rib", "implant": "implant", "contact": "contact",
                 "via": "via", "metal": "metal", "heater": "heater", "pad": "pad"}
        resolved: dict[str, tuple[float, float]] = {}
        for name, style in named.items():
            role = roles.get(style.get("role"))
            if role is None or style.get("visible") is False:
                continue
            z, t = _layer_interval(named, name, resolved)
            out[role + "_z"], out[role + "_height"] = z, t
            if role == "core":
                out["chip_thickness"] = t
        film = self._core_film()
        if film is not None and "chip_thickness" not in out:      # a film stack (InP): the core is a wafer film
            out.update(core_z=film.zmin, core_height=film.thickness, chip_thickness=film.thickness)
        if "rib_height" in out:
            out.setdefault("implant_z", out["rib_z"])
            out.setdefault("implant_height", out["rib_height"])
        return out

    def _core_film(self) -> Film | None:
        return next((film for film in stack_wafer(self).films if film.role == "core"), None)

    def component_core(self) -> StackCore:
        """What the stack makes an on-chip part's core of: the material of the core layer (role core, else the
        silicon or the nitride at z = 0, else the core film), of the slab under it (role slab, else the core's),
        their fills from the material table, and, in a film stack, the films over the core film that the core etch
        patterns with it; the stack's waveguide width; and the cladding over the parts, from the top of the films
        under the core to the top of the fill. The heights are in :meth:`component_heights`."""

        from optodraw.components.onchip.layer_stack import StackCore

        placed = [s for s in self.styles.values() if s.get("visible") is not False and s.get("thickness") is not None]

        def material(role: str) -> str | None:
            found = next((s for s in placed if str(s.get("role") or "").lower() == role), None)
            return canonical(found.get("material_preset") or "silicon") if found else None

        at_zero = {canonical(s.get("material_preset") or "") for s in placed if abs(float(s.get("zmin") or 0.0)) < 0.05}
        film = self._core_film()
        over: list[tuple[float, float, str]] = []
        if film is not None:
            films = stack_wafer(self).films
            for above in films[films.index(film) + 1:]:
                key = canonical(above.material)
                if over and over[-1][2] == key:                  # two films of one material: one band, no seam
                    over[-1] = (over[-1][0], over[-1][1] + above.thickness, key)
                else:
                    over.append((above.zmin, above.thickness, key))
        core = (material("core") or ("silicon" if "silicon" in at_zero else None)
                or ("silicon_nitride" if "silicon_nitride" in at_zero else None)
                or (canonical(film.material) if film is not None else "silicon"))
        slab = material("slab") or core
        wafer = stack_wafer(self)
        bottom = film.zmin if film is not None else max((f.zmin + f.thickness for f in wafer.films), default=0.0)
        fill = canonical(wafer.fill.material)
        cladding = (bottom, wafer.fill.top, fill) if wafer.fill.top > bottom + 1e-9 else None
        keys = {core, slab, fill, *(key for _, _, key in over)}
        return StackCore(core=core, slab=slab, over=tuple(over),
                         fills={key: material_fill(key, self.materials) for key in keys},
                         width=self.waveguide_width, cladding=cladding)


def _layer_interval(named: dict[str, dict[str, Any]], name: str, resolved: dict[str, tuple[float, float]],
                    trail: tuple[str, ...] = ()) -> tuple[float, float]:
    """``(zmin, thickness)`` of a named layer. A layer given by ``from``/``to`` endpoints (a via between two
    named layers) spans from the top of the first to the bottom of the second."""

    if name in resolved:
        return resolved[name]
    if name in trail:
        raise ValueError(f"Cyclic layer endpoints: {name}")
    if name not in named:
        raise ValueError(f"Unknown layer endpoint: {name}")
    style = named[name]
    if style.get("from") or style.get("to"):
        if not style.get("from") or not style.get("to"):
            raise ValueError(f"Layer {name} needs both from and to endpoints")
        lower = _layer_interval(named, style["from"], resolved, (*trail, name))
        upper = _layer_interval(named, style["to"], resolved, (*trail, name))
        z, t = lower[0] + lower[1], upper[0] - lower[0] - lower[1]
        if t < 0:
            raise ValueError(f"Layer {name} has reversed or overlapping endpoints")
    else:
        z, t = float(style.get("zmin", 0.0)), float(style["thickness"])
    resolved[name] = (z, t)
    return z, t


def _resolve_endpoint_layers(styles: dict[LayerSpec, dict[str, Any]]) -> None:
    """Give each layer defined by ``from``/``to`` endpoints its zmin and thickness, in place."""

    named = {str(style.get("name")): style for style in styles.values() if style.get("name")}
    resolved: dict[str, tuple[float, float]] = {}
    for style in styles.values():
        if (style.get("from") or style.get("to")) and style.get("thickness") is None:
            style["zmin"], style["thickness"] = _layer_interval(named, str(style.get("name")), resolved)


def _derive_oxide(styles: dict[LayerSpec, dict[str, Any]]) -> tuple[dict[str, float], str, list[str]]:
    """Derive the oxide envelope from the layers themselves.

    Physics of the convention: etch layers (``material: air``) are drawn from
    their floor UP TO the oxide surface, so the tallest etch top IS the cladding
    surface; a trench dipping below z=0 marks how deep the buried oxide extends.
    Metals are excluded from the fallback surface — bond pads poke through the
    passivation in real processes."""

    warnings: list[str] = []
    air_tops: list[float] = []
    air_bottoms: list[float] = []
    guide_tops: list[float] = []
    any_tops: list[float] = []
    for style in styles.values():
        if style.get("visible") is False:
            continue
        thickness = style.get("thickness")
        zmin = style.get("zmin")
        if thickness is None:
            continue
        z0 = float(zmin) if zmin is not None else 0.0
        top = z0 + float(thickness)
        any_tops.append(top)
        material = str(style.get("material_preset", "")).lower()
        if material == "air":
            air_tops.append(top)
            air_bottoms.append(z0)
        elif not is_metal(material):
            guide_tops.append(top)

    oxide: dict[str, float] = {}
    source = "derived"
    if air_tops and max(air_tops) > 0:
        oxide["cladding_top"] = round(max(air_tops), 4)
    elif guide_tops:
        oxide["cladding_top"] = round(max(guide_tops) + 0.3, 4)
        warnings.append(
            "oxide.cladding_top derived from the tallest guiding layer (+0.3) — "
            "add an explicit `oxide:` block for the true TOX surface"
        )
    elif any_tops:
        oxide["cladding_top"] = round(max(any_tops), 4)
        warnings.append("oxide.cladding_top derived from the tallest layer")
    else:
        oxide["cladding_top"] = 1.0
        source = "default"
        warnings.append("stack has no z/thickness data — default oxide envelope used")

    below = [b for b in air_bottoms if b < 0]
    if below:
        oxide["box_depth"] = round(-min(below), 4)
    else:
        oxide["box_depth"] = 2.0
        warnings.append("oxide.box_depth defaulted to 2.0 um (no etch reaches below z=0)")

    oxide["handle_thickness"] = 2.0
    return oxide, source, warnings


def stack_wafer(spec: LayerStackSpec) -> Wafer:
    """The wafer under the layers: the stack's own, or the one its oxide envelope gives (a stack built by hand)."""

    return spec.wafer if spec.wafer is not None else _oxide_wafer(spec.oxide)


def _oxide_wafer(oxide: dict[str, Any], materials: dict[str, str] | None = None) -> Wafer:
    """The old oxide envelope as a wafer: the handle is the substrate, the box one film that ends at z = 0, the top
    oxide the fill. A box 0 thick stays a film. ``materials`` holds the oxide block's handle, box and tox materials."""

    materials = materials or {}
    handle = float(oxide.get("handle_thickness", 2.0))
    box = float(oxide.get("box_depth", 2.0))
    return Wafer(substrate=Film("substrate", materials.get("handle", "silicon"), -box - handle, handle),
                 films=(Film("BOX", materials.get("box", "sio2"), -box, box),),
                 fill=Fill(materials.get("tox", "sio2"), float(oxide.get("cladding_top", 0.0)),
                           bool(oxide.get("tox_planarized"))))


def _oxide_materials(data: dict[str, Any]) -> dict[str, str]:
    """The materials an ``oxide:`` block names for its handle, box and tox."""

    ox = data.get("oxide")
    if not isinstance(ox, dict):
        return {}
    return {part: str(ox[part]["material"]) for part in ("handle", "box", "tox")
            if isinstance(ox.get(part), dict) and ox[part].get("material")}


def _block(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{key}: must be a mapping, not {value!r}")
    return value


def _core_layers_top(styles: dict[LayerSpec, dict[str, Any]]) -> float | None:
    """The top of the core layers: those with role core, else the silicon or nitride layers at z = 0."""

    placed = [s for s in styles.values() if s.get("visible") is not False
              and s.get("thickness") is not None and s.get("zmin") is not None]
    core = [s for s in placed if str(s.get("role") or "").lower() == "core"] or [
        s for s in placed if abs(float(s["zmin"])) < 1e-6
        and canonical(s.get("material_preset") or "silicon") in ("silicon", "silicon_nitride")]
    return max((float(s["zmin"]) + float(s["thickness"]) for s in core), default=None)


def _blocks_wafer(data: dict[str, Any], styles: dict[LayerSpec, dict[str, Any]], scale: float,
                  derived_top: float) -> tuple[Wafer, bool]:
    """The wafer of the ``substrate``, ``films`` and ``fill`` blocks, and whether the fill gives its top.

    The film with role core lies at z = 0 to its thickness, the films before it under it, the films after it over
    it. With no core film every film lies under the core, so the last one ends at z = 0. The substrate lies under
    the lowest film. ``top: flush`` is the top of the highest film, or of the core layers when no film is the
    core. With no top, the fill reaches ``derived_top``."""

    entries = data.get("films") or []
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("films: must be a list of mappings, bottom up")
    thicknesses = []
    for index, entry in enumerate(entries):
        thickness = coerce_scalar(entry.get("thickness"))
        if thickness is None or not entry.get("material"):
            raise ValueError(f"film {entry.get('name') or index + 1!r} needs a material and a thickness")
        thicknesses.append(abs(float(thickness)) * scale)
    roles = [str(entry.get("role") or "").lower() for entry in entries]
    core = roles.index("core") if "core" in roles else len(entries)
    z = bottom = 0.0 - sum(thicknesses[:core])
    films = []
    for index, (entry, thickness, role) in enumerate(zip(entries, thicknesses, roles)):
        films.append(Film(str(entry.get("name") or f"film {index + 1}"), str(entry["material"]), z, thickness,
                          role, str(entry.get("source") or "")))
        z += thickness

    substrate = _block(data, "substrate")
    depth = coerce_scalar(substrate.get("thickness"))
    depth = min(abs(float(depth)) * scale if depth is not None else 2.0, _HANDLE_CAP)
    fill = _block(data, "fill")
    given = fill.get("top")
    if isinstance(given, str) and given.strip().lower() == "flush":
        top = films[-1].zmin + films[-1].thickness if core < len(films) else _core_layers_top(styles)
        if top is None:
            raise ValueError("fill: top: flush needs a core: a film or layers with role: core")
    elif given is not None:
        top = coerce_scalar(given)
        if top is None:
            raise ValueError(f"fill: top must be a number in the stack's units or flush, not {given!r}")
        top = float(top) * scale
    else:
        top = derived_top
    wafer = Wafer(substrate=Film("substrate", str(substrate.get("material") or "silicon"), bottom - depth, depth,
                                 source=str(substrate.get("source") or "")),
                  films=tuple(films),
                  fill=Fill(str(fill.get("material") or "sio2"), top, fill.get("planarized") is True,
                            str(fill.get("source") or "")))
    return wafer, given is not None


def _stack_materials(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    """The ``materials:`` block: a fill colour and a label of the stack's own, keyed by table key."""

    out: dict[str, dict[str, str]] = {}
    for key, entry in _block(data, "materials").items():
        entry = entry if isinstance(entry, dict) else {}
        own: dict[str, str] = {}
        if entry.get("fill") is not None:
            fill = _normalize_hex_color(str(entry["fill"]))
            if fill is None:
                raise ValueError(f"materials: {key}: fill {entry['fill']!r} is not a colour such as '#f2e3bd'")
            own["fill"] = fill
        if entry.get("label"):
            own["label"] = str(entry["label"])
        out[canonical(key)] = own
    return out


BUNDLED_STACKS = Path(__file__).resolve().parent / "stacks"


def bundled_stack_names() -> list[str]:
    """The layer stacks of open PDKs that ship with optodraw, by name."""

    return sorted(p.stem for p in BUNDLED_STACKS.glob("*.yaml") if not p.stem.startswith("_"))


def load_layer_stack(path: str | PathLike[str]) -> LayerStackSpec:
    """Load a layer-stack YAML, or a bundled stack by name, into the unified :class:`LayerStackSpec`.

    This is THE entry point for stack consumers. ``oxide`` is always populated:
    explicit ``oxide:`` block first; missing keys filled by derivation from the
    layers; final fallback to safe defaults. ``warnings`` records every guess so
    callers can surface stack-quality issues instead of silently diverging.

    A stack states its wafer with the old ``oxide:`` block or with ``substrate``, ``films`` and ``fill`` blocks, not
    both. ``wafer`` holds it in either form; ``materials`` holds the stack's own fills and labels."""

    stack_path = Path(path)
    if stack_path.suffix.lower() in (".lyt", ".lyd25") and stack_path.is_file():
        from optodraw.gds.klayout_tech import load_klayout_technology   # a KLayout technology, or its d25 script

        return load_klayout_technology(stack_path)
    if not stack_path.is_file():
        bundled = BUNDLED_STACKS / f"{path}.yaml"
        if not bundled.is_file():
            raise FileNotFoundError(f"no layer stack {str(path)!r}: not a file, and not one of "
                                    f"{', '.join(bundled_stack_names())}")
        stack_path = bundled
    styles = parse_layerstack_yaml(stack_path)
    _resolve_endpoint_layers(styles)                     # a via between two named layers gets its own heights
    data = _load_yaml_file(stack_path)
    data = data if isinstance(data, dict) else {}
    name = str(data.get("name", stack_path.stem))
    blocks = [key for key in _WAFER_BLOCKS if key in data]
    if "oxide" in data and blocks:
        raise ValueError(f"{stack_path.name} has oxide: and {', '.join(blocks)}: a stack uses the oxide: block or "
                         f"the {', '.join(_WAFER_BLOCKS)} blocks, not both")

    derived, derived_source, warnings = _derive_oxide(styles)
    if blocks:
        wafer, top_given = _blocks_wafer(data, styles, _layerstack_length_scale(data), derived["cladding_top"])
        oxide = {"box_depth": abs(wafer.films[0].zmin) if wafer.films else 0.0,    # the films under the core
                 "cladding_top": wafer.fill.top, "handle_thickness": wafer.substrate.thickness}
        if wafer.fill.planarized:
            oxide["tox_planarized"] = 1.0
        source = "explicit" if top_given else "explicit+derived"
        warnings = [] if top_given else [w for w in warnings if "box_depth" not in w]
    else:
        explicit = parse_layerstack_oxide(stack_path) or {}
        oxide = dict(derived)
        oxide.update(explicit)  # explicit values are authoritative, key by key
        if set(explicit) >= {"box_depth", "cladding_top"}:
            source = "explicit"
            warnings = []  # fully specified: no guessing happened for the envelope
        elif explicit:
            source = "explicit+derived"
        else:
            source = derived_source
        wafer = _oxide_wafer(oxide, _oxide_materials(data))

    spec = LayerStackSpec(name=name, styles=styles, oxide=oxide, oxide_source=source, warnings=warnings,
                          wafer=wafer, materials=_stack_materials(data))
    guide = _block(data, "waveguide").get("width")
    if guide is not None:
        spec.waveguide_width = float(guide) * _layerstack_length_scale(data)
    passivation = (data.get("oxide") or {}).get("passivation")
    if isinstance(passivation, dict) and passivation.get("material"):
        spec.passivation_material = str(passivation["material"])
        spec.oxide["passivation_material"] = spec.passivation_material
    if not styles:
        spec.warnings.append("stack defined no layers")
    for layer, style in styles.items():
        if style.get("visible") is False:
            continue
        if style.get("thickness") is None:
            spec.warnings.append(f"layer {layer} has no thickness (renders flat)")
        elif float(style["thickness"]) < 0:
            spec.warnings.append(f"layer {layer} has negative thickness")
    return spec


def parse_xsection_thickness(
    xs_path: str | PathLike[str],
) -> dict[LayerSpec, dict[str, Any]]:
    """Best-effort per-layer thickness from a KLayout XSection ``.xs`` script.

    ``.xs`` is a Ruby program, so this is a heuristic over the documented idiom:
    layer handles ``v = layer("L/D")`` plus ``mask(v).grow(t)`` / ``deposit`` /
    ``etch`` calls (thickness = first numeric arg). Returns
    ``{LayerSpec: {"thickness", "name"}}`` for what it could resolve — empty when
    the script is too custom (enter thickness per layer in the editor instead)."""

    import re

    text = Path(xs_path).read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"#.*", "", text)  # strip comments

    var_to_spec: dict[str, LayerSpec] = {}
    for name, layer, datatype in re.findall(
        r"(\w+)\s*=\s*layer\s*\(\s*[\"']?(\d+)\s*/\s*(\d+)", text
    ):
        var_to_spec[name] = (int(layer), int(datatype))

    out: dict[LayerSpec, dict[str, Any]] = {}
    # mask(var).grow(t) / .deposit(t) / .etch(t) — thickness is the first number.
    for var, thickness in re.findall(
        r"mask\(\s*(\w+)\s*\)[^\n]*?\.(?:grow|deposit|etch)\s*\(\s*([\d.]+)", text
    ):
        spec = var_to_spec.get(var)
        if spec is None or spec in out:
            continue
        try:
            out[spec] = {"thickness": float(thickness), "name": var}
        except ValueError:
            continue
    return out


def parse_klayout_lyp(
    lyp_path: str | PathLike[str],
    *,
    include_hidden: bool = False,
    default_opacity: float = 0.78,
    transparent_opacity: float = 0.42,
    fallback_material_preset: str = "silicon",
    material_aliases: dict[str, str] | None = None,
) -> dict[LayerSpec, dict[str, Any]]:
    """Parse a KLayout ``.lyp`` layer-properties file into layer styles.

    KLayout ``.lyp`` files usually describe visual layer names, source layer
    specs, colors, and visibility, while physical z offsets and thicknesses
    live elsewhere. This parser captures that visual/naming contract so it can
    be combined with overrides, a GDS3D techfile, or a future process stack.
    """
    path = Path(lyp_path).expanduser()
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    styles: dict[LayerSpec, dict[str, Any]] = {}

    for properties in _iter_klayout_property_nodes(root):
        spec = _parse_klayout_source(_xml_child_text(properties, "source"))
        if spec is None:
            continue

        valid = _parse_bool_text(_xml_child_text(properties, "valid"), default=True)
        visible = valid and _parse_bool_text(_xml_child_text(properties, "visible"), default=True)
        if not visible and not include_hidden:
            continue

        name = _xml_child_text(properties, "name") or f"L{spec[0]}/{spec[1]}"
        fill_color = _normalize_hex_color(_xml_child_text(properties, "fill-color"))
        frame_color = _normalize_hex_color(_xml_child_text(properties, "frame-color"))
        transparent = _parse_bool_text(_xml_child_text(properties, "transparent"), default=False)

        material_name = _xml_child_text(properties, "material")
        material_preset = material_preset_from_name(material_name, material_aliases)
        if material_preset is None:
            material_preset = material_preset_from_layer_name(name) or fallback_material_preset

        opacity = transparent_opacity if transparent else default_opacity
        style: dict[str, Any] = {
            "name": name,
            "color": fill_color or frame_color or GDS_LAYER_PALETTE[spec[0] % len(GDS_LAYER_PALETTE)],
            "opacity": max(0.0, min(1.0, float(opacity))),
            "visible": visible,
            "physical_stack_known": False,
            "material_preset": material_preset,
            "style_source": "klayout-lyp",
            "description": _format_layer_description(
                spec,
                name=name,
                material_name=material_name,
                material_preset=material_preset,
                thickness=None,
                zmin=None,
                source_label="KLAYOUT LYP",
            ),
        }
        if material_name:
            style["material"] = material_name
        if frame_color is not None:
            style["stroke"] = frame_color

        styles[spec] = style

    return styles


def _load_yaml_file(path: Path) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to read BlenderGDS YAML configs. "
            "Install with: pip install optodraw[gds] or pip install pyyaml"
        ) from exc

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _blendergds_rgba_to_style(color_value: Any) -> tuple[str | None, float | None]:
    if not isinstance(color_value, (list, tuple)) or len(color_value) < 3:
        return None, None

    red = coerce_scalar(color_value[0])
    green = coerce_scalar(color_value[1])
    blue = coerce_scalar(color_value[2])
    if red is None or green is None or blue is None:
        return None, None

    opacity = coerce_scalar(color_value[3]) if len(color_value) >= 4 else None
    return _rgb_fraction_to_hex(red, green, blue), opacity


def parse_blendergds_layer_config(
    layer_config_path: str | PathLike[str],
    *,
    color_config_path: str | PathLike[str] | None = None,
    include_filler: bool = False,
    z_scale: float = 1.0,
    default_opacity: float = 0.78,
    fallback_material_preset: str = "silicon",
    material_aliases: dict[str, str] | None = None,
) -> dict[LayerSpec, dict[str, Any]]:
    """Parse a BlenderGDS-style YAML stack into OptoDraw layer styles.

    BlenderGDS stores process stacks as a top-level mapping from layer names to
    ``index``, ``type``, ``z``, and ``height`` values. Its optional color schema
    stores visual material hints under ``layers.<LayerName>``. This helper reads
    those files and returns the same ``layer_styles`` mapping accepted by
    :func:`load_gds_layout` and :class:`optodraw.components.models.GDSModel`.

    The parser intentionally handles the data format, not BlenderGDS internals;
    users can point it at their own YAML files or at configs from an installed
    BlenderGDS checkout.
    """
    layer_path = Path(layer_config_path).expanduser()
    raw_layers = _load_yaml_file(layer_path)
    if not isinstance(raw_layers, dict):
        raise ValueError("BlenderGDS layer config must be a YAML mapping of layer names to entries.")

    color_layers: dict[str, Any] = {}
    if color_config_path is not None:
        raw_colors = _load_yaml_file(Path(color_config_path).expanduser())
        if isinstance(raw_colors, dict):
            nested_layers = raw_colors.get("layers")
            color_layers = nested_layers if isinstance(nested_layers, dict) else raw_colors

    styles: dict[LayerSpec, dict[str, Any]] = {}
    for layer_name, entry in raw_layers.items():
        if not isinstance(layer_name, str) or not isinstance(entry, dict):
            continue
        if entry.get("purpose") == "filler" and not include_filler:
            continue

        datatype = entry.get("type", entry.get("datatype", 0))
        spec = _normalize_layer_key((
            entry.get("index", entry.get("layer")),
            0 if datatype in (None, "") else datatype,
        ))
        if spec is None:
            continue

        thickness_value = coerce_scalar(entry.get("height", entry.get("thickness")))
        zmin_value = coerce_scalar(entry.get("z", entry.get("zmin", entry.get("z_offset"))))
        thickness = abs(float(thickness_value or 0.0)) * float(z_scale)
        zmin = float(zmin_value or 0.0) * float(z_scale)

        color_entry = color_layers.get(layer_name, {}) if isinstance(color_layers, dict) else {}
        if not isinstance(color_entry, dict):
            color_entry = {}
        color, color_opacity = _blendergds_rgba_to_style(color_entry.get("color"))

        material_name = entry.get("material") if isinstance(entry.get("material"), str) else None
        material_preset = material_preset_from_name(material_name, material_aliases)
        if material_preset is None:
            material_preset = material_preset_from_layer_name(layer_name) or fallback_material_preset

        opacity = color_opacity if color_opacity is not None else default_opacity
        style: dict[str, Any] = {
            "name": layer_name,
            "color": color or GDS_LAYER_PALETTE[spec[0] % len(GDS_LAYER_PALETTE)],
            "opacity": max(0.0, min(1.0, float(opacity))),
            "thickness": thickness,
            "zmin": zmin,
            "z_offset": zmin,
            "material_preset": material_preset,
            "visible": True,
            "style_source": "blendergds-yaml",
            "description": _format_layer_description(
                spec,
                name=layer_name,
                material_name=material_name,
                material_preset=material_preset,
                thickness=thickness,
                zmin=zmin,
                source_label="BLENDERGDS YAML",
            ),
        }
        if material_name is not None:
            style["material"] = material_name
        for key in ("metallic", "metalness", "roughness"):
            value = coerce_scalar(color_entry.get(key))
            if value is not None:
                style[key] = float(value)
        if "purpose" in entry:
            style["purpose"] = entry["purpose"]

        styles[spec] = style

    return styles
