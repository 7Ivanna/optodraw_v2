"""KLayout technologies as optodraw layer stacks.

A KLayout technology file (.lyt) holds no layer colours and no heights: it names a layer-properties file (.lyp)
for the colours and names, and holds the database unit, reader and writer options and connectivity. KLayout's
2.5D heights live in a d25 script (.lyd25) beside it, usually in a ``d25`` folder: lines such as
``z(metal1, zstart: 1.1, zstop: 1.8, name: 'metal1: Aluminum 41/0')``. Only a z() of a plain input layer gives a
height; a layer the script builds with boolean operations has no single GDS layer and is skipped, and said so.
A d25 name of the form ``'<name>: <material> <L/D>'`` gives the layer's material. Nothing is guessed.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from os import PathLike
from pathlib import Path
from typing import Any

from optodraw.gds.parsers import LayerSpec, LayerStackSpec, _derive_oxide, material_preset_from_name, parse_klayout_lyp

_NUMBER = r"(-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)"
_INPUT = re.compile(r"input\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)")
_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$", re.M)
_Z = re.compile(r"\bz\(\s*(.*?)\s*\)\s*$", re.M)


def _script_text(path: Path) -> str:
    """The d25 script: the <text> of a KLayout macro file (entities decoded), or the file itself."""

    raw = path.read_text(encoding="utf-8")
    if raw.lstrip().startswith("<?xml") or raw.lstrip().startswith("<klayout-macro"):
        text = ET.fromstring(raw).findtext("text")
        return text or ""
    return raw


def _option(args: str, key: str) -> float | None:
    match = re.search(rf"\b{key}\s*:\s*{_NUMBER}", args)
    return float(match.group(1)) if match else None


def parse_lyd25(path: str | PathLike[str]) -> tuple[dict[LayerSpec, dict[str, Any]], list[str]]:
    """The heights a KLayout d25 script gives its plain input layers, and what it skipped."""

    script = _script_text(Path(path))
    inputs: dict[str, LayerSpec] = {}
    for name, value in _ASSIGN.findall(script):
        match = _INPUT.fullmatch(value.strip())
        if match:
            inputs[name] = (int(match.group(1)), int(match.group(2) or 0))
    found: dict[LayerSpec, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    for args in _Z.findall(script):
        inline = _INPUT.match(args) if args.startswith("input") else None      # z(input(L, D), ...) names it inline
        first = inline.group(0) if inline else args.split(",", 1)[0].strip()
        spec = (int(inline.group(1)), int(inline.group(2) or 0)) if inline else inputs.get(first)
        if spec is None:
            warnings.append(f"{first}: built by the script from other layers, so it has no single GDS layer; skipped")
            continue
        zstart, zstop, height = _option(args, "zstart"), _option(args, "zstop"), _option(args, "height")
        if zstart is None or (zstop is None and height is None):
            warnings.append(f"{first}: a z() with no zstart and zstop (or height); skipped")
            continue
        top = zstop if zstop is not None else zstart + height
        style: dict[str, Any] = {"zmin": min(zstart, top), "thickness": abs(top - zstart),
                                 "style_source": "klayout-lyd25"}
        label = re.search(r"\bname\s*:\s*['\"]([^'\"]*)['\"]", args)
        if label:
            head, _, rest = label.group(1).partition(":")
            style["name"] = head.strip() or first
            material = material_preset_from_name(rest.split()[0]) if rest.split() else None
            if material:
                style["material_preset"] = material
        found.setdefault(spec, []).append(style)
    styles: dict[LayerSpec, dict[str, Any]] = {}
    for spec, entries in found.items():
        ranges = {(round(e["zmin"], 9), round(e["thickness"], 9)) for e in entries}
        if len(ranges) > 1:
            warnings.append(f"{spec[0]}/{spec[1]}: {len(entries)} different z ranges (a placeholder layer); skipped")
            continue
        styles[spec] = entries[0]
    return styles, warnings


def load_klayout_technology(path: str | PathLike[str], *, lyd25: str | PathLike[str] | None = None) -> LayerStackSpec:
    """A layer stack from a KLayout technology: a .lyt (the colours and names of the .lyp it names, the heights
    of ``lyd25`` or of the one d25 script in its ``d25`` folder), or a .lyd25 alone (heights only)."""

    path = Path(path)
    warnings: list[str] = []
    if path.suffix.lower() == ".lyd25":
        styles, warnings = parse_lyd25(path)
        name = path.stem
    else:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        name = (root.findtext("name") or "").strip() or path.stem
        base = Path((root.findtext("base-path") or "").strip() or path.parent)
        if not base.is_dir():
            base = path.parent
        lyp_name = (root.findtext("layer-properties_file") or "").strip()
        styles = {}
        if lyp_name:
            lyp = base / lyp_name
            if not lyp.is_file():
                raise FileNotFoundError(f"{path.name} names {lyp_name}, which is not beside it; keep the technology "
                                        f"folder together (the .lyt, {lyp_name}, and d25/*.lyd25 for heights)")
            styles = parse_klayout_lyp(lyp)
        else:
            warnings.append(f"{path.name} names no layer-properties file: no colours or names")
        scripts = [Path(lyd25)] if lyd25 is not None else sorted((base / "d25").glob("*.lyd25"))
        if len(scripts) == 1:
            heights, more = parse_lyd25(scripts[0])
            warnings += more
            for spec, height in heights.items():
                merged = {**styles.get(spec, {}), **{k: v for k, v in height.items() if k != "name"}}
                merged.setdefault("name", height.get("name", f"{spec[0]}/{spec[1]}"))
                merged["physical_stack_known"] = True
                styles[spec] = merged
        else:
            warnings.append(f"no heights: {'no d25 script' if not scripts else f'{len(scripts)} d25 scripts'} in "
                            f"{base / 'd25'}; pass lyd25= to choose one")
    oxide, source, guessed = _derive_oxide(styles)
    return LayerStackSpec(name=name, styles=styles, oxide=oxide, oxide_source=source, warnings=warnings + guessed)
