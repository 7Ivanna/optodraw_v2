"""A process from a layer stack: the steps a foundry runs to make the bands the stack lists.

The stack gives each layer a z band and a material, and the wafer under them: a substrate, blanket films and the
fill of the etched space. The steps keep every band and add what a band alone hides: the etch that leaves a slab,
the implant through the core, growth on the core, the fill a via is etched through and the metal that fills it,
metal patterned on a flat fill, a conformal top cladding, and the cover over the top metal with the pad openings
etched through it.
"""

from __future__ import annotations

from typing import Any

from optodraw.gds.palette import canonical, doping_label, is_metal, material_label
from optodraw.gds.parsers import LayerStackSpec, Wafer, stack_wafer
from optodraw.gds.xsection.cut import layer_key
from optodraw.gds.xsection.schema import ProcessDefinition

_EPS = 1e-6
_CORES = ("silicon", "silicon_nitride")      # the old rule: a stack that names no core has one of these at z = 0
_WIRED = frozenset({"contact", "via", "metal", "heater", "pad"})


def _material(style: dict[str, Any]) -> str:
    return str(style.get("material_preset") or "silicon").lower()


def _role(style: dict[str, Any]) -> str:
    return str(style.get("role") or "").lower()


def _z0(style: dict[str, Any]) -> float:
    return float(style["zmin"])


def _top(style: dict[str, Any]) -> float:
    return float(style["zmin"]) + float(style["thickness"])


def _polarity(style: dict[str, Any]) -> str:
    if style.get("polarity"):
        return str(style["polarity"])
    name = str(style.get("name", "")).lower()
    return "etch" if "etch" in name or "trench" in name else "keep"


def _is_via(style: dict[str, Any]) -> bool:
    role = str(style.get("role") or "").lower()
    return role in ("contact", "via") or str(style.get("name", "")).upper().startswith("VIA")


def _nm(um: float) -> str:
    return f"{um * 1000:.0f} nm" if abs(um) < 1.0 else f"{um:g} µm"


def _core(layers: list, wafer: Wafer) -> tuple[str, float, float, list]:
    """The core: its material, its bottom and top (um), and the device layers, the layers of its material that
    start at its bottom or end at its top. A film with role: core is the core. Else the layers with role: core are
    the core, down to the bottom of a layer of their material that touches them (an LN slab under its ridge).
    Else the old rule: the thickest silicon or silicon nitride layer at z = 0, with its material's layers there."""

    film = next((film for film in wafer.films if film.role == "core"), None)
    named = [(spec, style) for spec, style in layers if _role(style) == "core"]
    if film is not None:
        material, bottom, top = film.material.lower(), 0.0, film.thickness
    elif named:
        kinds = sorted({_material(style) for _, style in named})
        if len(kinds) > 1:
            raise ValueError(f"the core layers are of {len(kinds)} materials ({', '.join(kinds)}): a core has one")
        material, top = kinds[0], max(_top(style) for _, style in named)
        low = min(_z0(style) for _, style in named)
        bottom = min(_z0(style) for _, style in layers
                     if _material(style) == material and _top(style) >= low - _EPS and _z0(style) <= top + _EPS)
    else:
        at_zero = [(spec, style) for spec, style in layers
                   if abs(_z0(style)) < _EPS and _material(style) in _CORES]
        if not at_zero:
            raise ValueError("the stack has no core layer at z = 0 (silicon or silicon nitride): give the core "
                             "layers role: core, or the core film role: core")
        material = _material(max(at_zero, key=lambda item: float(item[1]["thickness"]))[1])
        device = [(spec, style) for spec, style in at_zero if _material(style) == material]
        return material, 0.0, max(float(style["thickness"]) for _, style in device), device
    device = [(spec, style) for spec, style in layers
              if _material(style) == material and _z0(style) >= bottom - _EPS and _top(style) <= top + _EPS
              and (abs(_z0(style) - bottom) < _EPS or abs(_top(style) - top) < _EPS)]
    return material, bottom, top, device


