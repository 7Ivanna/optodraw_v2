"""Find the faults between a GDS file and a layer stack that would otherwise render silently.

A layer the stack does not name still renders, at a made-up height; a stack written in nanometres
renders a thousand times too thick; a datatype that differs by one makes a layer fall back; a material
the table does not know draws grey. None of these stops a render, so :func:`check_stack` names each one
before you render.
"""

from __future__ import annotations

import warnings
from os import PathLike
from pathlib import Path

from optodraw.gds.palette import canonical, is_known
from optodraw.gds.parsers import BUNDLED_STACKS, LayerStackSpec, _load_yaml_file, load_layer_stack, stack_wafer

# GDSModel reads these layers as the die outline, whatever the stack calls them.
FLOORPLAN_LAYERS = frozenset({(99, 0), (290, 0)})
_EPS = 1e-6


def unknown_material(material: str, where: str) -> str:
    """The finding for a material that neither the table nor the stack knows. A section check says the same."""

    return (f"material {material!r} ({where}) is not in the material table: it draws grey; name a known material "
            "or add it under materials:")


def _wafer_findings(spec: LayerStackSpec) -> list[str]:
    """Materials that neither the table nor the stack knows, two core films, core layers of two materials, and a
    core that does not start at z = 0, where the films under it end."""

    findings = []
    placed = {key: style for key, style in spec.styles.items() if style.get("visible") is not False}
    for (layer, datatype), style in sorted(placed.items()):
        material = style.get("material_preset")
        if material and not is_known(material, spec.materials):
            name = style.get("name") or f"{layer}/{datatype}"
            findings.append(unknown_material(str(material), f"layer {layer}/{datatype}, region {name}"))
    wafer = stack_wafer(spec)
    parts = [(wafer.substrate, "substrate"), *((film, f"film {film.name}") for film in wafer.films), (wafer.fill, "fill")]
    findings += [unknown_material(part.material, where) for part, where in parts
                 if not is_known(part.material, spec.materials)]

    core_films = [film.name for film in wafer.films if film.role == "core"]
    if len(core_films) > 1:
        findings.append(f"{len(core_films)} films have role: core ({', '.join(core_films)}): one film is the core")
    bands = [(float(s["zmin"]), float(s["zmin"]) + float(s["thickness"]), canonical(s.get("material_preset") or "silicon"),
              str(s.get("role") or "").lower()) for s in placed.values()
             if s.get("zmin") is not None and s.get("thickness") is not None]
    core = [band for band in bands if band[3] == "core" and band[2] != "air"]
    materials = sorted({band[2] for band in core})
    if len(materials) > 1:
        findings.append(f"the core layers are of {len(materials)} materials ({', '.join(materials)}): a core has one")
    elif core and not core_films:
        low, high = min(band[0] for band in core), max(band[1] for band in core)
        bottom = min(z0 for z0, z1, material, _ in bands      # the core's material that touches the core band
                     if material == materials[0] and z1 >= low - _EPS and z0 <= high + _EPS)
        if abs(bottom) > _EPS:
            findings.append(f"the core starts at z = {bottom:g} um, but the films under it end at z = 0: they do "
                            "not touch; z = 0 is the bottom of the core")
    return findings


def check_stack(gds: str | PathLike[str], stack: str | PathLike[str], *, cell_name: str | None = None) -> list[str]:
    """Return one sentence for each fault between ``gds`` and ``stack``; an empty list when they agree.

    ``stack`` is a layer-stack YAML path or the name of a bundled stack (``"gdsfactory_generic"``).
    """

    import gdstk

    from optodraw.gds.layout import load_gds_layout

    findings: list[str] = []
    tops = [cell.name for cell in gdstk.read_gds(str(gds)).top_level() if not cell.name.startswith("$$$")]
    if cell_name is None and len(tops) > 1:
        findings.append(f"several top cells {tops}: pass cell_name")

    spec = load_layer_stack(stack)
    findings += [f"stack: {warning}" for warning in spec.warnings]
    if spec.oxide_source != "explicit":
        findings.append(f"oxide is {spec.oxide_source}, not explicit: add an oxide block, or a top under fill:")
    findings += _wafer_findings(spec)
    stack_path = Path(stack) if Path(stack).is_file() else BUNDLED_STACKS / f"{stack}.yaml"
    raw = _load_yaml_file(stack_path)
    written = raw.get("layers", {}) if isinstance(raw, dict) else {}
    if isinstance(written, dict) and len(written) != len(spec.styles):
        findings.append(f"{len(written)} layers in the file, {len(spec.styles)} understood")
    top = float(spec.oxide.get("cladding_top", 0.0))
    for key, style in sorted(spec.styles.items()):
        thickness = style.get("thickness")
        if thickness is not None and float(thickness) > 20:
            findings.append(f"{key} is {float(thickness):g} um thick: a stack in nm needs units: nm")

    with warnings.catch_warnings():  # the load warns about undeclared layers; they are findings here
        warnings.simplefilter("ignore", UserWarning)
        layout = load_gds_layout(str(gds), cell_name=cell_name, layer_styles=spec.styles)
    drawn = set(layout.summary()["layer_specs"])
    for key in sorted(drawn - set(spec.styles)):
        same = sorted(k for k in spec.styles if k[0] == key[0])
        hint = f" (the stack has {same}: a datatype mismatch?)" if same else ""
        findings.append(f"{key} is drawn but not in the stack: it renders as a fallback slab{hint}")
    solids = {key: (float(s["zmin"]), float(s["zmin"]) + float(s.get("thickness") or 0.0))
              for key, s in spec.styles.items()
              if key in drawn and s.get("visible") is not False and s.get("material_preset") != "air"
              and s.get("zmin") is not None}
    for key, (zmin, _) in sorted(solids.items()):
        reach = top                     # how high the oxide and the drawn layers under this one reach
        for bottom, upper in sorted(span for other, span in solids.items() if other != key):
            if bottom <= reach + 1e-6:
                reach = max(reach, upper)
        if zmin > reach + 1e-6:
            findings.append(f"{key} starts at z = {zmin:g} um, above the oxide top at {top:g} um with no "
                            "drawn layer under it: it floats over a gap; raise the top oxide or lower the layer")
    for key in sorted(drawn & FLOORPLAN_LAYERS):
        findings.append(f"{key} is read as the die outline: keep real geometry off it")
    return findings