def _wafer_bands(wafer: Wafer, core: str, bottom: float, top: float) -> list[dict[str, Any]]:
    """The wafer bands bottom up: the substrate as ``handle``, the films under the core (the one on the substrate as
    ``box``), the core as ``device``, then the films over it."""

    split = next((index for index, film in enumerate(wafer.films) if film.role == "core"), None)
    under = wafer.films if split is None else wafer.films[:split]
    over = () if split is None else wafer.films[split + 1:]
    bands = [{"name": "handle", "material": wafer.substrate.material, "z0": wafer.substrate.zmin,
              "z1": under[0].zmin if under else bottom}]
    bands += [{"name": "box" if index == 0 else film.name, "material": film.material, "z0": film.zmin,
               "z1": film.zmin + film.thickness} for index, film in enumerate(under)]
    bands.append({"name": "device", "material": core, "z0": bottom, "z1": top})
    bands += [{"name": film.name, "material": film.material, "z0": film.zmin, "z1": film.zmin + film.thickness}
              for film in over]
    return bands


def process_from_stack(stack: LayerStackSpec, drawn: set[str] | None = None) -> ProcessDefinition:
    """Ordered process steps that make ``stack``. ``drawn`` (layer keys on the cut) leaves out the patterned
    layers the cut does not cross, so the oxide does not rise for a metal that is not there."""

    layers = [(spec, style) for spec, style in stack.styles.items()
              if style.get("visible", True) is not False and style.get("thickness") and style.get("zmin") is not None]
    # a layer of air is an etch, never a film: it cuts what lies in its z band under its mask. One that ends inside
    # the device layer (a shelf etch) is etched before the oxide; one that reaches up into the oxide (an oxide
    # open, a trench, a metal open) is cut through the finished stack, down to its zmin
    etches = [(spec, style) for spec, style in layers if _material(style) == "air"]
    layers = [item for item in layers if item not in etches]
    wafer = stack_wafer(stack)
    core, bottom, top, device = _core(layers, wafer)
    thick = top - bottom
    sidewall = min((float(style.get("sidewall_deg", 90.0)) for _, style in device), default=90.0)
    bands = _wafer_bands(wafer, core, bottom, top)
    surface = max(band["z1"] for band in bands)          # the top of the wafer
    fill = wafer.fill.material
    word = "oxide" if canonical(fill) == "sio2" else (material_label(fill, stack.materials) or fill)
    on_cut = (lambda spec: True) if drawn is None else (lambda spec: layer_key(spec) in drawn)
    steps: list[dict[str, Any]] = []

    def level(style: dict[str, Any]) -> float:          # the height a keep layer holds over the core bottom
        return _top(style) - bottom

    # 1. the device layer: drawn means kept; each lower layer leaves its slab. Each etch takes all but the
    # higher layers down to the next level, so every wall stands at a drawn edge and no wedge is left
    keep = [(spec, style) for spec, style in device if _polarity(style) == "keep"]
    held = [layer_key(spec) for spec, style in keep if level(style) >= thick - _EPS]
    at = thick
    for spec, style in sorted((item for item in keep if level(item[1]) < thick - _EPS),
                              key=lambda item: -level(item[1])):
        if not on_cut(spec):
            continue                                     # a slab the cut does not cross: no step to show
        t = level(style)
        steps.append({"id": f"etch_{layer_key(spec)}", "mask": f"~({' | '.join(held)})" if held else layer_key(spec),
                      "etch": {"depth": at - t, "into": ["device"],
                               "sidewall_deg": float(style.get("sidewall_deg", sidewall))},
                      "caption": f"Etch to the {_nm(t)} slab"})
        held.append(layer_key(spec))
        at = t
    if held:
        steps.append({"id": "etch_device", "mask": f"~({' | '.join(held)})",
                      "etch": {"depth": thick, "into": ["device"], "sidewall_deg": sidewall},
                      "caption": f"Etch the {_nm(thick)} device layer through"})
    for spec, style in device:
        if _polarity(style) == "etch" and on_cut(spec):
            steps.append({"id": f"trench_{layer_key(spec)}", "mask": layer_key(spec),
                          "etch": {"depth": float(style["thickness"]), "into": ["device"],
                                   "sidewall_deg": float(style.get("sidewall_deg", sidewall))},
                          "caption": f"Etch the {style.get('name', layer_key(spec))} trench"})

    # an etch that ends at the top of the wafer or under it is etched before the fill, into every wafer band its
    # z band reaches; one that reaches up into the fill is cut through the finished stack
    films = [band["name"] for band in bands if band["name"] not in ("handle", "box", "device")]
    cuts = []
    for spec, style in etches:
        if not on_cut(spec):
            continue
        z0, name = float(style["zmin"]), str(style.get("name") or layer_key(spec))
        if _top(style) <= bottom + _EPS:
            continue                 # air under the core (an undercut in the BOX): no etch from above reaches it
        step = {"id": f"cut_{layer_key(spec)}", "mask": layer_key(spec),
                "etch": {"to_z": z0, "into": [band["name"] for band in bands if band["z1"] > z0 + _EPS],
                         "sidewall_deg": float(style.get("sidewall_deg", sidewall))},
                "caption": f"Etch {name} to {_nm(z0)}"}
        if _top(style) <= surface + _EPS:
            steps.append(step)
        else:
            step["etch"]["into"] = ["oxide", "passivation", "device", "box", "handle", *films]
            step["etch"]["sidewall_deg"] = float(style.get("sidewall_deg", 90.0))
            cuts.append(step)

    # 2. implants: a marker band inside the core dopes it through, under the mask
    implants = [(spec, style) for spec, style in layers if (spec, style) not in device and _material(style) == core
                and _z0(style) > bottom + _EPS and _top(style) <= top + _EPS]
    for spec, style in implants:
        if not on_cut(spec):
            continue
        name = str(style.get("name") or layer_key(spec))
        steps.append({"id": f"implant_{layer_key(spec)}", "mask": layer_key(spec),
                      "implant": {"species": name, "into": ["device"]}, "caption": f"{doping_label(name)} implant"})

    # 3. growth, films in the oxide, then vias and metal, each in the order of its height
    rest = [(spec, style) for spec, style in layers
            if (spec, style) not in device and (spec, style) not in implants and on_cut(spec)]

    def stage(item) -> int:
        _, style = item
        if _material(style) == "germanium":
            return 0
        if not is_metal(_material(style)) and _role(style) not in _WIRED:
            return 1
        return 2

    oxide_top: float | None = None

    def oxide_to(z: float) -> None:
        nonlocal oxide_top
        if oxide_top is None or z > oxide_top + _EPS:
            steps.append({"id": f"oxide_to_{len(steps)}", "fill": {"material": "oxide", "to_z": z, "material_key": fill},
                          "caption": f"{word[:1].upper()}{word[1:]} to {_nm(z)} and CMP"})
            oxide_top = z

    pads = []
    film_tops: list[float] = []
    for spec, style in sorted(rest, key=lambda item: (stage(item), float(item[1]["zmin"]))):
        key, name, material = layer_key(spec), str(style.get("name") or layer_key(spec)), _material(style)
        z0 = float(style["zmin"])
        z1 = z0 + float(style["thickness"])
        if stage((spec, style)) == 0:
            steps.append({"id": f"grow_{key}", "mask": key,
                          "deposit": {"material": name, "material_key": material, "thickness": z1 - z0,
                                      "conformality": 0.0, "on": ["device"]},
                          "caption": f"{name} growth on {core.replace('_', ' ')}"})
        elif _is_via(style):
            oxide_to(z1)
            steps.append({"id": f"open_{key}", "mask": key,
                          "etch": {"depth": z1 - z0, "into": ["oxide"], "sidewall_deg": float(style.get("sidewall_deg", 90.0))},
                          "caption": f"Open the {name} holes"})
            steps.append({"id": f"fill_{key}", "fill": {"material": name, "to_z": z1, "material_key": material},
                          "caption": f"{name} fill and CMP"})
        else:
            oxide_to(z0)
            steps.append({"id": f"film_{key}", "deposit": {"material": name, "material_key": material,
                                                            "thickness": z1 - z0, "conformality": 0.0},
                          "caption": f"{name} deposit, {_nm(z1 - z0)}"})
            steps.append({"id": f"pattern_{key}", "mask": f"~{key}",
                          "etch": {"through": True, "into": [name], "sidewall_deg": float(style.get("sidewall_deg", 90.0))},
                          "caption": f"Pattern {name}"})
            film_tops.append(z1)
            if str(style.get("role") or "").lower() == "pad":
                pads.append((key, name))

    # 4. the top cladding: conformal over what stands up, flat when the stack says so. A fill that ends at the top
    # of the wafer or under it has nothing to stand over: it is flat
    cladding = wafer.fill.top
    if oxide_top is None or cladding > oxide_top + _EPS:
        if wafer.fill.planarized or cladding <= surface + _EPS:
            oxide_to(cladding)
        else:
            base = oxide_top if oxide_top is not None else 0.0     # the stack measures the cladding from z = 0
            steps.append({"id": "cladding", "deposit": {"material": "oxide", "material_key": fill,
                                                         "thickness": cladding - base, "conformality": 1.0},
                          "caption": f"Top {word}, {_nm(cladding - base)}"})

    # 5. the cover over the top metal, and the pad openings etched through it. A passivation of the fill's own
    # material is the last oxide level, so the dielectric is one body: round a metal that stands above the oxide
    # it is filled and planarised as every level below, to the metal's top plus its thickness; over a cladding
    # that already buries the metal it goes on as the cladding did. A passivation of another material is a film
    # of its own, on an oxide filled flush with the top metal. The pad opening is an etch through the cover,
    # down to the pads: on the stack's pad-opening layer (gdsfactory's PADOPEN) with its sidewall when the stack
    # names one, else over the whole pad. It goes no deeper than the cover where no pad lies under it
    passivation = float(stack.oxide.get("passivation", 0.0))
    if passivation > 0:
        material = (stack.passivation_material or "silicon_nitride").lower()
        flat = max(oxide_top or 0.0, cladding)
        peak = max([flat] + film_tops)
        if canonical(material) == canonical(fill) and peak > flat + _EPS:
            oxide_to(peak + passivation)
            cover = ["oxide"]
        elif canonical(material) == canonical(fill):
            steps.append({"id": "cover", "deposit": {"material": "oxide", "material_key": fill,
                                                      "thickness": passivation, "conformality": 1.0},
                          "caption": f"Top {word}, {_nm(passivation)} more"})
            cover = ["oxide"]
        else:
            oxide_to(peak)
            steps.append({"id": "passivation", "deposit": {"material": "passivation", "material_key": material,
                                                            "thickness": passivation, "conformality": 1.0},
                          "caption": f"Passivation, {_nm(passivation)}"})
            cover = ["passivation", "oxide"]
        opens = [(spec, style) for spec, style in stack.styles.items()
                 if str(style.get("role") or "").lower() == "pad_open"]
        if opens:
            for spec, style in opens:
                if on_cut(spec) and pads:
                    steps.append({"id": f"open_pad_{layer_key(spec)}", "mask": layer_key(spec),
                                  "etch": {"stop_on": [name for _, name in pads], "depth": passivation, "into": cover,
                                           "sidewall_deg": float(style.get("sidewall_deg", 90.0))},
                                  "caption": f"Open the pads ({style.get('name') or layer_key(spec)})"})
        else:
            for key, name in pads:
                steps.append({"id": f"open_pad_{key}", "mask": key,
                              "etch": {"stop_on": [name], "depth": passivation, "into": cover},
                              "caption": f"Open the {name} pads"})

    steps.extend(cuts)                                          # the openings, through the finished stack

    data = {
        "name": stack.name or "stack",
        "units": "um",
        "wafer": bands,
        "fill_material": fill,
        "layout_layers": {layer_key(spec): {"gds": [int(spec[0]), int(spec[1])]} for spec, _ in layers},
        "process": steps,
        "output_layers": [],
        "render": {"y_margin_um": 0.0},
    }
    return ProcessDefinition.from_mapping(data)
